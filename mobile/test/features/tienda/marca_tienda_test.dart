import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/tienda/models/tienda.dart';
import 'package:mobile/features/tienda/presentation/marca_tienda.dart';

Future<void> _montar(WidgetTester tester, Widget marca) {
  return tester.pumpWidget(
    MaterialApp(
      home: Scaffold(appBar: AppBar(title: marca)),
    ),
  );
}

void main() {
  group('MarcaTienda', () {
    testWidgets('sin logo muestra el nombre de la tienda', (tester) async {
      await _montar(tester, const MarcaTienda(tienda: Tienda(codigo: 'chaski-sport', nombre: 'Chaski Sport')));

      expect(find.text('Chaski Sport'), findsOneWidget);
    });

    testWidgets('sin tienda muestra FashionStore', (tester) async {
      await _montar(tester, const MarcaTienda());

      expect(find.text('FashionStore'), findsOneWidget);
    });

    testWidgets('un logo vacío cae al nombre', (tester) async {
      await _montar(tester, const MarcaTienda(tienda: Tienda(codigo: 'a', nombre: 'Andina', logoUrl: '')));

      expect(find.text('Andina'), findsOneWidget);
    });

    testWidgets('respeta el estilo recibido', (tester) async {
      await _montar(
        tester,
        const MarcaTienda(tienda: Tienda(codigo: 'a', nombre: 'Andina'), estilo: TextStyle(fontSize: 31)),
      );

      final texto = tester.widget<Text>(find.text('Andina'));
      expect(texto.style?.fontSize, 31);
    });
  });
}
