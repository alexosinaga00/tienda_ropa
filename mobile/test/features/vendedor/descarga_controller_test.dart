import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/api_client.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/network/providers.dart';
import 'package:mobile/features/vendedor/data/descarga_repository.dart';
import 'package:mobile/features/vendedor/state/catalogo_local_providers.dart';
import 'package:mobile/features/vendedor/state/descarga_catalogo_service.dart';
import 'package:mobile/features/vendedor/state/descarga_controller.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/api_client_falso.dart';
import '../../helpers/base_local_falsa.dart';
import '../../helpers/conectividad_falsa.dart';
import 'apoyo_operaciones.dart';
import 'apoyo_paquete.dart';

/// Un [ApiClientFalso] que, si hay [puerta], se detiene al pedir el manifiesto hasta que se abra (para ver una descarga
/// "en curso").
class ApiConPuerta extends ApiClientFalso {
  Completer<void>? puerta;
  final llegada = Completer<void>();

  @override
  Future<T> getObjeto<T>(String ruta, {Map<String, dynamic>? query, required DesdeJson<T> desde, bool publica = false}) async {
    if (ruta == rutaManifiesto && puerta != null) {
      if (!llegada.isCompleted) llegada.complete();
      await puerta!.future;
    }
    return super.getObjeto(ruta, query: query, desde: desde, publica: publica);
  }
}

const _sinConexion = ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: 'Sin conexión.');

