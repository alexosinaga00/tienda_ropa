import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/core/router/retroceso.dart';

String _ubicacion(GoRouter router) => router.routerDelegate.currentConfiguration.uri.toString();

/// Un router mínimo con las pantallas justas para probar el botón "atrás" del sistema.
GoRouter _routerDePrueba(String inicial) {
  Widget pantalla(String nombre) => Scaffold(body: Center(child: Text(nombre)));
  return GoRouter(
    initialLocation: inicial,
    routes: [
      GoRoute(path: '/home', builder: (context, state) => pantalla('PANTALLA HOME')),
      GoRoute(path: '/login', builder: (context, state) => pantalla('PANTALLA LOGIN')),
      GoRoute(path: '/registro', builder: (context, state) => pantalla('PANTALLA REGISTRO')),
      GoRoute(path: '/vendedor', builder: (context, state) => pantalla('PANTALLA VENDEDOR')),
      GoRoute(path: '/vendedor/acceso', builder: (context, state) => pantalla('PANTALLA ACCESO VENDEDOR')),
      GoRoute(
        path: '/producto/:id',
        builder: (context, state) => pantalla('PANTALLA PRODUCTO ${state.pathParameters['id']}'),
      ),
    ],
  );
}

/// Monta el router con el [RetrocesoDelRouter] como botón "atrás" y lo devuelve junto con el despachador.
Future<(GoRouter, RetrocesoDelRouter)> _montar(WidgetTester tester, String inicial) async {
  final router = _routerDePrueba(inicial);
  addTearDown(router.dispose);
  final despachador = RetrocesoDelRouter(router);
  await tester.pumpWidget(
    MaterialApp.router(
      routeInformationProvider: router.routeInformationProvider,
      routeInformationParser: router.routeInformationParser,
      routerDelegate: router.routerDelegate,
      backButtonDispatcher: despachador,
    ),
  );
  await tester.pump();
  return (router, despachador);
}

