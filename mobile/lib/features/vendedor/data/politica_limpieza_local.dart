import 'package:flutter/foundation.dart';
import 'package:sqflite/sqflite.dart';

import '../../../core/utils/reloj.dart';
import '../models/paquete_sincronizacion.dart';
import 'contador_pendientes_sqlite.dart';

/// Cuánto tiempo se conserva en el teléfono el historial de operaciones ya resueltas (confirmadas o rechazadas).
const retencionOperacionesResueltas = Duration(days: 30);

/// Lo que pasó al intentar limpiar la base local al cerrar sesión.
class ResultadoLimpieza {
  const ResultadoLimpieza({required this.pendientes, required this.purgo});

  /// Operaciones de la persona que siguen sin resolverse (registradas, enviadas o en conflicto). Con alguna, no se borra nada.
  final int pendientes;

  /// Verdadero si se ejecutó la depuración (no había pendientes de la persona); falso si se omitió por tenerlas.
  final bool purgo;
}

/// Qué se limpia de la base local cuando alguien cierra sesión.
abstract interface class PoliticaLimpiezaLocal {
  Future<ResultadoLimpieza> alCerrarSesion({required int empresaId, required int usuarioId});
}

/// Reglas:
/// - El catálogo (productos, variantes, stock, sucursales, referencias) SIEMPRE se conserva: es lo que permite trabajar
///   sin conexión la próxima vez.
/// - Con operaciones pendientes de esa persona no se borra NADA (ni lo que ellas referencian: clientes, ventas, reservas).
/// - Sin pendientes de esa persona, en una sola transacción: (1) se borran SUS operaciones confirmadas o rechazadas de más
///   de [retencionOperacionesResueltas] con sus ventas, reservas y respuestas del servidor; (2) se borran los clientes de la
///   empresa creados en el teléfono (sin `servidor_id`) que ninguna venta ni reserva referencia.
/// - Jamás se tocan las operaciones de otro usuario ni los datos de otra empresa, aunque estén vencidos.
class PoliticaLimpiezaLocalSqlite implements PoliticaLimpiezaLocal {
  PoliticaLimpiezaLocalSqlite(this._db, this._reloj);

  final Database _db;
  final Reloj _reloj;

  @override
  Future<ResultadoLimpieza> alCerrarSesion({required int empresaId, required int usuarioId}) async {
    final pendientes = await _contarPendientes(empresaId, usuarioId);
    if (pendientes > 0) {
      debugPrint('limpieza_local omitida pendientes=$pendientes');
      return ResultadoLimpieza(pendientes: pendientes, purgo: false);
    }

    final limite = _reloj.ahora().subtract(retencionOperacionesResueltas);
    var operaciones = 0;
    var clientes = 0;
    await _db.transaction((txn) async {
      final resueltas = await txn.query(
        'operacion_pendiente',
        columns: ['operacion_id', 'resuelta_en', 'creada_en'],
        where: "empresa_id = ? AND usuario_id = ? AND estado IN ('confirmada', 'rechazada')",
        whereArgs: [empresaId, usuarioId],
      );
      final vencidas = <String>[
        for (final fila in resueltas)
          if (_esAnterior(leerFechaUtc(fila['resuelta_en']) ?? leerFechaUtc(fila['creada_en']), limite))
            fila['operacion_id']! as String,
      ];

      // Primero los hijos: las llaves foráneas de venta, reserva y resultado_sync apuntan a la operación.
      for (final id in vencidas) {
        await txn.rawDelete(
          'DELETE FROM venta_detalle WHERE venta_id IN (SELECT id FROM venta WHERE operacion_id = ?)',
          [id],
        );
        await txn.delete('venta', where: 'operacion_id = ?', whereArgs: [id]);
        await txn.rawDelete(
          'DELETE FROM reserva_detalle WHERE reserva_id IN (SELECT id FROM reserva WHERE operacion_id = ?)',
          [id],
        );
        await txn.delete('reserva', where: 'operacion_id = ?', whereArgs: [id]);
        await txn.delete('resultado_sync', where: 'operacion_id = ?', whereArgs: [id]);
        await txn.delete('operacion_pendiente', where: 'operacion_id = ?', whereArgs: [id]);
      }
      operaciones = vencidas.length;

      // Los clientes hechos en el teléfono que ya nadie usa (los que bajaron del servidor tienen `servidor_id` y se quedan).
      clientes = await txn.rawDelete(
        'DELETE FROM cliente_minimo WHERE empresa_id = ? AND servidor_id IS NULL '
        'AND NOT EXISTS (SELECT 1 FROM venta v WHERE v.cliente_minimo_id = cliente_minimo.id) '
        'AND NOT EXISTS (SELECT 1 FROM reserva r WHERE r.cliente_minimo_id = cliente_minimo.id)',
        [empresaId],
      );
    });
    // Solo conteos: nunca datos de las operaciones.
    debugPrint('limpieza_local fin operaciones=$operaciones clientes=$clientes');
    return const ResultadoLimpieza(pendientes: 0, purgo: true);
  }

  /// Una fecha ilegible (o ausente) nunca se considera vencida: ante la duda se conserva.
  bool _esAnterior(DateTime? fecha, DateTime limite) => fecha != null && fecha.isBefore(limite);

  Future<int> _contarPendientes(int empresaId, int usuarioId) async {
    final filas = await _db.rawQuery(
      'SELECT COUNT(*) AS n FROM operacion_pendiente WHERE empresa_id = ? AND usuario_id = ? AND estado IN (?, ?, ?)',
      [empresaId, usuarioId, ...estadosPendientes],
    );
    return (filas.first['n'] as int?) ?? 0;
  }
}
