import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/asistente/models/pagina_asistente.dart';
import 'package:mobile/features/asistente/presentation/asistente_screen.dart';
import 'package:mobile/features/asistente/state/asistente_controller.dart';

void main() {
  group('navegacionPermitida', () {
    test('deja pasar la propia página y los dominios de Botpress', () {
      expect(navegacionPermitida('about:blank'), isTrue);
      expect(navegacionPermitida('data:text/html;base64,PGh0bWw+'), isTrue);
      expect(navegacionPermitida('https://cdn.botpress.cloud/webchat/v3.7/inject.js'), isTrue);
      expect(navegacionPermitida('https://files.bpcontent.cloud/2026/09/19/config.js'), isTrue);
      expect(navegacionPermitida('https://botpress.cloud/'), isTrue);
    });

    test('bloquea cualquier otra dirección', () {
      expect(navegacionPermitida('https://www.google.com'), isFalse);
      expect(navegacionPermitida('http://cdn.botpress.cloud/inject.js'), isFalse); // sin https
      expect(navegacionPermitida('javascript:alert(1)'), isFalse);
      expect(navegacionPermitida('intent://scan/#Intent;scheme=zxing;end'), isFalse);
      expect(navegacionPermitida('file:///data/local/tmp/x.html'), isFalse);
    });

    test('un dominio que solo contiene el de Botpress no cuenta', () {
      expect(navegacionPermitida('https://botpress.cloud.otro.com/'), isFalse);
      expect(navegacionPermitida('https://notbotpress.cloud/'), isFalse);
      expect(navegacionPermitida('https://evilbpcontent.cloud/'), isFalse);
    });

    test('una dirección mal formada se bloquea, no revienta', () {
      expect(navegacionPermitida('http://[::1'), isFalse);
      expect(navegacionPermitida(''), isFalse);
    });
  });

  group('paginaAsistente', () {
    test('carga los dos scripts de Botpress y usa el canal que escucha la pantalla', () {
      expect(paginaAsistente, contains('src="$urlInjectBotpress"'));
      expect(paginaAsistente, contains('src="$urlConfiguracionBotpress"'));
      expect(paginaAsistente, contains("$canalAsistente.postMessage('$mensajeListo')"));
      expect(paginaAsistente, contains("$canalAsistente.postMessage('$mensajeCerrado')"));
      expect(paginaAsistente, contains("bp.on('webchat:ready'"));
      expect(paginaAsistente, contains("bp.on('webchat:closed'"));
    });
  });

  group('AsistenteController', () {
    testWidgets('arranca conectando', (tester) async {
      final controlador = AsistenteController();
      expect(controlador.state, EstadoAsistente.cargando);
      controlador.dispose();
    });

    testWidgets('alListo pasa a listo y el plazo ya no lo pasa a error', (tester) async {
      final controlador = AsistenteController(plazo: const Duration(seconds: 25));
      await tester.pump(const Duration(seconds: 5));
      controlador.alListo();
      await tester.pump(const Duration(minutes: 1));
      expect(controlador.state, EstadoAsistente.listo);
      controlador.dispose();
    });

    testWidgets('si el chat no avisa a tiempo pasa a error', (tester) async {
      final controlador = AsistenteController(plazo: const Duration(seconds: 25));
      await tester.pump(const Duration(seconds: 24));
      expect(controlador.state, EstadoAsistente.cargando);
      await tester.pump(const Duration(seconds: 2));
      expect(controlador.state, EstadoAsistente.error);
      controlador.dispose();
    });

    testWidgets('reintentar vuelve a conectar con un plazo nuevo', (tester) async {
      final controlador = AsistenteController(plazo: const Duration(seconds: 25));
      await tester.pump(const Duration(seconds: 26));
      expect(controlador.state, EstadoAsistente.error);

      controlador.reintentar();
      expect(controlador.state, EstadoAsistente.cargando);
      await tester.pump(const Duration(seconds: 20)); // el plazo viejo ya habría vencido: no cuenta
      expect(controlador.state, EstadoAsistente.cargando);
      await tester.pump(const Duration(seconds: 6));
      expect(controlador.state, EstadoAsistente.error);
      controlador.dispose();
    });

    testWidgets('un aviso tardío, después del error, se acepta', (tester) async {
      final controlador = AsistenteController(plazo: const Duration(seconds: 25));
      await tester.pump(const Duration(seconds: 30));
      expect(controlador.state, EstadoAsistente.error);

      controlador.alListo();

      expect(controlador.state, EstadoAsistente.listo);
      controlador.dispose();
    });

    testWidgets('alFallar pasa a error de inmediato', (tester) async {
      final controlador = AsistenteController();
      controlador.alFallar();
      expect(controlador.state, EstadoAsistente.error);
      controlador.dispose();
    });

    testWidgets('tras dispose no hace nada ni deja temporizadores pendientes', (tester) async {
      final controlador = AsistenteController();
      controlador.dispose();
      controlador.alListo();
      controlador.reintentar();
      // (al terminar, testWidgets falla si quedó un Timer pendiente)
    });
  });

  group('CuerpoAsistente', () {
    Future<void> montar(WidgetTester tester, EstadoAsistente estado, {VoidCallback? alReintentar}) => tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: CuerpoAsistente(
            estado: estado,
            alReintentar: alReintentar ?? () {},
            child: const Text('EL CHAT'),
          ),
        ),
      ),
    );

    testWidgets('conectando: muestra el indicador y el texto sobre el chat', (tester) async {
      await montar(tester, EstadoAsistente.cargando);

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.text('Conectando con el asistente…'), findsOneWidget);
      expect(find.text('Reintentar'), findsNothing);
    });

    testWidgets('error: muestra el mensaje y "Reintentar" llama al callback', (tester) async {
      var reintentos = 0;
      await montar(tester, EstadoAsistente.error, alReintentar: () => reintentos++);

      expect(find.textContaining('No se pudo conectar con el asistente'), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing);

      await tester.tap(find.text('Reintentar'));
      expect(reintentos, 1);
    });

    testWidgets('listo: no superpone nada, se ve el chat', (tester) async {
      await montar(tester, EstadoAsistente.listo);

      expect(find.text('EL CHAT'), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing);
      expect(find.text('Reintentar'), findsNothing);
      expect(find.byIcon(Icons.cloud_off), findsNothing);
    });

    testWidgets('el chat sigue en el árbol mientras conecta (tiene que cargar para avisar que está listo)', (tester) async {
      await montar(tester, EstadoAsistente.cargando);

      expect(find.text('EL CHAT'), findsOneWidget);
    });
  });
}
