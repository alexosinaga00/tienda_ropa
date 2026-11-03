import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/sync/cola_operaciones.dart';
import 'package:mobile/core/sync/motor_sincronizacion.dart';
import 'package:mobile/core/sync/operacion_pendiente.dart';
import 'package:mobile/core/widgets/indicador_conexion.dart';
import 'package:mobile/features/vendedor/presentation/componentes_operacion.dart';
import 'package:mobile/features/vendedor/presentation/nueva_reserva_screen.dart';
import 'package:mobile/features/vendedor/state/nueva_reserva_controller.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'apoyo_catalogo_local.dart';
import 'apoyo_nueva_operacion.dart';
import 'apoyo_pantallas_sync.dart' show textosConVoseo;

const _ruta = '/vendedor/reserva/nueva';

void main() {
  late int anaId;
  late int luisId;

  /// El escenario de siempre más dos clientes: Ana (la conoce el servidor) y Luis (solo existe en el teléfono).
  Future<Database> baseConClientes(WidgetTester tester) {
    return abrirBaseSembrada(
      tester,
      siembra: (db) async {
        await sembrarEscenarioBasico(db);
        anaId = await sembrarClienteServidor(db, servidorId: 501, nombre: 'Ana', apellido: 'Pérez', ciNit: '1234567');
        luisId = await db.insert('cliente_minimo', {
          'empresa_id': 1,
          'servidor_id': null,
          'nombre': 'Luis',
          'apellido': 'Solo',
          'creado_en': '2026-10-31T09:00:00Z',
        });
      },
    );
  }

  Future<EscenarioNuevaOperacion> abrir(
    WidgetTester tester, {
    ColaEspia? cola,
    BloqueoSync? bloqueo,
    bool enLinea = true,
  }) async {
    final db = await baseConClientes(tester);
    return abrirNuevaOperacion(tester, db: db, ruta: _ruta, cola: cola, bloqueo: bloqueo, enLinea: enLinea);
  }

  Finder boton(String clave) => find.byKey(Key(clave));
  Finder botonRegistrar() => boton('boton_registrar_reserva');
  bool registrarHabilitado(WidgetTester tester) => tester.widget<ElevatedButton>(botonRegistrar()).onPressed != null;
  String? ayuda(WidgetTester tester) =>
      find.byKey(const Key('ayuda_registro')).evaluate().isEmpty ? null : tester.widget<Text>(find.byKey(const Key('ayuda_registro'))).data;

  Future<void> agregarPolera(WidgetTester tester, {int cantidad = 1}) async {
    await tester.tap(boton('boton_agregar_prenda'));
    await esperar(tester);
    await tester.tap(find.byKey(const Key('prenda_10')));
    await esperar(tester);
    for (var i = 1; i < cantidad; i++) {
      await tester.tap(find.byKey(const Key('selector_mas')));
      await tester.pump();
    }
    await tester.tap(find.byKey(const Key('boton_agregar')));
    await esperar(tester);
  }

  Future<void> elegirAna(WidgetTester tester) async {
    await tester.tap(boton('boton_elegir_cliente'));
    await esperar(tester);
    await tester.tap(find.byKey(Key('cliente_$anaId')));
    await esperar(tester);
  }

  Future<void> elegirHoy(WidgetTester tester) async {
    await tester.tap(boton('boton_fecha'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
  }

  /// Abre el selector de hora y acepta la hora que propone (10:00 para el inicio y una hora después para el fin).
  Future<void> aceptarHoraPropuesta(WidgetTester tester, String clave) async {
    await tester.tap(boton(clave));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
  }

  /// Abre el selector de hora, pasa al modo de teclado y escribe [hora]:[minuto].
  Future<void> escribirHora(WidgetTester tester, String clave, String hora, String minuto) async {
    await tester.tap(boton(clave));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Switch to text input mode'));
    await tester.pumpAndSettle();
    final campos = find.descendant(of: find.byType(Dialog), matching: find.byType(TextField));
    await tester.enterText(campos.at(0), hora);
    await tester.enterText(campos.at(1), minuto);
    await tester.pump();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
  }

  /// Cliente, prenda, fecha de hoy y la visita de 10:00 a 11:00.
  Future<void> llenarTodo(WidgetTester tester, {int cantidad = 1}) async {
    await agregarPolera(tester, cantidad: cantidad);
    await elegirAna(tester);
    await elegirHoy(tester);
    await aceptarHoraPropuesta(tester, 'boton_hora_desde');
    await aceptarHoraPropuesta(tester, 'boton_hora_hasta');
  }

  /// El router de prueba muestra "RESULTADO id nuevo=1" en la ruta del resultado (un push no cambia la URL del router).
  void abrioElResultado() {
    expect(find.text('RESULTADO ${GeneradorUuidFijo.idUno} nuevo=1'), findsOneWidget);
    expect(find.text('Registrar reserva'), findsNothing);
  }

  void sigueEnElFormulario() {
    expect(find.text('Registrar reserva'), findsOneWidget);
    expect(find.textContaining('RESULTADO'), findsNothing);
  }

  DateTime hoyLocal(EscenarioNuevaOperacion e) {
    final l = e.reloj.ahora().toLocal();
    return DateTime(l.year, l.month, l.day);
  }

  group('la pantalla', () {
    testWidgets('muestra el cliente obligatorio, las prendas, la visita y los avisos', (tester) async {
      await abrir(tester);

      expect(find.text('Nueva reserva'), findsOneWidget);
      expect(find.text('Sucursal'), findsOneWidget);
      expect(find.text('Cliente (obligatorio)'), findsOneWidget);
      expect(find.text('Prendas'), findsOneWidget);
      expect(find.text('Visita'), findsOneWidget);
      expect(find.text('Elegir fecha de la visita'), findsOneWidget);
      expect(find.text('Desde'), findsOneWidget);
      expect(find.text('Hasta'), findsOneWidget);
      expect(find.text('Observación (opcional)'), findsOneWidget);
      expect(find.text('Centro'), findsOneWidget);
      expect(find.text('Registrar reserva'), findsOneWidget);
      expect(find.text('0 prendas'), findsOneWidget);
    });

    testWidgets('avisa que el horario de la sucursal lo valida el servidor', (tester) async {
      await abrir(tester);
      expect(find.byKey(const Key('aviso_horario')), findsOneWidget);
      expect(find.text('El horario de la sucursal lo valida el servidor al sincronizar.'), findsOneWidget);
      expect(find.text(textoAyudaGuardado), findsOneWidget);
    });

    testWidgets('genera el id de la operación AL ABRIR, no al registrar', (tester) async {
      final e = await abrir(tester);
      expect(e.generador.pedidos, 1);
      expect(e.contenedor.read(nuevaReservaControllerProvider).operacionId, GeneradorUuidFijo.idUno);
      expect(e.cola.reservas, isEmpty);
    });

    testWidgets('una reserva no muestra precios ni totales', (tester) async {
      await abrir(tester);
      await agregarPolera(tester, cantidad: 2);
      expect(find.byKey(const Key('linea_100')), findsOneWidget);
      expect(find.textContaining('c/u'), findsNothing);
      expect(find.textContaining('Subtotal'), findsNothing);
      expect(find.textContaining('Total'), findsNothing);
    });

    testWidgets('el resumen cuenta las prendas en singular y plural', (tester) async {
      await abrir(tester);
      await agregarPolera(tester);
      expect(find.text('1 prenda'), findsOneWidget);
      await tester.tap(find.byKey(const Key('cantidad_mas_100')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('cantidad_mas_100')));
      await tester.pump();
      expect(find.text('3 prendas'), findsOneWidget);
    });

    testWidgets('ningún texto usa voseo', (tester) async {
      await abrir(tester);
      await llenarTodo(tester);
      expect(textosConVoseo(tester), isEmpty);
    });

    testWidgets('los botones principales miden al menos 48 de alto y de ancho', (tester) async {
      await abrir(tester);
      for (final clave in ['boton_agregar_prenda', 'boton_fecha', 'boton_hora_desde', 'boton_hora_hasta', 'boton_registrar_reserva']) {
        final tamano = tester.getSize(boton(clave));
        expect(tamano.height, greaterThanOrEqualTo(48), reason: clave);
        expect(tamano.width, greaterThanOrEqualTo(48), reason: clave);
      }
      expect(tester.getSize(boton('boton_elegir_cliente')).height, greaterThanOrEqualTo(48));
    });
  });

  group('el cliente', () {
    testWidgets('el selector ofrece solo clientes que el servidor conoce', (tester) async {
      await abrir(tester);
      await tester.tap(boton('boton_elegir_cliente'));
      await esperar(tester);

      expect(find.text('Elige un cliente'), findsOneWidget);
      expect(find.byKey(Key('cliente_$anaId')), findsOneWidget);
      expect(find.byKey(Key('cliente_$luisId')), findsNothing);
    });

    testWidgets('al elegirlo se muestra su nombre y su CI/NIT', (tester) async {
      await abrir(tester);
      await elegirAna(tester);

      expect(find.byKey(const Key('cliente_elegido')), findsOneWidget);
      expect(find.text('Ana Pérez'), findsOneWidget);
      expect(find.text('CI/NIT: 1234567'), findsOneWidget);
      expect(boton('boton_elegir_cliente'), findsNothing);
    });

    testWidgets('"Cambiar" vuelve a abrir el selector', (tester) async {
      await abrir(tester);
      await elegirAna(tester);
      await tester.tap(boton('boton_cambiar_cliente'));
      await esperar(tester);
      expect(find.text('Elige un cliente'), findsOneWidget);
    });

    testWidgets('cerrar el selector sin elegir deja la reserva sin cliente', (tester) async {
      await abrir(tester);
      await tester.tap(boton('boton_elegir_cliente'));
      await esperar(tester);
      await tester.tap(find.byTooltip('Cerrar'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('cliente_elegido')), findsNothing);
      expect(boton('boton_elegir_cliente'), findsOneWidget);
    });
  });

  group('la fecha y las horas', () {
    testWidgets('el selector de fecha no deja elegir un día anterior a hoy', (tester) async {
      final e = await abrir(tester);
      await tester.tap(boton('boton_fecha'));
      await tester.pumpAndSettle();

      final calendario = tester.widget<CalendarDatePicker>(find.byType(CalendarDatePicker));
      expect(calendario.firstDate, hoyLocal(e));
      expect(calendario.initialDate, hoyLocal(e));
    });

    testWidgets('elegir la fecha la muestra en el botón', (tester) async {
      final e = await abrir(tester);
      await elegirHoy(tester);

      final hoy = hoyLocal(e);
      expect(e.contenedor.read(nuevaReservaControllerProvider).fechaVisita, hoy);
      expect(find.text('Fecha: ${fechaVisitaLegible(hoy)}'), findsOneWidget);
    });

    testWidgets('se puede elegir un día de otro mes', (tester) async {
      final e = await abrir(tester);
      await tester.tap(boton('boton_fecha'));
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('Next month'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('15'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('OK'));
      await tester.pumpAndSettle();

      final hoy = hoyLocal(e);
      final elegida = e.contenedor.read(nuevaReservaControllerProvider).fechaVisita!;
      expect(elegida, DateTime(hoy.year, hoy.month + 1, 15));
    });

    testWidgets('cancelar el selector de fecha no cambia nada', (tester) async {
      final e = await abrir(tester);
      await tester.tap(boton('boton_fecha'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();

      expect(e.contenedor.read(nuevaReservaControllerProvider).fechaVisita, isNull);
      expect(find.text('Elegir fecha de la visita'), findsOneWidget);
    });

    testWidgets('el selector de hora propone 10:00 de inicio y una hora después de fin, en formato de 24 horas', (tester) async {
      final e = await abrir(tester);
      await aceptarHoraPropuesta(tester, 'boton_hora_desde');
      await aceptarHoraPropuesta(tester, 'boton_hora_hasta');

      final estado = e.contenedor.read(nuevaReservaControllerProvider);
      expect(estado.horaDesde, '10:00');
      expect(estado.horaHasta, '11:00');
      expect(find.text('Desde 10:00'), findsOneWidget);
      expect(find.text('Hasta 11:00'), findsOneWidget);
    });

    testWidgets('una hora escrita con el teclado se guarda como HH:mm', (tester) async {
      final e = await abrir(tester);
      await escribirHora(tester, 'boton_hora_desde', '09', '05');
      expect(e.contenedor.read(nuevaReservaControllerProvider).horaDesde, '09:05');
      expect(find.text('Desde 09:05'), findsOneWidget);
    });

    testWidgets('si el fin no es posterior al inicio se avisa y no se puede registrar', (tester) async {
      final e = await abrir(tester);
      await llenarTodo(tester);
      expect(registrarHabilitado(tester), isTrue);
      expect(find.byKey(const Key('error_horas')), findsNothing);

      await escribirHora(tester, 'boton_hora_hasta', '09', '00');

      expect(e.contenedor.read(nuevaReservaControllerProvider).horaHasta, '09:00');
      expect(find.byKey(const Key('error_horas')), findsOneWidget);
      expect(find.text('La hora de fin debe ser posterior a la hora de inicio.'), findsWidgets);
      expect(registrarHabilitado(tester), isFalse);
    });

    testWidgets('horas iguales también se avisan', (tester) async {
      await abrir(tester);
      await aceptarHoraPropuesta(tester, 'boton_hora_desde'); // 10:00
      await escribirHora(tester, 'boton_hora_hasta', '10', '00');
      expect(find.byKey(const Key('error_horas')), findsOneWidget);
    });
  });

  group('la observación', () {
    testWidgets('se guarda en la reserva', (tester) async {
      final e = await abrir(tester);
      await tester.enterText(find.byKey(const Key('campo_observacion')), 'Viene con su hijo');
      await tester.pump();
      expect(e.contenedor.read(nuevaReservaControllerProvider).observacion, 'Viene con su hijo');
    });

    testWidgets('el campo no deja pasar de 300 caracteres', (tester) async {
      final e = await abrir(tester);
      await tester.enterText(find.byKey(const Key('campo_observacion')), 'a' * 350);
      await tester.pump();
      expect(e.contenedor.read(nuevaReservaControllerProvider).observacion.length, maxObservacionReserva);
      expect(find.text('300/300'), findsOneWidget);
    });
  });

  group('cuándo se puede registrar', () {
    testWidgets('el botón está deshabilitado hasta tener cliente, prenda, fecha y las dos horas', (tester) async {
      await abrir(tester);
      expect(registrarHabilitado(tester), isFalse);
      expect(ayuda(tester), 'Agrega al menos una prenda.');

      await agregarPolera(tester);
      expect(registrarHabilitado(tester), isFalse);
      expect(ayuda(tester), 'Elige el cliente de la reserva.');

      await elegirAna(tester);
      expect(registrarHabilitado(tester), isFalse);
      expect(ayuda(tester), 'Elige la fecha de la visita.');

      await elegirHoy(tester);
      expect(registrarHabilitado(tester), isFalse);
      expect(ayuda(tester), 'Elige la hora de inicio y la de fin de la visita.');

      await aceptarHoraPropuesta(tester, 'boton_hora_desde');
      expect(registrarHabilitado(tester), isFalse);

      await aceptarHoraPropuesta(tester, 'boton_hora_hasta');
      expect(registrarHabilitado(tester), isTrue);
      expect(ayuda(tester), isNull);
    });

    testWidgets('quitar la única prenda vuelve a deshabilitar el botón', (tester) async {
      await abrir(tester);
      await llenarTodo(tester);
      expect(registrarHabilitado(tester), isTrue);

      await tester.tap(find.byKey(const Key('quitar_100')));
      await tester.pump();
      expect(registrarHabilitado(tester), isFalse);
      expect(find.text('Todavía no agregaste prendas.'), findsOneWidget);
    });
  });

  group('registrar', () {
    testWidgets('flujo completo: guarda la reserva en la cola y abre su resultado', (tester) async {
      final e = await abrir(tester);
      await llenarTodo(tester, cantidad: 2);

      await tester.tap(botonRegistrar());
      await esperar(tester);

      final reserva = e.cola.reservas.single;
      expect(reserva.operacionId, GeneradorUuidFijo.idUno);
      expect(reserva.empresaId, 1);
      expect(reserva.usuarioId, 7);
      expect(reserva.sucursalId, 1);
      expect(reserva.clienteMinimoId, anaId);
      expect(reserva.fechaVisita, hoyLocal(e));
      expect(reserva.horaDesde, '10:00');
      expect(reserva.horaHasta, '11:00');
      expect(reserva.observacion, isNull);
      expect(reserva.lineas.map((l) => (l.varianteId, l.cantidad)), [(100, 2)]);

      abrioElResultado();
      expect(find.text('RESULTADO ${GeneradorUuidFijo.idUno} nuevo=1'), findsOneWidget);
    });

    testWidgets('al navegar reemplaza la pantalla: volver no regresa al formulario', (tester) async {
      final e = await abrir(tester);
      await llenarTodo(tester);
      await tester.tap(botonRegistrar());
      await esperar(tester);

      e.router!.pop();
      await tester.pumpAndSettle();
      expect(find.text('PANTALLA INICIO'), findsOneWidget);
      expect(find.text('Nueva reserva'), findsNothing);
    });

    testWidgets('lleva la observación escrita', (tester) async {
      final e = await abrir(tester);
      await llenarTodo(tester);
      await tester.enterText(find.byKey(const Key('campo_observacion')), '  Probador grande  ');
      await tester.pump();
      await tester.tap(botonRegistrar());
      await esperar(tester);
      expect(e.cola.reservas.single.observacion, 'Probador grande');
    });

    testWidgets('NO sincroniza: solo guarda la operación como registrada', (tester) async {
      final e = await abrir(tester);
      await llenarTodo(tester);
      await tester.tap(botonRegistrar());
      await esperar(tester);

      expect(e.cola.de('registrarReserva').length, 1);
      expect(e.cola.de('marcarEnviadas'), isEmpty);
      expect(e.cola.todas.single.estado, EstadoOperacion.registrada);
    });

    testWidgets('sin conexión también se registra, y se ve el banner', (tester) async {
      final e = await abrir(tester, enLinea: false);
      expect(find.text(textoSinConexion), findsOneWidget);

      await llenarTodo(tester);
      await tester.tap(botonRegistrar());
      await esperar(tester);
      expect(e.cola.reservas.length, 1);
      abrioElResultado();
    });

    testWidgets('si la cola rechaza, muestra el mensaje, se queda en la pantalla y deja reintentar con el mismo id', (tester) async {
      final cola = ColaEspia()..errorAlRegistrar = const ColaError('Ese cliente no está en tus datos. Actualiza tus datos.');
      await abrir(tester, cola: cola);
      await llenarTodo(tester);

      await tester.tap(botonRegistrar());
      await esperar(tester);

      expect(find.byKey(const Key('error_registro')), findsOneWidget);
      expect(find.text('Ese cliente no está en tus datos. Actualiza tus datos.'), findsOneWidget);
      sigueEnElFormulario();
      expect(registrarHabilitado(tester), isTrue);

      await tester.tap(botonRegistrar());
      await esperar(tester);
      expect(cola.reservas.map((r) => r.operacionId), [GeneradorUuidFijo.idUno, GeneradorUuidFijo.idUno]);
      abrioElResultado();
    });

    testWidgets('un fallo inesperado de la cola muestra un texto claro', (tester) async {
      final cola = ColaEspia()..errorAlRegistrar = StateError('boom');
      await abrir(tester, cola: cola);
      await llenarTodo(tester);
      await tester.tap(botonRegistrar());
      await esperar(tester);

      expect(find.text(textoFalloGuardarReserva), findsOneWidget);
      expect(find.textContaining('boom'), findsNothing);
    });

    testWidgets('un doble toque guarda UNA sola reserva', (tester) async {
      final cola = ColaEspia()..puerta = Completer<void>();
      await abrir(tester, cola: cola);
      await llenarTodo(tester);

      await tester.tap(botonRegistrar());
      await tester.pump();
      await asentar(tester);
      // Ya se está guardando: el botón se deshabilitó y muestra el indicador (no se puede esperar a que "se asiente").
      expect(registrarHabilitado(tester), isFalse);
      await tester.tap(botonRegistrar(), warnIfMissed: false);
      await tester.pump();

      cola.puerta!.complete();
      await esperar(tester);

      expect(cola.reservas.length, 1);
      expect(cola.todas.length, 1);
      abrioElResultado();
    });
  });

  group('el aviso de stock', () {
    testWidgets('si se pide más de lo que se estima, pregunta antes de registrar', (tester) async {
      final e = await abrir(tester);
      await llenarTodo(tester, cantidad: 6); // Polera S: quedan 5

      await tester.tap(botonRegistrar());
      await esperar(tester);

      expect(find.text('Puede faltar stock'), findsOneWidget);
      expect(find.text('Quedan 5 de Polera Básica (S, Negro)'), findsOneWidget);
      expect(find.text('Revisar'), findsOneWidget);
      expect(find.text('Registrar igual'), findsOneWidget);
      expect(e.cola.reservas, isEmpty);
    });

    testWidgets('"Revisar" cierra el aviso y no registra nada', (tester) async {
      final e = await abrir(tester);
      await llenarTodo(tester, cantidad: 6);
      await tester.tap(botonRegistrar());
      await esperar(tester);

      await tester.tap(find.text('Revisar'));
      await tester.pumpAndSettle();

      expect(find.text('Puede faltar stock'), findsNothing);
      expect(e.cola.reservas, isEmpty);
      sigueEnElFormulario();
      expect(registrarHabilitado(tester), isTrue);
    });

    testWidgets('"Registrar igual" guarda la reserva con la cantidad pedida y abre su resultado', (tester) async {
      final e = await abrir(tester);
      await llenarTodo(tester, cantidad: 6);
      await tester.tap(botonRegistrar());
      await esperar(tester);

      await tester.tap(find.text('Registrar igual'));
      await esperar(tester);

      expect(e.cola.reservas.single.lineas.single.cantidad, 6);
      abrioElResultado();
    });

    testWidgets('pedir exactamente lo que queda no pregunta nada', (tester) async {
      final e = await abrir(tester);
      await llenarTodo(tester, cantidad: 5);
      await tester.tap(botonRegistrar());
      await esperar(tester);

      expect(find.text('Puede faltar stock'), findsNothing);
      expect(e.cola.reservas.length, 1);
    });
  });

  group('cuando el servidor no deja sincronizar', () {
    testWidgets('el bloqueo de plan muestra el aviso pero NO impide registrar', (tester) async {
      const mensaje = 'Tu plan no incluye operar sin conexión.';
      final e = await abrir(tester, bloqueo: const BloqueoSync(tipo: TipoBloqueo.planNoIncluye, mensaje: mensaje));

      expect(find.byKey(const Key('aviso_bloqueo_sync')), findsOneWidget);
      expect(find.textContaining(mensaje), findsOneWidget);

      await llenarTodo(tester);
      expect(registrarHabilitado(tester), isTrue);
      await tester.tap(botonRegistrar());
      await esperar(tester);

      expect(e.cola.reservas.length, 1);
      abrioElResultado();
    });

    testWidgets('la suscripción no activa también se avisa y se puede registrar', (tester) async {
      const mensaje = 'La suscripción de la empresa no está activa.';
      final e = await abrir(tester, bloqueo: const BloqueoSync(tipo: TipoBloqueo.suscripcionNoActiva, mensaje: mensaje));

      expect(find.textContaining(mensaje), findsOneWidget);
      await llenarTodo(tester);
      await tester.tap(botonRegistrar());
      await esperar(tester);
      expect(e.cola.reservas.length, 1);
    });

    testWidgets('sin bloqueo no hay aviso', (tester) async {
      await abrir(tester);
      expect(find.byKey(const Key('aviso_bloqueo_sync')), findsNothing);
    });
  });

  group('sin datos descargados', () {
    Future<EscenarioNuevaOperacion> abrirSinDatos(WidgetTester tester) async {
      final db = await abrirBaseSembrada(tester);
      return abrirNuevaOperacion(tester, db: db, ruta: _ruta);
    }

    testWidgets('invita a descargar el catálogo y no ofrece registrar', (tester) async {
      await abrirSinDatos(tester);

      expect(find.text('Aún no descargaste el catálogo'), findsOneWidget);
      expect(find.text('Descárgalo con conexión para poder registrar sin conexión.'), findsOneWidget);
      expect(find.text('Actualizar datos'), findsOneWidget);
      expect(botonRegistrar(), findsNothing);
      expect(boton('boton_agregar_prenda'), findsNothing);
    });

    testWidgets('"Volver" regresa al inicio', (tester) async {
      await abrirSinDatos(tester);
      await tester.tap(find.text('Volver'));
      await tester.pumpAndSettle();

      expect(find.text('Nueva reserva'), findsNothing);
      expect(find.text('PANTALLA INICIO'), findsOneWidget);
    });

    testWidgets('"Actualizar datos" pide la descarga', (tester) async {
      final e = await abrirSinDatos(tester);
      await tester.tap(find.text('Actualizar datos'));
      await tester.pump();
      await asentar(tester);
      expect(e.servicio.llamadas, 1);
    });
  });
}
