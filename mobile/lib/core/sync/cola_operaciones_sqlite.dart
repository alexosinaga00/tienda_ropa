import 'dart:async';
import 'dart:convert';

import 'package:sqflite/sqflite.dart';

import '../../features/vendedor/models/paquete_sincronizacion.dart';
import '../utils/reloj.dart';
import 'cola_operaciones.dart';
import 'contrato_sync.dart';
import 'lineas_operacion.dart';
import 'operacion_pendiente.dart';

/// El servidor admite hasta 100 líneas por operación (`max_length=100` del contrato).
const _maxLineas = 100;

/// El servidor admite hasta 300 caracteres de observación en una reserva.
const _maxObservacion = 300;

final _formatoHora = RegExp(r'^([01]\d|2[0-3]):[0-5]\d$');

const _mensajeYaRegistrada = 'Esta operación ya estaba registrada.';

/// La cola de operaciones sobre SQLite (D13). Cada escritura va en UNA transacción: o queda todo o no queda nada.
///
/// - El `operacion_id` se guarda en minúscula (como lo manda y lo devuelve el servidor).
/// - Fechas en texto ISO-8601 UTC ([aIsoUtc]); dinero en centavos.
/// - El payload y las filas `venta`/`reserva` se escriben juntos y NO se editan después: reenviar es idéntico.
/// - Una operación NUNCA se borra aquí.
/// - [cambios] emite DESPUÉS de cada escritura confirmada (nunca tras un rollback).
class ColaOperacionesSqlite implements ColaOperaciones {
  ColaOperacionesSqlite(this._db, this._reloj);

  final Database _db;
  final Reloj _reloj;
  final StreamController<void> _cambios = StreamController<void>.broadcast();

  @override
  Stream<void> get cambios => _cambios.stream;

  /// Cierra el flujo de [cambios]. Llamar una sola vez, al soltar la cola.
  Future<void> dispose() => _cambios.close();

  void _avisar() {
    if (!_cambios.isClosed) _cambios.add(null);
  }

  // ---- Registro ----------------------------------------------------------------------------

  @override
  Future<void> registrarVenta(NuevaVenta venta) async {
    final id = _idNormalizado(venta.operacionId);
    _validarLineasVenta(venta.lineas);
    if (!venta.efectivoConfirmado) {
      throw const ColaError('Confirma que recibiste el efectivo para registrar la venta.');
    }
    final total = totalCentavosDe(venta.lineas);

    try {
      await _db.transaction((txn) async {
        await _verificarNueva(txn, id);
        await _verificarSucursal(txn, venta.empresaId, venta.sucursalId);
        await _verificarVariantes(txn, venta.empresaId, venta.lineas.map((l) => l.varianteId));
        final clienteServidorId = venta.clienteMinimoId == null
            ? null
            : await _clienteServidorId(txn, venta.empresaId, venta.clienteMinimoId!);

        final payload = jsonEncode(
          payloadVentaContado(clienteServidorId: clienteServidorId, lineas: venta.lineas, totalCentavos: total),
        );
        final fecha = aIsoUtc(venta.fechaOperacion);
        await _insertarOperacion(
          txn,
          id: id,
          empresaId: venta.empresaId,
          sucursalId: venta.sucursalId,
          usuarioId: venta.usuarioId,
          tipo: TipoOperacion.ventaContado,
          payload: payload,
          fechaOperacion: fecha,
        );
        final ventaId = await txn.insert('venta', {
          'operacion_id': id,
          'empresa_id': venta.empresaId,
          'sucursal_id': venta.sucursalId,
          'usuario_id': venta.usuarioId,
          'cliente_minimo_id': venta.clienteMinimoId,
          'fecha_operacion': fecha,
          'forma_pago': 'efectivo',
          'efectivo_confirmado': 1,
          'total_centavos': total,
        });
        for (final l in venta.lineas) {
          await txn.insert('venta_detalle', {
            'venta_id': ventaId,
            'variante_id': l.varianteId,
            'cantidad': l.cantidad,
            'precio_unitario_centavos': l.precioUnitarioCentavos,
          });
        }
      });
    } on DatabaseException catch (e) {
      throw _traducir(e);
    }
    _avisar();
  }

