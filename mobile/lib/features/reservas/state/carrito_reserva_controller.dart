import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../auth/state/auth_controller.dart';
import '../models/item_reserva_temporal.dart';

/// Lista temporal de variantes que el cliente va agregando desde el
/// detalle de producto, antes de confirmar la reserva. Solo en memoria.
class CarritoReservaController extends StateNotifier<List<ItemReservaTemporal>> {
  CarritoReservaController() : super(const []);

  bool contiene(int varianteId) => state.any((item) => item.varianteId == varianteId);

  void agregar(ItemReservaTemporal item) {
    if (contiene(item.varianteId)) return;
    state = [...state, item];
  }

  void quitar(int varianteId) {
    state = state.where((item) => item.varianteId != varianteId).toList();
  }

  void vaciar() {
    state = const [];
  }
}

/// Una instancia por sesión: aunque solo viva en memoria, lo que un cliente
/// dejó a medio reservar no puede aparecerle al siguiente.
final carritoReservaProvider = StateNotifierProvider<CarritoReservaController, List<ItemReservaTemporal>>((ref) {
  ref.watch(authControllerProvider.select((s) => s.estaAutenticado));
  return CarritoReservaController();
});
