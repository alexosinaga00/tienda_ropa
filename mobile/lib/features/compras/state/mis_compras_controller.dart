import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../auth/state/auth_controller.dart';
import '../data/ventas_repository.dart';
import '../models/venta.dart';
import 'compras_providers.dart';

class MisComprasController extends StateNotifier<AsyncValue<List<Venta>>> {
  MisComprasController(this._ref, {required this.activo})
    : super(activo ? const AsyncValue.loading() : const AsyncValue.data([])) {
    if (activo) cargar();
  }

  final Ref _ref;
  final bool activo;

  VentasRepository get _repo => _ref.read(ventasRepositoryProvider);

  Future<void> cargar() async {
    if (!activo) return;
    state = const AsyncValue.loading();
    try {
      state = AsyncValue.data(await _repo.misCompras());
    } catch (error, stackTrace) {
      state = AsyncValue.error(error, stackTrace);
    }
  }
}

/// Una instancia por sesión: el historial de compras es dato personal y no
/// puede sobrevivir a un cierre de sesión.
final misComprasControllerProvider = StateNotifierProvider<MisComprasController, AsyncValue<List<Venta>>>((ref) {
  final autenticado = ref.watch(authControllerProvider.select((s) => s.estaAutenticado));
  return MisComprasController(ref, activo: autenticado);
});
