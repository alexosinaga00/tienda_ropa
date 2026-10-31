import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/vendedor/presentation/selector_sucursal_activa.dart';

import 'apoyo_catalogo_local.dart';

Future<String?> _sucursalGuardada(WidgetTester tester, EscenarioCatalogoLocal e) async {
  final filas = await enBase(tester, e.db, (db) => db.query('meta', where: 'clave = ?', whereArgs: ['sucursal_activa:1:7']));
  return filas.isEmpty ? null : filas.first['valor'] as String?;
}

void main() {
  group('SelectorSucursalActiva', () {
    testWidgets('sin ninguna sucursal descargada muestra "Sin sucursal"', (tester) async {
      final db = await abrirBaseSembrada(tester);
      await abrirComponente(tester, db: db, hijo: const SelectorSucursalActiva());

      expect(find.text('Sin sucursal'), findsOneWidget);
      expect(find.byType(PopupMenuButton<int>), findsNothing);
    });

    testWidgets('con una sola sucursal autorizada muestra solo su nombre', (tester) async {
      final db = await abrirBaseSembrada(
        tester,
        siembra: (b) async {
          await sembrarEscenarioBasico(b);
          await b.delete('sucursal_autorizada', where: 'sucursal_id = 2');
        },
      );
      await abrirComponente(tester, db: db, hijo: const SelectorSucursalActiva());

      expect(find.text('Centro'), findsOneWidget);
      expect(find.byType(PopupMenuButton<int>), findsNothing);
    });

    testWidgets('con varias muestra la activa y un menú con todas', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirComponente(tester, db: db, hijo: const SelectorSucursalActiva());

      expect(find.text('Centro'), findsOneWidget);
      expect(find.byType(PopupMenuButton<int>), findsOneWidget);

      await tester.tap(find.byType(PopupMenuButton<int>));
      await tester.pumpAndSettle();

      expect(find.text('Centro'), findsNWidgets(2)); // el botón y la opción
      expect(find.text('Norte'), findsOneWidget);
    });

    testWidgets('el depósito se marca "(depósito)"', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) => sembrarEscenarioBasico(b, depositoNorte: true));
      await abrirComponente(tester, db: db, hijo: const SelectorSucursalActiva());

      await tester.tap(find.byType(PopupMenuButton<int>));
      await tester.pumpAndSettle();

      expect(find.text('Norte (depósito)'), findsOneWidget);
      expect(find.text('Centro'), findsNWidgets(2));
    });

    testWidgets('sin elegir nada la activa es la primera que no es depósito', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b, depositoNorte: true);
        // Con el nombre "Almacén" el depósito iría primero por orden alfabético si no se descartara.
        await b.update('sucursal', {'nombre': 'Almacén'}, where: 'id = 2');
      });
      await abrirComponente(tester, db: db, hijo: const SelectorSucursalActiva());

      expect(find.text('Centro'), findsOneWidget);
    });

    testWidgets('elegir otra sucursal ya descargada la guarda y no vuelve a descargar', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) => sembrarEscenarioBasico(b, descargaNorte: true));
      final e = await abrirComponente(tester, db: db, hijo: const SelectorSucursalActiva());

      await tester.tap(find.byType(PopupMenuButton<int>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Norte'));
      await tester.pumpAndSettle();
      await asentar(tester);

      expect(find.text('Norte'), findsOneWidget);
      expect(find.text('Centro'), findsNothing);
      expect(await _sucursalGuardada(tester, e), '2');
      expect(e.servicio.llamadas, 0);
    });

    testWidgets('elegir una sucursal que nunca se descargó, con conexión, la descarga', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      final e = await abrirComponente(tester, db: db, hijo: const SelectorSucursalActiva());

      await tester.tap(find.byType(PopupMenuButton<int>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Norte'));
      await tester.pumpAndSettle();
      await asentar(tester);

      expect(e.servicio.llamadas, 1);
      expect(e.servicio.pedidos.single.sucursalId, 2);
      expect(await _sucursalGuardada(tester, e), '2');
      expect(find.text('Norte'), findsOneWidget);
    });

    testWidgets('sin conexión cambia de sucursal sin intentar descargar', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      final e = await abrirComponente(tester, db: db, hijo: const SelectorSucursalActiva(), enLinea: false);

      await tester.tap(find.byType(PopupMenuButton<int>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Norte'));
      await tester.pumpAndSettle();
      await asentar(tester);

      expect(e.servicio.llamadas, 0);
      expect(await _sucursalGuardada(tester, e), '2');
      expect(find.text('Norte'), findsOneWidget);
    });

    testWidgets('elegir la sucursal que ya está activa no hace nada', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      final e = await abrirComponente(tester, db: db, hijo: const SelectorSucursalActiva());

      await tester.tap(find.byType(PopupMenuButton<int>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Centro').last);
      await tester.pumpAndSettle();
      await asentar(tester);

      expect(e.servicio.llamadas, 0);
      expect(await _sucursalGuardada(tester, e), isNull);
    });

    testWidgets('respeta la sucursal que la persona había elegido antes', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b, descargaNorte: true);
        await b.insert('meta', {'clave': 'sucursal_activa:1:7', 'valor': '2'});
      });
      await abrirComponente(tester, db: db, hijo: const SelectorSucursalActiva());

      expect(find.text('Norte'), findsOneWidget);
    });

    testWidgets('el área tocable mide al menos 48 de alto', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirComponente(tester, db: db, hijo: const SelectorSucursalActiva());

      expect(tester.getSize(find.byType(PopupMenuButton<int>)).height, greaterThanOrEqualTo(48));
    });
  });
}
