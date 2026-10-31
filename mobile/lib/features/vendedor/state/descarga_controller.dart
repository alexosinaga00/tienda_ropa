import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/conectividad/conectividad_service.dart';
import '../../../core/utils/reloj.dart';
import 'catalogo_local_providers.dart';
import 'descarga_catalogo_service.dart';

/// Lo que la pantalla muestra de la descarga en curso o de la última.
class DescargaEstado {
  const DescargaEstado({this.descargando = false, this.mensaje, this.esError = false});

  final bool descargando;

  /// Un aviso para la persona: por qué se pospuso, que falló (con "sigues viendo los datos del ...") o null si todo salió bien.
  final String? mensaje;
  final bool esError;
}

/// Decide CUÁNDO descargar; el trabajo lo hace [DescargaCatalogoService]. Disparadores: (a) al entrar a la sesión del
/// personal con conexión, (b) al recuperar la conexión si la última descarga tiene más de [intervaloRecuperacion],
/// (c) el botón "Actualizar datos", (d) al cambiar de sucursal si esa sucursal nunca se descargó.
class DescargaController extends StateNotifier<DescargaEstado> {
  DescargaController(this._ref) : super(const DescargaEstado());

  final Ref _ref;

  static const intervaloRecuperacion = Duration(minutes: 15);

  /// Descarga la sucursal pedida o, si no, la activa (la primera vez, la que elija el servidor).
  Future<void> actualizar({bool forzarCompleta = false, int? sucursalId}) async {
    if (state.descargando) return;
    final empresaId = _ref.read(empresaLocalIdProvider);
    final usuarioId = _ref.read(usuarioLocalIdProvider);
    if (usuarioId == null) return;

    state = const DescargaEstado(descargando: true);
    try {
      final servicio = await _ref.read(descargaServiceProvider.future);
      final sucursal = sucursalId ?? await _ref.read(sucursalActivaProvider.future);
      final resultado = await servicio.descargar(sucursalId: sucursal, usuarioId: usuarioId, forzarCompleta: forzarCompleta);
      if (!mounted) return;
      switch (resultado) {
        case DescargaExitosa():
          // La primera vez la sucursal la eligió el servicio: queda como la activa de esta persona.
          if (sucursal == null && empresaId != null) {
            final repositorio = await _ref.read(descargaRepositoryProvider.future);
            await repositorio.fijarSucursalActiva(empresaId, usuarioId, resultado.sucursalId);
          }
          if (!mounted) return;
          _ref.read(descargaTerminadaProvider.notifier).state++;
          state = const DescargaEstado();
        case DescargaPospuesta(:final motivo):
          state = DescargaEstado(mensaje: motivo);
        case DescargaFallida(:final mensaje):
          state = DescargaEstado(mensaje: mensaje, esError: true);
      }
    } catch (_) {
      if (!mounted) return;
      state = const DescargaEstado(mensaje: 'No se pudo actualizar. Intenta de nuevo.', esError: true);
    }
  }

  /// (a) Al entrar a la sesión del personal: si hay conexión, se actualiza.
  Future<void> alEntrar() async {
    if (!_ref.read(conectividadServiceProvider).actual) return;
    await actualizar();
  }

  /// (b) Al volver la conexión: solo si lo último que se descargó tiene más de 15 minutos (o nunca se descargó).
  Future<void> alRecuperarConexion() async {
    final empresaId = _ref.read(empresaLocalIdProvider);
    final sucursalId = await _ref.read(sucursalActivaProvider.future);
    if (empresaId != null && sucursalId != null) {
      final repositorio = await _ref.read(descargaRepositoryProvider.future);
      final ultima = await repositorio.ultimaDescarga(empresaId, sucursalId);
      if (ultima != null && _ref.read(relojProvider).ahora().difference(ultima.descargadoEn) < intervaloRecuperacion) return;
    }
    await actualizar();
  }

  /// (d) Al cambiar la sucursal activa: se guarda, y si esa sucursal nunca se descargó (y hay conexión) se descarga.
  Future<void> alCambiarSucursal(int sucursalId) async {
    final empresaId = _ref.read(empresaLocalIdProvider);
    final usuarioId = _ref.read(usuarioLocalIdProvider);
    if (empresaId == null || usuarioId == null) return;
    final repositorio = await _ref.read(descargaRepositoryProvider.future);
    await repositorio.fijarSucursalActiva(empresaId, usuarioId, sucursalId);
    _ref.invalidate(sucursalActivaProvider);
    final ultima = await repositorio.ultimaDescarga(empresaId, sucursalId);
    if (ultima == null && _ref.read(conectividadServiceProvider).actual) {
      await actualizar(sucursalId: sucursalId);
    } else {
      _ref.read(descargaTerminadaProvider.notifier).state++; // refresca la vigencia con la sucursal nueva
    }
  }
}

final descargaControllerProvider = StateNotifierProvider<DescargaController, DescargaEstado>(
  (ref) => DescargaController(ref),
);
