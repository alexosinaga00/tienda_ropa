import 'dart:async';
import 'dart:convert';

import 'package:mobile/core/sync/cola_operaciones.dart';
import 'package:mobile/core/utils/dinero.dart';
import 'package:mobile/core/sync/contrato_sync.dart';
import 'package:mobile/core/sync/lineas_operacion.dart';
import 'package:mobile/core/sync/operacion_pendiente.dart';

/// Una llamada que recibió la [ColaFalsa]: el nombre del método y los ids de operación que tocó.
class LlamadaCola {
  const LlamadaCola(this.metodo, [this.ids = const [], this.detalle = const {}]);

  final String metodo;
  final List<String> ids;

  /// Los demás argumentos (error, proximoReintento, devolverIntento, motivo...).
  final Map<String, Object?> detalle;

  @override
  String toString() => '$metodo(${ids.join(',')}${detalle.isEmpty ? '' : ' $detalle'})';
}

/// Una [OperacionPendiente] de ejemplo (venta de una línea por defecto) para sembrar en la [ColaFalsa].
OperacionPendiente operacionDePrueba(
  String id, {
  int empresaId = 1,
  int sucursalId = 1,
  int usuarioId = 10,
  TipoOperacion tipo = TipoOperacion.ventaContado,
  EstadoOperacion estado = EstadoOperacion.registrada,
  DateTime? fechaOperacion,
  DateTime? creadaEn,
  int intentos = 0,
  String? ultimoError,
  DateTime? proximoReintentoEn,
  DateTime? resueltaEn,
  String? payload,
}) {
  final fecha = fechaOperacion ?? DateTime.utc(2026, 10, 31, 9);
  return OperacionPendiente(
    operacionId: id,
    empresaId: empresaId,
    sucursalId: sucursalId,
    usuarioId: usuarioId,
    tipo: tipo,
    estado: estado,
    payload:
        payload ??
        jsonEncode(
          tipo == TipoOperacion.ventaContado
              ? payloadVentaContado(
                  lineas: const [LineaVenta(varianteId: 5, cantidad: 1, precioUnitarioCentavos: 7500)],
                  totalCentavos: 7500,
                )
              : payloadReserva(
                  clienteServidorId: 3,
                  fechaVisita: DateTime.utc(2026, 11, 2),
                  horaDesde: '10:00',
                  horaHasta: '11:00',
                  lineas: const [LineaReserva(varianteId: 5, cantidad: 1)],
                ),
        ),
    versionContrato: 1,
    intentos: intentos,
    fechaOperacion: fecha,
    creadaEn: creadaEn ?? fecha,
    ultimoError: ultimoError,
    proximoReintentoEn: proximoReintentoEn,
    resueltaEn: resueltaEn,
  );
}

/// La cola en MEMORIA, fiel a las reglas de [ColaOperaciones]. Las pruebas de motor, controladores y pantallas la usan en
/// lugar de SQLite. Todo lo que recibe queda en [llamadas].
///
/// Diferencias con la real: los clientes no existen (el `clienteMinimoId` se toma como id del servidor) y no hay catálogo
/// (los nombres de las líneas son "Variante N").
class ColaFalsa implements ColaOperaciones {
  ColaFalsa([Iterable<OperacionPendiente> iniciales = const []]) {
    for (final o in iniciales) {
      sembrar(o);
    }
  }

  final Map<String, OperacionPendiente> _filas = {};
  final Map<String, List<ResultadoLocal>> _resultados = {};
  final List<String> _ordenInsercion = [];
  final StreamController<void> _cambios = StreamController<void>.broadcast();

  /// Todo lo que se pidió a la cola, en orden.
  final List<LlamadaCola> llamadas = [];

  /// Si se asigna, la próxima escritura (marcarEnviadas, aplicarResultados...) lanza este error una vez (para probar fallos de
  /// la cola).
  Object? fallarProximaEscritura;

  /// Agrega una fila tal cual (sin pasar por las reglas): para preparar el escenario.
  void sembrar(OperacionPendiente operacion) {
    if (!_filas.containsKey(operacion.operacionId)) _ordenInsercion.add(operacion.operacionId);
    _filas[operacion.operacionId] = operacion;
  }

  /// La fila actual (lanza si no existe).
  OperacionPendiente fila(String id) => _filas[id] ?? (throw StateError('La ColaFalsa no tiene la operación $id'));

  List<OperacionPendiente> get todas => [for (final id in _ordenInsercion) _filas[id]!];

  /// Las llamadas a un método.
  List<LlamadaCola> de(String metodo) => llamadas.where((l) => l.metodo == metodo).toList();

  // ---- Registro ----

