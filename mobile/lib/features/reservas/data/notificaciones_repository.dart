import 'package:dio/dio.dart';
import '../models/notificacion_app.dart';

class NotificacionesRepository {
  NotificacionesRepository(this._dio);

  final Dio _dio;

  Future<List<NotificacionApp>> listar() async {
    final respuesta = await _dio.get<List<dynamic>>('/notificaciones');
    return respuesta.data!.map((e) => NotificacionApp.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<NotificacionApp> marcarLeida(int id) async {
    final respuesta = await _dio.put<Map<String, dynamic>>('/notificaciones/$id/leida');
    return NotificacionApp.fromJson(respuesta.data!);
  }
}
