import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/utils/reloj.dart';
import '../config/cliente_offline_config.dart';
import '../data/repositorio_cliente.dart';
import '../models/linea_carrito_local.dart';

/// Lo que dejó "Pasar a mi carrito": cuántas líneas entraron al carrito del servidor y cuántas se quedaron aquí.
typedef ResultadoPaso = ({int pasadas, int fallidas});

/// El carrito LOCAL del cliente: solo existe mientras no hay conexión. Cada línea se guarda en la base del cliente (por
/// empresa y persona) con los datos para mostrarla sin red. Con conexión el carrito y la compra siguen siendo los del
/// servidor, sin cambios.
///
/// Al volver la red NO se mezcla solo con el del servidor: se queda a la vista, avisa, y el cliente decide entre "Pasar a
/// mi carrito" (cada línea se agrega al del servidor y sale de aquí) o descartarlo. Se vacía también al pagarlo con el
/// PayPal guardado (el pedido en cola se lleva las líneas).
class CarritoLocalController extends StateNotifier<List<LineaCarritoLocal>> {
  CarritoLocalController(this._repositorio, this._reloj, {required bool activo}) : super(const []) {
    if (activo) cargar();
  }

  final Future<RepositorioCliente?> Function() _repositorio;
  final Reloj _reloj;

  Future<RepositorioCliente?> _repo() async {
    try {
      return await _repositorio();
    } catch (e) {
      debugPrint('carrito_local no se pudo abrir la base error=${e.runtimeType}');
      return null;
    }
  }

  /// Lee el carrito local de la sesión actual. Nunca lanza.
  Future<void> cargar() async {
    final repo = await _repo();
    if (repo == null) {
      if (mounted) state = const [];
      return;
    }
    try {
      final lineas = await repo.carrito();
      if (mounted) state = lineas;
    } catch (e) {
      debugPrint('carrito_local no se pudo leer error=${e.runtimeType}');
    }
  }

  /// Guarda la prenda en el carrito local (suma si la variante ya estaba). Devuelve false si no hay sesión o falló.
  Future<bool> agregar({
    required int varianteId,
    required int productoId,
    required String productoNombre,
    required int precioUnitarioCentavos,
    String? talla,
    String? color,
    String? imagen,
    int? sucursalId,
    String? sucursalNombre,
    int cantidad = 1,
  }) async {
    final repo = await _repo();
    if (repo == null) return false;
    try {
      await repo.agregarLinea(
        LineaCarritoLocal(
          varianteId: varianteId,
          productoId: productoId,
          cantidad: cantidad,
          productoNombre: productoNombre,
          talla: talla,
          color: color,
          precioUnitarioCentavos: precioUnitarioCentavos,
          imagen: imagen,
          sucursalId: sucursalId,
          sucursalNombre: sucursalNombre,
          agregadoEn: _reloj.ahora(),
        ),
        maximo: maxUnidadesLinea,
      );
      await cargar();
      return true;
    } catch (e) {
      debugPrint('carrito_local no se pudo guardar error=${e.runtimeType}');
      return false;
    }
  }

  Future<void> cambiarCantidad(int varianteId, int cantidad) async {
    final repo = await _repo();
    if (repo == null) return;
    try {
      await repo.cambiarCantidad(varianteId, cantidad > maxUnidadesLinea ? maxUnidadesLinea : cantidad);
    } catch (e) {
      debugPrint('carrito_local no se pudo cambiar la cantidad error=${e.runtimeType}');
    }
    await cargar();
  }

  Future<void> quitar(int varianteId) => cambiarCantidad(varianteId, 0);

  Future<void> vaciar() async {
    final repo = await _repo();
    if (repo == null) return;
    try {
      await repo.vaciarCarrito();
    } catch (e) {
      debugPrint('carrito_local no se pudo vaciar error=${e.runtimeType}');
    }
    await cargar();
  }

  /// "Pasar a mi carrito": agrega al carrito del servidor cada línea, una por una, y la quita de aquí si el servidor la
  /// aceptó. Las que el servidor rechaza (sin stock, ya no existe) se quedan para que el cliente decida.
  Future<ResultadoPaso> pasarAlServidor(Future<void> Function(int varianteId, int cantidad) agregarAlServidor) async {
    var pasadas = 0;
    var fallidas = 0;
    for (final linea in [...state]) {
      try {
        await agregarAlServidor(linea.varianteId, linea.cantidad);
        await quitar(linea.varianteId);
        pasadas++;
      } catch (_) {
        fallidas++;
      }
    }
    return (pasadas: pasadas, fallidas: fallidas);
  }
}
