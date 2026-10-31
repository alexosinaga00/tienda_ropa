/// Un producto de la copia local del catálogo, listo para mostrar en una lista.
///
/// Los precios van en CENTAVOS y son los precios efectivos (precio de la variante menos su descuento) de las variantes
/// ACTIVAS. Un producto sin variantes activas tiene precios en 0 y existencia 0.
class ProductoLocal {
  const ProductoLocal({
    required this.id,
    required this.codigo,
    required this.nombre,
    required this.categoriaId,
    required this.categoriaNombre,
    required this.genero,
    this.imagenUrl,
    required this.precioDesdeCentavos,
    required this.precioMaxCentavos,
    this.existenciaEstimada,
  });

  final int id;
  final String codigo;
  final String nombre;
  final int categoriaId;
  final String categoriaNombre;
  final String genero;
  final String? imagenUrl;

  /// El menor precio efectivo (precio - descuento) entre sus variantes activas.
  final int precioDesdeCentavos;

  /// El mayor precio efectivo entre sus variantes activas.
  final int precioMaxCentavos;

  /// Suma de las existencias estimadas de sus variantes en la sucursal pedida; `null` si no se pidió sucursal.
  final int? existenciaEstimada;

  /// Hay más de un precio (la lista muestra "desde").
  bool get tieneRangoDePrecio => precioMaxCentavos > precioDesdeCentavos;

  @override
  String toString() => 'ProductoLocal($id, $codigo, $nombre)';
}
