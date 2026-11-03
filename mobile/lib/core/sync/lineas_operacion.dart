/// Una línea de una venta de contado. Los montos van en centavos: la suma no tiene errores de redondeo.
class LineaVenta {
  const LineaVenta({
    required this.varianteId,
    required this.cantidad,
    required this.precioUnitarioCentavos,
    this.descuentoUnitarioCentavos = 0,
  });

  final int varianteId;
  final int cantidad;

  /// El precio LOCAL de la variante al venderla: queda congelado en la línea (D17: el servidor acepta el que se cobró).
  final int precioUnitarioCentavos;
  final int descuentoUnitarioCentavos;

  /// (precio menos descuento) por cantidad: la misma cuenta que valida el servidor (`total_inconsistente`).
  int get subtotalCentavos => (precioUnitarioCentavos - descuentoUnitarioCentavos) * cantidad;
}

class LineaReserva {
  const LineaReserva({required this.varianteId, required this.cantidad});

  final int varianteId;
  final int cantidad;
}

/// El total de una venta: suma de (precio − descuento) × cantidad de cada línea.
int totalCentavosDe(Iterable<LineaVenta> lineas) => lineas.fold(0, (suma, l) => suma + l.subtotalCentavos);
