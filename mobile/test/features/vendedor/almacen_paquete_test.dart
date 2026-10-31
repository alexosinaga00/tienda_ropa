import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/features/vendedor/data/almacen_paquete.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';
import 'apoyo_paquete.dart';

void main() {
  late Database db;
  late RelojManual reloj;
  late AlmacenPaqueteSqlite almacen;

  setUp(() async {
    db = await abrirBaseDePrueba();
    addTearDown(db.close);
    reloj = RelojManual();
    almacen = AlmacenPaqueteSqlite(db, reloj);
  });

  Future<void> aplicar(PaqueteDescargado p, {int usuarioId = 7}) => almacen.aplicar(p, usuarioId: usuarioId);

  Future<Map<String, Object?>> fila(String tabla, String donde, List<Object?> args) async =>
      (await db.query(tabla, where: donde, whereArgs: args)).single;

  group('descarga completa', () {
    test('inserta empresa, sucursales, horarios, referencias, catálogo, stock y clientes', () async {
      await aplicar(armarPaquete(clientes: [jsonCliente(1, 'Ana', ci: '111'), jsonCliente(2, 'Luis', ci: '222')]));

      expect(await contar(db, 'empresa'), 1);
      expect(await contar(db, 'sucursal'), 2);
      expect(await contar(db, 'sucursal_horario'), 4);
      expect(await contar(db, 'sucursal_autorizada', donde: 'usuario_id = 7'), 2);
      expect(await contar(db, 'categoria'), 1);
      expect(await contar(db, 'talla'), 4);
      expect(await contar(db, 'color'), 1);
      expect(await contar(db, 'producto'), 2);
      expect(await contar(db, 'variante'), 4);
      expect(await contar(db, 'cliente_minimo'), 2);
      expect(await stockDe(db, 1), {100: 5, 101: 3, 110: 2, 111: 0});
      expect(await db.rawQuery('PRAGMA foreign_key_check'), isEmpty);
    });

    test('guarda los precios en centavos y el nombre de búsqueda sin tildes', () async {
      await aplicar(
        armarPaquete(
          productos: [
            jsonProducto(10, 'Polera Básica Ñandú', variantes: [jsonVariante(100, precio: '75.50', descuento: '5.25', barras: '779')]),
          ],
          stock: [],
        ),
      );

      final producto = await fila('producto', 'id = 10', []);
      expect(producto['nombre'], 'Polera Básica Ñandú');
      expect(producto['nombre_busqueda'], 'polera basica nandu');
      expect(producto['empresa_id'], 1);
      expect(producto['activo'], 1);
      final variante = await fila('variante', 'id = 100', []);
      expect(variante['precio_centavos'], 7550);
      expect(variante['descuento_centavos'], 525);
      expect(variante['codigo_barras'], '779');
      expect(variante['activo'], 1);
    });

    test('aplicar el MISMO paquete dos veces no duplica nada', () async {
      final paquete = armarPaquete(clientes: [jsonCliente(1, 'Ana', ci: '111')]);

      await aplicar(paquete);
      await aplicar(paquete);

      expect(await contar(db, 'empresa'), 1);
      expect(await contar(db, 'sucursal'), 2);
      expect(await contar(db, 'sucursal_horario'), 4);
      expect(await contar(db, 'sucursal_autorizada'), 2);
      expect(await contar(db, 'producto'), 2);
      expect(await contar(db, 'variante'), 4);
      expect(await contar(db, 'stock_conocido'), 4);
      expect(await contar(db, 'cliente_minimo'), 1);
      expect(await contar(db, 'descarga'), 1);
    });

    test('guarda la descarga (hora del teléfono, generado_en del stock, completa) y las claves de meta', () async {
      reloj.actual = DateTime.utc(2026, 10, 31, 12, 30);

      await aplicar(armarPaquete());

      final d = await fila('descarga', 'empresa_id = 1 AND sucursal_id = 1', []);
      expect(d['descargado_en'], '2026-10-31T12:30:00Z');
      expect(d['generado_en'], '2026-10-31T10:00:02Z');
      expect(d['completo'], 1);
      expect((await fila('meta', 'clave = ?', ['catalogo_generado_en:1']))['valor'], '2026-10-31T10:00:00Z');
      expect((await fila('meta', 'clave = ?', ['aviso_horas:1']))['valor'], '12');
      expect((await fila('meta', 'clave = ?', ['formato_descarga:1:1']))['valor'], formatoDescargaActual);
    });

    test('una cantidad negativa (más reservas que existencias) se guarda como 0', () async {
      await aplicar(armarPaquete(stock: [jsonItemStock(100, -3), jsonItemStock(101, 2)]));

      expect(await stockDe(db, 1), {100: 0, 101: 2});
    });

    test('el stock de una variante que no está en el catálogo se omite sin romper la descarga', () async {
      await aplicar(armarPaquete(stock: [jsonItemStock(100, 5), jsonItemStock(999, 8)]));

      expect(await stockDe(db, 1), {100: 5});
    });

    test('un padre de categoría que no existe se deja en NULL y una categoría inactiva se reemplaza por una genérica', () async {
      await aplicar(
        armarPaquete(
          manifiesto: jsonManifiesto(
            categorias: [
              {'id': 1, 'nombre': 'Poleras', 'categoria_padre_id': 77},
            ],
          ),
          productos: [jsonProducto(10, 'Gorra', categoria: 55, variantes: [jsonVariante(100)])],
          stock: [],
        ),
      );

      expect((await fila('categoria', 'id = 1', []))['categoria_padre_id'], isNull);
      expect((await fila('categoria', 'id = 55', []))['nombre'], 'Sin categoría');
      expect(await db.rawQuery('PRAGMA foreign_key_check'), isEmpty);
    });

    test('los horarios de una sucursal se reemplazan por los nuevos', () async {
      await aplicar(armarPaquete());

      await aplicar(
        armarPaquete(
          manifiesto: jsonManifiesto(
            sucursales: [
              jsonSucursal(1, horarios: [jsonHorario(5, apertura: '10:00', cierre: '20:00')]),
              jsonSucursal(2),
            ],
          ),
        ),
      );

      final horarios = await db.query('sucursal_horario', where: 'sucursal_id = 1');
      expect(horarios, hasLength(1));
      expect(horarios.single['dia_semana'], 5);
      expect(horarios.single['hora_cierre'], '20:00');
      expect(await contar(db, 'sucursal_horario', donde: 'sucursal_id = 2'), 2);
    });

    test('una sucursal que no está entre las autorizadas del manifiesto se rechaza sin tocar nada', () async {
      await expectLater(aplicar(armarPaquete(sucursalId: 99)), throwsA(isA<ErrorApp>()));

      expect(await contar(db, 'empresa'), 0);
      expect(await contar(db, 'producto'), 0);
    });
  });

  group('descarga incremental', () {
    test('actualiza un precio, agrega una variante y solo toca el stock que llegó', () async {
      await aplicar(armarPaquete());

      await aplicar(
        armarPaquete(
          productos: [
            jsonProducto(
              10,
              'Polera Básica',
              variantes: [jsonVariante(100, precio: '80.00'), jsonVariante(101, talla: 2), jsonVariante(102, talla: 3)],
            ),
            jsonProducto(11, 'Camisa Lino'),
          ],
          stock: [jsonItemStock(100, 9), jsonItemStock(102, 4)],
          completoStock: false,
          generadoStock: '2026-10-31T11:00:00Z',
        ),
      );

      expect((await fila('variante', 'id = 100', []))['precio_centavos'], 8000);
      expect(await contar(db, 'variante', donde: 'producto_id = 10'), 3);
      expect(await contar(db, 'variante'), 5);
      // 100 cambió, 102 es nueva, 101/110/111 no llegaron y conservan lo anterior.
      expect(await stockDe(db, 1), {100: 9, 101: 3, 102: 4, 110: 2, 111: 0});
      final d = await fila('descarga', 'sucursal_id = 1', []);
      expect(d['completo'], 0);
      expect(d['generado_en'], '2026-10-31T11:00:00Z');
    });

    test('un delta vacío no borra el stock', () async {
      await aplicar(armarPaquete());

      await aplicar(armarPaquete(stock: [], completoStock: false));

      expect(await contar(db, 'stock_conocido'), 4);
    });

    test('una descarga completa reemplaza el stock de la sucursal', () async {
      await aplicar(armarPaquete());

      await aplicar(armarPaquete(stock: [jsonItemStock(100, 1)]));

      expect(await stockDe(db, 1), {100: 1});
    });

    test('sin clientes en la descarga no se toca la lista local', () async {
      await aplicar(armarPaquete(clientes: [jsonCliente(1, 'Ana', ci: '111'), jsonCliente(2, 'Luis', ci: '222')]));

      await aplicar(armarPaquete(completoStock: false));

      expect(await contar(db, 'cliente_minimo'), 2);
    });
  });

  group('lo que el servidor da de baja', () {
    test('pasa a activo = 0, no se borra, y una venta pendiente sigue válida', () async {
      await aplicar(armarPaquete());
      await sembrarVentaPendiente(db, operacionId: 'op-1', varianteId: 110);

      // El segundo catálogo ya no trae la Camisa (11) ni la variante 101 de la Polera.
      await aplicar(armarPaquete(productos: [jsonProducto(10, 'Polera Básica', variantes: [jsonVariante(100)])], stock: [jsonItemStock(100, 5)]));

      expect(await contar(db, 'producto'), 2);
      expect(await contar(db, 'variante'), 4);
      expect((await fila('producto', 'id = 10', []))['activo'], 1);
      expect((await fila('producto', 'id = 11', []))['activo'], 0);
      expect((await fila('variante', 'id = 100', []))['activo'], 1);
      expect((await fila('variante', 'id = 101', []))['activo'], 0);
      expect((await fila('variante', 'id = 110', []))['activo'], 0);
      // La venta pendiente apunta a la variante 110, que sigue existiendo.
      final ventas = await db.rawQuery(
        'SELECT vd.variante_id, va.activo FROM venta_detalle vd JOIN variante va ON va.id = vd.variante_id',
      );
      expect(ventas.single['variante_id'], 110);
      expect(await db.rawQuery('PRAGMA foreign_key_check'), isEmpty);
    });

    test('si vuelve a aparecer, se reactiva', () async {
      await aplicar(armarPaquete());
      await aplicar(armarPaquete(productos: [jsonProducto(10, 'Polera Básica')], stock: []));
      expect((await fila('producto', 'id = 11', []))['activo'], 0);

      await aplicar(armarPaquete());

      expect((await fila('producto', 'id = 11', []))['activo'], 1);
      expect((await fila('variante', 'id = 110', []))['activo'], 1);
    });

    test('el stock de lo dado de baja se conserva, pero ya no se usa para vender', () async {
      await aplicar(armarPaquete());

      await aplicar(armarPaquete(productos: [jsonProducto(10, 'Polera Básica')], stock: [jsonItemStock(100, 5)], completoStock: false));

      expect((await stockDe(db, 1))[110], 2);
      expect((await fila('variante', 'id = 110', []))['activo'], 0);
    });
  });

  group('todo o nada', () {
    test('si falla a la mitad, se deshace todo y los datos anteriores quedan intactos', () async {
      reloj.actual = DateTime.utc(2026, 10, 31, 12);
      await aplicar(armarPaquete(clientes: [jsonCliente(1, 'Ana', ci: '111')]));
      reloj.actual = DateTime.utc(2026, 11, 1, 8);

      // El producto 12 trae una variante con una talla que no existe: la llave foránea falla a mitad de la escritura.
      await expectLater(
        aplicar(
          armarPaquete(
            productos: [
              jsonProducto(10, 'Polera RENOMBRADA', variantes: [jsonVariante(100, precio: '99.00')]),
              jsonProducto(12, 'Rota', variantes: [jsonVariante(120, talla: 99)]),
            ],
            stock: [jsonItemStock(100, 1)],
            clientes: [jsonCliente(5, 'Nuevo', ci: '555')],
            generadoStock: '2026-11-01T07:00:00Z',
          ),
        ),
        throwsA(isA<DatabaseException>()),
      );

      expect((await fila('producto', 'id = 10', []))['nombre'], 'Polera Básica');
      expect((await fila('producto', 'id = 11', []))['activo'], 1);
      expect(await contar(db, 'producto', donde: 'id = 12'), 0);
      expect((await fila('variante', 'id = 100', []))['precio_centavos'], 7500);
      expect((await fila('variante', 'id = 101', []))['activo'], 1);
      expect(await stockDe(db, 1), {100: 5, 101: 3, 110: 2, 111: 0});
      expect(await contar(db, 'cliente_minimo'), 1);
      final d = await fila('descarga', 'sucursal_id = 1', []);
      expect(d['descargado_en'], '2026-10-31T12:00:00Z');
      expect(d['generado_en'], '2026-10-31T10:00:02Z');
    });

    test('tras un fallo se puede volver a aplicar una descarga buena', () async {
      await expectLater(
        aplicar(armarPaquete(productos: [jsonProducto(12, 'Rota', variantes: [jsonVariante(120, talla: 99)])])),
        throwsA(isA<DatabaseException>()),
      );
      expect(await contar(db, 'empresa'), 0);

      await aplicar(armarPaquete());

      expect(await contar(db, 'producto'), 2);
    });
  });

  group('varias sucursales', () {
    test('el stock de una sucursal no pisa el de otra', () async {
      await aplicar(armarPaquete());

      await aplicar(armarPaquete(sucursalId: 2, stock: [jsonItemStock(100, 20), jsonItemStock(110, 30)]));

      expect(await stockDe(db, 1), {100: 5, 101: 3, 110: 2, 111: 0});
      expect(await stockDe(db, 2), {100: 20, 110: 30});
      expect(await contar(db, 'descarga'), 2);
    });

    test('bajar de nuevo una sucursal solo reemplaza su propio stock', () async {
      await aplicar(armarPaquete());
      await aplicar(armarPaquete(sucursalId: 2, stock: [jsonItemStock(100, 20)]));

      await aplicar(armarPaquete(sucursalId: 2, stock: [jsonItemStock(110, 7)]));

      expect(await stockDe(db, 2), {110: 7});
      expect(await stockDe(db, 1), {100: 5, 101: 3, 110: 2, 111: 0});
    });

    test('sucursal_autorizada se reemplaza por las del manifiesto y no toca a otros usuarios', () async {
      await aplicar(armarPaquete());
      await aplicar(armarPaquete(), usuarioId: 8);

      await aplicar(
        armarPaquete(manifiesto: jsonManifiesto(sucursales: [jsonSucursal(1)])),
      );

      final del7 = await db.query('sucursal_autorizada', where: 'usuario_id = 7');
      expect(del7.map((f) => f['sucursal_id']), [1]);
      expect(await contar(db, 'sucursal_autorizada', donde: 'usuario_id = 8'), 2);
      // La sucursal 2 sigue existiendo (puede tener operaciones): solo se quitó el permiso.
      expect(await contar(db, 'sucursal', donde: 'id = 2'), 1);
    });
  });

  group('clientes', () {
    test('no pisa los clientes creados en el teléfono', () async {
      await sembrarEmpresa(db);
      await db.insert('cliente_minimo', {
        'empresa_id': 1,
        'nombre': 'Pedro',
        'apellido': 'Local',
        'ci_nit': '999',
        'creado_en': '2026-10-30T10:00:00Z',
      });

      await aplicar(armarPaquete(clientes: [jsonCliente(1, 'Ana', ci: '111')]));

      expect(await contar(db, 'cliente_minimo'), 2);
      final pedro = await fila('cliente_minimo', 'ci_nit = ?', ['999']);
      expect(pedro['nombre'], 'Pedro');
      expect(pedro['servidor_id'], isNull);
    });

    test('si el servidor ya tiene al cliente que se creó en el teléfono, se enlaza sin cambiarle los datos', () async {
      await sembrarEmpresa(db);
      final localId = await db.insert('cliente_minimo', {
        'empresa_id': 1,
        'nombre': 'Pedro',
        'ci_nit': '999',
        'creado_en': '2026-10-30T10:00:00Z',
      });

      await aplicar(armarPaquete(clientes: [jsonCliente(40, 'Pedro Servidor', ci: '999')]));

      expect(await contar(db, 'cliente_minimo'), 1);
      final pedro = await fila('cliente_minimo', 'id = ?', [localId]);
      expect(pedro['servidor_id'], 40);
      expect(pedro['nombre'], 'Pedro');
    });

    test('un cliente del servidor se actualiza en el lugar en la siguiente descarga completa', () async {
      await aplicar(armarPaquete(clientes: [jsonCliente(1, 'Ana', ci: '111')]));
      final idLocal = (await fila('cliente_minimo', 'servidor_id = 1', []))['id'];

      await aplicar(armarPaquete(clientes: [jsonCliente(1, 'Ana María', ci: '111')]));

      expect(await contar(db, 'cliente_minimo'), 1);
      final ana = await fila('cliente_minimo', 'servidor_id = 1', []);
      expect(ana['id'], idLocal);
      expect(ana['nombre'], 'Ana María');
    });
  });

  group('partición por empresa', () {
    Map<String, Object?> sinFilaVolatil(Map<String, Object?> f) => Map.of(f);

    Future<List<Object?>> instantanea(int empresaId, int sucursalId) async {
      final productos = await db.query('producto', where: 'empresa_id = ?', whereArgs: [empresaId], orderBy: 'id');
      final variantes = await db.rawQuery(
        'SELECT v.* FROM variante v JOIN producto p ON p.id = v.producto_id WHERE p.empresa_id = ? ORDER BY v.id',
        [empresaId],
      );
      final stock = await db.query('stock_conocido', where: 'sucursal_id = ?', whereArgs: [sucursalId], orderBy: 'variante_id');
      final sucursales = await db.query('sucursal', where: 'empresa_id = ?', whereArgs: [empresaId], orderBy: 'id');
      final descarga = await db.query('descarga', where: 'empresa_id = ?', whereArgs: [empresaId]);
      return [productos.map(sinFilaVolatil).toList(), variantes, stock, sucursales, descarga];
    }

    PaqueteDescargado paqueteAndina() => armarPaquete(
      manifiesto: jsonManifiesto(empresaId: 2, codigo: 'andina', nombre: 'Boutique Andina'),
      productos: [
        jsonProducto(20, 'Falda Andina', categoria: 201, variantes: [jsonVariante(200, talla: 201, color: 201, sku: 'SKU-200')]),
      ],
      stock: [jsonItemStock(200, 6)],
      sucursalId: 201,
    );

    test('dos empresas conviven en la misma base sin mezclarse', () async {
      await aplicar(armarPaquete());
      await aplicar(paqueteAndina(), usuarioId: 9);

      expect(await contar(db, 'empresa'), 2);
      expect(await contar(db, 'producto', donde: 'empresa_id = 1'), 2);
      expect(await contar(db, 'producto', donde: 'empresa_id = 2'), 1);
      expect(await stockDe(db, 201), {200: 6});
      expect(await db.rawQuery('PRAGMA foreign_key_check'), isEmpty);
    });

    test('bajar el paquete de una empresa no toca nada de la otra', () async {
      await aplicar(armarPaquete());
      await aplicar(paqueteAndina(), usuarioId: 9);
      final antesAndina = await instantanea(2, 201);

      // Chaski cambia mucho: pierde la Camisa, reemplaza su stock y otro precio.
      reloj.actual = DateTime.utc(2026, 11, 2);
      await aplicar(
        armarPaquete(
          productos: [jsonProducto(10, 'Polera Básica', variantes: [jsonVariante(100, precio: '10.00')])],
          stock: [jsonItemStock(100, 1)],
        ),
      );

      expect(await instantanea(2, 201), antesAndina);
      expect((await fila('producto', 'id = 11', []))['activo'], 0);
      expect((await fila('producto', 'id = 20', []))['activo'], 1);
      expect((await fila('variante', 'id = 200', []))['activo'], 1);
    });

    test('los usuarios de una empresa conservan sus sucursales autorizadas cuando baja la otra', () async {
      await aplicar(armarPaquete(), usuarioId: 7);
      await aplicar(paqueteAndina(), usuarioId: 9);

      await aplicar(armarPaquete(manifiesto: jsonManifiesto(sucursales: [jsonSucursal(1)])), usuarioId: 7);

      expect((await db.query('sucursal_autorizada', where: 'usuario_id = 9')).map((f) => f['sucursal_id']), [201, 202]);
    });
  });
}
