import 'contrato_sync.dart';
import 'lineas_operacion.dart';
import 'operacion_pendiente.dart';

/// Se lanza cuando una operación no se puede registrar (datos inválidos o un cliente que el servidor no conoce). No queda NADA
/// guardado: el registro es una sola transacción.
class ColaError implements Exception {
  const ColaError(this.mensaje);

  final String mensaje;

  @override
  String toString() => 'ColaError($mensaje)';
}

/// Una venta de contado por registrar. La empresa, la sucursal y el usuario salen de la sesión; la fecha, del [Reloj].
class NuevaVenta {
  const NuevaVenta({
    required this.operacionId,
    required this.empresaId,
    required this.sucursalId,
    required this.usuarioId,
    required this.fechaOperacion,
    required this.lineas,
    this.clienteMinimoId,
    this.efectivoConfirmado = false,
  });

  /// UUID v4 generado AL ABRIR la pantalla (no al pulsar el botón): un doble toque intenta el mismo id y falla por la llave.
  final String operacionId;
  final int empresaId;
  final int sucursalId;
  final int usuarioId;
  final DateTime fechaOperacion;
  final List<LineaVenta> lineas;

  /// Un cliente de `cliente_minimo` que venga del servidor (con `servidor_id`); null = venta sin cliente.
  final int? clienteMinimoId;

  /// El efectivo recibido: sin esto no se registra. El monto recibido se asume igual al total.
  final bool efectivoConfirmado;

  int get totalCentavos => totalCentavosDe(lineas);
}

class NuevaReserva {
  const NuevaReserva({
    required this.operacionId,
    required this.empresaId,
    required this.sucursalId,
    required this.usuarioId,
    required this.fechaOperacion,
    required this.clienteMinimoId,
    required this.fechaVisita,
    required this.horaDesde,
    required this.horaHasta,
    required this.lineas,
    this.observacion,
  });

  final String operacionId;
  final int empresaId;
  final int sucursalId;
  final int usuarioId;
  final DateTime fechaOperacion;

  /// OBLIGATORIO y debe ser un cliente del servidor (`servidor_id` no nulo): el backend exige `cliente_id`.
  final int clienteMinimoId;
  final DateTime fechaVisita;

  /// "HH:mm".
  final String horaDesde;
  final String horaHasta;
  final String? observacion;
  final List<LineaReserva> lineas;
}

/// Una línea ya armada para mostrar: con el nombre de la prenda, talla, color y foto (de las tablas del catálogo local).
class LineaDetalle {
  const LineaDetalle({
    required this.varianteId,
    required this.cantidad,
    required this.nombre,
    this.talla,
    this.color,
    this.sku,
    this.imagenUrl,
    this.precioUnitarioCentavos,
  });

  final int varianteId;
  final int cantidad;
  final String nombre;
  final String? talla;
  final String? color;
  final String? sku;
  final String? imagenUrl;

  /// Solo en las ventas.
  final int? precioUnitarioCentavos;
}

/// Todo lo que la pantalla de resultado necesita de una operación: la fila, el cliente, las líneas y, según el tipo,
/// el total (venta) o la visita (reserva).
class DetalleOperacion {
  const DetalleOperacion({
    required this.operacion,
    required this.lineas,
    this.clienteNombre,
    this.clienteServidorId,
    this.totalCentavos,
    this.efectivoConfirmado,
    this.fechaVisita,
    this.horaDesde,
    this.horaHasta,
    this.observacion,
  });

  final OperacionPendiente operacion;
  final List<LineaDetalle> lineas;
  final String? clienteNombre;
  final int? clienteServidorId;
  final int? totalCentavos;
  final bool? efectivoConfirmado;
  final DateTime? fechaVisita;
  final String? horaDesde;
  final String? horaHasta;
  final String? observacion;
}

/// La cola de operaciones sobre SQLite (D13). Toda escritura es transaccional. Una operación NO se borra al enviarse.
abstract interface class ColaOperaciones {
  /// Guarda, en UNA transacción: la operación ('registrada', con su payload ya armado), la venta y sus detalles. Si algo falla
  /// no queda nada. Lanza [ColaError] si los datos no valen o el id ya existe (doble toque).
  Future<void> registrarVenta(NuevaVenta venta);

  Future<void> registrarReserva(NuevaReserva reserva);

  /// Las operaciones del usuario en su empresa, la más reciente primero. Sin [estados] devuelve todas.
  Future<List<OperacionPendiente>> listar({
    required int empresaId,
    required int usuarioId,
    Set<EstadoOperacion>? estados,
    TipoOperacion? tipo,
    int? limite,
    int desplazamiento = 0,
  });

  Future<OperacionPendiente?> obtener(String operacionId);

  Future<DetalleOperacion?> detalle(String operacionId);

  /// Las respuestas que dio el servidor a esta operación, de la más antigua a la más nueva.
  Future<List<ResultadoLocal>> resultados(String operacionId);

  /// Las que hay que enviar: 'registrada' o 'enviada' del usuario, cuyo `proximo_reintento_en` ya pasó (o sin espera), por
  /// `fecha_operacion` ascendente (el servidor las procesa en el orden en que OCURRIERON, D14).
  Future<List<OperacionPendiente>> paraEnviar({
    required int empresaId,
    required int usuarioId,
    required DateTime ahora,
    bool ignorarEspera = false,
    int? limite,
  });

  /// Las 'en_conflicto' del usuario, para preguntarle al servidor si un encargado ya las resolvió.
  Future<List<OperacionPendiente>> paraRevisarConflictos({required int empresaId, required int usuarioId});

  /// Pasa a 'enviada' con `intentos + 1`, en una transacción, ANTES de mandar el lote. Cuenta un intento CADA vez que se
  /// manda, también cuando se reenvía una que ya estaba 'enviada' (pudo no llegar). Ignora las que estén en otro estado.
  Future<void> marcarEnviadas(List<String> operacionIds);

  /// 'enviada' → 'registrada' (nunca llegó al servidor). Guarda el error y la espera. Con [devolverIntento] no gasta intentos
  /// (el 403 de plan/suscripción no es culpa de la operación).
  Future<void> volverARegistrada(
    List<String> operacionIds, {
    String? error,
    DateTime? proximoReintento,
    bool devolverIntento = false,
  });

  /// Anota el error y la espera de un fallo de red SIN cambiar el estado (una 'enviada' que pudo haber llegado sigue 'enviada').
  Future<void> registrarFalloDeRed(List<String> operacionIds, {required String error, required DateTime proximoReintento});

  /// Aplica lo que respondió el servidor, en UNA transacción por llamada: actualiza el estado, `resuelta_en` (la hora del
  /// SERVIDOR), `ultimo_error` y agrega una fila a `resultado_sync`. Un resultado para una operación en estado FINAL distinto
  /// no la hace retroceder; un `error_temporal` no cambia el estado (queda para reintentar). Devuelve los ids que cambiaron.
  Future<List<String>> aplicarResultados(List<ResultadoOperacionSync> resultados, {required DateTime recibidoEn});

  /// Marca como rechazada una operación que el servidor no acepta con un 4xx (aislada del lote): estado final local.
  Future<void> marcarRechazadaLocal(String operacionId, {required String motivo, required DateTime recibidoEn});

  /// Cuántas hay en cada estado (para las insignias y el resumen).
  Future<Map<EstadoOperacion, int>> conteoPorEstado({required int empresaId, required int usuarioId});

  /// Emite cada vez que algo cambia en la cola (la UI se refresca).
  Stream<void> get cambios;
}
