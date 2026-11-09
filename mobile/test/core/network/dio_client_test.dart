import 'dart:async';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/dio_client.dart';

import '../../helpers/token_storage_falso.dart';

/// Adaptador HTTP falso: simula el backend sin hacer red real.
class AdaptadorFalso implements HttpClientAdapter {
  AdaptadorFalso(this.responder);

  final Future<ResponseBody> Function(RequestOptions options) responder;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) {
    return responder(options);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody _json(String cuerpo, int status) {
  return ResponseBody.fromString(
    cuerpo,
    status,
    headers: {
      Headers.contentTypeHeader: [Headers.jsonContentType],
    },
  );
}

void main() {
  group('buildDio - refresh automático', () {
    test('un 401 dispara refresh y reintenta la request original una sola vez', () async {
      final storage = TokenStorageFalso()
        ..accessToken = 'ACCESS_VIEJO'
        ..refreshToken = 'REFRESH_VALIDO';
      var sesionesExpiradas = 0;
      var llamadasRefresh = 0;

      final dio = buildDio(
        tokenStorage: storage,
        onSesionExpirada: () async => sesionesExpiradas++,
      );

      dio.httpClientAdapter = AdaptadorFalso((options) async {
        if (options.path.contains('/auth/refresh')) {
          llamadasRefresh++;
          return _json('{"access_token":"ACCESS_NUEVO","refresh_token":"REFRESH_NUEVO"}', 200);
        }

        final auth = options.headers['Authorization'];
        if (auth == 'Bearer ACCESS_NUEVO') {
          return _json('{"ok":true}', 200);
        }
        return _json('{"detail":"Token inválido o expirado"}', 401);
      });

      final respuesta = await dio.get<Map<String, dynamic>>('/protegido');

      expect(respuesta.statusCode, 200);
      expect(llamadasRefresh, 1);
      expect(sesionesExpiradas, 0);
      expect(storage.accessToken, 'ACCESS_NUEVO');
    });

    test('si el refresh token también venció, no reintenta en bucle: falla una vez y cierra sesión', () async {
      final storage = TokenStorageFalso()
        ..accessToken = 'ACCESS_VIEJO'
        ..refreshToken = 'REFRESH_VENCIDO';
      var sesionesExpiradas = 0;
      var llamadasRefresh = 0;
      var llamadasProtegido = 0;

      final dio = buildDio(
        tokenStorage: storage,
        onSesionExpirada: () async => sesionesExpiradas++,
      );

      dio.httpClientAdapter = AdaptadorFalso((options) async {
        if (options.path.contains('/auth/refresh')) {
          llamadasRefresh++;
          return _json('{"detail":"Token inválido o expirado"}', 401);
        }
        llamadasProtegido++;
        return _json('{"detail":"Token inválido o expirado"}', 401);
      });

      await expectLater(dio.get<Map<String, dynamic>>('/protegido'), throwsA(isA<DioException>()));

      // Ni el refresh ni la request protegida se reintentan más de una vez:
      // esto es lo que evita el bucle infinito si el refresh token expiró.
      expect(llamadasRefresh, 1);
      expect(llamadasProtegido, 1);
      expect(sesionesExpiradas, 1);
      expect(storage.accessToken, isNull);
      expect(storage.refreshToken, isNull);
      expect(storage.vecesLimpiado, 1);
    });

    for (final estadoRechazo in [400, 403]) {
      test('un refresh rechazado con $estadoRechazo también cierra la sesión y limpia los tokens', () async {
        final storage = TokenStorageFalso()
          ..accessToken = 'ACCESS_VIEJO'
          ..refreshToken = 'REFRESH_INVALIDO';
        var sesionesExpiradas = 0;

        final dio = buildDio(tokenStorage: storage, onSesionExpirada: () async => sesionesExpiradas++);

        dio.httpClientAdapter = AdaptadorFalso((options) async {
          if (options.path.contains('/auth/refresh')) return _json('{"detail":"rechazado"}', estadoRechazo);
          return _json('{"detail":"vencido"}', 401);
        });

        await expectLater(dio.get<Map<String, dynamic>>('/protegido'), throwsA(isA<DioException>()));

        expect(sesionesExpiradas, 1);
        expect(storage.accessToken, isNull);
        expect(storage.refreshToken, isNull);
      });
    }

    test('sin refresh token guardado la sesión se cierra', () async {
      final storage = TokenStorageFalso()..accessToken = 'ACCESS_VIEJO';
      var sesionesExpiradas = 0;

      final dio = buildDio(tokenStorage: storage, onSesionExpirada: () async => sesionesExpiradas++);

      dio.httpClientAdapter = AdaptadorFalso((options) async => _json('{"detail":"vencido"}', 401));

      await expectLater(dio.get<Map<String, dynamic>>('/protegido'), throwsA(isA<DioException>()));

      expect(sesionesExpiradas, 1);
      expect(storage.vecesLimpiado, 1);
    });

    test('si el refresh falla por falta de conexión NO se limpian los tokens ni se cierra la sesión', () async {
      final storage = TokenStorageFalso()
        ..accessToken = 'ACCESS_VIEJO'
        ..refreshToken = 'REFRESH_VALIDO';
      var sesionesExpiradas = 0;
      var hayRed = false;
      var llamadasRefresh = 0;

      final dio = buildDio(tokenStorage: storage, onSesionExpirada: () async => sesionesExpiradas++);

      dio.httpClientAdapter = AdaptadorFalso((options) async {
        if (options.path.contains('/auth/refresh')) {
          llamadasRefresh++;
          if (!hayRed) {
            throw DioException(requestOptions: options, type: DioExceptionType.connectionError, error: 'sin conexión');
          }
          return _json('{"access_token":"ACCESS_NUEVO","refresh_token":"REFRESH_NUEVO"}', 200);
        }
        if (options.headers['Authorization'] == 'Bearer ACCESS_NUEVO') return _json('{"ok":true}', 200);
        return _json('{"detail":"vencido"}', 401);
      });

      // Sin red: la petición recibe su error original (el 401) y la sesión sigue intacta.
      await expectLater(
        dio.get<Map<String, dynamic>>('/protegido'),
        throwsA(isA<DioException>().having((e) => e.response?.statusCode, 'statusCode', 401)),
      );
      expect(llamadasRefresh, 1);
      expect(sesionesExpiradas, 0);
      expect(storage.vecesLimpiado, 0);
      expect(storage.accessToken, 'ACCESS_VIEJO');
      expect(storage.refreshToken, 'REFRESH_VALIDO');

      // Vuelve la red: ni el refresco en curso ni la marca de reintento quedaron bloqueados.
      hayRed = true;
      final respuesta = await dio.get<Map<String, dynamic>>('/protegido');
      expect(respuesta.statusCode, 200);
      expect(llamadasRefresh, 2);
      expect(sesionesExpiradas, 0);
      expect(storage.accessToken, 'ACCESS_NUEVO');
    });

    test('si el refresh falla por timeout NO se limpian los tokens ni se cierra la sesión', () async {
      final storage = TokenStorageFalso()
        ..accessToken = 'ACCESS_VIEJO'
        ..refreshToken = 'REFRESH_VALIDO';
      var sesionesExpiradas = 0;

      final dio = buildDio(tokenStorage: storage, onSesionExpirada: () async => sesionesExpiradas++);

      dio.httpClientAdapter = AdaptadorFalso((options) async {
        if (options.path.contains('/auth/refresh')) {
          throw DioException(requestOptions: options, type: DioExceptionType.receiveTimeout);
        }
        return _json('{"detail":"vencido"}', 401);
      });

      await expectLater(dio.get<Map<String, dynamic>>('/protegido'), throwsA(isA<DioException>()));

      expect(sesionesExpiradas, 0);
      expect(storage.vecesLimpiado, 0);
      expect(storage.refreshToken, 'REFRESH_VALIDO');
    });

    test('si el refresh responde 500 NO se limpian los tokens ni se cierra la sesión', () async {
      final storage = TokenStorageFalso()
        ..accessToken = 'ACCESS_VIEJO'
        ..refreshToken = 'REFRESH_VALIDO';
      var sesionesExpiradas = 0;
      var llamadasProtegido = 0;

      final dio = buildDio(tokenStorage: storage, onSesionExpirada: () async => sesionesExpiradas++);

      dio.httpClientAdapter = AdaptadorFalso((options) async {
        if (options.path.contains('/auth/refresh')) return _json('{"detail":"error interno"}', 500);
        llamadasProtegido++;
        return _json('{"detail":"vencido"}', 401);
      });

      await expectLater(
        dio.get<Map<String, dynamic>>('/protegido'),
        throwsA(isA<DioException>().having((e) => e.response?.statusCode, 'statusCode', 401)),
      );

      expect(llamadasProtegido, 1, reason: 'sin refresh exitoso no hay reintento de la petición');
      expect(sesionesExpiradas, 0);
      expect(storage.vecesLimpiado, 0);
      expect(storage.accessToken, 'ACCESS_VIEJO');
      expect(storage.refreshToken, 'REFRESH_VALIDO');
    });

    test('si el reintento tras un refresh exitoso falla, no se cierra la sesión', () async {
      final storage = TokenStorageFalso()
        ..accessToken = 'ACCESS_VIEJO'
        ..refreshToken = 'REFRESH_VALIDO';
      var sesionesExpiradas = 0;

      final dio = buildDio(tokenStorage: storage, onSesionExpirada: () async => sesionesExpiradas++);

      dio.httpClientAdapter = AdaptadorFalso((options) async {
        if (options.path.contains('/auth/refresh')) {
          return _json('{"access_token":"ACCESS_NUEVO","refresh_token":"REFRESH_NUEVO"}', 200);
        }
        if (options.headers['Authorization'] == 'Bearer ACCESS_NUEVO') return _json('{"detail":"falló"}', 500);
        return _json('{"detail":"vencido"}', 401);
      });

      await expectLater(
        dio.get<Map<String, dynamic>>('/protegido'),
        throwsA(isA<DioException>().having((e) => e.response?.statusCode, 'statusCode', 500)),
      );

      expect(sesionesExpiradas, 0);
      expect(storage.accessToken, 'ACCESS_NUEVO');
    });

    test('dos 401 concurrentes comparten un único refresh en curso', () async {
      final storage = TokenStorageFalso()
        ..accessToken = 'ACCESS_VIEJO'
        ..refreshToken = 'REFRESH_VALIDO';
      var llamadasRefresh = 0;
      final refreshCompleter = Completer<void>();

      final dio = buildDio(tokenStorage: storage, onSesionExpirada: () async {});

      dio.httpClientAdapter = AdaptadorFalso((options) async {
        if (options.path.contains('/auth/refresh')) {
          llamadasRefresh++;
          // Se demora a propósito para que las dos requests concurrentes
          // lleguen a pedir refresh antes de que el primero termine.
          await refreshCompleter.future;
          return _json('{"access_token":"ACCESS_NUEVO","refresh_token":"REFRESH_NUEVO"}', 200);
        }

        final auth = options.headers['Authorization'];
        if (auth == 'Bearer ACCESS_NUEVO') {
          return _json('{"ok":true}', 200);
        }
        return _json('{"detail":"vencido"}', 401);
      });

      final futuro1 = dio.get<Map<String, dynamic>>('/protegido');
      final futuro2 = dio.get<Map<String, dynamic>>('/protegido');

      // Deja que ambas requests entren al interceptor y pidan refresh.
      await Future<void>.delayed(const Duration(milliseconds: 50));
      refreshCompleter.complete();

      final resultados = await Future.wait([futuro1, futuro2]);

      expect(resultados[0].statusCode, 200);
      expect(resultados[1].statusCode, 200);
      expect(llamadasRefresh, 1);
    });
  });

  group('buildDio - qué peticiones llevan el JWT', () {
    Dio dioConToken(TokenStorageFalso storage, void Function(RequestOptions) alVer) {
      final dio = buildDio(tokenStorage: storage, onSesionExpirada: () async {});
      dio.httpClientAdapter = AdaptadorFalso((options) async {
        alVer(options);
        return _json('{"ok":true}', 200);
      });
      return dio;
    }

    test('la descarga del personal (/sincronizacion/paquete/catalogo) lleva el token aunque contenga "/catalogo"', () async {
      final storage = TokenStorageFalso()..accessToken = 'ACCESS';
      String? auth;
      final dio = dioConToken(storage, (o) => auth = o.headers['Authorization'] as String?);

      await dio.get<Map<String, dynamic>>('/sincronizacion/paquete/catalogo');

      expect(auth, 'Bearer ACCESS');
    });

    test('las demás rutas de /sincronizacion también llevan el token', () async {
      final storage = TokenStorageFalso()..accessToken = 'ACCESS';
      final vistas = <String?>[];
      final dio = dioConToken(storage, (o) => vistas.add(o.headers['Authorization'] as String?));

      for (final ruta in ['/sincronizacion/paquete', '/sincronizacion/paquete/stock', '/sincronizacion/paquete/clientes', '/sincronizacion/lote']) {
        await dio.get<Map<String, dynamic>>(ruta);
      }

      expect(vistas, everyElement('Bearer ACCESS'));
    });

    test('el detalle de variantes del carrito sigue llevando el token', () async {
      final storage = TokenStorageFalso()..accessToken = 'ACCESS';
      String? auth;
      final dio = dioConToken(storage, (o) => auth = o.headers['Authorization'] as String?);

      await dio.get<Map<String, dynamic>>('/catalogo/variantes/detalle');

      expect(auth, 'Bearer ACCESS');
    });

    test('el catálogo público de la tienda NO lleva el token', () async {
      final storage = TokenStorageFalso()..accessToken = 'ACCESS';
      String? auth = 'sin-valor';
      final dio = dioConToken(storage, (o) => auth = o.headers['Authorization'] as String?);

      await dio.get<Map<String, dynamic>>('/catalogo');

      expect(auth, isNull);
    });

    test('un 401 en la descarga del catálogo del personal dispara el refresh (no es una ruta pública)', () async {
      final storage = TokenStorageFalso()
        ..accessToken = 'ACCESS_VIEJO'
        ..refreshToken = 'REFRESH_VALIDO';
      var llamadasRefresh = 0;
      final dio = buildDio(tokenStorage: storage, onSesionExpirada: () async {});
      dio.httpClientAdapter = AdaptadorFalso((options) async {
        if (options.path.contains('/auth/refresh')) {
          llamadasRefresh++;
          return _json('{"access_token":"ACCESS_NUEVO","refresh_token":"REFRESH_NUEVO"}', 200);
        }
        if (options.headers['Authorization'] == 'Bearer ACCESS_NUEVO') return _json('{"ok":true}', 200);
        return _json('{"detail":"Token inválido o expirado"}', 401);
      });

      final respuesta = await dio.get<Map<String, dynamic>>('/sincronizacion/paquete/catalogo');

      expect(respuesta.statusCode, 200);
      expect(llamadasRefresh, 1);
    });
  });
}
