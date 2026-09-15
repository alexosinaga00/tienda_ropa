import 'package:dio/dio.dart';

/// El `detail` que manda el backend (p. ej. "Solo quedan 2 unidades
/// disponibles") si lo hay; si no, el mensaje genérico de quien llama.
String mensajeDeError(Object error, String porDefecto) {
  if (error is DioException) {
    final data = error.response?.data;
    final detalle = data is Map ? data['detail'] : null;
    if (detalle is String && detalle.isNotEmpty) return detalle;
  }
  return porDefecto;
}

bool esConflicto(Object error) => error is DioException && error.response?.statusCode == 409;
