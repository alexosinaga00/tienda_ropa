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
/// para las imágenes del probador). `options.path` en ese caso es la URL
/// entera, que no contiene ninguno de los prefijos de `_rutasPublicas`, así
/// que sin esta comprobación `_esRutaPublica` devolvía false y el
/// interceptor le adjuntaba el JWT del cliente a una petición dirigida a
/// res.cloudinary.com. Mismo criterio que usa el interceptor de la web
/// (auth.interceptor.ts: descarta lo que no empieza por environment.apiUrl).
bool _esUrlExterna(String path) {
  if (!path.startsWith('http://') && !path.startsWith('https://')) return false;
  return !path.startsWith(ApiConfig.baseUrl);
}

/// Cuándo NO corresponde mandar el JWT ni intentar refrescar la sesión: la petición está marcada como pública
/// (`extra['publica']`, la pone [ApiClient]), es de un tercero, o es una de las rutas públicas de siempre (los
/// repositorios que todavía pasan [Dio] directo).
bool _sinSesion(RequestOptions options) =>
    options.extra['publica'] == true || _esUrlExterna(options.path) || _esRutaPublica(options.path);

/// El refresh token ya no sirve: no hay uno guardado o el backend lo rechazó (400/401/403). Es lo único que
/// justifica cerrar la sesión; un timeout, la falta de conexión o un 5xx del refresh NO lo son.
class _SesionVencida implements Exception {
  const _SesionVencida();
}

const _estadosRefreshRechazado = {400, 401, 403};

/// Cliente Dio con JWT automático y refresh transparente en 401.
///
/// [onSesionExpirada] se llama cuando el backend rechaza el refresh (el refresh
/// token venció o es inválido: 400/401/403): ahí es responsabilidad de quien
/// arma el cliente cerrar la sesión de verdad (limpiar estado, redirigir a
/// login). Si el refresh falla por red, timeout o 5xx NO se limpian los
/// tokens ni se cierra la sesión: el error original llega a quien hizo la
/// petición y el próximo intento volverá a refrescar.
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
    if (refreshToken == null) throw const _SesionVencida();

    // dioRefresh siempre habla por el mismo transporte que dio (relevante
    // sobre todo en tests, que reemplazan el adapter después de armar el
    // cliente).
    dioRefresh.httpClientAdapter = dio.httpClientAdapter;
    final Response<Map<String, dynamic>> respuesta;
    try {
      respuesta = await dioRefresh.post<Map<String, dynamic>>('/auth/refresh', data: {'refresh_token': refreshToken});
    } on DioException catch (e) {
      if (_estadosRefreshRechazado.contains(e.response?.statusCode)) throw const _SesionVencida();
      rethrow;
    }

    final datos = respuesta.data!;
    final nuevoAccessToken = datos['access_token'] as String;
    final nuevoRefreshToken = datos['refresh_token'] as String;
    await tokenStorage.guardar(accessToken: nuevoAccessToken, refreshToken: nuevoRefreshToken);
    return nuevoAccessToken;
  }

  /// Un único refresh compartido por todas las requests que reciben 401 a la vez. Si el backend rechaza el refresh,
  /// la sesión se cierra aquí, una sola vez; con cualquier otro fallo solo se libera el candado para el próximo intento.
  Future<String> refrescoCompartido() {
    return refrescoEnCurso ??= () async {
      try {
        return await refrescarToken();
      } on _SesionVencida {
        await tokenStorage.limpiar();
        await onSesionExpirada();
        rethrow;
      } finally {
        refrescoEnCurso = null;
      }
    }();
  }

  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) async {
        if (!_sinSesion(options)) {
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
        if (!esNoAutorizado || _sinSesion(error.requestOptions) || yaReintentado) {
          handler.next(error);
          return;
        }

        final String nuevoAccessToken;
        try {
          nuevoAccessToken = await refrescoCompartido();
        } catch (_) {
          // Sesión vencida (ya cerrada en refrescoCompartido) o fallo de red/5xx del refresh (sesión intacta):
          // en ambos casos la petición recibe su error original.
          handler.next(error);
          return;
        }

        final opciones = error.requestOptions;
        opciones.extra = {...opciones.extra, 'reintentado': true};
        opciones.headers['Authorization'] = 'Bearer $nuevoAccessToken';

        try {
          final respuesta = await dio.fetch(opciones);
          handler.resolve(respuesta);
        } on DioException catch (errorReintento) {
          // El refresh sí funcionó: si el reintento falla es un error de esa petición, no de la sesión.
          handler.next(errorReintento);
        }
      },
    ),
  );

  return dio;
}
