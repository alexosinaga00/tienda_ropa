import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/cliente_offline/config/cliente_offline_config.dart';
import 'package:mobile/features/cliente_offline/data/metodo_pago_repository.dart';
import 'package:mobile/features/cliente_offline/data/repositorio_cliente.dart';
import 'package:mobile/features/cliente_offline/models/linea_carrito_local.dart';
import 'package:mobile/features/cliente_offline/models/metodo_pago.dart';
import 'package:mobile/features/cliente_offline/state/carrito_local_controller.dart';
import 'package:mobile/features/cliente_offline/state/metodo_pago_controller.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/api_client_falso.dart';
import '../../helpers/cliente_offline_apoyo.dart';
import '../../helpers/siembra_operaciones.dart';

void main() {
  late Database db;
  late RelojDePrueba reloj;

  setUp(() async {
    db = await abrirBaseClienteDePrueba();
    reloj = RelojDePrueba(DateTime.utc(2026, 11, 6, 12));
  });

  tearDown(() => db.close());

  CarritoLocalController carrito({AlcanceCliente? alcance = alcanceAna, bool activo = true}) => CarritoLocalController(
    () async => alcance == null ? null : RepositorioCliente(db, alcance: alcance),
    reloj,
    activo: activo,
  );

  Future<void> reposar() => Future<void>.delayed(const Duration(milliseconds: 30));

  group('CarritoLocalController (el carrito de sin conexión)', () {
    test('al abrir lee lo que ya había guardado', () async {
      await RepositorioCliente(db, alcance: alcanceAna).agregarLinea(lineaCarrito(varianteId: 5), maximo: 20);

      final c = carrito();
      await reposar();

      expect(c.state.map((l) => l.varianteId), [5]);
    });

    test('agregar guarda la prenda con los datos para mostrarla (nombre, talla, color, precio, foto)', () async {
      final c = carrito();

      final ok = await c.agregar(
        varianteId: 10,
        productoId: 1,
        productoNombre: 'Polera Nike',
        precioUnitarioCentavos: 19900,
        talla: 'M',
        color: 'Azul',
        imagen: 'https://x/p.jpg',
      );

      expect(ok, isTrue);
      final l = c.state.single;
      expect(l.productoNombre, 'Polera Nike');
      expect(l.detalle, 'M · Azul');
      expect(l.precioUnitarioCentavos, 19900);
      expect(l.imagen, 'https://x/p.jpg');
      expect(l.agregadoEn, reloj.actual);
    });

    test('agregar la misma prenda suma, con el tope de unidades por línea', () async {
      final c = carrito();
      for (var i = 0; i < maxUnidadesLinea + 5; i++) {
        await c.agregar(varianteId: 10, productoId: 1, productoNombre: 'Polera', precioUnitarioCentavos: 100);
      }

      expect(c.state, hasLength(1));
      expect(c.state.single.cantidad, maxUnidadesLinea);
    });

    test('cambiar cantidad, quitar y vaciar', () async {
      final c = carrito();
      await c.agregar(varianteId: 1, productoId: 1, productoNombre: 'A', precioUnitarioCentavos: 100);
      await c.agregar(varianteId: 2, productoId: 2, productoNombre: 'B', precioUnitarioCentavos: 200);

      await c.cambiarCantidad(1, 4);
      expect(c.state.firstWhere((l) => l.varianteId == 1).cantidad, 4);
      await c.cambiarCantidad(1, 999);
      expect(c.state.firstWhere((l) => l.varianteId == 1).cantidad, maxUnidadesLinea);
      await c.quitar(2);
      expect(c.state.map((l) => l.varianteId), [1]);
      await c.cambiarCantidad(1, 0);
      expect(c.state, isEmpty);

      await c.agregar(varianteId: 3, productoId: 3, productoNombre: 'C', precioUnitarioCentavos: 300);
      await c.vaciar();
      expect(c.state, isEmpty);
    });

    test('sin sesión de cliente no guarda nada', () async {
      final c = carrito(alcance: null, activo: false);

      final ok = await c.agregar(varianteId: 1, productoId: 1, productoNombre: 'A', precioUnitarioCentavos: 100);

      expect(ok, isFalse);
      expect(c.state, isEmpty);
    });

    test('el carrito de una persona no lo ve otra', () async {
      final ana = carrito();
      await ana.agregar(varianteId: 1, productoId: 1, productoNombre: 'De Ana', precioUnitarioCentavos: 100);

      final luis = carrito(alcance: alcanceLuis);
      await reposar();

      expect(luis.state, isEmpty);
      expect(ana.state, hasLength(1));
    });

    test('"Pasar a mi carrito" pasa línea por línea; las que el servidor rechaza se quedan', () async {
      final c = carrito();
      await c.agregar(varianteId: 1, productoId: 1, productoNombre: 'Pasa', precioUnitarioCentavos: 100, cantidad: 2);
      await c.agregar(varianteId: 2, productoId: 2, productoNombre: 'Sin stock', precioUnitarioCentavos: 100);
      await c.agregar(varianteId: 3, productoId: 3, productoNombre: 'Pasa también', precioUnitarioCentavos: 100);
      final recibidas = <(int, int)>[];

      final r = await c.pasarAlServidor((varianteId, cantidad) async {
        if (varianteId == 2) throw StateError('409: sin stock');
        recibidas.add((varianteId, cantidad));
      });

      expect(r.pasadas, 2);
      expect(r.fallidas, 1);
      expect(recibidas, [(1, 2), (3, 1)]);
      expect(c.state.map((l) => l.productoNombre), ['Sin stock']);
      expect(await RepositorioCliente(db, alcance: alcanceAna).carrito(), hasLength(1), reason: 'también en la base');
    });

    test('si TODAS fallan, ninguna se pierde', () async {
      final c = carrito();
      await c.agregar(varianteId: 1, productoId: 1, productoNombre: 'A', precioUnitarioCentavos: 100);
      await c.agregar(varianteId: 2, productoId: 2, productoNombre: 'B', precioUnitarioCentavos: 100);

      final r = await c.pasarAlServidor((_, _) async => throw StateError('sin red'));

      expect(r.pasadas, 0);
      expect(r.fallidas, 2);
      expect(c.state, hasLength(2));
    });

    test('si la base local no abre, no lanza', () async {
      final c = CarritoLocalController(() async => throw StateError('no abre'), reloj, activo: true);

      await reposar();
      final ok = await c.agregar(varianteId: 1, productoId: 1, productoNombre: 'A', precioUnitarioCentavos: 100);

      expect(ok, isFalse);
      expect(c.state, isEmpty);
    });
  });

  group('MetodoPagoController (lo que se recuerda del PayPal)', () {
    late ApiClientFalso api;

    MetodoPagoController controlador({AlcanceCliente? alcance = alcanceAna, bool activo = true}) =>
        MetodoPagoController(
          () async => alcance == null ? null : RepositorioCliente(db, alcance: alcance),
          MetodoPagoRepository(api),
          reloj,
          activo: activo,
        );

    setUp(() => api = ApiClientFalso());

    test('empieza sin saber nada', () async {
      final c = controlador();
      await reposar();

      expect(c.state, isNull);
    });

    test('refrescar con conexión pregunta al servidor y lo recuerda en la base', () async {
      api.responder('GET', '/metodos-pago/paypal', {
        'guardado': true,
        'correo_paypal': 'j***@gmail.com',
        'guardado_en': '2026-11-05T15:00:00Z',
      });
      final c = controlador();

      final estado = await c.refrescar();

      expect(estado!.guardado, isTrue);
      expect(c.state!.guardado, isTrue);
      expect(c.state!.correoPaypal, 'j***@gmail.com');
      expect(c.state!.verificadoEn, reloj.actual);

      // Una app recién abierta (sin red) lo sigue sabiendo.
      final nuevo = controlador();
      await reposar();
      expect(nuevo.state!.guardado, isTrue);
      expect(nuevo.state!.correoPaypal, 'j***@gmail.com');
    });

    test('si la consulta falla, queda lo que ya se recordaba', () async {
      final c = controlador();
      await c.recordar(const MetodoPagoPaypal(guardado: true, correoPaypal: 'a***@x.com'));
      api.responder('GET', '/metodos-pago/paypal', errorSinRed);

      final estado = await c.refrescar();

      expect(estado, isNull);
      expect(c.state!.guardado, isTrue);
    });

    test('quitarlo se recuerda también', () async {
      final c = controlador();
      await c.recordar(const MetodoPagoPaypal(guardado: true, correoPaypal: 'a***@x.com'));

      await c.recordar(MetodoPagoPaypal.sinGuardar);

      expect(c.state!.guardado, isFalse);
      expect(c.state!.correoPaypal, isNull);
      final nuevo = controlador();
      await reposar();
      expect(nuevo.state!.guardado, isFalse);
    });

    test('lo recordado es por persona', () async {
      await controlador().recordar(const MetodoPagoPaypal(guardado: true));

      final luis = controlador(alcance: alcanceLuis);
      await reposar();

      expect(luis.state, isNull);
    });

    test('en la base solo hay estado y correo enmascarado: ni tokens ni tarjeta', () async {
      await controlador().recordar(const MetodoPagoPaypal(guardado: true, correoPaypal: 'j***@gmail.com'));

      final filas = await db.query('cli_meta');

      expect(filas, hasLength(1));
      final valor = filas.single['valor']! as String;
      expect(valor, contains('j***@gmail.com'));
      for (final prohibido in ['token', 'vault', 'tarjeta', 'card', 'password']) {
        expect(valor.toLowerCase(), isNot(contains(prohibido)));
      }
    });
  });
}
