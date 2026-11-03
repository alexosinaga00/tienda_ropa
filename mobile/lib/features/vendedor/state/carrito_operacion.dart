import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/sync/cola_operaciones.dart';
import '../models/producto_local.dart';
import '../models/variante_local.dart';
import 'catalogo_local_providers.dart';

/// Lo más que se puede pedir de una misma prenda en una línea.
const maxCantidadPorLinea = 999;

/// Una prenda en la venta o reserva que se está armando. El precio y el descuento son los LOCALES del momento en que se
/// agregó la prenda y quedan CONGELADOS en la línea (D17: el servidor acepta el precio que se cobró).
class LineaCarrito {
  const LineaCarrito({
    required this.varianteId,
    required this.productoId,
    required this.nombre,
    required this.talla,
    required this.color,
    this.imagenUrl,
    required this.cantidad,
    required this.precioUnitarioCentavos,
    this.descuentoUnitarioCentavos = 0,
  });

  final int varianteId;
  final int productoId;
  final String nombre;
  final String talla;
  final String color;
  final String? imagenUrl;
  final int cantidad;
  final int precioUnitarioCentavos;
  final int descuentoUnitarioCentavos;

  /// Precio menos descuento, de una unidad.
  int get precioFinalCentavos => precioUnitarioCentavos - descuentoUnitarioCentavos;

  int get subtotalCentavos => precioFinalCentavos * cantidad;

  bool get tieneDescuento => descuentoUnitarioCentavos > 0;

  /// "M, Negro".
  String get descripcionVariante => '$talla, $color';

  LineaCarrito conCantidad(int nueva) => LineaCarrito(
    varianteId: varianteId,
    productoId: productoId,
    nombre: nombre,
    talla: talla,
    color: color,
    imagenUrl: imagenUrl,
    cantidad: nueva,
    precioUnitarioCentavos: precioUnitarioCentavos,
    descuentoUnitarioCentavos: descuentoUnitarioCentavos,
  );

  @override
  String toString() => 'LineaCarrito($varianteId x$cantidad)';
}

/// Agrega [cantidad] de [variante]. Si la variante ya está en la lista suma a su línea y conserva el precio con que entró.
List<LineaCarrito> agregarLinea(List<LineaCarrito> lineas, VarianteLocal variante, ProductoLocal producto, int cantidad) {
  if (cantidad < 1) return lineas;
  final i = lineas.indexWhere((l) => l.varianteId == variante.id);
  if (i >= 0) {
    final suma = (lineas[i].cantidad + cantidad).clamp(1, maxCantidadPorLinea).toInt();
    return [...lineas]..[i] = lineas[i].conCantidad(suma);
  }
  return [
    ...lineas,
    LineaCarrito(
      varianteId: variante.id,
      productoId: producto.id,
      nombre: producto.nombre,
      talla: variante.tallaCodigo,
      color: variante.colorNombre,
      imagenUrl: producto.imagenUrl,
      cantidad: cantidad.clamp(1, maxCantidadPorLinea).toInt(),
      precioUnitarioCentavos: variante.precioCentavos,
      descuentoUnitarioCentavos: variante.descuentoCentavos,
    ),
  ];
}

/// Cambia la cantidad de una línea. Una cantidad fuera de 1..[maxCantidadPorLinea] se ignora (para quitar la prenda está
/// [quitarLinea]).
List<LineaCarrito> cambiarCantidadLinea(List<LineaCarrito> lineas, int varianteId, int cantidad) {
  if (cantidad < 1 || cantidad > maxCantidadPorLinea) return lineas;
  return [for (final l in lineas) l.varianteId == varianteId ? l.conCantidad(cantidad) : l];
}

List<LineaCarrito> quitarLinea(List<LineaCarrito> lineas, int varianteId) =>
    [for (final l in lineas) if (l.varianteId != varianteId) l];

/// Cómo terminó un intento de registrar.
sealed class ResultadoRegistro {
  const ResultadoRegistro();

  /// Hay prendas que piden más de lo que se estima que queda. NO se registró nada: la persona decide.
  const factory ResultadoRegistro.advertencias(List<String> textos) = RegistroConAdvertencias;

  /// No se registró: el mensaje dice por qué (datos que faltan o la cola rechazó la operación).
  const factory ResultadoRegistro.error(String mensaje) = RegistroConError;

  /// Quedó guardada en el teléfono (también cuando era un segundo intento del mismo id).
  const factory ResultadoRegistro.registrada(String operacionId) = RegistroExitoso;
}

class RegistroConAdvertencias extends ResultadoRegistro {
  const RegistroConAdvertencias(this.textos);

  final List<String> textos;
}

class RegistroConError extends ResultadoRegistro {
  const RegistroConError(this.mensaje);

  final String mensaje;
}

class RegistroExitoso extends ResultadoRegistro {
  const RegistroExitoso(this.operacionId);

  final String operacionId;
}

/// "Quedan 2 de Polera (M, Negro)" para cada línea que pide más de lo que se ESTIMA que queda en la sucursal. Vacío si todo
/// alcanza. Es solo un aviso: el servidor decide al sincronizar (puede dejar la operación en conflicto, D15).
Future<List<String>> advertenciasDeStock(Ref ref, {required int sucursalId, required List<LineaCarrito> lineas}) async {
  final catalogo = await ref.read(catalogoLocalProvider.future);
  if (catalogo == null) return const [];
  final existencias = <int, int>{};
  for (final productoId in {for (final l in lineas) l.productoId}) {
    final variantes = await catalogo.variantesDeProducto(productoId, sucursalId: sucursalId);
    for (final v in variantes) {
      existencias[v.id] = v.cantidadEstimada;
    }
  }
  final avisos = <String>[];
  for (final l in lineas) {
    final quedan = existencias[l.varianteId];
    if (quedan == null || l.cantidad <= quedan) continue;
    final prenda = '${l.nombre} (${l.descripcionVariante})';
    avisos.add(
      switch (quedan) {
        <= 0 => 'No queda ninguna de $prenda',
        1 => 'Queda 1 de $prenda',
        _ => 'Quedan $quedan de $prenda',
      },
    );
  }
  return avisos;
}

/// Guarda con [escribir] y traduce el resultado. Un [ColaError] sobre un id que la cola YA tiene (doble toque) es éxito: es la
/// misma operación, no un error. Cualquier otro [ColaError] se devuelve como mensaje; un fallo inesperado, también.
Future<ResultadoRegistro> guardarEnCola(
  ColaOperaciones cola,
  String operacionId,
  Future<void> Function() escribir, {
  required String textoFalloInesperado,
}) async {
  try {
    await escribir();
    return ResultadoRegistro.registrada(operacionId);
  } on ColaError catch (e) {
    try {
      if (await cola.obtener(operacionId) != null) return ResultadoRegistro.registrada(operacionId);
    } catch (_) {
      // Si ni siquiera se puede consultar, vale el mensaje original.
    }
    return ResultadoRegistro.error(e.mensaje);
  } catch (_) {
    return ResultadoRegistro.error(textoFalloInesperado);
  }
}