  @override
  Future<void> registrarVenta(NuevaVenta venta) async {
    llamadas.add(LlamadaCola('registrarVenta', [venta.operacionId]));
    if (venta.lineas.isEmpty) throw const ColaError('La venta no tiene prendas.');
    if (!venta.efectivoConfirmado) throw const ColaError('Falta confirmar el efectivo recibido.');
    _exigirNueva(venta.operacionId);
    _insertar(
      OperacionPendiente(
        operacionId: venta.operacionId,
        empresaId: venta.empresaId,
        sucursalId: venta.sucursalId,
        usuarioId: venta.usuarioId,
        tipo: TipoOperacion.ventaContado,
        estado: EstadoOperacion.registrada,
        payload: jsonEncode(
          payloadVentaContado(
            clienteServidorId: venta.clienteMinimoId,
            lineas: venta.lineas,
            totalCentavos: venta.totalCentavos,
          ),
        ),
        versionContrato: 1,
        intentos: 0,
        fechaOperacion: venta.fechaOperacion,
        creadaEn: venta.fechaOperacion,
      ),
    );
  }

  @override
  Future<void> registrarReserva(NuevaReserva reserva) async {
    llamadas.add(LlamadaCola('registrarReserva', [reserva.operacionId]));
    if (reserva.lineas.isEmpty) throw const ColaError('La reserva no tiene prendas.');
    _exigirNueva(reserva.operacionId);
    _insertar(
      OperacionPendiente(
        operacionId: reserva.operacionId,
        empresaId: reserva.empresaId,
        sucursalId: reserva.sucursalId,
        usuarioId: reserva.usuarioId,
        tipo: TipoOperacion.reserva,
        estado: EstadoOperacion.registrada,
        payload: jsonEncode(
          payloadReserva(
            clienteServidorId: reserva.clienteMinimoId,
            fechaVisita: reserva.fechaVisita,
            horaDesde: reserva.horaDesde,
            horaHasta: reserva.horaHasta,
            observacion: reserva.observacion,
            lineas: reserva.lineas,
          ),
        ),
        versionContrato: 1,
        intentos: 0,
        fechaOperacion: reserva.fechaOperacion,
        creadaEn: reserva.fechaOperacion,
      ),
    );
  }

  void _exigirNueva(String id) {
    if (_filas.containsKey(id)) throw ColaError('La operación $id ya existe.');
  }

  void _insertar(OperacionPendiente operacion) {
    sembrar(operacion);
    _avisar();
  }

  // ---- Lectura ----

  @override
  Future<List<OperacionPendiente>> listar({
    required int empresaId,
    required int usuarioId,
    Set<EstadoOperacion>? estados,
    TipoOperacion? tipo,
    int? limite,
    int desplazamiento = 0,
  }) async {
    llamadas.add(const LlamadaCola('listar'));
    final lista = todas
        .where(
          (o) =>
              o.empresaId == empresaId &&
              o.usuarioId == usuarioId &&
              (estados == null || estados.contains(o.estado)) &&
              (tipo == null || o.tipo == tipo),
        )
        .toList()
        .reversed
        .toList();
    // Más reciente primero (fecha_operacion descendente; a igual fecha, la última en entrar).
    final indexadas = [for (var i = 0; i < lista.length; i++) (i, lista[i])];
    indexadas.sort((a, b) {
      final p = b.$2.fechaOperacion.compareTo(a.$2.fechaOperacion);
      return p != 0 ? p : a.$1.compareTo(b.$1);
    });
    var resultado = [for (final e in indexadas) e.$2].skip(desplazamiento);
    if (limite != null) resultado = resultado.take(limite);
    return resultado.toList();
  }

  @override
  Future<OperacionPendiente?> obtener(String operacionId) async {
    llamadas.add(LlamadaCola('obtener', [operacionId]));
    return _filas[operacionId];
  }

  @override
  Future<DetalleOperacion?> detalle(String operacionId) async {
    llamadas.add(LlamadaCola('detalle', [operacionId]));
    final op = _filas[operacionId];
    if (op == null) return null;
    final payload = jsonDecode(op.payload) as Map<String, dynamic>;
    final lineasJson = (payload['lineas'] as List<dynamic>? ?? const []).cast<Map<String, dynamic>>();
    final lineas = [
      for (final l in lineasJson)
        LineaDetalle(
          varianteId: l['variante_id'] as int,
          cantidad: l['cantidad'] as int,
          nombre: 'Variante ${l['variante_id']}',
          precioUnitarioCentavos: l['precio_unitario'] == null ? null : aCentavos(l['precio_unitario']!),
        ),
    ];
    return DetalleOperacion(
      operacion: op,
      lineas: lineas,
      clienteServidorId: payload['cliente_id'] as int?,
      totalCentavos: payload['total'] == null ? null : aCentavos(payload['total']!),
      efectivoConfirmado: op.tipo == TipoOperacion.ventaContado ? true : null,
      horaDesde: payload['hora_visita_desde'] as String?,
      horaHasta: payload['hora_visita_hasta'] as String?,
      observacion: payload['observacion'] as String?,
    );
  }

