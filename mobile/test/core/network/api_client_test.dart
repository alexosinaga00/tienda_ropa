import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/api_client.dart';
import 'package:mobile/core/network/dio_client.dart';
import 'package:mobile/core/network/error_app.dart';

import '../../helpers/token_storage_falso.dart';

/// Adaptador HTTP falso: guarda cada petición que recibe y responde con [responder].
class _Adaptador implements HttpClientAdapter {
  _Adaptador(this.responder);

  final Future<ResponseBody> Function(RequestOptions options) responder;
  final List<RequestOptions> peticiones = [];

  @override
  Future<ResponseBody> fetch(RequestOptions options, Stream<Uint8List>? requestStream, Future<void>? cancelFuture) {
    peticiones.add(options);
    return responder(options);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody _json(String cuerpo, int status) {
  return ResponseBody.fromString(cuerpo, status, headers: {
    Headers.contentTypeHeader: [Headers.jsonContentType],
  });
}

class _Item {
  const _Item(this.id, this.nombre);

  factory _Item.fromJson(Map<String, dynamic> json) => _Item(json['id'] as int, json['nombre'] as String);

  final int id;
  final String nombre;
}

/// Un Dio sin interceptores (no hay sesión que probar): solo el adaptador falso.
(DioApiClient, _Adaptador) _cliente({
  String? codigo = 'chaski',
  Future<ResponseBody> Function(RequestOptions options)? responder,
}) {
  final adaptador = _Adaptador(responder ?? (o) async => _json('{"id":1,"nombre":"x"}', 200));
  final dio = Dio(BaseOptions(baseUrl: 'http://test'))..httpClientAdapter = adaptador;
  return (DioApiClient(dio, codigoTienda: () => codigo), adaptador);
}

/// Un Dio de verdad ([buildDio], con token y refresh) y un cliente encima.
({DioApiClient cliente, _Adaptador adaptador, TokenStorageFalso storage, List<int> sesionesExpiradas}) _clienteConSesion(
  Future<ResponseBody> Function(RequestOptions options) responder, {
  String? codigo = 'chaski',
  String? access = 'ACCESS',
  String? refresh = 'REFRESH',
}) {
  final storage = TokenStorageFalso()
    ..accessToken = access
    ..refreshToken = refresh;
  final expiradas = <int>[];
  final dio = buildDio(tokenStorage: storage, onSesionExpirada: () async => expiradas.add(1));
  final adaptador = _Adaptador(responder);
  dio.httpClientAdapter = adaptador;
  return (
    cliente: DioApiClient(dio, codigoTienda: () => codigo),
    adaptador: adaptador,
    storage: storage,
    sesionesExpiradas: expiradas,
  );
}

void main() {
  group('DioApiClient - parseo', () {
    test('getLista convierte cada elemento con desde', () async {
      final (cliente, adaptador) = _cliente(
        responder: (o) async => _json('[{"id":1,"nombre":"a"},{"id":2,"nombre":"b"}]', 200),
      );

      final items = await cliente.getLista<_Item>('/cosas', desde: _Item.fromJson);

      expect(items.map((i) => i.id), [1, 2]);
      expect(items.map((i) => i.nombre), ['a', 'b']);
      expect(adaptador.peticiones.single.method, 'GET');
      expect(adaptador.peticiones.single.path, '/cosas');
    });

    test('getLista acepta una lista vacía', () async {
      final (cliente, _) = _cliente(responder: (o) async => _json('[]', 200));

      expect(await cliente.getLista<_Item>('/cosas', desde: _Item.fromJson), isEmpty);
    });

    test('getObjeto convierte el objeto y manda el query', () async {
      final (cliente, adaptador) = _cliente(responder: (o) async => _json('{"id":7,"nombre":"siete"}', 200));

      final item = await cliente.getObjeto<_Item>('/cosas/7', query: {'x': 1}, desde: _Item.fromJson);

      expect(item.id, 7);
      expect(item.nombre, 'siete');
      expect(adaptador.peticiones.single.queryParameters, {'x': 1});
    });

    test('postObjeto manda el cuerpo y el query, y convierte la respuesta', () async {
      final (cliente, adaptador) = _cliente(responder: (o) async => _json('{"id":3,"nombre":"tres"}', 201));

      final item = await cliente.postObjeto<_Item>(
        '/cosas',
        cuerpo: {'nombre': 'tres'},
        query: {'dry_run': true},
        desde: _Item.fromJson,
      );

      final peticion = adaptador.peticiones.single;
      expect(item.id, 3);
      expect(peticion.method, 'POST');
      expect(peticion.path, '/cosas');
      expect(peticion.queryParameters, {'dry_run': true});
      expect(peticion.data, {'nombre': 'tres'});
    });

    test('postVacio, putObjeto y eliminar usan el método y la ruta que corresponden', () async {
      final (cliente, adaptador) = _cliente(responder: (o) async => _json('{"id":1,"nombre":"x"}', 200));

      await cliente.postVacio('/accion', cuerpo: {'a': 1});
      final editado = await cliente.putObjeto<_Item>('/cosas/1', cuerpo: {'nombre': 'x'}, desde: _Item.fromJson);
      await cliente.eliminar('/cosas/1');

      expect(editado.nombre, 'x');
      expect(adaptador.peticiones.map((p) => '${p.method} ${p.path}'), ['POST /accion', 'PUT /cosas/1', 'DELETE /cosas/1']);
      expect(adaptador.peticiones.first.data, {'a': 1});
    });
  });

  group('DioApiClient - rutas públicas', () {
    test('publica: true reescribe la ruta a /public/{codigo}/...', () async {
      final (cliente, adaptador) = _cliente(responder: (o) async => _json('[]', 200));

      await cliente.getLista<_Item>('/catalogo/productos', desde: _Item.fromJson, publica: true);

      expect(adaptador.peticiones.single.path, '/public/chaski/catalogo/productos');
      expect(adaptador.peticiones.single.extra['publica'], isTrue);
    });

    test('la reescritura vale para getObjeto, postObjeto y postVacio', () async {
      final (cliente, adaptador) = _cliente();

      await cliente.getObjeto<_Item>('/tienda', desde: _Item.fromJson, publica: true);
      await cliente.postObjeto<_Item>('/registro', cuerpo: const {}, desde: _Item.fromJson, publica: true);
      await cliente.postVacio('/ia/eventos', cuerpo: const {}, publica: true);

      expect(adaptador.peticiones.map((p) => p.path), [
        '/public/chaski/tienda',
        '/public/chaski/registro',
        '/public/chaski/ia/eventos',
      ]);
      expect(adaptador.peticiones.every((p) => p.extra['publica'] == true), isTrue);
    });

    test('una ruta que ya empieza con /public/ no se reescribe', () async {
      final (cliente, adaptador) = _cliente(responder: (o) async => _json('[]', 200));

      await cliente.getLista<_Item>('/public/tiendas', desde: _Item.fromJson, publica: true);

      expect(adaptador.peticiones.single.path, '/public/tiendas');
      expect(adaptador.peticiones.single.extra['publica'], isTrue);
    });

    test('con publica: false la ruta no cambia aunque haya tienda y no se marca como pública', () async {
      final (cliente, adaptador) = _cliente();

      await cliente.getObjeto<_Item>('/cosas/1', desde: _Item.fromJson);

      expect(adaptador.peticiones.single.path, '/cosas/1');
      expect(adaptador.peticiones.single.extra['publica'], isNot(true));
    });

    test('el código de la tienda se lee en cada llamada, no al armar el cliente', () async {
      String? codigo = 'uno';
      final adaptador = _Adaptador((o) async => _json('{"id":1,"nombre":"x"}', 200));
      final dio = Dio(BaseOptions(baseUrl: 'http://test'))..httpClientAdapter = adaptador;
      final cliente = DioApiClient(dio, codigoTienda: () => codigo);

      await cliente.getObjeto<_Item>('/tienda', desde: _Item.fromJson, publica: true);
      codigo = 'dos';
      await cliente.getObjeto<_Item>('/tienda', desde: _Item.fromJson, publica: true);

      expect(adaptador.peticiones.map((p) => p.path), ['/public/uno/tienda', '/public/dos/tienda']);
    });

    for (final codigo in [null, '']) {
      test('sin tienda ($codigo) y publica: true lanza ErrorApp "Elige una tienda para continuar." sin llamar a la red', () async {
        final (cliente, adaptador) = _cliente(codigo: codigo);

        final llamadas = <Future<Object?> Function()>[
          () => cliente.getLista<_Item>('/catalogo', desde: _Item.fromJson, publica: true),
          () => cliente.getObjeto<_Item>('/catalogo', desde: _Item.fromJson, publica: true),
          () => cliente.postObjeto<_Item>('/x', desde: _Item.fromJson, publica: true),
          () => cliente.postVacio('/x', publica: true),
        ];
        for (final llamada in llamadas) {
          await expectLater(
            llamada(),
            throwsA(
              isA<ErrorApp>()
                  .having((e) => e.tipo, 'tipo', TipoErrorApp.desconocido)
                  .having((e) => e.mensaje, 'mensaje', 'Elige una tienda para continuar.'),
            ),
          );
        }
        expect(adaptador.peticiones, isEmpty);
      });
    }

    test('sin tienda, una ruta /public/ absoluta sí funciona', () async {
      final (cliente, adaptador) = _cliente(codigo: null, responder: (o) async => _json('[]', 200));

      await cliente.getLista<_Item>('/public/tiendas', desde: _Item.fromJson, publica: true);

      expect(adaptador.peticiones.single.path, '/public/tiendas');
    });

    test('sin tienda, las rutas privadas no necesitan código', () async {
      final (cliente, adaptador) = _cliente(codigo: null);

      await cliente.getObjeto<_Item>('/cosas/1', desde: _Item.fromJson);

      expect(adaptador.peticiones.single.path, '/cosas/1');
    });
  });

  group('DioApiClient con buildDio - Authorization y cabeceras', () {
    test('publica: true NO manda Authorization pero publica: false SÍ', () async {
      final sesion = _clienteConSesion((o) async => _json('{"id":1,"nombre":"x"}', 200));

      await sesion.cliente.getObjeto<_Item>('/tienda', desde: _Item.fromJson, publica: true);
      await sesion.cliente.getObjeto<_Item>('/auth/yo', desde: _Item.fromJson);

      final publica = sesion.adaptador.peticiones[0];
      final privada = sesion.adaptador.peticiones[1];
      expect(publica.path, '/public/chaski/tienda');
      expect(publica.headers.containsKey('Authorization'), isFalse);
      expect(privada.path, '/auth/yo');
      expect(privada.headers['Authorization'], 'Bearer ACCESS');
    });

    test('una ruta /public/ absoluta tampoco manda Authorization', () async {
      final sesion = _clienteConSesion((o) async => _json('[]', 200));

      await sesion.cliente.getLista<_Item>('/public/tiendas', desde: _Item.fromJson, publica: true);

      expect(sesion.adaptador.peticiones.single.headers.containsKey('Authorization'), isFalse);
    });

    test('ninguna petición lleva una cabecera con la empresa (ni clave ni valor)', () async {
      final sesion = _clienteConSesion((o) async => _json('{"id":1,"nombre":"x"}', 200));

      await sesion.cliente.getObjeto<_Item>('/tienda', desde: _Item.fromJson, publica: true);
      await sesion.cliente.getObjeto<_Item>('/auth/yo', desde: _Item.fromJson);
      await sesion.cliente.postObjeto<_Item>('/registro', cuerpo: const {}, desde: _Item.fromJson, publica: true);
      await sesion.cliente.postObjeto<_Item>('/ventas', cuerpo: const {}, desde: _Item.fromJson);
      await sesion.cliente.postVacio('/ia/eventos', cuerpo: const {}, publica: true);
      await sesion.cliente.putObjeto<_Item>('/cosas/1', cuerpo: const {}, desde: _Item.fromJson);
      await sesion.cliente.eliminar('/cosas/1');

      expect(sesion.adaptador.peticiones, hasLength(7));
      for (final peticion in sesion.adaptador.peticiones) {
        for (final cabecera in peticion.headers.entries) {
          final texto = '${cabecera.key}: ${cabecera.value}'.toLowerCase();
          expect(texto, isNot(contains('empresa')), reason: '${peticion.path} -> $texto');
          expect(texto, isNot(contains('tienda')), reason: '${peticion.path} -> $texto');
          expect(texto, isNot(contains('tenant')), reason: '${peticion.path} -> $texto');
          expect(texto, isNot(contains('chaski')), reason: '${peticion.path} -> $texto');
        }
      }
    });
  });

  group('DioApiClient - errores', () {
    test('un DioException con respuesta sale como ErrorApp traducido', () async {
      final (cliente, _) = _cliente(responder: (o) async => _json('{"detail":"Producto no encontrado"}', 404));

      await expectLater(
        cliente.getObjeto<_Item>('/cosas/9', desde: _Item.fromJson),
        throwsA(
          isA<ErrorApp>()
              .having((e) => e.tipo, 'tipo', TipoErrorApp.noEncontrado)
              .having((e) => e.estado, 'estado', 404)
              .having((e) => e.mensaje, 'mensaje', 'Producto no encontrado'),
        ),
      );
    });

    test('todos los métodos traducen el error: ningún DioException escapa', () async {
      final (cliente, _) = _cliente(responder: (o) async => _json('{"detail":"traza"}', 500));

      final llamadas = <Future<Object?> Function()>[
        () => cliente.getLista<_Item>('/x', desde: _Item.fromJson),
        () => cliente.getObjeto<_Item>('/x', desde: _Item.fromJson),
        () => cliente.postObjeto<_Item>('/x', desde: _Item.fromJson),
        () => cliente.postVacio('/x'),
        () => cliente.putObjeto<_Item>('/x', desde: _Item.fromJson),
        () => cliente.eliminar('/x'),
      ];
      for (final llamada in llamadas) {
        await expectLater(
          llamada(),
          throwsA(isA<ErrorApp>().having((e) => e.tipo, 'tipo', TipoErrorApp.servidor)),
        );
      }
    });

    test('un fallo de conexión sale como ErrorApp sinConexion', () async {
      final (cliente, _) = _cliente(
        responder: (o) async => throw DioException(requestOptions: o, type: DioExceptionType.connectionError),
      );

      await expectLater(
        cliente.getLista<_Item>('/x', desde: _Item.fromJson),
        throwsA(
          isA<ErrorApp>()
              .having((e) => e.tipo, 'tipo', TipoErrorApp.sinConexion)
              .having((e) => e.mensaje, 'mensaje', 'Sin conexión. Revisa tu internet e intenta de nuevo.'),
        ),
      );
    });

    test('un código funcional del backend llega como el tipo funcional', () async {
      final (cliente, _) = _cliente(
        responder: (o) async => _json('{"detail":"x","codigo":"plan_no_incluye_funcionalidad","mensaje":"m"}', 403),
      );

      await expectLater(
        cliente.getObjeto<_Item>('/analitica/panel', desde: _Item.fromJson),
        throwsA(isA<ErrorApp>().having((e) => e.tipo, 'tipo', TipoErrorApp.planNoIncluyeFuncionalidad)),
      );
    });

    test('una respuesta mal formada (campo con tipo incorrecto) sale como ErrorApp desconocido', () async {
      final (cliente, _) = _cliente(responder: (o) async => _json('{"id":"no-es-un-entero","nombre":"x"}', 200));

      await expectLater(
        cliente.getObjeto<_Item>('/x', desde: _Item.fromJson),
        throwsA(
          isA<ErrorApp>()
              .having((e) => e.tipo, 'tipo', TipoErrorApp.desconocido)
              .having((e) => e.mensaje, 'mensaje', 'La respuesta del servidor no se entendió.'),
        ),
      );
    });

    test('un elemento de la lista con tipo incorrecto sale como ErrorApp desconocido', () async {
      final (cliente, _) = _cliente(responder: (o) async => _json('[1, 2, 3]', 200));

      await expectLater(
        cliente.getLista<_Item>('/x', desde: _Item.fromJson),
        throwsA(isA<ErrorApp>().having((e) => e.tipo, 'tipo', TipoErrorApp.desconocido)),
      );
    });

    test('un objeto donde se esperaba una lista (y al revés) sale como ErrorApp desconocido', () async {
      final (objetoEnLista, _) = _cliente(responder: (o) async => _json('{"id":1,"nombre":"x"}', 200));
      final (listaEnObjeto, _) = _cliente(responder: (o) async => _json('[]', 200));

      await expectLater(
        objetoEnLista.getLista<_Item>('/x', desde: _Item.fromJson),
        throwsA(isA<ErrorApp>().having((e) => e.tipo, 'tipo', TipoErrorApp.desconocido)),
      );
      await expectLater(
        listaEnObjeto.getObjeto<_Item>('/x', desde: _Item.fromJson),
        throwsA(isA<ErrorApp>().having((e) => e.tipo, 'tipo', TipoErrorApp.desconocido)),
      );
    });

    test('un cuerpo vacío (204) donde se esperaba un objeto sale como ErrorApp desconocido', () async {
      final (cliente, _) = _cliente(responder: (o) async => ResponseBody.fromString('', 204));

      await expectLater(
        cliente.getObjeto<_Item>('/x', desde: _Item.fromJson),
        throwsA(isA<ErrorApp>().having((e) => e.tipo, 'tipo', TipoErrorApp.desconocido)),
      );
    });

    test('postVacio acepta un 204 sin cuerpo', () async {
      final (cliente, adaptador) = _cliente(responder: (o) async => ResponseBody.fromString('', 204));

      await cliente.postVacio('/accion');

      expect(adaptador.peticiones, hasLength(1));
    });
  });

  group('DioApiClient con buildDio - refresh de sesión', () {
    test('un 401 en una ruta privada refresca el token y reintenta igual que antes', () async {
      var refrescos = 0;
      final sesion = _clienteConSesion((o) async {
        if (o.path.contains('/auth/refresh')) {
          refrescos++;
          return _json('{"access_token":"ACCESS_NUEVO","refresh_token":"REFRESH_NUEVO"}', 200);
        }
        if (o.headers['Authorization'] == 'Bearer ACCESS_NUEVO') return _json('{"id":5,"nombre":"ok"}', 200);
        return _json('{"detail":"vencido"}', 401);
      }, access: 'ACCESS_VIEJO');

      final item = await sesion.cliente.getObjeto<_Item>('/protegido', desde: _Item.fromJson);

      expect(item.id, 5);
      expect(refrescos, 1);
      expect(sesion.storage.accessToken, 'ACCESS_NUEVO');
      expect(sesion.sesionesExpiradas, isEmpty);
    });

    test('si el refresh es rechazado, la ruta privada falla como ErrorApp noAutorizado y se cierra la sesión', () async {
      final sesion = _clienteConSesion((o) async => _json('{"detail":"vencido"}', 401));

      await expectLater(
        sesion.cliente.getObjeto<_Item>('/protegido', desde: _Item.fromJson),
        throwsA(isA<ErrorApp>().having((e) => e.tipo, 'tipo', TipoErrorApp.noAutorizado)),
      );

      expect(sesion.sesionesExpiradas, hasLength(1));
      expect(sesion.storage.accessToken, isNull);
    });

    test('un 401 en una ruta pública NO intenta refrescar ni toca la sesión', () async {
      var refrescos = 0;
      final sesion = _clienteConSesion((o) async {
        if (o.path.contains('/auth/refresh')) refrescos++;
        return _json('{"detail":"no autorizado"}', 401);
      });

      await expectLater(
        sesion.cliente.getObjeto<_Item>('/tienda', desde: _Item.fromJson, publica: true),
        throwsA(isA<ErrorApp>().having((e) => e.tipo, 'tipo', TipoErrorApp.noAutorizado)),
      );
      await expectLater(
        sesion.cliente.getLista<_Item>('/public/tiendas', desde: _Item.fromJson, publica: true),
        throwsA(isA<ErrorApp>().having((e) => e.tipo, 'tipo', TipoErrorApp.noAutorizado)),
      );

      expect(refrescos, 0);
      expect(sesion.sesionesExpiradas, isEmpty);
      expect(sesion.storage.vecesLimpiado, 0);
      expect(sesion.storage.accessToken, 'ACCESS');
      expect(sesion.storage.refreshToken, 'REFRESH');
    });
  });
}
