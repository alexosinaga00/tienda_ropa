import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/vendedor/models/cliente_local.dart';
import 'package:mobile/features/vendedor/presentation/selector_cliente.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';
import 'apoyo_catalogo_local.dart';
import 'apoyo_nueva_operacion.dart';
import 'apoyo_operaciones.dart' show sembrarCliente;
import 'apoyo_pantallas_sync.dart' show textosConVoseo;

Finder _buscador() => find.byKey(const Key('buscador_clientes'));

Finder _fila(int id) => find.byKey(Key('cliente_$id'));

Future<void> _base(Database db) async {
  await sembrarEmpresa(db);
}

/// Tres clientes del servidor, uno solo del teléfono (sin `servidor_id`) y uno de otra empresa. Devuelve los ids locales de
/// Ana, José y Marta, en ese orden.
Future<List<int>> _sembrarClientes(Database db) async {
  await _base(db);
  final ana = await sembrarClienteServidor(db, servidorId: 501, nombre: 'Ana', apellido: 'Pérez', ciNit: '1234567');
  final jose = await sembrarClienteServidor(db, servidorId: 502, nombre: 'José', apellido: 'Núñez', ciNit: '7654321-1B');
  final marta = await sembrarClienteServidor(db, servidorId: 503, nombre: 'Marta', apellido: null);
  await sembrarCliente(db, nombre: 'Solo Teléfono'); // sin servidor_id
  await sembrarEmpresa(db, id: 2, codigo: 'andes', nombre: 'Andes');
  await sembrarCliente(db, empresaId: 2, servidorId: 900, nombre: 'Ajeno');
  return [ana, jose, marta];
}

Future<EscenarioNuevaOperacion> _abrir(WidgetTester tester, Database db, {Size tamano = const Size(800, 1800)}) async {
  final e = await abrirAnfitrion(tester, db: db, tamano: tamano, abrir: (context, ref) => mostrarSelectorCliente(context, ref));
  await abrirSelector(tester);
  return e;
}