  @override
  Future<void> registrarReserva(NuevaReserva reserva) async {
    final id = _idNormalizado(reserva.operacionId);
    _validarLineasReserva(reserva.lineas);
    if (!_formatoHora.hasMatch(reserva.horaDesde) || !_formatoHora.hasMatch(reserva.horaHasta)) {
      throw const ColaError('Las horas de la visita deben tener el formato HH:mm.');
    }
    if (reserva.horaHasta.compareTo(reserva.horaDesde) <= 0) {
      throw const ColaError('La hora de fin de la visita debe ser posterior a la hora de inicio.');
    }
    // El día de la operación es el del teléfono (la hora local): una reserva de las 22:00 en Bolivia ya es del día siguiente
    // en UTC, y la visita de "hoy" no debe rechazarse por eso.
    final operacion = reserva.fechaOperacion.toLocal();
    final diaOperacion = DateTime(operacion.year, operacion.month, operacion.day);
    final diaVisita = DateTime(reserva.fechaVisita.year, reserva.fechaVisita.month, reserva.fechaVisita.day);
    if (diaVisita.isBefore(diaOperacion)) {
      throw const ColaError('La fecha de la visita no puede ser anterior al día de la reserva.');
    }
    final observacion = reserva.observacion?.trim();
    if (observacion != null && observacion.length > _maxObservacion) {
      throw const ColaError('La observación no puede pasar de $_maxObservacion caracteres.');
    }

    try {
      await _db.transaction((txn) async {
        await _verificarNueva(txn, id);
        await _verificarSucursal(txn, reserva.empresaId, reserva.sucursalId);
        await _verificarVariantes(txn, reserva.empresaId, reserva.lineas.map((l) => l.varianteId));
        final clienteServidorId = await _clienteServidorId(txn, reserva.empresaId, reserva.clienteMinimoId);

        final sobre = payloadReserva(
          clienteServidorId: clienteServidorId,
          fechaVisita: reserva.fechaVisita,
          horaDesde: reserva.horaDesde,
          horaHasta: reserva.horaHasta,
          observacion: observacion,
          lineas: reserva.lineas,
        );
        final fecha = aIsoUtc(reserva.fechaOperacion);
        await _insertarOperacion(
          txn,
          id: id,
          empresaId: reserva.empresaId,
          sucursalId: reserva.sucursalId,
          usuarioId: reserva.usuarioId,
          tipo: TipoOperacion.reserva,
          payload: jsonEncode(sobre),
          fechaOperacion: fecha,
        );
        final reservaId = await txn.insert('reserva', {
          'operacion_id': id,
          'empresa_id': reserva.empresaId,
          'sucursal_id': reserva.sucursalId,
          'usuario_id': reserva.usuarioId,
          'cliente_minimo_id': reserva.clienteMinimoId,
          'fecha_operacion': fecha,
          // La misma fecha "AAAA-MM-DD" que viaja en el payload.
          'fecha_visita': sobre['fecha_visita'],
          'hora_visita_desde': reserva.horaDesde,
          'hora_visita_hasta': reserva.horaHasta,
          'observacion': sobre['observacion'],
        });
        for (final l in reserva.lineas) {
          await txn.insert('reserva_detalle', {'reserva_id': reservaId, 'variante_id': l.varianteId, 'cantidad': l.cantidad});
        }
      });
    } on DatabaseException catch (e) {
      throw _traducir(e);
    }
    _avisar();
  }

  String _idNormalizado(String operacionId) {
    final id = operacionId.trim().toLowerCase();
    if (id.isEmpty) throw const ColaError('Falta el identificador de la operación.');
    return id;
  }

