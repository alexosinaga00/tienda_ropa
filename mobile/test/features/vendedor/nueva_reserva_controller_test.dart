import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/sync/cola_operaciones.dart';
import 'package:mobile/features/vendedor/data/catalogo_local_repository.dart';
import 'package:mobile/features/vendedor/models/cliente_local.dart';
import 'package:mobile/features/vendedor/models/producto_local.dart';
import 'package:mobile/features/vendedor/models/variante_local.dart';
import 'package:mobile/features/vendedor/state/nueva_reserva_controller.dart';
import 'package:mobile/features/vendedor/state/sincronizacion_providers.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';
import '../../helpers/cola_falsa.dart' show operacionDePrueba;
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
  late DateTime hoy;

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
    final local = instanteBase.toLocal();
    hoy = DateTime(local.year, local.month, local.day);
  });

  tearDown(() async {
    await cola.cerrar();
    await db.close();
  });

  DateTime enDias(int dias) => DateTime(hoy.year, hoy.month, hoy.day + dias);

  Future<(ProductoLocal, VarianteLocal)> prenda(int productoId, int varianteId, {int sucursalId = 1}) async {
    final producto = (await catalogo.productoPorId(productoId, sucursalId: sucursalId))!;
    final variantes = await catalogo.variantesDeProducto(productoId, sucursalId: sucursalId);
    return (producto, variantes.firstWhere((v) => v.id == varianteId));
  }

  NuevaReservaController crear([ProviderContainer? en]) {
    final c = en ?? contenedor;
    c.listen(nuevaReservaControllerProvider, (anterior, actual) {});
    return c.read(nuevaReservaControllerProvider.notifier);
  }

  NuevaReservaState estado([ProviderContainer? en]) => (en ?? contenedor).read(nuevaReservaControllerProvider);

  /// Un controlador con todo lo necesario menos lo que cada prueba quiera cambiar: Polera S x[cantidad] en Centro, Ana,
  /// visita mañana de 10:00 a 11:00.
  Future<NuevaReservaController> listo({int cantidad = 1}) async {
    final c = crear();
    final (p, v) = await prenda(10, 100);
    c.elegirSucursal(1);
    c.agregar(v, p, cantidad);
    c.elegirCliente(ana);
    c.elegirFecha(enDias(1));
    c.elegirHoraDesde('10:00');
    c.elegirHoraHasta('11:00');
    return c;
  }

  group('armar la reserva', () {
    test('empieza vacía: sin prendas, cliente, fecha ni horas, y no se puede registrar', () {
      final c = crear();
      expect(c, isNotNull);
      final e = estado();
      expect(e.lineas, isEmpty);
      expect(e.cantidadPrendas, 0);
      expect(e.cliente, isNull);
      expect(e.fechaVisita, isNull);
      expect(e.horaDesde, isNull);
      expect(e.horaHasta, isNull);
      expect(e.observacion, '');
      expect(e.sucursalId, isNull);
      expect(e.registrando, isFalse);
      expect(e.error, isNull);
      expect(e.puedeRegistrar, isFalse);
      expect(e.problema, 'Agrega al menos una prenda.');
    });

    test('"hoy" es el día del reloj en la hora local, sin hora', () {
      crear();
      expect(estado().hoy, hoy);
      expect(estado().hoy.hour, 0);
    });

    test('agregar guarda la prenda con su talla, color y cantidad', () async {
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
      expect(estado().cantidadPrendas, 2);
    });

    test('agregar la misma variante suma a su línea; otra variante es otra línea', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100);
      final (p2, v2) = await prenda(11, 110);
      c.agregar(v, p, 1);
      c.agregar(v, p, 3);
      c.agregar(v2, p2, 2);
      expect(estado().lineas.length, 2);
      expect(estado().lineas.first.cantidad, 4);
      expect(estado().cantidadPrendas, 6);
    });

    test('cambiarCantidad cambia la línea y una cantidad inválida se ignora', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100);
      c.agregar(v, p, 2);
      c.cambiarCantidad(100, 5);
      expect(estado().lineas.single.cantidad, 5);
      c.cambiarCantidad(100, 0);
      c.cambiarCantidad(100, maxCantidadPorLinea + 1);
      expect(estado().lineas.single.cantidad, 5);
    });

    test('quitar saca la línea y deja las demás', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100);
      final (p2, v2) = await prenda(11, 110);
      c.agregar(v, p, 1);
      c.agregar(v2, p2, 1);
      c.quitar(100);
      expect(estado().lineas.map((l) => l.varianteId), [110]);
    });

    test('elegir, cambiar y quitar el cliente', () {
      final c = crear();
      const otro = ClienteLocal(id: 99, servidorId: 700, nombre: 'Rosa');
      c.elegirCliente(ana);
      expect(estado().cliente, ana);
      c.elegirCliente(otro);
      expect(estado().cliente, otro);
      c.quitarCliente();
      expect(estado().cliente, isNull);
    });

    test('elegirFecha guarda solo el día: la hora se descarta', () {
      final c = crear();
      c.elegirFecha(DateTime(hoy.year, hoy.month, hoy.day + 2, 15, 45));
      expect(estado().fechaVisita, enDias(2));
    });

    test('las horas y la observación se guardan tal cual', () {
      final c = crear();
      c.elegirHoraDesde('09:30');
      c.elegirHoraHasta('10:15');
      c.cambiarObservacion('Viene con su hijo');
      expect(estado().horaDesde, '09:30');
      expect(estado().horaHasta, '10:15');
      expect(estado().observacion, 'Viene con su hijo');
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

    test('cambiar de sucursal conserva cliente, fecha y horas', () async {
      final c = await listo();
      c.elegirSucursal(2);
      expect(estado().cliente, ana);
      expect(estado().fechaVisita, enDias(1));
      expect(estado().horaDesde, '10:00');
      expect(estado().horaHasta, '11:00');
    });

    test('editar borra el error anterior', () async {
      final c = crear();
      await c.registrar(); // faltan prendas
      expect(estado().error, isNotNull);
      c.cambiarObservacion('hola');
      expect(estado().error, isNull);
    });
  });

  group('qué falta para poder registrar', () {
    test('con todo en orden no falta nada', () async {
      await listo();
      expect(estado().problema, isNull);
      expect(estado().puedeRegistrar, isTrue);
    });

    test('exige al menos una prenda', () async {
      final c = await listo();
      c.quitar(100);
      expect(estado().problema, 'Agrega al menos una prenda.');
      final r = await c.registrar();
      expect((r as RegistroConError).mensaje, 'Agrega al menos una prenda.');
      expect(cola.reservas, isEmpty);
    });

    test('el cliente es OBLIGATORIO: sin cliente no se registra', () async {
      final c = await listo();
      c.quitarCliente();
      expect(estado().problema, 'Elige el cliente de la reserva.');
      expect(estado().puedeRegistrar, isFalse);
      final r = await c.registrar();
      expect((r as RegistroConError).mensaje, 'Elige el cliente de la reserva.');
      expect(estado().error, 'Elige el cliente de la reserva.');
      expect(cola.reservas, isEmpty);
    });

    test('exige la fecha de la visita', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100);
      c.elegirSucursal(1);
      c.agregar(v, p, 1);
      c.elegirCliente(ana);
      c.elegirHoraDesde('10:00');
      c.elegirHoraHasta('11:00');
      final r = await c.registrar();
      expect((r as RegistroConError).mensaje, 'Elige la fecha de la visita.');
      expect(cola.reservas, isEmpty);
    });

    test('una fecha anterior a hoy se rechaza', () async {
      final c = await listo();
      c.elegirFecha(enDias(-1));
      expect(estado().problema, 'La fecha de la visita no puede ser anterior a hoy.');
      final r = await c.registrar();
      expect((r as RegistroConError).mensaje, 'La fecha de la visita no puede ser anterior a hoy.');
      expect(cola.reservas, isEmpty);
    });

    test('hoy y los días siguientes se aceptan', () async {
      final c = await listo();
      c.elegirFecha(hoy);
      expect(estado().problema, isNull);
      c.elegirFecha(enDias(30));
      expect(estado().problema, isNull);
    });

    test('exige las dos horas', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100);
      c.elegirSucursal(1);
      c.agregar(v, p, 1);
      c.elegirCliente(ana);
      c.elegirFecha(enDias(1));
      expect(estado().problema, 'Elige la hora de inicio y la de fin de la visita.');
      c.elegirHoraDesde('10:00');
      expect(estado().problema, 'Elige la hora de inicio y la de fin de la visita.');
      c.elegirHoraHasta('11:00');
      expect(estado().problema, isNull);
    });

    for (final (desde, hasta) in [('12:00', '10:00'), ('10:00', '10:00'), ('23:59', '00:00')]) {
      test('horas invertidas o iguales ($desde a $hasta) se rechazan', () async {
        final c = await listo();
        c.elegirHoraDesde(desde);
        c.elegirHoraHasta(hasta);
        expect(estado().problema, 'La hora de fin debe ser posterior a la hora de inicio.');
        final r = await c.registrar();
        expect(r, isA<RegistroConError>());
        expect(cola.reservas, isEmpty);
      });
    }

    for (final mala in ['9:00', '25:00', '10:60', 'diez', '10-00', '']) {
      test('el formato "$mala" no es HH:mm y se rechaza', () async {
        final c = await listo();
        c.elegirHoraDesde(mala);
        c.elegirHoraHasta('23:59');
        expect(estado().problema, 'Las horas de la visita deben tener el formato HH:mm.');
        expect(estado().puedeRegistrar, isFalse);
      });
    }

    test('la hora de fin se compara contra la de inicio con dos dígitos (09:00 antes de 10:00)', () async {
      final c = await listo();
      c.elegirHoraDesde('09:00');
      c.elegirHoraHasta('10:00');
      expect(estado().problema, isNull);
    });

    test('una observación de 300 caracteres vale; de 301, no', () async {
      final c = await listo();
      c.cambiarObservacion('a' * maxObservacionReserva);
      expect(estado().problema, isNull);
      c.cambiarObservacion('a' * (maxObservacionReserva + 1));
      expect(estado().problema, 'La observación no puede pasar de 300 caracteres.');
      final r = await c.registrar();
      expect((r as RegistroConError).mensaje, 'La observación no puede pasar de 300 caracteres.');
      expect(cola.reservas, isEmpty);
    });

    test('los espacios de los bordes no cuentan para el límite de la observación', () async {
      final c = await listo();
      c.cambiarObservacion('  ${'a' * maxObservacionReserva}  ');
      expect(estado().problema, isNull);
    });

    test('exige una sucursal', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100);
      c.agregar(v, p, 1);
      c.elegirCliente(ana);
      c.elegirFecha(enDias(1));
      c.elegirHoraDesde('10:00');
      c.elegirHoraHasta('11:00');
      final r = await c.registrar();
      expect((r as RegistroConError).mensaje, 'Elige una sucursal.');
      expect(cola.reservas, isEmpty);
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
      expect(cola.reservas.map((r) => r.operacionId), [GeneradorUuidFijo.idUno, GeneradorUuidFijo.idUno]);
      expect(generador.pedidos, 1);
    });

    test('otro controlador (otra apertura de la pantalla) tiene otro id', () {
      crear();
      final primero = estado().operacionId;
      contenedor.invalidate(nuevaReservaControllerProvider);
      expect(estado().operacionId, isNot(primero));
      expect(estado().operacionId, GeneradorUuidFijo.idDos);
    });

    test('dos contenedores distintos generan ids distintos', () {
      final otro = _contenedor(db, ColaEspia(), GeneradorUuidFijo([GeneradorUuidFijo.idTres]), reloj);
      crear();
      crear(otro);
      expect(estado().operacionId, GeneradorUuidFijo.idUno);
      expect(estado(otro).operacionId, GeneradorUuidFijo.idTres);
    });
  });

  group('registrar', () {
    test('registra y devuelve el id de la operación', () async {
      final c = await listo();
      final r = await c.registrar();
      expect(r, isA<RegistroExitoso>());
      expect((r as RegistroExitoso).operacionId, GeneradorUuidFijo.idUno);
      expect(cola.todas.single.operacionId, GeneradorUuidFijo.idUno);
      expect(estado().registrando, isFalse);
      expect(estado().error, isNull);
    });

    test('la reserva que recibe la cola tiene empresa, usuario, sucursal, fecha del reloj, líneas, cliente y horas', () async {
      final c = await listo(cantidad: 2);
      final (p2, v2) = await prenda(11, 110);
      c.agregar(v2, p2, 1);
      c.elegirHoraDesde('14:30');
      c.elegirHoraHasta('15:45');
      c.elegirFecha(enDias(3));
      c.cambiarObservacion('Viene con su hijo');
      await c.registrar();

      final reserva = cola.reservas.single;
      expect(reserva.operacionId, GeneradorUuidFijo.idUno);
      expect(reserva.empresaId, 1);
      expect(reserva.usuarioId, 7);
      expect(reserva.sucursalId, 1);
      expect(reserva.fechaOperacion, instanteBase);
      expect(reserva.clienteMinimoId, ana.id);
      expect(reserva.fechaVisita, enDias(3));
      expect(reserva.horaDesde, '14:30');
      expect(reserva.horaHasta, '15:45');
      expect(reserva.observacion, 'Viene con su hijo');
      expect(reserva.lineas.map((l) => (l.varianteId, l.cantidad)), [(100, 2), (110, 1)]);
    });

    test('la observación se guarda recortada', () async {
      final c = await listo();
      c.cambiarObservacion('   Probador grande   ');
      await c.registrar();
      expect(cola.reservas.single.observacion, 'Probador grande');
    });

    test('una observación en blanco se registra sin observación', () async {
      final c = await listo();
      c.cambiarObservacion('    ');
      await c.registrar();
      expect(cola.reservas.single.observacion, isNull);
    });

    test('la fecha de la operación es la del reloj al registrar (no la de abrir la pantalla)', () async {
      final c = await listo();
      reloj.avanzar(const Duration(minutes: 7));
      await c.registrar();
      expect(cola.reservas.single.fechaOperacion, instanteBase.add(const Duration(minutes: 7)));
    });

    test('NO sincroniza ni crea una venta: solo guarda la reserva en la cola', () async {
      final c = await listo();
      await c.registrar();
      expect(cola.de('registrarReserva').length, 1);
      expect(cola.de('registrarVenta'), isEmpty);
      expect(cola.de('marcarEnviadas'), isEmpty);
      expect(cola.todas.single.estado.name, 'registrada');
      expect(cola.todas.single.tipo.name, 'reserva');
    });

    test('un ColaError devuelve su mensaje y deja el error en el estado', () async {
      final c = await listo();
      cola.errorAlRegistrar = const ColaError('Ese cliente no está en tus datos. Actualiza tus datos e intenta de nuevo.');
      final r = await c.registrar();
      expect((r as RegistroConError).mensaje, startsWith('Ese cliente no está en tus datos'));
      expect(estado().error, r.mensaje);
      expect(estado().registrando, isFalse);
      expect(cola.todas, isEmpty);
    });

    test('un fallo inesperado de la cola devuelve un mensaje claro, no la excepción', () async {
      final c = await listo();
      cola.errorAlRegistrar = StateError('boom');
      final r = await c.registrar();
      expect((r as RegistroConError).mensaje, textoFalloGuardarReserva);
      expect(estado().error, textoFalloGuardarReserva);
      expect(estado().registrando, isFalse);
    });

    test('tras un error se puede corregir y volver a registrar', () async {
      final c = await listo();
      c.quitarCliente();
      expect(await c.registrar(), isA<RegistroConError>());
      c.elegirCliente(ana);
      expect(estado().error, isNull);
      expect(await c.registrar(), isA<RegistroExitoso>());
      expect(cola.reservas.length, 1);
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
      c.elegirCliente(ana);
      c.elegirFecha(enDias(1));
      c.elegirHoraDesde('10:00');
      c.elegirHoraHasta('11:00');
      final r = await c.registrar();
      expect((r as RegistroConError).mensaje, 'Tu sesión no está disponible. Vuelve a entrar.');
      expect(cola.reservas, isEmpty);
    });

    test('después de registrar, la reserva ya no se puede editar', () async {
      final c = await listo();
      await c.registrar();
      final (p2, v2) = await prenda(11, 110);
      c.agregar(v2, p2, 1);
      c.quitar(100);
      c.quitarCliente();
      c.elegirFecha(enDias(5));
      c.elegirHoraDesde('08:00');
      c.elegirHoraHasta('09:00');
      c.cambiarObservacion('otra');
      c.elegirSucursal(2);
      expect(estado().lineas.map((l) => l.varianteId), [100]);
      expect(estado().cliente, ana);
      expect(estado().fechaVisita, enDias(1));
      expect(estado().horaDesde, '10:00');
      expect(estado().horaHasta, '11:00');
      expect(estado().observacion, '');
      expect(estado().sucursalId, 1);
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
      expect(estado().puedeRegistrar, isFalse);
      cola.puerta!.complete();

      final resultados = await Future.wait([a, b]);
      expect(resultados.every((r) => r is RegistroExitoso), isTrue);
      expect(cola.reservas.length, 1);
      expect(cola.todas.length, 1);
      expect(estado().error, isNull);
    });

    test('mientras se guarda no se puede editar', () async {
      final c = await listo();
      cola.puerta = Completer<void>();
      final pendiente = c.registrar();
      await Future<void>.delayed(const Duration(milliseconds: 60));
      c.cambiarObservacion('tarde');
      c.quitarCliente();
      expect(estado().observacion, '');
      expect(estado().cliente, ana);
      cola.puerta!.complete();
      await pendiente;
    });

    test('un registrar después de guardada devuelve el mismo id sin duplicar ni mostrar error', () async {
      final c = await listo();
      final primero = await c.registrar();
      final segundo = await c.registrar();
      expect((segundo as RegistroExitoso).operacionId, (primero as RegistroExitoso).operacionId);
      expect(cola.reservas.length, 1);
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
      expect(cola.reservas, isEmpty);
      expect(estado().registrando, isFalse);
      expect(estado().error, isNull);
    });

    test('con permitirSinStock registra igual, con la cantidad pedida', () async {
      final c = await listo(cantidad: 6);
      await c.registrar();
      final r = await c.registrar(permitirSinStock: true);
      expect(r, isA<RegistroExitoso>());
      expect(cola.reservas.single.lineas.single.cantidad, 6);
    });

    test('pedir exactamente lo que queda no avisa', () async {
      final c = await listo(cantidad: 5);
      expect(await c.registrar(), isA<RegistroExitoso>());
    });

    test('una variante agotada avisa que no queda ninguna', () async {
      final c = await listo();
      c.quitar(100);
      final (p, v) = await prenda(11, 111); // Camisa Lino M: 0
      c.agregar(v, p, 1);
      final r = await c.registrar();
      expect((r as RegistroConAdvertencias).textos, ['No queda ninguna de Camisa Lino (M, Negro)']);
    });

    test('cuando queda una sola lo dice en singular y cuenta la sucursal elegida', () async {
      final c = crear();
      final (p, v) = await prenda(10, 100, sucursalId: 2); // en Norte queda 1
      c.elegirSucursal(2);
      c.agregar(v, p, 2);
      c.elegirCliente(ana);
      c.elegirFecha(enDias(1));
      c.elegirHoraDesde('10:00');
      c.elegirHoraHasta('11:00');
      final r = await c.registrar();
      expect((r as RegistroConAdvertencias).textos, ['Queda 1 de Polera Básica (S, Negro)']);
    });

    test('los datos que faltan se avisan antes que el stock', () async {
      final c = await listo(cantidad: 6);
      c.quitarCliente();
      final r = await c.registrar();
      expect(r, isA<RegistroConError>());
    });
  });

  test('el contenedor liberado no deja el controlador escribiendo en un estado muerto', () async {
    final c = await listo();
    cola.puerta = Completer<void>();
    final pendiente = c.registrar();
    await Future<void>.delayed(const Duration(milliseconds: 60));
    contenedor.dispose();
    cola.puerta!.complete();
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
