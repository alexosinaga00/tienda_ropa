/// Una variante (talla + color) de un producto, con su existencia en UNA sucursal.
///
/// Dinero en centavos. Si la variante no tiene stock descargado para la sucursal, las cantidades son 0 y [generadoEn] es
/// `null` (el stock no se conoce).
class VarianteLocal {
  const VarianteLocal({
    required this.id,
    required this.productoId,
    required this.tallaId,
    required this.tallaCodigo,
    required this.tallaOrden,
    required this.colorId,
    required this.colorNombre,
    this.colorHex,
    required this.sku,
    required this.precioCentavos,
    required this.descuentoCentavos,
    required this.cantidadConocida,
    required this.cantidadEstimada,
    this.generadoEn,
  });

  final int id;
  final int productoId;
  final int tallaId;
  final String tallaCodigo;
  final int tallaOrden;
  final int colorId;
  final String colorNombre;
  final String? colorHex;
  final String sku;
  final int precioCentavos;
  final int descuentoCentavos;

  /// Lo que el servidor dijo que había (disponible) en [generadoEn].
  final int cantidadConocida;

  /// Lo conocido menos lo vendido o reservado sin conexión que el servidor aún no refleja. Nunca baja de 0.
  final int cantidadEstimada;

  /// Hora del servidor (UTC) del stock conocido; `null` si no hay stock descargado para esta sucursal.
  final DateTime? generadoEn;

  /// Precio menos descuento, sin bajar de 0.
  int get precioFinalCentavos {
    final neto = precioCentavos - descuentoCentavos;
    return neto < 0 ? 0 : neto;
  }

  bool get tieneDescuento => descuentoCentavos > 0;

  @override
  String toString() => 'VarianteLocal($id, $sku)';
}