  void _validarLineasVenta(List<LineaVenta> lineas) {
    if (lineas.isEmpty) throw const ColaError('Agrega al menos una prenda a la venta.');
    if (lineas.length > _maxLineas) throw const ColaError('Una venta admite hasta $_maxLineas prendas.');
    for (final l in lineas) {
      if (l.cantidad <= 0) throw const ColaError('La cantidad de cada prenda debe ser mayor que cero.');
      if (l.precioUnitarioCentavos < 0) throw const ColaError('El precio de una prenda no puede ser negativo.');
      if (l.descuentoUnitarioCentavos < 0) throw const ColaError('El descuento de una prenda no puede ser negativo.');
      if (l.descuentoUnitarioCentavos > l.precioUnitarioCentavos) {
        throw const ColaError('El descuento de una prenda no puede ser mayor que su precio.');
      }
    }
  }

  void _validarLineasReserva(List<LineaReserva> lineas) {
    if (lineas.isEmpty) throw const ColaError('Agrega al menos una prenda a la reserva.');
    if (lineas.length > _maxLineas) throw const ColaError('Una reserva admite hasta $_maxLineas prendas.');
    for (final l in lineas) {
      if (l.cantidad <= 0) throw const ColaError('La cantidad de cada prenda debe ser mayor que cero.');
    }
  }

  /// El `operacion_id` ya existe: el doble toque (o un reintento) no duplica nada.
  Future<void> _verificarNueva(DatabaseExecutor txn, String id) async {
    final filas = await txn.query('operacion_pendiente', columns: ['operacion_id'], where: 'operacion_id = ?', whereArgs: [id]);
    if (filas.isNotEmpty) throw const ColaError(_mensajeYaRegistrada);
  }

  Future<void> _verificarSucursal(DatabaseExecutor txn, int empresaId, int sucursalId) async {
    final filas = await txn.query(
      'sucursal',
      columns: ['id'],
      where: 'id = ? AND empresa_id = ? AND activo = 1',
      whereArgs: [sucursalId, empresaId],
    );
    if (filas.isEmpty) {
      throw const ColaError('La sucursal no está disponible en este teléfono. Actualiza tus datos e intenta de nuevo.');
    }
  }

  /// Cada variante debe existir, estar activa (ella y su producto) y ser de la empresa.
  Future<void> _verificarVariantes(DatabaseExecutor txn, int empresaId, Iterable<int> varianteIds) async {
    final ids = varianteIds.toSet().toList();
    final filas = await txn.rawQuery(
      'SELECT v.id AS id FROM variante v JOIN producto p ON p.id = v.producto_id '
      'WHERE v.id IN (${_marcas(ids.length)}) AND v.activo = 1 AND p.activo = 1 AND p.empresa_id = ?',
      [...ids, empresaId],
    );
    if (filas.length != ids.length) {
      throw const ColaError('Una de las prendas ya no está disponible. Actualiza tus datos e intenta de nuevo.');
    }
  }

  /// El id del cliente en el SERVIDOR: sin conexión no se crean clientes, así que el cliente debe venir ya del servidor.
  Future<int> _clienteServidorId(DatabaseExecutor txn, int empresaId, int clienteMinimoId) async {
    final filas = await txn.query(
      'cliente_minimo',
      columns: ['servidor_id'],
      where: 'id = ? AND empresa_id = ?',
      whereArgs: [clienteMinimoId, empresaId],
    );
    if (filas.isEmpty) throw const ColaError('El cliente no existe en este teléfono. Elige otro cliente.');
    final servidorId = filas.first['servidor_id'] as int?;
    if (servidorId == null) {
      throw const ColaError('Este cliente todavía no está en el servidor. Actualiza tus datos o elige otro cliente.');
    }
    return servidorId;
  }

