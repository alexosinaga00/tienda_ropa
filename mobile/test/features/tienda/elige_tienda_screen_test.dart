import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/tienda/models/tienda.dart';
import 'package:mobile/features/tienda/state/tienda_controller.dart';

import '../../helpers/api_client_falso.dart';
import 'apoyo_tienda.dart';

ApiClientFalso _apiConDosTiendas() {
  return ApiClientFalso()
    ..responder('GET', rutaListaTiendas, [
      jsonTienda('chaski-sport', 'Chaski Sport', color: '#C0392B'),
      jsonTienda('boutique-andina', 'Boutique Andina', color: 'rojo-feo'),
    ]);
}

void main() {
  group('EligeTiendaScreen', () {
    testWidgets('muestra una tarjeta por tienda con su nombre y su código', (tester) async {
      await abrirEscenario(tester, _apiConDosTiendas());

      expect(find.text('Elige tu tienda'), findsOneWidget);
      expect(find.text('Chaski Sport'), findsOneWidget);
      expect(find.text('chaski-sport'), findsOneWidget);
      expect(find.text('Boutique Andina'), findsOneWidget);
      expect(find.text('boutique-andina'), findsOneWidget);
    });

    testWidgets('muestra el esqueleto mientras carga', (tester) async {
      final api = ApiLento()
        ..responder('GET', rutaListaTiendas, [jsonTienda('chaski-sport', 'Chaski Sport')]);
      await abrirEscenario(tester, api);
      expect(find.byKey(const Key('esqueleto_tiendas')), findsOneWidget);
      expect(find.text('Chaski Sport'), findsNothing);

      api.puerta.complete();
      await tester.pump();
      await tester.pump();
      expect(find.byKey(const Key('esqueleto_tiendas')), findsNothing);
      expect(find.text('Chaski Sport'), findsOneWidget);
    });

    testWidgets('sin logo dibuja el monograma con las siglas de la tienda', (tester) async {
      await abrirEscenario(tester, _apiConDosTiendas());

      expect(find.text('CS'), findsOneWidget);
      // Color inválido: usa el acento por defecto, pero igual hay monograma.
      expect(find.text('BA'), findsOneWidget);
    });

    testWidgets('la búsqueda espera 400 ms y llama a la API con q', (tester) async {
      final api = _apiConDosTiendas()
        ..responder('GET', rutaListaTiendas, [jsonTienda('chaski-sport', 'Chaski Sport')]);
      await abrirEscenario(tester, api);
      expect(api.de('GET', rutaListaTiendas), hasLength(1));

      await tester.enterText(find.byType(TextField), 'chas');
      await tester.pump(const Duration(milliseconds: 200));
      expect(api.de('GET', rutaListaTiendas), hasLength(1), reason: 'todavía no pasó el debounce');

      await tester.pump(const Duration(milliseconds: 250));
      await tester.pump();
      final llamadas = api.de('GET', rutaListaTiendas);
      expect(llamadas, hasLength(2));
      expect(llamadas.last.query?['q'], 'chas');
      expect(find.text('Boutique Andina'), findsNothing);
      expect(find.text('Chaski Sport'), findsOneWidget);
    });

    testWidgets('varias teclas seguidas hacen una sola consulta', (tester) async {
      final api = _apiConDosTiendas();
      await abrirEscenario(tester, api);

      await tester.enterText(find.byType(TextField), 'c');
      await tester.pump(const Duration(milliseconds: 300));
      await tester.enterText(find.byType(TextField), 'ch');
      await tester.pump(const Duration(milliseconds: 300));
      expect(api.de('GET', rutaListaTiendas), hasLength(1));
      await tester.pump(const Duration(milliseconds: 150));
      await tester.pump();
      expect(api.de('GET', rutaListaTiendas), hasLength(2));
      expect(api.de('GET', rutaListaTiendas).last.query?['q'], 'ch');
    });

    testWidgets('tocar una tarjeta guarda la tienda y abre el catálogo', (tester) async {
      final escenario = await abrirEscenario(tester, _apiConDosTiendas());

      await tester.tap(find.text('Chaski Sport'));
      await tester.pumpAndSettle();

      expect(find.text('HOME'), findsOneWidget);
      expect(escenario.storage.tienda?.codigo, 'chaski-sport');
      expect(escenario.contenedor.read(tiendaActualProvider)?.nombre, 'Chaski Sport');
    });

    testWidgets('sin resultados muestra el mensaje de búsqueda vacía', (tester) async {
      final api = ApiClientFalso()..responder('GET', rutaListaTiendas, <Map<String, dynamic>>[]);
      await abrirEscenario(tester, api);

      expect(find.text('No encontramos tiendas con ese nombre'), findsOneWidget);
    });

    testWidgets('sin conexión ofrece Reintentar, que vuelve a pedir la lista', (tester) async {
      final api = ApiClientFalso()
        ..responder('GET', rutaListaTiendas, errorSinConexion)
        ..responder('GET', rutaListaTiendas, [jsonTienda('chaski-sport', 'Chaski Sport')]);
      await abrirEscenario(tester, api);

      expect(find.text('Sin conexión. Revisa tu internet e intenta de nuevo.'), findsOneWidget);
      expect(find.byIcon(Icons.cloud_off_outlined), findsOneWidget);
      expect(find.textContaining('Volver a'), findsNothing);

      await tester.tap(find.text('Reintentar'));
      await tester.pump();
      await tester.pump();

      expect(api.de('GET', rutaListaTiendas), hasLength(2));
      expect(find.text('Chaski Sport'), findsOneWidget);
    });

    testWidgets('sin conexión y con tienda guardada ofrece "Volver a {nombre}"', (tester) async {
      final api = ApiClientFalso()..responder('GET', rutaListaTiendas, errorSinConexion);
      final escenario = await abrirEscenario(
        tester,
        api,
        guardada: const Tienda(codigo: 'chaski-sport', nombre: 'Chaski Sport'),
      );

      expect(find.text('Volver a Chaski Sport'), findsOneWidget);
      await tester.tap(find.text('Volver a Chaski Sport'));
      await tester.pumpAndSettle();

      expect(find.text('HOME'), findsOneWidget);
      expect(escenario.storage.tienda?.codigo, 'chaski-sport');
    });

    testWidgets('otro error muestra el texto por defecto y Reintentar', (tester) async {
      final api = ApiClientFalso()
        ..responder('GET', rutaListaTiendas, StateError('algo raro'))
        ..responder('GET', rutaListaTiendas, [jsonTienda('chaski-sport', 'Chaski Sport')]);
      await abrirEscenario(tester, api);

      expect(find.text('No se pudieron cargar las tiendas.'), findsOneWidget);
      expect(find.text('Reintentar'), findsOneWidget);
      expect(find.byIcon(Icons.cloud_off_outlined), findsNothing);
    });

    testWidgets('muestra el aviso del controlador una sola vez y lo limpia', (tester) async {
      final escenario = await abrirEscenario(
        tester,
        _apiConDosTiendas(),
        aviso: avisoTiendaDesaparecida,
      );
      await tester.pump();
      await tester.pump();

      expect(find.text(avisoTiendaDesaparecida), findsOneWidget);
      expect(find.byIcon(Icons.info_outline), findsOneWidget);
      expect(escenario.contenedor.read(tiendaControllerProvider).aviso, isNull);
    });

    testWidgets('sin aviso no hay franja de información', (tester) async {
      await abrirEscenario(tester, _apiConDosTiendas());

      expect(find.byIcon(Icons.info_outline), findsNothing);
    });

    testWidgets('la flecha de volver solo aparece cuando hay a dónde volver', (tester) async {
      await abrirEscenario(tester, _apiConDosTiendas());
      expect(find.byType(BackButton), findsNothing);
    });

    testWidgets('con una pantalla anterior muestra la flecha y vuelve', (tester) async {
      final api = _apiConDosTiendas();
      await abrirEscenario(tester, api, inicial: '/home', empujarTienda: true);

      expect(find.byType(BackButton), findsOneWidget);
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();
      expect(find.text('HOME'), findsOneWidget);
    });
  });
}
