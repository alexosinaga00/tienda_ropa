import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/local/esquema_local.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';

Future<void> _operacion(
  Database db,
  String id, {
  String tipo = 'venta_contado',
  String estado = 'registrada',
  int empresaId = 1,
  int sucursalId = 1,
}) {
  return db.insert('operacion_pendiente', {
    'operacion_id': id,
    'empresa_id': empresaId,
    'sucursal_id': sucursalId,
    'usuario_id': 10,
    'tipo': tipo,
    'estado': estado,
    'payload': '{}',
    'version_contrato': 1,
    'fecha_operacion': '2026-10-31T10:00:00Z',
    'creada_en': '2026-10-31T10:00:00Z',
  });
}

Future<int> _venta(Database db, String operacionId, {String formaPago = 'efectivo'}) {
  return db.insert('venta', {
    'operacion_id': operacionId,
    'empresa_id': 1,
    'sucursal_id': 1,
    'usuario_id': 10,
    'fecha_operacion': '2026-10-31T10:00:00Z',
    'forma_pago': formaPago,
    'total_centavos': 7500,
  });
}

Future<int> _cliente(Database db) {
  return db.insert('cliente_minimo', {'empresa_id': 1, 'nombre': 'Ana', 'creado_en': '2026-10-31T10:00:00Z'});
}

Future<int> _reserva(Database db, String operacionId, int clienteId) {
  return db.insert('reserva', {
    'operacion_id': operacionId,
    'empresa_id': 1,
    'sucursal_id': 1,
    'usuario_id': 10,
    'cliente_minimo_id': clienteId,
    'fecha_operacion': '2026-10-31T10:00:00Z',
    'fecha_visita': '2026-11-01',
    'hora_visita_desde': '10:00',
    'hora_visita_hasta': '11:00',
  });
}

Future<int> _contar(Database db, String tabla) async =>
    (await db.rawQuery('SELECT COUNT(*) AS n FROM $tabla')).first['n']! as int;

