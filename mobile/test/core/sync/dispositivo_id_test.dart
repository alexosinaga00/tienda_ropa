import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/sync/dispositivo_id.dart';
import 'package:mobile/core/sync/generador_uuid.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';

class _Generador implements GeneradorUuid {
  _Generador([this.prefijo = 'uuid']);

  final String prefijo;
  int llamadas = 0;

  @override
  String nuevo() => '$prefijo-${++llamadas}';
}

void main() {
  late Database db;

  setUp(() async {
    db = await abrirBaseDePrueba();
  });

  tearDown(() async {
    await db.close();
  });

  group('obtenerDispositivoId', () {
    test('la primera vez genera un UUID, lo guarda en meta y lo devuelve', () async {
      final generador = _Generador();

      final id = await obtenerDispositivoId(db, generador);

      expect(id, 'uuid-1');
      final filas = await db.query('meta', where: 'clave = ?', whereArgs: [claveDispositivoId]);
      expect(filas.single['valor'], 'uuid-1');
      expect(claveDispositivoId, 'dispositivo_id');
    });

    test('devuelve siempre el mismo y no vuelve a generar', () async {
      final generador = _Generador();

      final a = await obtenerDispositivoId(db, generador);
      final b = await obtenerDispositivoId(db, generador);
      final c = await obtenerDispositivoId(db, _Generador('otro'));

      expect(b, a);
      expect(c, a);
      expect(generador.llamadas, 1);
    });

    test('respeta un valor que ya estaba guardado', () async {
      await db.insert('meta', {'clave': claveDispositivoId, 'valor': 'preexistente'});
      final generador = _Generador();

      expect(await obtenerDispositivoId(db, generador), 'preexistente');
      expect(generador.llamadas, 0);
    });

    test('no toca las demás claves de meta', () async {
      final antes = await db.query('meta', orderBy: 'clave');

      await obtenerDispositivoId(db, _Generador());

      final despues = await db.query('meta', where: 'clave <> ?', whereArgs: [claveDispositivoId], orderBy: 'clave');
      expect(despues, antes);
    });

    test('con el generador real el identificador es un UUID v4 en minúscula', () async {
      final id = await obtenerDispositivoId(db, const GeneradorUuidV4());

      expect(RegExp(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$').hasMatch(id), isTrue, reason: id);
    });

    test('dos llamadas simultáneas terminan con el mismo identificador', () async {
      final generador = _Generador();

      final ids = await Future.wait([
        obtenerDispositivoId(db, generador),
        obtenerDispositivoId(db, generador),
        obtenerDispositivoId(db, generador),
      ]);

      expect(ids.toSet(), hasLength(1));
      final filas = await db.query('meta', where: 'clave = ?', whereArgs: [claveDispositivoId]);
      expect(filas, hasLength(1));
      expect(filas.single['valor'], ids.first);
    });

    test('dos generadores reales producen identificadores distintos (dos teléfonos)', () {
      expect(const GeneradorUuidV4().nuevo(), isNot(const GeneradorUuidV4().nuevo()));
    });
  });

  group('persistencia en archivo', () {
    late Directory carpeta;

    setUp(() async {
      carpeta = await Directory.systemTemp.createTemp('dispositivo_id_test');
    });

    tearDown(() async {
      try {
        await carpeta.delete(recursive: true);
      } catch (_) {
        // En Windows el archivo puede seguir tomado un instante: no importa para la prueba.
      }
    });

    test('al cerrar y reabrir la base, el identificador es el mismo', () async {
      final ruta = p.join(carpeta.path, 'local.db');
      final primera = await abrirBaseDePrueba(ruta: ruta);
      final id = await obtenerDispositivoId(primera, _Generador());
      await primera.close();

      final segunda = await abrirBaseDePrueba(ruta: ruta);
      addTearDown(segunda.close);
      final generador = _Generador('nuevo');
      final despues = await obtenerDispositivoId(segunda, generador);

      expect(despues, id);
      expect(generador.llamadas, 0);
    });
  });
}
