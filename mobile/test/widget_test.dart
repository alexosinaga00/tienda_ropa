import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/providers.dart';
import 'package:mobile/features/tienda/models/tienda.dart';
import 'package:mobile/main.dart';

import 'helpers/sesion_storage_falso.dart';
import 'helpers/token_storage_falso.dart';

Future<void> _esperarSplash(WidgetTester tester) async {
  // El splash se queda 3 s a propósito para que se vea el logo; se espera ese tiempo y luego la transición. No se usa
  // pumpAndSettle porque el spinner del splash anima indefinidamente.
  await tester.pump(const Duration(seconds: 3));
  for (var i = 0; i < 20; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

void main() {
  testWidgets('con tienda guardada y sin sesión, la app termina en el catálogo (invitado)', (WidgetTester tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tokenStorageProvider.overrideWithValue(TokenStorageFalso()),
          // Ajuste de E18: sin una tienda elegida la app va a "Elige tu tienda"; con una guardada llega al catálogo.
          sesionStorageProvider.overrideWithValue(
            SesionStorageFalso(tienda: const Tienda(codigo: 'fashionstore', nombre: 'FashionStore')),
          ),
        ],
        child: const FashionStoreApp(),
      ),
    );

    // restaurarSesion() resuelve a "no autenticado" y el router redirige de /splash a /home: el catálogo es público
    // para invitados (ver app_router.dart).
    await _esperarSplash(tester);

    expect(find.byTooltip('Probador virtual'), findsOneWidget);
  });

  testWidgets('sin tienda guardada, la app termina en Elige tu tienda', (WidgetTester tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tokenStorageProvider.overrideWithValue(TokenStorageFalso()),
          sesionStorageProvider.overrideWithValue(SesionStorageFalso()),
        ],
        child: const FashionStoreApp(),
      ),
    );

    await _esperarSplash(tester);

    expect(find.text('Elige tu tienda'), findsWidgets);
    expect(find.byTooltip('Probador virtual'), findsNothing);
  });
}
