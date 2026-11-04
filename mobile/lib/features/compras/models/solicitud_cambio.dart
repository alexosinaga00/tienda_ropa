import '../../../core/utils/fecha_servidor.dart';

/// Los estados de una solicitud de cambio que manda el backend.
const estadoSolicitudPendiente = 'pendiente';

const etiquetasEstadoSolicitud = {
  'pendiente': 'Pendiente',
  'aprobada': 'Aprobada',
  'rechazada': 'Rechazada',
  'cancelada': 'Cancelada',
  'vencida': 'Vencida',
};

/// Una prenda de la solicitud: la que se devuelve y la talla o el color que se quiere en su lugar.
class SolicitudCambioLinea {
  const SolicitudCambioLinea({
    required this.ventaDetalleId,
    required this.cantidad,
    required this.varianteDevueltaId,
    required this.prendaDevuelta,
    this.varianteNuevaId,
    this.prendaNueva,
    this.disponibleNueva,
  });

  factory SolicitudCambioLinea.fromJson(Map<String, dynamic> json) => SolicitudCambioLinea(
    ventaDetalleId: json['venta_detalle_id'] as int,
    cantidad: json['cantidad'] as int,
    varianteDevueltaId: json['variante_devuelta_id'] as int,
    prendaDevuelta: json['prenda_devuelta'] as String,
    varianteNuevaId: json['variante_nueva_id'] as int?,
    prendaNueva: json['prenda_nueva'] as String?,
    disponibleNueva: json['disponible_nueva'] as int?,
  );

  final int ventaDetalleId;
  final int cantidad;
  final int varianteDevueltaId;
  final String prendaDevuelta;
  final int? varianteNuevaId;
  final String? prendaNueva;

  /// Unidades de la prenda nueva en la sucursal (solo informativo: no se reservan).
  final int? disponibleNueva;
}

/// `GET /solicitudes-cambio/mias`: lo que el cliente pidió cambiar de una compra. El personal de la sucursal la aprueba
/// o la rechaza cuando el cliente lleva la prenda.
class SolicitudCambio {
  const SolicitudCambio({
    required this.id,
    required this.codigo,
    required this.ventaId,
    required this.ventaCodigo,
    required this.sucursalId,
    required this.fecha,
    required this.estado,
    required this.atenderHasta,
    required this.detalle,
    this.clienteNombre,
    this.motivo,
    this.motivoRechazo,
    this.resueltaEn,
    this.correoProgramado = false,
  });

  factory SolicitudCambio.fromJson(Map<String, dynamic> json) => SolicitudCambio(
    id: json['id'] as int,
    codigo: json['codigo'] as String,
    ventaId: json['venta_id'] as int,
    ventaCodigo: json['venta_codigo'] as String,
    sucursalId: json['sucursal_id'] as int,
    clienteNombre: json['cliente_nombre'] as String?,
    fecha: fechaDelServidor(json['fecha'] as String),
    estado: json['estado'] as String,
    motivo: json['motivo'] as String?,
    motivoRechazo: json['motivo_rechazo'] as String?,
    resueltaEn: json['resuelta_en'] == null ? null : fechaDelServidor(json['resuelta_en'] as String),
    atenderHasta: fechaDelServidor(json['atender_hasta'] as String),
    detalle: (json['detalle'] as List)
        .map((l) => SolicitudCambioLinea.fromJson(l as Map<String, dynamic>))
        .toList(),
    correoProgramado: json['correo_programado'] as bool? ?? false,
  );

  final int id;
  final String codigo;
  final int ventaId;
  final String ventaCodigo;
  final int sucursalId;
  final String? clienteNombre;

  /// En hora local.
  final DateTime fecha;
  final String estado;
  final String? motivo;
  final String? motivoRechazo;
  final DateTime? resueltaEn;

  /// Hasta cuándo se puede aprobar en la tienda; pasado ese instante la solicitud vence sola. En hora local.
  final DateTime atenderHasta;
  final List<SolicitudCambioLinea> detalle;
  final bool correoProgramado;

  bool get estaPendiente => estado == estadoSolicitudPendiente;

  String get etiquetaEstado => etiquetasEstadoSolicitud[estado] ?? estado;
}

/// Una línea del pedido: cuántas unidades de una prenda de la compra se cambian y por cuál variante.
class LineaSolicitudCambio {
  const LineaSolicitudCambio({required this.ventaDetalleId, required this.cantidad, required this.varianteNuevaId});

  final int ventaDetalleId;
  final int cantidad;
  final int varianteNuevaId;

  Map<String, dynamic> toJson() => {
    'venta_detalle_id': ventaDetalleId,
    'cantidad': cantidad,
    'variante_nueva_id': varianteNuevaId,
  };
}

/// Una talla o un color por el que se puede cambiar una prenda de la compra (mismo producto y mismo precio).
class OpcionCambio {
  const OpcionCambio({required this.varianteId, required this.etiqueta, required this.disponible});

  final int varianteId;

  /// "L · Azul".
  final String etiqueta;

  /// Unidades disponibles en la sucursal de la compra.
  final int disponible;
}
