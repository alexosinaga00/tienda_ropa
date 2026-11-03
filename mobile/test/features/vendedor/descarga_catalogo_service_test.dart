import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/api_client.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/utils/fecha_servidor.dart';
import 'package:mobile/features/vendedor/data/almacen_paquete.dart';
import 'package:mobile/features/vendedor/data/descarga_repository.dart';
import 'package:mobile/features/vendedor/data/paquete_api.dart';
import 'package:mobile/features/vendedor/state/descarga_catalogo_service.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/api_client_falso.dart';
import '../../helpers/base_local_falsa.dart';
import 'apoyo_paquete.dart';

/// Un [ApiClientFalso] que ejecuta [gancho] antes de contestar una ruta (para frenar o intervenir a mitad de la descarga).
class ApiClientConGancho extends ApiClientFalso {
  Future<void> Function(String ruta)? gancho;

  @override
  Future<T> getObjeto<T>(String ruta, {Map<String, dynamic>? query, required DesdeJson<T> desde, bool publica = false}) async {
    await gancho?.call(ruta);
    return super.getObjeto(ruta, query: query, desde: desde, publica: publica);
  }
}

class AlmacenQueFalla implements AlmacenPaquete {
  @override
  Future<void> aplicar(PaqueteDescargado paquete, {required int usuarioId}) async {
    throw StateError('disco lleno');
  }
}

ErrorApp _errorHttp(int estado, Map<String, Object?> datos) {
  final opciones = RequestOptions(path: '/sincronizacion/paquete');
  return ErrorApp.desde(
    DioException(
      requestOptions: opciones,
      type: DioExceptionType.badResponse,
      response: Response(requestOptions: opciones, statusCode: estado, data: datos),
    ),
  );
}

const _sinConexion = ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: 'Sin conexión.');

Map<String, Object?> _operacionEnviada(String id) => {
  'operacion_id': id,
  'empresa_id': 1,
  'sucursal_id': 1,
  'usuario_id': 7,
  'tipo': 'venta_contado',
  'estado': 'enviada',
  'payload': '{}',
  'version_contrato': 1,
  'fecha_operacion': '2026-10-31T09:00:00Z',
  'creada_en': '2026-10-31T09:00:00Z',
};

