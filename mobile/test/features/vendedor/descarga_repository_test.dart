import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/vendedor/data/almacen_paquete.dart';
import 'package:mobile/features/vendedor/data/descarga_repository.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';
import 'apoyo_paquete.dart';

void main() {
  late Database db;
  late DescargaRepositorySqlite repo;

  setUp(() async {
    db = await abrirBaseDePrueba();
    addTearDown(db.close);
    repo = DescargaRepositorySqlite(db);
    await sembrarEmpresa(db);
    await sembrarSucursal(db, id: 1);
    await sembrarSucursal(db, id: 2);
    await sembrarEmpresa(db, id: 2, codigo: 'andina', nombre: 'Andina');
    await sembrarSucursal(db, id: 3, empresaId: 2);
  });

  group('ultimaDescarga', () {
    test('es null si nunca se descargó', () async {
      expect(await repo.ultimaDescarga(1, 1), isNull);
    });

    test('devuelve la hora del teléfono, la del servidor y si fue completa', () async {
      await db.insert('descarga', {
        'empresa_id': 1,
        'sucursal_id': 1,
        'descargado_en': '2026-10-31T12:30:00Z',
        'generado_en': '2026-10-31T10:00:02Z',
        'completo': 1,
      });

      final u = (await repo.ultimaDescarga(1, 1))!;

      expect(u.descargadoEn, DateTime.utc(2026, 10, 31, 12, 30));
      expect(u.generadoEn, DateTime.utc(2026, 10, 31, 10, 0, 2));
      expect(u.completo, isTrue);
    });

    test('la vigencia es por sucursal y por empresa', () async {
      await db.insert('descarga', {
        'empresa_id': 1,
        'sucursal_id': 1,
        'descargado_en': '2026-10-31T12:30:00Z',
        'generado_en': '2026-10-31T10:00:02Z',
        'completo': 0,
      });

      expect(await repo.ultimaDescarga(1, 2), isNull);
      expect(await repo.ultimaDescarga(2, 3), isNull);
      expect((await repo.ultimaDescarga(1, 1))!.completo, isFalse);
    });

    test('una fila con fecha ilegible se trata como si no hubiera descarga', () async {
      await db.insert('descarga', {
        'empresa_id': 1,
        'sucursal_id': 1,
        'descargado_en': 'basura',
        'generado_en': '2026-10-31T10:00:02Z',
        'completo': 1,
      });

      expect(await repo.ultimaDescarga(1, 1), isNull);
    });
  });

  group('sucursal activa', () {
    test('es null hasta que se elige y se guarda en meta con su clave', () async {
      expect(await repo.sucursalActiva(1, 7), isNull);

      await repo.fijarSucursalActiva(1, 7, 2);

      expect(await repo.sucursalActiva(1, 7), 2);
      final meta = await db.query('meta', where: 'clave = ?', whereArgs: ['sucursal_activa:1:7']);
      expect(meta.single['valor'], '2');
    });

    test('cambiarla reemplaza la anterior', () async {
      await repo.fijarSucursalActiva(1, 7, 1);
      await repo.fijarSucursalActiva(1, 7, 2);

      expect(await repo.sucursalActiva(1, 7), 2);
      expect(await contar(db, 'meta', donde: "clave LIKE 'sucursal_activa:%'"), 1);
    });

    test('es independiente por usuario y por empresa', () async {
      await repo.fijarSucursalActiva(1, 7, 1);
      await repo.fijarSucursalActiva(1, 8, 2);
      await repo.fijarSucursalActiva(2, 7, 3);

      expect(await repo.sucursalActiva(1, 7), 1);
      expect(await repo.sucursalActiva(1, 8), 2);
      expect(await repo.sucursalActiva(2, 7), 3);
      expect(await repo.sucursalActiva(2, 8), isNull);
    });
  });

  group('operaciones enviadas', () {
    test('sin operaciones, o solo registradas, no hay enviadas', () async {
      expect(await repo.hayOperacionesEnviadas(1), isFalse);

      await db.insert('operacion_pendiente', _operacion('a', empresaId: 1, sucursalId: 1, estado: 'registrada'));

      expect(await repo.hayOperacionesEnviadas(1), isFalse);
    });

    test('una operación enviada se detecta, y deja de contar cuando se confirma', () async {
      await db.insert('operacion_pendiente', _operacion('a', empresaId: 1, sucursalId: 1, estado: 'enviada'));
      expect(await repo.hayOperacionesEnviadas(1), isTrue);

      await db.update('operacion_pendiente', {'estado': 'confirmada'}, where: "operacion_id = 'a'");

      expect(await repo.hayOperacionesEnviadas(1), isFalse);
    });

    test('solo cuentan las de la empresa consultada', () async {
      await db.insert('operacion_pendiente', _operacion('b', empresaId: 2, sucursalId: 3, estado: 'enviada'));

      expect(await repo.hayOperacionesEnviadas(1), isFalse);
      expect(await repo.hayOperacionesEnviadas(2), isTrue);
    });

    test('rechazada y en conflicto no cuentan', () async {
      await db.insert('operacion_pendiente', _operacion('c', empresaId: 1, sucursalId: 1, estado: 'rechazada'));
      await db.insert('operacion_pendiente', _operacion('d', empresaId: 1, sucursalId: 1, estado: 'en_conflicto'));

      expect(await repo.hayOperacionesEnviadas(1), isFalse);
    });
  });

  group('otros datos de meta y de la sucursal', () {
    test('avisoHoras sale de meta por empresa', () async {
      expect(await repo.avisoHoras(1), isNull);

      await db.insert('meta', {'clave': claveMetaAvisoHoras(1), 'valor': '12'});

      expect(await repo.avisoHoras(1), 12);
      expect(await repo.avisoHoras(2), isNull);
    });

    test('empresaDeSucursal conoce la empresa de una sucursal ya guardada', () async {
      expect(await repo.empresaDeSucursal(1), 1);
      expect(await repo.empresaDeSucursal(3), 2);
      expect(await repo.empresaDeSucursal(99), isNull);
    });

    test('formatoDescarga lee la clave por empresa y sucursal', () async {
      expect(await repo.formatoDescarga(1, 1), isNull);

      await db.insert('meta', {'clave': claveMetaFormato(1, 1), 'valor': 'contrato1-esquema1'});

      expect(await repo.formatoDescarga(1, 1), 'contrato1-esquema1');
      expect(await repo.formatoDescarga(1, 2), isNull);
    });
  });
}

Map<String, Object?> _operacion(String id, {required int empresaId, required int sucursalId, required String estado}) => {
  'operacion_id': id,
  'empresa_id': empresaId,
  'sucursal_id': sucursalId,
  'usuario_id': 7,
  'tipo': 'venta_contado',
  'estado': estado,
  'payload': '{}',
  'version_contrato': 1,
  'fecha_operacion': '2026-10-31T09:00:00Z',
  'creada_en': '2026-10-31T09:00:00Z',
};
