import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/local/abrir_base_local.dart';
import 'package:mobile/core/local/esquema_local.dart';
import 'package:mobile/core/local_cliente/abrir_base_cliente.dart';
import 'package:mobile/core/local_cliente/esquema_cliente.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/cliente_offline_apoyo.dart';

void main() {
  late Directory carpeta;
  late String ruta;

  setUpAll(sqfliteFfiInit);

  setUp(() async {
    carpeta = await Directory.systemTemp.createTemp('fashionstore_cliente_');
    ruta = p.join(carpeta.path, 'cliente_prueba.db');
  });

  tearDown(() async {
    try {
      await carpeta.delete(recursive: true);
    } on FileSystemException {
      // En Windows el archivo puede seguir tomado un instante por el hilo de SQLite; no afecta a las pruebas.
    }
  });

  Future<Database> abrir({int version = 1, Map<int, List<String>> migraciones = const {}}) {
    return abrirBaseCliente(fabrica: databaseFactoryFfi, ruta: ruta, version: version, migraciones: migraciones);
  }

  Future<List<String>> tablas(Database db) async => [
    for (final f in await db.rawQuery(
      "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'",
    ))
      f['name']! as String,
  ];

  Future<void> insertarPedido(Database db, {String estado = 'pendiente', int total = 100}) => db.insert('cli_pedido', {
    'empresa_id': 7,
    'usuario_id': 4,
    'operacion_id': 'op-1',
    'estado': estado,
    'sucursal_id': 3,
    'sucursal_nombre': 'Centro',
    'costo_envio_centavos': 0,
    'lineas_json': '[]',
    'total_maximo_centavos': total,
    'fecha_pedido': '2026-11-06T12:00:00Z',
    'creado_en': '2026-11-06T12:00:00Z',
  });

  group('la base del cliente es APARTE de la del personal', () {
    test('es otro archivo', () {
      expect(nombreArchivoBaseCliente, isNot(nombreArchivoBaseLocal));
      expect(nombreArchivoBaseCliente, 'fashionstore_cliente.db');
    });

    test('crea solo sus 4 tablas cli_, ninguna de las del personal', () async {
      final db = await abrir();

      final creadas = await tablas(db);

      expect(creadas, unorderedEquals(tablasEsquemaClienteV1));
      expect(creadas.every((t) => t.startsWith('cli_')), isTrue);
      for (final delPersonal in tablasEsquemaV1) {
        expect(creadas, isNot(contains(delPersonal)), reason: '$delPersonal es de la base del personal');
      }
      await db.close();
    });

    test('la versión del esquema queda en user_version', () async {
      final db = await abrir();
      expect((await db.rawQuery('PRAGMA user_version')).single['user_version'], versionEsquemaCliente);
      await db.close();
    });
  });

  group('restricciones del esquema', () {
    test('un pedido con un estado desconocido o un total negativo se rechaza', () async {
      final db = await abrir();

      await expectLater(insertarPedido(db, estado: 'raro'), throwsA(isA<DatabaseException>()));
      await expectLater(insertarPedido(db, total: -1), throwsA(isA<DatabaseException>()));

      await insertarPedido(db);
      expect(await db.query('cli_pedido'), hasLength(1));
      await db.close();
    });

    test('la llave del pedido es (empresa, usuario, operación): dos personas pueden repetir el id', () async {
      final db = await abrir();
      await insertarPedido(db);

      await expectLater(insertarPedido(db), throwsA(isA<DatabaseException>()));
      await db.insert('cli_pedido', {
        'empresa_id': 7,
        'usuario_id': 9,
        'operacion_id': 'op-1',
        'estado': 'pendiente',
        'sucursal_id': 3,
        'sucursal_nombre': 'Centro',
        'costo_envio_centavos': 0,
        'lineas_json': '[]',
        'total_maximo_centavos': 100,
        'fecha_pedido': '2026-11-06T12:00:00Z',
        'creado_en': '2026-11-06T12:00:00Z',
      });
      expect(await db.query('cli_pedido'), hasLength(2));
      await db.close();
    });

    test('una línea del carrito con cantidad 0 se rechaza', () async {
      final db = await abrir();
      await expectLater(
        db.insert('cli_carrito', {
          'empresa_id': 7,
          'usuario_id': 4,
          'variante_id': 1,
          'producto_id': 1,
          'cantidad': 0,
          'producto_nombre': 'Polera',
          'precio_centavos': 100,
          'agregado_en': '2026-11-06T12:00:00Z',
        }),
        throwsA(isA<DatabaseException>()),
      );
      await db.close();
    });

    test('el cache solo admite los tipos conocidos', () async {
      final db = await abrir();
      await expectLater(
        db.insert('cli_cache', {'tienda': 'a', 'tipo': 'otro', 'clave': '1', 'json': '{}', 'guardado_en': 'x'}),
        throwsA(isA<DatabaseException>()),
      );
      await db.close();
    });
  });

  group('migraciones', () {
    test('migrar de 1 a 2 conserva los pedidos sin enviar', () async {
      var db = await abrir();
      await insertarPedido(db);
      await db.close();

      db = await abrir(
        version: 2,
        migraciones: {
          2: ['ALTER TABLE cli_meta ADD COLUMN nota TEXT'],
        },
      );

      expect((await db.rawQuery('PRAGMA user_version')).single['user_version'], 2);
      final pedido = (await db.query('cli_pedido')).single;
      expect(pedido['operacion_id'], 'op-1');
      expect(pedido['estado'], 'pendiente');
      expect((await db.query('cli_meta')), isEmpty);
      await db.insert('cli_meta', {'empresa_id': 7, 'usuario_id': 4, 'clave': 'k', 'valor': 'v', 'nota': 'n'});
      await db.close();
    });

    test('crear directamente en la versión 3 aplica las migraciones 2 y 3', () async {
      final db = await abrir(
        version: 3,
        migraciones: {
          2: ['ALTER TABLE cli_meta ADD COLUMN a TEXT'],
          3: ['ALTER TABLE cli_meta ADD COLUMN b TEXT'],
        },
      );

      final columnas = [for (final c in await db.rawQuery('PRAGMA table_info(cli_meta)')) c['name']];
      expect(columnas, containsAll(['a', 'b']));
      await db.close();
    });

    test('falta una migración: lanza un error en vez de dejar la base a medias', () async {
      var db = await abrir();
      await db.close();

      await expectLater(abrir(version: 2), throwsA(isA<StateError>()));
    });

    test('bajar de versión lanza un error y NO borra la base', () async {
      var db = await abrir(
        version: 2,
        migraciones: {
          2: ['ALTER TABLE cli_meta ADD COLUMN a TEXT'],
        },
      );
      await insertarPedido(db);
      await db.close();

      await expectLater(abrir(), throwsA(anything));

      db = await abrir(
        version: 2,
        migraciones: {
          2: ['ALTER TABLE cli_meta ADD COLUMN a TEXT'],
        },
      );
      expect(await db.query('cli_pedido'), hasLength(1), reason: 'el pedido sin enviar sigue ahí');
      await db.close();
    });
  });

  test('la base de prueba en memoria se abre con el mismo esquema', () async {
    final db = await abrirBaseClienteDePrueba();
    expect(await tablas(db), unorderedEquals(tablasEsquemaClienteV1));
    await db.close();
  });
}