void main() {
  late Database db;
  late ApiConPuerta api;
  late RelojManual reloj;
  late ConectividadFalsa conectividad;
  late ProviderContainer c;

  /// Monta el contenedor con la base real, el servicio de descarga REAL sobre el [ApiClientFalso] y la sesión del usuario 7.
  void montar({bool enLinea = true, bool conSesion = true}) {
    conectividad = ConectividadFalsa(enLinea: enLinea);
    addTearDown(conectividad.cerrar);
    c = contenedorLocal(
      db,
      auth: conSesion ? sesionDe(personalDe()) : sinSesion,
      reloj: reloj,
      conectividad: conectividad,
      extra: [apiClientProvider.overrideWithValue(api)],
    );
  }

  DescargaController controlador() => c.read(descargaControllerProvider.notifier);
  DescargaEstado estado() => c.read(descargaControllerProvider);
  int terminadas() => c.read(descargaTerminadaProvider);
  int manifiestos() => api.de('GET', rutaManifiesto).length;

  setUp(() async {
    db = await abrirBaseDePrueba();
    addTearDown(db.close);
    api = ApiConPuerta();
    reloj = RelojManual(DateTime.utc(2026, 10, 31, 12));
  });

  group('actualizar', () {
    test('exitosa: incrementa descargaTerminadaProvider y deja el estado sin error', () async {
      prepararServidor(api);
      montar();

      await controlador().actualizar();

      expect(terminadas(), 1);
      expect(estado().descargando, isFalse);
      expect(estado().mensaje, isNull);
      expect(estado().esError, isFalse);
      expect(await contar(db, 'producto'), 2);
      expect(await contar(db, 'cliente_minimo'), 2);
    });

    test('mientras descarga el estado dice "descargando" y al terminar deja de decirlo', () async {
      prepararServidor(api);
      api.puerta = Completer<void>();
      montar();

      final futuro = controlador().actualizar();
      await api.llegada.future;
      expect(estado().descargando, isTrue);

      api.puerta!.complete();
      await futuro;

      expect(estado().descargando, isFalse);
    });

    test('la primera vez fija como activa la sucursal que eligió el servicio', () async {
      prepararServidor(api);
      montar();
      expect(await c.read(sucursalActivaProvider.future), isNull);

      await controlador().actualizar();

      expect(await DescargaRepositorySqlite(db).sucursalActiva(1, 7), 1);
      expect(await c.read(sucursalActivaProvider.future), 1);
    });

    test('la primera vez elige la primera sucursal que no es depósito', () async {
      prepararServidor(
        api,
        manifiesto: jsonManifiesto(sucursales: [jsonSucursal(1, deposito: true), jsonSucursal(2)]),
        paginasStock: [jsonPaginaStock(2, [jsonItemStock(100, 5)])],
        sucursalId: 2,
      );
      montar();

      await controlador().actualizar();

      expect(await DescargaRepositorySqlite(db).sucursalActiva(1, 7), 2);
      expect(await stockDe(db, 2), {100: 5});
    });

    test('con la sucursal ya elegida, una segunda actualización no la cambia', () async {
      prepararServidor(api);
      api.responder('GET', rutaStock, jsonPaginaStock(2, [jsonItemStock(100, 9)]));
      montar();
      await controlador().actualizar();
      await DescargaRepositorySqlite(db).fijarSucursalActiva(1, 7, 2);
      c.invalidate(sucursalActivaProvider);

      await controlador().actualizar();

      expect(await DescargaRepositorySqlite(db).sucursalActiva(1, 7), 2);
      expect(terminadas(), 2);
    });

    test('fallida sin datos anteriores: deja el mensaje con esError y no incrementa', () async {
      api.responder('GET', rutaManifiesto, _sinConexion);
      montar();

      await controlador().actualizar();

      expect(estado().descargando, isFalse);
      expect(estado().esError, isTrue);
      expect(estado().mensaje, mensajeSinDatosDescargados);
      expect(terminadas(), 0);
    });

    test('fallida con datos anteriores: el mensaje dice que sigues viendo los datos del día', () async {
      prepararServidor(api);
      api.responder('GET', rutaManifiesto, _sinConexion);
      montar();
      await controlador().actualizar();
      expect(estado().esError, isFalse);

      await controlador().actualizar();

      expect(estado().esError, isTrue);
      expect(estado().mensaje, contains('sigues viendo los datos del'));
      expect(terminadas(), 1, reason: 'la descarga fallida no avisa a las listas');
      expect(await contar(db, 'producto'), 2, reason: 'los datos anteriores quedan intactos');
    });

    test('tras una falla se puede reintentar y la siguiente exitosa limpia el error', () async {
      api.responder('GET', rutaManifiesto, _sinConexion);
      prepararServidor(api);
      montar();
      await controlador().actualizar();
      expect(estado().esError, isTrue);

      await controlador().actualizar();

      expect(estado().esError, isFalse);
      expect(estado().mensaje, isNull);
      expect(terminadas(), 1);
    });

    test('pospuesta: con operaciones enviadas deja el motivo, sin error y sin descargar', () async {
      prepararServidor(api);
      montar();
      await controlador().actualizar();
      await sembrarVentaPendiente(db, operacionId: 'op-1', varianteId: 100, estado: 'enviada');

      await controlador().actualizar();

      expect(estado().mensaje, mensajeOperacionesEnviadas);
      expect(estado().esError, isFalse);
      expect(estado().descargando, isFalse);
      expect(terminadas(), 1);
      expect(manifiestos(), 1, reason: 'ni siquiera se pidió el manifiesto');
    });

    test('un fallo inesperado del servicio deja un mensaje genérico con error', () async {
      conectividad = ConectividadFalsa();
      addTearDown(conectividad.cerrar);
      c = contenedorLocal(
        db,
        auth: sesionDe(personalDe()),
        reloj: reloj,
        conectividad: conectividad,
        extra: [descargaServiceProvider.overrideWith((ref) async => throw StateError('base rota'))],
      );

      await controlador().actualizar();

      expect(estado().esError, isTrue);
      expect(estado().mensaje, 'No se pudo actualizar. Intenta de nuevo.');
      expect(estado().descargando, isFalse);
    });

    test('no hay dos descargas a la vez: la segunda llamada no hace nada', () async {
      prepararServidor(api);
      api.puerta = Completer<void>();
      montar();

      final primera = controlador().actualizar();
      await api.llegada.future;
      await controlador().actualizar();
      await controlador().actualizar(forzarCompleta: true);
      api.puerta!.complete();
      await primera;

      expect(manifiestos(), 1);
      expect(terminadas(), 1);
    });

    test('sin sesión no descarga nada', () async {
      prepararServidor(api);
      montar(conSesion: false);

      await controlador().actualizar();

      expect(api.llamadas, isEmpty);
      expect(terminadas(), 0);
      expect(estado().descargando, isFalse);
    });
  });

  group('alEntrar', () {
    test('con conexión descarga', () async {
      prepararServidor(api);
      montar();

      await controlador().alEntrar();

      expect(manifiestos(), 1);
      expect(terminadas(), 1);
    });

    test('sin conexión no descarga ni toca la red', () async {
      prepararServidor(api);
      montar(enLinea: false);

      await controlador().alEntrar();

      expect(api.llamadas, isEmpty);
      expect(terminadas(), 0);
      expect(estado().mensaje, isNull);
    });

    test('al volver la conexión ya se puede descargar', () async {
      prepararServidor(api);
      montar(enLinea: false);
      await controlador().alEntrar();
      expect(api.llamadas, isEmpty);

      conectividad.emitir(true);
      await controlador().alEntrar();

      expect(manifiestos(), 1);
    });
  });

  group('alRecuperarConexion', () {
    test('si nunca se descargó, descarga', () async {
      prepararServidor(api);
      montar();

      await controlador().alRecuperarConexion();

      expect(manifiestos(), 1);
      expect(terminadas(), 1);
    });

    test('con la última descarga de hace menos de 15 minutos NO descarga', () async {
      prepararServidor(api);
      montar();
      await controlador().actualizar();
      reloj.actual = reloj.actual.add(const Duration(minutes: 14, seconds: 59));

      await controlador().alRecuperarConexion();

      expect(manifiestos(), 1);
      expect(terminadas(), 1);
    });

    test('con exactamente 15 minutos sí descarga', () async {
      prepararServidor(api);
      montar();
      await controlador().actualizar();
      reloj.actual = reloj.actual.add(DescargaController.intervaloRecuperacion);

      await controlador().alRecuperarConexion();

      expect(manifiestos(), 2);
      expect(terminadas(), 2);
    });

    test('con la última descarga de hace más de 15 minutos sí descarga', () async {
      prepararServidor(api);
      montar();
      await controlador().actualizar();
      reloj.actual = reloj.actual.add(const Duration(hours: 3));

      await controlador().alRecuperarConexion();

      expect(manifiestos(), 2);
      expect(terminadas(), 2);
    });

    test('el intervalo es de 15 minutos', () {
      expect(DescargaController.intervaloRecuperacion, const Duration(minutes: 15));
    });
  });

  group('alCambiarSucursal', () {
    test('guarda la sucursal y, si nunca se bajó, la descarga', () async {
      prepararServidor(api);
      api.responder('GET', rutaStock, jsonPaginaStock(2, [jsonItemStock(100, 9)]));
      montar();
      await controlador().actualizar();
      expect(await c.read(sucursalActivaProvider.future), 1);

      await controlador().alCambiarSucursal(2);

      final repositorio = DescargaRepositorySqlite(db);
      expect(await repositorio.sucursalActiva(1, 7), 2);
      expect(await c.read(sucursalActivaProvider.future), 2);
      expect(await repositorio.ultimaDescarga(1, 2), isNotNull);
      expect(await stockDe(db, 2), {100: 9});
      expect(manifiestos(), 2);
      expect(terminadas(), 2);
    });

    test('si esa sucursal ya se bajó antes, solo la guarda y refresca (no descarga)', () async {
      prepararServidor(api);
      api.responder('GET', rutaStock, jsonPaginaStock(2, [jsonItemStock(100, 9)]));
      montar();
      await controlador().actualizar();
      await controlador().alCambiarSucursal(2);
      final antes = manifiestos();
      final terminadasAntes = terminadas();

      await controlador().alCambiarSucursal(1);

      expect(await DescargaRepositorySqlite(db).sucursalActiva(1, 7), 1);
      expect(await c.read(sucursalActivaProvider.future), 1);
      expect(manifiestos(), antes);
      expect(terminadas(), terminadasAntes + 1, reason: 'refresca la vigencia con la sucursal nueva');
    });

    test('sin conexión y nunca bajada: la guarda y no descarga', () async {
      prepararServidor(api);
      montar();
      await controlador().actualizar();
      conectividad.emitir(false);

      await controlador().alCambiarSucursal(2);

      expect(await DescargaRepositorySqlite(db).sucursalActiva(1, 7), 2);
      expect(manifiestos(), 1);
      expect(await DescargaRepositorySqlite(db).ultimaDescarga(1, 2), isNull);
      expect(terminadas(), 2, reason: 'se refresca igual para que se vea la elección');
    });

    test('sin sesión no hace nada', () async {
      prepararServidor(api);
      montar(conSesion: false);

      await controlador().alCambiarSucursal(2);

      expect(api.llamadas, isEmpty);
      expect(await contar(db, 'meta', donde: "clave LIKE 'sucursal_activa%'"), 0);
      expect(terminadas(), 0);
    });
  });
}
