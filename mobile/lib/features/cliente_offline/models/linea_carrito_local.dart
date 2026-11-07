/// Con quién se guarda todo lo del cliente: la empresa (tienda) y la persona de la sesión. Nada de otra empresa u otra
/// persona se ve.
class AlcanceCliente {
  const AlcanceCliente({required this.empresaId, required this.usuarioId});

  final int empresaId;
  final int usuarioId;

  String get clave => '$empresaId:$usuarioId';

  @override
  bool operator ==(Object other) =>
      other is AlcanceCliente && other.empresaId == empresaId && other.usuarioId == usuarioId;

  @override
  int get hashCode => Object.hash(empresaId, usuarioId);

  @override
  String toString() => 'AlcanceCliente($empresaId, $usuarioId)';
}

/// Una línea del carrito LOCAL (el que existe mientras no hay conexión), con todo lo necesario para mostrarla sin red.
class LineaCarritoLocal {
  const LineaCarritoLocal({
    required this.varianteId,
    required this.productoId,
    required this.cantidad,
    required this.productoNombre,
    required this.precioUnitarioCentavos,
    required this.agregadoEn,
    this.talla,
    this.color,
    this.imagen,
    this.sucursalId,
    this.sucursalNombre,
  });

  factory LineaCarritoLocal.desdeFila(Map<String, Object?> fila) => LineaCarritoLocal(
    varianteId: fila['variante_id']! as int,
    productoId: fila['producto_id']! as int,
    cantidad: fila['cantidad']! as int,
    productoNombre: fila['producto_nombre']! as String,
    talla: fila['talla'] as String?,
    color: fila['color'] as String?,
    precioUnitarioCentavos: fila['precio_centavos']! as int,
    imagen: fila['imagen'] as String?,
    sucursalId: fila['sucursal_id'] as int?,
    sucursalNombre: fila['sucursal_nombre'] as String?,
    agregadoEn: DateTime.parse(fila['agregado_en']! as String).toUtc(),
  );

  final int varianteId;
  final int productoId;
  final int cantidad;
  final String productoNombre;
  final String? talla;
  final String? color;

  /// El precio que el cliente vio al agregarla, en centavos.
  final int precioUnitarioCentavos;
  final String? imagen;

  /// Sucursal donde se sabía que había stock al agregarla (null = no se sabía).
  final int? sucursalId;
  final String? sucursalNombre;
  final DateTime agregadoEn;

  int get subtotalCentavos => precioUnitarioCentavos * cantidad;

  /// "M · Azul" (o lo que haya); vacío si no hay talla ni color.
  String get detalle => [?talla, ?color].join(' · ');

  LineaCarritoLocal conCantidad(int nueva) => LineaCarritoLocal(
    varianteId: varianteId,
    productoId: productoId,
    cantidad: nueva,
    productoNombre: productoNombre,
    talla: talla,
    color: color,
    precioUnitarioCentavos: precioUnitarioCentavos,
    imagen: imagen,
    sucursalId: sucursalId,
    sucursalNombre: sucursalNombre,
    agregadoEn: agregadoEn,
  );

  Map<String, Object?> aFila(AlcanceCliente alcance) => {
    'empresa_id': alcance.empresaId,
    'usuario_id': alcance.usuarioId,
    'variante_id': varianteId,
    'producto_id': productoId,
    'cantidad': cantidad,
    'producto_nombre': productoNombre,
    'talla': talla,
    'color': color,
    'precio_centavos': precioUnitarioCentavos,
    'imagen': imagen,
    'sucursal_id': sucursalId,
    'sucursal_nombre': sucursalNombre,
    'agregado_en': agregadoEn.toUtc().toIso8601String(),
  };
}

/// Suma de `precio x cantidad` de las líneas, en centavos enteros (nada de decimales con coma flotante).
int totalDeLineasCentavos(Iterable<LineaCarritoLocal> lineas) => lineas.fold(0, (suma, l) => suma + l.subtotalCentavos);