void main() {
  late Database db;

  setUp(() async {
    db = await abrirBaseDePrueba();
  });

  tearDown(() async {
    await db.close();
  });

  Future<void> sembrarBase() async {
    await sembrarEmpresa(db);
    await sembrarSucursal(db, id: 1);
    await sembrarReferencias(db);
    await sembrarProducto(db, id: 1, nombre: 'Polera', variantes: [variante(1)]);
  }

  group('estructura', () {
    test('crea las 19 tablas del esquema', () async {
      final filas = await db.rawQuery("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'");
      final nombres = filas.map((f) => f['name']! as String).toSet();
      expect(tablasEsquemaV1.length, 19);
      expect(nombres, tablasEsquemaV1.toSet());
    });

    test('crea la vista v_stock_local', () async {
      final filas = await db.rawQuery("SELECT name FROM sqlite_master WHERE type = 'view'");
      expect(filas.map((f) => f['name']), ['v_stock_local']);
    });

    test('crea los índices', () async {
      final filas = await db.rawQuery("SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'");
      final nombres = filas.map((f) => f['name']! as String).toSet();
      expect(
        nombres,
        containsAll(<String>{
          'ix_sucursal_empresa',
          'ix_producto_busqueda',
          'ix_producto_categoria',
          'ix_variante_producto',
          'ix_variante_sku',
          'ix_stock_sucursal',
          'ux_cliente_ci',
          'ux_cliente_servidor',
          'ix_operacion_estado',
          'ix_operacion_fecha',
          'ix_venta_sucursal',
          'ix_reserva_sucursal',
        }),
      );
    });

    test('meta.version_esquema es 1', () async {
      final filas = await db.query('meta', where: 'clave = ?', whereArgs: ['version_esquema']);
      expect(filas.single['valor'], '1');
      expect(versionEsquemaLocal, 1);
    });

    test('las llaves foráneas están activadas', () async {
      final filas = await db.rawQuery('PRAGMA foreign_keys');
      expect(filas.single['foreign_keys'], 1);
    });
  });

  group('llaves foráneas', () {
    test('una variante con un producto inexistente falla', () async {
      await sembrarEmpresa(db);
      await sembrarReferencias(db);
      expect(
        () => db.insert('variante', {
          'producto_id': 999,
          'talla_id': 1,
          'color_id': 1,
          'sku': 'X',
          'precio_centavos': 100,
        }),
        throwsA(isA<DatabaseException>()),
      );
    });

    test('una sucursal de una empresa inexistente falla', () async {
      expect(() => sembrarSucursal(db, id: 1, empresaId: 99), throwsA(isA<DatabaseException>()));
    });

    test('borrar un producto con variantes falla (RESTRICT)', () async {
      await sembrarBase();
      expect(() => db.delete('producto', where: 'id = 1'), throwsA(isA<DatabaseException>()));
      expect(await _contar(db, 'producto'), 1);
    });

    test('borrar una variante usada por una venta falla (RESTRICT)', () async {
      await sembrarBase();
      await _operacion(db, 'op-1');
      final ventaId = await _venta(db, 'op-1');
      await db.insert('venta_detalle', {'venta_id': ventaId, 'variante_id': 1, 'cantidad': 1, 'precio_unitario_centavos': 7500});
      expect(() => db.delete('variante', where: 'id = 1'), throwsA(isA<DatabaseException>()));
      expect(await _contar(db, 'variante'), 1);
    });

    test('borrar un producto usado por una venta falla (RESTRICT)', () async {
      await sembrarBase();
      await _operacion(db, 'op-1');
      final ventaId = await _venta(db, 'op-1');
      await db.insert('venta_detalle', {'venta_id': ventaId, 'variante_id': 1, 'cantidad': 1, 'precio_unitario_centavos': 7500});
      expect(() => db.delete('producto', where: 'id = 1'), throwsA(isA<DatabaseException>()));
    });

    test('borrar una sucursal con operaciones falla (RESTRICT)', () async {
      await sembrarBase();
      await _operacion(db, 'op-1');
      expect(() => db.delete('sucursal', where: 'id = 1'), throwsA(isA<DatabaseException>()));
    });

    test('borrar una sucursal borra su horario y sus autorizaciones (CASCADE)', () async {
      await sembrarEmpresa(db);
      await sembrarSucursal(db, id: 1);
      await db.insert('sucursal_horario', {'sucursal_id': 1, 'dia_semana': 1, 'hora_apertura': '09:00', 'hora_cierre': '18:00'});
      await db.insert('sucursal_autorizada', {'usuario_id': 10, 'sucursal_id': 1});
      await db.delete('sucursal', where: 'id = 1');
      expect(await _contar(db, 'sucursal_horario'), 0);
      expect(await _contar(db, 'sucursal_autorizada'), 0);
    });
  });

  group('categoría autorreferenciada', () {
    test('insertar el hijo antes que el padre dentro de una transacción funciona', () async {
      await sembrarEmpresa(db);
      await db.transaction((txn) async {
        await txn.insert('categoria', {'id': 2, 'empresa_id': 1, 'nombre': 'Polos', 'categoria_padre_id': 1});
        await txn.insert('categoria', {'id': 1, 'empresa_id': 1, 'nombre': 'Poleras'});
      });
      expect(await _contar(db, 'categoria'), 2);
    });

    // OJO: una violación diferida DENTRO de `db.transaction` (el COMMIT es lo que falla) deja colgado a sqflite_common_ffi
    // (la llamada nunca termina y la base queda inutilizable); por eso aquí solo se prueba fuera de una transacción explícita.
    test('si el padre no existe, el insert suelto falla al cerrarse la sentencia', () async {
      await sembrarEmpresa(db);
      await expectLater(
        db.insert('categoria', {'id': 2, 'empresa_id': 1, 'nombre': 'Polos', 'categoria_padre_id': 77}),
        throwsA(isA<DatabaseException>()),
      );
      expect(await _contar(db, 'categoria'), 0);
    });

    test('un producto puede insertarse antes que su categoría dentro de una transacción', () async {
      await sembrarEmpresa(db);
      await db.transaction((txn) async {
        await txn.insert('producto', {
          'id': 1,
          'empresa_id': 1,
          'codigo': 'P1',
          'nombre': 'Polera',
          'nombre_busqueda': 'polera',
          'categoria_id': 5,
        });
        await txn.insert('categoria', {'id': 5, 'empresa_id': 1, 'nombre': 'Poleras'});
      });
      expect(await _contar(db, 'producto'), 1);
    });
  });

  group('CHECK', () {
    test('estado de operacion_pendiente fuera de la lista falla', () async {
      await sembrarEmpresa(db);
      await sembrarSucursal(db, id: 1);
      expect(() => _operacion(db, 'op-1', estado: 'perdida'), throwsA(isA<DatabaseException>()));
    });

    test('acepta los cinco estados válidos', () async {
      await sembrarEmpresa(db);
      await sembrarSucursal(db, id: 1);
      var i = 0;
      for (final e in ['registrada', 'enviada', 'confirmada', 'rechazada', 'en_conflicto']) {
        await _operacion(db, 'op-${i++}', estado: e);
      }
      expect(await _contar(db, 'operacion_pendiente'), 5);
    });

    test('tipo de operacion_pendiente fuera de la lista falla', () async {
      await sembrarEmpresa(db);
      await sembrarSucursal(db, id: 1);
      expect(() => _operacion(db, 'op-1', tipo: 'devolucion'), throwsA(isA<DatabaseException>()));
    });

    test('cantidad 0 o negativa en venta_detalle falla', () async {
      await sembrarBase();
      await _operacion(db, 'op-1');
      final ventaId = await _venta(db, 'op-1');
      for (final cantidad in [0, -1]) {
        expect(
          () => db.insert('venta_detalle', {'venta_id': ventaId, 'variante_id': 1, 'cantidad': cantidad, 'precio_unitario_centavos': 100}),
          throwsA(isA<DatabaseException>()),
        );
      }
    });

    test('cantidad 0 o negativa en reserva_detalle falla', () async {
      await sembrarBase();
      await _operacion(db, 'op-1', tipo: 'reserva');
      final reservaId = await _reserva(db, 'op-1', await _cliente(db));
      for (final cantidad in [0, -2]) {
        expect(
          () => db.insert('reserva_detalle', {'reserva_id': reservaId, 'variante_id': 1, 'cantidad': cantidad}),
          throwsA(isA<DatabaseException>()),
        );
      }
    });

    test('forma_pago distinta de efectivo en venta falla', () async {
      await sembrarBase();
      await _operacion(db, 'op-1');
      expect(() => _venta(db, 'op-1', formaPago: 'tarjeta'), throwsA(isA<DatabaseException>()));
    });

    test('cantidad negativa en stock_conocido falla y 0 se acepta', () async {
      await sembrarBase();
      expect(() => sembrarStock(db, varianteId: 1, sucursalId: 1, cantidad: -1), throwsA(isA<DatabaseException>()));
      await sembrarStock(db, varianteId: 1, sucursalId: 1, cantidad: 0);
      expect(await _contar(db, 'stock_conocido'), 1);
    });

    test('un precio negativo en variante falla', () async {
      await sembrarBase();
      expect(
        () => db.insert('variante', {'producto_id': 1, 'talla_id': 2, 'color_id': 1, 'sku': 'N', 'precio_centavos': -1}),
        throwsA(isA<DatabaseException>()),
      );
    });

    test('activo y es_deposito solo admiten 0 o 1', () async {
      await sembrarEmpresa(db);
      expect(
        () => db.insert('sucursal', {'id': 1, 'empresa_id': 1, 'codigo': 'S', 'nombre': 'S', 'activo': 2}),
        throwsA(isA<DatabaseException>()),
      );
      expect(
        () => db.insert('sucursal', {'id': 1, 'empresa_id': 1, 'codigo': 'S', 'nombre': 'S', 'es_deposito': 5}),
        throwsA(isA<DatabaseException>()),
      );
    });

    test('día de la semana fuera de 1..7 falla', () async {
      await sembrarEmpresa(db);
      await sembrarSucursal(db, id: 1);
      expect(
        () => db.insert('sucursal_horario', {'sucursal_id': 1, 'dia_semana': 8, 'hora_apertura': '09:00', 'hora_cierre': '18:00'}),
        throwsA(isA<DatabaseException>()),
      );
    });
  });

  group('unicidad', () {
    test('UNIQUE (empresa_id, codigo) de producto', () async {
      await sembrarEmpresa(db);
      await sembrarReferencias(db);
      await sembrarProducto(db, id: 1, nombre: 'Polera', codigo: 'IGUAL');
      expect(() => sembrarProducto(db, id: 2, nombre: 'Otra', codigo: 'IGUAL'), throwsA(isA<DatabaseException>()));
    });

    test('el mismo código de producto en dos empresas SÍ se permite', () async {
      await sembrarEmpresa(db);
      await sembrarEmpresa(db, id: 2, codigo: 'andes', nombre: 'Andes');
      await sembrarReferencias(db);
      await sembrarReferencias(db, empresaId: 2, categoriaId: 2);
      await sembrarProducto(db, id: 1, nombre: 'Polera', codigo: 'IGUAL');
      await sembrarProducto(db, id: 2, empresaId: 2, categoriaId: 2, nombre: 'Polera', codigo: 'IGUAL');
      expect(await _contar(db, 'producto'), 2);
    });

    test('el MISMO sku en dos empresas SÍ se permite', () async {
      await sembrarEmpresa(db);
      await sembrarEmpresa(db, id: 2, codigo: 'andes', nombre: 'Andes');
      await sembrarReferencias(db);
      await sembrarReferencias(db, empresaId: 2, categoriaId: 2);
      await sembrarProducto(db, id: 1, nombre: 'Polera', variantes: [variante(1, sku: 'MISMO')]);
      await sembrarProducto(
        db,
        id: 2,
        empresaId: 2,
        categoriaId: 2,
        nombre: 'Polera',
        variantes: [variante(2, tallaId: 201, colorId: 201, sku: 'MISMO')],
      );
      final filas = await db.query('variante', where: 'sku = ?', whereArgs: ['MISMO']);
      expect(filas, hasLength(2));
    });

    test('la misma talla y color dos veces en un producto falla', () async {
      await sembrarEmpresa(db);
      await sembrarReferencias(db);
      expect(
        () => sembrarProducto(db, id: 1, nombre: 'Polera', variantes: [variante(1), variante(2)]),
        throwsA(isA<DatabaseException>()),
      );
    });

    test('operacion_id duplicado falla', () async {
      await sembrarEmpresa(db);
      await sembrarSucursal(db, id: 1);
      await _operacion(db, 'op-1');
      expect(() => _operacion(db, 'op-1'), throwsA(isA<DatabaseException>()));
    });

    test('una operación solo tiene una venta', () async {
      await sembrarBase();
      await _operacion(db, 'op-1');
      await _venta(db, 'op-1');
      expect(() => _venta(db, 'op-1'), throwsA(isA<DatabaseException>()));
    });

    test('el mismo ci_nit en una empresa falla; sin ci_nit puede repetirse', () async {
      await sembrarEmpresa(db);
      Future<int> cliente(String? ci) =>
          db.insert('cliente_minimo', {'empresa_id': 1, 'nombre': 'X', 'ci_nit': ci, 'creado_en': '2026-10-31T10:00:00Z'});
      await cliente('123');
      expect(() => cliente('123'), throwsA(isA<DatabaseException>()));
      await cliente(null);
      await cliente(null);
      expect(await _contar(db, 'cliente_minimo'), 3);
    });
  });

  group('CASCADE', () {
    test('borrar una venta borra sus detalles', () async {
      await sembrarBase();
      await _operacion(db, 'op-1');
      final ventaId = await _venta(db, 'op-1');
      await db.insert('venta_detalle', {'venta_id': ventaId, 'variante_id': 1, 'cantidad': 2, 'precio_unitario_centavos': 7500});
      await db.insert('venta_detalle', {'venta_id': ventaId, 'variante_id': 1, 'cantidad': 1, 'precio_unitario_centavos': 7500});
      expect(await _contar(db, 'venta_detalle'), 2);
      await db.delete('venta', where: 'id = ?', whereArgs: [ventaId]);
      expect(await _contar(db, 'venta_detalle'), 0);
    });

    test('borrar una reserva borra sus detalles', () async {
      await sembrarBase();
      await _operacion(db, 'op-1', tipo: 'reserva');
      final reservaId = await _reserva(db, 'op-1', await _cliente(db));
      await db.insert('reserva_detalle', {'reserva_id': reservaId, 'variante_id': 1, 'cantidad': 2});
      await db.delete('reserva', where: 'id = ?', whereArgs: [reservaId]);
      expect(await _contar(db, 'reserva_detalle'), 0);
    });
  });
}
