import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/features/notificaciones/presentation/boton_notificaciones.dart';
import 'package:mobile/features/notificaciones/presentation/notificaciones_screen.dart';

import 'apoyo_notificaciones.dart';

/// Monta `inicio` con dos pantallas de destino de mentira, para comprobar a dónde lleva cada toque.
Future<void> _abrir(
  WidgetTester tester,
  RepositorioNotificacionesFalso repositorio, {
  Widget inicio = const NotificacionesScreen(),
}) async {
  final router = GoRouter(
    routes: [
      GoRoute(path: '/', builder: (context, state) => inicio),
      GoRoute(path: '/notificaciones', builder: (context, state) => const Scaffold(body: Text('LISTA'))),
      GoRoute(
        path: '/reserva/:id',
        builder: (context, state) => Scaffold(body: Text('RESERVA ${state.pathParameters['id']}')),
      ),
      GoRoute(
        path: '/compras/:id',
        builder: (context, state) => Scaffold(body: Text('COMPRA ${state.pathParameters['id']}')),
      ),
    ],
  );
  await tester.pumpWidget(
    ProviderScope(
      overrides: overridesNotificaciones(repositorio),
      child: MaterialApp.router(routerConfig: router),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('NotificacionesScreen', () {
    testWidgets('lista las notificaciones con su texto, su hora y las no leídas resaltadas', (tester) async {
      final repositorio = RepositorioNotificacionesFalso([
        notificacion(1, titulo: 'Tu pedido está en camino', mensaje: 'Tu compra V-1 salió a reparto.', tipo: 'envio'),
        notificacion(2, titulo: 'Tu reserva está lista', tipo: 'reserva_preparada', leida: true, hace: const Duration(hours: 3)),
      ]);
      await _abrir(tester, repositorio);

      expect(find.text('Tu pedido está en camino'), findsOneWidget);
      expect(find.text('Tu compra V-1 salió a reparto.'), findsOneWidget);
      expect(find.text('hace 5 min'), findsOneWidget);
      expect(find.text('Tu reserva está lista'), findsOneWidget);
      expect(find.text('hace 3 h'), findsOneWidget);
      expect(find.byIcon(Icons.circle), findsOneWidget); // solo la primera
    });

    testWidgets('sin notificaciones lo dice, y no ofrece "marcar todas"', (tester) async {
      await _abrir(tester, RepositorioNotificacionesFalso([]));

      expect(find.text('No tienes notificaciones'), findsOneWidget);
      expect(find.byTooltip('Marcar todas como leídas'), findsNothing);
    });

    testWidgets('si no se pueden cargar avisa en vez de quedar en blanco', (tester) async {
      await _abrir(tester, RepositorioNotificacionesFalso([notificacion(1)])..fallaListar = true);

      expect(find.text('No se pudieron cargar tus notificaciones.'), findsOneWidget);
    });

    testWidgets('tocar una reserva preparada la marca como leída y abre la reserva', (tester) async {
      final repositorio = RepositorioNotificacionesFalso([
        notificacion(1, titulo: 'Tu reserva está lista', tipo: 'reserva_preparada', referenciaId: 5),
      ]);
      await _abrir(tester, repositorio);

      await tester.tap(find.text('Tu reserva está lista'));
      await tester.pumpAndSettle();

      expect(repositorio.marcadas, [1]);
      expect(find.text('RESERVA 5'), findsOneWidget);
    });

    testWidgets('tocar el estado de un envío abre la compra', (tester) async {
      final repositorio = RepositorioNotificacionesFalso([
        notificacion(1, titulo: 'Tu pedido está en camino', tipo: 'envio', referenciaId: 12),
      ]);
      await _abrir(tester, repositorio);

      await tester.tap(find.text('Tu pedido está en camino'));
      await tester.pumpAndSettle();

      expect(find.text('COMPRA 12'), findsOneWidget);
    });

    testWidgets('un tipo desconocido se marca como leído pero no abre nada', (tester) async {
      final repositorio = RepositorioNotificacionesFalso([notificacion(1, titulo: 'Novedad', tipo: 'promocion')]);
      await _abrir(tester, repositorio);

      await tester.tap(find.text('Novedad'));
      await tester.pumpAndSettle();

      expect(repositorio.marcadas, [1]);
      expect(find.text('Novedad'), findsOneWidget); // sigue en la lista
      expect(find.byIcon(Icons.circle), findsNothing);
    });

    testWidgets('"Marcar todas como leídas" las marca todas y desaparece', (tester) async {
      final repositorio = RepositorioNotificacionesFalso([notificacion(1), notificacion(2), notificacion(3, leida: true)]);
      await _abrir(tester, repositorio);
      expect(find.byIcon(Icons.circle), findsNWidgets(2));

      await tester.tap(find.byTooltip('Marcar todas como leídas'));
      await tester.pumpAndSettle();

      expect(repositorio.marcadas, unorderedEquals([1, 2]));
      expect(find.byIcon(Icons.circle), findsNothing);
      expect(find.byTooltip('Marcar todas como leídas'), findsNothing);
    });
  });

  group('BotonNotificaciones', () {
    Widget barra() => Scaffold(appBar: AppBar(actions: const [BotonNotificaciones()]));

    testWidgets('con notificaciones sin leer muestra cuántas', (tester) async {
      await _abrir(
        tester,
        RepositorioNotificacionesFalso([notificacion(1), notificacion(2), notificacion(3, leida: true)]),
        inicio: barra(),
      );

      expect(find.text('2'), findsOneWidget);
    });

    testWidgets('sin notificaciones sin leer no muestra ningún número', (tester) async {
      await _abrir(tester, RepositorioNotificacionesFalso([notificacion(1, leida: true)]), inicio: barra());

      expect(find.byIcon(Icons.notifications_outlined), findsOneWidget);
      expect(find.text('0'), findsNothing);
      expect(find.text('1'), findsNothing);
    });

    testWidgets('si hay muchas muestra 99+', (tester) async {
      await _abrir(tester, RepositorioNotificacionesFalso([for (var i = 1; i <= 120; i++) notificacion(i)]), inicio: barra());

      expect(find.text('99+'), findsOneWidget);
    });

    testWidgets('al tocarla abre la lista', (tester) async {
      await _abrir(tester, RepositorioNotificacionesFalso([notificacion(1)]), inicio: barra());

      await tester.tap(find.byTooltip('Notificaciones'));
      await tester.pumpAndSettle();

      expect(find.text('LISTA'), findsOneWidget);
    });
  });
}
