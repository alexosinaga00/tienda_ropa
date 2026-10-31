import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/widgets/indicador_conexion.dart';
import 'package:mobile/features/auth/state/auth_state.dart';
import 'package:mobile/features/vendedor/presentation/inicio_vendedor_screen.dart';

import 'apoyo_vendedor.dart';

Finder _enTarjeta(String texto) => find.descendant(of: find.byType(Card), matching: find.text(texto));

void main() {
  group('InicioVendedorScreen - contenido', () {
    testWidgets('muestra saludo, rol, tienda y sesión verificada', (tester) async {
      await abrirVendedor(tester, inicial: '/vendedor', estadoAuth: sesionDePersonal());

      expect(find.text('Hola, Marta'), findsOneWidget);
      expect(_enTarjeta('Cajero'), findsOneWidget);
      expect(_enTarjeta('Chaski Sport'), findsOneWidget);
      expect(find.text('Sesión verificada'), findsOneWidget);
      expect(find.text('Sesión sin verificar: sin conexión'), findsNothing);
      expect(find.text('Las herramientas de venta llegan en las siguientes etapas.'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Cambiar de tienda'), findsOneWidget);
      expect(find.widgetWithText(ElevatedButton, 'Cerrar sesión'), findsOneWidget);
    });

    testWidgets('la barra muestra la marca de la tienda y no tiene flecha de volver', (tester) async {
      await abrirVendedor(tester, inicial: '/vendedor', estadoAuth: sesionDePersonal());

      expect(find.descendant(of: find.byType(AppBar), matching: find.text('Chaski Sport')), findsOneWidget);
      expect(find.byType(BackButton), findsNothing);
      expect(tester.widget<AppBar>(find.byType(AppBar)).automaticallyImplyLeading, isFalse);
    });

    final roles = {
      'administrador': 'Administrador',
      'encargado_sucursal': 'Encargado de sucursal',
      'cajero': 'Cajero',
      'rol_nuevo': 'rol_nuevo',
    };
    roles.forEach((rol, texto) {
      testWidgets('el rol "$rol" se muestra como "$texto"', (tester) async {
        await abrirVendedor(
          tester,
          inicial: '/vendedor',
          estadoAuth: sesionDePersonal(usuario: usuarioDePrueba(roles: [rol])),
        );

        expect(_enTarjeta(texto), findsOneWidget);
      });
    });

    test('rolLegible usa el primer rol y tiene un respaldo sin roles', () {
      expect(rolLegible(const ['encargado_sucursal', 'administrador']), 'Encargado de sucursal');
      expect(rolLegible(const []), 'Personal');
    });

    testWidgets('sin tienda elegida usa el nombre de la empresa de la cuenta', (tester) async {
      await abrirVendedor(
        tester,
        inicial: '/vendedor',
        tienda: null,
        estadoAuth: sesionDePersonal(usuario: usuarioDePrueba(empresaNombre: 'Boutique Andina')),
      );

      expect(_enTarjeta('Boutique Andina'), findsOneWidget);
      expect(find.descendant(of: find.byType(AppBar), matching: find.text('FashionStore')), findsOneWidget);
    });

    testWidgets('sin usuario muestra un indicador de carga y no el saludo', (tester) async {
      await abrirVendedor(
        tester,
        inicial: '/vendedor',
        estadoAuth: const AuthState(estado: EstadoSesion.autenticado),
      );

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.textContaining('Hola,'), findsNothing);
    });
  });

  group('InicioVendedorScreen - conexión y verificación', () {
    testWidgets('con la sesión verificada no se vuelve a verificar', (tester) async {
      final e = await abrirVendedor(tester, inicial: '/vendedor', estadoAuth: sesionDePersonal());
      await tester.pump();

      expect(e.authFalso.verificaciones, 0);
    });

    testWidgets('sin verificar muestra la advertencia y verifica después del primer frame', (tester) async {
      final e = await abrirVendedor(
        tester,
        inicial: '/vendedor',
        enLinea: false,
        estadoAuth: sesionDePersonal(verificada: false),
      );
      await tester.pump();

      expect(find.text('Sesión sin verificar: sin conexión'), findsOneWidget);
      expect(find.text('Sesión verificada'), findsNothing);
      expect(e.authFalso.verificaciones, 1);
    });

    testWidgets('al volver la conexión vuelve a verificar la sesión', (tester) async {
      final e = await abrirVendedor(
        tester,
        inicial: '/vendedor',
        enLinea: false,
        estadoAuth: sesionDePersonal(verificada: false),
      );
      await tester.pump();
      expect(e.authFalso.verificaciones, 1);

      e.conectividad.emitir(true);
      await tester.pump();
      await tester.pump();

      expect(e.authFalso.verificaciones, 2);
    });

    testWidgets('perder la conexión no dispara una verificación', (tester) async {
      final e = await abrirVendedor(
        tester,
        inicial: '/vendedor',
        estadoAuth: sesionDePersonal(verificada: false),
      );
      await tester.pump();
      final antes = e.authFalso.verificaciones;

      e.conectividad.emitir(false);
      await tester.pump();
      await tester.pump();

      expect(e.authFalso.verificaciones, antes);
    });

    testWidgets('con la sesión ya verificada, volver la conexión no verifica', (tester) async {
      final e = await abrirVendedor(
        tester,
        inicial: '/vendedor',
        enLinea: false,
        estadoAuth: sesionDePersonal(),
      );

      e.conectividad.emitir(true);
      await tester.pump();
      await tester.pump();

      expect(e.authFalso.verificaciones, 0);
    });

    testWidgets('el banner de conexión aparece sin red y desaparece al volver', (tester) async {
      final e = await abrirVendedor(tester, inicial: '/vendedor', enLinea: false, estadoAuth: sesionDePersonal());
      expect(find.text(textoSinConexion), findsOneWidget);

      e.conectividad.emitir(true);
      await tester.pump();
      await tester.pump();

      expect(find.text(textoSinConexion), findsNothing);
    });

    testWidgets('con red no hay banner', (tester) async {
      await abrirVendedor(tester, inicial: '/vendedor', estadoAuth: sesionDePersonal());

      expect(find.text(textoSinConexion), findsNothing);
    });
  });

  group('InicioVendedorScreen - acciones', () {
    testWidgets('"Cerrar sesión" sin pendientes cierra la sesión sin preguntar', (tester) async {
      final e = await abrirVendedor(tester, inicial: '/vendedor', estadoAuth: sesionDePersonal());
      e.tokens.accessToken = 'ACCESS';
      e.sesion.perfil = usuarioDePrueba();

      await tester.tap(find.widgetWithText(ElevatedButton, 'Cerrar sesión'));
      // Sin el redirect del router real la pantalla queda cargando (sin usuario): no se puede esperar a que "se asiente".
      await tester.pump();
      await tester.pump();

      expect(find.byType(AlertDialog), findsNothing);
      expect(e.auth.estaAutenticado, isFalse);
      expect(e.auth.motivoCierre, MotivoCierre.voluntario);
      expect(e.auth.modoPrevio, isNotNull);
      expect(e.tokens.accessToken, isNull);
      expect(e.sesion.perfil, isNull);
    });

    testWidgets('"Cambiar de tienda" pide confirmación y Cancelar no cierra la sesión', (tester) async {
      final e = await abrirVendedor(tester, inicial: '/vendedor', estadoAuth: sesionDePersonal());

      await tester.tap(find.widgetWithText(OutlinedButton, 'Cambiar de tienda'));
      await tester.pumpAndSettle();

      expect(find.byType(AlertDialog), findsOneWidget);
      expect(find.text('Se cerrará tu sesión en Chaski Sport.'), findsOneWidget);

      await tester.tap(find.widgetWithText(TextButton, 'Cancelar'));
      await tester.pumpAndSettle();

      expect(find.byType(AlertDialog), findsNothing);
      expect(e.auth.estaAutenticado, isTrue);
      expect(e.ruta, '/vendedor');
    });

    testWidgets('confirmar "Cambiar de tienda" cierra la sesión y abre /tienda', (tester) async {
      final e = await abrirVendedor(tester, inicial: '/vendedor', estadoAuth: sesionDePersonal());

      await tester.tap(find.widgetWithText(OutlinedButton, 'Cambiar de tienda'));
      await tester.pumpAndSettle();
      await tester.tap(find.descendant(of: find.byType(AlertDialog), matching: find.widgetWithText(TextButton, 'Cambiar de tienda')));
      await tester.pumpAndSettle();

      expect(e.auth.estaAutenticado, isFalse);
      expect(e.ruta, '/tienda');
      expect(find.text('PANTALLA TIENDAS'), findsOneWidget);
    });
  });
}