void main() {
  group('rutaPadreDe', () {
    const tabla = <String, String?>{
      '/home': null,
      '/tienda': null,
      '/splash': null,
      '/registro': '/login',
      '/recuperar': '/login',
      '/restablecer': '/login',
      '/login': '/home',
      '/favoritos': '/home',
      '/carrito': '/home',
      '/compras': '/home',
      '/reservas': '/home',
      '/notificaciones': '/home',
      '/asistente': '/home',
      '/probador': '/home',
      '/producto/7': '/home',
      '/reserva/confirmar': '/home',
      '/reserva/9': '/reservas',
      '/compras/3': '/compras',
      '/checkout/entrega': '/carrito',
      '/checkout/pago': '/checkout/entrega',
      '/checkout/direccion/nueva': '/checkout/entrega',
      '/checkout/estado/5': '/compras',
      '/ruta/que/no/existe': '/home',
    };

    for (final entrada in tabla.entries) {
      test('${entrada.key} sube a ${entrada.value ?? 'nada (cierra la app)'}', () {
        expect(rutaPadreDe(entrada.key), entrada.value);
      });
    }

    test('el padre de una ruta con padre nunca es ella misma (no hay bucles)', () {
      for (final ruta in tabla.keys) {
        expect(rutaPadreDe(ruta), isNot(ruta));
      }
    });

    test('toda cadena de padres termina en una ruta sin padre', () {
      for (final ruta in tabla.keys) {
        var actual = ruta;
        var saltos = 0;
        while (rutaPadreDe(actual) != null) {
          actual = rutaPadreDe(actual)!;
          expect(++saltos, lessThan(6), reason: 'la cadena de $ruta no termina');
        }
        expect(actual, anyOf('/home', '/tienda', '/splash'));
      }
    });
  });

  group('rutaPadreDe - área del personal', () {
    // Sin padre a propósito: si la sesión del personal venció, el router lo manda a su acceso, y un padre lo atraparía.
    test('/vendedor no tiene padre', () {
      expect(rutaPadreDe('/vendedor'), isNull);
    });

    test('/vendedor/acceso no tiene padre', () {
      expect(rutaPadreDe('/vendedor/acceso'), isNull);
    });

    test('las rutas del cliente siguen colgando del catálogo', () {
      expect(rutaPadreDe('/carrito'), '/home');
      expect(rutaPadreDe('/login'), '/home');
    });
  });

  group('RetrocesoDelRouter - área del personal', () {
    testWidgets('desde /vendedor no maneja el botón: la app se cierra', (tester) async {
      final (router, despachador) = await _montar(tester, '/vendedor');
      expect(find.text('PANTALLA VENDEDOR'), findsOneWidget);

      final manejado = await despachador.didPopRoute();
      await tester.pump();

      expect(manejado, isFalse);
      expect(_ubicacion(router), '/vendedor');
    });

    testWidgets('desde /vendedor/acceso no maneja el botón: la app se cierra', (tester) async {
      final (router, despachador) = await _montar(tester, '/vendedor/acceso');

      final manejado = await despachador.didPopRoute();
      await tester.pump();

      expect(manejado, isFalse);
      expect(_ubicacion(router), '/vendedor/acceso');
    });
  });

  group('RetrocesoDelRouter', () {
    testWidgets('desde /registro abierto con go sube a /login y maneja el botón', (tester) async {
      final (router, despachador) = await _montar(tester, '/registro');
      expect(find.text('PANTALLA REGISTRO'), findsOneWidget);

      final manejado = await despachador.didPopRoute();
      await tester.pump();

      expect(manejado, isTrue);
      expect(_ubicacion(router), '/login');
      expect(find.text('PANTALLA LOGIN'), findsOneWidget);
    });

    testWidgets('desde /login abierto con go sube a /home', (tester) async {
      final (router, despachador) = await _montar(tester, '/login');

      final manejado = await despachador.didPopRoute();
      await tester.pump();

      expect(manejado, isTrue);
      expect(_ubicacion(router), '/home');
      expect(find.text('PANTALLA HOME'), findsOneWidget);
    });

    testWidgets('desde /home no maneja el botón: la app se cerraría', (tester) async {
      final (router, despachador) = await _montar(tester, '/home');

      final manejado = await despachador.didPopRoute();
      await tester.pump();

      expect(manejado, isFalse);
      expect(_ubicacion(router), '/home');
    });

    testWidgets('con una pila real vuelve a la pantalla anterior sin usar el padre', (tester) async {
      // El padre de /producto/7 es /home, pero la pantalla anterior es /login: debe ganar la pila.
      final (router, despachador) = await _montar(tester, '/login');
      router.push('/producto/7');
      await tester.pump();
      await tester.pump();
      expect(find.text('PANTALLA PRODUCTO 7'), findsOneWidget);

      final manejado = await despachador.didPopRoute();
      await tester.pump();
      await tester.pump(const Duration(seconds: 1));

      expect(manejado, isTrue);
      expect(_ubicacion(router), '/login');
      expect(find.text('PANTALLA LOGIN'), findsOneWidget);
    });

    testWidgets('con pila [home, producto] vuelve a /home', (tester) async {
      final (router, despachador) = await _montar(tester, '/home');
      router.push('/producto/7');
      await tester.pump();
      await tester.pump();

      final manejado = await despachador.didPopRoute();
      await tester.pump();
      await tester.pump(const Duration(seconds: 1));

      expect(manejado, isTrue);
      expect(_ubicacion(router), '/home');
    });

    testWidgets('un producto abierto con go (sin pila) sube a /home', (tester) async {
      final (router, despachador) = await _montar(tester, '/producto/7');

      final manejado = await despachador.didPopRoute();
      await tester.pump();

      expect(manejado, isTrue);
      expect(_ubicacion(router), '/home');
    });

    testWidgets('dos veces seguidas desde /registro: primero /login, luego /home, luego la app se cierra', (tester) async {
      final (router, despachador) = await _montar(tester, '/registro');

      expect(await despachador.didPopRoute(), isTrue);
      await tester.pump();
      expect(_ubicacion(router), '/login');

      expect(await despachador.didPopRoute(), isTrue);
      await tester.pump();
      expect(_ubicacion(router), '/home');

      expect(await despachador.didPopRoute(), isFalse);
      expect(_ubicacion(router), '/home');
    });

    testWidgets('con un diálogo abierto el botón lo cierra y NO cambia la ruta', (tester) async {
      final (router, despachador) = await _montar(tester, '/registro');
      final contexto = tester.element(find.text('PANTALLA REGISTRO'));
      showDialog<void>(context: contexto, builder: (_) => const AlertDialog(title: Text('DIALOGO ABIERTO')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.text('DIALOGO ABIERTO'), findsOneWidget);

      final manejado = await despachador.didPopRoute();
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));

      expect(manejado, isTrue);
      expect(find.text('DIALOGO ABIERTO'), findsNothing);
      expect(_ubicacion(router), '/registro');
      expect(find.text('PANTALLA REGISTRO'), findsOneWidget);
    });
  });
}