  Future<void> _insertarOperacion(
    DatabaseExecutor txn, {
    required String id,
    required int empresaId,
    required int sucursalId,
    required int usuarioId,
    required TipoOperacion tipo,
    required String payload,
    required String fechaOperacion,
  }) {
    return txn.insert('operacion_pendiente', {
      'operacion_id': id,
      'empresa_id': empresaId,
      'sucursal_id': sucursalId,
      'usuario_id': usuarioId,
      'tipo': tipo.nombre,
      'estado': EstadoOperacion.registrada.nombre,
      'payload': payload,
      'version_contrato': 1,
      'intentos': 0,
      'fecha_operacion': fechaOperacion,
      'creada_en': aIsoUtc(_reloj.ahora()),
    });
  }

  /// La llave única de `operacion_id` también cuenta como "ya registrada" (dos registros simultáneos con el mismo id).
  Exception _traducir(DatabaseException e) => e.isUniqueConstraintError() ? const ColaError(_mensajeYaRegistrada) : e;

  // ---- Lectura -----------------------------------------------------------------------------

  @override
  Future<List<OperacionPendiente>> listar({
    required int empresaId,
    required int usuarioId,
    Set<EstadoOperacion>? estados,
    TipoOperacion? tipo,
    int? limite,
    int desplazamiento = 0,
  }) async {
    if (limite != null && limite <= 0) return const [];
    final filtros = ['empresa_id = ?', 'usuario_id = ?'];
    final args = <Object?>[empresaId, usuarioId];
    // Un conjunto vacío equivale a "sin filtro": nadie pide "ningún estado".
    if (estados != null && estados.isNotEmpty) {
      filtros.add('estado IN (${_marcas(estados.length)})');
      args.addAll(estados.map((e) => e.nombre));
    }
    if (tipo != null) {
      filtros.add('tipo = ?');
      args.add(tipo.nombre);
    }
    final filas = await _db.rawQuery(
      'SELECT * FROM operacion_pendiente WHERE ${filtros.join(' AND ')} '
      'ORDER BY julianday(fecha_operacion) DESC, creada_en DESC, rowid DESC '
      'LIMIT ? OFFSET ?',
      [...args, limite ?? -1, desplazamiento < 0 ? 0 : desplazamiento],
    );
    return filas.map(_aOperacion).toList();
  }

  @override
  Future<OperacionPendiente?> obtener(String operacionId) async {
    final filas = await _db.query('operacion_pendiente', where: 'operacion_id = ?', whereArgs: [operacionId.trim().toLowerCase()]);
    return filas.isEmpty ? null : _aOperacion(filas.first);
  }

