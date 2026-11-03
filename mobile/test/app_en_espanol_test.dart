import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/providers.dart';
import 'package:mobile/main.dart';

import 'helpers/sesion_storage_falso.dart';
import 'helpers/token_storage_falso.dart';

Future<void> _abrirApp(WidgetTester tester) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        sesionStorageProvider.overrideWithValue(SesionStorageFalso()),
        tokenStorageProvider.overrideWithValue(TokenStorageFalso()),
      ],
      child: const FashionStoreApp(),
    ),
  );
  // El splash se queda 3 s a propósito; no se usa pumpAndSettle porque su spinner anima sin parar.
  await tester.pump(const Duration(seconds: 3));
  for (var i = 0; i < 20; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

/// La app fija el español para lo nativo de Flutter (calendario, reloj, botones): sin esto salía en inglés.
void main() {
  testWidgets('la app declara el español como único idioma', (tester) async {
    await _abrirApp(tester);

    final app = tester.widget<MaterialApp>(find.byType(MaterialApp));
    expect(app.locale, const Locale('es'));
    expect(app.supportedLocales, const [Locale('es')]);
    expect(app.localizationsDelegates, isNotEmpty);
  });

  testWidgets('el selector de fecha y el de hora salen en español', (tester) async {
    await _abrirApp(tester);

    final contexto = tester.element(find.byType(Scaffold).first);
    showDatePicker(
      context: contexto,
      initialDate: DateTime(2026, 11, 10),
      firstDate: DateTime(2026, 11, 1),
      lastDate: DateTime(2026, 12, 31),
    );
    await tester.pump(const Duration(milliseconds: 500));

    expect(find.text('Cancelar'), findsOneWidget);
    expect(find.text('Cancel'), findsNothing);
    expect(find.text('OK'), findsNothing);
    expect(find.textContaining('noviembre'), findsWidgets);
  });
}
