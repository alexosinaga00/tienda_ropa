import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/features/tienda/data/tienda_repository.dart';
import 'package:mobile/features/tienda/models/tienda.dart';
import 'package:mobile/features/tienda/state/tienda_controller.dart';

import '../../helpers/api_client_falso.dart';
import '../../helpers/sesion_storage_falso.dart';

const _guardada = Tienda(codigo: 'chaski', nombre: 'Chaski Sport', logoUrl: null, colorAcento: '#112233');

const _rutaTienda = '/public/chaski/tienda';

ErrorApp _error(int estado) => ErrorApp.desde(
  DioException(
    requestOptions: RequestOptions(path: _rutaTienda),
    type: DioExceptionType.badResponse,
    response: Response(requestOptions: RequestOptions(path: _rutaTienda), statusCode: estado),
  ),
);

ErrorApp _sinConexion() =>
    ErrorApp.desde(DioException(requestOptions: RequestOptions(path: _rutaTienda), type: DioExceptionType.connectionError));

Map<String, dynamic> _json(Tienda t) => t.toJson();

class _Contexto {
  _Contexto({Tienda? guardada})
    : storage = SesionStorageFalso(tienda: guardada),
      api = ApiClientFalso();

  final SesionStorageFalso storage;
  final ApiClientFalso api;
  int cierresDeSesion = 0;

  TiendaController crear() {
    final controlador = TiendaController(
      storage: storage,
      repositorio: () => TiendaRepository(api),
      alTiendaDesaparecida: () async => cierresDeSesion++,
    );
    addTearDown(controlador.dispose);
    return controlador;
  }
}

