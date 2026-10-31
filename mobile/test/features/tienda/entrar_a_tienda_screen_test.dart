import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../helpers/api_client_falso.dart';
import 'apoyo_tienda.dart';

void main() {
  group('EntrarATiendaScreen', () {
    testWidgets('una tienda existente se guarda y abre el catálogo', (tester) async {
      final api = ApiClientFalso()
        ..responder('GET', rutaTienda('chaski-sport'), jsonTienda('chaski-sport', 'Chaski Sport', disponible: true));
      final escenario = await abrirEscenario(tester, api, inicial: '/t/chaski-sport');
      await tester.pumpAndSettle();

      expect(find.text('HOME'), findsOneWidget);
      expect(escenario.storage.tienda?.codigo, 'chaski-sport');
      expect(api.de('GET', rutaTienda('chaski-sport')), hasLength(1));
    });

    testWidgets('mientras responde muestra "Abriendo tienda…"', (tester) async {
      final api = ApiLento()
        ..responder('GET', rutaTienda('chaski-sport'), jsonTienda('chaski-sport', 'Chaski Sport'));
      final escenario = await abrirEscenario(tester, api, inicial: '/t/chaski-sport');

      expect(find.text('Abriendo tienda…'), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(escenario.storage.tienda, isNull);

      api.puerta.complete();
      await tester.pumpAndSettle();
      expect(find.text('HOME'), findsOneWidget);
      expect(escenario.storage.tienda?.codigo, 'chaski-sport');
    });

    testWidgets('una tienda que no existe (404) vuelve a /tienda con un aviso', (tester) async {
      final api = ApiClientFalso()
        ..responder('GET', rutaTienda('no-existe'), errorNoEncontrado)
        ..responder('GET', rutaListaTiendas, [jsonTienda('chaski-sport', 'Chaski Sport')]);
      final escenario = await abrirEscenario(tester, api, inicial: '/t/no-existe');
      await tester.pumpAndSettle();

      expect(find.text('Elige tu tienda'), findsOneWidget);
      expect(find.text('Esa tienda no está disponible.'), findsOneWidget);
      expect(escenario.storage.tienda, isNull);
    });

    testWidgets('una tienda sin suscripción activa no se guarda y vuelve a /tienda', (tester) async {
      final api = ApiClientFalso()
        ..responder('GET', rutaTienda('vencida'), jsonTienda('vencida', 'Vencida', disponible: false))
        ..responder('GET', rutaListaTiendas, [jsonTienda('chaski-sport', 'Chaski Sport')]);
      final escenario = await abrirEscenario(tester, api, inicial: '/t/vencida');
      await tester.pumpAndSettle();

      expect(find.text('Elige tu tienda'), findsOneWidget);
      expect(find.text('Esa tienda no está disponible.'), findsOneWidget);
      expect(escenario.storage.tienda, isNull);
    });

    testWidgets('sin conexión muestra Reintentar y Elegir otra tienda', (tester) async {
      final api = ApiClientFalso()..responder('GET', rutaTienda('chaski-sport'), errorSinConexion);
      await abrirEscenario(tester, api, inicial: '/t/chaski-sport');
      await tester.pumpAndSettle();

      expect(find.text('Sin conexión. Revisa tu internet e intenta de nuevo.'), findsOneWidget);
      expect(find.text('Reintentar'), findsOneWidget);
      expect(find.text('Elegir otra tienda'), findsOneWidget);
      expect(find.text('HOME'), findsNothing);
    });

    testWidgets('Reintentar vuelve a pedir la tienda y, si responde, entra', (tester) async {
      final api = ApiClientFalso()
        ..responder('GET', rutaTienda('chaski-sport'), errorSinConexion)
        ..responder('GET', rutaTienda('chaski-sport'), jsonTienda('chaski-sport', 'Chaski Sport'));
      final escenario = await abrirEscenario(tester, api, inicial: '/t/chaski-sport');
      await tester.pumpAndSettle();

      await tester.tap(find.text('Reintentar'));
      await tester.pumpAndSettle();

      expect(find.text('HOME'), findsOneWidget);
      expect(escenario.storage.tienda?.codigo, 'chaski-sport');
      expect(api.de('GET', rutaTienda('chaski-sport')), hasLength(2));
    });

    testWidgets('Elegir otra tienda lleva a la lista', (tester) async {
      final api = ApiClientFalso()
        ..responder('GET', rutaTienda('chaski-sport'), errorSinConexion)
        ..responder('GET', rutaListaTiendas, [jsonTienda('chaski-sport', 'Chaski Sport')]);
      await abrirEscenario(tester, api, inicial: '/t/chaski-sport');
      await tester.pumpAndSettle();

      await tester.tap(find.text('Elegir otra tienda'));
      await tester.pumpAndSettle();

      expect(find.text('Elige tu tienda'), findsOneWidget);
    });
  });
}