// IMPORTANTE: el ApiClientFalso entrega las respuestas en el orden en que se preparan y repite la última, así que en cada
// prueba se preparan todas las respuestas (descarga 1, 2, ...) antes de la primera llamada.
void main() {
  late Database db;
  late ApiClientConGancho api;
  late RelojManual reloj;
  late DescargaRepositorySqlite repo;
  late DescargaCatalogoService servicio;

  setUp(() async {
    db = await abrirBaseDePrueba();
    addTearDown(db.close);
    api = ApiClientConGancho();
    reloj = RelojManual(DateTime.utc(2026, 10, 31, 12));
    repo = DescargaRepositorySqlite(db);
    servicio = DescargaCatalogoService(PaqueteApi(api), AlmacenPaqueteSqlite(db, reloj), repo, reloj);
  });

  Future<ResultadoDescarga> descargar({int sucursalId = 1, bool forzar = false}) =>
      servicio.descargar(sucursalId: sucursalId, usuarioId: 7, forzarCompleta: forzar);

  /// Una descarga posterior: otro instante del servidor, un precio nuevo y solo el stock que cambió.
  void prepararOtra({String generadoEn = '2026-10-31T11:00:02Z'}) {
    prepararServidor(
      api,
      manifiesto: jsonManifiesto(generadoEn: '2026-10-31T11:00:00Z'),
      paginasCatalogo: [
        jsonPaginaCatalogo([
          jsonProducto(10, 'Polera Básica', variantes: [jsonVariante(100, precio: '80.00'), jsonVariante(101, talla: 2)]),
          jsonProducto(11, 'Camisa Lino'),
        ]),
      ],
      paginasStock: [
        jsonPaginaStock(1, [jsonItemStock(100, 9)], incremental: true, generadoEn: generadoEn),
      ],
      paginasClientes: const [],
    );
  }

  group('descarga correcta', () {
    test('la primera es completa: stock sin desde y con clientes', () async {
      prepararServidor(api);

      final r = await descargar();

      final ok = r as DescargaExitosa;
      expect(ok.completa, isTrue);
      expect(ok.productos, 2);
      expect(ok.milisegundos, greaterThanOrEqualTo(0));
      expect(api.de('GET', rutaStock).single.query, {'sucursal_id': 1, 'limite': 500});
      expect(api.de('GET', rutaClientes), hasLength(1));
      expect(await contar(db, 'producto'), 2);
      expect(await stockDe(db, 1), {100: 5, 101: 3, 110: 2, 111: 0});
      expect(await contar(db, 'cliente_minimo'), 2);
      final ultima = (await repo.ultimaDescarga(1, 1))!;
      expect(ultima.completo, isTrue);
      expect(ultima.descargadoEn, DateTime.utc(2026, 10, 31, 12));
      expect(await repo.avisoHoras(1), 12);
    });

    test('la segunda manda desde igual al generado_en guardado y no vuelve a bajar clientes', () async {
      prepararServidor(api);
      prepararOtra();
      await descargar();

      final r = await descargar();

      expect((r as DescargaExitosa).completa, isFalse);
      final consulta = api.de('GET', rutaStock).last.query!;
      expect(consulta['desde'], '2026-10-31T10:00:02Z');
      expect(consulta['sucursal_id'], 1);
      expect(api.de('GET', rutaClientes), hasLength(1));
      // Delta: cambió el 100; el resto del stock conserva lo anterior. El precio nuevo del catálogo se aplicó.
      expect(await stockDe(db, 1), {100: 9, 101: 3, 110: 2, 111: 0});
      expect((await db.query('variante', where: 'id = 100')).single['precio_centavos'], 8000);
      expect((await repo.ultimaDescarga(1, 1))!.generadoEn, DateTime.utc(2026, 10, 31, 11, 0, 2));
    });

    test('la tercera usa el generado_en de la segunda', () async {
      prepararServidor(api);
      prepararOtra();
      prepararOtra(generadoEn: '2026-10-31T12:00:02Z');
      await descargar();
      await descargar();

      await descargar();

      expect(api.de('GET', rutaStock).map((l) => l.query!['desde']), [null, '2026-10-31T10:00:02Z', '2026-10-31T11:00:02Z']);
    });

    test('forzarCompleta ignora el delta y vuelve a bajar todo, clientes incluidos', () async {
      prepararServidor(api);
      prepararServidor(api, paginasStock: [jsonPaginaStock(1, [jsonItemStock(100, 1)], generadoEn: '2026-10-31T13:00:00Z')]);
      await descargar();

      final r = await descargar(forzar: true);

      expect((r as DescargaExitosa).completa, isTrue);
      expect(api.de('GET', rutaStock).last.query!.containsKey('desde'), isFalse);
      expect(api.de('GET', rutaClientes), hasLength(2));
      expect(await stockDe(db, 1), {100: 1}); // completo = reemplaza
    });

    test('si cambió el contrato o el esquema desde la última descarga, la siguiente es completa', () async {
      prepararServidor(api);
      prepararOtra();
      await descargar();
      await db.update('meta', {'valor': 'contrato0-esquema0'}, where: 'clave = ?', whereArgs: ['formato_descarga:1:1']);

      final r = await descargar();

      expect((r as DescargaExitosa).completa, isTrue);
      expect(api.de('GET', rutaStock).last.query!.containsKey('desde'), isFalse);
    });

    test('la primera descarga de OTRA sucursal es completa y no toca el stock de la primera', () async {
      prepararServidor(api);
      prepararServidor(api, paginasStock: [jsonPaginaStock(2, [jsonItemStock(100, 44)])]);
      await descargar();

      final r = await descargar(sucursalId: 2);

      expect((r as DescargaExitosa).completa, isTrue);
      expect(api.de('GET', rutaStock).last.query!.containsKey('desde'), isFalse);
      expect(await stockDe(db, 1), {100: 5, 101: 3, 110: 2, 111: 0});
      expect(await stockDe(db, 2), {100: 44});
    });

    test('registra inicio y fin sin datos personales ni nombres de productos', () async {
      final lineas = <String>[];
      final original = debugPrint;
      debugPrint = (String? mensaje, {int? wrapWidth}) {
        if (mensaje != null) lineas.add(mensaje);
      };
      addTearDown(() => debugPrint = original);
      prepararServidor(api);

      await descargar();

      final texto = lineas.join('\n');
      expect(texto, contains('descarga_catalogo inicio sucursal=1 tipo=completa'));
      expect(texto, contains('resultado=ok'));
      expect(texto, contains('productos=2'));
      for (final prohibido in ['Ana', 'Luis', 'Polera', 'Camisa', 'SKU-']) {
        expect(texto, isNot(contains(prohibido)), reason: 'no debe registrar "$prohibido"');
      }
    });
  });

  group('se pospone', () {
    test('si hay operaciones enviadas no pide nada al servidor', () async {
      prepararServidor(api);
      await descargar();
      await db.insert('operacion_pendiente', _operacionEnviada('op-1'));
      final llamadasAntes = api.llamadas.length;

      final r = await descargar();

      expect((r as DescargaPospuesta).motivo, mensajeOperacionesEnviadas);
      expect(api.llamadas.length, llamadasAntes);
    });

    test('si una operación pasa a enviada mientras se descarga, no se guarda nada', () async {
      prepararServidor(api);
      prepararOtra();
      await descargar();
      api.gancho = (ruta) async {
        if (ruta == rutaStock) await db.insert('operacion_pendiente', _operacionEnviada('op-2'));
      };

      final r = await descargar();

      expect(r, isA<DescargaPospuesta>());
      expect((await db.query('variante', where: 'id = 100')).single['precio_centavos'], 7500);
      expect(await stockDe(db, 1), {100: 5, 101: 3, 110: 2, 111: 0});
    });

    test('nunca hay dos descargas a la vez', () async {
      prepararServidor(api);
      prepararOtra();
      final puerta = Completer<void>();
      api.gancho = (ruta) => ruta == rutaManifiesto ? puerta.future : Future.value();

      final primera = descargar();
      await Future<void>.delayed(Duration.zero);
      expect(servicio.descargando, isTrue);

      final segunda = await descargar();
      expect((segunda as DescargaPospuesta).motivo, 'Ya se está actualizando.');

      puerta.complete();
      expect(await primera, isA<DescargaExitosa>());
      expect(servicio.descargando, isFalse);
      expect(api.de('GET', rutaManifiesto), hasLength(1));

      // Terminada la primera, otra descarga ya puede empezar.
      api.gancho = null;
      expect(await descargar(), isA<DescargaExitosa>());
      expect(api.de('GET', rutaManifiesto), hasLength(2));
    });

    test('dos descargas lanzadas en el mismo instante: solo una corre', () async {
      prepararServidor(api);

      final resultados = await Future.wait([descargar(), descargar()]);

      expect(resultados.whereType<DescargaExitosa>(), hasLength(1));
      expect(resultados.whereType<DescargaPospuesta>(), hasLength(1));
      expect(api.de('GET', rutaManifiesto), hasLength(1));
    });
  });

  group('errores', () {
    test('una versión de contrato mayor pide actualizar la app y no guarda nada', () async {
      prepararServidor(api, manifiesto: jsonManifiesto(version: '2.0'));

      final f = await descargar() as DescargaFallida;

      expect(f.mensaje, 'Actualiza la app para sincronizar.');
      expect(f.hayDatosAnteriores, isFalse);
      expect(await contar(db, 'producto'), 0);
    });

    test('una versión mayor en el catálogo (con manifiesto bueno) también', () async {
      prepararServidor(api, paginasCatalogo: [jsonPaginaCatalogo([jsonProducto(10, 'A')], version: '2.0')]);

      final f = await descargar() as DescargaFallida;

      expect(f.mensaje, 'Actualiza la app para sincronizar.');
      expect(await contar(db, 'empresa'), 0);
    });

    test('sin conexión deja los datos anteriores y dice de qué fecha son', () async {
      prepararServidor(api);
      api.responder('GET', rutaManifiesto, _sinConexion);
      await descargar();
      reloj.actual = DateTime.utc(2026, 11, 2);

      final f = await descargar() as DescargaFallida;

      final fecha = formatearFechaHora(DateTime.utc(2026, 10, 31, 12).toLocal());
      expect(f.mensaje, 'No se pudo actualizar; sigues viendo los datos del $fecha');
      expect(f.hayDatosAnteriores, isTrue);
      expect(f.ultimaDescarga!.descargadoEn, DateTime.utc(2026, 10, 31, 12));
      expect(await stockDe(db, 1), {100: 5, 101: 3, 110: 2, 111: 0});
      expect(await contar(db, 'producto', donde: 'activo = 1'), 2);
    });

    test('un error 5xx se trata igual: lo anterior sigue ahí', () async {
      prepararServidor(api);
      api.responder('GET', rutaManifiesto, _errorHttp(503, {'detail': 'caído'}));
      await descargar();

      final f = await descargar() as DescargaFallida;

      expect(f.mensaje, startsWith('No se pudo actualizar; sigues viendo los datos del '));
      expect(f.hayDatosAnteriores, isTrue);
    });

    test('sin conexión y sin descarga previa: todavía no hay datos', () async {
      api.responder('GET', rutaManifiesto, _sinConexion);

      final f = await descargar() as DescargaFallida;

      expect(f.mensaje, 'No se pudo actualizar y todavía no hay datos descargados.');
      expect(f.hayDatosAnteriores, isFalse);
      expect(f.ultimaDescarga, isNull);
    });

    test('un plan sin la función (403) muestra el mensaje de ErrorApp', () async {
      api.responder('GET', rutaManifiesto, _errorHttp(403, {'detail': 'plan_no_incluye_funcionalidad', 'codigo': 'plan_no_incluye_funcionalidad'}));

      final f = await descargar() as DescargaFallida;

      expect(f.mensaje, 'Tu plan no incluye esta función. Consulta con el administrador de tu empresa.');
    });

    test('una suscripción inactiva (403) muestra el mensaje de ErrorApp', () async {
      api.responder('GET', rutaManifiesto, _errorHttp(403, {'detail': 'suscripcion_no_activa', 'codigo': 'suscripcion_no_activa'}));

      final f = await descargar() as DescargaFallida;

      expect(f.mensaje, 'La suscripción de esta tienda no está activa. Contacta al administrador de la tienda.');
    });

    test('una sucursal que no es de la persona se rechaza antes de bajar el catálogo', () async {
      prepararServidor(api);

      final f = await descargar(sucursalId: 99) as DescargaFallida;

      expect(f.mensaje, 'Esa sucursal no está autorizada para tu cuenta.');
      expect(api.de('GET', rutaCatalogo), isEmpty);
    });

    test('un catálogo incompleto falla y conserva lo anterior', () async {
      prepararServidor(api);
      prepararServidor(api, paginasCatalogo: [jsonPaginaCatalogo([jsonProducto(10, 'Polera Básica')], total: 2)]);
      await descargar();

      final f = await descargar() as DescargaFallida;

      expect(f.mensaje, 'La descarga quedó incompleta. Intenta de nuevo.');
      expect(f.hayDatosAnteriores, isTrue);
      expect(await contar(db, 'producto', donde: 'activo = 1'), 2);
    });

    test('si el stock falla después de bajar el catálogo, el catálogo nuevo tampoco se guarda', () async {
      prepararServidor(api);
      api.responder('GET', rutaStock, const ErrorApp(tipo: TipoErrorApp.servidor, mensaje: 'x'));
      prepararServidor(
        api,
        paginasCatalogo: [
          jsonPaginaCatalogo([jsonProducto(10, 'Polera RARA', variantes: [jsonVariante(100, precio: '1.00')])]),
        ],
        paginasStock: const [],
      );
      await descargar();

      final f = await descargar() as DescargaFallida;

      expect(f.hayDatosAnteriores, isTrue);
      expect((await db.query('producto', where: 'id = 10')).single['nombre'], 'Polera Básica');
      expect((await db.query('variante', where: 'id = 100')).single['precio_centavos'], 7500);
    });

    test('un error al guardar no escapa: se informa y el servicio queda libre', () async {
      prepararServidor(api);
      final roto = DescargaCatalogoService(PaqueteApi(api), AlmacenQueFalla(), repo, reloj);

      final r = await roto.descargar(sucursalId: 1, usuarioId: 7);

      expect((r as DescargaFallida).mensaje, mensajeNoSePudoGuardar);
      expect(roto.descargando, isFalse);
    });

    test('después de un fallo la descarga queda libre para reintentar', () async {
      api.responder('GET', rutaManifiesto, _sinConexion);
      prepararServidor(api);

      expect(await descargar(), isA<DescargaFallida>());
      expect(await descargar(), isA<DescargaExitosa>());
    });
  });
}