void main() {
  group('TiendaController - carga', () {
    test('al crearlo todavía no está cargada y luego carga la tienda guardada', () async {
      final ctx = _Contexto(guardada: _guardada);
      final controlador = ctx.crear();

      expect(controlador.state.cargada, isFalse);

      await controlador.cargadaFuture;

      expect(controlador.state.cargada, isTrue);
      expect(controlador.state.tienda, _guardada);
      expect(controlador.state.aviso, isNull);
    });

    test('sin tienda guardada queda cargada con tienda null', () async {
      final ctx = _Contexto();
      final controlador = ctx.crear();

      await controlador.cargadaFuture;

      expect(controlador.state.cargada, isTrue);
      expect(controlador.state.tienda, isNull);
    });
  });

  group('TiendaController - elegir y olvidar', () {
    test('elegir guarda la tienda en el almacenamiento y la deja en el estado', () async {
      final ctx = _Contexto();
      final controlador = ctx.crear();
      await controlador.cargadaFuture;

      await controlador.elegir(_guardada);

      expect(ctx.storage.tienda, _guardada);
      expect(controlador.state.tienda, _guardada);
      expect(controlador.state.cargada, isTrue);
    });

    test('elegir otra tienda reemplaza a la anterior', () async {
      final ctx = _Contexto(guardada: _guardada);
      final controlador = ctx.crear();
      await controlador.cargadaFuture;
      const otra = Tienda(codigo: 'andina', nombre: 'Boutique Andina');

      await controlador.elegir(otra);

      expect(ctx.storage.tienda, otra);
      expect(controlador.state.tienda, otra);
    });

    test('olvidar borra la tienda del almacenamiento y del estado', () async {
      final ctx = _Contexto(guardada: _guardada);
      final controlador = ctx.crear();
      await controlador.cargadaFuture;

      await controlador.olvidar();

      expect(ctx.storage.tienda, isNull);
      expect(ctx.storage.vecesBorrada, 1);
      expect(controlador.state.tienda, isNull);
      expect(controlador.state.cargada, isTrue);
    });
  });

  group('TiendaController.validarGuardada', () {
    test('sin tienda guardada no consulta al servidor', () async {
      final ctx = _Contexto();
      final controlador = ctx.crear();

      await controlador.validarGuardada();

      expect(ctx.api.llamadas, isEmpty);
      expect(ctx.cierresDeSesion, 0);
    });

    test('con un 404 olvida la tienda, cierra la sesión y deja el aviso de tienda desaparecida', () async {
      final ctx = _Contexto(guardada: _guardada);
      ctx.api.responder('GET', _rutaTienda, _error(404));
      final controlador = ctx.crear();

      await controlador.validarGuardada();

      expect(ctx.storage.tienda, isNull);
      expect(ctx.storage.vecesBorrada, 1);
      expect(ctx.cierresDeSesion, 1);
      expect(controlador.state.tienda, isNull);
      expect(controlador.state.cargada, isTrue);
      expect(controlador.state.aviso, avisoTiendaDesaparecida);
    });

    test('consulta la ruta pública de la tienda guardada', () async {
      final ctx = _Contexto(guardada: _guardada);
      ctx.api.responder('GET', _rutaTienda, _json(_guardada));
      final controlador = ctx.crear();

      await controlador.validarGuardada();

      final llamada = ctx.api.de('GET', _rutaTienda).single;
      expect(llamada.publica, isTrue);
    });

    for (final entrada in {
      'sin conexión': _sinConexion(),
      'un error 500': _error(500),
      'un error 503': _error(503),
    }.entries) {
      test('con ${entrada.key} conserva la tienda, el almacenamiento y la sesión', () async {
        final ctx = _Contexto(guardada: _guardada);
        ctx.api.responder('GET', _rutaTienda, entrada.value);
        final controlador = ctx.crear();

        await controlador.validarGuardada();

        expect(controlador.state.tienda, _guardada);
        expect(controlador.state.aviso, isNull);
        expect(ctx.storage.tienda, _guardada);
        expect(ctx.storage.vecesBorrada, 0);
        expect(ctx.cierresDeSesion, 0);
      });
    }

    test('con un 200 actualiza nombre, logo y color y lo guarda', () async {
      final ctx = _Contexto(guardada: _guardada);
      const vigente = Tienda(
        codigo: 'chaski',
        nombre: 'Chaski Sport Bolivia',
        logoUrl: 'https://img.test/logo.png',
        colorAcento: '#AABBCC',
      );
      ctx.api.responder('GET', _rutaTienda, _json(vigente));
      final controlador = ctx.crear();

      await controlador.validarGuardada();

      expect(controlador.state.tienda, vigente);
      expect(controlador.state.tienda!.nombre, 'Chaski Sport Bolivia');
      expect(controlador.state.tienda!.logoUrl, 'https://img.test/logo.png');
      expect(controlador.state.tienda!.colorAcento, '#AABBCC');
      expect(controlador.state.aviso, isNull);
      expect(ctx.storage.tienda, vigente);
      expect(ctx.cierresDeSesion, 0);
    });

    test('con un 200 sin cambios no reescribe el almacenamiento', () async {
      final ctx = _Contexto(guardada: _guardada);
      ctx.api.responder('GET', _rutaTienda, _json(_guardada));
      final controlador = ctx.crear();
      final almacenada = ctx.storage.tienda;

      await controlador.validarGuardada();

      expect(identical(ctx.storage.tienda, almacenada), isTrue);
      expect(controlador.state.tienda, _guardada);
      expect(controlador.state.aviso, isNull);
    });

    test('con disponible: false deja el aviso de tienda sin suscripción y conserva la tienda', () async {
      final ctx = _Contexto(guardada: _guardada);
      const sinSuscripcion = Tienda(
        codigo: 'chaski',
        nombre: 'Chaski Sport',
        colorAcento: '#112233',
        disponible: false,
      );
      ctx.api.responder('GET', _rutaTienda, _json(sinSuscripcion));
      final controlador = ctx.crear();

      await controlador.validarGuardada();

      expect(controlador.state.aviso, avisoTiendaSinSuscripcion);
      expect(controlador.state.tienda, sinSuscripcion);
      expect(controlador.state.tienda!.disponible, isFalse);
      expect(ctx.storage.tienda, sinSuscripcion);
      expect(ctx.cierresDeSesion, 0);
    });

    test('una validación posterior con la tienda disponible quita el aviso', () async {
      final ctx = _Contexto(guardada: _guardada);
      ctx.api.responder('GET', _rutaTienda, _json(const Tienda(codigo: 'chaski', nombre: 'Chaski Sport', disponible: false)));
      ctx.api.responder('GET', _rutaTienda, _json(_guardada));
      final controlador = ctx.crear();

      await controlador.validarGuardada();
      expect(controlador.state.aviso, avisoTiendaSinSuscripcion);

      await controlador.validarGuardada();
      expect(controlador.state.aviso, isNull);
      expect(controlador.state.tienda, _guardada);
    });
  });

  group('TiendaController.limpiarAviso', () {
    test('quita el aviso y conserva la tienda', () async {
      final ctx = _Contexto(guardada: _guardada);
      ctx.api.responder('GET', _rutaTienda, _json(const Tienda(codigo: 'chaski', nombre: 'Chaski Sport', disponible: false)));
      final controlador = ctx.crear();
      await controlador.validarGuardada();
      expect(controlador.state.aviso, isNotNull);

      controlador.limpiarAviso();

      expect(controlador.state.aviso, isNull);
      expect(controlador.state.tienda, isNotNull);
      expect(controlador.state.cargada, isTrue);
    });

    test('quita el aviso de tienda desaparecida', () async {
      final ctx = _Contexto(guardada: _guardada);
      ctx.api.responder('GET', _rutaTienda, _error(404));
      final controlador = ctx.crear();
      await controlador.validarGuardada();

      controlador.limpiarAviso();

      expect(controlador.state.aviso, isNull);
      expect(controlador.state.tienda, isNull);
    });

    test('sin aviso no cambia el estado', () async {
      final ctx = _Contexto(guardada: _guardada);
      final controlador = ctx.crear();
      await controlador.cargadaFuture;
      final antes = controlador.state;

      controlador.limpiarAviso();

      expect(identical(controlador.state, antes), isTrue);
    });
  });
}
