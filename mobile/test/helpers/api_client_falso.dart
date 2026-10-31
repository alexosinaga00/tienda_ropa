import 'package:mobile/core/network/api_client.dart';
import 'package:mobile/core/network/error_app.dart';

/// Una llamada que recibió el [ApiClientFalso].
class LlamadaApi {
  const LlamadaApi({required this.metodo, required this.ruta, this.query, this.cuerpo, this.publica = false});

  final String metodo;
  final String ruta;
  final Map<String, dynamic>? query;
  final Object? cuerpo;
  final bool publica;

  @override
  String toString() => '$metodo $ruta${publica ? ' (pública)' : ''}';
}

/// Doble de [ApiClient] para tests. Cada respuesta se prepara con [responder] para un método y una ruta: un `List` (se
/// usa en `getLista`), un `Map` (en `getObjeto`/`postObjeto`), `null` (en `postVacio`) o un [ErrorApp] (se lanza).
///
/// Si se preparan varias para la misma clave se entregan en orden y la ÚLTIMA se repite. Una llamada sin respuesta
/// preparada falla con un [StateError]: así una ruta mal armada no pasa inadvertida.
class ApiClientFalso implements ApiClient {
  final List<LlamadaApi> llamadas = [];
  final Map<String, List<Object?>> _respuestas = {};

  void responder(String metodo, String ruta, Object? respuesta) {
    _respuestas.putIfAbsent('$metodo $ruta', () => []).add(respuesta);
  }

  /// Las llamadas hechas con ese método y esa ruta.
  List<LlamadaApi> de(String metodo, String ruta) =>
      llamadas.where((l) => l.metodo == metodo && l.ruta == ruta).toList();

  Object? _siguiente(LlamadaApi llamada) {
    llamadas.add(llamada);
    final cola = _respuestas['${llamada.metodo} ${llamada.ruta}'];
    if (cola == null || cola.isEmpty) {
      throw StateError('El ApiClientFalso no tiene respuesta preparada para $llamada');
    }
    final respuesta = cola.length > 1 ? cola.removeAt(0) : cola.first;
    if (respuesta is ErrorApp) throw respuesta;
    return respuesta;
  }

  @override
  Future<List<T>> getLista<T>(
    String ruta, {
    Map<String, dynamic>? query,
    required DesdeJson<T> desde,
    bool publica = false,
  }) async {
    final datos = _siguiente(LlamadaApi(metodo: 'GET', ruta: ruta, query: query, publica: publica));
    return (datos! as List<dynamic>).map((e) => desde(e as Map<String, dynamic>)).toList();
  }

  @override
  Future<T> getObjeto<T>(
    String ruta, {
    Map<String, dynamic>? query,
    required DesdeJson<T> desde,
    bool publica = false,
  }) async {
    final datos = _siguiente(LlamadaApi(metodo: 'GET', ruta: ruta, query: query, publica: publica));
    return desde(datos! as Map<String, dynamic>);
  }

  @override
  Future<T> postObjeto<T>(
    String ruta, {
    Object? cuerpo,
    Map<String, dynamic>? query,
    required DesdeJson<T> desde,
    bool publica = false,
  }) async {
    final datos = _siguiente(LlamadaApi(metodo: 'POST', ruta: ruta, query: query, cuerpo: cuerpo, publica: publica));
    return desde(datos! as Map<String, dynamic>);
  }

  @override
  Future<void> postVacio(String ruta, {Object? cuerpo, bool publica = false}) async {
    _siguiente(LlamadaApi(metodo: 'POST', ruta: ruta, cuerpo: cuerpo, publica: publica));
  }

  @override
  Future<T> putObjeto<T>(String ruta, {Object? cuerpo, required DesdeJson<T> desde}) async {
    final datos = _siguiente(LlamadaApi(metodo: 'PUT', ruta: ruta, cuerpo: cuerpo));
    return desde(datos! as Map<String, dynamic>);
  }

  @override
  Future<void> eliminar(String ruta) async {
    _siguiente(LlamadaApi(metodo: 'DELETE', ruta: ruta));
  }
}
