import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/vendedor/data/catalogo_local_repository.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';

/// Pruebas de la vista `v_stock_local`: lo conocido menos lo que el servidor todavía no refleja.
void main() {
  const generado = '2026-10-31T10:00:00Z';

  late Database db;
  var contador = 0;
  int? clienteId;

  setUp(() async {
    contador = 0;
    clienteId = null;
    db = await abrirBaseDePrueba();
    await sembrarEmpresa(db);
    await sembrarSucursal(db, id: 1);
    await sembrarSucursal(db, id: 2);
    await sembrarReferencias(db);
    await sembrarProducto(db, id: 1, nombre: 'Polera', variantes: [variante(1, tallaId: 1), variante(2, tallaId: 2)]);
    await sembrarStock(db, varianteId: 1, sucursalId: 1, cantidad: 10, generadoEn: generado);
    await sembrarStock(db, varianteId: 2, sucursalId: 1, cantidad: 10, generadoEn: generado);
    await sembrarStock(db, varianteId: 1, sucursalId: 2, cantidad: 10, generadoEn: generado);
  });

  tearDown(() async {
    await db.close();
  });

  Future<void> operacion(String id, String tipo, String estado, {int sucursalId = 1, String? resuelta}) {
    return db.insert('operacion_pendiente', {
      'operacion_id': id,
      'empresa_id': 1,
      'sucursal_id': sucursalId,
      'usuario_id': 10,
      'tipo': tipo,
      'estado': estado,
      'payload': '{}',
      'version_contrato': 1,
      'fecha_operacion': '2026-10-31T09:00:00Z',
      'creada_en': '2026-10-31T09:00:00Z',
      'resuelta_en': resuelta,
    });
  }

  /// Registra una venta pendiente (con su operación) de [cantidad] unidades.
  Future<void> venta(String estado, int cantidad, {int varianteId = 1, int sucursalId = 1, String? resuelta}) async {
    final id = 'venta-${contador++}';
    await operacion(id, 'venta_contado', estado, sucursalId: sucursalId, resuelta: resuelta);
    final ventaId = await db.insert('venta', {
      'operacion_id': id,
      'empresa_id': 1,
      'sucursal_id': sucursalId,
      'usuario_id': 10,
      'fecha_operacion': '2026-10-31T09:00:00Z',
      'forma_pago': 'efectivo',
      'total_centavos': cantidad * 7500,
    });
    await db.insert('venta_detalle', {
      'venta_id': ventaId,
      'variante_id': varianteId,
      'cantidad': cantidad,
      'precio_unitario_centavos': 7500,
    });
  }

  Future<void> reserva(String estado, int cantidad, {int varianteId = 1, int sucursalId = 1, String? resuelta}) async {
    final id = 'reserva-${contador++}';
    await operacion(id, 'reserva', estado, sucursalId: sucursalId, resuelta: resuelta);
    clienteId ??= await db.insert('cliente_minimo', {'empresa_id': 1, 'nombre': 'Ana', 'creado_en': '2026-10-31T09:00:00Z'});
    final reservaId = await db.insert('reserva', {
      'operacion_id': id,
      'empresa_id': 1,
      'sucursal_id': sucursalId,
      'usuario_id': 10,
      'cliente_minimo_id': clienteId,
      'fecha_operacion': '2026-10-31T09:00:00Z',
      'fecha_visita': '2026-11-02',
      'hora_visita_desde': '10:00',
      'hora_visita_hasta': '11:00',
    });
    await db.insert('reserva_detalle', {'reserva_id': reservaId, 'variante_id': varianteId, 'cantidad': cantidad});
  }

  /// (conocida, estimada) de una variante en una sucursal.
  Future<(int, int)> stock({int varianteId = 1, int sucursalId = 1}) async {
    final fila = (await db.query(
      'v_stock_local',
      where: 'variante_id = ? AND sucursal_id = ?',
      whereArgs: [varianteId, sucursalId],
    ))
        .single;
    return (fila['cantidad_conocida']! as int, fila['cantidad_estimada']! as int);
  }

  group('ventas', () {
    test('sin operaciones, la estimada es igual a la conocida', () async {
      expect(await stock(), (10, 10));
      expect((await db.query('v_stock_local')).length, 3);
    });

    test('la vista trae generado_en del stock conocido', () async {
      final fila = (await db.query('v_stock_local', where: 'variante_id = 1 AND sucursal_id = 1')).single;
      expect(fila['generado_en'], generado);
    });

    test('una venta registrada resta', () async {
      await venta('registrada', 3);
      expect(await stock(), (10, 7));
    });

    test('una venta enviada resta', () async {
      await venta('enviada', 4);
      expect(await stock(), (10, 6));
    });

    test('una venta rechazada NO resta', () async {
      await venta('rechazada', 5, resuelta: '2026-10-31T12:00:00Z');
      expect(await stock(), (10, 10));
    });

    test('una venta en conflicto NO resta', () async {
      await venta('en_conflicto', 5, resuelta: '2026-10-31T12:00:00Z');
      expect(await stock(), (10, 10));
    });

    test('confirmada DESPUÉS del stock conocido resta (el servidor aún no la refleja)', () async {
      await venta('confirmada', 2, resuelta: '2026-10-31T10:00:01Z');
      expect(await stock(), (10, 8));
    });

    test('confirmada ANTES del stock conocido no resta (ya está reflejada)', () async {
      await venta('confirmada', 2, resuelta: '2026-10-31T09:59:59Z');
      expect(await stock(), (10, 10));
    });

    test('confirmada EN el mismo instante del stock conocido no resta', () async {
      await venta('confirmada', 2, resuelta: generado);
      expect(await stock(), (10, 10));
    });

    test('confirmada sin resuelta_en no resta', () async {
      await venta('confirmada', 2);
      expect(await stock(), (10, 10));
    });

    test('al refrescar el stock (generado_en nuevo) la confirmada deja de restar', () async {
      await venta('confirmada', 2, resuelta: '2026-10-31T10:30:00Z');
      expect(await stock(), (10, 8));
      await db.update('stock_conocido', {'generado_en': '2026-10-31T11:00:00Z', 'cantidad': 8}, where: 'variante_id = 1 AND sucursal_id = 1');
      expect(await stock(), (8, 8));
    });
  });

  group('reservas', () {
    test('una reserva registrada resta igual que una venta', () async {
      await reserva('registrada', 3);
      expect(await stock(), (10, 7));
    });

    test('una reserva enviada resta', () async {
      await reserva('enviada', 2);
      expect(await stock(), (10, 8));
    });

    test('rechazada y en conflicto no restan', () async {
      await reserva('rechazada', 5, resuelta: '2026-10-31T12:00:00Z');
      await reserva('en_conflicto', 5, resuelta: '2026-10-31T12:00:00Z');
      expect(await stock(), (10, 10));
    });

    test('confirmada resta solo si es posterior al stock conocido', () async {
      await reserva('confirmada', 2, resuelta: '2026-10-31T10:00:01Z');
      await reserva('confirmada', 4, resuelta: '2026-10-31T09:00:00Z');
      expect(await stock(), (10, 8));
    });
  });

  group('combinaciones', () {
    test('nunca baja de 0', () async {
      await venta('registrada', 25);
      expect(await stock(), (10, 0));
      await reserva('enviada', 7);
      expect(await stock(), (10, 0));
    });

    test('suma varias operaciones de ventas y reservas', () async {
      await venta('registrada', 2);
      await venta('enviada', 1);
      await reserva('registrada', 4);
      await venta('rechazada', 9); // no cuenta
      expect(await stock(), (10, 3));
    });

    test('otra sucursal no afecta', () async {
      await venta('registrada', 6, sucursalId: 2);
      expect(await stock(sucursalId: 1), (10, 10));
      expect(await stock(sucursalId: 2), (10, 4));
    });

    test('otra variante no afecta', () async {
      await venta('registrada', 6, varianteId: 2);
      expect(await stock(varianteId: 1), (10, 10));
      expect(await stock(varianteId: 2), (10, 4));
    });

    test('una venta con dos líneas de la misma variante resta ambas', () async {
      await venta('registrada', 2);
      final ventaId = (await db.query('venta')).single['id']! as int;
      await db.insert('venta_detalle', {'venta_id': ventaId, 'variante_id': 1, 'cantidad': 3, 'precio_unitario_centavos': 7500});
      expect(await stock(), (10, 5));
    });

    test('borrar la venta (cascade) devuelve la existencia', () async {
      await venta('registrada', 4);
      expect(await stock(), (10, 6));
      await db.delete('venta');
      expect(await stock(), (10, 10));
    });

    test('una variante sin stock descargado no aparece en la vista', () async {
      await sembrarProducto(db, id: 2, nombre: 'Otra', variantes: [variante(30, tallaId: 3)]);
      final filas = await db.query('v_stock_local', where: 'variante_id = 30');
      expect(filas, isEmpty);
    });
  });

  group('en el listado del catálogo', () {
    test('la existencia del producto refleja las operaciones pendientes', () async {
      final repo = CatalogoLocalSqlite(db, empresaId: 1);
      expect((await repo.productoPorId(1, sucursalId: 1))!.existenciaEstimada, 20);
      await venta('registrada', 5, varianteId: 1);
      await reserva('enviada', 3, varianteId: 2);
      await venta('rechazada', 8, varianteId: 2);
      expect((await repo.productoPorId(1, sucursalId: 1))!.existenciaEstimada, 12);
      expect((await repo.productoPorId(1, sucursalId: 2))!.existenciaEstimada, 10);
      final variantes = await repo.variantesDeProducto(1, sucursalId: 1);
      expect(variantes.map((v) => v.cantidadEstimada), [5, 7]);
      expect(variantes.map((v) => v.cantidadConocida), [10, 10]);
    });
  });
}
