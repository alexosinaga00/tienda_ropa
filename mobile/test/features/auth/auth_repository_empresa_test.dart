import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/features/auth/data/auth_repository.dart';

import '../../helpers/token_storage_falso.dart';

class _Adaptador implements HttpClientAdapter {
  final List<RequestOptions> peticiones = [];

  @override
  Future<ResponseBody> fetch(RequestOptions options, Stream<Uint8List>? requestStream, Future<void>? cancelFuture) async {
    peticiones.add(options);
    final cuerpo = switch (options.path) {
      '/auth/login' => '{"access_token":"ACCESS","refresh_token":"REFRESH"}',
      '/auth/recuperar' => '{"mensaje":"ok","token_dev":"TOKEN"}',
      _ => '{}',
    };
    return ResponseBody.fromString(cuerpo, 200, headers: {
      Headers.contentTypeHeader: [Headers.jsonContentType],
    });
  }

  @override
  void close({bool force = false}) {}
}

({AuthRepository repositorio, _Adaptador adaptador, TokenStorageFalso tokens}) _armar({String? Function()? codigoEmpresa}) {
  final adaptador = _Adaptador();
  final dio = Dio(BaseOptions(baseUrl: 'http://test'))..httpClientAdapter = adaptador;
  final tokens = TokenStorageFalso();
  return (
    repositorio: AuthRepository(dio: dio, tokenStorage: tokens, codigoEmpresa: codigoEmpresa),
    adaptador: adaptador,
    tokens: tokens,
  );
}

void main() {
  group('AuthRepository.login', () {
    test('con codigoEmpresa manda "empresa" en el cuerpo y guarda los tokens', () async {
      final c = _armar(codigoEmpresa: () => 'chaski');

      await c.repositorio.login(email: 'a@b.com', password: 'clave12345');

      final peticion = c.adaptador.peticiones.single;
      expect(peticion.path, '/auth/login');
      expect(peticion.data, {'empresa': 'chaski', 'email': 'a@b.com', 'password': 'clave12345'});
      expect(c.tokens.accessToken, 'ACCESS');
      expect(c.tokens.refreshToken, 'REFRESH');
    });

    test('sin codigoEmpresa no manda "empresa"', () async {
      final c = _armar();

      await c.repositorio.login(email: 'a@b.com', password: 'clave12345');

      expect(c.adaptador.peticiones.single.data, {'email': 'a@b.com', 'password': 'clave12345'});
    });

    test('con un callback que devuelve null o vacío tampoco manda "empresa"', () async {
      for (final codigo in [null, '']) {
        final c = _armar(codigoEmpresa: () => codigo);

        await c.repositorio.login(email: 'a@b.com', password: 'clave12345');

        final cuerpo = c.adaptador.peticiones.single.data as Map<String, dynamic>;
        expect(cuerpo.containsKey('empresa'), isFalse, reason: 'codigo: "$codigo"');
      }
    });

    test('el código se lee en cada llamada: sigue a la tienda elegida', () async {
      String? codigo = 'uno';
      final c = _armar(codigoEmpresa: () => codigo);

      await c.repositorio.login(email: 'a@b.com', password: 'x');
      codigo = 'dos';
      await c.repositorio.login(email: 'a@b.com', password: 'x');

      expect(c.adaptador.peticiones.map((p) => (p.data as Map)['empresa']), ['uno', 'dos']);
    });

    test('el login no se marca como petición pública por extra (la ruta ya es pública en el interceptor)', () async {
      final c = _armar(codigoEmpresa: () => 'chaski');

      await c.repositorio.login(email: 'a@b.com', password: 'x');

      expect(c.adaptador.peticiones.single.extra['publica'], isNot(true));
      expect(c.adaptador.peticiones.single.path, '/auth/login');
    });
  });

  group('AuthRepository.registro', () {
    test('va a /public/{codigo}/registro con extra publica y el cuerpo del cliente', () async {
      final c = _armar(codigoEmpresa: () => 'chaski');

      await c.repositorio.registro(
        nombre: 'Ana',
        apellido: 'Pérez',
        email: 'ana@b.com',
        password: 'clave12345',
        telefono: '70000000',
      );

      final peticion = c.adaptador.peticiones.single;
      expect(peticion.method, 'POST');
      expect(peticion.path, '/public/chaski/registro');
      expect(peticion.extra['publica'], isTrue);
      expect(peticion.data, {
        'nombre': 'Ana',
        'apellido': 'Pérez',
        'email': 'ana@b.com',
        'password': 'clave12345',
        'telefono': '70000000',
      });
      expect((peticion.data as Map).containsKey('empresa'), isFalse, reason: 'la empresa va en la ruta, no en el cuerpo');
    });

    test('sin teléfono (o vacío) no manda telefono', () async {
      final c = _armar(codigoEmpresa: () => 'chaski');

      await c.repositorio.registro(nombre: 'Ana', apellido: 'P', email: 'a@b.com', password: 'x');
      await c.repositorio.registro(nombre: 'Ana', apellido: 'P', email: 'a@b.com', password: 'x', telefono: '');

      for (final peticion in c.adaptador.peticiones) {
        expect((peticion.data as Map).containsKey('telefono'), isFalse);
      }
    });

    test('sin tienda (el callback devuelve null o vacío) lanza ErrorApp "Elige una tienda para continuar."', () async {
      for (final codigo in [null, '']) {
        final c = _armar(codigoEmpresa: () => codigo);

        await expectLater(
          c.repositorio.registro(nombre: 'Ana', apellido: 'P', email: 'a@b.com', password: 'x'),
          throwsA(
            isA<ErrorApp>()
                .having((e) => e.tipo, 'tipo', TipoErrorApp.desconocido)
                .having((e) => e.mensaje, 'mensaje', 'Elige una tienda para continuar.'),
          ),
        );
        expect(c.adaptador.peticiones, isEmpty, reason: 'no se llama al servidor');
      }
    });

    test('sin callback usa /auth/registro (compatibilidad con las pruebas antiguas)', () async {
      final c = _armar();

      await c.repositorio.registro(nombre: 'Ana', apellido: 'P', email: 'a@b.com', password: 'x');

      final peticion = c.adaptador.peticiones.single;
      expect(peticion.path, '/auth/registro');
      expect(peticion.extra['publica'], isNot(true));
    });
  });

  group('AuthRepository.solicitarRecuperacion', () {
    test('con tienda manda "empresa" junto al correo y devuelve token_dev', () async {
      final c = _armar(codigoEmpresa: () => 'chaski');

      final token = await c.repositorio.solicitarRecuperacion('a@b.com');

      final peticion = c.adaptador.peticiones.single;
      expect(peticion.path, '/auth/recuperar');
      expect(peticion.data, {'empresa': 'chaski', 'email': 'a@b.com'});
      expect(token, 'TOKEN');
    });

    test('sin tienda no manda "empresa"', () async {
      for (final callback in <String? Function()?>[null, () => null, () => '']) {
        final c = _armar(codigoEmpresa: callback);

        await c.repositorio.solicitarRecuperacion('a@b.com');

        expect(c.adaptador.peticiones.single.data, {'email': 'a@b.com'});
      }
    });
  });
}