  @override
  Future<DetalleOperacion?> detalle(String operacionId) async {
    final operacion = await obtener(operacionId);
    if (operacion == null) return null;
    final id = operacion.operacionId;

    String? nombreCompleto(Object? nombre, Object? apellido) {
      final n = (nombre as String?)?.trim();
      if (n == null || n.isEmpty) return null;
      final a = (apellido as String?)?.trim();
      return a == null || a.isEmpty ? n : '$n $a';
    }

    if (operacion.tipo == TipoOperacion.ventaContado) {
      final cabecera = await _db.rawQuery(
        'SELECT ve.total_centavos AS total, ve.efectivo_confirmado AS efectivo, cm.nombre AS cliente_nombre, '
        'cm.apellido AS cliente_apellido, cm.servidor_id AS cliente_servidor_id '
        'FROM venta ve LEFT JOIN cliente_minimo cm ON cm.id = ve.cliente_minimo_id WHERE ve.operacion_id = ?',
        [id],
      );
      final lineas = await _db.rawQuery(
        '''
SELECT d.variante_id AS variante_id, d.cantidad AS cantidad, d.precio_unitario_centavos AS precio,
       p.nombre AS nombre, p.imagen_principal_url AS imagen, t.codigo AS talla, c.nombre AS color, v.sku AS sku
FROM venta_detalle d
JOIN venta ve ON ve.id = d.venta_id
LEFT JOIN variante v ON v.id = d.variante_id
LEFT JOIN producto p ON p.id = v.producto_id
LEFT JOIN talla t ON t.id = v.talla_id
LEFT JOIN color c ON c.id = v.color_id
WHERE ve.operacion_id = ?
ORDER BY d.id''',
        [id],
      );
      final c = cabecera.isEmpty ? null : cabecera.first;
      return DetalleOperacion(
        operacion: operacion,
        lineas: lineas.map(_aLineaDetalle).toList(),
        clienteNombre: c == null ? null : nombreCompleto(c['cliente_nombre'], c['cliente_apellido']),
        clienteServidorId: c?['cliente_servidor_id'] as int?,
        totalCentavos: c?['total'] as int?,
        efectivoConfirmado: c == null ? null : (c['efectivo'] as int?) == 1,
      );
    }

    final cabecera = await _db.rawQuery(
      'SELECT r.fecha_visita AS fecha_visita, r.hora_visita_desde AS desde, r.hora_visita_hasta AS hasta, '
      'r.observacion AS observacion, cm.nombre AS cliente_nombre, cm.apellido AS cliente_apellido, '
      'cm.servidor_id AS cliente_servidor_id '
      'FROM reserva r LEFT JOIN cliente_minimo cm ON cm.id = r.cliente_minimo_id WHERE r.operacion_id = ?',
      [id],
    );
    final lineas = await _db.rawQuery(
      '''
SELECT d.variante_id AS variante_id, d.cantidad AS cantidad, NULL AS precio,
       p.nombre AS nombre, p.imagen_principal_url AS imagen, t.codigo AS talla, c.nombre AS color, v.sku AS sku
FROM reserva_detalle d
JOIN reserva r ON r.id = d.reserva_id
LEFT JOIN variante v ON v.id = d.variante_id
LEFT JOIN producto p ON p.id = v.producto_id
LEFT JOIN talla t ON t.id = v.talla_id
LEFT JOIN color c ON c.id = v.color_id
WHERE r.operacion_id = ?
ORDER BY d.id''',
      [id],
    );
    final c = cabecera.isEmpty ? null : cabecera.first;
    return DetalleOperacion(
      operacion: operacion,
      lineas: lineas.map(_aLineaDetalle).toList(),
      clienteNombre: c == null ? null : nombreCompleto(c['cliente_nombre'], c['cliente_apellido']),
      clienteServidorId: c?['cliente_servidor_id'] as int?,
      fechaVisita: _soloFecha(c?['fecha_visita'] as String?),
      horaDesde: c?['desde'] as String?,
      horaHasta: c?['hasta'] as String?,
      observacion: c?['observacion'] as String?,
    );
  }

  @override
  Future<List<ResultadoLocal>> resultados(String operacionId) async {
    final filas = await _db.query(
      'resultado_sync',
      where: 'operacion_id = ?',
      whereArgs: [operacionId.trim().toLowerCase()],
      orderBy: 'id ASC',
    );
    return [
      for (final f in filas)
        ResultadoLocal(
          operacionId: f['operacion_id']! as String,
          recibidoEn: _fecha(f['recibido_en'] as String?) ?? _epoca,
          estadoResultado: f['estado_resultado']! as String,
          codigoMotivo: f['codigo_motivo'] as String?,
          motivo: f['motivo'] as String?,
          entidadServidorId: f['entidad_servidor_id'] as int?,
          detalleJson: f['detalle_json'] as String?,
        ),
    ];
  }

  @override
  Future<List<OperacionPendiente>> paraEnviar({
    required int empresaId,
    required int usuarioId,
    required DateTime ahora,
    bool ignorarEspera = false,
    int? limite,
  }) async {
    if (limite != null && limite <= 0) return const [];
    final filas = await _db.rawQuery(
      'SELECT * FROM operacion_pendiente '
      "WHERE empresa_id = ? AND usuario_id = ? AND estado IN ('registrada', 'enviada') "
      '${ignorarEspera ? '' : 'AND (proximo_reintento_en IS NULL OR julianday(proximo_reintento_en) <= julianday(?)) '}'
      'ORDER BY julianday(fecha_operacion) ASC, creada_en ASC, rowid ASC LIMIT ?',
      [empresaId, usuarioId, if (!ignorarEspera) aIsoUtc(ahora), limite ?? -1],
    );
    return filas.map(_aOperacion).toList();
  }

