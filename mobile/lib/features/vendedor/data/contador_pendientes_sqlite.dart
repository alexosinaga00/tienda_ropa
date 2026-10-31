import 'package:flutter/foundation.dart';
import 'package:sqflite/sqflite.dart';

import '../../../core/sesion/contador_pendientes.dart';

/// Los estados de una operación que todavía necesita al personal: aún no se envió, se envió sin respuesta o el servidor
/// la dejó en conflicto. 'confirmada' y 'rechazada' son finales y no cuentan.
const estadosPendientes = <String>['registrada', 'enviada', 'en_conflicto'];

const _marcadores = '?, ?, ?';

/// Cuenta las operaciones pendientes en la base local. NUNCA lanza: los avisos de cerrar sesión y cambiar de tienda lo
/// usan, y un fallo al contar (sin plugin, base que no abre, etc.) no debe impedir cerrar sesión; se responde 0.
class ContadorPendientesSqlite implements ContadorPendientes {
  ContadorPendientesSqlite(this._baseLocal);

  /// Abre (o reutiliza) la base local. Se pide en cada consulta para que un fallo pasajero no quede pegado.
  final Future<Database> Function() _baseLocal;

  /// Las operaciones pendientes de ESE usuario en ESA empresa. Sin empresa o sin usuario no hay nada que contar.
  @override
  Future<int> pendientesDe({int? empresaId, int? usuarioId}) async {
    if (empresaId == null || usuarioId == null) return 0;
    return _contar(
      'empresa_id = ? AND usuario_id = ? AND estado IN ($_marcadores)',
      [empresaId, usuarioId, ...estadosPendientes],
    );
  }

  /// Las operaciones pendientes de OTROS usuarios de la misma empresa (las de ESTE usuario no cuentan).
  Future<int> pendientesDeOtros({required int empresaId, required int usuarioId}) {
    return _contar(
      'empresa_id = ? AND usuario_id <> ? AND estado IN ($_marcadores)',
      [empresaId, usuarioId, ...estadosPendientes],
    );
  }

  Future<int> _contar(String donde, List<Object?> argumentos) async {
    try {
      final db = await _baseLocal();
      final filas = await db.rawQuery('SELECT COUNT(*) AS n FROM operacion_pendiente WHERE $donde', argumentos);
      return (filas.first['n'] as int?) ?? 0;
    } catch (error) {
      // Solo el tipo: nunca datos de la base.
      debugPrint('contador_pendientes error=${error.runtimeType}');
      return 0;
    }
  }
}
