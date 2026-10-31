import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../features/tienda/state/tienda_controller.dart';
import '../sesion/sesion_storage.dart';
import 'api_client.dart';
import 'dio_client.dart';
import 'token_storage.dart';

final tokenStorageProvider = Provider<TokenStorage>((ref) => const TokenStorage());

/// La tienda elegida (y, más adelante, el perfil del personal) en el almacenamiento seguro del dispositivo.
final sesionStorageProvider = Provider<SesionStorage>((ref) => const SesionStorage());

/// Se incrementa cuando el interceptor de Dio no pudo refrescar el token
/// (el refresh token también venció). authControllerProvider escucha esto
/// para cerrar la sesión de verdad, sin que dioProvider tenga que conocer
/// a authControllerProvider (evita un ciclo de providers).
final sesionExpiradaProvider = StateProvider<int>((ref) => 0);

final dioProvider = Provider<Dio>((ref) {
  final tokenStorage = ref.watch(tokenStorageProvider);
  return buildDio(
    tokenStorage: tokenStorage,
    onSesionExpirada: () async {
      ref.read(sesionExpiradaProvider.notifier).state++;
    },
  );
});

/// El punto de red de los repositorios. Observa la tienda elegida: al cambiarla se reconstruye y arrastra consigo a
/// todos los repositorios que lo usan, así que ninguna petición mezcla datos de dos tiendas.
final apiClientProvider = Provider<ApiClient>((ref) {
  final dio = ref.watch(dioProvider);
  ref.watch(tiendaCodigoProvider);
  return DioApiClient(dio, codigoTienda: () => ref.read(tiendaCodigoProvider));
});