  @override
  Future<List<OperacionPendiente>> paraRevisarConflictos({required int empresaId, required int usuarioId}) async {
    final filas = await _db.rawQuery(
      "SELECT * FROM operacion_pendiente WHERE empresa_id = ? AND usuario_id = ? AND estado = 'en_conflicto' "
      'ORDER BY julianday(fecha_operacion) ASC, creada_en ASC, rowid ASC',
      [empresaId, usuarioId],
    );
    return filas.map(_aOperacion).toList();
  }

  @override
  Future<Map<EstadoOperacion, int>> conteoPorEstado({required int empresaId, required int usuarioId}) async {
    final filas = await _db.rawQuery(
      'SELECT estado, COUNT(*) AS n FROM operacion_pendiente WHERE empresa_id = ? AND usuario_id = ? GROUP BY estado',
      [empresaId, usuarioId],
    );
    final conteo = {for (final e in EstadoOperacion.values) e: 0};
    for (final f in filas) {
      final estado = EstadoOperacion.desdeNombre(f['estado'] as String?);
      if (estado != null) conteo[estado] = f['n']! as int;
    }
    return conteo;
  }

  // ---- Estado ------------------------------------------------------------------------------

  @override
  Future<void> marcarEnviadas(List<String> operacionIds) async {
    final ids = _ids(operacionIds);
    if (ids.isEmpty) return;
    var cambio = false;
    await _db.transaction((txn) async {
      for (final id in ids) {
        final n = await txn.rawUpdate(
          "UPDATE operacion_pendiente SET estado = 'enviada', intentos = intentos + 1, proximo_reintento_en = NULL "
          "WHERE operacion_id = ? AND estado IN ('registrada', 'enviada')",
          [id],
        );
        if (n > 0) cambio = true;
      }
    });
    if (cambio) _avisar();
  }

  @override
  Future<void> volverARegistrada(
    List<String> operacionIds, {
    String? error,
    DateTime? proximoReintento,
    bool devolverIntento = false,
  }) async {
    final ids = _ids(operacionIds);
    if (ids.isEmpty) return;
    var cambio = false;
    await _db.transaction((txn) async {
      for (final id in ids) {
        final n = await txn.rawUpdate(
          "UPDATE operacion_pendiente SET estado = 'registrada', ultimo_error = ?, proximo_reintento_en = ?, "
          'intentos = CASE WHEN ? = 1 THEN MAX(0, intentos - 1) ELSE intentos END '
          "WHERE operacion_id = ? AND estado = 'enviada'",
          [error, proximoReintento == null ? null : aIsoUtc(proximoReintento), devolverIntento ? 1 : 0, id],
        );
        if (n > 0) cambio = true;
      }
    });
    if (cambio) _avisar();
  }

  @override
  Future<void> registrarFalloDeRed(List<String> operacionIds, {required String error, required DateTime proximoReintento}) async {
    final ids = _ids(operacionIds);
    if (ids.isEmpty) return;
    var cambio = false;
    await _db.transaction((txn) async {
      for (final id in ids) {
        final n = await txn.rawUpdate(
          'UPDATE operacion_pendiente SET ultimo_error = ?, proximo_reintento_en = ? '
          "WHERE operacion_id = ? AND estado IN ('registrada', 'enviada')",
          [error, aIsoUtc(proximoReintento), id],
        );
        if (n > 0) cambio = true;
      }
    });
    if (cambio) _avisar();
  }

