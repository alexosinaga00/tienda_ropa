import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/network/providers.dart';
import '../../auth/state/auth_controller.dart';
import '../../tracking/models/evento.dart';
import '../../tracking/state/tracking_service.dart';
import '../data/favoritos_repository.dart';
import '../models/favorito.dart';

final favoritosRepositoryProvider = Provider<FavoritosRepository>(
  (ref) => FavoritosRepository(ref.watch(dioProvider)),
);

class FavoritosController extends StateNotifier<AsyncValue<List<Favorito>>> {
  FavoritosController(this._ref, {required this.activo})
    : super(activo ? const AsyncValue.loading() : const AsyncValue.data([])) {
    if (activo) cargar();
  }

  final Ref _ref;
  final bool activo;

  FavoritosRepository get _repo => _ref.read(favoritosRepositoryProvider);

  Future<void> cargar() async {
    if (!activo) return;
    state = const AsyncValue.loading();
    try {
      state = AsyncValue.data(await _repo.listar());
    } catch (error, stackTrace) {
      state = AsyncValue.error(error, stackTrace);
    }
  }

  bool esFavorito(int varianteId) => state.value?.any((f) => f.varianteId == varianteId) ?? false;

  Future<void> alternar(int varianteId) async {
    final yaEsFavorito = esFavorito(varianteId);
    if (yaEsFavorito) {
      await _repo.quitar(varianteId);
    } else {
      await _repo.agregar(varianteId);
      _ref.read(trackingServiceProvider).track(tipo: TipoEvento.favorito, varianteId: varianteId);
    }
    await cargar();
  }
}

/// Una instancia por sesión: al iniciar o cerrar sesión se descarta y se crea
/// otra, así los favoritos de un cliente nunca quedan a la vista del
/// siguiente que entre en el mismo teléfono.
final favoritosControllerProvider = StateNotifierProvider<FavoritosController, AsyncValue<List<Favorito>>>((ref) {
  final autenticado = ref.watch(authControllerProvider.select((s) => s.estaAutenticado));
  return FavoritosController(ref, activo: autenticado);
});