  @override
  Future<List<ResultadoLocal>> resultados(String operacionId) async {
    llamadas.add(LlamadaCola('resultados', [operacionId]));
    return List.of(_resultados[operacionId] ?? const []);
  }

  @override
  Future<List<OperacionPendiente>> paraEnviar({
    required int empresaId,
    required int usuarioId,
    required DateTime ahora,
    bool ignorarEspera = false,
    int? limite,
  }) async {
    llamadas.add(LlamadaCola('paraEnviar', const [], {'ahora': ahora, 'ignorarEspera': ignorarEspera, 'limite': limite}));
    final candidatas = <(int, OperacionPendiente)>[];
    var i = 0;
    for (final o in todas) {
      final espera = o.proximoReintentoEn;
      final listaYa = ignorarEspera || espera == null || !espera.isAfter(ahora);
      if (o.empresaId == empresaId && o.usuarioId == usuarioId && o.estado.seEnvia && listaYa) {
        candidatas.add((i, o));
      }
      i++;
    }
    candidatas.sort((a, b) {
      final p = a.$2.fechaOperacion.compareTo(b.$2.fechaOperacion);
      return p != 0 ? p : a.$1.compareTo(b.$1);
    });
    var lista = candidatas.map((e) => e.$2);
    if (limite != null) lista = lista.take(limite);
    return lista.toList();
  }

  @override
  Future<List<OperacionPendiente>> paraRevisarConflictos({required int empresaId, required int usuarioId}) async {
    llamadas.add(const LlamadaCola('paraRevisarConflictos'));
    return todas
        .where((o) => o.empresaId == empresaId && o.usuarioId == usuarioId && o.estado == EstadoOperacion.enConflicto)
        .toList();
  }

  // ---- Transiciones ----

  @override
  Future<void> marcarEnviadas(List<String> operacionIds) async {
    llamadas.add(LlamadaCola('marcarEnviadas', List.of(operacionIds)));
    _simularFallo();
    for (final id in operacionIds) {
      final o = _filas[id];
      // Como la cola real: cada envío cuenta un intento, también el de una 'enviada' huérfana que se reenvía.
      if (o == null || !o.estado.seEnvia) continue;
      _filas[id] = _copiar(o, estado: EstadoOperacion.enviada, intentos: o.intentos + 1, proximoReintentoEn: null, limpiarEspera: true);
    }
    _avisar();
  }

  @override
  Future<void> volverARegistrada(
    List<String> operacionIds, {
    String? error,
    DateTime? proximoReintento,
    bool devolverIntento = false,
  }) async {
    llamadas.add(
      LlamadaCola('volverARegistrada', List.of(operacionIds), {
        'error': error,
        'proximoReintento': proximoReintento,
        'devolverIntento': devolverIntento,
      }),
    );
    _simularFallo();
    for (final id in operacionIds) {
      final o = _filas[id];
      if (o == null || o.estado != EstadoOperacion.enviada) continue;
      final intentos = devolverIntento && o.intentos > 0 ? o.intentos - 1 : o.intentos;
      _filas[id] = _copiar(
        o,
        estado: EstadoOperacion.registrada,
        intentos: intentos,
        ultimoError: error,
        proximoReintentoEn: proximoReintento,
        limpiarEspera: proximoReintento == null,
      );
    }
    _avisar();
  }

  @override
  Future<void> registrarFalloDeRed(
    List<String> operacionIds, {
    required String error,
    required DateTime proximoReintento,
  }) async {
    llamadas.add(
      LlamadaCola('registrarFalloDeRed', List.of(operacionIds), {'error': error, 'proximoReintento': proximoReintento}),
    );
    _simularFallo();
    for (final id in operacionIds) {
      final o = _filas[id];
      if (o == null || o.estado.esFinal) continue;
      _filas[id] = _copiar(o, ultimoError: error, proximoReintentoEn: proximoReintento);
    }
    _avisar();
  }