  @override
  Future<List<String>> aplicarResultados(List<ResultadoOperacionSync> resultados, {required DateTime recibidoEn}) async {
    if (resultados.isEmpty) return const [];
    final cambiaron = <String>[];
    var hubo = false;
    final recibido = aIsoUtc(recibidoEn);

    await _db.transaction((txn) async {
      for (final r in resultados) {
        final id = r.operacionId.trim().toLowerCase();
        if (id.isEmpty) continue;
        final filas = await txn.query('operacion_pendiente', columns: ['estado'], where: 'operacion_id = ?', whereArgs: [id]);
        if (filas.isEmpty) continue;
        final actual = EstadoOperacion.desdeNombre(filas.first['estado'] as String?);
        if (actual == null) continue;

        final texto = _textoONulo(r.mensaje) ?? _textoONulo(r.motivo);
        final destino = r.estado.aEstadoLocal;

        if (destino == null) {
          // error_temporal o un estado que la app no conoce: el estado no cambia (se reintenta con el mismo id) y no se guarda
          // como respuesta. Solo se anota qué pasó, salvo que la operación ya haya terminado.
          if (actual.esFinal) continue;
          await txn.update(
            'operacion_pendiente',
            {
              'ultimo_error':
                  texto ??
                  (r.estado == EstadoResultadoSync.errorTemporal
                      ? 'El servidor no pudo procesarla ahora. Se reintentará.'
                      : 'El servidor respondió algo que la app no entiende.'),
            },
            where: 'operacion_id = ?',
            whereArgs: [id],
          );
          hubo = true;
          continue;
        }

        // Solo transiciones válidas: una final no retrocede y una respuesta repetida del mismo estado no cambia nada.
        if (!actual.puedePasarA(destino)) continue;

        await txn.update(
          'operacion_pendiente',
          {
            'estado': destino.nombre,
            'ultimo_error': destino == EstadoOperacion.confirmada ? null : texto,
            // La hora del SERVIDOR; si no la mandó, la de recepción. En conflicto aún no hay resolución.
            'resuelta_en': destino.esFinal ? aIsoUtc(r.procesadaEn ?? recibidoEn) : null,
            'proximo_reintento_en': null,
          },
          where: 'operacion_id = ?',
          whereArgs: [id],
        );
        await txn.insert('resultado_sync', {
          'operacion_id': id,
          'recibido_en': recibido,
          'estado_resultado': r.estado.nombre,
          'codigo_motivo': r.motivo,
          'motivo': r.mensaje,
          'entidad_servidor_id': r.recurso?.id,
          'detalle_json': _detalleJson(r),
        });
        cambiaron.add(id);
        hubo = true;
      }
    });
    if (hubo) _avisar();
    return cambiaron;
  }

  @override
  Future<void> marcarRechazadaLocal(String operacionId, {required String motivo, required DateTime recibidoEn}) async {
    final id = operacionId.trim().toLowerCase();
    var cambio = false;
    await _db.transaction((txn) async {
      final recibido = aIsoUtc(recibidoEn);
      final n = await txn.rawUpdate(
        "UPDATE operacion_pendiente SET estado = 'rechazada', ultimo_error = ?, resuelta_en = ?, proximo_reintento_en = NULL "
        "WHERE operacion_id = ? AND estado IN ('registrada', 'enviada')",
        [motivo, recibido, id],
      );
      if (n == 0) return;
      await txn.insert('resultado_sync', {
        'operacion_id': id,
        'recibido_en': recibido,
        'estado_resultado': EstadoOperacion.rechazada.nombre,
        'codigo_motivo': codigoRechazoLocal,
        'motivo': motivo,
      });
      cambio = true;
    });
    if (cambio) _avisar();
  }

  // ---- Apoyo -------------------------------------------------------------------------------

