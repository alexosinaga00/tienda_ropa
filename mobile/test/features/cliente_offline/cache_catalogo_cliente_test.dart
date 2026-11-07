import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/features/catalogo/data/catalogo_repository.dart';
import 'package:mobile/features/catalogo/data/referencia_repository.dart';
import 'package:mobile/features/catalogo/models/filtros_catalogo.dart';
import 'package:mobile/features/cliente_offline/config/cliente_offline_config.dart';
import 'package:mobile/features/cliente_offline/data/cache_catalogo_cliente.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/api_client_falso.dart';
import '../../helpers/cliente_offline_apoyo.dart';
import '../../helpers/siembra_operaciones.dart';

Map<String, dynamic> _item(int id, String nombre, {String precio = '199.00', String? imagen}) => {
  'id': id,
  'codigo': 'P$id',
  'nombre': nombre,
  'categoria_id': 1,
  'genero': 'unisex',
  'precio_base': precio,
  'admite_probador': false,
  'imagen_principal': imagen,
};

Map<String, dynamic> _detalle(int id, String nombre) => {
  'id': id,
  'codigo': 'P$id',
  'nombre': nombre,
  'descripcion': 'Algodón',
  'categoria_id': 1,
  'material_id': null,
  'temporada_id': null,
  'coleccion_id': null,
  'genero': 'unisex',
  'precio_base': '199.00',
  'admite_probador': false,
  'variantes': [
    {
      'id': 100 + id,
      'talla_id': 2,
      'color_id': 3,
      'sku': 'SKU-$id',
      'precio_efectivo': '199.00',
      'cantidad_disponible': 5,
    },
  ],
  'imagenes': [
    {'id': 1, 'url': 'https://x/$id.jpg', 'color_id': 3, 'es_principal': true, 'orden': 0},
  ],
};