  @override
  Future<List<String>> aplicarResultados(List<ResultadoOperacionSync> resultados, {required DateTime recibidoEn}) async {
    llamadas.add(LlamadaCola('aplicarResultados', [for (final r in resultados) r.operacionId], {'recibidoEn': recibidoEn}));
    _simularFallo();
    final cambiadas = <String>[];
    for (final r in resultados) {
      final destino = r.estado.aEstadoLocal;
      final o = _filas[r.operacionId];
      if (o == null) continue;
      if (destino == null) {
        // error_temporal: el estado no cambia y no se guarda como respuesta; solo se anota qué pasó.
        if (!o.estado.esFinal) {
          _filas[o.operacionId] = _copiar(o, ultimoError: r.mensaje ?? 'El servidor no pudo procesarla ahora. Se reintentará.');
        }
        continue;
      }
      // Solo transiciones válidas: una operación FINAL no retrocede y repetir el mismo estado no cambia nada.
      if (!o.estado.puedePasarA(destino)) continue;

      final esFinal = destino.esFinal;
      _filas[o.operacionId] = _copiar(
        o,
        estado: destino,
        ultimoError: esFinal && destino == EstadoOperacion.confirmada ? null : (r.motivo ?? o.ultimoError),
        limpiarError: destino == EstadoOperacion.confirmada,
        proximoReintentoEn: null,
        limpiarEspera: true,
        resueltaEn: esFinal ? (r.procesadaEn ?? recibidoEn) : null,
      );
      _resultados.putIfAbsent(o.operacionId, () => []).add(
        ResultadoLocal(
          operacionId: o.operacionId,
          recibidoEn: recibidoEn,
          estadoResultado: r.estado.nombre,
          codigoMotivo: r.motivo,
          motivo: r.mensaje,
          entidadServidorId: r.recurso?.id,
        ),
      );
      cambiadas.add(o.operacionId);
    }
    _avisar();
    return cambiadas;
  }

  @override
  Future<void> marcarRechazadaLocal(String operacionId, {required String motivo, required DateTime recibidoEn}) async {
    llamadas.add(LlamadaCola('marcarRechazadaLocal', [operacionId], {'motivo': motivo, 'recibidoEn': recibidoEn}));
    _simularFallo();
    final o = _filas[operacionId];
    // Solo las que aún se envían (registrada o enviada), como la cola real.
    if (o == null || !o.estado.seEnvia) return;
    _filas[operacionId] = _copiar(
      o,
      estado: EstadoOperacion.rechazada,
      ultimoError: motivo,
      proximoReintentoEn: null,
      limpiarEspera: true,
      resueltaEn: recibidoEn,
    );
    _resultados.putIfAbsent(operacionId, () => []).add(
      ResultadoLocal(
        operacionId: operacionId,
        recibidoEn: recibidoEn,
        estadoResultado: 'rechazada',
        codigoMotivo: 'rechazo_local',
        motivo: motivo,
      ),
    );
    _avisar();
  }

  @override
  Future<Map<EstadoOperacion, int>> conteoPorEstado({required int empresaId, required int usuarioId}) async {
    llamadas.add(const LlamadaCola('conteoPorEstado'));
    final conteo = {for (final e in EstadoOperacion.values) e: 0};
    for (final o in todas) {
      if (o.empresaId == empresaId && o.usuarioId == usuarioId) conteo[o.estado] = conteo[o.estado]! + 1;
    }
    return conteo;
  }

  @override
  Stream<void> get cambios => _cambios.stream;

  Future<void> cerrar() => _cambios.close();

  // ---- Internas ----

  void _simularFallo() {
    final e = fallarProximaEscritura;
    if (e != null) {
      fallarProximaEscritura = null;
      throw e;
    }
  }

  void _avisar() {
    if (!_cambios.isClosed) _cambios.add(null);
  }

  OperacionPendiente _copiar(
    OperacionPendiente o, {
    EstadoOperacion? estado,
    int? intentos,
    String? ultimoError,
    bool limpiarError = false,
    DateTime? proximoReintentoEn,
    bool limpiarEspera = false,
    DateTime? resueltaEn,
  }) {
    return OperacionPendiente(
      operacionId: o.operacionId,
      empresaId: o.empresaId,
      sucursalId: o.sucursalId,
      usuarioId: o.usuarioId,
      tipo: o.tipo,
      estado: estado ?? o.estado,
      payload: o.payload,
      versionContrato: o.versionContrato,
      intentos: intentos ?? o.intentos,
      ultimoError: limpiarError ? null : (ultimoError ?? o.ultimoError),
      proximoReintentoEn: limpiarEspera ? proximoReintentoEn : (proximoReintentoEn ?? o.proximoReintentoEn),
      fechaOperacion: o.fechaOperacion,
      creadaEn: o.creadaEn,
      resueltaEn: resueltaEn ?? o.resueltaEn,
    );
  }
}