  /// El `detalle_json` de una respuesta: lo que la pantalla de resultado necesita. Los montos van en CENTAVOS (enteros).
  /// Claves: `recurso` {tipo, id, codigo, total_centavos}, `cambio_centavos`, `duplicada`, `avisos` [{variante_id,
  /// precio_operacion_centavos, precio_actual_centavos}], `faltantes` [{variante_id, solicitado, disponible}] y `resolucion`
  /// {accion, motivo}. Sin nada que contar, es null.
  String? _detalleJson(ResultadoOperacionSync r) {
    final mapa = <String, Object?>{
      if (r.recurso != null)
        'recurso': {
          'tipo': r.recurso!.tipo,
          'id': r.recurso!.id,
          'codigo': r.recurso!.codigo,
          if (r.recurso!.totalCentavos != null) 'total_centavos': r.recurso!.totalCentavos,
        },
      'cambio_centavos': ?r.cambioCentavos,
      if (r.duplicada) 'duplicada': true,
      if (r.avisos.isNotEmpty)
        'avisos': [
          for (final a in r.avisos)
            {
              'variante_id': a.varianteId,
              'precio_operacion_centavos': a.precioOperacionCentavos,
              'precio_actual_centavos': a.precioActualCentavos,
            },
        ],
      if (r.faltantes.isNotEmpty)
        'faltantes': [
          for (final f in r.faltantes) {'variante_id': f.varianteId, 'solicitado': f.solicitado, 'disponible': f.disponible},
        ],
      if (r.resolucion != null) 'resolucion': {'accion': r.resolucion!.accion, 'motivo': ?r.resolucion!.motivo},
    };
    return mapa.isEmpty ? null : jsonEncode(mapa);
  }

  List<String> _ids(List<String> ids) =>
      {for (final id in ids) id.trim().toLowerCase()}.where((id) => id.isNotEmpty).toList();

  String? _textoONulo(String? s) {
    final t = s?.trim();
    return t == null || t.isEmpty ? null : t;
  }

  String _marcas(int n) => List.filled(n, '?').join(', ');
}

/// El código de motivo que se guarda cuando la rechaza el propio teléfono (el servidor devolvió un 4xx para esa operación).
const codigoRechazoLocal = 'rechazo_local';

final _epoca = DateTime.fromMillisecondsSinceEpoch(0, isUtc: true);

DateTime? _fecha(String? iso) => leerFechaUtc(iso);

/// "AAAA-MM-DD" a un día sin hora (a medianoche local, para que sus componentes no cambien).
DateTime? _soloFecha(String? texto) {
  if (texto == null) return null;
  final partes = texto.split('-');
  if (partes.length != 3) return null;
  final y = int.tryParse(partes[0]);
  final m = int.tryParse(partes[1]);
  final d = int.tryParse(partes[2]);
  if (y == null || m == null || d == null) return null;
  return DateTime(y, m, d);
}

LineaDetalle _aLineaDetalle(Map<String, Object?> f) {
  final varianteId = f['variante_id']! as int;
  final nombre = (f['nombre'] as String?)?.trim();
  return LineaDetalle(
    varianteId: varianteId,
    cantidad: f['cantidad']! as int,
    // Una variante que ya no estuviera en el catálogo local no rompe la pantalla.
    nombre: nombre == null || nombre.isEmpty ? 'Prenda #$varianteId' : nombre,
    talla: f['talla'] as String?,
    color: f['color'] as String?,
    sku: f['sku'] as String?,
    imagenUrl: f['imagen'] as String?,
    precioUnitarioCentavos: f['precio'] as int?,
  );
}

OperacionPendiente _aOperacion(Map<String, Object?> f) => OperacionPendiente(
  operacionId: f['operacion_id']! as String,
  empresaId: f['empresa_id']! as int,
  sucursalId: f['sucursal_id']! as int,
  usuarioId: f['usuario_id']! as int,
  tipo: TipoOperacion.desdeNombre(f['tipo'] as String?) ?? TipoOperacion.ventaContado,
  estado: EstadoOperacion.desdeNombre(f['estado'] as String?) ?? EstadoOperacion.registrada,
  payload: f['payload']! as String,
  versionContrato: f['version_contrato']! as int,
  intentos: f['intentos']! as int,
  ultimoError: f['ultimo_error'] as String?,
  proximoReintentoEn: _fecha(f['proximo_reintento_en'] as String?),
  fechaOperacion: _fecha(f['fecha_operacion'] as String?) ?? _epoca,
  creadaEn: _fecha(f['creada_en'] as String?) ?? _epoca,
  resueltaEn: _fecha(f['resuelta_en'] as String?),
);
