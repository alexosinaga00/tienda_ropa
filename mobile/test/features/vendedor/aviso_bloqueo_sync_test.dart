import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/sync/motor_sincronizacion.dart';
import 'package:mobile/core/theme/app_theme.dart';
import 'package:mobile/features/vendedor/presentation/aviso_bloqueo_sync.dart';
import 'package:mobile/features/vendedor/presentation/textos_sync.dart';
import 'package:mobile/features/vendedor/state/sincronizacion_providers.dart';

import 'apoyo_pantallas_sync.dart' show textosConVoseo;

const _planNoIncluye = BloqueoSync(tipo: TipoBloqueo.planNoIncluye, mensaje: 'Tu plan no incluye operar sin conexión.');
const _suscripcion = BloqueoSync(tipo: TipoBloqueo.suscripcionNoActiva, mensaje: 'La suscripción de la empresa no está activa.');
const _actualizar = BloqueoSync(tipo: TipoBloqueo.actualizarApp, mensaje: 'Actualiza la aplicación para poder sincronizar.');

Finder get _aviso => find.byKey(const Key('aviso_bloqueo_sync'));

/// Monta el aviso solo, con el estado del motor que entrega [estados].
Future<void> _montar(WidgetTester tester, Stream<EstadoSync> estados) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [estadoSyncProvider.overrideWith((ref) => estados)],
      child: const MaterialApp(
        home: Scaffold(body: Column(children: [AvisoBloqueoSync(), Text('CONTENIDO DE DEBAJO')])),
      ),
    ),
  );
  await tester.pump();
  await tester.pump();
}

Color _colorDelIcono(WidgetTester tester) => tester.widget<Icon>(find.descendant(of: _aviso, matching: find.byType(Icon))).color!;

void main() {
  group('AvisoBloqueoSync - cuándo se muestra', () {
    testWidgets('sin bloqueo ni sesión vencida no muestra nada ni ocupa espacio', (tester) async {
      await _montar(tester, Stream.value(const EstadoSync()));

      expect(_aviso, findsNothing);
      expect(find.byType(Icon), findsNothing);
      expect(tester.getSize(find.byType(AvisoBloqueoSync)), Size.zero);
    });

    testWidgets('mientras el motor no ha respondido tampoco muestra nada', (tester) async {
      final controlador = StreamController<EstadoSync>();
      addTearDown(controlador.close);
      await _montar(tester, controlador.stream);

      expect(_aviso, findsNothing);
    });

    testWidgets('una sincronización en curso sin problemas no muestra nada', (tester) async {
      await _montar(tester, Stream.value(const EstadoSync(enCurso: true)));
      expect(_aviso, findsNothing);
    });
  });

  group('AvisoBloqueoSync - cada tipo de bloqueo', () {
    final casos = <String, BloqueoSync>{
      'el plan no incluye la función': _planNoIncluye,
      'la suscripción no está activa': _suscripcion,
      'la app debe actualizarse': _actualizar,
    };

    casos.forEach((nombre, bloqueo) {
      testWidgets('$nombre: muestra el mensaje del servidor con ícono y color de advertencia', (tester) async {
        await _montar(tester, Stream.value(EstadoSync(bloqueo: bloqueo)));

        expect(_aviso, findsOneWidget);
        expect(find.descendant(of: _aviso, matching: find.text(bloqueo.mensaje)), findsOneWidget);
        expect(find.descendant(of: _aviso, matching: find.byIcon(Icons.sync_problem)), findsOneWidget);
        expect(_colorDelIcono(tester), AppColors.advertencia);
        final texto = tester.widget<Text>(find.text(bloqueo.mensaje));
        expect(texto.style!.color, AppColors.advertencia);
      });
    });

    testWidgets('la franja empuja el contenido de debajo (no lo tapa)', (tester) async {
      await _montar(tester, Stream.value(const EstadoSync(bloqueo: _planNoIncluye)));
      expect(tester.getTopLeft(find.text('CONTENIDO DE DEBAJO')).dy, greaterThanOrEqualTo(tester.getBottomLeft(_aviso).dy));
    });

    testWidgets('es un aviso, no un botón: no bloquea nada', (tester) async {
      await _montar(tester, Stream.value(const EstadoSync(bloqueo: _planNoIncluye)));
      expect(find.descendant(of: _aviso, matching: find.byType(ElevatedButton)), findsNothing);
      expect(find.descendant(of: _aviso, matching: find.byType(InkWell)), findsNothing);
    });

    testWidgets('el texto del aviso no usa voseo', (tester) async {
      await _montar(tester, Stream.value(const EstadoSync(bloqueo: _actualizar)));
      expect(textosConVoseo(tester), isEmpty);
    });
  });

  group('AvisoBloqueoSync - sesión vencida', () {
    testWidgets('dice que vuelva a ingresar, en color de error', (tester) async {
      await _montar(tester, Stream.value(const EstadoSync(sesionVencida: true)));

      expect(_aviso, findsOneWidget);
      expect(find.text(textoSesionVencida), findsOneWidget);
      expect(textoSesionVencida, 'Tu sesión venció: vuelve a ingresar para enviar');
      expect(_colorDelIcono(tester), AppColors.error);
      expect(tester.widget<Text>(find.text(textoSesionVencida)).style!.color, AppColors.error);
    });

    testWidgets('si además hay un bloqueo, manda la sesión vencida', (tester) async {
      await _montar(tester, Stream.value(const EstadoSync(sesionVencida: true, bloqueo: _planNoIncluye)));

      expect(find.text(textoSesionVencida), findsOneWidget);
      expect(find.text(_planNoIncluye.mensaje), findsNothing);
    });
  });

  group('AvisoBloqueoSync - cambios en vivo', () {
    testWidgets('aparece cuando el motor se bloquea y desaparece cuando se resuelve', (tester) async {
      final controlador = StreamController<EstadoSync>();
      addTearDown(controlador.close);
      await _montar(tester, controlador.stream);
      expect(_aviso, findsNothing);

      controlador.add(const EstadoSync(bloqueo: _suscripcion));
      await tester.pump();
      await tester.pump();
      expect(_aviso, findsOneWidget);
      expect(find.text(_suscripcion.mensaje), findsOneWidget);

      controlador.add(const EstadoSync(bloqueo: _actualizar));
      await tester.pump();
      await tester.pump();
      expect(find.text(_suscripcion.mensaje), findsNothing);
      expect(find.text(_actualizar.mensaje), findsOneWidget);

      controlador.add(const EstadoSync());
      await tester.pump();
      await tester.pump();
      expect(_aviso, findsNothing);
    });

    testWidgets('pasa de bloqueo a sesión vencida', (tester) async {
      final controlador = StreamController<EstadoSync>();
      addTearDown(controlador.close);
      await _montar(tester, controlador.stream);

      controlador.add(const EstadoSync(bloqueo: _planNoIncluye));
      await tester.pump();
      await tester.pump();
      expect(find.text(_planNoIncluye.mensaje), findsOneWidget);

      controlador.add(const EstadoSync(sesionVencida: true));
      await tester.pump();
      await tester.pump();
      expect(find.text(_planNoIncluye.mensaje), findsNothing);
      expect(find.text(textoSesionVencida), findsOneWidget);
    });
  });
}
