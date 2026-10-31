import 'package:dio/dio.dart';
import '../../../core/network/error_app.dart';
import '../../../core/network/token_storage.dart';
import '../models/usuario.dart';

class AuthRepository {
  /// [codigoEmpresa] devuelve el código de la tienda elegida. Con él, el login manda `empresa` en el cuerpo y el registro
  /// va a `/public/{codigo}/registro`. Sin él (las pruebas antiguas) se conserva el comportamiento de antes.
  AuthRepository({required this._dio, required this._tokenStorage, this._codigoEmpresa});

  final Dio _dio;
  final TokenStorage _tokenStorage;
  final String? Function()? _codigoEmpresa;

  /// [empresa] es lo que escribió el personal tal cual (nombre o código: el backend lo normaliza); sin él se usa el
  /// código de la tienda elegida.
  Future<void> login({required String email, required String password, String? empresa}) async {
    empresa ??= _codigoEmpresa?.call();
    final respuesta = await _dio.post<Map<String, dynamic>>(
      '/auth/login',
      data: {if (empresa != null && empresa.isNotEmpty) 'empresa': empresa, 'email': email, 'password': password},
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
    final datos = {
      'nombre': nombre,
      'apellido': apellido,
      'email': email,
      'password': password,
      if (telefono != null && telefono.isNotEmpty) 'telefono': telefono,
    };
    if (_codigoEmpresa == null) {
      await _dio.post<Map<String, dynamic>>('/auth/registro', data: datos);
      return;
    }
    // Los clientes se registran por tienda: la cuenta pertenece a la tienda elegida.
    final codigo = _codigoEmpresa();
    if (codigo == null || codigo.isEmpty) {
      throw const ErrorApp(tipo: TipoErrorApp.desconocido, mensaje: 'Elige una tienda para continuar.');
    }
    await _dio.post<Map<String, dynamic>>(
      '/public/$codigo/registro',
      data: datos,
      options: Options(extra: {'publica': true}),
    );
  }

  Future<Usuario> obtenerUsuarioActual() async {
    final respuesta = await _dio.get<Map<String, dynamic>>('/auth/yo');
    return Usuario.fromJson(respuesta.data!);
  }

  /// POST /auth/recuperar. El backend responde siempre lo mismo, exista o no el correo. Devuelve el `token_dev`,
  /// que solo viene con ENVIRONMENT=local (todavía no hay servicio de correo): en producción es null.
  Future<String?> solicitarRecuperacion(String email) async {
    final empresa = _codigoEmpresa?.call();
    final respuesta = await _dio.post<Map<String, dynamic>>(
      '/auth/recuperar',
      data: {if (empresa != null && empresa.isNotEmpty) 'empresa': empresa, 'email': email},
    );
    return respuesta.data?['token_dev'] as String?;
  }

  Future<void> confirmarRecuperacion({required String token, required String password}) async {
    await _dio.post<Map<String, dynamic>>('/auth/recuperar/confirmar', data: {'token': token, 'password': password});
  }

  Future<void> logout() => _tokenStorage.limpiar();
}
