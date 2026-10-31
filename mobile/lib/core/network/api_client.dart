import 'package:dio/dio.dart';
import 'error_app.dart';

typedef DesdeJson<T> = T Function(Map<String, dynamic> json);

/// El único punto de red de los repositorios. Todo error sale como [ErrorApp]: un `DioException` no escapa de aquí.
/// Es la interfaz que las pruebas reemplazan por un falso.
///
/// Rutas: con `publica: true` la ruta se pide a `/public/{codigo}/...` (la tienda elegida) y no se manda el token. Una
/// ruta que ya empieza con `/public/` (la lista de tiendas) se respeta tal cual. Con `publica: false` la ruta no
/// cambia y la empresa sale del token: NUNCA hay una cabecera con la empresa (D02).
abstract interface class ApiClient {
  Future<List<T>> getLista<T>(String ruta, {Map<String, dynamic>? query, required DesdeJson<T> desde, bool publica = false});

  Future<T> getObjeto<T>(String ruta, {Map<String, dynamic>? query, required DesdeJson<T> desde, bool publica = false});

  Future<T> postObjeto<T>(
    String ruta, {
    Object? cuerpo,
    Map<String, dynamic>? query,
    required DesdeJson<T> desde,
    bool publica = false,
  });

  /// POST cuya respuesta no importa (204 o un cuerpo que no se usa).
  Future<void> postVacio(String ruta, {Object? cuerpo, bool publica = false});

  Future<T> putObjeto<T>(String ruta, {Object? cuerpo, required DesdeJson<T> desde});

  Future<void> eliminar(String ruta);
}

class DioApiClient implements ApiClient {
  DioApiClient(this._dio, {required this._codigoTienda});

  final Dio _dio;
  final String? Function() _codigoTienda;

  static const _errorSinTienda = ErrorApp(tipo: TipoErrorApp.desconocido, mensaje: 'Elige una tienda para continuar.');

  /// La ruta final y las opciones de la petición según sea pública o no.
  (String, Options) _preparar(String ruta, bool publica) {
    if (!publica) return (ruta, Options());
    final opciones = Options(extra: {'publica': true});
    if (ruta.startsWith('/public/')) return (ruta, opciones);
    final codigo = _codigoTienda();
    if (codigo == null || codigo.isEmpty) throw _errorSinTienda;
    return ('/public/$codigo$ruta', opciones);
  }

  Future<R> _traducir<R>(Future<R> Function() peticion) async {
    try {
      return await peticion();
    } on ErrorApp {
      rethrow;
    } on DioException catch (e) {
      throw ErrorApp.desde(e);
    } on TypeError {
      throw const ErrorApp(tipo: TipoErrorApp.desconocido, mensaje: 'La respuesta del servidor no se entendió.');
    } on FormatException {
      throw const ErrorApp(tipo: TipoErrorApp.desconocido, mensaje: 'La respuesta del servidor no se entendió.');
    }
  }

  @override
  Future<List<T>> getLista<T>(String ruta, {Map<String, dynamic>? query, required DesdeJson<T> desde, bool publica = false}) {
    return _traducir(() async {
      final (destino, opciones) = _preparar(ruta, publica);
      final respuesta = await _dio.get<List<dynamic>>(destino, queryParameters: query, options: opciones);
      return respuesta.data!.map((e) => desde(e as Map<String, dynamic>)).toList();
    });
  }

  @override
  Future<T> getObjeto<T>(String ruta, {Map<String, dynamic>? query, required DesdeJson<T> desde, bool publica = false}) {
    return _traducir(() async {
      final (destino, opciones) = _preparar(ruta, publica);
      final respuesta = await _dio.get<Map<String, dynamic>>(destino, queryParameters: query, options: opciones);
      return desde(respuesta.data!);
    });
  }

  @override
  Future<T> postObjeto<T>(
    String ruta, {
    Object? cuerpo,
    Map<String, dynamic>? query,
    required DesdeJson<T> desde,
    bool publica = false,
  }) {
    return _traducir(() async {
      final (destino, opciones) = _preparar(ruta, publica);
      final respuesta = await _dio.post<Map<String, dynamic>>(
        destino,
        data: cuerpo,
        queryParameters: query,
        options: opciones,
      );
      return desde(respuesta.data!);
    });
  }

  @override
  Future<void> postVacio(String ruta, {Object? cuerpo, bool publica = false}) {
    return _traducir(() async {
      final (destino, opciones) = _preparar(ruta, publica);
      await _dio.post<dynamic>(destino, data: cuerpo, options: opciones);
    });
  }

  @override
  Future<T> putObjeto<T>(String ruta, {Object? cuerpo, required DesdeJson<T> desde}) {
    return _traducir(() async {
      final respuesta = await _dio.put<Map<String, dynamic>>(ruta, data: cuerpo);
      return desde(respuesta.data!);
    });
  }

  @override
  Future<void> eliminar(String ruta) {
    return _traducir(() async {
      await _dio.delete<dynamic>(ruta);
    });
  }
}
