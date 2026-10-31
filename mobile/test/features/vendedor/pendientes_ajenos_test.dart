import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/vendedor/presentation/aviso_pendientes_ajenos.dart';
import 'package:mobile/features/vendedor/state/catalogo_local_providers.dart';
import 'package:mobile/features/vendedor/state/pendientes_providers.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';
import 'apoyo_operaciones.dart';

Future<void> _montar(WidgetTester tester, Override pendientes) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [pendientes],
      child: const MaterialApp(home: Scaffold(body: Column(children: [AvisoPendientesAjenos(), Text('RESTO')]))),
    ),
  );
  await tester.pump();
}

void main() {
  group('AvisoPendientesAjenos (widget)', () {
    testWidgets('con 0 no muestra nada', (tester) async {
      await _montar(tester, pendientesAjenosProvider.overrideWith((ref) async => 0));

      expect(find.textContaining('pendiente'), findsNothing);
      expect(find.byIcon(Icons.info_outline), findsNothing);
      expect(find.text('RESTO'), findsOneWidget);
    });

    testWidgets('con 1 usa el singular', (tester) async {
      await _montar(tester, pendientesAjenosProvider.overrideWith((ref) async => 1));

      expect(
        find.text('Hay 1 operación pendiente de otro usuario. Ingresa con esa cuenta para enviarlas.'),
        findsOneWidget,
      );
      expect(find.textContaining('1 operaciones'), findsNothing);
    });

    testWidgets('con 3 usa el plural', (tester) async {
      await _montar(tester, pendientesAjenosProvider.overrideWith((ref) async => 3));

      expect(
        find.text('Hay 3 operaciones pendientes de otro usuario. Ingresa con esa cuenta para enviarlas.'),
        findsOneWidget,
      );
    });

    testWidgets('es una franja ámbar de ancho completo con un ícono de información', (tester) async {
      await _montar(tester, pendientesAjenosProvider.overrideWith((ref) async => 2));

      final franja = tester.widget<Container>(find.ancestor(of: find.byIcon(Icons.info_outline), matching: find.byType(Container)).first);
      expect(franja.color, const Color(0xFFFFF3CD));
      expect(tester.getSize(find.byType(AvisoPendientesAjenos)).width, tester.view.physicalSize.width / tester.view.devicePixelRatio);
      expect(tester.getSize(find.byIcon(Icons.info_outline)).width, greaterThanOrEqualTo(20));
    });

    testWidgets('mientras se calcula no muestra nada', (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [pendientesAjenosProvider.overrideWith((ref) => Future<int>.delayed(const Duration(seconds: 1), () => 4))],
          child: const MaterialApp(home: Scaffold(body: AvisoPendientesAjenos())),
        ),
      );
      await tester.pump();
      expect(find.textContaining('Hay '), findsNothing);

      await tester.pump(const Duration(seconds: 2));
      expect(find.textContaining('Hay 4 operaciones'), findsOneWidget);
    });

    testWidgets('si el cálculo falla no muestra nada ni rompe la pantalla', (tester) async {
      await _montar(tester, pendientesAjenosProvider.overrideWith((ref) async => throw StateError('falló')));

      expect(find.textContaining('Hay '), findsNothing);
      expect(find.text('RESTO'), findsOneWidget);
    });

    testWidgets('se actualiza cuando cambia el valor del provider', (tester) async {
      await _montar(tester, pendientesAjenosProvider.overrideWith((ref) async => 2));
      expect(find.textContaining('Hay 2 operaciones'), findsOneWidget);

      final contenedor = ProviderScope.containerOf(tester.element(find.byType(AvisoPendientesAjenos)));
      contenedor.invalidate(pendientesAjenosProvider);
      await tester.pump();
      await tester.pump();

      expect(find.textContaining('Hay 2 operaciones'), findsOneWidget);
    });
  });

  group('textoPendientesAjenos', () {
    test('singular y plural', () {
      expect(textoPendientesAjenos(1), contains('1 operación pendiente de otro usuario'));
      expect(textoPendientesAjenos(2), contains('2 operaciones pendientes de otro usuario'));
      expect(textoPendientesAjenos(12), contains('12 operaciones pendientes'));
    });
  });

  group('pendientesAjenosProvider', () {
    late Database db;

    setUp(() async {
      db = await abrirBaseDePrueba();
      addTearDown(db.close);
      await sembrarDosEmpresas(db);
    });

    test('sin sesión es 0', () async {
      await sembrarOperacion(db, id: 'ajena', usuarioId: 8, estado: 'registrada');
      final contenedor = contenedorLocal(db);

      expect(await contenedor.read(pendientesAjenosProvider.future), 0);
    });

    test('cuenta las pendientes de otros usuarios de la empresa de la sesión', () async {
      await sembrarOperacion(db, id: 'mia', estado: 'registrada');
      await sembrarOperacion(db, id: 'o8', usuarioId: 8, estado: 'registrada');
      await sembrarOperacion(db, id: 'o9', usuarioId: 9, estado: 'en_conflicto');
      await sembrarOperacion(db, id: 'o8-ok', usuarioId: 8, estado: 'confirmada');
      await sembrarOperacion(db, id: 'e2', empresaId: 2, sucursalId: 11, varianteId: 200, usuarioId: 8, estado: 'registrada');
      final contenedor = contenedorLocal(db, auth: sesionDe(personalDe()));

      expect(await contenedor.read(pendientesAjenosProvider.future), 2);
    });

    test('otra empresa de la sesión cuenta su propia partición', () async {
      await sembrarOperacion(db, id: 'e2', empresaId: 2, sucursalId: 11, varianteId: 200, usuarioId: 8, estado: 'enviada');
      final contenedor = contenedorLocal(db, auth: sesionDe(personalDe(empresaId: 2, codigo: 'andina')));

      expect(await contenedor.read(pendientesAjenosProvider.future), 1);
    });

    test('se recalcula cuando termina una descarga', () async {
      final contenedor = contenedorLocal(db, auth: sesionDe(personalDe()));
      expect(await contenedor.read(pendientesAjenosProvider.future), 0);

      await sembrarOperacion(db, id: 'o8', usuarioId: 8, estado: 'registrada');
      contenedor.read(descargaTerminadaProvider.notifier).state++;

      expect(await contenedor.read(pendientesAjenosProvider.future), 1);
    });

    test('ante un error de la base responde 0', () async {
      final contenedor = ProviderContainer(
        overrides: [
          baseLocalProvider.overrideWith((ref) async => throw StateError('no abre')),
          authControllerProvider.overrideWith((ref) => AuthControllerFijo(ref, sesionDe(personalDe()))),
        ],
      );
      addTearDown(contenedor.dispose);

      // Con sesión sí intenta contar; el error de la base no se propaga.
      expect(await contenedor.read(pendientesAjenosProvider.future), 0);
    });
  });

  group('politicaLimpiezaLocalProvider', () {
    test('construye la política sobre la base local', () async {
      final db = await abrirBaseDePrueba();
      addTearDown(db.close);
      await sembrarDosEmpresas(db);
      final contenedor = contenedorLocal(db);

      final politica = await contenedor.read(politicaLimpiezaLocalProvider.future);
      final r = await politica.alCerrarSesion(empresaId: 1, usuarioId: 7);

      expect(r.pendientes, 0);
      expect(r.purgo, isTrue);
    });

    test('si la base no abre, el futuro falla (quien lo usa debe capturarlo)', () async {
      final contenedor = ProviderContainer(
        overrides: [baseLocalProvider.overrideWith((ref) async => throw StateError('no abre'))],
      );
      addTearDown(contenedor.dispose);

      await expectLater(contenedor.read(politicaLimpiezaLocalProvider.future), throwsStateError);
    });
  });
}
