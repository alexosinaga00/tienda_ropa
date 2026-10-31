import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/widgets/indicador_conexion.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/auth/state/auth_state.dart';
import 'package:mobile/features/tienda/state/tienda_controller.dart';

import 'apoyo_vendedor.dart';

Finder _campo(String etiqueta) => find.widgetWithText(TextFormField, etiqueta);
Finder _boton(String texto) => find.widgetWithText(ElevatedButton, texto);

String _textoDe(WidgetTester tester, String etiqueta) =>
    tester.widget<EditableText>(find.descendant(of: _campo(etiqueta), matching: find.byType(EditableText))).controller.text;

bool _ocultaTexto(WidgetTester tester, String etiqueta) =>
    tester.widget<EditableText>(find.descendant(of: _campo(etiqueta), matching: find.byType(EditableText))).obscureText;

Future<void> _llenar(WidgetTester tester, {String empresa = 'Chaski Sport', String correo = 'marta@chaski.bo', String clave = 'clave12345'}) async {
  await tester.enterText(_campo('Empresa'), empresa);
  await tester.enterText(_campo('Correo'), correo);
  await tester.enterText(_campo('Contraseña'), clave);
}

Future<void> _ingresar(WidgetTester tester) async {
  await tester.tap(_boton('Ingresar'));
  await tester.pumpAndSettle();
}

