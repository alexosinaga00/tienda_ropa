import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/features/auth/data/auth_repository.dart';
import 'package:mobile/features/auth/presentation/recuperar_screen.dart';
import 'package:mobile/features/auth/presentation/restablecer_screen.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';

import '../../helpers/token_storage_falso.dart';

class _RepositorioFalso extends AuthRepository {
  _RepositorioFalso({this.tokenDev, this.confirmacionFalla = false})
    : super(dio: Dio(), tokenStorage: TokenStorageFalso());

  final String? tokenDev;
  final bool confirmacionFalla;
  final solicitudes = <String>[];
  final confirmaciones = <(String, String)>[];

  @override
  Future<String?> solicitarRecuperacion(String email) async {
    solicitudes.add(email);
    return tokenDev;
  }

  @override
  Future<void> confirmarRecuperacion({required String token, required String password}) async {
    if (confirmacionFalla) throw Exception('token vencido');
    confirmaciones.add((token, password));
  }
}

Future<void> _abrir(WidgetTester tester, String ubicacion, _RepositorioFalso repositorio) async {
  final router = GoRouter(
    initialLocation: ubicacion,
    routes: [
      GoRoute(path: '/recuperar', builder: (context, state) => const RecuperarScreen()),
      GoRoute(
        path: '/restablecer',
        builder: (context, state) => RestablecerScreen(token: state.uri.queryParameters['token']),
      ),
      GoRoute(path: '/login', builder: (context, state) => const Scaffold(body: Text('PANTALLA LOGIN'))),
    ],
  );
  await tester.pumpWidget(
    ProviderScope(
      overrides: [authRepositoryProvider.overrideWithValue(repositorio)],
      child: MaterialApp.router(routerConfig: router),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('RecuperarScreen', () {
    testWidgets('rechaza un correo sin @ y no llama al backend', (tester) async {
      final repositorio = _RepositorioFalso();
      await _abrir(tester, '/recuperar', repositorio);

      await tester.enterText(find.byType(TextFormField), 'sin-arroba');
      await tester.tap(find.text('Enviar instrucciones'));
      await tester.pumpAndSettle();

      expect(find.text('Ingresá un email válido'), findsOneWidget);
      expect(repositorio.solicitudes, isEmpty);
    });

    testWidgets('en producción (sin token_dev) solo avisa que se enviarán instrucciones', (tester) async {
      final repositorio = _RepositorioFalso();
      await _abrir(tester, '/recuperar', repositorio);

      await tester.enterText(find.byType(TextFormField), 'cliente@example.com');
      await tester.tap(find.text('Enviar instrucciones'));
      await tester.pumpAndSettle();

      expect(repositorio.solicitudes, ['cliente@example.com']);
      expect(find.text('Revisá tu correo'), findsOneWidget);
      expect(find.text('Si el correo está registrado, se enviarán instrucciones de recuperación.'), findsOneWidget);
      expect(find.text('Continuar a restablecer contraseña'), findsNothing);
    });

    testWidgets('en local (con token_dev) ofrece seguir a restablecer con ese token', (tester) async {
      await _abrir(tester, '/recuperar', _RepositorioFalso(tokenDev: 'abc.def'));

      await tester.enterText(find.byType(TextFormField), 'cliente@example.com');
      await tester.tap(find.text('Enviar instrucciones'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Continuar a restablecer contraseña'));
      await tester.pumpAndSettle();

      expect(find.text('Elegí una contraseña nueva'), findsOneWidget);
    });
  });

  group('RestablecerScreen', () {
    testWidgets('sin token muestra "Enlace inválido" y ofrece pedir otro', (tester) async {
      await _abrir(tester, '/restablecer', _RepositorioFalso());

      expect(find.text('Enlace inválido'), findsOneWidget);
      expect(find.text('Solicitar otro enlace'), findsOneWidget);
    });

    testWidgets('valida el largo y que las dos contraseñas coincidan', (tester) async {
      final repositorio = _RepositorioFalso();
      await _abrir(tester, '/restablecer?token=abc', repositorio);

      await tester.enterText(find.byType(TextFormField).at(0), 'corta');
      await tester.enterText(find.byType(TextFormField).at(1), 'otra');
      await tester.tap(find.text('Cambiar contraseña'));
      await tester.pumpAndSettle();
      expect(find.text('Usá al menos 8 caracteres'), findsOneWidget);
      expect(find.text('Las contraseñas no coinciden'), findsOneWidget);

      await tester.enterText(find.byType(TextFormField).at(0), 'claveNueva123');
      await tester.enterText(find.byType(TextFormField).at(1), 'claveDistinta1');
      await tester.tap(find.text('Cambiar contraseña'));
      await tester.pumpAndSettle();
      expect(find.text('Las contraseñas no coinciden'), findsOneWidget);
      expect(repositorio.confirmaciones, isEmpty);
    });

    testWidgets('con datos válidos cambia la contraseña y vuelve al login', (tester) async {
      final repositorio = _RepositorioFalso();
      await _abrir(tester, '/restablecer?token=abc', repositorio);

      await tester.enterText(find.byType(TextFormField).at(0), 'claveNueva123');
      await tester.enterText(find.byType(TextFormField).at(1), 'claveNueva123');
      await tester.tap(find.text('Cambiar contraseña'));
      await tester.pump();
      await tester.pump();

      expect(repositorio.confirmaciones, [('abc', 'claveNueva123')]);
      expect(find.text('Contraseña actualizada'), findsOneWidget);

      await tester.pump(const Duration(seconds: 3));
      await tester.pumpAndSettle();
      expect(find.text('PANTALLA LOGIN'), findsOneWidget);
    });

    testWidgets('si el token venció o no es válido, lo explica y no cambia de pantalla', (tester) async {
      await _abrir(tester, '/restablecer?token=abc', _RepositorioFalso(confirmacionFalla: true));

      await tester.enterText(find.byType(TextFormField).at(0), 'claveNueva123');
      await tester.enterText(find.byType(TextFormField).at(1), 'claveNueva123');
      await tester.tap(find.text('Cambiar contraseña'));
      await tester.pumpAndSettle();

      expect(find.text('El enlace de recuperación venció o no es válido. Solicitá uno nuevo.'), findsOneWidget);
      expect(find.text('Contraseña actualizada'), findsNothing);
    });
  });
}
