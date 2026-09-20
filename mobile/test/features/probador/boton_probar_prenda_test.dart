import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/features/probador/models/activo_probador.dart';
import 'package:mobile/features/probador/presentation/boton_probar_prenda.dart';
import 'package:mobile/features/probador/state/probador_providers.dart';

AssetsVariante _assets() => AssetsVariante(
  overlay: const ActivoProbador(
    id: 1,
    varianteId: 7,
    tipo: 'overlay_2d',
    publicId: 'p7',
    url: 'https://ejemplo.test/7.png',
    anclajes: null,
    anchoPx: 100,
    altoPx: 100,
    estado: 'validado',
  ),
  flatlay: null,
);

/// Monta el botón para la variante 7; `consulta` es lo que responde la consulta de assets (datos, null, error o
/// una que nunca termina).
Future<void> _abrir(
  WidgetTester tester, {
  required Future<AssetsVariante?> Function() consulta,
  bool compacto = false,
  bool avisarSiNoHay = false,
}) async {
  final router = GoRouter(
    routes: [
      GoRoute(
        path: '/',
        builder: (context, state) =>
            Scaffold(body: BotonProbarPrenda(varianteId: 7, compacto: compacto, avisarSiNoHay: avisarSiNoHay)),
      ),
      GoRoute(
        path: '/probador',
        builder: (context, state) =>
            Scaffold(body: Text('PROBADOR con variante ${state.uri.queryParameters['variante']}')),
      ),
    ],
  );
  await tester.pumpWidget(
    ProviderScope(
      overrides: [assetsProbadorProvider(7).overrideWith((ref) => consulta())],
      child: MaterialApp.router(routerConfig: router),
    ),
  );
  await tester.pump();
}

void main() {
  group('BotonProbarPrenda', () {
    testWidgets('con overlay muestra el botón y abre el probador con esa variante', (tester) async {
      await _abrir(tester, consulta: () async => _assets());

      expect(find.text('Probar en el probador virtual'), findsOneWidget);
      await tester.tap(find.text('Probar en el probador virtual'));
      await tester.pumpAndSettle();

      expect(find.text('PROBADOR con variante 7'), findsOneWidget);
    });

    testWidgets('en el carrito (compacto) es un "Probar" chico que abre el probador con esa línea', (tester) async {
      await _abrir(tester, consulta: () async => _assets(), compacto: true);

      expect(find.text('Probar en el probador virtual'), findsNothing);
      await tester.tap(find.text('Probar'));
      await tester.pumpAndSettle();

      expect(find.text('PROBADOR con variante 7'), findsOneWidget);
    });

    testWidgets('sin overlay no muestra el botón', (tester) async {
      await _abrir(tester, consulta: () async => null);

      expect(find.byType(OutlinedButton), findsNothing);
      expect(find.byType(TextButton), findsNothing);
      expect(find.text('Esta variante aún no tiene probador'), findsNothing);
    });

    testWidgets('sin overlay, el detalle (avisarSiNoHay) lo explica en vez de callar', (tester) async {
      await _abrir(tester, consulta: () async => null, avisarSiNoHay: true);

      expect(find.text('Esta variante aún no tiene probador'), findsOneWidget);
      expect(find.byType(OutlinedButton), findsNothing);
    });

    testWidgets('mientras consulta, o si la consulta falla, no muestra nada ni un error', (tester) async {
      await _abrir(tester, consulta: () => Completer<AssetsVariante?>().future, avisarSiNoHay: true);
      expect(find.byType(OutlinedButton), findsNothing);
      expect(find.text('Esta variante aún no tiene probador'), findsNothing);

      await _abrir(
        tester,
        consulta: () => Future<AssetsVariante?>.error(Exception('sin red')),
        avisarSiNoHay: true,
      );
      expect(find.byType(OutlinedButton), findsNothing);
      expect(find.text('Esta variante aún no tiene probador'), findsNothing);
      expect(tester.takeException(), isNull);
    });
  });
}
