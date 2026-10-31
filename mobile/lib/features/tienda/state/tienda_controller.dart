import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/network/api_client.dart';
import '../../../core/network/error_app.dart';
import '../../../core/network/providers.dart';
import '../../../core/sesion/sesion_storage.dart';
import '../../auth/state/auth_controller.dart';
import '../data/tienda_repository.dart';
import '../models/tienda.dart';

const avisoTiendaDesaparecida = 'Esa tienda ya no está disponible. Elige otra para continuar.';
const avisoTiendaSinSuscripcion = 'Esta tienda no está disponible por ahora. Intenta más tarde.';

class TiendaState {
  const TiendaState({this.cargada = false, this.tienda, this.aviso});

  /// Falso hasta que se leyó el almacenamiento del dispositivo: el router espera a que sea verdadero.
  final bool cargada;
  final Tienda? tienda;

  /// Un mensaje para mostrar una vez en "Elige tu tienda" (p. ej. la tienda guardada ya no existe).
  final String? aviso;
}

/// La tienda que eligió la persona: se guarda en el dispositivo y de ella salen las rutas públicas
/// (`/public/{codigo}/...`) y la empresa del login. Cambiarla reconstruye todo lo que la observa.
class TiendaController extends StateNotifier<TiendaState> {
  TiendaController({
    required this._storage,
    required this._repositorio,
    required this._alTiendaDesaparecida,
  }) : super(const TiendaState()) {
    cargadaFuture = _cargar();
  }

  final SesionStorage _storage;
  final TiendaRepository Function() _repositorio;
  final Future<void> Function() _alTiendaDesaparecida;

  /// Se completa cuando ya se leyó la tienda guardada (`restaurarSesion` lo espera).
  late final Future<void> cargadaFuture;

  Future<void> _cargar() async {
    final guardada = await _storage.leerTienda();
    if (!mounted) return;
    state = TiendaState(cargada: true, tienda: guardada);
  }

  Future<void> elegir(Tienda tienda) async {
    await _storage.guardarTienda(tienda);
    if (!mounted) return;
    state = TiendaState(cargada: true, tienda: tienda);
  }

  Future<void> olvidar() async {
    await _storage.borrarTienda();
    if (!mounted) return;
    state = const TiendaState(cargada: true);
  }

  void limpiarAviso() {
    if (state.aviso == null) return;
    state = TiendaState(cargada: state.cargada, tienda: state.tienda);
  }

  /// Confirma con el servidor que la tienda guardada sigue existiendo y refresca su nombre, logo y color (el branding
  /// puede cambiar). Si ya no existe se olvida y se cierra la sesión. Sin conexión o con un error del servidor NO se
  /// toca nada: la persona sigue con lo que tenía.
  Future<void> validarGuardada() async {
    await cargadaFuture;
    final guardada = state.tienda;
    if (guardada == null) return;
    try {
      final vigente = await _repositorio().obtener(guardada.codigo);
      if (!mounted) return;
      if (vigente != guardada) await _storage.guardarTienda(vigente);
      state = TiendaState(
        cargada: true,
        tienda: vigente,
        aviso: vigente.disponible ? null : avisoTiendaSinSuscripcion,
      );
    } catch (e) {
      if (!mounted) return;
      if (ErrorApp.desde(e).tipo != TipoErrorApp.noEncontrado) return;
      await _storage.borrarTienda();
      await _alTiendaDesaparecida();
      if (!mounted) return;
      state = const TiendaState(cargada: true, aviso: avisoTiendaDesaparecida);
    }
  }
}

/// Las tiendas son públicas y no dependen de la tienda elegida: usan un cliente sin código de tienda.
final tiendaRepositoryProvider = Provider<TiendaRepository>(
  (ref) => TiendaRepository(DioApiClient(ref.watch(dioProvider), codigoTienda: () => null)),
);

final tiendaControllerProvider = StateNotifierProvider<TiendaController, TiendaState>((ref) {
  return TiendaController(
    storage: ref.watch(sesionStorageProvider),
    repositorio: () => ref.read(tiendaRepositoryProvider),
    alTiendaDesaparecida: () => ref.read(authControllerProvider.notifier).logout(),
  );
});

final tiendaActualProvider = Provider<Tienda?>((ref) => ref.watch(tiendaControllerProvider.select((s) => s.tienda)));

/// El código de la tienda elegida. Los providers que dependen de la tienda lo observan para reconstruirse al cambiarla.
final tiendaCodigoProvider = Provider<String?>((ref) => ref.watch(tiendaActualProvider)?.codigo);
