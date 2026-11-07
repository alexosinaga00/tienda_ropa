import '../../../core/utils/dinero.dart';

/// Los motivos estables con que el servidor rechaza un pedido hecho sin conexión (más `pedido_vencido`, que también
/// decide la propia app).
const motivoSinMetodoPago = 'sin_metodo_pago';
const motivoPedidoVencido = 'pedido_vencido';
const motivoPedidoInvalido = 'pedido_invalido';

/// Cuerpo de `POST /pedidos-diferidos`. El cliente NUNCA manda precios: solo prendas, cantidades y el tope aceptado.
class PedidoDiferidoCrear {
  const PedidoDiferidoCrear({
    required this.operacionId,
    required this.sucursalId,
    required this.costoEnvioCentavos,
    required this.lineas,
    required this.totalMaximoCentavos,
    required this.fechaPedido,
  });

  final String operacionId;
  final int sucursalId;
  final int costoEnvioCentavos;
  final List<({int varianteId, int cantidad})> lineas;
  final int totalMaximoCentavos;
  final String fechaPedido;

  Map<String, dynamic> toJson() => {
    'operacion_id': operacionId,
    'sucursal_id': sucursalId,
    'costo_envio': deCentavos(costoEnvioCentavos),
    'lineas': [
      for (final l in lineas) {'variante_id': l.varianteId, 'cantidad': l.cantidad},
    ],
    'total_maximo': deCentavos(totalMaximoCentavos),
    'fecha_pedido': fechaPedido,
  };
}

/// Respuesta 200 de `POST /pedidos-diferidos`: una decisión FINAL del servidor (cobrado o rechazado).
class PedidoDiferidoRespuesta {
  const PedidoDiferidoRespuesta({
    required this.operacionId,
    required this.cobrado,
    required this.mensaje,
    required this.duplicada,
    this.motivo,
    this.ventaId,
    this.codigoVenta,
    this.totalCentavos,
    this.totalUsd,
  });

  /// Un 200 que no es lo que manda este servidor (un proxy, una página de error) lanza [FormatException]: el llamador lo
  /// trata como un fallo temporal y reintenta.
  factory PedidoDiferidoRespuesta.fromJson(Map<String, dynamic> json) {
    final estado = json['estado'];
    if (estado != 'cobrado' && estado != 'rechazado') {
      throw FormatException('Estado de pedido desconocido: $estado');
    }
    final total = json['total'];
    return PedidoDiferidoRespuesta(
      operacionId: json['operacion_id'] as String,
      cobrado: estado == 'cobrado',
      motivo: json['motivo'] as String?,
      mensaje: (json['mensaje'] as String?) ?? '',
      ventaId: json['venta_id'] as int?,
      codigoVenta: json['codigo_venta'] as String?,
      totalCentavos: total == null ? null : aCentavos(total as Object),
      totalUsd: json['total_usd']?.toString(),
      duplicada: json['duplicada'] as bool? ?? false,
    );
  }

  final String operacionId;
  final bool cobrado;
  final String? motivo;
  final String mensaje;
  final int? ventaId;
  final String? codigoVenta;
  final int? totalCentavos;
  final String? totalUsd;
  final bool duplicada;
}
