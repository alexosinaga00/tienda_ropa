import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/sync/motor_sincronizacion.dart';
import 'package:mobile/core/sync/operacion_pendiente.dart';
import 'package:mobile/features/vendedor/presentation/textos_sync.dart';
import 'package:mobile/features/vendedor/state/sincronizacion_providers.dart';

import '../../helpers/cola_falsa.dart' show operacionDePrueba;
import 'apoyo_pantallas_sync.dart';
import 'apoyo_vendedor.dart';

/// Las tarjetas "Nueva venta de contado", "Nueva reserva" y "Operaciones" del inicio del personal (E20), con la cola en memoria.
void main() {
  Future<EscenarioVendedor> abrirInicio(
    WidgetTester tester, {
    Iterable<OperacionPendiente> operaciones = const [],
    ColaDePantalla? cola,
    Stream<EstadoSync>? estados,
    bool enLinea = true,
  }) async {
    final colaFalsa = cola ?? ColaDePantalla();
    for (final o in operaciones) {
      colaFalsa.sembrar(o);
    }
    addTearDown(colaFalsa.cerrar);
    final e = await abrirVendedor(
      tester,
      inicial: '/vendedor',
      enLinea: enLinea,
      estadoAuth: sesionDePersonal(),
      overrides: [
        colaOperacionesProvider.overrideWith((ref) async => colaFalsa),
        estadoSyncProvider.overrideWith((ref) => estados ?? Stream.value(const EstadoSync())),
      ],
    );
    await asentarSync(tester);
    return e;
  }

  Finder insignia() => find.byKey(const Key('insignia_operaciones'));
  double arriba(WidgetTester tester, String texto) => tester.getTopLeft(find.text(texto)).dy;

  group('las tarjetas nuevas', () {
    testWidgets('el inicio ofrece nueva venta, nueva reserva y operaciones', (tester) async {
      await abrirInicio(tester);

      expect(find.text('Nueva venta de contado'), findsOneWidget);
      expect(find.text('Cobra en efectivo, con o sin conexión'), findsOneWidget);
      expect(find.text('Nueva reserva'), findsOneWidget);
      expect(find.text('Aparta prendas para la visita de un cliente'), findsOneWidget);
      expect(find.text('Operaciones'), findsOneWidget);
      expect(find.byIcon(Icons.point_of_sale), findsOneWidget);
      expect(find.byIcon(Icons.event_available_outlined), findsOneWidget);
      expect(find.byIcon(Icons.receipt_long_outlined), findsOneWidget);
    });

    testWidgets('van en orden: venta, reserva, operaciones, catálogo y actualizar', (tester) async {
      await abrirInicio(tester);

      final posiciones = [
        arriba(tester, 'Hola, Marta'),
        arriba(tester, 'Nueva venta de contado'),
        arriba(tester, 'Nueva reserva'),
        arriba(tester, 'Operaciones'),
        arriba(tester, 'Catálogo sin conexión'),
        arriba(tester, 'Actualizar datos'),
        tester.getTopLeft(find.text('Cambiar de tienda')).dy,
        tester.getTopLeft(find.text('Cerrar sesión')).dy,
      ];
      final ordenadas = [...posiciones]..sort();
      expect(posiciones, ordenadas);
      expect(posiciones.toSet().length, posiciones.length);
    });

    testWidgets('"Nueva venta de contado" abre la pantalla de nueva venta', (tester) async {
      await abrirInicio(tester);
      await tester.tap(find.text('Nueva venta de contado'));
      await tester.pumpAndSettle();
      expect(find.text('PANTALLA NUEVA VENTA'), findsOneWidget);
    });

    testWidgets('"Nueva reserva" abre la pantalla de nueva reserva', (tester) async {
      await abrirInicio(tester);
      await tester.tap(find.text('Nueva reserva'));
      await tester.pumpAndSettle();
      expect(find.text('PANTALLA NUEVA RESERVA'), findsOneWidget);
    });

    testWidgets('"Operaciones" abre la lista de operaciones', (tester) async {
      await abrirInicio(tester);
      await tester.tap(find.text('Operaciones'));
      await tester.pumpAndSettle();
      expect(find.text('PANTALLA OPERACIONES'), findsOneWidget);
    });

    testWidgets('tocar el subtítulo o el ícono también abre la pantalla (toda la tarjeta es tocable)', (tester) async {
      await abrirInicio(tester);
      await tester.tap(find.text('Aparta prendas para la visita de un cliente'));
      await tester.pumpAndSettle();
      expect(find.text('PANTALLA NUEVA RESERVA'), findsOneWidget);
    });

    testWidgets('sin conexión las tarjetas de venta y reserva siguen activas', (tester) async {
      await abrirInicio(tester, enLinea: false);
      await tester.tap(find.text('Nueva venta de contado'));
      await tester.pumpAndSettle();
      expect(find.text('PANTALLA NUEVA VENTA'), findsOneWidget);
    });

    testWidgets('cada tarjeta mide al menos 64 de alto', (tester) async {
      await abrirInicio(tester);
      for (final titulo in ['Nueva venta de contado', 'Nueva reserva', 'Operaciones']) {
        final tarjeta = find.ancestor(of: find.text(titulo), matching: find.byType(Card)).first;
        expect(tester.getSize(tarjeta).height, greaterThanOrEqualTo(64), reason: titulo);
      }
    });

    testWidgets('ningún texto del inicio usa voseo', (tester) async {
      await abrirInicio(tester, operaciones: [opDe(1), opDe(2, estado: EstadoOperacion.rechazada)]);
      expect(textosConVoseo(tester), isEmpty);
    });
  });

  group('la insignia y el subtítulo de "Operaciones"', () {
    testWidgets('sin operaciones no hay insignia y dice "Todo al día"', (tester) async {
      await abrirInicio(tester);
      expect(insignia(), findsNothing);
      expect(find.text('Todo al día'), findsOneWidget);
    });

    testWidgets('con 3 por enviar y 1 en conflicto: insignia 4 y el subtítulo lo dice', (tester) async {
      await abrirInicio(
        tester,
        operaciones: [
          opDe(1),
          opDe(2),
          opDe(3, estado: EstadoOperacion.enviada),
          opDe(4, estado: EstadoOperacion.enConflicto),
        ],
      );

      expect(insignia(), findsOneWidget);
      expect(find.descendant(of: insignia(), matching: find.text('4')), findsOneWidget);
      expect(find.text('3 por enviar · 1 en conflicto'), findsOneWidget);
    });

    testWidgets('"por enviar" suma las registradas y las enviadas', (tester) async {
      await abrirInicio(tester, operaciones: [opDe(1), opDe(2, estado: EstadoOperacion.enviada)]);
      expect(find.text('2 por enviar'), findsOneWidget);
      expect(find.descendant(of: insignia(), matching: find.text('2')), findsOneWidget);
    });

    testWidgets('las rechazadas cuentan en la insignia y se nombran en el subtítulo (singular y plural)', (tester) async {
      await abrirInicio(tester, operaciones: [opDe(1, estado: EstadoOperacion.rechazada)]);
      expect(find.text('1 rechazada'), findsOneWidget);
      expect(find.descendant(of: insignia(), matching: find.text('1')), findsOneWidget);
    });

    testWidgets('varias rechazadas van en plural', (tester) async {
      await abrirInicio(
        tester,
        operaciones: [opDe(1, estado: EstadoOperacion.rechazada), opDe(2, estado: EstadoOperacion.rechazada), opDe(3)],
      );
      expect(find.text('1 por enviar · 2 rechazadas'), findsOneWidget);
      expect(find.descendant(of: insignia(), matching: find.text('3')), findsOneWidget);
    });

    testWidgets('las sincronizadas no cuentan: sin insignia y "Todo al día"', (tester) async {
      await abrirInicio(
        tester,
        operaciones: [opDe(1, estado: EstadoOperacion.confirmada), opDe(2, estado: EstadoOperacion.confirmada)],
      );
      expect(insignia(), findsNothing);
      expect(find.text('Todo al día'), findsOneWidget);
    });

    testWidgets('más de 99 se muestra como "99+"', (tester) async {
      await abrirInicio(tester, operaciones: [for (var i = 1; i <= 100; i++) opDe(i)]);
      expect(find.descendant(of: insignia(), matching: find.text('99+')), findsOneWidget);
      expect(find.text('100 por enviar'), findsOneWidget);
    });

    testWidgets('solo cuentan las operaciones de esta cuenta y esta empresa', (tester) async {
      await abrirInicio(
        tester,
        operaciones: [
          opDe(1),
          operacionDePrueba(idOp(2), empresaId: empresaPrueba, usuarioId: 99),
          operacionDePrueba(idOp(3), empresaId: 9, usuarioId: usuarioPrueba),
        ],
      );
      expect(find.text('1 por enviar'), findsOneWidget);
      expect(find.descendant(of: insignia(), matching: find.text('1')), findsOneWidget);
    });

    testWidgets('la insignia tiene una etiqueta para lectores de pantalla', (tester) async {
      await abrirInicio(tester, operaciones: [opDe(1), opDe(2), opDe(3)]);
      expect(find.byWidgetPredicate((w) => w is Semantics && w.properties.label == '3 por atender'), findsOneWidget);
    });

    testWidgets('se actualiza sola cuando cambia la cola', (tester) async {
      final cola = ColaDePantalla();
      cola.sembrar(opDe(1));
      cola.sembrar(opDe(2));
      await abrirInicio(tester, cola: cola);
      expect(find.text('2 por enviar'), findsOneWidget);

      await cola.cambiarEstado(idOp(1), EstadoOperacion.confirmada);
      await asentarSync(tester);
      expect(find.text('1 por enviar'), findsOneWidget);
      expect(find.descendant(of: insignia(), matching: find.text('1')), findsOneWidget);

      await cola.cambiarEstado(idOp(2), EstadoOperacion.confirmada);
      await asentarSync(tester);
      expect(insignia(), findsNothing);
      expect(find.text('Todo al día'), findsOneWidget);

      cola.sembrar(opDe(3, estado: EstadoOperacion.enConflicto));
      await cola.avisarCambio();
      await asentarSync(tester);
      expect(find.text('1 en conflicto'), findsOneWidget);
      expect(insignia(), findsOneWidget);
    });
  });

  group('el aviso de bloqueo', () {
    testWidgets('sin bloqueo no hay aviso', (tester) async {
      await abrirInicio(tester);
      expect(find.byKey(const Key('aviso_bloqueo_sync')), findsNothing);
    });

    testWidgets('un bloqueo de plan o suscripción se avisa ARRIBA de las tarjetas, sin ocultarlas', (tester) async {
      const mensaje = 'Tu plan no incluye operar sin conexión.';
      await abrirInicio(
        tester,
        estados: Stream.value(const EstadoSync(bloqueo: BloqueoSync(tipo: TipoBloqueo.planNoIncluye, mensaje: mensaje))),
      );

      expect(find.byKey(const Key('aviso_bloqueo_sync')), findsOneWidget);
      expect(find.text(mensaje), findsOneWidget);
      final aviso = tester.getTopLeft(find.byKey(const Key('aviso_bloqueo_sync'))).dy;
      expect(aviso, lessThan(arriba(tester, 'Nueva venta de contado')));
      expect(aviso, greaterThan(arriba(tester, 'Hola, Marta')));
      // Registrar sigue siendo posible.
      await tester.tap(find.text('Nueva reserva'));
      await tester.pumpAndSettle();
      expect(find.text('PANTALLA NUEVA RESERVA'), findsOneWidget);
    });

    testWidgets('la sesión vencida también se avisa', (tester) async {
      await abrirInicio(tester, estados: Stream.value(const EstadoSync(sesionVencida: true)));
      expect(find.byKey(const Key('aviso_bloqueo_sync')), findsOneWidget);
      expect(find.text(textoSesionVencida), findsOneWidget);
    });

    testWidgets('el aviso aparece y desaparece con el estado del motor', (tester) async {
      final controlador = StreamController<EstadoSync>();
      addTearDown(controlador.close);
      await abrirInicio(tester, estados: controlador.stream);
      expect(find.byKey(const Key('aviso_bloqueo_sync')), findsNothing);

      controlador.add(const EstadoSync(bloqueo: BloqueoSync(tipo: TipoBloqueo.suscripcionNoActiva, mensaje: 'Suscripción vencida.')));
      await asentarSync(tester);
      expect(find.text('Suscripción vencida.'), findsOneWidget);

      controlador.add(const EstadoSync());
      await asentarSync(tester);
      expect(find.byKey(const Key('aviso_bloqueo_sync')), findsNothing);
    });
  });

  group('lo que ya existía sigue en el inicio', () {
    testWidgets('ya no está el texto provisional de las siguientes etapas', (tester) async {
      await abrirInicio(tester);
      expect(find.text('Las herramientas de venta llegan en las siguientes etapas.'), findsNothing);
      expect(find.textContaining('siguientes etapas'), findsNothing);
    });

    testWidgets('saludo, rol, tienda y sesión verificada', (tester) async {
      await abrirInicio(tester);
      expect(find.text('Hola, Marta'), findsOneWidget);
      expect(find.descendant(of: find.byType(Card), matching: find.text('Cajero')), findsOneWidget);
      expect(find.descendant(of: find.byType(Card), matching: find.text('Chaski Sport')), findsOneWidget);
      expect(find.text('Sesión verificada'), findsOneWidget);
    });

    testWidgets('las tarjetas de catálogo sin conexión y de actualizar datos', (tester) async {
      await abrirInicio(tester);
      expect(find.text('Catálogo sin conexión'), findsOneWidget);
      expect(find.text('Aún sin datos'), findsOneWidget);
      expect(find.text('Actualizar datos'), findsOneWidget);
      expect(find.text('Aún no hay datos descargados'), findsOneWidget);

      await tester.tap(find.text('Catálogo sin conexión'));
      await tester.pumpAndSettle();
      expect(find.text('PANTALLA CATALOGO'), findsOneWidget);
    });

    testWidgets('"Cambiar de tienda" y "Cerrar sesión" siguen al final', (tester) async {
      await abrirInicio(tester);
      expect(find.widgetWithText(OutlinedButton, 'Cambiar de tienda'), findsOneWidget);
      expect(find.widgetWithText(ElevatedButton, 'Cerrar sesión'), findsOneWidget);
      expect(
        tester.getTopLeft(find.widgetWithText(OutlinedButton, 'Cambiar de tienda')).dy,
        greaterThan(arriba(tester, 'Actualizar datos')),
      );
    });

    testWidgets('cerrar sesión sigue funcionando', (tester) async {
      final e = await abrirInicio(tester);
      e.tokens.accessToken = 'ACCESS';
      e.sesion.perfil = usuarioDePrueba();

      await tester.tap(find.widgetWithText(ElevatedButton, 'Cerrar sesión'));
      await tester.pump();
      await tester.pump();

      expect(e.auth.estaAutenticado, isFalse);
    });
  });
}
