import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/dio_client.dart';
import 'package:mobile/features/auth/data/auth_repository.dart';

import '../../helpers/token_storage_falso.dart';

/// Adaptador HTTP falso: guarda las peticiones y responde como el backend (202 con el cuerpo dado).
class _AdaptadorRegistrador implements HttpClientAdapter {
  _AdaptadorRegistrador(this.cuerpoJson);

  final String cuerpoJson;
  final peticiones = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    peticiones.add(options);
    return ResponseBody.fromString(
      cuerpoJson,
      202,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

AuthRepository _repositorio(_AdaptadorRegistrador adaptador, TokenStorageFalso storage) {
  final dio = buildDio(tokenStorage: storage, onSesionExpirada: () async {});
  dio.httpClientAdapter = adaptador;
  return AuthRepository(dio: dio, tokenStorage: storage);
}

void main() {
  group('AuthRepository - recuperar contraseña (CU-35)', () {
    test('solicitarRecuperacion manda el correo y devuelve token_dev cuando el backend lo incluye', () async {
      final adaptador = _AdaptadorRegistrador('{"detail": "Si el correo está registrado...", "token_dev": "abc.def"}');
      final repositorio = _repositorio(adaptador, TokenStorageFalso());

      final tokenDev = await repositorio.solicitarRecuperacion('cliente@example.com');

      expect(tokenDev, 'abc.def');
      expect(adaptador.peticiones, hasLength(1));
      expect(adaptador.peticiones.single.method, 'POST');
      expect(adaptador.peticiones.single.path, '/auth/recuperar');
      expect(adaptador.peticiones.single.data, {'email': 'cliente@example.com'});
    });

    test('sin token_dev (producción: no hay servicio de correo) devuelve null', () async {
      final adaptador = _AdaptadorRegistrador('{"detail": "Si el correo está registrado...", "token_dev": null}');

      final tokenDev = await _repositorio(adaptador, TokenStorageFalso()).solicitarRecuperacion('cliente@example.com');

      expect(tokenDev, isNull);
    });

    test('confirmarRecuperacion manda el token y la contraseña nueva', () async {
      final adaptador = _AdaptadorRegistrador('{"detail": "Contraseña actualizada."}');
      final repositorio = _repositorio(adaptador, TokenStorageFalso());

      await repositorio.confirmarRecuperacion(token: 'abc.def', password: 'claveNueva123');

      expect(adaptador.peticiones.single.method, 'POST');
      expect(adaptador.peticiones.single.path, '/auth/recuperar/confirmar');
      expect(adaptador.peticiones.single.data, {'token': 'abc.def', 'password': 'claveNueva123'});
    });

    test('las dos rutas son públicas: no mandan Authorization aunque haya una sesión guardada', () async {
      final storage = TokenStorageFalso();
      await storage.guardar(accessToken: 'ACCESS', refreshToken: 'REFRESH');
      final adaptador = _AdaptadorRegistrador('{"detail": "ok", "token_dev": null}');
      final repositorio = _repositorio(adaptador, storage);

      await repositorio.solicitarRecuperacion('cliente@example.com');
      await repositorio.confirmarRecuperacion(token: 't', password: 'claveNueva123');

      expect(adaptador.peticiones, hasLength(2));
      for (final peticion in adaptador.peticiones) {
        expect(peticion.headers.containsKey('Authorization'), isFalse, reason: peticion.path);
      }
    });
  });
}
