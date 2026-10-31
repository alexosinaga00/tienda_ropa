import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/local/abrir_base_local.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';

void main() {
  late Directory carpeta;
  late String ruta;

  setUpAll(sqfliteFfiInit);

  setUp(() async {
    carpeta = await Directory.systemTemp.createTemp('fashionstore_migraciones_');
    ruta = p.join(carpeta.path, 'base_prueba.db');
  });

  tearDown(() async {
    try {
      await carpeta.delete(recursive: true);
    } on FileSystemException {
      // En Windows el archivo puede seguir tomado un instante por el hilo de SQLite; no afecta a las pruebas.
    }
  });

  Future<Database> abrir({int version = 1, Map<int, List<String>> migraciones = const {}}) {
    return abrirBaseLocal(fabrica: databaseFactoryFfi, ruta: ruta, version: version, migraciones: migraciones);
  }

  Future<String?> versionMeta(Database db) async {
    final filas = await db.query('meta', where: 'clave = ?', whereArgs: ['version_esquema']);
    return filas.isEmpty ? null : filas.single['valor'] as String;
  }

  Future<int> cuenta(Database db, String tabla) async => (await db.rawQuery('SELECT COUNT(*) AS n FROM $tabla')).first['n']! as int;

  test('una base nueva queda en la versión 1 con meta.version_esquema = 1', () async {
    final db = await abrir();
    expect(await versionMeta(db), '1');
    expect((await db.rawQuery('PRAGMA user_version')).single['user_version'], 1);
    await db.close();
  });

  test('migrar de 1 a 2 conserva los datos y deja meta.version_esquema = 2', () async {
    var db = await abrir();
    await sembrarEmpresa(db);
    await sembrarSucursal(db, id: 1);
    await sembrarReferencias(db);
    await sembrarProducto(db, id: 1, nombre: 'Polera', variantes: [variante(1)]);
    await db.close();

    db = await abrir(version: 2, migraciones: {
      2: ['ALTER TABLE empresa ADD COLUMN pais TEXT'],
    });
    expect(await versionMeta(db), '2');
    expect((await db.rawQuery('PRAGMA user_version')).single['user_version'], 2);
    expect(await cuenta(db, 'empresa'), 1);
    expect(await cuenta(db, 'producto'), 1);
    expect(await cuenta(db, 'variante'), 1);
    // La columna nueva existe y las filas viejas la tienen en NULL.
    final empresa = (await db.query('empresa')).single;
    expect(empresa.containsKey('pais'), isTrue);
    expect(empresa['pais'], isNull);
    await db.close();
  });

  test('las llaves foráneas siguen activas después de migrar', () async {
    var db = await abrir();
    await db.close();
    db = await abrir(version: 2, migraciones: {
      2: ['ALTER TABLE empresa ADD COLUMN pais TEXT'],
    });
    expect((await db.rawQuery('PRAGMA foreign_keys')).single['foreign_keys'], 1);
    await db.close();
  });

  test('crear directamente en la versión 3 aplica las migraciones 2 y 3', () async {
    final db = await abrir(version: 3, migraciones: {
      2: ['ALTER TABLE empresa ADD COLUMN pais TEXT'],
      3: ['ALTER TABLE empresa ADD COLUMN moneda TEXT'],
    });
    expect(await versionMeta(db), '3');
    await db.insert('empresa', {'id': 1, 'codigo': 'a', 'nombre': 'A', 'pais': 'BO', 'moneda': 'BOB'});
    await db.close();
  });

  test('reabrir con la misma versión no repite migraciones ni toca los datos', () async {
    var db = await abrir(version: 2, migraciones: {
      2: ['ALTER TABLE empresa ADD COLUMN pais TEXT'],
    });
    await sembrarEmpresa(db);
    await db.close();

    // Si repitiera la migración, el ALTER fallaría porque la columna ya existe.
    db = await abrir(version: 2, migraciones: {
      2: ['ALTER TABLE empresa ADD COLUMN pais TEXT'],
    });
    expect(await cuenta(db, 'empresa'), 1);
    expect(await versionMeta(db), '2');
    await db.close();
  });

  test('reabrir con una versión menor lanza StateError y NO borra el archivo ni los datos', () async {
    var db = await abrir(version: 2, migraciones: {
      2: ['ALTER TABLE empresa ADD COLUMN pais TEXT'],
    });
    await sembrarEmpresa(db);
    await sembrarSucursal(db, id: 1);
    await db.close();
    final tamanoAntes = await File(ruta).length();

    await expectLater(abrir(version: 1), throwsStateError);

    expect(await File(ruta).exists(), isTrue);
    expect(await File(ruta).length(), tamanoAntes);

    db = await abrir(version: 2, migraciones: {
      2: ['ALTER TABLE empresa ADD COLUMN pais TEXT'],
    });
    expect(await cuenta(db, 'empresa'), 1);
    expect(await cuenta(db, 'sucursal'), 1);
    expect(await versionMeta(db), '2');
    await db.close();
  });

  test('subir a la versión 2 sin migración registrada lanza StateError y conserva la base en la versión 1', () async {
    var db = await abrir();
    await sembrarEmpresa(db);
    await db.close();

    await expectLater(abrir(version: 2), throwsStateError);

    db = await abrir();
    expect(await cuenta(db, 'empresa'), 1);
    expect(await versionMeta(db), '1');
    expect((await db.rawQuery('PRAGMA user_version')).single['user_version'], 1);
    await db.close();
  });

  test('una migración que falla a mitad se deshace entera', () async {
    var db = await abrir();
    await sembrarEmpresa(db);
    await db.close();

    await expectLater(
      abrir(version: 2, migraciones: {
        2: ['ALTER TABLE empresa ADD COLUMN pais TEXT', 'ESTO NO ES SQL'],
      }),
      throwsA(isA<DatabaseException>()),
    );

    db = await abrir();
    final columnas = (await db.rawQuery('PRAGMA table_info(empresa)')).map((c) => c['name']).toList();
    expect(columnas, isNot(contains('pais')));
    expect(await cuenta(db, 'empresa'), 1);
    expect(await versionMeta(db), '1');
    await db.close();
  });
}
