import 'package:dio/dio.dart';
import '../config/api_config.dart';
import 'token_storage.dart';

const _rutasPublicas = ['/auth/login', '/auth/registro', '/auth/refresh', '/auth/recuperar', '/catalogo'];

// Excepción dentro de '/catalogo': obtener_detalle_para_dashboard (usado acá
// por el carrito, para resolver nombre/foto de cada línea) exige un usuario
// logueado del lado del backend -- sin esto, quedaría marcado como público
// y nunca se le mandaría el token.
const _rutasCatalogoConToken = ['/catalogo/variantes/detalle'];

bool _esRutaPublica(String path) {
  if (_rutasCatalogoConToken.any((ruta) => path.contains(ruta))) return false;
  return _rutasPublicas.any((ruta) => path.contains(ruta));
}

/// Una URL ABSOLUTA que no apunta a nuestra API es de un tercero (Cloudinary,
/// para el overlay del probador). `options.path` en ese caso es la URL
/// entera, que no contiene ninguno de los prefijos de `_rutasPublicas`, así
/// que sin esta comprobación `_esRutaPublica` devolvía false y el
/// interceptor le adjuntaba el JWT del cliente a una petición dirigida a
/// res.cloudinary.com. Mismo criterio que usa el interceptor de la web
/// (auth.interceptor.ts: descarta lo que no empieza por environment.apiUrl).
bool _esUrlExterna(String path) {
  if (!path.startsWith('http://') && !path.startsWith('https://')) return false;
  return !path.startsWith(ApiConfig.baseUrl);
}

/// Cuándo NO corresponde mandar el JWT ni intentar refrescar la sesión.
bool _sinSesion(String path) => _esUrlExterna(path) || _esRutaPublica(path);

/// Cliente Dio con JWT automático y refresh transparente en 401.
///
/// [onSesionExpirada] se llama cuando el refresh también falla (el refresh
/// token venció o es inválido): ahí es responsabilidad de quien arma el
/// cliente cerrar la sesión de verdad (limpiar estado, redirigir a login).
///
/// Dos cosas evitan el bucle infinito si el refresh token también expiró:
/// 1. Cada request reintentada se marca con `extra['reintentado'] = true`;
///    si vuelve a dar 401, no se reintenta una segunda vez, se propaga el
///    error tal cual.
/// 2. Si ya hay un refresh en curso, las demás requests que reciben 401 al
///    mismo tiempo esperan ese mismo refresh en vez de disparar uno cada una.
Dio buildDio({
  required TokenStorage tokenStorage,
  required Future<void> Function() onSesionExpirada,
}) {
  final dio = Dio(
    BaseOptions(
      baseUrl: ApiConfig.baseUrl,
      connectTimeout: const Duration(seconds: 15),
      receiveTimeout: const Duration(seconds: 15),
    ),
  );

  // Dio aparte, sin interceptores, para llamar a /auth/refresh sin
  // reentrar en este mismo flujo de manejo de 401.
  final dioRefresh = Dio(BaseOptions(baseUrl: ApiConfig.baseUrl));

  Future<String>? refrescoEnCurso;

  Future<String> refrescarToken() async {
    final refreshToken = await tokenStorage.leerRefreshToken();
    if (refreshToken == null) {
      throw DioException(
        requestOptions: RequestOptions(path: '/auth/refresh'),
        error: 'No hay refresh token guardado',
      );
    }

    // dioRefresh siempre habla por el mismo transporte que dio (relevante
    // sobre todo en tests, que reemplazan el adapter después de armar el
    // cliente).
    dioRefresh.httpClientAdapter = dio.httpClientAdapter;
    final respuesta = await dioRefresh.post<Map<String, dynamic>>(
      '/auth/refresh',
      data: {'refresh_token': refreshToken},
    );

    final datos = respuesta.data!;
    final nuevoAccessToken = datos['access_token'] as String;
    final nuevoRefreshToken = datos['refresh_token'] as String;
    await tokenStorage.guardar(accessToken: nuevoAccessToken, refreshToken: nuevoRefreshToken);
    return nuevoAccessToken;
  }

  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) async {
        if (!_sinSesion(options.path)) {
          final token = await tokenStorage.leerAccessToken();
          if (token != null) {
            options.headers['Authorization'] = 'Bearer $token';
          }
        }
        handler.next(options);
      },
      onError: (error, handler) async {
        final esNoAutorizado = error.response?.statusCode == 401;
        final yaReintentado = error.requestOptions.extra['reintentado'] == true;

        // `_sinSesion` y no `_esRutaPublica`: si Cloudinary respondiera 401,
        // esto intentaba refrescar el token y, al fallar, cerraba la sesión
        // del cliente por un error de un tercero.
        if (!esNoAutorizado || _sinSesion(error.requestOptions.path) || yaReintentado) {
          handler.next(error);
          return;
        }

        try {
          refrescoEnCurso ??= refrescarToken();
          final nuevoAccessToken = await refrescoEnCurso;
          refrescoEnCurso = null;

          final opciones = error.requestOptions;
          opciones.extra = {...opciones.extra, 'reintentado': true};
          opciones.headers['Authorization'] = 'Bearer $nuevoAccessToken';

          final respuesta = await dio.fetch(opciones);
          handler.resolve(respuesta);
        } catch (_) {
          refrescoEnCurso = null;
          await tokenStorage.limpiar();
          await onSesionExpirada();
          handler.next(error);
        }
      },
    ),
  );

  return dio;
}
