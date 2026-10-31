import 'package:dio/dio.dart';
import 'error_app.dart';

/// Lo que se le muestra a la persona. Un error funcional del plan o de la suscripción tiene su mensaje fijo; si no,
/// el `detail` que manda el backend (p. ej. "Solo quedan 2 unidades disponibles") si lo hay; si no, el mensaje
/// genérico de quien llama.
String mensajeDeError(Object error, String porDefecto) {
  if (error is ErrorApp) {
    if (error.esFuncional) return error.mensaje;
    final detalle = error.detalle;
    return detalle != null && detalle.isNotEmpty ? detalle : porDefecto;
  }
  if (error is DioException) {
    final traducido = ErrorApp.desde(error);
    if (traducido.esFuncional) return traducido.mensaje;
    final data = error.response?.data;
    final detalle = data is Map ? data['detail'] : null;
    if (detalle is String && detalle.isNotEmpty) return detalle;
  }
  return porDefecto;
}

bool esConflicto(Object error) => _estadoDe(error) == 409;

/// El backend respondió 404 (p. ej. una variante sin assets del probador).
bool esNoEncontrado(Object error) => _estadoDe(error) == 404;

/// No se pudo hablar con el servidor: sin conexión o timeout (conexión, envío o respuesta).
bool esSinConexion(Object error) {
  if (error is ErrorApp) return error.tipo == TipoErrorApp.sinConexion;
  if (error is! DioException) return false;
  switch (error.type) {
    case DioExceptionType.connectionError:
    case DioExceptionType.connectionTimeout:
    case DioExceptionType.sendTimeout:
    case DioExceptionType.receiveTimeout:
      return true;
    default:
      return false;
  }
}

/// El backend respondió con un error 5xx.
bool esErrorDeServidor(Object error) {
  final estado = _estadoDe(error);
  return estado != null && estado >= 500;
}

/// El plan de la empresa no incluye la función pedida (403 `plan_no_incluye_funcionalidad`).
bool esPlanNoIncluye(Object error) => ErrorApp.desde(error).tipo == TipoErrorApp.planNoIncluyeFuncionalidad;

/// La suscripción de la empresa no está activa (403 `suscripcion_no_activa`).
bool esSuscripcionNoActiva(Object error) => ErrorApp.desde(error).tipo == TipoErrorApp.suscripcionNoActiva;

/// La empresa llegó al límite de su plan (409 `limite_plan_excedido`).
bool esLimitePlan(Object error) => ErrorApp.desde(error).tipo == TipoErrorApp.limitePlanExcedido;

int? _estadoDe(Object error) {
  if (error is ErrorApp) return error.estado;
  if (error is DioException) return error.response?.statusCode;
  return null;
}
