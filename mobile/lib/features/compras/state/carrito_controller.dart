import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../auth/state/auth_controller.dart';
import '../models/carrito.dart';
import 'compras_providers.dart';

class CarritoController extends StateNotifier<AsyncValue<Carrito>> {
  // Sin sesión queda en `loading` y no consulta: `Carrito` no tiene una
  // versión vacía que no sea inventarle un id y un cliente que no existen,
  // y las pantallas que lo muestran están detrás del login igual.
  CarritoController(this._ref, {required this.activo}) : super(const AsyncValue.loading()) {
    if (activo) cargar();
  }

  final Ref _ref;
  final bool activo;

  Future<void> cargar() async {
    if (!activo) return;
    state = const AsyncValue.loading();
    try {
      state = AsyncValue.data(await _conExhibicion(await _ref.read(carritoRepositoryProvider).obtener()));
    } catch (error, stackTrace) {
      state = AsyncValue.error(error, stackTrace);
    }
  }

  Future<void> agregar({required int varianteId, required int cantidad}) async {
    final carrito = await _ref
        .read(carritoRepositoryProvider)
        .agregar(varianteId: varianteId, cantidad: cantidad);
    state = AsyncValue.data(await _conExhibicion(carrito));
  }

  Future<void> actualizarCantidad({required int varianteId, required int cantidad}) async {
    final carrito = await _ref
        .read(carritoRepositoryProvider)
        .actualizarCantidad(varianteId: varianteId, cantidad: cantidad);
    state = AsyncValue.data(await _conExhibicion(carrito));
  }

  Future<void> quitar(int varianteId) async {
    final carrito = await _ref.read(carritoRepositoryProvider).quitar(varianteId);
    state = AsyncValue.data(await _conExhibicion(carrito));
  }

  Future<Carrito> _conExhibicion(Carrito carrito) async {
    if (carrito.detalle.isEmpty) return carrito;
    final porVariante = await lookupVariantes(_ref, carrito.detalle.map((l) => l.varianteId).toList());
    final detalleResuelto = carrito.detalle.map((linea) {
      final item = porVariante[linea.varianteId];
      return linea.conExhibicion(
        productoNombre: item?.productoNombre,
        imagenPrincipal: item?.imagenPrincipal,
        tallaCodigo: item?.tallaCodigo,
        colorNombre: item?.colorNombre,
      );
    }).toList();
    return carrito.conDetalle(detalleResuelto);
  }
}

/// Una instancia por sesión: el carrito de un cliente no puede quedar a la
/// vista (ni comprable) para el siguiente que entre en el mismo teléfono.
final carritoControllerProvider = StateNotifierProvider<CarritoController, AsyncValue<Carrito>>((ref) {
  final autenticado = ref.watch(authControllerProvider.select((s) => s.estaAutenticado));
  return CarritoController(ref, activo: autenticado);
});