void main() {
  group('SelectorCliente - la lista', () {
    testWidgets('muestra solo los clientes del servidor de la empresa, ordenados por nombre', (tester) async {
      late List<int> ids;
      final db = await abrirBaseSembrada(tester, siembra: (b) async => ids = await _sembrarClientes(b));
      await _abrir(tester, db);

      expect(find.text('Elige un cliente'), findsOneWidget);
      expect(_fila(ids[0]), findsOneWidget);
      expect(_fila(ids[1]), findsOneWidget);
      expect(_fila(ids[2]), findsOneWidget);
      expect(find.text('Solo Teléfono'), findsNothing); // sin servidor_id: el backend no lo conoce
      expect(find.text('Ajeno'), findsNothing); // de otra empresa
      expect(find.byType(ListTile), findsNWidgets(3));
      expect(tester.getTopLeft(_fila(ids[0])).dy, lessThan(tester.getTopLeft(_fila(ids[1])).dy)); // Ana, José, Marta
      expect(tester.getTopLeft(_fila(ids[1])).dy, lessThan(tester.getTopLeft(_fila(ids[2])).dy));
    });

    testWidgets('cada fila lleva el nombre completo y, si tiene, el CI/NIT', (tester) async {
      late List<int> ids;
      final db = await abrirBaseSembrada(tester, siembra: (b) async => ids = await _sembrarClientes(b));
      await _abrir(tester, db);

      expect(find.descendant(of: _fila(ids[0]), matching: find.text('Ana Pérez')), findsOneWidget);
      expect(find.descendant(of: _fila(ids[0]), matching: find.text('CI/NIT: 1234567')), findsOneWidget);
      expect(find.descendant(of: _fila(ids[2]), matching: find.text('Marta')), findsOneWidget); // sin apellido
      expect(find.descendant(of: _fila(ids[2]), matching: find.textContaining('CI/NIT')), findsNothing);
    });

    testWidgets('sin clientes descargados explica que sin conexión solo valen los ya descargados', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: _base);
      await _abrir(tester, db);

      expect(find.byKey(const Key('mensaje_clientes')), findsOneWidget);
      expect(find.text(textoSinClientes), findsOneWidget);
      expect(find.textContaining('Sin conexión solo se pueden usar los clientes ya descargados'), findsOneWidget);
    });

    testWidgets('si solo hay clientes creados en el teléfono tampoco aparece ninguno', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await _base(b);
        await sembrarCliente(b, nombre: 'Solo Teléfono');
      });
      await _abrir(tester, db);

      expect(find.text('Solo Teléfono'), findsNothing);
      expect(find.text(textoSinClientes), findsOneWidget);
    });

    testWidgets('las filas miden al menos 48 de alto y el texto va en tuteo', (tester) async {
      late List<int> ids;
      final db = await abrirBaseSembrada(tester, siembra: (b) async => ids = await _sembrarClientes(b));
      await _abrir(tester, db);

      expect(tester.getSize(_fila(ids[0])).height, greaterThanOrEqualTo(48));
      expect(tester.getSize(find.widgetWithIcon(IconButton, Icons.close)).shortestSide, greaterThanOrEqualTo(48));
      expect(textosConVoseo(tester), isEmpty);
    });
  });

  group('SelectorCliente - la búsqueda', () {
    testWidgets('espera 300 ms antes de buscar (debounce)', (tester) async {
      late List<int> ids;
      final db = await abrirBaseSembrada(tester, siembra: (b) async => ids = await _sembrarClientes(b));
      await _abrir(tester, db);

      await tester.enterText(_buscador(), 'marta');
      await tester.pump(const Duration(milliseconds: 100));
      await asentar(tester);
      expect(_fila(ids[0]), findsOneWidget); // aún no filtró

      await tester.pump(const Duration(milliseconds: 250));
      await asentar(tester);
      await tester.pumpAndSettle();
      expect(_fila(ids[2]), findsOneWidget);
      expect(_fila(ids[0]), findsNothing);
    });

    testWidgets('no distingue tildes ni mayúsculas ("jose" encuentra a José, "NUNEZ" a Núñez)', (tester) async {
      late List<int> ids;
      final db = await abrirBaseSembrada(tester, siembra: (b) async => ids = await _sembrarClientes(b));
      await _abrir(tester, db);

      await buscarEscribiendo(tester, _buscador(), 'jose');
      expect(_fila(ids[1]), findsOneWidget);
      expect(_fila(ids[0]), findsNothing);

      await buscarEscribiendo(tester, _buscador(), 'NUNEZ');
      expect(_fila(ids[1]), findsOneWidget);

      await buscarEscribiendo(tester, _buscador(), 'perez');
      expect(_fila(ids[0]), findsOneWidget);
      expect(_fila(ids[1]), findsNothing);
    });

    testWidgets('busca por CI/NIT', (tester) async {
      late List<int> ids;
      final db = await abrirBaseSembrada(tester, siembra: (b) async => ids = await _sembrarClientes(b));
      await _abrir(tester, db);

      await buscarEscribiendo(tester, _buscador(), '7654321');
      expect(_fila(ids[1]), findsOneWidget);
      expect(_fila(ids[0]), findsNothing);
    });

    testWidgets('con varias palabras deben aparecer todas', (tester) async {
      late List<int> ids;
      final db = await abrirBaseSembrada(tester, siembra: (b) async => ids = await _sembrarClientes(b));
      await _abrir(tester, db);

      await buscarEscribiendo(tester, _buscador(), 'ana perez');
      expect(_fila(ids[0]), findsOneWidget);
      await buscarEscribiendo(tester, _buscador(), 'ana nunez');
      expect(find.text(textoSinClientes), findsOneWidget);
    });

    testWidgets('sin coincidencias muestra el mismo mensaje de "sin clientes"', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: _sembrarClientes);
      await _abrir(tester, db);

      await buscarEscribiendo(tester, _buscador(), 'zzzz');
      expect(find.text(textoSinClientes), findsOneWidget);
      expect(find.byType(ListTile), findsNothing);
    });

    testWidgets('"Borrar búsqueda" devuelve la lista completa', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: _sembrarClientes);
      await _abrir(tester, db);

      await buscarEscribiendo(tester, _buscador(), 'ana');
      expect(find.byType(ListTile), findsOneWidget);
      await tester.tap(find.byTooltip('Borrar búsqueda'));
      await esperar(tester);
      expect(find.byType(ListTile), findsNWidgets(3));
    });

    testWidgets('una búsqueda con % o _ se toma como texto, no como comodín', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: _sembrarClientes);
      await _abrir(tester, db);

      await buscarEscribiendo(tester, _buscador(), '%');
      expect(find.text(textoSinClientes), findsOneWidget);
      await buscarEscribiendo(tester, _buscador(), '_');
      expect(find.text(textoSinClientes), findsOneWidget);
    });
  });

  group('SelectorCliente - paginación', () {
    testWidgets('lee de a $tamanoPaginaClientes y carga más al desplazarse', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await _base(b);
        for (var i = 1; i <= 25; i++) {
          await sembrarClienteServidor(b, servidorId: 1000 + i, nombre: 'Cliente ${i.toString().padLeft(2, '0')}', apellido: null);
        }
      });
      await _abrir(tester, db, tamano: const Size(800, 700));

      expect(find.text('Cliente 25'), findsNothing);
      for (var i = 0; i < 20 && find.text('Cliente 25').evaluate().isEmpty; i++) {
        await tester.drag(find.byType(ListView).first, const Offset(0, -500));
        await tester.pump();
        await asentar(tester);
      }
      await tester.pumpAndSettle();
      expect(find.text('Cliente 25'), findsOneWidget);
    });

    testWidgets('con menos de una página no pide más', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: _sembrarClientes);
      await _abrir(tester, db);

      await tester.drag(find.byType(ListView).first, const Offset(0, -300));
      await esperar(tester);
      expect(find.byType(ListTile), findsNWidgets(3));
    });
  });

  group('SelectorCliente - el resultado', () {
    testWidgets('elegir devuelve el cliente con su id local y el del servidor', (tester) async {
      late List<int> ids;
      final db = await abrirBaseSembrada(tester, siembra: (b) async => ids = await _sembrarClientes(b));
      final e = await _abrir(tester, db);

      await tester.tap(_fila(ids[1]));
      await tester.pumpAndSettle();

      final elegido = e.resultados.single! as ClienteLocal;
      expect(elegido.id, ids[1]);
      expect(elegido.servidorId, 502);
      expect(elegido.nombreCompleto, 'José Núñez');
      expect(elegido.ciNit, '7654321-1B');
      expect(find.text('Elige un cliente'), findsNothing); // la hoja se cerró
    });

    testWidgets('elegir un cliente que apareció por una búsqueda también lo devuelve', (tester) async {
      late List<int> ids;
      final db = await abrirBaseSembrada(tester, siembra: (b) async => ids = await _sembrarClientes(b));
      final e = await _abrir(tester, db);

      await buscarEscribiendo(tester, _buscador(), 'marta');
      await tester.tap(_fila(ids[2]));
      await tester.pumpAndSettle();
      expect((e.resultados.single! as ClienteLocal).servidorId, 503);
    });

    testWidgets('cerrar sin elegir devuelve null', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: _sembrarClientes);
      final e = await _abrir(tester, db);

      await tester.tap(find.byTooltip('Cerrar'));
      await tester.pumpAndSettle();
      expect(e.resultados, [null]);
    });
  });
}