void main() {
  group('AccesoVendedorScreen - contenido', () {
    testWidgets('muestra los tres campos, el botón, la ayuda y los dos enlaces', (tester) async {
      await abrirVendedor(tester);

      expect(find.text('Acceso del personal'), findsNWidgets(2), reason: 'barra y título');
      expect(find.text('Ingresa con la cuenta que te dio tu empresa.'), findsOneWidget);
      expect(_campo('Empresa'), findsOneWidget);
      expect(_campo('Correo'), findsOneWidget);
      expect(_campo('Contraseña'), findsOneWidget);
      expect(_boton('Ingresar'), findsOneWidget);
      expect(find.widgetWithText(TextButton, 'Elegir otra tienda'), findsOneWidget);
      expect(find.widgetWithText(TextButton, 'Soy cliente'), findsOneWidget);
    });

    testWidgets('el botón Ingresar ocupa todo el ancho y mide 48 px de alto', (tester) async {
      await abrirVendedor(tester);

      final tamano = tester.getSize(_boton('Ingresar'));
      expect(tamano.height, 48);
      expect(tamano.width, greaterThan(300));
    });

    testWidgets('Empresa inicia con el nombre de la tienda elegida y se puede editar', (tester) async {
      await abrirVendedor(tester);
      expect(_textoDe(tester, 'Empresa'), 'Chaski Sport');

      await tester.enterText(_campo('Empresa'), 'Boutique Andina');
      await tester.pump();

      expect(_textoDe(tester, 'Empresa'), 'Boutique Andina');
    });

    testWidgets('sin tienda elegida el campo Empresa empieza vacío', (tester) async {
      await abrirVendedor(tester, tienda: null);

      expect(_textoDe(tester, 'Empresa'), isEmpty);
    });

    testWidgets('la contraseña se oculta y el ojo la muestra y la vuelve a ocultar', (tester) async {
      await abrirVendedor(tester);
      expect(_ocultaTexto(tester, 'Contraseña'), isTrue);

      await tester.tap(find.byTooltip('Mostrar contraseña'));
      await tester.pump();
      expect(_ocultaTexto(tester, 'Contraseña'), isFalse);

      await tester.tap(find.byTooltip('Ocultar contraseña'));
      await tester.pump();
      expect(_ocultaTexto(tester, 'Contraseña'), isTrue);
    });

    testWidgets('el correo se escribe en minúsculas', (tester) async {
      await abrirVendedor(tester);

      await tester.enterText(_campo('Correo'), 'MARTA@Chaski.BO');
      await tester.pump();

      expect(_textoDe(tester, 'Correo'), 'marta@chaski.bo');
    });

    testWidgets('sin red muestra el banner de conexión', (tester) async {
      await abrirVendedor(tester, enLinea: false);

      expect(find.text(textoSinConexion), findsOneWidget);
    });

    testWidgets('con red no hay banner', (tester) async {
      await abrirVendedor(tester);

      expect(find.text(textoSinConexion), findsNothing);
    });

    testWidgets('abierta como pantalla raíz no tiene flecha de volver', (tester) async {
      await abrirVendedor(tester);

      expect(find.byType(BackButton), findsNothing);
    });

    testWidgets('abierta encima de otra pantalla tiene flecha de volver', (tester) async {
      final e = await abrirVendedor(tester, inicial: '/home');
      unawaited(e.router.push('/vendedor/acceso'));
      await tester.pumpAndSettle();

      expect(find.byType(BackButton), findsOneWidget);
    });
  });

  group('AccesoVendedorScreen - validaciones', () {
    testWidgets('con todo vacío muestra los tres mensajes y no llama al servidor', (tester) async {
      final e = await abrirVendedor(tester, tienda: null);

      await _ingresar(tester);

      expect(find.text('Escribe el nombre de tu empresa.'), findsOneWidget);
      expect(find.text('Escribe un correo válido.'), findsOneWidget);
      expect(find.text('Escribe tu contraseña.'), findsOneWidget);
      expect(e.repo.logins, isEmpty);
    });

    for (final correo in ['marta', 'marta@chaski', 'marta.chaski', '   ']) {
      testWidgets('el correo "$correo" no es válido', (tester) async {
        final e = await abrirVendedor(tester);
        await _llenar(tester, correo: correo);

        await _ingresar(tester);

        expect(find.text('Escribe un correo válido.'), findsOneWidget);
        expect(e.repo.logins, isEmpty);
      });
    }

    testWidgets('una empresa de solo espacios no vale', (tester) async {
      final e = await abrirVendedor(tester);
      await _llenar(tester, empresa: '   ');

      await _ingresar(tester);

      expect(find.text('Escribe el nombre de tu empresa.'), findsOneWidget);
      expect(e.repo.logins, isEmpty);
    });
  });

  group('AccesoVendedorScreen - ingreso', () {
    testWidgets('un cajero entra: manda empresa, correo y contraseña y va a /vendedor', (tester) async {
      final e = await abrirVendedor(tester);
      await _llenar(tester, empresa: '  Chaski Sport ', correo: ' Marta@Chaski.bo ');

      await _ingresar(tester);

      expect(e.repo.logins, hasLength(1));
      expect(e.repo.logins.single.empresa, 'Chaski Sport');
      expect(e.repo.logins.single.email, 'marta@chaski.bo');
      expect(e.repo.logins.single.password, 'clave12345');
      expect(e.auth.estaAutenticado, isTrue);
      expect(e.ruta, '/vendedor');
      expect(find.text('Hola, Marta'), findsOneWidget);
    });

    testWidgets('al entrar se guardan el perfil y la tienda de la cuenta', (tester) async {
      final e = await abrirVendedor(
        tester,
        tienda: null,
        usuarioLogin: usuarioDePrueba(empresaCodigo: 'andina', empresaNombre: 'Boutique Andina'),
      );
      await _llenar(tester, empresa: 'andina');

      await _ingresar(tester);

      expect(e.sesion.perfil?.email, 'marta@chaski.bo');
      expect(e.contenedor.read(tiendaActualProvider)?.codigo, 'andina');
      expect(e.ruta, '/vendedor');
    });

    testWidgets('credenciales incorrectas: muestra el mensaje y no navega', (tester) async {
      final e = await abrirVendedor(tester, errorLogin: errorDio(DioExceptionType.badResponse, estado: 401));
      await _llenar(tester);

      await _ingresar(tester);

      expect(find.text(mensajeCredencialesPersonal), findsOneWidget);
      expect(find.text('Empresa, correo o contraseña incorrectos.'), findsOneWidget);
      expect(e.ruta, '/vendedor/acceso');
      expect(e.auth.estaAutenticado, isFalse);
      expect(e.tokens.accessToken, isNull);
    });

    testWidgets('una cuenta de cliente muestra su mensaje y NO navega', (tester) async {
      final e = await abrirVendedor(
        tester,
        usuarioLogin: usuarioDePrueba(roles: const ['cliente'], permisos: const []),
      );
      await _llenar(tester);

      await _ingresar(tester);

      expect(find.text(mensajeCuentaDeCliente), findsOneWidget);
      expect(e.ruta, '/vendedor/acceso');
      expect(e.auth.estaAutenticado, isFalse);
      expect(e.tokens.accessToken, isNull, reason: 'la sesión que abrió el login se cierra');
    });

    testWidgets('un rol sin acceso a la app móvil muestra su mensaje y NO navega', (tester) async {
      final e = await abrirVendedor(
        tester,
        usuarioLogin: usuarioDePrueba(roles: const ['proveedor'], permisos: const []),
      );
      await _llenar(tester);

      await _ingresar(tester);

      expect(find.text(mensajeSinAccesoMovil), findsOneWidget);
      expect(e.ruta, '/vendedor/acceso');
      expect(e.auth.estaAutenticado, isFalse);
    });

    testWidgets('sin conexión muestra que la primera vez se necesita internet', (tester) async {
      final e = await abrirVendedor(tester, errorLogin: errorDio(DioExceptionType.connectionError));
      await _llenar(tester);

      await _ingresar(tester);

      expect(find.text(mensajePrimeraVezSinConexion), findsOneWidget);
      expect(e.ruta, '/vendedor/acceso');
    });

    testWidgets('suscripción no activa muestra el mensaje fijo', (tester) async {
      final error = errorDio(
        DioExceptionType.badResponse,
        estado: 403,
        datos: {'detail': 'suscripcion_no_activa', 'codigo': 'suscripcion_no_activa', 'mensaje': 'texto del servidor'},
      );
      final e = await abrirVendedor(tester, errorLogin: error);
      await _llenar(tester);

      await _ingresar(tester);

      final fijo = ErrorApp.desde(error).mensaje;
      expect(fijo, 'La suscripción de esta tienda no está activa. Contacta al administrador de la tienda.');
      expect(find.text(fijo), findsOneWidget);
      expect(find.text('texto del servidor'), findsNothing);
      expect(e.ruta, '/vendedor/acceso');
    });

    testWidgets('un error del servidor muestra un mensaje en español, nunca la excepción', (tester) async {
      await abrirVendedor(tester, errorLogin: errorDio(DioExceptionType.badResponse, estado: 500));
      await _llenar(tester);

      await _ingresar(tester);

      expect(find.text('El servidor no pudo responder. Intenta de nuevo en unos minutos.'), findsOneWidget);
      expect(find.textContaining('DioException'), findsNothing);
    });

    testWidgets('un error desconocido muestra el mensaje de credenciales, no la excepción cruda', (tester) async {
      await abrirVendedor(tester, errorLogin: StateError('boom'));
      await _llenar(tester);

      await _ingresar(tester);

      expect(find.text(mensajeCredencialesPersonal), findsOneWidget);
      expect(find.textContaining('boom'), findsNothing);
    });

    testWidgets('después de un error el botón vuelve a estar activo para reintentar', (tester) async {
      final e = await abrirVendedor(tester, errorLogin: errorDio(DioExceptionType.badResponse, estado: 401));
      await _llenar(tester);

      await _ingresar(tester);
      expect(tester.widget<ElevatedButton>(find.byType(ElevatedButton)).onPressed, isNotNull);

      await _ingresar(tester);
      expect(e.repo.logins, hasLength(2));
      expect(find.text(mensajeCredencialesPersonal), findsOneWidget);
    });

    testWidgets('mientras carga el botón está deshabilitado y muestra el indicador', (tester) async {
      final puerta = Completer<void>();
      final e = await abrirVendedor(tester, puerta: puerta);
      await _llenar(tester);

      await tester.tap(_boton('Ingresar'));
      await tester.pump();

      final boton = tester.widget<ElevatedButton>(find.byType(ElevatedButton));
      expect(boton.onPressed, isNull);
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.text('Ingresar'), findsNothing);

      // Un segundo toque no envía otra petición.
      await tester.tap(find.byType(ElevatedButton), warnIfMissed: false);
      await tester.pump();
      expect(e.repo.logins, hasLength(1));

      puerta.complete();
      await tester.pumpAndSettle();
      expect(e.ruta, '/vendedor');
    });
  });

  group('AccesoVendedorScreen - enlaces', () {
    testWidgets('"Soy cliente" olvida el motivo del cierre y va a /home', (tester) async {
      final e = await abrirVendedor(tester, estadoAuth: sesionVencida);
      expect(e.auth.motivoCierre, MotivoCierre.vencida);

      await tester.tap(find.widgetWithText(TextButton, 'Soy cliente'));
      await tester.pumpAndSettle();

      expect(e.authFalso.olvidos, 1);
      expect(e.auth.motivoCierre, isNull);
      expect(e.ruta, '/home');
      expect(find.text('PANTALLA HOME'), findsOneWidget);
    });

    testWidgets('"Elegir otra tienda" olvida el motivo y abre /tienda encima', (tester) async {
      final e = await abrirVendedor(tester, estadoAuth: sesionVencida);

      await tester.tap(find.widgetWithText(TextButton, 'Elegir otra tienda'));
      await tester.pumpAndSettle();

      expect(e.authFalso.olvidos, 1);
      expect(e.auth.motivoCierre, isNull);
      expect(e.ruta, '/tienda');
      expect(find.text('PANTALLA TIENDAS'), findsOneWidget);
      expect(e.router.canPop(), isTrue, reason: 'se apila: la flecha de volver sirve');
    });
  });
}
