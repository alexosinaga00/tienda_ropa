import 'package:flutter_test/flutter_test.dart';

import 'apoyo_vendedor.dart';

/// Las tarjetas del catálogo sin conexión en el inicio del personal y cuándo se dispara la descarga (E19).
void main() {
  group('InicioVendedorScreen - catálogo sin conexión', () {
    testWidgets('muestra las tarjetas "Catálogo sin conexión" y "Actualizar datos"', (tester) async {
      await abrirVendedor(tester, inicial: '/vendedor', estadoAuth: sesionDePersonal());

      expect(find.text('Catálogo sin conexión'), findsOneWidget);
      expect(find.text('Actualizar datos'), findsOneWidget);
      expect(find.text('Aún sin datos'), findsOneWidget);
      expect(find.text('Aún no hay datos descargados'), findsOneWidget);
    });

    testWidgets('lo que ya estaba sigue: saludo, cambiar de tienda y cerrar sesión', (tester) async {
      await abrirVendedor(tester, inicial: '/vendedor', estadoAuth: sesionDePersonal());

      expect(find.text('Hola, Marta'), findsOneWidget);
      expect(find.text('Cambiar de tienda'), findsOneWidget);
      expect(find.text('Cerrar sesión'), findsOneWidget);
    });

    testWidgets('al entrar con conexión descarga una vez', (tester) async {
      final e = await abrirVendedor(tester, inicial: '/vendedor', estadoAuth: sesionDePersonal());
      await tester.pump();
      await tester.pump();

      expect(e.servicioDescarga!.llamadas, 1);
      expect(e.servicioDescarga!.pedidos.single.usuarioId, sesionDePersonal().usuario!.id);
    });

    testWidgets('al entrar SIN conexión no descarga', (tester) async {
      final e = await abrirVendedor(tester, inicial: '/vendedor', enLinea: false, estadoAuth: sesionDePersonal());
      await tester.pump();
      await tester.pump();

      expect(e.servicioDescarga!.llamadas, 0);
    });

    testWidgets('tocar "Catálogo sin conexión" abre el catálogo local', (tester) async {
      await abrirVendedor(tester, inicial: '/vendedor', estadoAuth: sesionDePersonal());

      await tester.tap(find.text('Catálogo sin conexión'));
      await tester.pump();
      await tester.pump();

      // El router de prueba muestra un texto fijo en esa ruta (un push no cambia `currentConfiguration`).
      expect(find.text('PANTALLA CATALOGO'), findsOneWidget);
    });

    testWidgets('tocar "Actualizar datos" vuelve a descargar', (tester) async {
      final e = await abrirVendedor(tester, inicial: '/vendedor', estadoAuth: sesionDePersonal());
      await tester.pump();
      await tester.pump();
      expect(e.servicioDescarga!.llamadas, 1);

      await tester.tap(find.text('Actualizar datos'));
      await tester.pump();
      await tester.pump();

      expect(e.servicioDescarga!.llamadas, 2);
    });

    testWidgets('sin conexión la tarjeta "Actualizar datos" avisa y no descarga', (tester) async {
      final e = await abrirVendedor(tester, inicial: '/vendedor', enLinea: false, estadoAuth: sesionDePersonal());
      await tester.pump();

      expect(find.textContaining('Sin conexión: no se puede actualizar ahora.'), findsOneWidget);
      await tester.tap(find.text('Actualizar datos'));
      await tester.pump();

      expect(e.servicioDescarga!.llamadas, 0);
    });

    testWidgets('al volver la conexión descarga si todavía no hay datos', (tester) async {
      final e = await abrirVendedor(tester, inicial: '/vendedor', enLinea: false, estadoAuth: sesionDePersonal());
      await tester.pump();
      expect(e.servicioDescarga!.llamadas, 0);

      e.conectividad.emitir(true);
      await tester.pump();
      await tester.pump();

      expect(e.servicioDescarga!.llamadas, 1);
    });
  });
}
