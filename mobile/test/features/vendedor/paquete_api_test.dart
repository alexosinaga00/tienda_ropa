import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/features/vendedor/data/paquete_api.dart';

import '../../helpers/api_client_falso.dart';
import 'apoyo_paquete.dart';

void main() {
  late ApiClientFalso api;
  late PaqueteApi paquete;

  setUp(() {
    api = ApiClientFalso();
    paquete = PaqueteApi(api);
  });

  group('una página', () {
    test('el manifiesto va a /sincronizacion/paquete, con sesión y sin parámetros', () async {
      api.responder('GET', '/sincronizacion/paquete', jsonManifiesto());

      final m = await paquete.manifiesto();

      expect(m.empresa.codigo, 'chaski');
      final llamada = api.llamadas.single;
      expect(llamada.metodo, 'GET');
      expect(llamada.ruta, '/sincronizacion/paquete');
      expect(llamada.query, isEmpty);
      expect(llamada.publica, isFalse);
    });

    test('el manifiesto acepta sucursal_id', () async {
      api.responder('GET', '/sincronizacion/paquete', jsonManifiesto());

      await paquete.manifiesto(sucursalId: 2);

      expect(api.llamadas.single.query, {'sucursal_id': 2});
    });

    test('el catálogo usa desde_id y limite', () async {
      api.responder('GET', '/sincronizacion/paquete/catalogo', jsonPaginaCatalogo([]));

      await paquete.paginaCatalogo(desdeId: 40, limite: 100);

      final llamada = api.llamadas.single;
      expect(llamada.ruta, '/sincronizacion/paquete/catalogo');
      expect(llamada.query, {'desde_id': 40, 'limite': 100});
      expect(llamada.publica, isFalse);
    });

    test('el stock usa sucursal_id, desde (ISO en UTC), desde_variante_id y limite', () async {
      api.responder('GET', '/sincronizacion/paquete/stock', jsonPaginaStock(3, []));

      await paquete.paginaStock(
        sucursalId: 3,
        desde: DateTime.utc(2026, 10, 30, 8, 15),
        desdeVarianteId: 77,
        limite: 250,
      );

      final llamada = api.llamadas.single;
      expect(llamada.ruta, '/sincronizacion/paquete/stock');
      expect(llamada.query, {
        'sucursal_id': 3,
        'desde': '2026-10-30T08:15:00Z',
        'desde_variante_id': 77,
        'limite': 250,
      });
    });

    test('el stock completo solo manda sucursal_id', () async {
      api.responder('GET', '/sincronizacion/paquete/stock', jsonPaginaStock(3, []));

      await paquete.paginaStock(sucursalId: 3);

      expect(api.llamadas.single.query, {'sucursal_id': 3});
    });

    test('los clientes usan desde_id y limite', () async {
      api.responder('GET', '/sincronizacion/paquete/clientes', jsonPaginaClientes([]));

      await paquete.paginaClientes(desdeId: 5, limite: 50);

      final llamada = api.llamadas.single;
      expect(llamada.ruta, '/sincronizacion/paquete/clientes');
      expect(llamada.query, {'desde_id': 5, 'limite': 50});
    });
  });

  group('todas las páginas', () {
    test('el catálogo sigue siguiente_desde_id hasta que termina y junta los productos', () async {
      api
        ..responder('GET', rutaCatalogo, jsonPaginaCatalogo([jsonProducto(1, 'A'), jsonProducto(2, 'B')], total: 5, siguiente: 2))
        ..responder('GET', rutaCatalogo, jsonPaginaCatalogo([jsonProducto(3, 'C'), jsonProducto(4, 'D')], total: 5, siguiente: 4))
        ..responder('GET', rutaCatalogo, jsonPaginaCatalogo([jsonProducto(5, 'E')], total: 5));

      final catalogo = await paquete.descargarCatalogo();

      expect(catalogo.productos.map((p) => p.id), [1, 2, 3, 4, 5]);
      final consultas = api.de('GET', rutaCatalogo).map((l) => l.query).toList();
      expect(consultas.map((q) => q!['desde_id']), [null, 2, 4]);
      expect(consultas.every((q) => q!['limite'] == 200), isTrue);
      expect(catalogo.generadoEn, DateTime.utc(2026, 10, 31, 10, 0, 1));
    });

    test('si la cantidad recibida no coincide con total, la descarga quedó incompleta', () async {
      api.responder('GET', rutaCatalogo, jsonPaginaCatalogo([jsonProducto(1, 'A')], total: 2));

      await expectLater(
        paquete.descargarCatalogo(),
        throwsA(isA<ErrorApp>().having((e) => e.mensaje, 'mensaje', 'La descarga quedó incompleta. Intenta de nuevo.')),
      );
    });

    test('un catálogo vacío con total 0 es válido', () async {
      api.responder('GET', rutaCatalogo, jsonPaginaCatalogo([], total: 0));

      final catalogo = await paquete.descargarCatalogo();

      expect(catalogo.productos, isEmpty);
    });

    test('el tope de páginas corta un servidor que nunca termina', () async {
      final corto = PaqueteApi(api, topePaginas: 3);
      for (var i = 1; i <= 6; i++) {
        api.responder('GET', rutaCatalogo, jsonPaginaCatalogo([jsonProducto(i, 'P$i')], total: 6, siguiente: i));
      }

      await expectLater(corto.descargarCatalogo(), throwsA(isA<ErrorApp>()));
      expect(api.de('GET', rutaCatalogo), hasLength(3));
    });

    test('un cursor que no avanza también corta (no pide la misma página para siempre)', () async {
      api
        ..responder('GET', rutaCatalogo, jsonPaginaCatalogo([jsonProducto(1, 'A')], total: 9, siguiente: 1))
        ..responder('GET', rutaCatalogo, jsonPaginaCatalogo([jsonProducto(2, 'B')], total: 9, siguiente: 1));

      await expectLater(paquete.descargarCatalogo(), throwsA(isA<ErrorApp>()));
      expect(api.de('GET', rutaCatalogo), hasLength(2));
    });

    test('el stock pagina por desde_variante_id, repite desde en cada página y guarda el generado_en de la primera', () async {
      final desde = DateTime.utc(2026, 10, 30, 12);
      api
        ..responder(
          'GET',
          rutaStock,
          jsonPaginaStock(2, [jsonItemStock(1, 4), jsonItemStock(2, 5)], incremental: true, siguiente: 2, generadoEn: '2026-10-31T10:00:00Z'),
        )
        ..responder(
          'GET',
          rutaStock,
          jsonPaginaStock(2, [jsonItemStock(3, 6)], incremental: true, generadoEn: '2026-10-31T10:00:09Z'),
        );

      final stock = await paquete.descargarStock(sucursalId: 2, desde: desde);

      expect(stock.items.map((i) => i.varianteId), [1, 2, 3]);
      expect(stock.incremental, isTrue);
      expect(stock.generadoEn, DateTime.utc(2026, 10, 31, 10));
      final consultas = api.de('GET', rutaStock).map((l) => l.query!).toList();
      expect(consultas.map((q) => q['desde']), ['2026-10-30T12:00:00Z', '2026-10-30T12:00:00Z']);
      expect(consultas.map((q) => q['desde_variante_id']), [null, 2]);
      expect(consultas.every((q) => q['sucursal_id'] == 2), isTrue);
    });

    test('si el servidor contesta el stock de otra sucursal, la descarga queda incompleta', () async {
      api.responder('GET', rutaStock, jsonPaginaStock(9, [jsonItemStock(1, 4)]));

      await expectLater(paquete.descargarStock(sucursalId: 2), throwsA(isA<ErrorApp>()));
    });

    test('los clientes se juntan y se verifica el total', () async {
      api
        ..responder('GET', rutaClientes, jsonPaginaClientes([jsonCliente(1, 'Ana'), jsonCliente(2, 'Luis')], total: 3, siguiente: 2))
        ..responder('GET', rutaClientes, jsonPaginaClientes([jsonCliente(3, 'Eva')], total: 3));

      final clientes = await paquete.descargarClientes();

      expect(clientes.clientes.map((c) => c.id), [1, 2, 3]);
      expect(api.de('GET', rutaClientes).map((l) => l.query!['desde_id']), [null, 2]);
    });

    test('clientes: un total que no cuadra deja la descarga incompleta', () async {
      api.responder('GET', rutaClientes, jsonPaginaClientes([jsonCliente(1, 'Ana')], total: 4));

      await expectLater(paquete.descargarClientes(), throwsA(isA<ErrorApp>()));
    });

    test('un error del servidor (plan sin la función) llega tal cual como ErrorApp', () async {
      const plan = ErrorApp(tipo: TipoErrorApp.planNoIncluyeFuncionalidad, mensaje: 'Tu plan no incluye esta función.');
      api.responder('GET', rutaCatalogo, plan);

      await expectLater(
        paquete.descargarCatalogo(),
        throwsA(isA<ErrorApp>().having((e) => e.tipo, 'tipo', TipoErrorApp.planNoIncluyeFuncionalidad)),
      );
    });

    test('una versión de contrato mayor en cualquier página corta la descarga', () async {
      api.responder('GET', rutaCatalogo, jsonPaginaCatalogo([jsonProducto(1, 'A')], version: '2.0'));

      await expectLater(
        paquete.descargarCatalogo(),
        throwsA(isA<ErrorApp>().having((e) => e.mensaje, 'mensaje', 'Actualiza la app para sincronizar.')),
      );
    });
  });
}
