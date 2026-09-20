import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../auth/state/auth_controller.dart';
import '../../reservas/data/notificaciones_repository.dart';
import '../../reservas/models/notificacion_app.dart';
import '../../reservas/state/reservas_providers.dart' show notificacionesRepositoryProvider;

/// Las notificaciones del cliente: la lista, cuáles están sin leer y marcarlas como leídas. Se actualiza cuando la app
/// lo pide (al abrir el catálogo, la lista o Mis reservas) con [refrescar].
///
/// Un error de red conserva la lista anterior: solo si todavía no hay nada se muestra el error. Sin sesión ([activo]
/// en false) no consulta al backend: quedaría en 401 y cerraría la sesión que no existe.
class NotificacionesController extends StateNotifier<AsyncValue<List<NotificacionApp>>> {
  NotificacionesController(this._repositorio, {required this.activo})
    : super(activo ? const AsyncValue.loading() : const AsyncValue.data([])) {
    if (activo) refrescar();
  }

  final NotificacionesRepository _repositorio;
  final bool activo;

  Future<void> refrescar() async {
    if (!activo) return;
    try {
      final lista = await _repositorio.listar();
      if (!mounted) return;
      state = AsyncValue.data(lista);
    } catch (error, stack) {
      if (!mounted) return;
      if (!state.hasValue) state = AsyncValue.error(error, stack);
    }
  }

  /// Se marca al instante en pantalla y, si el backend falla, se vuelve a dejar como estaba.
  Future<void> marcarLeida(int id) async {
    final anterior = state.valueOrNull;
    if (anterior == null) return;
    state = AsyncValue.data([for (final n in anterior) n.id == id ? n.conLeida(true) : n]);
    try {
      await _repositorio.marcarLeida(id);
    } catch (_) {
      if (!mounted) return;
      final actual = state.valueOrNull ?? anterior;
      state = AsyncValue.data([for (final n in actual) n.id == id ? n.conLeida(false) : n]);
    }
  }

  Future<void> marcarTodasLeidas() async {
    final sinLeer = (state.valueOrNull ?? const <NotificacionApp>[]).where((n) => !n.leida).map((n) => n.id).toList();
    await Future.wait([for (final id in sinLeer) marcarLeida(id)]);
  }
}

/// Una instancia por sesión: al iniciar o cerrar sesión se descarta y se crea otra, así el contador de un cliente
/// nunca queda a la vista del siguiente.
final notificacionesProvider = StateNotifierProvider<NotificacionesController, AsyncValue<List<NotificacionApp>>>((ref) {
  final autenticado = ref.watch(authControllerProvider.select((s) => s.estaAutenticado));
  return NotificacionesController(ref.watch(notificacionesRepositoryProvider), activo: autenticado);
});

/// Cuántas notificaciones sin leer hay: el número de la campana.
final notificacionesNoLeidasProvider = Provider<int>(
  (ref) => (ref.watch(notificacionesProvider).valueOrNull ?? const <NotificacionApp>[]).where((n) => !n.leida).length,
);
