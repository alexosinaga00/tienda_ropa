import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/cliente_offline/data/repositorio_cliente.dart';
import 'package:mobile/features/cliente_offline/models/linea_carrito_local.dart';
import 'package:mobile/features/cliente_offline/models/pedido_sin_conexion.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/cliente_offline_apoyo.dart';

void main() {
  late Database db;
  late RepositorioCliente ana;
  late RepositorioCliente luis;

  setUp(() async {
    db = await abrirBaseClienteDePrueba();
    ana = RepositorioCliente(db, alcance: alcanceAna);
    luis = RepositorioCliente(db, alcance: alcanceLuis);
  });

  tearDown(() => db.close());

  group('carrito local', () {
    test('agrega una prenda con todo lo necesario para mostrarla sin red', () async {
      await ana.agregarLinea(
        lineaCarrito(
          varianteId: 10,
          productoId: 5,
          nombre: 'Polera Nike',
          talla: 'M',
          color: 'Azul',
          precio: 19900,
          imagen: 'https://x/p.jpg',
        ),
        maximo: 20,
      );

      final l = (await ana.carrito()).single;
      expect(l.varianteId, 10);
      expect(l.productoId, 5);
      expect(l.productoNombre, 'Polera Nike');
      expect(l.detalle, 'M · Azul');
      expect(l.precioUnitarioCentavos, 19900);
      expect(l.imagen, 'https://x/p.jpg');
      expect(l.cantidad, 1);
    });

    test('agregar la misma variante suma las cantidades, con tope', () async {
      await ana.agregarLinea(lineaCarrito(cantidad: 15), maximo: 20);

      final suma = await ana.agregarLinea(lineaCarrito(cantidad: 4), maximo: 20);
      final tope = await ana.agregarLinea(lineaCarrito(cantidad: 4), maximo: 20);

      expect(suma.cantidad, 19);
      expect(tope.cantidad, 20);
      expect(await ana.carrito(), hasLength(1));
    });

    test('al sumar conserva cuándo se agregó por primera vez y refresca el precio que acaba de ver', () async {
      final primera = DateTime.utc(2026, 11, 1, 8);
      await ana.agregarLinea(lineaCarrito(precio: 10000, agregadoEn: primera), maximo: 20);

      await ana.agregarLinea(lineaCarrito(precio: 12000, agregadoEn: DateTime.utc(2026, 11, 5)), maximo: 20);

      final l = (await ana.carrito()).single;
      expect(l.agregadoEn, primera);
      expect(l.precioUnitarioCentavos, 12000);
    });

    test('cambiar cantidad, quitar con 0 y vaciar', () async {
      await ana.agregarLinea(lineaCarrito(varianteId: 1), maximo: 20);
      await ana.agregarLinea(lineaCarrito(varianteId: 2), maximo: 20);

      await ana.cambiarCantidad(1, 5);
      expect((await ana.carrito()).firstWhere((l) => l.varianteId == 1).cantidad, 5);

      await ana.cambiarCantidad(2, 0);
      expect((await ana.carrito()).map((l) => l.varianteId), [1]);

      await ana.vaciarCarrito();
      expect(await ana.carrito(), isEmpty);
    });

    test('las líneas salen de la más vieja a la más nueva', () async {
      await ana.agregarLinea(lineaCarrito(varianteId: 3, agregadoEn: DateTime.utc(2026, 11, 3)), maximo: 20);
      await ana.agregarLinea(lineaCarrito(varianteId: 1, agregadoEn: DateTime.utc(2026, 11, 1)), maximo: 20);
      await ana.agregarLinea(lineaCarrito(varianteId: 2, agregadoEn: DateTime.utc(2026, 11, 2)), maximo: 20);

      expect((await ana.carrito()).map((l) => l.varianteId), [1, 2, 3]);
    });

    test('cada persona ve solo SU carrito', () async {
      await ana.agregarLinea(lineaCarrito(varianteId: 1), maximo: 20);
      await luis.agregarLinea(lineaCarrito(varianteId: 2), maximo: 20);
      final otraEmpresa = RepositorioCliente(db, alcance: alcanceOtraEmpresa);
      await otraEmpresa.agregarLinea(lineaCarrito(varianteId: 3), maximo: 20);

      expect((await ana.carrito()).map((l) => l.varianteId), [1]);
      expect((await luis.carrito()).map((l) => l.varianteId), [2]);
      expect((await otraEmpresa.carrito()).map((l) => l.varianteId), [3]);

      await ana.vaciarCarrito();
      expect(await luis.carrito(), hasLength(1));
    });

    test('el subtotal se suma en centavos enteros', () {
      final lineas = [
        lineaCarrito(varianteId: 1, cantidad: 3, precio: 10),
        lineaCarrito(varianteId: 2, cantidad: 1, precio: 20),
      ];

      expect(totalDeLineasCentavos(lineas), 50);
    });
  });

  group('lo recordado (meta)', () {
    test('guardar, leer y reemplazar, por persona', () async {
      await ana.guardarMeta('metodo_pago', 'uno');
      await ana.guardarMeta('metodo_pago', 'dos');
      await luis.guardarMeta('metodo_pago', 'de luis');

      expect(await ana.leerMeta('metodo_pago'), 'dos');
      expect(await luis.leerMeta('metodo_pago'), 'de luis');
      expect(await ana.leerMeta('otra'), isNull);

      await ana.borrarMeta('metodo_pago');
      expect(await ana.leerMeta('metodo_pago'), isNull);
      expect(await luis.leerMeta('metodo_pago'), 'de luis');
    });
  });

  group('pedidos', () {
    test('registrar guarda el pedido y vacía el carrito en la MISMA transacción', () async {
      await ana.agregarLinea(lineaCarrito(), maximo: 20);

      final guardado = await ana.registrarPedido(pedidoDePrueba(), vaciarElCarrito: true);

      expect(guardado.operacionId, idOperacion(1));
      expect(await ana.carrito(), isEmpty);
      expect(await ana.pedidos(), hasLength(1));
    });

    test('si el pedido no se puede guardar, el carrito queda intacto', () async {
      await ana.agregarLinea(lineaCarrito(), maximo: 20);
      final malo = PedidoSinConexion(
        empresaId: 7,
        usuarioId: 4,
        operacionId: idOperacion(1),
        estado: EstadoPedidoLocal.pendiente,
        sucursalId: 3,
        sucursalNombre: 'Centro',
        costoEnvioCentavos: 0,
        lineas: const [],
        totalMaximoCentavos: -5, // viola el CHECK
        fechaPedido: '2026-11-06T12:00:00Z',
        creadoEn: DateTime.utc(2026, 11, 6, 12),
      );

      await expectLater(ana.registrarPedido(malo, vaciarElCarrito: true), throwsA(isA<DatabaseException>()));

      expect(await ana.carrito(), hasLength(1));
      expect(await ana.pedidos(), isEmpty);
    });

    test('un doble toque (misma operacion_id) devuelve el que ya estaba y no crea otro', () async {
      final primero = await ana.registrarPedido(pedidoDePrueba(cantidad: 2));

      final segundo = await ana.registrarPedido(pedidoDePrueba(cantidad: 9));

      expect(segundo.totalMaximoCentavos, primero.totalMaximoCentavos);
      expect(await ana.pedidos(), hasLength(1));
    });

    test('no guarda un pedido de otra persona o de otra empresa', () async {
      await expectLater(ana.registrarPedido(pedidoDePrueba(alcance: alcanceLuis)), throwsA(isA<StateError>()));
      await expectLater(ana.registrarPedido(pedidoDePrueba(alcance: alcanceOtraEmpresa)), throwsA(isA<StateError>()));
    });

    test('lo que se guarda vuelve igual: líneas, tope, fechas y estado', () async {
      final original = pedidoDePrueba(n: 7, cantidad: 3, precio: 12550);
      await ana.registrarPedido(original);

      final leido = (await ana.pedido(idOperacion(7)))!;

      expect(leido.estado, EstadoPedidoLocal.pendiente);
      expect(leido.sucursalId, 3);
      expect(leido.sucursalNombre, 'Centro');
      expect(leido.totalMaximoCentavos, 37650);
      expect(leido.lineas.single.varianteId, 10);
      expect(leido.lineas.single.cantidad, 3);
      expect(leido.lineas.single.precioUnitarioCentavos, 12550);
      expect(leido.lineas.single.detalle, 'M · Azul');
      expect(leido.creadoEn, original.creadoEn);
      expect(leido.fechaPedido, original.fechaPedido);
      expect(leido.visto, isFalse);
    });

    test('cada persona ve solo SUS pedidos, del más nuevo al más viejo', () async {
      await ana.registrarPedido(pedidoDePrueba(n: 1, creadoEn: DateTime.utc(2026, 11, 1)));
      await ana.registrarPedido(pedidoDePrueba(n: 2, creadoEn: DateTime.utc(2026, 11, 3)));
      await luis.registrarPedido(pedidoDePrueba(n: 3, alcance: alcanceLuis));

      expect((await ana.pedidos()).map((p) => p.operacionId), [idOperacion(2), idOperacion(1)]);
      expect((await luis.pedidos()).map((p) => p.operacionId), [idOperacion(3)]);
      expect(await luis.pedido(idOperacion(1)), isNull);
    });

    test('contarSinEnviar cuenta pendientes y enviando; no cuenta vencidos ni resueltos', () async {
      await ana.registrarPedido(pedidoDePrueba(n: 1));
      await ana.registrarPedido(pedidoDePrueba(n: 2, estado: EstadoPedidoLocal.enviando));
      await ana.registrarPedido(pedidoDePrueba(n: 3, estado: EstadoPedidoLocal.cobrado));
      await ana.registrarPedido(pedidoDePrueba(n: 4, estado: EstadoPedidoLocal.rechazado));
      await ana.registrarPedido(pedidoDePrueba(n: 5, estado: EstadoPedidoLocal.vencido));
      await luis.registrarPedido(pedidoDePrueba(n: 6, alcance: alcanceLuis));

      expect(await ana.contarSinEnviar(), 2);
      expect(await luis.contarSinEnviar(), 1);
    });

    test('marcarEnviando suma un intento; no se puede enviar uno ya resuelto', () async {
      await ana.registrarPedido(pedidoDePrueba(n: 1));
      await ana.registrarPedido(pedidoDePrueba(n: 2, estado: EstadoPedidoLocal.cobrado));
      final ahora = DateTime.utc(2026, 11, 6, 13);

      expect(await ana.marcarEnviando(idOperacion(1), ahora), isTrue);
      expect(await ana.marcarEnviando(idOperacion(2), ahora), isFalse);
      expect(await ana.marcarEnviando(idOperacion(99), ahora), isFalse);

      final p = (await ana.pedido(idOperacion(1)))!;
      expect(p.estado, EstadoPedidoLocal.enviando);
      expect(p.intentos, 1);
      expect(p.ultimoIntentoEn, ahora);
    });

    test('pedidosParaEnviar: el más antiguo primero; un enviando solo si quedó huérfano', () async {
      final ahora = DateTime.utc(2026, 11, 6, 12);
      await ana.registrarPedido(pedidoDePrueba(n: 1, creadoEn: DateTime.utc(2026, 11, 6, 11)));
      await ana.registrarPedido(pedidoDePrueba(n: 2, creadoEn: DateTime.utc(2026, 11, 6, 9)));
      await ana.registrarPedido(
        pedidoDePrueba(
          n: 3,
          creadoEn: DateTime.utc(2026, 11, 6, 10),
          estado: EstadoPedidoLocal.enviando,
          ultimoIntentoEn: ahora.subtract(const Duration(seconds: 200)),
        ),
      );
      await ana.registrarPedido(
        pedidoDePrueba(
          n: 4,
          creadoEn: DateTime.utc(2026, 11, 6, 8),
          estado: EstadoPedidoLocal.enviando,
          ultimoIntentoEn: ahora.subtract(const Duration(seconds: 20)),
        ),
      );
      await ana.registrarPedido(pedidoDePrueba(n: 5, estado: EstadoPedidoLocal.vencido));

      final lista = await ana.pedidosParaEnviar(ahora, const Duration(seconds: 120));

      expect(lista.map((p) => p.operacionId), [idOperacion(2), idOperacion(3), idOperacion(1)]);
    });

    test('un estado final (cobrado, rechazado, vencido) no puede cambiar de estado', () async {
      for (final final_ in [EstadoPedidoLocal.cobrado, EstadoPedidoLocal.rechazado, EstadoPedidoLocal.vencido]) {
        await ana.registrarPedido(pedidoDePrueba(n: final_.index, estado: final_));
        await expectLater(
          ana.actualizarPedido(idOperacion(final_.index), {'estado': 'pendiente'}),
          throwsA(isA<StateError>()),
          reason: '$final_ ya no cambia',
        );
        expect((await ana.pedido(idOperacion(final_.index)))!.estado, final_);
      }
    });

    test('repetir la misma respuesta final (mismo estado) no es un error', () async {
      await ana.registrarPedido(pedidoDePrueba(estado: EstadoPedidoLocal.cobrado));

      await ana.actualizarPedido(idOperacion(1), {'estado': 'cobrado', 'mensaje': 'otra vez'});

      expect((await ana.pedido(idOperacion(1)))!.mensaje, 'otra vez');
    });

    test('solo se pueden cambiar las columnas permitidas', () async {
      await ana.registrarPedido(pedidoDePrueba());

      await expectLater(
        ana.actualizarPedido(idOperacion(1), {'total_maximo_centavos': 1}),
        throwsA(isA<ArgumentError>()),
      );
      await expectLater(ana.actualizarPedido(idOperacion(1), {'operacion_id': 'x'}), throwsA(isA<ArgumentError>()));
      await expectLater(ana.actualizarPedido(idOperacion(99), {'visto': 1}), throwsA(isA<StateError>()));
      expect((await ana.pedido(idOperacion(1)))!.totalMaximoCentavos, 39800);
    });

    test('descartar: solo pendiente o vencido; nada más se puede quitar', () async {
      await ana.registrarPedido(pedidoDePrueba(n: 1));
      await ana.registrarPedido(pedidoDePrueba(n: 2, estado: EstadoPedidoLocal.vencido));
      await ana.registrarPedido(pedidoDePrueba(n: 3, estado: EstadoPedidoLocal.enviando));
      await ana.registrarPedido(pedidoDePrueba(n: 4, estado: EstadoPedidoLocal.cobrado));

      expect(await ana.descartarPedido(idOperacion(1)), isTrue);
      expect(await ana.descartarPedido(idOperacion(2)), isTrue);
      expect(await ana.descartarPedido(idOperacion(3)), isFalse);
      expect(await ana.descartarPedido(idOperacion(4)), isFalse);
      expect(await luis.descartarPedido(idOperacion(3)), isFalse);

      expect(await ana.pedidos(), hasLength(2));
    });

    test('marcarVistos solo toca los resueltos y vencidos de ESA persona', () async {
      await ana.registrarPedido(pedidoDePrueba(n: 1, estado: EstadoPedidoLocal.cobrado));
      await ana.registrarPedido(pedidoDePrueba(n: 2));
      await luis.registrarPedido(pedidoDePrueba(n: 3, alcance: alcanceLuis, estado: EstadoPedidoLocal.rechazado));

      await ana.marcarVistos();

      expect((await ana.pedido(idOperacion(1)))!.visto, isTrue);
      expect((await ana.pedido(idOperacion(2)))!.visto, isFalse);
      expect((await luis.pedido(idOperacion(3)))!.visto, isFalse);
    });
  });

  group('cerrar sesión', () {
    Future<void> sembrarTodo(RepositorioCliente repo, AlcanceCliente a, int base) async {
      await repo.agregarLinea(lineaCarrito(varianteId: base), maximo: 20);
      await repo.guardarMeta('metodo_pago', 'x');
      await repo.registrarPedido(pedidoDePrueba(n: base + 1, alcance: a));
      await repo.registrarPedido(pedidoDePrueba(n: base + 2, alcance: a, estado: EstadoPedidoLocal.enviando));
      await repo.registrarPedido(pedidoDePrueba(n: base + 3, alcance: a, estado: EstadoPedidoLocal.cobrado));
      await repo.registrarPedido(pedidoDePrueba(n: base + 4, alcance: a, estado: EstadoPedidoLocal.rechazado));
      await repo.registrarPedido(pedidoDePrueba(n: base + 5, alcance: a, estado: EstadoPedidoLocal.vencido));
    }

    test(
      'el cierre normal borra el carrito, lo recordado y lo resuelto, pero CONSERVA los pedidos sin enviar',
      () async {
        await sembrarTodo(ana, alcanceAna, 10);
        await sembrarTodo(luis, alcanceLuis, 20);

        await ana.vaciarAlCerrarSesion();

        expect(await ana.carrito(), isEmpty);
        expect(await ana.leerMeta('metodo_pago'), isNull);
        expect(
          (await ana.pedidos()).map((p) => p.estado),
          unorderedEquals([EstadoPedidoLocal.pendiente, EstadoPedidoLocal.enviando]),
        );
        // Lo de Luis no se toca.
        expect(await luis.carrito(), hasLength(1));
        expect(await luis.leerMeta('metodo_pago'), 'x');
        expect(await luis.pedidos(), hasLength(5));
      },
    );

    test(
      '"Borrarlos y salir" borra TODO de esa persona, también los pedidos sin enviar, y nada de los demás',
      () async {
        await sembrarTodo(ana, alcanceAna, 10);
        await sembrarTodo(luis, alcanceLuis, 20);

        await ana.borrarTodo();

        expect(await ana.carrito(), isEmpty);
        expect(await ana.leerMeta('metodo_pago'), isNull);
        expect(await ana.pedidos(), isEmpty);
        expect(await luis.pedidos(), hasLength(5));
        expect(await luis.carrito(), hasLength(1));
      },
    );

    test('los pedidos conservados siguen ahí cuando la misma cuenta vuelve a entrar', () async {
      await sembrarTodo(ana, alcanceAna, 10);
      await ana.vaciarAlCerrarSesion();

      final denuevo = RepositorioCliente(db, alcance: alcanceAna);

      expect(await denuevo.contarSinEnviar(), 2);
      expect((await denuevo.pedidosParaEnviar(DateTime.utc(2027), const Duration(seconds: 120))), hasLength(2));
    });
  });
}