void main() {
  late Database db;
  late RelojDePrueba reloj;
  String? tienda;
  late CacheCatalogoClienteSqlite cache;

  setUp(() async {
    db = await abrirBaseClienteDePrueba();
    reloj = RelojDePrueba(DateTime.utc(2026, 11, 6, 12));
    tienda = 'chaski';
    cache = CacheCatalogoClienteSqlite(() async => db, () => tienda, reloj);
  });

  tearDown(() => db.close());

  group('CacheCatalogoClienteSqlite', () {
    test('guarda las prendas vistas y las devuelve en el orden del listado', () async {
      await cache.guardarItems([_item(3, 'Tercera'), _item(1, 'Primera')], primeraPosicion: 0);
      await cache.guardarItems([_item(2, 'Segunda')], primeraPosicion: 2);

      final items = await cache.leerItems();

      // Orden de posición: 0 -> Tercera, 1 -> Primera, 2 -> Segunda.
      expect(items.map((i) => i.nombre), ['Tercera', 'Primera', 'Segunda']);
      expect(items.first.precioBase, 199.0);
      expect(items.first.imagenPrincipal, isNull);
    });

    test('una búsqueda no cambia el lugar que la prenda ya tenía y agrega las nuevas al final', () async {
      await cache.guardarItems([_item(1, 'Polera'), _item(2, 'Camisa')], primeraPosicion: 0);

      await cache.guardarItems([_item(2, 'Camisa'), _item(9, 'Chamarra')]);

      expect((await cache.leerItems()).map((i) => i.nombre), ['Polera', 'Camisa', 'Chamarra']);
    });

    test('busca por texto sin importar mayúsculas ni tildes', () async {
      await cache.guardarItems([
        _item(1, 'Camisa Ñandú'),
        _item(2, 'Polera'),
        _item(3, 'CAMISÁ lino'),
      ], primeraPosicion: 0);

      expect((await cache.leerItems(texto: 'camisa')).map((i) => i.id), [1, 3]);
      expect((await cache.leerItems(texto: 'LINO')).map((i) => i.id), [3]);
      expect((await cache.leerItems(texto: 'NANDU')).map((i) => i.id), [1]);
      expect(await cache.leerItems(texto: 'zapato'), isEmpty);
      expect(await cache.leerItems(texto: '  '), hasLength(3));
    });

    test('no se mezcla entre tiendas', () async {
      await cache.guardarItems([_item(1, 'De chaski')], primeraPosicion: 0);
      tienda = 'andina';
      await cache.guardarItems([_item(2, 'De andina')], primeraPosicion: 0);

      expect((await cache.leerItems()).map((i) => i.nombre), ['De andina']);
      tienda = 'chaski';
      expect((await cache.leerItems()).map((i) => i.nombre), ['De chaski']);
    });

    test('sin tienda elegida no guarda ni lee', () async {
      tienda = null;

      await expectLater(cache.guardarItems([_item(1, 'X')]), throwsA(isA<StateError>()));
      await expectLater(cache.leerItems(), throwsA(isA<StateError>()));
    });

    test('nunca guarda más del tope: se queda con las primeras del listado', () async {
      await cache.guardarItems([
        for (var i = 0; i < maxItemsEnCache + 20; i++) _item(i + 1, 'Prenda ${i + 1}'),
      ], primeraPosicion: 0);

      final items = await cache.leerItems();

      expect(items, hasLength(maxItemsEnCache));
      expect(items.first.id, 1);
      expect(items.last.id, maxItemsEnCache);
    });

    test('guarda el detalle con sus variantes y fotos, y lo lee', () async {
      await cache.guardarDetalle(5, _detalle(5, 'Polera'));

      final d = (await cache.leerDetalle(5))!;

      expect(d.nombre, 'Polera');
      expect(d.variantes.single.id, 105);
      expect(d.variantes.single.tallaId, 2);
      expect(d.variantes.single.precioEfectivo, 199.0);
      expect(d.imagenes.single.url, 'https://x/5.jpg');
      expect(await cache.leerDetalle(6), isNull);
    });

    test('los detalles también tienen tope: se borran los más viejos', () async {
      for (var i = 1; i <= maxDetallesEnCache + 3; i++) {
        reloj.avanzar(const Duration(seconds: 1));
        await cache.guardarDetalle(i, _detalle(i, 'P$i'));
      }

      expect(await cache.leerDetalle(1), isNull);
      expect(await cache.leerDetalle(3), isNull);
      expect(await cache.leerDetalle(4), isNotNull);
      expect(await cache.leerDetalle(maxDetallesEnCache + 3), isNotNull);
    });

    test('las referencias se reemplazan enteras: lo que el servidor ya no manda desaparece', () async {
      await cache.guardarReferencias(cacheSucursal, [
        {'id': 2, 'codigo': 'S2', 'nombre': 'Sur', 'es_deposito': false},
        {'id': 1, 'codigo': 'S1', 'nombre': 'Centro', 'es_deposito': false},
      ]);
      expect((await cache.leerReferencias(cacheSucursal)).map((s) => s['nombre']), ['Centro', 'Sur']);

      await cache.guardarReferencias(cacheSucursal, [
        {'id': 1, 'codigo': 'S1', 'nombre': 'Centro', 'es_deposito': false},
      ]);

      expect((await cache.leerReferencias(cacheSucursal)).map((s) => s['nombre']), ['Centro']);
      expect(await cache.leerReferencias(cacheTalla), isEmpty);
    });

    test('una fila dañada no tumba el resto', () async {
      await cache.guardarItems([_item(1, 'Buena')], primeraPosicion: 0);
      await db.insert('cli_cache', {
        'tienda': 'chaski',
        'tipo': 'item',
        'clave': '2',
        'orden': 1,
        'json': '{no es json',
        'guardado_en': '2026-11-06T12:00:00Z',
      });

      expect((await cache.leerItems()).map((i) => i.nombre), ['Buena']);
    });
  });

  group('CatalogoRepository con cache', () {
    late ApiClientFalso api;
    late CatalogoRepository repo;

    setUp(() {
      api = ApiClientFalso();
      repo = CatalogoRepository(api, cache: cache);
    });

    test('con conexión recuerda lo que lista, busca y detalla', () async {
      api
        ..responder('GET', '/catalogo', [_item(1, 'Polera'), _item(2, 'Camisa')])
        ..responder('GET', '/catalogo/1', _detalle(1, 'Polera'));

      final items = await repo.listar(pagina: 1, tamanio: 20);
      final detalle = await repo.detalle(1);

      expect(items, hasLength(2));
      expect(detalle.nombre, 'Polera');
      expect((await cache.leerItems()).map((i) => i.nombre), ['Polera', 'Camisa']);
      expect((await cache.leerDetalle(1))!.nombre, 'Polera');
    });

    test('sin conexión muestra lo recordado, paginado como el servidor', () async {
      await cache.guardarItems([for (var i = 1; i <= 5; i++) _item(i, 'Prenda $i')], primeraPosicion: 0);
      api.responder('GET', '/catalogo', errorSinRed);

      final pagina1 = await repo.listar(pagina: 1, tamanio: 2);
      final pagina3 = await repo.listar(pagina: 3, tamanio: 2);
      final pagina4 = await repo.listar(pagina: 4, tamanio: 2);

      expect(pagina1.map((i) => i.id), [1, 2]);
      expect(pagina3.map((i) => i.id), [5]);
      expect(pagina4, isEmpty);
    });

    test('también con el servidor caído (5xx)', () async {
      await cache.guardarItems([_item(1, 'Polera')], primeraPosicion: 0);
      api.responder('GET', '/catalogo', errorHttp(503));

      expect((await repo.listar(pagina: 1, tamanio: 20)).single.nombre, 'Polera');
    });

    test('sin conexión y sin nada recordado, el error original llega a la pantalla', () async {
      api.responder('GET', '/catalogo', errorSinRed);

      await expectLater(repo.listar(pagina: 1, tamanio: 20), throwsA(same(errorSinRed)));
    });

    test('un error que NO es de red (404, 422) no se tapa con lo recordado', () async {
      await cache.guardarItems([_item(1, 'Polera')], primeraPosicion: 0);
      api.responder('GET', '/catalogo', errorHttp(422));

      await expectLater(repo.listar(pagina: 1, tamanio: 20), throwsA(isA<ErrorApp>()));
    });

    test('buscar sin conexión filtra por texto entre lo recordado', () async {
      await cache.guardarItems([
        _item(1, 'Polera azul'),
        _item(2, 'Camisa'),
        _item(3, 'Polera roja'),
      ], primeraPosicion: 0);
      api.responder('GET', '/catalogo/buscar', errorSinRed);

      final resultado = await repo.buscar(const FiltrosCatalogo(texto: 'polera'), pagina: 1, tamanio: 20);

      expect(resultado.map((i) => i.nombre), ['Polera azul', 'Polera roja']);
    });

    test('el detalle sin conexión sale de lo recordado', () async {
      await cache.guardarDetalle(1, _detalle(1, 'Polera'));
      api.responder('GET', '/catalogo/1', errorSinRed);

      final d = await repo.detalle(1);

      expect(d.nombre, 'Polera');
      expect(d.variantes, hasLength(1));
    });

    test('el detalle sin conexión de una prenda que nunca se vio dice claro que no estaba guardada', () async {
      api.responder('GET', '/catalogo/9', errorSinRed);

      await expectLater(
        repo.detalle(9),
        throwsA(
          isA<ErrorApp>()
              .having((e) => e.tipo, 'tipo', TipoErrorApp.sinConexion)
              .having((e) => e.mensaje, 'mensaje', mensajePrendaNoGuardada),
        ),
      );
    });

    test('un 404 del detalle no se tapa con lo recordado', () async {
      await cache.guardarDetalle(1, _detalle(1, 'Polera'));
      api.responder('GET', '/catalogo/1', const ErrorApp(tipo: TipoErrorApp.noEncontrado, mensaje: 'x', estado: 404));

      await expectLater(repo.detalle(1), throwsA(isA<ErrorApp>().having((e) => e.estado, 'estado', 404)));
    });

    test('si la base local falla, la consulta con conexión sigue funcionando', () async {
      await db.close();
      api.responder('GET', '/catalogo', [_item(1, 'Polera')]);

      final items = await repo.listar(pagina: 1, tamanio: 20);

      expect(items.single.nombre, 'Polera');
      db = await abrirBaseClienteDePrueba(); // para el tearDown
    });

    test('sin cache (como en las pruebas viejas) se comporta igual que antes', () async {
      final sinCache = CatalogoRepository(api);
      api.responder('GET', '/catalogo', errorSinRed);

      await expectLater(sinCache.listar(pagina: 1, tamanio: 20), throwsA(isA<ErrorApp>()));
    });
  });

  group('ReferenciaRepository con cache', () {
    test('recuerda tallas, colores y sucursales y las da sin conexión', () async {
      final api = ApiClientFalso();
      final repo = ReferenciaRepository(api, cache: cache);
      api
        ..responder('GET', '/tallas', [
          {'id': 2, 'codigo': 'M', 'orden': 1},
        ])
        ..responder('GET', '/colores', [
          {'id': 3, 'nombre': 'Azul', 'codigo_hex': '#0000ff'},
        ])
        ..responder('GET', '/sucursales', [
          {'id': 1, 'codigo': 'S1', 'nombre': 'Centro', 'es_deposito': false},
          {'id': 9, 'codigo': 'D1', 'nombre': 'Depósito', 'es_deposito': true},
        ]);
      await repo.tallas();
      await repo.colores();
      await repo.sucursales();

      final sinRed = ApiClientFalso()
        ..responder('GET', '/tallas', errorSinRed)
        ..responder('GET', '/colores', errorSinRed)
        ..responder('GET', '/sucursales', errorSinRed);
      final repoSinRed = ReferenciaRepository(sinRed, cache: cache);

      expect((await repoSinRed.tallas()).single.codigo, 'M');
      expect((await repoSinRed.colores()).single.nombre, 'Azul');
      final sucursales = await repoSinRed.sucursales();
      expect(sucursales.map((s) => s.nombre), ['Centro', 'Depósito']);
      expect(sucursales.last.esDeposito, isTrue);
    });

    test('sin conexión y sin nada guardado, el error llega', () async {
      final api = ApiClientFalso()..responder('GET', '/sucursales', errorSinRed);
      final repo = ReferenciaRepository(api, cache: cache);

      await expectLater(repo.sucursales(), throwsA(isA<ErrorApp>()));
    });
  });
}
