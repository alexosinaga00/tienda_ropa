import '../../../core/utils/fecha_servidor.dart';
import 'linea_con_exhibicion.dart';

/// Línea de una venta (comprobante/historial), más los campos de
/// exhibición resueltos aparte -- mismo motivo que CarritoLinea: el
/// backend solo conoce variante_id.
class VentaLinea implements LineaConExhibicion<VentaLinea> {
  const VentaLinea({
    required this.id,
    required this.varianteId,
    required this.cantidad,
    required this.precioUnitario,
    required this.subtotal,
    this.cantidadDevuelta = 0,
    this.productoNombre,
    this.imagenPrincipal,
    this.tallaCodigo,
    this.colorNombre,
  });

  factory VentaLinea.fromJson(Map<String, dynamic> json) => VentaLinea(
    id: json['id'] as int,
    varianteId: json['variante_id'] as int,
    cantidad: json['cantidad'] as int,
    precioUnitario: double.parse(json['precio_unitario'].toString()),
    subtotal: double.parse(json['subtotal'].toString()),
    // Solo cuentan las devoluciones aprobadas. Si el servidor no lo manda (versión anterior), se toma 0.
    cantidadDevuelta: (json['cantidad_devuelta'] as num?)?.toInt() ?? 0,
  );

  final int id;
  @override
  final int varianteId;
  final int cantidad;
  final double precioUnitario;
  final double subtotal;

  /// Unidades de esta línea que ya se devolvieron (devoluciones aprobadas).
  final int cantidadDevuelta;
  final String? productoNombre;
  final String? imagenPrincipal;
  final String? tallaCodigo;
  final String? colorNombre;

  /// Lo que queda por cambiar o devolver de esta línea (nunca negativo).
  int get cantidadRestante => (cantidad - cantidadDevuelta).clamp(0, cantidad);

  @override
  VentaLinea conExhibicion({
    required String? productoNombre,
    required String? imagenPrincipal,
    required String? tallaCodigo,
    required String? colorNombre,
  }) {
    return VentaLinea(
      id: id,
      varianteId: varianteId,
      cantidad: cantidad,
      precioUnitario: precioUnitario,
      subtotal: subtotal,
      cantidadDevuelta: cantidadDevuelta,
      productoNombre: productoNombre,
      imagenPrincipal: imagenPrincipal,
      tallaCodigo: tallaCodigo,
      colorNombre: colorNombre,
    );
  }
}

class Venta {
  const Venta({
    required this.id,
    required this.codigo,
    required this.estado,
    required this.fecha,
    required this.subtotal,
    required this.descuento,
    required this.costoEnvio,
    required this.total,
    required this.detalle,
    this.sucursalId,
    this.unidadesDevueltas = 0,
  });

  factory Venta.fromJson(Map<String, dynamic> json) => Venta(
    id: json['id'] as int,
    codigo: json['codigo'] as String,
    estado: json['estado'] as String,
    fecha: fechaDelServidor(json['fecha'] as String),
    subtotal: double.parse(json['subtotal'].toString()),
    descuento: double.parse(json['descuento'].toString()),
    costoEnvio: double.parse(json['costo_envio'].toString()),
    total: double.parse(json['total'].toString()),
    detalle: (json['detalle'] as List).map((d) => VentaLinea.fromJson(d as Map<String, dynamic>)).toList(),
    sucursalId: json['sucursal_id'] as int?,
    unidadesDevueltas: json['unidades_devueltas'] as int? ?? 0,
  );

  final int id;
  final String codigo;
  final String estado;
  final DateTime fecha;
  final double subtotal;
  final double descuento;
  final double costoEnvio;
  final double total;
  final List<VentaLinea> detalle;

  /// La sucursal de la compra (dónde se retira o a dónde se lleva la prenda a cambiar).
  final int? sucursalId;

  /// Unidades devueltas de esta compra. La devolución no cambia el estado: se dice aparte.
  final int unidadesDevueltas;

  bool get esEnvioADomicilio => costoEnvio > 0;

  /// "Con devolución (1 de 4)" o "Devuelta"; null si no se devolvió nada.
  String? get etiquetaDevolucion {
    if (unidadesDevueltas <= 0) return null;
    final vendidas = detalle.fold<int>(0, (suma, linea) => suma + linea.cantidad);
    return unidadesDevueltas >= vendidas ? 'Devuelta' : 'Con devolución ($unidadesDevueltas de $vendidas)';
  }

  /// Unidades vendidas en total.
  int get unidadesVendidas => detalle.fold<int>(0, (suma, linea) => suma + linea.cantidad);

  /// Unidades ya devueltas: lo que dice el servidor para la compra o, si es más, la suma de sus líneas.
  int get unidadesYaDevueltas {
    final porLinea = detalle.fold<int>(0, (suma, linea) => suma + linea.cantidadDevuelta);
    return porLinea > unidadesDevueltas ? porLinea : unidadesDevueltas;
  }

  /// Las líneas a las que todavía les queda alguna unidad por cambiar.
  List<VentaLinea> get lineasCambiables => [
    for (final linea in detalle)
      if (linea.cantidadRestante > 0) linea,
  ];

  /// Falso cuando todas las prendas ya se devolvieron: no hay nada que cambiar. Si el servidor no dice cuánto se
  /// devolvió por línea (versión anterior), se calcula con el total devuelto de la compra.
  bool get hayPrendasCambiables {
    final porLinea = detalle.fold<int>(0, (suma, linea) => suma + linea.cantidadDevuelta);
    if (porLinea == 0 && unidadesDevueltas > 0) return unidadesDevueltas < unidadesVendidas;
    return lineasCambiables.isNotEmpty;
  }

  /// "Ya devolviste 1 de 4 prendas de esta compra"; null si no se devolvió nada.
  String? get avisoDevolucionParcial {
    final devueltas = unidadesYaDevueltas;
    if (devueltas <= 0) return null;
    return 'Ya devolviste $devueltas de $unidadesVendidas prendas de esta compra.';
  }

  Venta conDetalle(List<VentaLinea> nuevoDetalle) => Venta(
    id: id,
    codigo: codigo,
    estado: estado,
    fecha: fecha,
    subtotal: subtotal,
    descuento: descuento,
    costoEnvio: costoEnvio,
    total: total,
    detalle: nuevoDetalle,
    sucursalId: sucursalId,
    unidadesDevueltas: unidadesDevueltas,
  );
}

const etiquetasEstadoVenta = {
  'pendiente_pago': 'Pendiente de pago',
  'pagada': 'Pagada',
  'entregada': 'Entregada',
  'anulada': 'Anulada',
};
