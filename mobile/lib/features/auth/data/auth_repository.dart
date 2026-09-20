import 'package:dio/dio.dart';
import '../../../core/network/token_storage.dart';
import '../models/usuario.dart';

class AuthRepository {
  AuthRepository({required Dio dio, required TokenStorage tokenStorage})
    : _dio = dio,
      _tokenStorage = tokenStorage;

  final Dio _dio;
  final TokenStorage _tokenStorage;

  Future<void> login({required String email, required String password}) async {
    final respuesta = await _dio.post<Map<String, dynamic>>(
      '/auth/login',
      data: {'email': email, 'password': password},
    );
    final datos = respuesta.data!;
    await _tokenStorage.guardar(
      accessToken: datos['access_token'] as String,
      refreshToken: datos['refresh_token'] as String,
    );
  }

  Future<void> registro({
    required String nombre,
    required String apellido,
    required String email,
    required String password,
    String? telefono,
  }) async {
    await _dio.post<Map<String, dynamic>>(
      '/auth/registro',
      data: {
        'nombre': nombre,
        'apellido': apellido,
        'email': email,
        'password': password,
        if (telefono != null && telefono.isNotEmpty) 'telefono': telefono,
      },
    );
  }

  Future<Usuario> obtenerUsuarioActual() async {
    final respuesta = await _dio.get<Map<String, dynamic>>('/auth/yo');
    return Usuario.fromJson(respuesta.data!);
  }

  /// POST /auth/recuperar. El backend responde siempre lo mismo, exista o no el correo. Devuelve el `token_dev`,
  /// que solo viene con ENVIRONMENT=local (todavía no hay servicio de correo): en producción es null.
  Future<String?> solicitarRecuperacion(String email) async {
    final respuesta = await _dio.post<Map<String, dynamic>>('/auth/recuperar', data: {'email': email});
    return respuesta.data?['token_dev'] as String?;
  }

  Future<void> confirmarRecuperacion({required String token, required String password}) async {
    await _dio.post<Map<String, dynamic>>('/auth/recuperar/confirmar', data: {'token': token, 'password': password});
  }
  Future<void> logout() => _tokenStorage.limpiar();
}
