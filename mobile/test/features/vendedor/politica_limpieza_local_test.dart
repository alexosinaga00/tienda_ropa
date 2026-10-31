import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/vendedor/data/politica_limpieza_local.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';
import 'apoyo_operaciones.dart';
import 'apoyo_paquete.dart';

/// Hoy es 2026-10-31 12:00 UTC; el límite de retención es 2026-10-01 12:00 UTC (30 días antes).
String _haceDias(int dias, {int horas = 0}) =>
    DateTime.utc(2026, 10, 31, 12).subtract(Duration(days: dias, hours: horas)).toIso8601String();

void main() {
  late Database db;
  late RelojManual reloj;
  late PoliticaLimpiezaLocalSqlite politica;

  setUp(() async {
    db = await abrirBaseDePrueba();
    addTearDown(db.close);
    await sembrarDosEmpresas(db);
    reloj = RelojManual(DateTime.utc(2026, 10, 31, 12));
    politica = PoliticaLimpiezaLocalSqlite(db, reloj);
  });

  Future<ResultadoLimpieza> limpiar({int empresaId = 1, int usuarioId = 7}) =>
      politica.alCerrarSesion(empresaId: empresaId, usuarioId: usuarioId);

  Future<List<String>> operaciones() async {
    final filas = await db.query('operacion_pendiente', columns: ['operacion_id'], orderBy: 'operacion_id');
    return [for (final f in filas) f['operacion_id']! as String];
  }

  const tablasDeCatalogo = [
    'empresa',
    'sucursal',
    'categoria',
    'talla',
    'color',
    'producto',
    'variante',
    'stock_conocido',
  ];

  Future<Map<String, int>> fotoDeCatalogo() async => {for (final t in tablasDeCatalogo) t: await contar(db, t)};

  test('la retención de operaciones resueltas es de 30 días', () {
    expect(retencionOperacionesResueltas, const Duration(days: 30));
  });

  group('con operaciones pendientes del usuario', () {
    for (final estado in ['registrada', 'enviada', 'en_conflicto']) {
      test("una operación '$estado' impide borrar nada: purgo=false y pendientes=1", () async {
        await sembrarOperacion(db, id: 'pend', estado: estado);
        await sembrarOperacion(db, id: 'vieja', estado: 'confirmada', creadaEn: _haceDias(60), resueltaEn: _haceDias(59));
        await sembrarCliente(db, nombre: 'Huérfano');

        final r = await limpiar();

        expect(r.pendientes, 1);
        expect(r.purgo, isFalse);
        expect(await operaciones(), ['pend', 'vieja']);
        expect(await contar(db, 'cliente_minimo'), 1);
        expect(await contar(db, 'venta'), 2);
        expect(await contar(db, 'venta_detalle'), 2);
      });
    }

    test('cuenta todas las pendientes del usuario', () async {
      await sembrarOperacion(db, id: 'a', estado: 'registrada');
      await sembrarOperacion(db, id: 'b', estado: 'enviada');
      await sembrarOperacion(db, id: 'c', estado: 'en_conflicto');

      final r = await limpiar();

      expect(r.pendientes, 3);
      expect(r.purgo, isFalse);
    });

    test('no borra lo que ellas referencian: cliente, venta, reserva y sus detalles', () async {
      final cliente = await sembrarCliente(db, nombre: 'Ana');
      await sembrarOperacion(db, id: 'venta-pend', estado: 'registrada', clienteId: cliente);
      await sembrarOperacion(db, id: 'reserva-pend', tipo: 'reserva', estado: 'enviada', clienteId: cliente);
      await sembrarCliente(db, nombre: 'Sin uso');

      final r = await limpiar();

      expect(r.purgo, isFalse);
      expect(await contar(db, 'cliente_minimo'), 2, reason: 'ni siquiera el huérfano se borra mientras haya pendientes');
      expect(await contar(db, 'venta'), 1);
      expect(await contar(db, 'venta_detalle'), 1);
      expect(await contar(db, 'reserva'), 1);
      expect(await contar(db, 'reserva_detalle'), 1);
    });

    test('conserva el catálogo y el stock', () async {
      await sembrarOperacion(db, id: 'pend');
      final antes = await fotoDeCatalogo();

      await limpiar();

      expect(await fotoDeCatalogo(), antes);
    });

    test('las confirmadas y rechazadas no cuentan como pendientes', () async {
      await sembrarOperacion(db, id: 'ok', estado: 'confirmada', creadaEn: _haceDias(1), resueltaEn: _haceDias(1));
      await sembrarOperacion(db, id: 'no', estado: 'rechazada', creadaEn: _haceDias(1), resueltaEn: _haceDias(1));

      final r = await limpiar();

      expect(r.pendientes, 0);
      expect(r.purgo, isTrue);
    });
  });

  group('sin pendientes: depuración de operaciones resueltas', () {
    test('borra las confirmadas y rechazadas de más de 30 días y deja las recientes', () async {
      await sembrarOperacion(db, id: 'conf-vieja', estado: 'confirmada', creadaEn: _haceDias(45), resueltaEn: _haceDias(40));
      await sembrarOperacion(db, id: 'rech-vieja', estado: 'rechazada', creadaEn: _haceDias(45), resueltaEn: _haceDias(31));
      await sembrarOperacion(db, id: 'conf-reciente', estado: 'confirmada', creadaEn: _haceDias(10), resueltaEn: _haceDias(9));
      await sembrarOperacion(db, id: 'rech-reciente', estado: 'rechazada', creadaEn: _haceDias(2), resueltaEn: _haceDias(1));

      final r = await limpiar();

      expect(r.pendientes, 0);
      expect(r.purgo, isTrue);
      expect(await operaciones(), ['conf-reciente', 'rech-reciente']);
    });

    test('el límite es estricto: a exactamente 30 días se conserva; un instante más, se borra', () async {
      await sembrarOperacion(db, id: 'justo', estado: 'confirmada', creadaEn: _haceDias(40), resueltaEn: _haceDias(30));
      await sembrarOperacion(db, id: 'pasado', estado: 'confirmada', creadaEn: _haceDias(40), resueltaEn: _haceDias(30, horas: 1));

      await limpiar();

      expect(await operaciones(), ['justo']);
    });

    test('usa resuelta_en si existe: creada hace 40 días pero resuelta hace 5 se conserva', () async {
      await sembrarOperacion(db, id: 'resuelta-ayer', estado: 'confirmada', creadaEn: _haceDias(40), resueltaEn: _haceDias(5));
      await sembrarOperacion(db, id: 'creada-ayer', estado: 'confirmada', creadaEn: _haceDias(5), resueltaEn: _haceDias(40));

      await limpiar();

      expect(await operaciones(), ['resuelta-ayer']);
    });

    test('sin resuelta_en usa creada_en', () async {
      await sembrarOperacion(db, id: 'sin-resuelta-vieja', estado: 'rechazada', creadaEn: _haceDias(50));
      await sembrarOperacion(db, id: 'sin-resuelta-nueva', estado: 'rechazada', creadaEn: _haceDias(3));

      await limpiar();

      expect(await operaciones(), ['sin-resuelta-nueva']);
    });

    test('entiende las fechas del servidor con y sin milisegundos', () async {
      await sembrarOperacion(db, id: 'con-ms', estado: 'confirmada', creadaEn: '2026-08-01T10:00:00.000Z', resueltaEn: '2026-08-01T10:00:00.000Z');
      await sembrarOperacion(db, id: 'sin-ms', estado: 'confirmada', creadaEn: '2026-08-01T10:00:00Z', resueltaEn: '2026-08-01T10:00:00Z');

      await limpiar();

      expect(await operaciones(), isEmpty);
    });

    test('una fecha ilegible nunca se considera vencida: ante la duda se conserva', () async {
      await sembrarOperacion(db, id: 'rara', estado: 'confirmada', creadaEn: 'ayer por la tarde', resueltaEn: 'no es fecha');

      final r = await limpiar();

      expect(r.purgo, isTrue);
      expect(await operaciones(), ['rara']);
    });

    test('borra también la venta, el detalle, la reserva y las respuestas del servidor de la operación', () async {
      final cliente = await sembrarCliente(db, nombre: 'Ana');
      await sembrarOperacion(
        db,
        id: 'venta-vieja',
        estado: 'confirmada',
        creadaEn: _haceDias(60),
        resueltaEn: _haceDias(59),
        clienteId: cliente,
        conResultado: true,
      );
      await sembrarOperacion(
        db,
        id: 'reserva-vieja',
        tipo: 'reserva',
        estado: 'rechazada',
        creadaEn: _haceDias(60),
        resueltaEn: _haceDias(59),
        clienteId: cliente,
        conResultado: true,
      );

      await limpiar();

      for (final tabla in ['operacion_pendiente', 'venta', 'venta_detalle', 'reserva', 'reserva_detalle', 'resultado_sync']) {
        expect(await contar(db, tabla), 0, reason: tabla);
      }
    });

    test('lo que se conserva queda completo con sus hijos', () async {
      await sembrarOperacion(db, id: 'vieja', estado: 'confirmada', creadaEn: _haceDias(60), resueltaEn: _haceDias(59), conResultado: true);
      await sembrarOperacion(db, id: 'nueva', estado: 'confirmada', creadaEn: _haceDias(2), resueltaEn: _haceDias(1), conResultado: true);

      await limpiar();

      expect(await contar(db, 'venta'), 1);
      expect(await contar(db, 'venta_detalle'), 1);
      expect(await contar(db, 'resultado_sync', donde: "operacion_id = 'nueva'"), 1);
      expect(await contar(db, 'resultado_sync', donde: "operacion_id = 'vieja'"), 0);
    });

    test('conserva TODO el catálogo y el stock', () async {
      await sembrarOperacion(db, id: 'vieja', estado: 'confirmada', creadaEn: _haceDias(60), resueltaEn: _haceDias(59));
      await db.insert('descarga', {
        'empresa_id': 1,
        'sucursal_id': 1,
        'descargado_en': '2026-10-31T10:00:00Z',
        'generado_en': '2026-10-31T10:00:00Z',
        'completo': 1,
      });
      await db.insert('sucursal_autorizada', {'usuario_id': 7, 'sucursal_id': 1});
      final antes = await fotoDeCatalogo();
      final stockAntes = await stockDe(db, 1);

      await limpiar();

      expect(await fotoDeCatalogo(), antes);
      expect(await stockDe(db, 1), stockAntes);
      expect(await contar(db, 'descarga'), 1);
      expect(await contar(db, 'sucursal_autorizada'), 1);
      expect(await contar(db, 'meta', donde: "clave = 'version_esquema'"), 1);
    });

    test('es idempotente: una segunda limpieza no cambia nada', () async {
      await sembrarOperacion(db, id: 'vieja', estado: 'confirmada', creadaEn: _haceDias(60), resueltaEn: _haceDias(59));
      await sembrarOperacion(db, id: 'nueva', estado: 'confirmada', creadaEn: _haceDias(2), resueltaEn: _haceDias(1));
      await limpiar();
      final despues = await operaciones();

      final r = await limpiar();

      expect(r.purgo, isTrue);
      expect(await operaciones(), despues);
    });

    test('sin ninguna operación ni cliente no falla', () async {
      final r = await limpiar();

      expect(r.pendientes, 0);
      expect(r.purgo, isTrue);
    });

    test('con el reloj fijo: al avanzar el tiempo, lo reciente pasa a vencido', () async {
      await sembrarOperacion(db, id: 'de-hace-10', estado: 'confirmada', creadaEn: _haceDias(10), resueltaEn: _haceDias(10));

      await limpiar();
      expect(await operaciones(), ['de-hace-10']);

      reloj.actual = reloj.actual.add(const Duration(days: 21));
      await limpiar();

      expect(await operaciones(), isEmpty);
    });

    test('integridad referencial: las llaves foráneas están activas y nada queda huérfano', () async {
      final foreignKeys = await db.rawQuery('PRAGMA foreign_keys');
      expect(foreignKeys.first.values.first, 1);
      final cliente = await sembrarCliente(db, nombre: 'Ana');
      await sembrarOperacion(db, id: 'v1', estado: 'confirmada', creadaEn: _haceDias(60), resueltaEn: _haceDias(59), clienteId: cliente, conResultado: true);
      await sembrarOperacion(db, id: 'r1', tipo: 'reserva', estado: 'rechazada', creadaEn: _haceDias(60), resueltaEn: _haceDias(59), clienteId: cliente, conResultado: true);
      await sembrarOperacion(db, id: 'v2', estado: 'confirmada', creadaEn: _haceDias(1), resueltaEn: _haceDias(1), clienteId: cliente);

      await limpiar();

      expect(await db.rawQuery('PRAGMA foreign_key_check'), isEmpty);
      expect(await contar(db, 'cliente_minimo'), 1, reason: 'sigue referenciado por la venta reciente');
    });
  });

  group('clientes creados en el teléfono', () {
    test('borra los que ninguna venta ni reserva referencia', () async {
      await sembrarCliente(db, nombre: 'Huérfano 1');
      await sembrarCliente(db, nombre: 'Huérfano 2', ciNit: '999');

      await limpiar();

      expect(await contar(db, 'cliente_minimo'), 0);
    });

    test('conserva los referenciados por una venta o por una reserva', () async {
      final deVenta = await sembrarCliente(db, nombre: 'De venta');
      final deReserva = await sembrarCliente(db, nombre: 'De reserva');
      await sembrarCliente(db, nombre: 'Huérfano');
      await sembrarOperacion(db, id: 'v', estado: 'confirmada', creadaEn: _haceDias(1), resueltaEn: _haceDias(1), clienteId: deVenta);
      await sembrarOperacion(db, id: 'r', tipo: 'reserva', estado: 'confirmada', creadaEn: _haceDias(1), resueltaEn: _haceDias(1), clienteId: deReserva);

      await limpiar();

      final filas = await db.query('cliente_minimo', columns: ['nombre'], orderBy: 'nombre');
      expect([for (final f in filas) f['nombre']], ['De reserva', 'De venta']);
    });

    test('conserva los que vienen del servidor (servidor_id), aunque nadie los use', () async {
      await sembrarCliente(db, nombre: 'Del servidor', servidorId: 55, ciNit: '111');
      await sembrarCliente(db, nombre: 'Hecho aquí');

      await limpiar();

      final filas = await db.query('cliente_minimo', columns: ['nombre']);
      expect([for (final f in filas) f['nombre']], ['Del servidor']);
    });

    test('un cliente de una operación vencida también se borra en la misma limpieza', () async {
      final cliente = await sembrarCliente(db, nombre: 'Solo de la vieja');
      await sembrarOperacion(db, id: 'vieja', estado: 'confirmada', creadaEn: _haceDias(60), resueltaEn: _haceDias(59), clienteId: cliente);

      await limpiar();

      expect(await contar(db, 'cliente_minimo'), 0);
      expect(await contar(db, 'venta'), 0);
    });

    test('un cliente de la operación vencida que otra operación reciente también usa se conserva', () async {
      final cliente = await sembrarCliente(db, nombre: 'Compartido');
      await sembrarOperacion(db, id: 'vieja', estado: 'confirmada', creadaEn: _haceDias(60), resueltaEn: _haceDias(59), clienteId: cliente);
      await sembrarOperacion(db, id: 'nueva', estado: 'confirmada', creadaEn: _haceDias(1), resueltaEn: _haceDias(1), clienteId: cliente);

      await limpiar();

      expect(await contar(db, 'cliente_minimo'), 1);
    });
  });

  group('aislamiento por usuario', () {
    test('las operaciones vencidas de otro usuario NO se borran', () async {
      await sembrarOperacion(db, id: 'mia-vieja', estado: 'confirmada', creadaEn: _haceDias(60), resueltaEn: _haceDias(59));
      await sembrarOperacion(db, id: 'ajena-vieja', usuarioId: 8, estado: 'confirmada', creadaEn: _haceDias(60), resueltaEn: _haceDias(59));
      await sembrarOperacion(db, id: 'ajena-rechazada', usuarioId: 8, estado: 'rechazada', creadaEn: _haceDias(90), resueltaEn: _haceDias(80), conResultado: true);

      final r = await limpiar();

      expect(r.purgo, isTrue);
      expect(await operaciones(), ['ajena-rechazada', 'ajena-vieja']);
      expect(await contar(db, 'venta', donde: 'usuario_id = 8'), 2);
      expect(await contar(db, 'resultado_sync'), 1);
    });

    test('las pendientes de otro usuario no cuentan para este ni impiden su depuración', () async {
      await sembrarOperacion(db, id: 'ajena-pend', usuarioId: 8, estado: 'registrada');
      await sembrarOperacion(db, id: 'mia-vieja', estado: 'confirmada', creadaEn: _haceDias(60), resueltaEn: _haceDias(59));

      final r = await limpiar();

      expect(r.pendientes, 0);
      expect(r.purgo, isTrue);
      expect(await operaciones(), ['ajena-pend']);
    });

    test('los clientes que usa una operación pendiente de otro usuario se conservan', () async {
      final cliente = await sembrarCliente(db, nombre: 'Del colega');
      await sembrarOperacion(db, id: 'ajena-pend', usuarioId: 8, estado: 'en_conflicto', clienteId: cliente);
      await sembrarOperacion(db, id: 'ajena-reserva', usuarioId: 8, tipo: 'reserva', estado: 'enviada', clienteId: cliente);
      await sembrarCliente(db, nombre: 'Huérfano');

      await limpiar();

      final filas = await db.query('cliente_minimo', columns: ['nombre']);
      expect([for (final f in filas) f['nombre']], ['Del colega']);
      expect(await contar(db, 'venta'), 1);
      expect(await contar(db, 'reserva'), 1);
    });

    test('el otro usuario, al cerrar su sesión, no depura las operaciones de este', () async {
      await sembrarOperacion(db, id: 'mia-vieja', estado: 'confirmada', creadaEn: _haceDias(60), resueltaEn: _haceDias(59));

      await limpiar(usuarioId: 8);

      expect(await operaciones(), ['mia-vieja']);
    });
  });

  group('aislamiento por empresa', () {
    test('no toca nada de otra empresa, ni vencido ni pendiente ni clientes', () async {
      await sembrarOperacion(db, id: 'e1-vieja', estado: 'confirmada', creadaEn: _haceDias(60), resueltaEn: _haceDias(59));
      await sembrarOperacion(
        db,
        id: 'e2-vieja',
        empresaId: 2,
        sucursalId: 11,
        varianteId: 200,
        estado: 'confirmada',
        creadaEn: _haceDias(60),
        resueltaEn: _haceDias(59),
        conResultado: true,
      );
      await sembrarCliente(db, empresaId: 1, nombre: 'Huérfano E1');
      await sembrarCliente(db, empresaId: 2, nombre: 'Huérfano E2');

      await limpiar();

      expect(await operaciones(), ['e2-vieja']);
      final clientes = await db.query('cliente_minimo', columns: ['empresa_id', 'nombre']);
      expect(clientes, hasLength(1));
      expect(clientes.single['nombre'], 'Huérfano E2');
      expect(await contar(db, 'venta', donde: 'empresa_id = 2'), 1);
      expect(await contar(db, 'resultado_sync'), 1);
    });

    test('una pendiente del mismo usuario en OTRA empresa no impide depurar esta', () async {
      await sembrarOperacion(db, id: 'e2-pend', empresaId: 2, sucursalId: 11, varianteId: 200, estado: 'registrada');
      await sembrarOperacion(db, id: 'e1-vieja', estado: 'confirmada', creadaEn: _haceDias(60), resueltaEn: _haceDias(59));

      final r = await limpiar();

      expect(r.pendientes, 0);
      expect(r.purgo, isTrue);
      expect(await operaciones(), ['e2-pend']);
    });

    test('la otra empresa tampoco cambia su catálogo ni su stock', () async {
      await sembrarOperacion(db, id: 'e1-vieja', estado: 'confirmada', creadaEn: _haceDias(60), resueltaEn: _haceDias(59));
      final antes = await fotoDeCatalogo();

      await limpiar();
      await limpiar(empresaId: 2);

      expect(await fotoDeCatalogo(), antes);
      expect(await stockDe(db, 11), {200: 4});
    });
  });
}
