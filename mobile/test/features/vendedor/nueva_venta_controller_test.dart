import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/sync/cola_operaciones.dart';
import 'package:mobile/features/vendedor/data/catalogo_local_repository.dart';
import 'package:mobile/features/vendedor/models/cliente_local.dart';
import 'package:mobile/features/vendedor/models/producto_local.dart';
import 'package:mobile/features/vendedor/models/variante_local.dart';
import 'package:mobile/features/vendedor/state/nueva_venta_controller.dart';
import 'package:mobile/features/vendedor/state/sincronizacion_providers.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';
import '../../helpers/cola_falsa.dart';
import '../../helpers/siembra_operaciones.dart';
import 'apoyo_catalogo_local.dart' show instanteBase, sembrarEscenarioBasico;
import 'apoyo_nueva_operacion.dart';
import 'apoyo_operaciones.dart';

void main() {
  late Database db;
  late ColaEspia cola;
  late GeneradorUuidFijo generador;
  late RelojDePrueba reloj;
  late ProviderContainer contenedor;
  late CatalogoLocalRepository catalogo;
  late ClienteLocal ana;

  setUp(() async {
    db = await abrirBaseDePrueba();
    await sembrarEscenarioBasico(db);
    final anaId = await sembrarClienteServidor(db, servidorId: 501, nombre: 'Ana', apellido: 'Pérez', ciNit: '1234567');
    ana = ClienteLocal(id: anaId, servidorId: 501, nombre: 'Ana', apellido: 'Pérez', ciNit: '1234567');
    cola = ColaEspia();
    generador = GeneradorUuidFijo();
    reloj = RelojDePrueba(instanteBase);
    catalogo = CatalogoLocalSqlite(db, empresaId: 1);
    contenedor = _contenedor(db, cola, generador, reloj);
  });

  tearDown(() async {
    await cola.cerrar();
    await db.close();
  });

  Future<(ProductoLocal, VarianteLocal)> prenda(int productoId, int varianteId, {int sucursalId = 1}) async {
    final producto = (await catalogo.productoPorId(productoId, sucursalId: sucursalId))!;
    final variantes = await catalogo.variantesDeProducto(productoId, sucursalId: sucursalId);
    return (producto, variantes.firstWhere((v) => v.id == varianteId));
  }

  NuevaVentaController crear([ProviderContainer? en]) {
    final c = en ?? contenedor;
    c.listen(nuevaVentaControllerProvider, (anterior, actual) {});
    return c.read(nuevaVentaControllerProvider.notifier);
  }

  NuevaVentaState estado([ProviderContainer? en]) => (en ?? contenedor).read(nuevaVentaControllerProvider);

  /// Un controlador listo para registrar: Polera S x1, efectivo recibido, sucursal Centro.
  Future<NuevaVentaController> listo({int cantidad = 1}) async {
    final c = crear();
    final (p, v) = await prenda(10, 100);
    c.elegirSucursal(1);
    c.agregar(v, p, cantidad);
    c.confirmarEfectivo(true);
    return c;
  }

  group('armar la venta', () {
    test('empieza vacía, sin cliente y con el efectivo sin confirmar', () {
      final c = crear();
      expect(c, isNotNull);
      final e = estado();
      expect(e.lineas, isEmpty);
      expect(e.totalCentavos, 0);
      expect(e.cliente, isNull);
      expect(e.efectivoConfirmado, isFalse);
      expect(e.registrando, isFalse);
      expect(e.error, isNull);
      expect(e.sucursalId, isNull);
      expect(e.puedeRegistrar, isFalse);
    });

    test('agregar guarda la prenda con su talla, color, foto y precio', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100);
      c.agregar(v, p, 2);

      final l = estado().lineas.single;
      expect(l.varianteId, 100);
      expect(l.productoId, 10);
      expect(l.nombre, 'Polera Básica');
      expect(l.talla, 'S');
      expect(l.color, 'Negro');
      expect(l.cantidad, 2);
      expect(l.precioUnitarioCentavos, 7500);
      expect(l.descuentoUnitarioCentavos, 0);
      expect(l.subtotalCentavos, 15000);
    });

    test('agregar la misma variante suma a su línea (no crea otra)', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100);
      c.agregar(v, p, 1);
      c.agregar(v, p, 3);
      expect(estado().lineas.length, 1);
      expect(estado().lineas.single.cantidad, 4);
    });

    test('variantes distintas son líneas distintas y el total las suma en centavos', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100);
      final (p2, v2) = await prenda(11, 110);
      c.agregar(v, p, 2); // 2 x 75,00
      c.agregar(v2, p2, 1); // 1 x 50,00
      expect(estado().lineas.length, 2);
      expect(estado().totalCentavos, 20000);
      expect(estado().cantidadPrendas, 3);
    });

    test('el descuento de la variante se resta del precio en el total', () async {
      await db.update('variante', {'descuento_centavos': 500}, where: 'id = 100');
      final c = crear();
      final (p, v) = await prenda(10, 100);
      c.agregar(v, p, 2);
      expect(estado().lineas.single.descuentoUnitarioCentavos, 500);
      expect(estado().totalCentavos, 14000); // (7500 - 500) x 2
    });

    test('el precio queda CONGELADO aunque el catálogo cambie después (D17)', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100);
      c.agregar(v, p, 1);

      await db.update('variante', {'precio_centavos': 9900}, where: 'id = 100');
      final (_, vNueva) = await prenda(10, 100);
      expect(vNueva.precioCentavos, 9900);
      c.agregar(vNueva, p, 1);

      final l = estado().lineas.single;
      expect(l.cantidad, 2);
      expect(l.precioUnitarioCentavos, 7500); // conserva el precio con que entró
      expect(estado().totalCentavos, 15000);
    });

    test('una variante nueva toma el precio local de ese momento', () async {
      await db.update('variante', {'precio_centavos': 8800}, where: 'id = 101');
      final c = crear();
      final (p, v) = await prenda(10, 101);
      c.agregar(v, p, 1);
      expect(estado().lineas.single.precioUnitarioCentavos, 8800);
    });

    test('cambiarCantidad actualiza la línea y el total', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100);
      c.agregar(v, p, 1);
      c.cambiarCantidad(100, 5);
      expect(estado().lineas.single.cantidad, 5);
      expect(estado().totalCentavos, 37500);
    });

    test('una cantidad menor que 1 o mayor que el tope se ignora', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100);
      c.agregar(v, p, 3);
      c.cambiarCantidad(100, 0);
      c.cambiarCantidad(100, -2);
      c.cambiarCantidad(100, maxCantidadPorLinea + 1);
      expect(estado().lineas.single.cantidad, 3);
      c.agregar(v, p, 0); // agregar cero tampoco hace nada
      expect(estado().lineas.single.cantidad, 3);
    });

    test('quitar saca la línea y deja las demás', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100);
      final (p2, v2) = await prenda(11, 110);
      c.agregar(v, p, 1);
      c.agregar(v2, p2, 1);
      c.quitar(100);
      expect(estado().lineas.map((l) => l.varianteId), [110]);
      c.quitar(999); // una que no está: no pasa nada
      expect(estado().lineas.length, 1);
    });

    test('elegir y quitar el cliente', () {
      final c = crear();
      c.elegirCliente(ana);
      expect(estado().cliente, ana);
      c.quitarCliente();
      expect(estado().cliente, isNull);
    });

    test('confirmar el efectivo se puede marcar y desmarcar', () {
      final c = crear();
      c.confirmarEfectivo(true);
      expect(estado().efectivoConfirmado, isTrue);
      c.confirmarEfectivo(false);
      expect(estado().efectivoConfirmado, isFalse);
    });

    test('cambiar de sucursal vacía las prendas; elegir la misma no', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100);
      c.elegirSucursal(1);
      c.agregar(v, p, 2);

      c.elegirSucursal(1);
      expect(estado().lineas.length, 1);

      c.elegirSucursal(2);
      expect(estado().sucursalId, 2);
      expect(estado().lineas, isEmpty);
    });

    test('editar borra el error anterior', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100);
      c.agregar(v, p, 1);
      await c.registrar(); // falta el efectivo
      expect(estado().error, isNotNull);
      c.confirmarEfectivo(true);
      expect(estado().error, isNull);
    });
  });

  group('el id de la operación', () {
    test('se genera al crear el controlador, no al registrar', () {
      expect(generador.pedidos, 0);
      crear();
      expect(generador.pedidos, 1);
      expect(estado().operacionId, GeneradorUuidFijo.idUno);
    });

    test('es el mismo en cada intento fallido y al reintentar', () async {
      final c = await listo();
      cola.errorAlRegistrar = const ColaError('La sucursal no está disponible en este teléfono.');
      final r1 = await c.registrar();
      expect(r1, isA<RegistroConError>());
      expect(estado().operacionId, GeneradorUuidFijo.idUno);

      final r2 = await c.registrar();
      expect(r2, isA<RegistroExitoso>());
      expect(cola.ventas.map((v) => v.operacionId), [GeneradorUuidFijo.idUno, GeneradorUuidFijo.idUno]);
      expect(generador.pedidos, 1);
    });

    test('otro controlador (otra apertura de la pantalla) tiene otro id', () {
      crear();
      final primero = estado().operacionId;
      contenedor.invalidate(nuevaVentaControllerProvider);
      expect(estado().operacionId, isNot(primero));
      expect(estado().operacionId, GeneradorUuidFijo.idDos);
    });
  });

  group('registrar', () {
    test('exige al menos una prenda', () async {
      final c = crear();
      c.confirmarEfectivo(true);
      final r = await c.registrar();
      expect(r, isA<RegistroConError>());
      expect((r as RegistroConError).mensaje, 'Agrega al menos una prenda.');
      expect(cola.ventas, isEmpty);
      expect(estado().error, 'Agrega al menos una prenda.');
    });

    test('exige confirmar el efectivo', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100);
      c.elegirSucursal(1);
      c.agregar(v, p, 1);
      final r = await c.registrar();
      expect((r as RegistroConError).mensaje, 'Confirma que recibiste el efectivo.');
      expect(cola.ventas, isEmpty);
    });

    test('exige una sucursal', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100);
      c.agregar(v, p, 1);
      c.confirmarEfectivo(true);
      final r = await c.registrar();
      expect((r as RegistroConError).mensaje, 'Elige una sucursal.');
      expect(cola.ventas, isEmpty);
    });

    test('registra y devuelve el id de la operación', () async {
      final c = await listo();
      final r = await c.registrar();
      expect(r, isA<RegistroExitoso>());
      expect((r as RegistroExitoso).operacionId, GeneradorUuidFijo.idUno);
      expect(cola.todas.single.operacionId, GeneradorUuidFijo.idUno);
      expect(estado().registrando, isFalse);
      expect(estado().error, isNull);
    });

    test('la venta que recibe la cola tiene empresa, usuario, sucursal, fecha del reloj, líneas y cliente', () async {
      final c = await listo(cantidad: 2);
      final (p2, v2) = await prenda(11, 110);
      c.agregar(v2, p2, 1);
      c.elegirCliente(ana);
      await c.registrar();

      final venta = cola.ventas.single;
      expect(venta.operacionId, GeneradorUuidFijo.idUno);
      expect(venta.empresaId, 1);
      expect(venta.usuarioId, 7);
      expect(venta.sucursalId, 1);
      expect(venta.fechaOperacion, instanteBase);
      expect(venta.clienteMinimoId, ana.id);
      expect(venta.efectivoConfirmado, isTrue);
      expect(venta.lineas.map((l) => (l.varianteId, l.cantidad, l.precioUnitarioCentavos, l.descuentoUnitarioCentavos)), [
        (100, 2, 7500, 0),
        (110, 1, 5000, 0),
      ]);
      expect(venta.totalCentavos, 20000);
    });

    test('sin cliente la venta va sin cliente', () async {
      final c = await listo();
      await c.registrar();
      expect(cola.ventas.single.clienteMinimoId, isNull);
    });

    test('la fecha de la operación es la del reloj al registrar (no la de abrir la pantalla)', () async {
      final c = await listo();
      reloj.avanzar(const Duration(minutes: 7));
      await c.registrar();
      expect(cola.ventas.single.fechaOperacion, instanteBase.add(const Duration(minutes: 7)));
    });

    test('NO sincroniza: solo guarda en la cola', () async {
      final c = await listo();
      await c.registrar();
      expect(cola.de('registrarVenta').length, 1);
      expect(cola.de('marcarEnviadas'), isEmpty);
      expect(cola.todas.single.estado.name, 'registrada');
    });

    test('un ColaError devuelve su mensaje y deja el error en el estado', () async {
      final c = await listo();
      cola.errorAlRegistrar = const ColaError('Una de las prendas ya no está disponible. Actualiza tus datos e intenta de nuevo.');
      final r = await c.registrar();
      expect((r as RegistroConError).mensaje, startsWith('Una de las prendas ya no está disponible'));
      expect(estado().error, r.mensaje);
      expect(estado().registrando, isFalse);
      expect(cola.todas, isEmpty);
    });

    test('un fallo inesperado de la cola devuelve un mensaje claro, no la excepción', () async {
      final c = await listo();
      cola.errorAlRegistrar = StateError('boom');
      final r = await c.registrar();
      expect((r as RegistroConError).mensaje, textoFalloGuardarVenta);
      expect(estado().error, textoFalloGuardarVenta);
    });

    test('sin sesión no registra y avisa', () async {
      final sinSesionContenedor = contenedorLocal(
        db,
        reloj: reloj,
        extra: [colaOperacionesProvider.overrideWith((ref) async => cola), generadorUuidProvider.overrideWithValue(generador)],
      );
      final c = crear(sinSesionContenedor);
      final (p, v) = await prenda(10, 100);
      c.elegirSucursal(1);
      c.agregar(v, p, 1);
      c.confirmarEfectivo(true);
      final r = await c.registrar();
      expect((r as RegistroConError).mensaje, 'Tu sesión no está disponible. Vuelve a entrar.');
      expect(cola.ventas, isEmpty);
    });

    test('después de registrar, la venta ya no se puede editar', () async {
      final c = await listo();
      await c.registrar();
      final (p2, v2) = await prenda(11, 110);
      c.agregar(v2, p2, 1);
      c.quitar(100);
      c.confirmarEfectivo(false);
      expect(estado().lineas.map((l) => l.varianteId), [100]);
      expect(estado().efectivoConfirmado, isTrue);
    });
  });

  group('doble toque', () {
    test('dos registrar seguidos (el primero aún en curso) guardan UNA vez y comparten el resultado', () async {
      final c = await listo();
      cola.puerta = Completer<void>();
      final a = c.registrar();
      final b = c.registrar();
      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(estado().registrando, isTrue);
      cola.puerta!.complete();

      final resultados = await Future.wait([a, b]);
      expect(resultados.every((r) => r is RegistroExitoso), isTrue);
      expect(cola.ventas.length, 1);
      expect(cola.todas.length, 1);
      expect(estado().error, isNull);
    });

    test('un registrar después de guardada devuelve el mismo id sin duplicar ni mostrar error', () async {
      final c = await listo();
      final primero = await c.registrar();
      final segundo = await c.registrar();
      expect((segundo as RegistroExitoso).operacionId, (primero as RegistroExitoso).operacionId);
      expect(cola.ventas.length, 1);
      expect(estado().error, isNull);
    });

    test('si la cola ya tenía ese id (el primer intento sí llegó), cuenta como registrada y no como error', () async {
      final c = await listo();
      cola.sembrar(operacionDePrueba(GeneradorUuidFijo.idUno));
      final r = await c.registrar();
      expect(r, isA<RegistroExitoso>());
      expect(estado().error, isNull);
      expect(cola.todas.length, 1);
    });
  });

  group('aviso de stock', () {
    test('si una línea pide más de lo que se estima, avisa SIN registrar', () async {
      final c = await listo(cantidad: 6); // Polera S: quedan 5
      final r = await c.registrar();
      expect(r, isA<RegistroConAdvertencias>());
      expect((r as RegistroConAdvertencias).textos, ['Quedan 5 de Polera Básica (S, Negro)']);
      expect(cola.ventas, isEmpty);
      expect(estado().registrando, isFalse);
      expect(estado().error, isNull);
    });

    test('con permitirSinStock registra igual', () async {
      final c = await listo(cantidad: 6);
      await c.registrar();
      final r = await c.registrar(permitirSinStock: true);
      expect(r, isA<RegistroExitoso>());
      expect(cola.ventas.single.lineas.single.cantidad, 6);
    });

    test('pedir exactamente lo que queda no avisa', () async {
      final c = await listo(cantidad: 5);
      expect(await c.registrar(), isA<RegistroExitoso>());
    });

    test('una variante agotada avisa que no queda ninguna', () async {
      final c = crear();
      final (p, v) = await prenda(11, 111); // Camisa Lino M: 0
      c.elegirSucursal(1);
      c.agregar(v, p, 1);
      c.confirmarEfectivo(true);
      final r = await c.registrar();
      expect((r as RegistroConAdvertencias).textos, ['No queda ninguna de Camisa Lino (M, Negro)']);
    });

    test('cuando queda una sola lo dice en singular', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100, sucursalId: 2); // en Norte queda 1
      c.elegirSucursal(2);
      c.agregar(v, p, 2);
      c.confirmarEfectivo(true);
      final r = await c.registrar();
      expect((r as RegistroConAdvertencias).textos, ['Queda 1 de Polera Básica (S, Negro)']);
    });

    test('lista todas las líneas que se pasan, en orden, y no las que alcanzan', () async {
      final c = await listo(cantidad: 1); // Polera S x1: alcanza
      final (p2, v2) = await prenda(11, 110);
      final (p3, v3) = await prenda(11, 111);
      c.agregar(v2, p2, 3); // quedan 2
      c.agregar(v3, p3, 1); // quedan 0
      final r = await c.registrar();
      expect((r as RegistroConAdvertencias).textos, [
        'Quedan 2 de Camisa Lino (S, Negro)',
        'No queda ninguna de Camisa Lino (M, Negro)',
      ]);
    });

    test('la existencia que cuenta es la de la sucursal elegida', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100, sucursalId: 2);
      c.elegirSucursal(2);
      c.agregar(v, p, 1); // en Norte queda 1: alcanza
      c.confirmarEfectivo(true);
      expect(await c.registrar(), isA<RegistroExitoso>());
    });
  });

  test('el contenedor liberado no deja el controlador escribiendo en un estado muerto', () async {
    final c = await listo();
    cola.puerta = Completer<void>();
    final pendiente = c.registrar();
    await Future<void>.delayed(const Duration(milliseconds: 60));
    contenedor.dispose();
    cola.puerta!.complete();
    // No lanza: el resultado llega y listo.
    expect(await pendiente, isA<ResultadoRegistro>());
  });
}

ProviderContainer _contenedor(Database db, ColaEspia cola, GeneradorUuidFijo generador, RelojDePrueba reloj) {
  return contenedorLocal(
    db,
    auth: sesionDe(personalDe()),
    reloj: reloj,
    extra: [colaOperacionesProvider.overrideWith((ref) async => cola), generadorUuidProvider.overrideWithValue(generador)],
  );
}
