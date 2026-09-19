/// Línea del carrito tal como la devuelve el backend, más los campos de
/// exhibición (nombre/foto/talla/color) que se resuelven aparte con
/// CatalogoRepository.detallePorVariantes -- el carrito del backend solo
/// conoce variante_id, nunca el nombre del producto.
class CarritoLinea {
  const CarritoLinea({
    required this.id,
    required this.varianteId,
    required this.cantidad,
    required this.precioUnitario,
    required this.subtotal,
    this.disponible = true,
    this.productoNombre,
    this.imagenPrincipal,
    this.tallaCodigo,
    this.colorNombre,
  });

  factory CarritoLinea.fromJson(Map<String, dynamic> json) => CarritoLinea(
    id: json['id'] as int,
    varianteId: json['variante_id'] as int,
    cantidad: json['cantidad'] as int,
    precioUnitario: double.parse(json['precio_unitario'].toString()),
    subtotal: double.parse(json['subtotal'].toString()),
    disponible: json['disponible'] as bool? ?? true,
  );

  final int id;
  final int varianteId;
  final int cantidad;
  final double precioUnitario;
  final double subtotal;

  /// False si la prenda se dio de baja después de agregarla: no suma al
  /// subtotal y el backend no deja comprar el carrito hasta quitarla.
  final bool disponible;
  final String? productoNombre;
  final String? imagenPrincipal;
  final String? tallaCodigo;
  final String? colorNombre;

  CarritoLinea conExhibicion({
    required String? productoNombre,
    required String? imagenPrincipal,
    required String? tallaCodigo,
    required String? colorNombre,
  }) {
    return CarritoLinea(
      id: id,
      varianteId: varianteId,
      cantidad: cantidad,
      precioUnitario: precioUnitario,
      subtotal: subtotal,
      disponible: disponible,
      productoNombre: productoNombre,
      imagenPrincipal: imagenPrincipal,
      tallaCodigo: tallaCodigo,
      colorNombre: colorNombre,
    );
  }
}

class Carrito {
  const Carrito({
    required this.id,
    required this.clienteId,
    required this.sucursalId,
    required this.actualizadoEn,
    required this.detalle,
    required this.subtotal,
  });

  factory Carrito.fromJson(Map<String, dynamic> json) => Carrito(
    id: json['id'] as int,
    clienteId: json['cliente_id'] as int,
    sucursalId: json['sucursal_id'] as int?,
    actualizadoEn: DateTime.parse(json['actualizado_en'] as String),
    detalle: (json['detalle'] as List).map((d) => CarritoLinea.fromJson(d as Map<String, dynamic>)).toList(),
    subtotal: double.parse(json['subtotal'].toString()),
  );

  final int id;
  final int clienteId;
  final int? sucursalId;
  final DateTime actualizadoEn;
  final List<CarritoLinea> detalle;
  final double subtotal;

  bool get vacio => detalle.isEmpty;
  int get cantidadTotal => detalle.fold(0, (suma, linea) => suma + linea.cantidad);

  Carrito conDetalle(List<CarritoLinea> nuevoDetalle) => Carrito(
    id: id,
    clienteId: clienteId,
    sucursalId: sucursalId,
    actualizadoEn: actualizadoEn,
    detalle: nuevoDetalle,
    subtotal: subtotal,
  );
}

class ResumenCarritoLinea {
  const ResumenCarritoLinea({
    required this.varianteId,
    required this.cantidad,
    required this.precioUnitario,
    required this.descuentoUnitario,
    required this.subtotal,
  });

  factory ResumenCarritoLinea.fromJson(Map<String, dynamic> json) => ResumenCarritoLinea(
    varianteId: json['variante_id'] as int,
    cantidad: json['cantidad'] as int,
    precioUnitario: double.parse(json['precio_unitario'].toString()),
    descuentoUnitario: double.parse(json['descuento_unitario'].toString()),
    subtotal: double.parse(json['subtotal'].toString()),
  );

  final int varianteId;
  final int cantidad;
  final double precioUnitario;
  final double descuentoUnitario;
  final double subtotal;
}

/// GET /carrito/aplicar-promocion: vista previa de lo que costaría el
/// carrito ahora mismo, con las promociones vigentes ya aplicadas.
class ResumenCarrito {
  const ResumenCarrito({required this.lineas, required this.subtotal, required this.descuento, required this.total});

  factory ResumenCarrito.fromJson(Map<String, dynamic> json) => ResumenCarrito(
    lineas: (json['lineas'] as List).map((l) => ResumenCarritoLinea.fromJson(l as Map<String, dynamic>)).toList(),
    subtotal: double.parse(json['subtotal'].toString()),
    descuento: double.parse(json['descuento'].toString()),
    total: double.parse(json['total'].toString()),
  );

  final List<ResumenCarritoLinea> lineas;
  final double subtotal;
  final double descuento;
  final double total;
}
