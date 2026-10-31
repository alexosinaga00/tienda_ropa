import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/conectividad/conectividad_service.dart';
import 'package:mobile/core/widgets/indicador_conexion.dart';

class ConectividadFalsa implements ConectividadService {
  ConectividadFalsa({bool enLineaInicial = true}) : _actual = enLineaInicial;

  final _controlador = StreamController<bool>.broadcast();
  bool _actual;

  void poner(bool valor) {
    _actual = valor;
    _controlador.add(valor);
  }

  @override
  Stream<bool> get enLinea => _controlador.stream;

  @override
  bool get actual => _actual;

  @override
  Future<bool> verificarAhora() async => _actual;
}

const _textoBanner = 'Sin conexión. Los datos pueden estar desactualizados.';

Widget _app(ConectividadFalsa falsa, Widget hijo, {bool conBarra = false}) {
  return ProviderScope(
    overrides: [conectividadServiceProvider.overrideWithValue(falsa)],
    child: MaterialApp(
      home: Scaffold(
        appBar: conBarra ? AppBar(title: const Text('Titulo'), actions: [hijo]) : null,
        body: conBarra ? const SizedBox() : Column(children: [hijo, const Text('contenido')]),
      ),
    ),
  );
}

/// El evento pasa por el stream del servicio y por el del provider antes de llegar al widget: hacen falta dos vueltas.
Future<void> _asentar(WidgetTester tester) async {
  await tester.pump();
  await tester.pump();
}

void main() {
  group('IndicadorConexion.banner', () {
    testWidgets('sin red muestra la franja con el texto exacto y el ícono', (tester) async {
      await tester.pumpWidget(_app(ConectividadFalsa(enLineaInicial: false), const IndicadorConexion.banner()));
      await tester.pump();

      expect(find.text(_textoBanner), findsOneWidget);
      expect(find.byIcon(Icons.cloud_off), findsOneWidget);
    });

    testWidgets('con red no se ve y no ocupa espacio', (tester) async {
      await tester.pumpWidget(_app(ConectividadFalsa(), const IndicadorConexion.banner()));
      await tester.pump();

      expect(find.text(_textoBanner), findsNothing);
      expect(find.byIcon(Icons.cloud_off), findsNothing);
      expect(tester.getSize(find.byType(IndicadorConexion)), Size.zero);
    });

    testWidgets('aparece y desaparece al cambiar la conexión', (tester) async {
      final falsa = ConectividadFalsa();
      await tester.pumpWidget(_app(falsa, const IndicadorConexion.banner()));
      await tester.pump();
      expect(find.text(_textoBanner), findsNothing);

      falsa.poner(false);
      await _asentar(tester);
      expect(find.text(_textoBanner), findsOneWidget);

      falsa.poner(true);
      await _asentar(tester);
      expect(find.text(_textoBanner), findsNothing);
    });

    testWidgets('la letra mide al menos 14 y ocupa todo el ancho', (tester) async {
      await tester.pumpWidget(_app(ConectividadFalsa(enLineaInicial: false), const IndicadorConexion.banner()));
      await tester.pump();

      final texto = tester.widget<Text>(find.text(_textoBanner));
      expect(texto.style!.fontSize, greaterThanOrEqualTo(14));
      expect(tester.getSize(find.byType(IndicadorConexion)).width, tester.view.physicalSize.width / tester.view.devicePixelRatio);
    });
  });

  group('IndicadorConexion.icono', () {
    testWidgets('sin red muestra el ícono con su tooltip', (tester) async {
      await tester.pumpWidget(
        _app(ConectividadFalsa(enLineaInicial: false), const IndicadorConexion.icono(), conBarra: true),
      );
      await tester.pump();

      expect(find.byIcon(Icons.cloud_off), findsOneWidget);
      expect(find.byTooltip('Sin conexión'), findsOneWidget);
      // El ícono no lleva el texto largo del banner.
      expect(find.text(_textoBanner), findsNothing);
    });

    testWidgets('con red no muestra nada', (tester) async {
      await tester.pumpWidget(_app(ConectividadFalsa(), const IndicadorConexion.icono(), conBarra: true));
      await tester.pump();

      expect(find.byIcon(Icons.cloud_off), findsNothing);
      expect(find.byTooltip('Sin conexión'), findsNothing);
    });

    testWidgets('aparece y desaparece al cambiar la conexión', (tester) async {
      final falsa = ConectividadFalsa();
      await tester.pumpWidget(_app(falsa, const IndicadorConexion.icono(), conBarra: true));
      await tester.pump();

      falsa.poner(false);
      await _asentar(tester);
      expect(find.byIcon(Icons.cloud_off), findsOneWidget);

      falsa.poner(true);
      await _asentar(tester);
      expect(find.byIcon(Icons.cloud_off), findsNothing);
    });
  });
}
