import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/sync/cola_operaciones.dart';
import 'package:mobile/core/sync/cola_operaciones_sqlite.dart';
import 'package:mobile/core/sync/contrato_sync.dart';
import 'package:mobile/core/sync/lineas_operacion.dart';
import 'package:mobile/core/sync/operacion_pendiente.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';
import '../../helpers/siembra_operaciones.dart';

Matcher colaError([String? contiene]) => throwsA(
  isA<ColaError>().having((e) => e.mensaje, 'mensaje', contiene == null ? isNotEmpty : contains(contiene)),
);

void main() {
  late Database db;
  late RelojDePrueba reloj;
  late ColaOperacionesSqlite cola;

  setUp(() async {
    db = await abrirBaseDePrueba();
    await sembrarMundoDeOperaciones(db);
    reloj = RelojDePrueba(DateTime.utc(2026, 10, 31, 12));
    cola = ColaOperacionesSqlite(db, reloj);
  });

  tearDown(() async {
    await cola.dispose();
    await db.close();
  });

  // ---- Atajos ----

  NuevaVenta venta({
    String id = 'id-v1',
    int empresaId = 1,
    int sucursalId = 1,
    int usuarioId = 7,
    DateTime? fecha,
    List<LineaVenta>? lineas,
    int? cliente,
    bool efectivo = true,
  }) {
    return NuevaVenta(
      operacionId: id,
      empresaId: empresaId,
      sucursalId: sucursalId,
      usuarioId: usuarioId,
      fechaOperacion: fecha ?? DateTime.utc(2026, 10, 31, 14),
      lineas: lineas ?? const [LineaVenta(varianteId: 100, cantidad: 2, precioUnitarioCentavos: 7500)],
      clienteMinimoId: cliente,
      efectivoConfirmado: efectivo,
    );
  }

  NuevaReserva reserva({
    String id = 'id-r1',
    int empresaId = 1,
    int sucursalId = 1,
    int usuarioId = 7,
    DateTime? fecha,
    int cliente = 1,
    DateTime? visita,
    String desde = '10:00',
    String hasta = '11:00',
    String? observacion,
    List<LineaReserva>? lineas,
  }) {
    return NuevaReserva(
      operacionId: id,
      empresaId: empresaId,
      sucursalId: sucursalId,
      usuarioId: usuarioId,
      fechaOperacion: fecha ?? DateTime.utc(2026, 10, 31, 15),
      clienteMinimoId: cliente,
      fechaVisita: visita ?? DateTime(2026, 11, 2),
      horaDesde: desde,
      horaHasta: hasta,
      observacion: observacion,
      lineas: lineas ?? const [LineaReserva(varianteId: 100, cantidad: 1)],
    );
  }

  Future<Map<String, Object?>> fila(String id) async =>
      (await db.query('operacion_pendiente', where: 'operacion_id = ?', whereArgs: [id])).single;

  Future<void> poner(String id, String estado, {int? intentos, String? proximo, String? resuelta}) => db.update(
    'operacion_pendiente',
    {'estado': estado, 'intentos': ?intentos, 'proximo_reintento_en': ?proximo, 'resuelta_en': ?resuelta},
    where: 'operacion_id = ?',
    whereArgs: [id],
  );

  /// Registra una venta y la lleva al estado pedido (por SQL, sin pasar por las reglas).
  Future<void> ventaEn(String id, String estado, {DateTime? fecha, int usuarioId = 7, int intentos = 0}) async {
    await cola.registrarVenta(venta(id: id, fecha: fecha, usuarioId: usuarioId));
    if (estado != 'registrada') await poner(id, estado, intentos: intentos);
  }

  Future<int> estimado({int varianteId = 100, int sucursalId = 1}) async {
    final f = await db.rawQuery(
      'SELECT cantidad_estimada AS n FROM v_stock_local WHERE variante_id = ? AND sucursal_id = ?',
      [varianteId, sucursalId],
    );
    return f.single['n']! as int;
  }

  // =========================================================================================
  group('registrarVenta: lo que se guarda', () {
    test('guarda la operación, la venta y sus detalles', () async {
      await cola.registrarVenta(
        venta(
          cliente: 1,
          lineas: const [
            LineaVenta(varianteId: 100, cantidad: 2, precioUnitarioCentavos: 7500),
            LineaVenta(varianteId: 101, cantidad: 1, precioUnitarioCentavos: 5000, descuentoUnitarioCentavos: 500),
          ],
        ),
      );

      final op = await fila('id-v1');
      expect(op['empresa_id'], 1);
      expect(op['sucursal_id'], 1);
      expect(op['usuario_id'], 7);
      expect(op['tipo'], 'venta_contado');
      expect(op['estado'], 'registrada');
      expect(op['version_contrato'], 1);
      expect(op['intentos'], 0);
      expect(op['ultimo_error'], isNull);
      expect(op['proximo_reintento_en'], isNull);
      expect(op['resuelta_en'], isNull);

      final ventas = await db.query('venta');
      expect(ventas, hasLength(1));
      expect(ventas.single['operacion_id'], 'id-v1');
      expect(ventas.single['forma_pago'], 'efectivo');
      expect(ventas.single['efectivo_confirmado'], 1);
      expect(ventas.single['total_centavos'], 19500);
      expect(ventas.single['cliente_minimo_id'], 1);

      final detalles = await db.query('venta_detalle', orderBy: 'id');
      expect(detalles, hasLength(2));
      expect(detalles[0]['variante_id'], 100);
      expect(detalles[0]['cantidad'], 2);
      expect(detalles[0]['precio_unitario_centavos'], 7500);
      expect(detalles[1]['variante_id'], 101);
      expect(detalles[1]['cantidad'], 1);
      expect(detalles[1]['precio_unitario_centavos'], 5000);
      expect(detalles.every((d) => d['venta_id'] == ventas.single['id']), isTrue);
    });

    test('el payload coincide con las tablas (total e items)', () async {
      await cola.registrarVenta(
        venta(
          cliente: 1,
          lineas: const [
            LineaVenta(varianteId: 100, cantidad: 2, precioUnitarioCentavos: 7500),
            LineaVenta(varianteId: 101, cantidad: 3, precioUnitarioCentavos: 5000, descuentoUnitarioCentavos: 500),
          ],
        ),
      );
      final payload = jsonDecode((await fila('id-v1'))['payload']! as String) as Map<String, dynamic>;
      final total = (await db.query('venta')).single['total_centavos']! as int;
      final detalles = await db.query('venta_detalle', orderBy: 'id');

      expect(payload['total'], '${total ~/ 100}.${(total % 100).toString().padLeft(2, '0')}');
      final items = payload['lineas'] as List;
      expect(items, hasLength(detalles.length));
      for (var i = 0; i < items.length; i++) {
        final item = items[i] as Map;
        expect(item['variante_id'], detalles[i]['variante_id']);
        expect(item['cantidad'], detalles[i]['cantidad']);
        final centavos = detalles[i]['precio_unitario_centavos']! as int;
        expect(item['precio_unitario'], '${centavos ~/ 100}.${(centavos % 100).toString().padLeft(2, '0')}');
      }
    });

    test('el payload exacto: el cliente va por su id del SERVIDOR, no por el local', () async {
      await cola.registrarVenta(
        venta(
          cliente: 1,
          lineas: const [
            LineaVenta(varianteId: 100, cantidad: 2, precioUnitarioCentavos: 7500),
            LineaVenta(varianteId: 101, cantidad: 1, precioUnitarioCentavos: 5000, descuentoUnitarioCentavos: 500),
          ],
        ),
      );
      final payload = jsonDecode((await fila('id-v1'))['payload']! as String);
      expect(payload, {
        'cliente_id': 501,
        'lineas': [
          {'variante_id': 100, 'cantidad': 2, 'precio_unitario': '75.00', 'descuento_unitario': '0.00'},
          {'variante_id': 101, 'cantidad': 1, 'precio_unitario': '50.00', 'descuento_unitario': '5.00'},
        ],
        'total': '195.00',
        'pago': {'metodo': 'efectivo', 'monto_recibido': '195.00'},
      });
    });

    test('el payload guardado es el mismo que arma OperacionEnvio al enviar', () async {
      await cola.registrarVenta(venta(cliente: 1));
      final guardada = (await cola.obtener('id-v1'))!;
      final envio = OperacionEnvio.desde(guardada).toJson();
      expect(envio['payload'], jsonDecode(guardada.payload));
      expect(envio['operacion_id'], 'id-v1');
      expect(envio['sucursal_id'], 1);
      expect(envio['fecha_operacion'], '2026-10-31T14:00:00Z');
    });

    test('una venta sin cliente no manda cliente_id y deja cliente_minimo_id en NULL', () async {
      await cola.registrarVenta(venta());
      final payload = jsonDecode((await fila('id-v1'))['payload']! as String) as Map;
      expect(payload.containsKey('cliente_id'), isFalse);
      expect((await db.query('venta')).single['cliente_minimo_id'], isNull);
    });

    test('el descuento solo viaja en el payload (el detalle guarda el precio de lista)', () async {
      await cola.registrarVenta(
        venta(lineas: const [LineaVenta(varianteId: 100, cantidad: 2, precioUnitarioCentavos: 7500, descuentoUnitarioCentavos: 1000)]),
      );
      final detalle = (await db.query('venta_detalle')).single;
      expect(detalle['precio_unitario_centavos'], 7500);
      final linea = ((jsonDecode((await fila('id-v1'))['payload']! as String) as Map)['lineas'] as List).single as Map;
      expect(linea['descuento_unitario'], '10.00');
      expect((await db.query('venta')).single['total_centavos'], 13000, reason: '(7500 - 1000) x 2');
    });

    test('el total y el monto recibido salen de la cuenta de las líneas', () async {
      await cola.registrarVenta(
        venta(
          lineas: const [
            LineaVenta(varianteId: 100, cantidad: 3, precioUnitarioCentavos: 1999),
            LineaVenta(varianteId: 101, cantidad: 1, precioUnitarioCentavos: 5, descuentoUnitarioCentavos: 5),
          ],
        ),
      );
      final payload = jsonDecode((await fila('id-v1'))['payload']! as String) as Map;
      expect(payload['total'], '59.97');
      expect((payload['pago'] as Map)['monto_recibido'], '59.97');
    });

    test('una venta gratis (descuento igual al precio) es válida: total 0', () async {
      await cola.registrarVenta(
        venta(lineas: const [LineaVenta(varianteId: 100, cantidad: 1, precioUnitarioCentavos: 7500, descuentoUnitarioCentavos: 7500)]),
      );
      expect((await db.query('venta')).single['total_centavos'], 0);
    });

    test('la misma variante en dos líneas se acepta (dos filas de detalle)', () async {
      await cola.registrarVenta(
        venta(
          lineas: const [
            LineaVenta(varianteId: 100, cantidad: 1, precioUnitarioCentavos: 7500),
            LineaVenta(varianteId: 100, cantidad: 2, precioUnitarioCentavos: 7000),
          ],
        ),
      );
      expect(await contarFilas(db, 'venta_detalle'), 2);
    });

    test('las fechas se guardan en UTC con Z: la de la operación y la de creación', () async {
      reloj.actual = DateTime.utc(2026, 10, 31, 12, 30, 15);
      await cola.registrarVenta(venta(fecha: DateTime(2026, 10, 31, 9, 0)));
      final op = await fila('id-v1');
      final esperada = DateTime(2026, 10, 31, 9, 0).toUtc();
      expect(op['fecha_operacion'], endsWith('Z'));
      expect(DateTime.parse(op['fecha_operacion']! as String), esperada);
      expect(op['creada_en'], '2026-10-31T12:30:15Z');
      expect((await db.query('venta')).single['fecha_operacion'], op['fecha_operacion']);
    });

    test('creada_en usa el reloj inyectado, no el del sistema', () async {
      reloj.actual = DateTime.utc(2030, 1, 2, 3, 4, 5);
      await cola.registrarVenta(venta());
      expect((await fila('id-v1'))['creada_en'], '2030-01-02T03:04:05Z');
    });

    test('el id se guarda en minúscula', () async {
      await cola.registrarVenta(venta(id: 'AAAA-BBBB'));
      expect((await db.query('operacion_pendiente')).single['operacion_id'], 'aaaa-bbbb');
      expect(await cola.obtener('AAAA-BBBB'), isNotNull);
      expect(await cola.obtener('aaaa-bbbb'), isNotNull);
    });

    test('una venta no deja nada en resultado_sync ni toca el stock conocido', () async {
      await cola.registrarVenta(venta());
      expect(await contarFilas(db, 'resultado_sync'), 0);
      final stock = await db.query('stock_conocido', where: 'variante_id = 100');
      expect(stock.single['cantidad'], 10);
    });
  });

  // =========================================================================================
  group('registrarVenta: validaciones (no deja NADA guardado)', () {
    Future<void> sinRastro(NuevaVenta v, [String? mensaje]) async {
      final antes = await huellaDeRegistro(db);
      await expectLater(cola.registrarVenta(v), colaError(mensaje));
      expect(await huellaDeRegistro(db), antes);
    }

    test('sin líneas', () => sinRastro(venta(lineas: const []), 'al menos una prenda'));

    test('cantidad cero', () {
      return sinRastro(venta(lineas: const [LineaVenta(varianteId: 100, cantidad: 0, precioUnitarioCentavos: 7500)]), 'cantidad');
    });

    test('cantidad negativa', () {
      return sinRastro(venta(lineas: const [LineaVenta(varianteId: 100, cantidad: -1, precioUnitarioCentavos: 7500)]), 'cantidad');
    });

    test('precio negativo', () {
      return sinRastro(venta(lineas: const [LineaVenta(varianteId: 100, cantidad: 1, precioUnitarioCentavos: -1)]), 'precio');
    });

    test('descuento mayor que el precio', () {
      return sinRastro(
        venta(lineas: const [LineaVenta(varianteId: 100, cantidad: 1, precioUnitarioCentavos: 1000, descuentoUnitarioCentavos: 1001)]),
        'descuento',
      );
    });

    test('descuento negativo', () {
      return sinRastro(
        venta(lineas: const [LineaVenta(varianteId: 100, cantidad: 1, precioUnitarioCentavos: 1000, descuentoUnitarioCentavos: -5)]),
        'descuento',
      );
    });

    test('sin confirmar el efectivo', () => sinRastro(venta(efectivo: false), 'efectivo'));

    test('más de 100 líneas', () {
      final lineas = [for (var i = 0; i < 101; i++) const LineaVenta(varianteId: 100, cantidad: 1, precioUnitarioCentavos: 100)];
      return sinRastro(venta(lineas: lineas), '100');
    });

    test('exactamente 100 líneas sí se acepta', () async {
      final lineas = [for (var i = 0; i < 100; i++) const LineaVenta(varianteId: 100, cantidad: 1, precioUnitarioCentavos: 100)];
      await cola.registrarVenta(venta(lineas: lineas));
      expect(await contarFilas(db, 'venta_detalle'), 100);
    });

    test('id vacío o solo espacios', () async {
      await sinRastro(venta(id: ''), 'identificador');
      await sinRastro(venta(id: '   '), 'identificador');
    });

    test('la sucursal no existe', () => sinRastro(venta(sucursalId: 99), 'sucursal'));

    test('la sucursal está dada de baja', () => sinRastro(venta(sucursalId: 2), 'sucursal'));

    test('la sucursal es de otra empresa', () => sinRastro(venta(sucursalId: 11), 'sucursal'));

    test('la variante no existe', () {
      return sinRastro(venta(lineas: const [LineaVenta(varianteId: 999, cantidad: 1, precioUnitarioCentavos: 100)]), 'prendas');
    });

    test('una variante dada de baja', () async {
      await db.update('variante', {'activo': 0}, where: 'id = 101');
      await sinRastro(venta(lineas: const [LineaVenta(varianteId: 101, cantidad: 1, precioUnitarioCentavos: 100)]), 'prendas');
    });

    test('la variante activa de un producto dado de baja', () {
      return sinRastro(venta(lineas: const [LineaVenta(varianteId: 110, cantidad: 1, precioUnitarioCentavos: 100)]), 'prendas');
    });

    test('la variante es de otra empresa', () {
      return sinRastro(venta(lineas: const [LineaVenta(varianteId: 200, cantidad: 1, precioUnitarioCentavos: 100)]), 'prendas');
    });

    test('una sola variante mala entre varias buenas tumba toda la venta (rollback total)', () {
      return sinRastro(
        venta(
          lineas: const [
            LineaVenta(varianteId: 100, cantidad: 1, precioUnitarioCentavos: 100),
            LineaVenta(varianteId: 101, cantidad: 1, precioUnitarioCentavos: 100),
            LineaVenta(varianteId: 999, cantidad: 1, precioUnitarioCentavos: 100),
          ],
        ),
        'prendas',
      );
    });

    test('el cliente no existe', () => sinRastro(venta(cliente: 999), 'cliente'));

    test('el cliente solo existe en el teléfono (sin servidor_id)', () => sinRastro(venta(cliente: 2), 'servidor'));

    test('el cliente es de otra empresa', () => sinRastro(venta(cliente: 3), 'cliente'));

    test('falla el segundo detalle: se deshace todo (operación, venta y primer detalle)', () async {
      await db.execute(
        "CREATE TRIGGER falla_detalle BEFORE INSERT ON venta_detalle WHEN NEW.cantidad = 3 "
        "BEGIN SELECT RAISE(ABORT, 'falla de prueba'); END",
      );
      final antes = await huellaDeRegistro(db);
      await expectLater(
        cola.registrarVenta(
          venta(
            lineas: const [
              LineaVenta(varianteId: 100, cantidad: 1, precioUnitarioCentavos: 100),
              LineaVenta(varianteId: 101, cantidad: 3, precioUnitarioCentavos: 100),
            ],
          ),
        ),
        throwsA(isA<DatabaseException>()),
      );
      expect(await huellaDeRegistro(db), antes);
      expect(await cola.obtener('id-v1'), isNull);
    });

    test('tras un rechazo se puede registrar otra con el MISMO id ya corregida', () async {
      await expectLater(cola.registrarVenta(venta(efectivo: false)), colaError());
      await cola.registrarVenta(venta());
      expect(await contarFilas(db, 'operacion_pendiente'), 1);
    });
  });

  // =========================================================================================
  group('registrarVenta: id repetido y doble toque', () {
    test('el MISMO operacion_id dos veces no duplica y avisa', () async {
      await cola.registrarVenta(venta());
      final antes = await huellaDeRegistro(db);
      await expectLater(cola.registrarVenta(venta()), colaError('Esta operación ya estaba registrada.'));
      expect(await huellaDeRegistro(db), antes);
      expect(antes, [1, 1, 1, 0, 0, 0]);
    });

    test('el segundo intento tampoco cambia lo ya guardado', () async {
      await cola.registrarVenta(venta(cliente: 1));
      final primera = await fila('id-v1');
      await expectLater(
        cola.registrarVenta(venta(cliente: 1, lineas: const [LineaVenta(varianteId: 101, cantidad: 9, precioUnitarioCentavos: 1)])),
        colaError(),
      );
      expect(await fila('id-v1'), primera);
      expect((await db.query('venta')).single['total_centavos'], 15000);
    });

    test('dos toques simultáneos: uno se guarda y el otro recibe el aviso', () async {
      final resultados = await Future.wait([
        cola.registrarVenta(venta()).then((_) => 'ok', onError: (Object e) => e is ColaError ? 'duplicada' : 'otro'),
        cola.registrarVenta(venta()).then((_) => 'ok', onError: (Object e) => e is ColaError ? 'duplicada' : 'otro'),
      ]);
      expect(resultados.toList()..sort(), ['duplicada', 'ok']);
      expect(await contarFilas(db, 'operacion_pendiente'), 1);
      expect(await contarFilas(db, 'venta'), 1);
      expect(await contarFilas(db, 'venta_detalle'), 1);
    });

    test('cinco toques simultáneos dejan una sola operación', () async {
      final resultados = await Future.wait([
        for (var i = 0; i < 5; i++)
          cola.registrarVenta(venta()).then((_) => 1, onError: (Object e) => 0),
      ]);
      expect(resultados.reduce((a, b) => a + b), 1);
      expect(await contarFilas(db, 'operacion_pendiente'), 1);
    });

    test('el mismo id en otra letra (mayúsculas) cuenta como el mismo', () async {
      await cola.registrarVenta(venta(id: 'abc'));
      await expectLater(cola.registrarVenta(venta(id: 'ABC')), colaError('ya estaba registrada'));
    });

    test('un id usado por una venta tampoco se acepta para una reserva', () async {
      await cola.registrarVenta(venta(id: 'mismo'));
      await expectLater(cola.registrarReserva(reserva(id: 'mismo')), colaError('ya estaba registrada'));
      expect(await contarFilas(db, 'reserva'), 0);
    });

    test('ids distintos coexisten', () async {
      await cola.registrarVenta(venta(id: 'a'));
      await cola.registrarVenta(venta(id: 'b'));
      expect(await contarFilas(db, 'operacion_pendiente'), 2);
    });
  });

  // =========================================================================================
  group('registrarReserva', () {
    test('guarda la operación, la reserva y sus detalles', () async {
      await cola.registrarReserva(
        reserva(
          observacion: '  Viene con su hijo  ',
          lineas: const [LineaReserva(varianteId: 100, cantidad: 2), LineaReserva(varianteId: 101, cantidad: 1)],
        ),
      );
      final op = await fila('id-r1');
      expect(op['tipo'], 'reserva');
      expect(op['estado'], 'registrada');
      expect(op['fecha_operacion'], '2026-10-31T15:00:00Z');
      expect(op['creada_en'], '2026-10-31T12:00:00Z');

      final r = (await db.query('reserva')).single;
      expect(r['operacion_id'], 'id-r1');
      expect(r['cliente_minimo_id'], 1);
      expect(r['fecha_visita'], '2026-11-02');
      expect(r['hora_visita_desde'], '10:00');
      expect(r['hora_visita_hasta'], '11:00');
      expect(r['observacion'], 'Viene con su hijo');
      expect(r['fecha_operacion'], '2026-10-31T15:00:00Z');

      final d = await db.query('reserva_detalle', orderBy: 'id');
      expect(d.map((x) => [x['variante_id'], x['cantidad']]), [
        [100, 2],
        [101, 1],
      ]);
    });

    test('el payload exacto: el cliente va por su id del servidor', () async {
      await cola.registrarReserva(
        reserva(observacion: 'Pasa por la tarde', lineas: const [LineaReserva(varianteId: 100, cantidad: 2)]),
      );
      expect(jsonDecode((await fila('id-r1'))['payload']! as String), {
        'cliente_id': 501,
        'fecha_visita': '2026-11-02',
        'hora_visita_desde': '10:00',
        'hora_visita_hasta': '11:00',
        'observacion': 'Pasa por la tarde',
        'lineas': [
          {'variante_id': 100, 'cantidad': 2},
        ],
      });
    });

    test('el payload coincide con las tablas', () async {
      await cola.registrarReserva(
        reserva(
          observacion: 'x',
          lineas: const [LineaReserva(varianteId: 100, cantidad: 2), LineaReserva(varianteId: 101, cantidad: 1)],
        ),
      );
      final payload = jsonDecode((await fila('id-r1'))['payload']! as String) as Map;
      final r = (await db.query('reserva')).single;
      final d = await db.query('reserva_detalle', orderBy: 'id');
      expect(payload['fecha_visita'], r['fecha_visita']);
      expect(payload['hora_visita_desde'], r['hora_visita_desde']);
      expect(payload['hora_visita_hasta'], r['hora_visita_hasta']);
      expect(payload['observacion'], r['observacion']);
      expect((payload['lineas'] as List).map((l) => [(l as Map)['variante_id'], l['cantidad']]), d.map((x) => [x['variante_id'], x['cantidad']]));
    });

    test('sin observación (null, vacía o espacios): ni clave en el payload ni valor en la tabla', () async {
      var n = 0;
      for (final obs in [null, '', '    ']) {
        final id = 'r${n++}';
        await cola.registrarReserva(reserva(id: id, observacion: obs));
        expect((jsonDecode((await fila(id))['payload']! as String) as Map).containsKey('observacion'), isFalse);
      }
      final observaciones = (await db.query('reserva')).map((r) => r['observacion']);
      expect(observaciones, everyElement(isNull));
    });

    test('la observación de 300 caracteres se acepta y la de 301 no', () async {
      await cola.registrarReserva(reserva(id: 'ok', observacion: 'a' * 300));
      await expectLater(cola.registrarReserva(reserva(id: 'mal', observacion: 'a' * 301)), colaError('300'));
      expect(await cola.obtener('mal'), isNull);
    });

    test('la visita del mismo día de la operación se acepta', () async {
      await cola.registrarReserva(reserva(visita: DateTime(2026, 10, 31)));
      expect(await contarFilas(db, 'reserva'), 1);
    });

    test('la visita de un día anterior se rechaza sin dejar nada', () async {
      final antes = await huellaDeRegistro(db);
      await expectLater(cola.registrarReserva(reserva(visita: DateTime(2026, 10, 30))), colaError('fecha'));
      expect(await huellaDeRegistro(db), antes);
    });

    test('hora fin igual o anterior a la de inicio se rechaza', () async {
      final antes = await huellaDeRegistro(db);
      await expectLater(cola.registrarReserva(reserva(desde: '10:00', hasta: '10:00')), colaError('posterior'));
      await expectLater(cola.registrarReserva(reserva(desde: '11:00', hasta: '10:59')), colaError('posterior'));
      expect(await huellaDeRegistro(db), antes);
    });

    test('un minuto de diferencia basta', () async {
      await cola.registrarReserva(reserva(desde: '10:00', hasta: '10:01'));
      expect(await contarFilas(db, 'reserva'), 1);
    });

    test('formatos de hora inválidos', () async {
      final antes = await huellaDeRegistro(db);
      var n = 0;
      for (final (desde, hasta) in [
        ('9:00', '10:00'),
        ('09:00', '10:0'),
        ('25:00', '26:00'),
        ('10:60', '11:00'),
        ('', '11:00'),
        ('10:00', ''),
        ('10-00', '11:00'),
        ('10:00:00', '11:00'),
        ('abc', 'def'),
      ]) {
        await expectLater(cola.registrarReserva(reserva(id: 'h${n++}', desde: desde, hasta: hasta)), colaError('HH:mm'), reason: '$desde-$hasta');
      }
      expect(await huellaDeRegistro(db), antes);
    });

    test('los extremos del día son válidos: 00:00 a 23:59', () async {
      await cola.registrarReserva(reserva(desde: '00:00', hasta: '23:59'));
      expect(await contarFilas(db, 'reserva'), 1);
    });

    test('el cliente es OBLIGATORIO y debe tener servidor_id', () async {
      final antes = await huellaDeRegistro(db);
      await expectLater(cola.registrarReserva(reserva(cliente: 2)), colaError('servidor'));
      await expectLater(cola.registrarReserva(reserva(cliente: 999)), colaError('cliente'));
      await expectLater(cola.registrarReserva(reserva(cliente: 3)), colaError('cliente'), reason: 'de otra empresa');
      expect(await huellaDeRegistro(db), antes);
    });

    test('sin líneas, cantidad cero o más de 100 líneas', () async {
      final antes = await huellaDeRegistro(db);
      await expectLater(cola.registrarReserva(reserva(lineas: const [])), colaError('al menos una prenda'));
      await expectLater(cola.registrarReserva(reserva(lineas: const [LineaReserva(varianteId: 100, cantidad: 0)])), colaError('cantidad'));
      await expectLater(
        cola.registrarReserva(reserva(lineas: [for (var i = 0; i < 101; i++) const LineaReserva(varianteId: 100, cantidad: 1)])),
        colaError('100'),
      );
      expect(await huellaDeRegistro(db), antes);
    });

    test('sucursal o variante que no valen', () async {
      final antes = await huellaDeRegistro(db);
      await expectLater(cola.registrarReserva(reserva(sucursalId: 2)), colaError('sucursal'));
      await expectLater(cola.registrarReserva(reserva(sucursalId: 11)), colaError('sucursal'));
      await expectLater(cola.registrarReserva(reserva(lineas: const [LineaReserva(varianteId: 999, cantidad: 1)])), colaError('prendas'));
      await expectLater(cola.registrarReserva(reserva(lineas: const [LineaReserva(varianteId: 200, cantidad: 1)])), colaError('prendas'));
      expect(await huellaDeRegistro(db), antes);
    });

    test('falla un detalle: se deshace todo', () async {
      await db.execute(
        "CREATE TRIGGER falla_rd BEFORE INSERT ON reserva_detalle WHEN NEW.cantidad = 5 "
        "BEGIN SELECT RAISE(ABORT, 'falla de prueba'); END",
      );
      final antes = await huellaDeRegistro(db);
      await expectLater(
        cola.registrarReserva(
          reserva(lineas: const [LineaReserva(varianteId: 100, cantidad: 1), LineaReserva(varianteId: 101, cantidad: 5)]),
        ),
        throwsA(isA<DatabaseException>()),
      );
      expect(await huellaDeRegistro(db), antes);
    });

    test('el mismo id dos veces no duplica', () async {
      await cola.registrarReserva(reserva());
      await expectLater(cola.registrarReserva(reserva()), colaError('ya estaba registrada'));
      expect(await contarFilas(db, 'reserva'), 1);
      expect(await contarFilas(db, 'reserva_detalle'), 1);
    });

    test('doble toque simultáneo', () async {
      final r = await Future.wait([
        cola.registrarReserva(reserva()).then((_) => 1, onError: (Object e) => 0),
        cola.registrarReserva(reserva()).then((_) => 1, onError: (Object e) => 0),
      ]);
      expect(r.reduce((a, b) => a + b), 1);
      expect(await contarFilas(db, 'reserva'), 1);
    });

    test('una reserva descuenta de las existencias estimadas', () async {
      await cola.registrarReserva(reserva(lineas: const [LineaReserva(varianteId: 100, cantidad: 3)]));
      expect(await estimado(), 7);
    });
  });

  // =========================================================================================
  group('listar y obtener', () {
    setUp(() async {
      await cola.registrarVenta(venta(id: 'v-1', fecha: DateTime.utc(2026, 10, 31, 9)));
      await cola.registrarReserva(reserva(id: 'r-2', fecha: DateTime.utc(2026, 10, 31, 10)));
      await cola.registrarVenta(venta(id: 'v-3', fecha: DateTime.utc(2026, 10, 31, 11)));
      await cola.registrarVenta(venta(id: 'v-otro-usuario', usuarioId: 8, fecha: DateTime.utc(2026, 10, 31, 12)));
      await cola.registrarVenta(
        venta(
          id: 'v-otra-empresa',
          empresaId: 2,
          sucursalId: 11,
          lineas: const [LineaVenta(varianteId: 200, cantidad: 1, precioUnitarioCentavos: 100)],
          fecha: DateTime.utc(2026, 10, 31, 13),
        ),
      );
    });

    Future<List<String>> ids({
      int empresaId = 1,
      int usuarioId = 7,
      Set<EstadoOperacion>? estados,
      TipoOperacion? tipo,
      int? limite,
      int desplazamiento = 0,
    }) async {
      final filas = await cola.listar(
        empresaId: empresaId,
        usuarioId: usuarioId,
        estados: estados,
        tipo: tipo,
        limite: limite,
        desplazamiento: desplazamiento,
      );
      return filas.map((o) => o.operacionId).toList();
    }

    test('devuelve las del usuario en su empresa, la más reciente primero', () async {
      expect(await ids(), ['v-3', 'r-2', 'v-1']);
    });

    test('filtra por usuario', () async {
      expect(await ids(usuarioId: 8), ['v-otro-usuario']);
      expect(await ids(usuarioId: 99), isEmpty);
    });

    test('filtra por empresa: nunca mezcla', () async {
      expect(await ids(empresaId: 2), ['v-otra-empresa']);
      expect(await ids(empresaId: 2, usuarioId: 8), isEmpty);
      expect(await ids(empresaId: 3), isEmpty);
    });

    test('filtra por estados', () async {
      await poner('v-1', 'enviada');
      await poner('r-2', 'confirmada');
      expect(await ids(estados: {EstadoOperacion.registrada}), ['v-3']);
      expect(await ids(estados: {EstadoOperacion.enviada}), ['v-1']);
      expect(await ids(estados: {EstadoOperacion.registrada, EstadoOperacion.enviada}), ['v-3', 'v-1']);
      expect(await ids(estados: {EstadoOperacion.confirmada}), ['r-2']);
      expect(await ids(estados: {EstadoOperacion.rechazada}), isEmpty);
    });

    test('sin estados (null o conjunto vacío) devuelve todas', () async {
      expect(await ids(estados: null), hasLength(3));
      expect(await ids(estados: <EstadoOperacion>{}), hasLength(3));
    });

    test('filtra por tipo', () async {
      expect(await ids(tipo: TipoOperacion.reserva), ['r-2']);
      expect(await ids(tipo: TipoOperacion.ventaContado), ['v-3', 'v-1']);
    });

    test('estado y tipo juntos', () async {
      await poner('v-1', 'enviada');
      expect(await ids(estados: {EstadoOperacion.enviada}, tipo: TipoOperacion.ventaContado), ['v-1']);
      expect(await ids(estados: {EstadoOperacion.enviada}, tipo: TipoOperacion.reserva), isEmpty);
    });

    test('pagina con limite y desplazamiento', () async {
      expect(await ids(limite: 2), ['v-3', 'r-2']);
      expect(await ids(limite: 2, desplazamiento: 2), ['v-1']);
      expect(await ids(limite: 1, desplazamiento: 1), ['r-2']);
      expect(await ids(limite: 10, desplazamiento: 3), isEmpty);
    });

    test('desplazamiento sin límite devuelve el resto', () async {
      expect(await ids(desplazamiento: 1), ['r-2', 'v-1']);
    });

    test('límite cero o negativo devuelve vacío', () async {
      expect(await ids(limite: 0), isEmpty);
      expect(await ids(limite: -3), isEmpty);
    });

    test('un desplazamiento negativo cuenta como cero', () async {
      expect(await ids(desplazamiento: -4), ['v-3', 'r-2', 'v-1']);
    });

    test('ordena por la fecha en que OCURRIÓ, no por el orden en que se guardó', () async {
      await cola.registrarVenta(venta(id: 'v-antigua', fecha: DateTime.utc(2026, 10, 30, 8)));
      expect((await ids()).last, 'v-antigua');
    });

    test('un empate al segundo se desempata bien aunque una fecha lleve fracción', () async {
      await cola.registrarVenta(venta(id: 'v-t1', fecha: DateTime.utc(2026, 10, 31, 20, 0, 5)));
      await cola.registrarVenta(venta(id: 'v-t2', fecha: DateTime.utc(2026, 10, 31, 20, 0, 5, 500)));
      expect((await ids()).take(2), ['v-t2', 'v-t1'], reason: '20:00:05.500 es posterior a 20:00:05');
    });

    test('devuelve los datos de la fila bien leídos', () async {
      final o = (await cola.listar(empresaId: 1, usuarioId: 7, tipo: TipoOperacion.reserva)).single;
      expect(o.operacionId, 'r-2');
      expect(o.empresaId, 1);
      expect(o.sucursalId, 1);
      expect(o.usuarioId, 7);
      expect(o.tipo, TipoOperacion.reserva);
      expect(o.estado, EstadoOperacion.registrada);
      expect(o.versionContrato, 1);
      expect(o.intentos, 0);
      expect(o.fechaOperacion, DateTime.utc(2026, 10, 31, 10));
      expect(o.fechaOperacion.isUtc, isTrue);
      expect(o.creadaEn, DateTime.utc(2026, 10, 31, 12));
      expect(o.ultimoError, isNull);
      expect(o.proximoReintentoEn, isNull);
      expect(o.resueltaEn, isNull);
      expect(jsonDecode(o.payload), isA<Map>());
    });

    test('obtener devuelve la operación o null', () async {
      expect((await cola.obtener('v-1'))!.operacionId, 'v-1');
      expect(await cola.obtener('no-existe'), isNull);
      expect(await cola.obtener(''), isNull);
    });
  });

  // =========================================================================================
  group('paraEnviar', () {
    Future<List<String>> paraEnviar({int usuarioId = 7, int empresaId = 1, DateTime? ahora, bool ignorar = false, int? limite}) async {
      final filas = await cola.paraEnviar(
        empresaId: empresaId,
        usuarioId: usuarioId,
        ahora: ahora ?? reloj.ahora(),
        ignorarEspera: ignorar,
        limite: limite,
      );
      return filas.map((o) => o.operacionId).toList();
    }

    test('ordena por fecha_operacion ascendente (D14), no por el orden de registro', () async {
      await cola.registrarVenta(venta(id: 'tarde', fecha: DateTime.utc(2026, 10, 31, 15)));
      await cola.registrarVenta(venta(id: 'temprano', fecha: DateTime.utc(2026, 10, 31, 8)));
      await cola.registrarReserva(reserva(id: 'medio', fecha: DateTime.utc(2026, 10, 31, 11)));
      expect(await paraEnviar(), ['temprano', 'medio', 'tarde']);
    });

    test('incluye registrada y enviada; excluye confirmada, rechazada y en_conflicto', () async {
      await ventaEn('a-reg', 'registrada', fecha: DateTime.utc(2026, 10, 31, 1));
      await ventaEn('b-env', 'enviada', fecha: DateTime.utc(2026, 10, 31, 2));
      await ventaEn('c-con', 'confirmada', fecha: DateTime.utc(2026, 10, 31, 3));
      await ventaEn('d-rec', 'rechazada', fecha: DateTime.utc(2026, 10, 31, 4));
      await ventaEn('e-cfl', 'en_conflicto', fecha: DateTime.utc(2026, 10, 31, 5));
      expect(await paraEnviar(), ['a-reg', 'b-env']);
    });

    test('solo las del usuario y de la empresa', () async {
      await ventaEn('mia', 'registrada');
      await ventaEn('ajena', 'registrada', usuarioId: 8);
      await cola.registrarVenta(
        venta(
          id: 'otra-empresa',
          empresaId: 2,
          sucursalId: 11,
          lineas: const [LineaVenta(varianteId: 200, cantidad: 1, precioUnitarioCentavos: 1)],
        ),
      );
      expect(await paraEnviar(), ['mia']);
      expect(await paraEnviar(usuarioId: 8), ['ajena']);
      expect(await paraEnviar(empresaId: 2), ['otra-empresa']);
    });

    test('respeta la espera: si el próximo reintento no llegó, no sale', () async {
      await ventaEn('esperando', 'registrada');
      await cola.registrarFalloDeRed(['esperando'], error: 'Sin red', proximoReintento: reloj.ahora().add(const Duration(seconds: 30)));
      expect(await paraEnviar(), isEmpty);
      expect(await paraEnviar(ahora: reloj.ahora().add(const Duration(seconds: 29))), isEmpty);
    });

    test('cuando la espera se cumple (incluso justo en el límite) vuelve a salir', () async {
      await ventaEn('esperando', 'registrada');
      final hasta = reloj.ahora().add(const Duration(seconds: 30));
      await cola.registrarFalloDeRed(['esperando'], error: 'Sin red', proximoReintento: hasta);
      expect(await paraEnviar(ahora: hasta), ['esperando']);
      expect(await paraEnviar(ahora: hasta.add(const Duration(seconds: 1))), ['esperando']);
    });

    test('la espera con fracción de segundo se compara bien', () async {
      await ventaEn('esperando', 'registrada');
      final base = DateTime.utc(2026, 10, 31, 12);
      await cola.registrarFalloDeRed(['esperando'], error: 'x', proximoReintento: base.add(const Duration(milliseconds: 500)));
      expect(await paraEnviar(ahora: base), isEmpty, reason: '12:00:00 es antes que 12:00:00.500');
      expect(await paraEnviar(ahora: base.add(const Duration(milliseconds: 600))), ['esperando']);
    });

    test('ignorarEspera las trae aunque falte tiempo', () async {
      await ventaEn('esperando', 'registrada');
      await cola.registrarFalloDeRed(['esperando'], error: 'x', proximoReintento: reloj.ahora().add(const Duration(minutes: 5)));
      expect(await paraEnviar(), isEmpty);
      expect(await paraEnviar(ignorar: true), ['esperando']);
    });

    test('una enviada que quedó con espera también respeta el reintento', () async {
      await ventaEn('env', 'enviada');
      await cola.registrarFalloDeRed(['env'], error: 'x', proximoReintento: reloj.ahora().add(const Duration(minutes: 1)));
      expect(await paraEnviar(), isEmpty);
    });

    test('limite recorta después de ordenar', () async {
      await cola.registrarVenta(venta(id: 'c', fecha: DateTime.utc(2026, 10, 31, 3)));
      await cola.registrarVenta(venta(id: 'a', fecha: DateTime.utc(2026, 10, 31, 1)));
      await cola.registrarVenta(venta(id: 'b', fecha: DateTime.utc(2026, 10, 31, 2)));
      expect(await paraEnviar(limite: 2), ['a', 'b']);
      expect(await paraEnviar(limite: 0), isEmpty);
    });

    test('las que esperan no ocupan lugar en el límite', () async {
      await cola.registrarVenta(venta(id: 'a', fecha: DateTime.utc(2026, 10, 31, 1)));
      await cola.registrarVenta(venta(id: 'b', fecha: DateTime.utc(2026, 10, 31, 2)));
      await cola.registrarFalloDeRed(['a'], error: 'x', proximoReintento: reloj.ahora().add(const Duration(minutes: 1)));
      expect(await paraEnviar(limite: 1), ['b']);
    });

    test('sin operaciones devuelve vacío', () async {
      expect(await paraEnviar(), isEmpty);
    });
  });

  group('paraRevisarConflictos', () {
    test('solo las en_conflicto del usuario y la empresa, por fecha ascendente', () async {
      await ventaEn('c2', 'en_conflicto', fecha: DateTime.utc(2026, 10, 31, 6));
      await ventaEn('c1', 'en_conflicto', fecha: DateTime.utc(2026, 10, 31, 5));
      await ventaEn('otra', 'en_conflicto', usuarioId: 8);
      await ventaEn('normal', 'registrada');
      final ids = (await cola.paraRevisarConflictos(empresaId: 1, usuarioId: 7)).map((o) => o.operacionId);
      expect(ids, ['c1', 'c2']);
      expect(await cola.paraRevisarConflictos(empresaId: 2, usuarioId: 7), isEmpty);
    });
  });

  // =========================================================================================
  group('marcarEnviadas', () {
    test('registrada → enviada con un intento más', () async {
      await ventaEn('a', 'registrada');
      await cola.marcarEnviadas(['a']);
      final o = (await cola.obtener('a'))!;
      expect(o.estado, EstadoOperacion.enviada);
      expect(o.intentos, 1);
    });

    test('una enviada que se reenvía suma otro intento', () async {
      await ventaEn('a', 'registrada');
      await cola.marcarEnviadas(['a']);
      await cola.marcarEnviadas(['a']);
      final o = (await cola.obtener('a'))!;
      expect(o.estado, EstadoOperacion.enviada);
      expect(o.intentos, 2);
    });

    test('borra la espera del reintento', () async {
      await ventaEn('a', 'registrada');
      await cola.registrarFalloDeRed(['a'], error: 'x', proximoReintento: reloj.ahora().add(const Duration(minutes: 1)));
      await cola.marcarEnviadas(['a']);
      expect((await cola.obtener('a'))!.proximoReintentoEn, isNull);
    });

    test('conserva el último error (lo reemplaza la respuesta del servidor)', () async {
      await ventaEn('a', 'registrada');
      await cola.registrarFalloDeRed(['a'], error: 'Sin red', proximoReintento: reloj.ahora());
      await cola.marcarEnviadas(['a']);
      expect((await cola.obtener('a'))!.ultimoError, 'Sin red');
    });

    test('varias a la vez, en una transacción', () async {
      await ventaEn('a', 'registrada');
      await ventaEn('b', 'registrada');
      await ventaEn('c', 'registrada');
      await cola.marcarEnviadas(['a', 'c']);
      expect((await cola.obtener('a'))!.estado, EstadoOperacion.enviada);
      expect((await cola.obtener('b'))!.estado, EstadoOperacion.registrada);
      expect((await cola.obtener('c'))!.estado, EstadoOperacion.enviada);
    });

    test('ignora las que no pueden: finales, en conflicto e ids que no existen', () async {
      await ventaEn('con', 'confirmada', intentos: 1);
      await ventaEn('rec', 'rechazada', intentos: 1);
      await ventaEn('cfl', 'en_conflicto', intentos: 1);
      await cola.marcarEnviadas(['con', 'rec', 'cfl', 'fantasma']);
      for (final (id, estado) in [
        ('con', EstadoOperacion.confirmada),
        ('rec', EstadoOperacion.rechazada),
        ('cfl', EstadoOperacion.enConflicto),
      ]) {
        final o = (await cola.obtener(id))!;
        expect(o.estado, estado, reason: id);
        expect(o.intentos, 1, reason: id);
      }
    });

    test('una lista vacía no hace nada ni emite', () async {
      var n = 0;
      final sub = cola.cambios.listen((_) => n++);
      await cola.marcarEnviadas([]);
      await pumpEventQueue();
      expect(n, 0);
      await sub.cancel();
    });

    test('el id en mayúsculas también la encuentra', () async {
      await ventaEn('abc', 'registrada');
      await cola.marcarEnviadas(['ABC']);
      expect((await cola.obtener('abc'))!.estado, EstadoOperacion.enviada);
    });

    test('un id repetido en la lista suma UN intento', () async {
      await ventaEn('a', 'registrada');
      await cola.marcarEnviadas(['a', 'a']);
      expect((await cola.obtener('a'))!.intentos, 1);
    });

    test('muchas operaciones a la vez', () async {
      final ids = [for (var i = 0; i < 40; i++) 'op-$i'];
      for (final id in ids) {
        await cola.registrarVenta(venta(id: id));
      }
      await cola.marcarEnviadas(ids);
      final conteo = await cola.conteoPorEstado(empresaId: 1, usuarioId: 7);
      expect(conteo[EstadoOperacion.enviada], 40);
    });
  });

  group('volverARegistrada', () {
    test('enviada → registrada guardando el error y la espera, sin gastar ni devolver intentos', () async {
      await ventaEn('a', 'registrada');
      await cola.marcarEnviadas(['a']);
      final espera = reloj.ahora().add(const Duration(seconds: 10));
      await cola.volverARegistrada(['a'], error: 'Sin conexión', proximoReintento: espera);
      final o = (await cola.obtener('a'))!;
      expect(o.estado, EstadoOperacion.registrada);
      expect(o.intentos, 1);
      expect(o.ultimoError, 'Sin conexión');
      expect(o.proximoReintentoEn, espera);
    });

    test('con devolverIntento resta uno', () async {
      await ventaEn('a', 'registrada');
      await cola.marcarEnviadas(['a']);
      await cola.marcarEnviadas(['a']);
      await cola.volverARegistrada(['a'], error: 'Plan', devolverIntento: true);
      final o = (await cola.obtener('a'))!;
      expect(o.estado, EstadoOperacion.registrada);
      expect(o.intentos, 1);
    });

    test('devolverIntento nunca baja de cero', () async {
      await ventaEn('a', 'enviada', intentos: 0);
      await cola.volverARegistrada(['a'], devolverIntento: true);
      expect((await cola.obtener('a'))!.intentos, 0);
    });

    test('solo actúa sobre las enviadas: una registrada no cambia ni anota el error', () async {
      await ventaEn('a', 'registrada');
      await cola.volverARegistrada(['a'], error: 'no debería quedar');
      final o = (await cola.obtener('a'))!;
      expect(o.estado, EstadoOperacion.registrada);
      expect(o.ultimoError, isNull);
    });

    test('las finales y en conflicto no vuelven atrás', () async {
      await ventaEn('con', 'confirmada');
      await ventaEn('rec', 'rechazada');
      await ventaEn('cfl', 'en_conflicto');
      await cola.volverARegistrada(['con', 'rec', 'cfl'], error: 'x');
      expect((await cola.obtener('con'))!.estado, EstadoOperacion.confirmada);
      expect((await cola.obtener('rec'))!.estado, EstadoOperacion.rechazada);
      expect((await cola.obtener('cfl'))!.estado, EstadoOperacion.enConflicto);
    });

    test('sin espera la deja lista para enviar de inmediato', () async {
      await ventaEn('a', 'enviada');
      await cola.volverARegistrada(['a'], error: 'x');
      final listas = await cola.paraEnviar(empresaId: 1, usuarioId: 7, ahora: reloj.ahora());
      expect(listas.map((o) => o.operacionId), ['a']);
    });

    test('vuelve a salir después de la espera', () async {
      await ventaEn('a', 'enviada');
      await cola.volverARegistrada(['a'], proximoReintento: reloj.ahora().add(const Duration(seconds: 10)));
      expect(await cola.paraEnviar(empresaId: 1, usuarioId: 7, ahora: reloj.ahora()), isEmpty);
      expect(await cola.paraEnviar(empresaId: 1, usuarioId: 7, ahora: reloj.ahora().add(const Duration(seconds: 11))), hasLength(1));
    });
  });

  group('registrarFalloDeRed', () {
    test('NO cambia el estado: una enviada que pudo llegar sigue enviada', () async {
      await ventaEn('a', 'registrada');
      await cola.marcarEnviadas(['a']);
      final espera = reloj.ahora().add(const Duration(seconds: 20));
      await cola.registrarFalloDeRed(['a'], error: 'Se cortó la conexión', proximoReintento: espera);
      final o = (await cola.obtener('a'))!;
      expect(o.estado, EstadoOperacion.enviada);
      expect(o.intentos, 1);
      expect(o.ultimoError, 'Se cortó la conexión');
      expect(o.proximoReintentoEn, espera);
    });

    test('una registrada tampoco cambia de estado', () async {
      await ventaEn('a', 'registrada');
      await cola.registrarFalloDeRed(['a'], error: 'x', proximoReintento: reloj.ahora());
      final o = (await cola.obtener('a'))!;
      expect(o.estado, EstadoOperacion.registrada);
      expect(o.intentos, 0);
    });

    test('no toca las finales ni las en conflicto', () async {
      await ventaEn('con', 'confirmada');
      await ventaEn('cfl', 'en_conflicto');
      await cola.registrarFalloDeRed(['con', 'cfl'], error: 'x', proximoReintento: reloj.ahora());
      expect((await cola.obtener('con'))!.ultimoError, isNull);
      expect((await cola.obtener('cfl'))!.ultimoError, isNull);
    });

    test('varias a la vez', () async {
      await ventaEn('a', 'registrada');
      await ventaEn('b', 'enviada');
      await cola.registrarFalloDeRed(['a', 'b'], error: 'x', proximoReintento: reloj.ahora());
      expect((await cola.obtener('a'))!.ultimoError, 'x');
      expect((await cola.obtener('b'))!.ultimoError, 'x');
    });

    test('un nuevo fallo reemplaza el error y la espera anteriores', () async {
      await ventaEn('a', 'registrada');
      await cola.registrarFalloDeRed(['a'], error: 'uno', proximoReintento: reloj.ahora());
      final espera = reloj.ahora().add(const Duration(minutes: 5));
      await cola.registrarFalloDeRed(['a'], error: 'dos', proximoReintento: espera);
      final o = (await cola.obtener('a'))!;
      expect(o.ultimoError, 'dos');
      expect(o.proximoReintentoEn, espera);
    });
  });

  // =========================================================================================
  group('aplicarResultados: transiciones', () {
    final servidor = DateTime.utc(2026, 10, 31, 15, 30);
    final recibido = DateTime.utc(2026, 10, 31, 12, 5);

    Future<List<String>> aplicar(List<ResultadoOperacionSync> r) => cola.aplicarResultados(r, recibidoEn: recibido);

    test('enviada → confirmada: estado, hora del SERVIDOR, sin error y una fila en resultado_sync', () async {
      await ventaEn('a', 'enviada');
      await poner('a', 'enviada', resuelta: null);
      await cola.registrarFalloDeRed(['a'], error: 'Sin red', proximoReintento: reloj.ahora());
      final cambiaron = await aplicar([
        resultadoDe(
          'a',
          EstadoResultadoSync.confirmada,
          procesadaEn: servidor,
          recurso: const RecursoSync(tipo: 'venta', id: 77, codigo: 'V-77', totalCentavos: 15000),
        ),
      ]);
      expect(cambiaron, ['a']);
      final o = (await cola.obtener('a'))!;
      expect(o.estado, EstadoOperacion.confirmada);
      expect(o.resueltaEn, servidor, reason: 'la hora del servidor, no la del teléfono');
      expect(o.ultimoError, isNull);
      expect(o.proximoReintentoEn, isNull);

      final r = await cola.resultados('a');
      expect(r, hasLength(1));
      expect(r.single.estadoResultado, 'confirmada');
      expect(r.single.recibidoEn, recibido);
      expect(r.single.entidadServidorId, 77);
      expect(r.single.codigoMotivo, isNull);
    });

    test('enviada → rechazada: guarda el código del motivo, el mensaje y lo deja como último error', () async {
      await ventaEn('a', 'enviada');
      final cambiaron = await aplicar([
        resultadoDe(
          'a',
          EstadoResultadoSync.rechazada,
          motivo: 'variante_inactiva',
          mensaje: 'La variante 3 está dada de baja',
          procesadaEn: servidor,
        ),
      ]);
      expect(cambiaron, ['a']);
      final o = (await cola.obtener('a'))!;
      expect(o.estado, EstadoOperacion.rechazada);
      expect(o.ultimoError, 'La variante 3 está dada de baja');
      expect(o.resueltaEn, servidor);
      final r = (await cola.resultados('a')).single;
      expect(r.estadoResultado, 'rechazada');
      expect(r.codigoMotivo, 'variante_inactiva');
      expect(r.motivo, 'La variante 3 está dada de baja');
    });

    test('sin mensaje, el último error es el código del motivo', () async {
      await ventaEn('a', 'enviada');
      await aplicar([resultadoDe('a', EstadoResultadoSync.rechazada, motivo: 'fecha_futura', procesadaEn: servidor)]);
      expect((await cola.obtener('a'))!.ultimoError, 'fecha_futura');
    });

    test('enviada → en_conflicto: sin resolución todavía, con los faltantes en el detalle', () async {
      await ventaEn('a', 'enviada');
      final cambiaron = await aplicar([
        resultadoDe(
          'a',
          EstadoResultadoSync.enConflicto,
          motivo: 'stock_insuficiente',
          mensaje: 'Falta stock',
          procesadaEn: servidor,
          faltantes: const [FaltanteSync(varianteId: 100, solicitado: 2, disponible: 1)],
        ),
      ]);
      expect(cambiaron, ['a']);
      final o = (await cola.obtener('a'))!;
      expect(o.estado, EstadoOperacion.enConflicto);
      expect(o.resueltaEn, isNull, reason: 'aún nadie la resolvió');
      expect(o.ultimoError, 'Falta stock');
      final detalle = jsonDecode((await cola.resultados('a')).single.detalleJson!) as Map;
      expect(detalle['faltantes'], [
        {'variante_id': 100, 'solicitado': 2, 'disponible': 1},
      ]);
    });

    test('en_conflicto → confirmada (un encargado la aprobó) con la resolución en el detalle', () async {
      await ventaEn('a', 'enviada');
      await aplicar([resultadoDe('a', EstadoResultadoSync.enConflicto, motivo: 'stock_insuficiente')]);
      final cambiaron = await cola.aplicarResultados([
        resultadoDe(
          'a',
          EstadoResultadoSync.confirmada,
          procesadaEn: servidor,
          resolucion: const ResolucionSync(accion: 'forzar', motivo: 'Ya se la llevó'),
        ),
      ], recibidoEn: recibido.add(const Duration(hours: 1)));
      expect(cambiaron, ['a']);
      final o = (await cola.obtener('a'))!;
      expect(o.estado, EstadoOperacion.confirmada);
      expect(o.resueltaEn, servidor);
      expect(o.ultimoError, isNull);
      final rs = await cola.resultados('a');
      expect(rs.map((r) => r.estadoResultado), ['en_conflicto', 'confirmada']);
      final detalle = jsonDecode(rs.last.detalleJson!) as Map;
      expect(detalle['resolucion'], {'accion': 'forzar', 'motivo': 'Ya se la llevó'});
    });

    test('en_conflicto → rechazada (un encargado la rechazó)', () async {
      await ventaEn('a', 'enviada');
      await aplicar([resultadoDe('a', EstadoResultadoSync.enConflicto, motivo: 'stock_insuficiente')]);
      await aplicar([
        resultadoDe(
          'a',
          EstadoResultadoSync.rechazada,
          motivo: 'rechazada_por_encargado',
          mensaje: 'Sin stock',
          procesadaEn: servidor,
          resolucion: const ResolucionSync(accion: 'rechazar', motivo: 'Sin stock'),
        ),
      ]);
      final o = (await cola.obtener('a'))!;
      expect(o.estado, EstadoOperacion.rechazada);
      expect(o.ultimoError, 'Sin stock');
      expect(o.resueltaEn, servidor);
    });

    test('registrada → confirmada NO es una transición válida: se ignora', () async {
      await ventaEn('a', 'registrada');
      final cambiaron = await aplicar([resultadoDe('a', EstadoResultadoSync.confirmada, procesadaEn: servidor)]);
      expect(cambiaron, isEmpty);
      expect((await cola.obtener('a'))!.estado, EstadoOperacion.registrada);
      expect(await cola.resultados('a'), isEmpty);
    });

    test('una operación FINAL no retrocede ni cambia de lado', () async {
      await ventaEn('con', 'enviada');
      await aplicar([resultadoDe('con', EstadoResultadoSync.confirmada, procesadaEn: servidor)]);
      await ventaEn('rec', 'enviada');
      await aplicar([resultadoDe('rec', EstadoResultadoSync.rechazada, motivo: 'fecha_futura', procesadaEn: servidor)]);

      final contradicciones = [
        resultadoDe('con', EstadoResultadoSync.rechazada, motivo: 'x', procesadaEn: servidor.add(const Duration(hours: 1))),
        resultadoDe('con', EstadoResultadoSync.enConflicto, procesadaEn: servidor.add(const Duration(hours: 1))),
        resultadoDe('rec', EstadoResultadoSync.confirmada, procesadaEn: servidor.add(const Duration(hours: 1))),
        resultadoDe('rec', EstadoResultadoSync.enConflicto, procesadaEn: servidor.add(const Duration(hours: 1))),
      ];
      expect(await aplicar(contradicciones), isEmpty);

      final con = (await cola.obtener('con'))!;
      expect(con.estado, EstadoOperacion.confirmada);
      expect(con.resueltaEn, servidor, reason: 'la hora original no se pisa');
      expect(con.ultimoError, isNull);
      final rec = (await cola.obtener('rec'))!;
      expect(rec.estado, EstadoOperacion.rechazada);
      expect(rec.ultimoError, 'fecha_futura');
      expect(await cola.resultados('con'), hasLength(1));
      expect(await cola.resultados('rec'), hasLength(1));
    });

    test('repetir la MISMA respuesta final (duplicada) no cambia nada ni agrega filas', () async {
      await ventaEn('a', 'enviada');
      await aplicar([resultadoDe('a', EstadoResultadoSync.confirmada, procesadaEn: servidor)]);
      final cambiaron = await aplicar([resultadoDe('a', EstadoResultadoSync.confirmada, duplicada: true, procesadaEn: servidor)]);
      expect(cambiaron, isEmpty);
      expect(await cola.resultados('a'), hasLength(1));
    });

    test('en_conflicto repetido (se vuelve a consultar) no llena el historial', () async {
      await ventaEn('a', 'enviada');
      await aplicar([resultadoDe('a', EstadoResultadoSync.enConflicto, motivo: 'stock_insuficiente')]);
      await aplicar([resultadoDe('a', EstadoResultadoSync.enConflicto, motivo: 'stock_insuficiente')]);
      await aplicar([resultadoDe('a', EstadoResultadoSync.enConflicto, motivo: 'stock_insuficiente')]);
      expect(await cola.resultados('a'), hasLength(1));
    });

    test('un reenvío duplicado de una enviada se aplica igual (duplicada=true la deja confirmada)', () async {
      await ventaEn('a', 'enviada');
      final cambiaron = await aplicar([resultadoDe('a', EstadoResultadoSync.confirmada, duplicada: true, procesadaEn: servidor)]);
      expect(cambiaron, ['a']);
      final detalle = jsonDecode((await cola.resultados('a')).single.detalleJson!) as Map;
      expect(detalle['duplicada'], isTrue);
    });

    test('error_temporal NO cambia el estado: anota el error y no guarda respuesta', () async {
      await ventaEn('a', 'enviada', intentos: 1);
      final cambiaron = await aplicar([
        resultadoDe('a', EstadoResultadoSync.errorTemporal, motivo: 'error_interno', mensaje: 'Reintenta más tarde'),
      ]);
      expect(cambiaron, isEmpty);
      final o = (await cola.obtener('a'))!;
      expect(o.estado, EstadoOperacion.enviada);
      expect(o.intentos, 1);
      expect(o.ultimoError, 'Reintenta más tarde');
      expect(await cola.resultados('a'), isEmpty);
    });

    test('error_temporal sin texto anota un error genérico', () async {
      await ventaEn('a', 'enviada');
      await aplicar([resultadoDe('a', EstadoResultadoSync.errorTemporal)]);
      expect((await cola.obtener('a'))!.ultimoError, isNotEmpty);
    });

    test('un estado desconocido tampoco cambia el estado', () async {
      await ventaEn('a', 'enviada');
      final cambiaron = await aplicar([resultadoDe('a', EstadoResultadoSync.desconocido, mensaje: 'algo raro')]);
      expect(cambiaron, isEmpty);
      final o = (await cola.obtener('a'))!;
      expect(o.estado, EstadoOperacion.enviada);
      expect(o.ultimoError, 'algo raro');
    });

    test('error_temporal sobre una operación final no la toca', () async {
      await ventaEn('a', 'enviada');
      await aplicar([resultadoDe('a', EstadoResultadoSync.confirmada, procesadaEn: servidor)]);
      await aplicar([resultadoDe('a', EstadoResultadoSync.errorTemporal, mensaje: 'Reintenta')]);
      final o = (await cola.obtener('a'))!;
      expect(o.estado, EstadoOperacion.confirmada);
      expect(o.ultimoError, isNull);
    });

    test('sin procesada_en la hora de resolución es la de recepción', () async {
      await ventaEn('a', 'enviada');
      await aplicar([resultadoDe('a', EstadoResultadoSync.confirmada)]);
      expect((await cola.obtener('a'))!.resueltaEn, recibido);
    });

    test('el id del servidor en mayúsculas encuentra la operación', () async {
      await ventaEn('abc-def', 'enviada');
      final cambiaron = await aplicar([resultadoDe('ABC-DEF', EstadoResultadoSync.confirmada, procesadaEn: servidor)]);
      expect(cambiaron, ['abc-def']);
    });

    test('un id que no existe aquí se salta y las demás se aplican', () async {
      await ventaEn('a', 'enviada');
      await ventaEn('b', 'enviada');
      final cambiaron = await aplicar([
        resultadoDe('a', EstadoResultadoSync.confirmada, procesadaEn: servidor),
        resultadoDe('fantasma', EstadoResultadoSync.confirmada, procesadaEn: servidor),
        resultadoDe('', EstadoResultadoSync.confirmada),
        resultadoDe('b', EstadoResultadoSync.rechazada, motivo: 'fecha_futura', procesadaEn: servidor),
      ]);
      expect(cambiaron, ['a', 'b']);
    });

    test('devuelve solo los ids que cambiaron de estado', () async {
      await ventaEn('a', 'enviada');
      await ventaEn('b', 'enviada');
      await ventaEn('c', 'registrada');
      final cambiaron = await aplicar([
        resultadoDe('a', EstadoResultadoSync.confirmada, procesadaEn: servidor),
        resultadoDe('b', EstadoResultadoSync.errorTemporal),
        resultadoDe('c', EstadoResultadoSync.confirmada),
      ]);
      expect(cambiaron, ['a']);
    });

    test('una lista vacía no hace nada', () async {
      expect(await aplicar([]), isEmpty);
    });

    test('el mismo id dos veces en la misma llamada: la segunda ve el estado ya cambiado', () async {
      await ventaEn('a', 'enviada');
      final cambiaron = await aplicar([
        resultadoDe('a', EstadoResultadoSync.enConflicto, motivo: 'stock_insuficiente'),
        resultadoDe('a', EstadoResultadoSync.confirmada, procesadaEn: servidor),
      ]);
      expect(cambiaron, ['a', 'a']);
      expect((await cola.obtener('a'))!.estado, EstadoOperacion.confirmada);
      expect(await cola.resultados('a'), hasLength(2));
    });

    test('es una sola transacción: si una respuesta falla al guardarse, no se aplica NINGUNA', () async {
      await ventaEn('a', 'enviada');
      await ventaEn('b', 'enviada');
      await db.execute(
        "CREATE TRIGGER falla_rechazo BEFORE INSERT ON resultado_sync WHEN NEW.estado_resultado = 'rechazada' "
        "BEGIN SELECT RAISE(ABORT, 'falla de prueba'); END",
      );
      await expectLater(
        aplicar([
          resultadoDe('a', EstadoResultadoSync.confirmada, procesadaEn: servidor),
          resultadoDe('b', EstadoResultadoSync.rechazada, motivo: 'fecha_futura', procesadaEn: servidor),
        ]),
        throwsA(isA<DatabaseException>()),
      );
      expect((await cola.obtener('a'))!.estado, EstadoOperacion.enviada);
      expect((await cola.obtener('b'))!.estado, EstadoOperacion.enviada);
      expect(await contarFilas(db, 'resultado_sync'), 0);
    });
  });

  group('aplicarResultados: detalle_json y resultados()', () {
    final servidor = DateTime.utc(2026, 10, 31, 15, 30);

    test('guarda recurso, cambio y avisos en centavos', () async {
      await ventaEn('a', 'enviada');
      await cola.aplicarResultados([
        resultadoDe(
          'a',
          EstadoResultadoSync.confirmada,
          procesadaEn: servidor,
          recurso: const RecursoSync(tipo: 'venta', id: 77, codigo: 'V-000077', totalCentavos: 19500),
          cambioCentavos: 550,
          avisos: const [AvisoPrecioSync(varianteId: 100, precioOperacionCentavos: 7500, precioActualCentavos: 8000)],
        ),
      ], recibidoEn: servidor);
      final r = (await cola.resultados('a')).single;
      expect(r.entidadServidorId, 77);
      expect(jsonDecode(r.detalleJson!), {
        'recurso': {'tipo': 'venta', 'id': 77, 'codigo': 'V-000077', 'total_centavos': 19500},
        'cambio_centavos': 550,
        'avisos': [
          {'variante_id': 100, 'precio_operacion_centavos': 7500, 'precio_actual_centavos': 8000},
        ],
      });
    });

    test('una reserva confirmada guarda su recurso sin total', () async {
      await cola.registrarReserva(reserva(id: 'r'));
      await poner('r', 'enviada');
      await cola.aplicarResultados([
        resultadoDe(
          'r',
          EstadoResultadoSync.confirmada,
          procesadaEn: servidor,
          recurso: const RecursoSync(tipo: 'reserva', id: 5, codigo: 'R-5'),
        ),
      ], recibidoEn: servidor);
      final detalle = jsonDecode((await cola.resultados('r')).single.detalleJson!) as Map;
      expect(detalle['recurso'], {'tipo': 'reserva', 'id': 5, 'codigo': 'R-5'});
    });

    test('sin nada que detallar, detalle_json es NULL', () async {
      await ventaEn('a', 'enviada');
      await cola.aplicarResultados([resultadoDe('a', EstadoResultadoSync.rechazada, motivo: 'fecha_futura')], recibidoEn: servidor);
      final r = (await cola.resultados('a')).single;
      expect(r.detalleJson, isNull);
      expect(r.entidadServidorId, isNull);
    });

    test('resultados() devuelve las respuestas de la más antigua a la más nueva', () async {
      await ventaEn('a', 'enviada');
      await cola.aplicarResultados([resultadoDe('a', EstadoResultadoSync.enConflicto, motivo: 'stock_insuficiente')], recibidoEn: DateTime.utc(2026, 10, 31, 10));
      await cola.aplicarResultados([resultadoDe('a', EstadoResultadoSync.confirmada, procesadaEn: servidor)], recibidoEn: DateTime.utc(2026, 10, 31, 16));
      final rs = await cola.resultados('a');
      expect(rs.map((r) => r.estadoResultado), ['en_conflicto', 'confirmada']);
      expect(rs.map((r) => r.recibidoEn), [DateTime.utc(2026, 10, 31, 10), DateTime.utc(2026, 10, 31, 16)]);
      expect(rs.first.operacionId, 'a');
    });

    test('resultados de una operación sin respuestas o inexistente: vacío', () async {
      await ventaEn('a', 'registrada');
      expect(await cola.resultados('a'), isEmpty);
      expect(await cola.resultados('fantasma'), isEmpty);
    });

    test('las respuestas de una operación no aparecen en otra', () async {
      await ventaEn('a', 'enviada');
      await ventaEn('b', 'enviada');
      await cola.aplicarResultados([resultadoDe('a', EstadoResultadoSync.confirmada, procesadaEn: servidor)], recibidoEn: servidor);
      expect(await cola.resultados('b'), isEmpty);
    });
  });

  // =========================================================================================
  group('marcarRechazadaLocal', () {
    final recibido = DateTime.utc(2026, 10, 31, 13);

    test('registrada → rechazada con una fila "rechazo_local"', () async {
      await ventaEn('a', 'registrada');
      await cola.marcarRechazadaLocal('a', motivo: 'El servidor no acepta los datos (HTTP 422).', recibidoEn: recibido);
      final o = (await cola.obtener('a'))!;
      expect(o.estado, EstadoOperacion.rechazada);
      expect(o.ultimoError, 'El servidor no acepta los datos (HTTP 422).');
      expect(o.proximoReintentoEn, isNull);
      final r = (await cola.resultados('a')).single;
      expect(r.codigoMotivo, 'rechazo_local');
      expect(r.estadoResultado, 'rechazada');
      expect(r.motivo, 'El servidor no acepta los datos (HTTP 422).');
      expect(r.recibidoEn, recibido);
      expect(r.entidadServidorId, isNull);
      expect(r.detalleJson, isNull);
    });

    test('también desde enviada, y deja de ofrecerse para enviar', () async {
      await ventaEn('a', 'enviada');
      await cola.marcarRechazadaLocal('a', motivo: 'x', recibidoEn: recibido);
      expect((await cola.obtener('a'))!.estado, EstadoOperacion.rechazada);
      expect(await cola.paraEnviar(empresaId: 1, usuarioId: 7, ahora: reloj.ahora()), isEmpty);
    });

    test('no la rechaza si ya es final o está en conflicto', () async {
      await ventaEn('con', 'confirmada');
      await ventaEn('rec', 'rechazada');
      await ventaEn('cfl', 'en_conflicto');
      for (final id in ['con', 'rec', 'cfl']) {
        await cola.marcarRechazadaLocal(id, motivo: 'x', recibidoEn: recibido);
      }
      expect((await cola.obtener('con'))!.estado, EstadoOperacion.confirmada);
      expect((await cola.obtener('rec'))!.estado, EstadoOperacion.rechazada);
      expect((await cola.obtener('cfl'))!.estado, EstadoOperacion.enConflicto);
      expect(await contarFilas(db, 'resultado_sync'), 0);
    });

    test('un id que no existe no hace nada ni falla', () async {
      await cola.marcarRechazadaLocal('fantasma', motivo: 'x', recibidoEn: recibido);
      expect(await contarFilas(db, 'resultado_sync'), 0);
    });

    test('repetirlo no agrega otra fila', () async {
      await ventaEn('a', 'registrada');
      await cola.marcarRechazadaLocal('a', motivo: 'x', recibidoEn: recibido);
      await cola.marcarRechazadaLocal('a', motivo: 'x', recibidoEn: recibido);
      expect(await cola.resultados('a'), hasLength(1));
    });

    test('libera las existencias que la operación tenía apartadas', () async {
      await cola.registrarVenta(venta(id: 'a'));
      expect(await estimado(), 8);
      await cola.marcarRechazadaLocal('a', motivo: 'x', recibidoEn: recibido);
      expect(await estimado(), 10);
    });
  });

  // =========================================================================================
  group('conteoPorEstado', () {
    test('sin operaciones devuelve todos los estados en 0', () async {
      final c = await cola.conteoPorEstado(empresaId: 1, usuarioId: 7);
      expect(c.keys.toSet(), EstadoOperacion.values.toSet());
      expect(c.values.every((n) => n == 0), isTrue);
    });

    test('cuenta cada estado', () async {
      await ventaEn('a', 'registrada');
      await ventaEn('b', 'registrada');
      await ventaEn('c', 'enviada');
      await ventaEn('d', 'confirmada');
      await ventaEn('e', 'confirmada');
      await ventaEn('f', 'confirmada');
      await ventaEn('g', 'rechazada');
      await ventaEn('h', 'en_conflicto');
      final c = await cola.conteoPorEstado(empresaId: 1, usuarioId: 7);
      expect(c[EstadoOperacion.registrada], 2);
      expect(c[EstadoOperacion.enviada], 1);
      expect(c[EstadoOperacion.confirmada], 3);
      expect(c[EstadoOperacion.rechazada], 1);
      expect(c[EstadoOperacion.enConflicto], 1);
    });

    test('separa por usuario y por empresa', () async {
      await ventaEn('mia', 'registrada');
      await ventaEn('ajena', 'registrada', usuarioId: 8);
      await cola.registrarVenta(
        venta(
          id: 'otra-empresa',
          empresaId: 2,
          sucursalId: 11,
          lineas: const [LineaVenta(varianteId: 200, cantidad: 1, precioUnitarioCentavos: 1)],
        ),
      );
      expect((await cola.conteoPorEstado(empresaId: 1, usuarioId: 7))[EstadoOperacion.registrada], 1);
      expect((await cola.conteoPorEstado(empresaId: 1, usuarioId: 8))[EstadoOperacion.registrada], 1);
      expect((await cola.conteoPorEstado(empresaId: 2, usuarioId: 7))[EstadoOperacion.registrada], 1);
      expect((await cola.conteoPorEstado(empresaId: 2, usuarioId: 8))[EstadoOperacion.registrada], 0);
    });

    test('incluye ventas y reservas', () async {
      await cola.registrarVenta(venta(id: 'v'));
      await cola.registrarReserva(reserva(id: 'r'));
      expect((await cola.conteoPorEstado(empresaId: 1, usuarioId: 7))[EstadoOperacion.registrada], 2);
    });
  });

  // =========================================================================================
  group('la vista v_stock_local con las operaciones de la cola', () {
    // stock_conocido: variante 100 en la sucursal 1 = 10, generado a las 10:00 del 31/10 (hora del servidor).
    final servidorDespues = DateTime.utc(2026, 10, 31, 11);
    final servidorAntes = DateTime.utc(2026, 10, 31, 9);

    test('una registrada resta', () async {
      await cola.registrarVenta(venta(lineas: const [LineaVenta(varianteId: 100, cantidad: 3, precioUnitarioCentavos: 100)]));
      expect(await estimado(), 7);
    });

    test('una enviada resta (no sabemos si el servidor la aplicó)', () async {
      await cola.registrarVenta(venta());
      await cola.marcarEnviadas(['id-v1']);
      expect(await estimado(), 8);
    });

    test('una rechazada NO resta', () async {
      await cola.registrarVenta(venta());
      await cola.marcarEnviadas(['id-v1']);
      await cola.aplicarResultados([resultadoDe('id-v1', EstadoResultadoSync.rechazada, motivo: 'fecha_futura', procesadaEn: servidorDespues)], recibidoEn: servidorDespues);
      expect(await estimado(), 10);
    });

    test('una en_conflicto NO resta (el servidor no la aplicó)', () async {
      await cola.registrarVenta(venta());
      await cola.marcarEnviadas(['id-v1']);
      await cola.aplicarResultados([resultadoDe('id-v1', EstadoResultadoSync.enConflicto, motivo: 'stock_insuficiente', procesadaEn: servidorDespues)], recibidoEn: servidorDespues);
      expect(await estimado(), 10);
    });

    test('una confirmada resta SOLO hasta el siguiente paquete de stock', () async {
      await cola.registrarVenta(venta());
      await cola.marcarEnviadas(['id-v1']);
      await cola.aplicarResultados([resultadoDe('id-v1', EstadoResultadoSync.confirmada, procesadaEn: servidorDespues)], recibidoEn: servidorDespues);
      expect(await estimado(), 8, reason: 'el stock conocido (10:00) es anterior a la confirmación (11:00)');

      // Llega un paquete de stock generado DESPUÉS de la confirmación: ya refleja la venta, no se resta dos veces.
      await db.update('stock_conocido', {'cantidad': 8, 'generado_en': '2026-10-31T12:00:00Z'}, where: 'variante_id = 100');
      expect(await estimado(), 8);
    });

    test('una confirmada ANTES del stock conocido no resta (ese stock ya la incluye)', () async {
      await cola.registrarVenta(venta());
      await cola.marcarEnviadas(['id-v1']);
      await cola.aplicarResultados([resultadoDe('id-v1', EstadoResultadoSync.confirmada, procesadaEn: servidorAntes)], recibidoEn: servidorAntes);
      expect(await estimado(), 10);
    });

    test('suma varias operaciones y nunca baja de 0', () async {
      await cola.registrarVenta(venta(id: 'a', lineas: const [LineaVenta(varianteId: 100, cantidad: 6, precioUnitarioCentavos: 1)]));
      await cola.registrarReserva(reserva(id: 'b', lineas: const [LineaReserva(varianteId: 100, cantidad: 3)]));
      expect(await estimado(), 1);
      await cola.registrarVenta(venta(id: 'c', lineas: const [LineaVenta(varianteId: 100, cantidad: 5, precioUnitarioCentavos: 1)]));
      expect(await estimado(), 0);
    });

    test('solo resta en la sucursal de la operación', () async {
      await sembrarSucursal(db, id: 3);
      await sembrarStock(db, varianteId: 100, sucursalId: 3, cantidad: 10);
      await cola.registrarVenta(venta(sucursalId: 3));
      expect(await estimado(sucursalId: 3), 8);
      expect(await estimado(sucursalId: 1), 10);
    });

    test('solo resta la variante vendida', () async {
      await cola.registrarVenta(venta());
      expect(await estimado(varianteId: 101), 4);
    });

    test('al confirmarse y llegar el paquete, el ciclo completo da el stock real', () async {
      await cola.registrarVenta(venta());
      expect(await estimado(), 8);
      await cola.marcarEnviadas(['id-v1']);
      expect(await estimado(), 8);
      await cola.aplicarResultados([resultadoDe('id-v1', EstadoResultadoSync.confirmada, procesadaEn: servidorDespues)], recibidoEn: servidorDespues);
      expect(await estimado(), 8);
      await db.update('stock_conocido', {'cantidad': 8, 'generado_en': '2026-10-31T13:00:00Z'}, where: 'variante_id = 100');
      expect(await estimado(), 8);
    });
  });

  // =========================================================================================
  group('cambios (el flujo para refrescar la pantalla)', () {
    late int emitidos;
    late StreamSubscription<void> sub;

    setUp(() {
      emitidos = 0;
      sub = cola.cambios.listen((_) => emitidos++);
    });

    tearDown(() async {
      await sub.cancel();
    });

    test('emite una vez tras registrar una venta', () async {
      await cola.registrarVenta(venta());
      await pumpEventQueue();
      expect(emitidos, 1);
    });

    test('emite tras registrar una reserva', () async {
      await cola.registrarReserva(reserva());
      await pumpEventQueue();
      expect(emitidos, 1);
    });

    test('NO emite si la validación rechaza el registro', () async {
      await expectLater(cola.registrarVenta(venta(efectivo: false)), colaError());
      await expectLater(cola.registrarVenta(venta(cliente: 2)), colaError());
      await pumpEventQueue();
      expect(emitidos, 0);
    });

    test('NO emite si el registro hizo rollback en plena transacción', () async {
      await db.execute(
        "CREATE TRIGGER falla_detalle BEFORE INSERT ON venta_detalle WHEN NEW.cantidad = 3 "
        "BEGIN SELECT RAISE(ABORT, 'falla de prueba'); END",
      );
      await expectLater(
        cola.registrarVenta(venta(lineas: const [LineaVenta(varianteId: 100, cantidad: 3, precioUnitarioCentavos: 1)])),
        throwsA(isA<DatabaseException>()),
      );
      await pumpEventQueue();
      expect(emitidos, 0);
    });

    test('NO emite con un id duplicado', () async {
      await cola.registrarVenta(venta());
      await pumpEventQueue();
      emitidos = 0;
      await expectLater(cola.registrarVenta(venta()), colaError());
      await pumpEventQueue();
      expect(emitidos, 0);
    });

    test('emite tras marcarEnviadas, volverARegistrada y registrarFalloDeRed cuando algo cambió', () async {
      await cola.registrarVenta(venta());
      await pumpEventQueue();
      emitidos = 0;
      await cola.marcarEnviadas(['id-v1']);
      await pumpEventQueue();
      expect(emitidos, 1);
      await cola.registrarFalloDeRed(['id-v1'], error: 'x', proximoReintento: reloj.ahora());
      await pumpEventQueue();
      expect(emitidos, 2);
      await cola.volverARegistrada(['id-v1'], error: 'x');
      await pumpEventQueue();
      expect(emitidos, 3);
    });

    test('NO emite cuando la llamada no cambió nada (ids que no existen o estados que no aplican)', () async {
      await ventaEn('a', 'confirmada');
      await pumpEventQueue();
      emitidos = 0;
      await cola.marcarEnviadas(['a', 'fantasma']);
      await cola.volverARegistrada(['a']);
      await cola.registrarFalloDeRed(['a'], error: 'x', proximoReintento: reloj.ahora());
      await cola.marcarRechazadaLocal('a', motivo: 'x', recibidoEn: reloj.ahora());
      await pumpEventQueue();
      expect(emitidos, 0);
    });

    test('aplicarResultados emite UNA vez por llamada aunque lleve varias respuestas', () async {
      await ventaEn('a', 'enviada');
      await ventaEn('b', 'enviada');
      await pumpEventQueue();
      emitidos = 0;
      await cola.aplicarResultados([
        resultadoDe('a', EstadoResultadoSync.confirmada, procesadaEn: reloj.ahora()),
        resultadoDe('b', EstadoResultadoSync.confirmada, procesadaEn: reloj.ahora()),
      ], recibidoEn: reloj.ahora());
      await pumpEventQueue();
      expect(emitidos, 1);
    });

    test('aplicarResultados NO emite si todas se ignoran', () async {
      await ventaEn('a', 'registrada');
      await pumpEventQueue();
      emitidos = 0;
      await cola.aplicarResultados([resultadoDe('a', EstadoResultadoSync.confirmada)], recibidoEn: reloj.ahora());
      await cola.aplicarResultados([resultadoDe('fantasma', EstadoResultadoSync.confirmada)], recibidoEn: reloj.ahora());
      await pumpEventQueue();
      expect(emitidos, 0);
    });

    test('aplicarResultados NO emite si hizo rollback', () async {
      await ventaEn('a', 'enviada');
      await pumpEventQueue();
      emitidos = 0;
      await db.execute(
        "CREATE TRIGGER falla_rechazo BEFORE INSERT ON resultado_sync WHEN NEW.estado_resultado = 'rechazada' "
        "BEGIN SELECT RAISE(ABORT, 'falla de prueba'); END",
      );
      await expectLater(
        cola.aplicarResultados([resultadoDe('a', EstadoResultadoSync.rechazada, motivo: 'x')], recibidoEn: reloj.ahora()),
        throwsA(isA<DatabaseException>()),
      );
      await pumpEventQueue();
      expect(emitidos, 0);
    });

    test('un error_temporal que anota el error también emite (cambia lo que se ve)', () async {
      await ventaEn('a', 'enviada');
      await pumpEventQueue();
      emitidos = 0;
      await cola.aplicarResultados([resultadoDe('a', EstadoResultadoSync.errorTemporal, mensaje: 'x')], recibidoEn: reloj.ahora());
      await pumpEventQueue();
      expect(emitidos, 1);
    });

    test('marcarRechazadaLocal emite', () async {
      await ventaEn('a', 'registrada');
      await pumpEventQueue();
      emitidos = 0;
      await cola.marcarRechazadaLocal('a', motivo: 'x', recibidoEn: reloj.ahora());
      await pumpEventQueue();
      expect(emitidos, 1);
    });

    test('es un flujo broadcast: varios oyentes reciben el aviso', () async {
      var segundo = 0;
      final sub2 = cola.cambios.listen((_) => segundo++);
      await cola.registrarVenta(venta());
      await pumpEventQueue();
      expect(emitidos, 1);
      expect(segundo, 1);
      await sub2.cancel();
    });

    test('dispose cierra el flujo y las escrituras siguientes no fallan', () async {
      var cerrado = false;
      final sub3 = cola.cambios.listen((_) {}, onDone: () => cerrado = true);
      await cola.dispose();
      await pumpEventQueue();
      expect(cerrado, isTrue);
      await cola.registrarVenta(venta());
      expect(await contarFilas(db, 'operacion_pendiente'), 1);
      await sub3.cancel();
    });
  });

  // =========================================================================================
  group('detalle', () {
    test('une los nombres del catálogo y el cliente de una venta', () async {
      await cola.registrarVenta(
        venta(
          cliente: 1,
          lineas: const [
            LineaVenta(varianteId: 100, cantidad: 2, precioUnitarioCentavos: 7500),
            LineaVenta(varianteId: 101, cantidad: 1, precioUnitarioCentavos: 5000, descuentoUnitarioCentavos: 500),
          ],
        ),
      );
      final d = (await cola.detalle('id-v1'))!;
      expect(d.operacion.operacionId, 'id-v1');
      expect(d.clienteNombre, 'Ana Pérez');
      expect(d.clienteServidorId, 501);
      expect(d.totalCentavos, 19500);
      expect(d.efectivoConfirmado, isTrue);
      expect(d.fechaVisita, isNull);
      expect(d.horaDesde, isNull);
      expect(d.horaHasta, isNull);
      expect(d.observacion, isNull);

      expect(d.lineas, hasLength(2));
      final l = d.lineas.first;
      expect(l.varianteId, 100);
      expect(l.cantidad, 2);
      expect(l.nombre, 'Polera Básica');
      expect(l.talla, 'S');
      expect(l.color, 'Negro');
      expect(l.sku, 'POL-S-NEG');
      expect(l.imagenUrl, 'https://img.test/polera.jpg');
      expect(l.precioUnitarioCentavos, 7500);
      expect(d.lineas.last.talla, 'M');
      expect(d.lineas.last.precioUnitarioCentavos, 5000);
    });

    test('una venta sin cliente', () async {
      await cola.registrarVenta(venta());
      final d = (await cola.detalle('id-v1'))!;
      expect(d.clienteNombre, isNull);
      expect(d.clienteServidorId, isNull);
      expect(d.totalCentavos, 15000);
    });

    test('un cliente sin apellido muestra solo el nombre', () async {
      final id = await sembrarClienteMinimo(db, servidorId: 502, nombre: 'Cher');
      await cola.registrarVenta(venta(cliente: id));
      expect((await cola.detalle('id-v1'))!.clienteNombre, 'Cher');
    });

    test('una reserva: visita, horas, observación y líneas sin precio', () async {
      await cola.registrarReserva(
        reserva(observacion: 'Pasa por la tarde', lineas: const [LineaReserva(varianteId: 100, cantidad: 2)]),
      );
      final d = (await cola.detalle('id-r1'))!;
      expect(d.clienteNombre, 'Ana Pérez');
      expect(d.clienteServidorId, 501);
      expect(d.fechaVisita, DateTime(2026, 11, 2));
      expect(d.horaDesde, '10:00');
      expect(d.horaHasta, '11:00');
      expect(d.observacion, 'Pasa por la tarde');
      expect(d.totalCentavos, isNull);
      expect(d.efectivoConfirmado, isNull);
      expect(d.lineas.single.nombre, 'Polera Básica');
      expect(d.lineas.single.cantidad, 2);
      expect(d.lineas.single.precioUnitarioCentavos, isNull);
    });

    test('una variante que ya no existiera NUNCA rompe: usa "Prenda #id"', () async {
      await cola.registrarVenta(
        venta(
          lineas: const [
            LineaVenta(varianteId: 100, cantidad: 1, precioUnitarioCentavos: 7500),
            LineaVenta(varianteId: 101, cantidad: 1, precioUnitarioCentavos: 5000),
          ],
        ),
      );
      // Con las llaves foráneas activas esto no pasaría; se simula una base dañada.
      await db.execute('PRAGMA foreign_keys = OFF');
      await db.delete('variante', where: 'id = 101');
      await db.execute('PRAGMA foreign_keys = ON');

      final d = (await cola.detalle('id-v1'))!;
      expect(d.lineas, hasLength(2));
      expect(d.lineas.first.nombre, 'Polera Básica');
      expect(d.lineas.last.nombre, 'Prenda #101');
      expect(d.lineas.last.talla, isNull);
      expect(d.lineas.last.color, isNull);
      expect(d.lineas.last.sku, isNull);
      expect(d.lineas.last.imagenUrl, isNull);
      expect(d.lineas.last.precioUnitarioCentavos, 5000, reason: 'el precio cobrado está en el detalle de la venta');
    });

    test('lo mismo en una reserva', () async {
      await cola.registrarReserva(reserva(lineas: const [LineaReserva(varianteId: 101, cantidad: 1)]));
      await db.execute('PRAGMA foreign_keys = OFF');
      await db.delete('variante', where: 'id = 101');
      await db.execute('PRAGMA foreign_keys = ON');
      expect((await cola.detalle('id-r1'))!.lineas.single.nombre, 'Prenda #101');
    });

    test('una variante dada de baja después sigue mostrando su nombre', () async {
      await cola.registrarVenta(venta());
      await db.update('variante', {'activo': 0}, where: 'id = 100');
      await db.update('producto', {'activo': 0}, where: 'id = 10');
      expect((await cola.detalle('id-v1'))!.lineas.single.nombre, 'Polera Básica');
    });

    test('un producto sin imagen deja imagenUrl en null', () async {
      await sembrarProducto(db, id: 30, nombre: 'Sin foto', variantes: [variante(300, tallaId: 4)]);
      await cola.registrarVenta(venta(lineas: const [LineaVenta(varianteId: 300, cantidad: 1, precioUnitarioCentavos: 100)]));
      expect((await cola.detalle('id-v1'))!.lineas.single.imagenUrl, isNull);
    });

    test('operación inexistente: null', () async {
      expect(await cola.detalle('fantasma'), isNull);
    });

    test('la operación del detalle refleja el estado actual', () async {
      await cola.registrarVenta(venta());
      await cola.marcarEnviadas(['id-v1']);
      expect((await cola.detalle('id-v1'))!.operacion.estado, EstadoOperacion.enviada);
    });

    test('el detalle de una operación con filas inconsistentes (sin venta) no rompe', () async {
      await db.insert('operacion_pendiente', {
        'operacion_id': 'huerfana',
        'empresa_id': 1,
        'sucursal_id': 1,
        'usuario_id': 7,
        'tipo': 'venta_contado',
        'estado': 'registrada',
        'payload': '{}',
        'version_contrato': 1,
        'fecha_operacion': '2026-10-31T10:00:00Z',
        'creada_en': '2026-10-31T10:00:00Z',
      });
      final d = (await cola.detalle('huerfana'))!;
      expect(d.lineas, isEmpty);
      expect(d.totalCentavos, isNull);
    });
  });

  // =========================================================================================
  group('aislamiento por empresa y principios', () {
    test('el catálogo y los clientes de otra empresa no se pueden usar', () async {
      final antes = await huellaDeRegistro(db);
      await expectLater(
        cola.registrarVenta(venta(empresaId: 2, sucursalId: 11, lineas: const [LineaVenta(varianteId: 100, cantidad: 1, precioUnitarioCentavos: 1)])),
        colaError('prendas'),
      );
      await expectLater(
        cola.registrarVenta(venta(empresaId: 2, sucursalId: 11, cliente: 1, lineas: const [LineaVenta(varianteId: 200, cantidad: 1, precioUnitarioCentavos: 1)])),
        colaError('cliente'),
      );
      expect(await huellaDeRegistro(db), antes);
    });

    test('la empresa 2 registra con lo suyo y su cliente va por su servidor_id', () async {
      await cola.registrarVenta(
        venta(empresaId: 2, sucursalId: 11, cliente: 3, lineas: const [LineaVenta(varianteId: 200, cantidad: 1, precioUnitarioCentavos: 1000)]),
      );
      final payload = jsonDecode((await fila('id-v1'))['payload']! as String) as Map;
      expect(payload['cliente_id'], 601);
      expect((await fila('id-v1'))['empresa_id'], 2);
    });

    test('una operación NUNCA se borra aquí: pasar por todos los estados la deja en su sitio', () async {
      await cola.registrarVenta(venta());
      await cola.marcarEnviadas(['id-v1']);
      await cola.volverARegistrada(['id-v1']);
      await cola.marcarEnviadas(['id-v1']);
      await cola.aplicarResultados([resultadoDe('id-v1', EstadoResultadoSync.confirmada, procesadaEn: reloj.ahora())], recibidoEn: reloj.ahora());
      expect(await contarFilas(db, 'operacion_pendiente'), 1);
      expect(await contarFilas(db, 'venta'), 1);
      expect(await contarFilas(db, 'venta_detalle'), 1);
    });

    test('el payload y las filas venta no se editan después de registrar', () async {
      await cola.registrarVenta(venta(cliente: 1));
      final antes = (await fila('id-v1'))['payload'];
      final ventaAntes = await db.query('venta');
      await cola.marcarEnviadas(['id-v1']);
      await cola.registrarFalloDeRed(['id-v1'], error: 'x', proximoReintento: reloj.ahora());
      await cola.volverARegistrada(['id-v1']);
      await cola.marcarEnviadas(['id-v1']);
      await cola.aplicarResultados([resultadoDe('id-v1', EstadoResultadoSync.confirmada, procesadaEn: reloj.ahora())], recibidoEn: reloj.ahora());
      expect((await fila('id-v1'))['payload'], antes);
      expect(await db.query('venta'), ventaAntes);
    });

    test('reenviar produce exactamente el mismo sobre (idempotencia D12)', () async {
      await cola.registrarVenta(venta(cliente: 1));
      final primero = OperacionEnvio.desde((await cola.obtener('id-v1'))!).toJson();
      await cola.marcarEnviadas(['id-v1']);
      await cola.volverARegistrada(['id-v1'], error: 'x');
      await cola.marcarEnviadas(['id-v1']);
      final segundo = OperacionEnvio.desde((await cola.obtener('id-v1'))!).toJson();
      expect(segundo, primero);
    });
  });
}
