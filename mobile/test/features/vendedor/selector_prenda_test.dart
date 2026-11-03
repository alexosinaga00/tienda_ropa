import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/theme/app_theme.dart';
import 'package:mobile/features/vendedor/presentation/nivel_existencia.dart';
import 'package:mobile/features/vendedor/presentation/selector_prenda.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';
import 'apoyo_catalogo_local.dart';
import 'apoyo_nueva_operacion.dart';
import 'apoyo_pantallas_sync.dart' show textosConVoseo;

Finder _fila(int id) => find.byKey(Key('prenda_$id'));

/// El nombre de la prenda como título de la fila (el recuadro sin foto repite el nombre: se distingue por el estilo).
Finder _nombreEnFila(int id, String nombre) => find.descendant(
  of: _fila(id),
  matching: find.byWidgetPredicate((w) => w is Text && w.data == nombre && w.style?.fontWeight == FontWeight.w600),
);

Finder _enFila(int id, String texto) => find.descendant(of: _fila(id), matching: find.text(texto));

Finder _buscador() => find.byKey(const Key('buscador_prendas'));

/// Monta un anfitrión con el botón "Abrir" y abre el selector de la sucursal [sucursalId].
Future<EscenarioNuevaOperacion> _abrir(
  WidgetTester tester,
  Database db, {
  int sucursalId = 1,
  Size tamano = const Size(800, 1800),
}) async {
  final e = await abrirAnfitrion(
    tester,
    db: db,
    tamano: tamano,
    abrir: (context, ref) => mostrarSelectorPrenda(context, ref, sucursalId: sucursalId),
  );
  await abrirSelector(tester);
  return e;
}

SeleccionPrenda _eleccion(EscenarioNuevaOperacion e) => e.resultados.single! as SeleccionPrenda;

/// Una segunda variante de la Polera Básica (talla S, color Rojo) con 4 unidades en Centro, a Bs 80.00.
Future<void> _agregarColorRojo(Database db) async {
  await db.insert('color', {'id': 2, 'empresa_id': 1, 'nombre': 'Rojo', 'codigo_hex': '#C62828'});
  await db.insert('variante', {
    'id': 102,
    'producto_id': 10,
    'talla_id': 1,
    'color_id': 2,
    'sku': 'SKU-102',
    'precio_centavos': 8000,
    'descuento_centavos': 0,
    'activo': 1,
  });
  await sembrarStock(db, varianteId: 102, sucursalId: 1, cantidad: 4);
}

/// Más prendas, para probar el paginado ("Prenda 01".."Prenda NN", ordenadas después de la Polera Básica).
Future<void> _sembrarMuchas(Database db, int n) async {
  await sembrarEscenarioBasico(db);
  for (var i = 1; i <= n; i++) {
    final id = 1000 + i;
    final nombre = 'Prenda ${i.toString().padLeft(2, '0')}';
    await sembrarProducto(db, id: id, nombre: nombre, codigo: 'X$id', variantes: [variante(id * 10, sku: 'SKU-X$id')]);
    await sembrarStock(db, varianteId: id * 10, sucursalId: 1, cantidad: 5);
  }
}

void main() {
  group('SelectorPrenda - la lista', () {
    testWidgets('muestra el título y las prendas de la copia local, ordenadas por nombre, con precio', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db);

      expect(find.text('Elige una prenda'), findsOneWidget);
      for (final id in [10, 11, 12, 13]) {
        expect(_fila(id), findsOneWidget);
      }
      expect(_nombreEnFila(10, 'Polera Básica'), findsOneWidget);
      expect(_nombreEnFila(11, 'Camisa Lino'), findsOneWidget);
      // Orden por nombre: Camisa Lino, Camisa Oxford, Pantalón Jean, Polera Básica.
      expect(tester.getTopLeft(_fila(11)).dy, lessThan(tester.getTopLeft(_fila(13)).dy));
      expect(tester.getTopLeft(_fila(13)).dy, lessThan(tester.getTopLeft(_fila(12)).dy));
      expect(tester.getTopLeft(_fila(12)).dy, lessThan(tester.getTopLeft(_fila(10)).dy));
      expect(_enFila(10, 'Bs 75.00'), findsOneWidget);
      expect(_enFila(11, 'Desde Bs 50.00'), findsOneWidget);
      expect(_enFila(13, 'Bs 120.00'), findsOneWidget);
    });

    testWidgets('cada fila lleva la existencia estimada de la sucursal, con texto, ícono y color', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db);

      expect(_enFila(10, '8 en tienda'), findsOneWidget); // 5 + 3 en Centro
      expect(_enFila(11, 'Quedan 2'), findsOneWidget);
      expect(_enFila(12, 'Agotado'), findsOneWidget);
      Color? color(int id, String texto) => tester.widget<Text>(_enFila(id, texto)).style?.color;
      expect(color(10, '8 en tienda'), AppColors.exito);
      expect(color(11, 'Quedan 2'), AppColors.advertencia);
      expect(color(12, 'Agotado'), AppColors.textoTenue);
      expect(find.descendant(of: _fila(10), matching: find.byIcon(Icons.check_circle_outline)), findsOneWidget);
      expect(find.descendant(of: _fila(11), matching: find.byIcon(Icons.warning_amber_rounded)), findsOneWidget);
      expect(find.descendant(of: _fila(12), matching: find.byIcon(Icons.remove_circle_outline)), findsOneWidget);
    });

    testWidgets('la existencia que se ve es la de la sucursal pedida', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db, sucursalId: 2);

      expect(_enFila(10, 'Queda 1'), findsOneWidget); // en Norte solo queda 1 de la variante S
      expect(_enFila(13, 'Agotado'), findsOneWidget);
    });

    testWidgets('las prendas sin foto muestran un recuadro con su nombre (no se pide ninguna imagen de red)', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db);

      expect(find.byKey(const Key('foto_alterna_10')), findsOneWidget);
      expect(find.byIcon(Icons.checkroom), findsNWidgets(4));
    });

    testWidgets('las filas son tocables: miden al menos 48 de alto', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db);

      expect(tester.getSize(_fila(10)).height, greaterThanOrEqualTo(48));
    });

    testWidgets('sin prendas descargadas se explica qué pasa', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEmpresa(b);
        await sembrarSucursal(b, id: 1);
      });
      await _abrir(tester, db);

      expect(find.text('Aún no hay prendas descargadas en el teléfono.'), findsOneWidget);
      expect(_buscador(), findsOneWidget);
    });

    testWidgets('los datos de otra empresa no aparecen', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        await sembrarEmpresa(b, id: 2, codigo: 'andes', nombre: 'Andes');
        await sembrarReferencias(b, empresaId: 2, categoriaId: 20, categoria: 'Ajenas');
        await sembrarProducto(b, id: 50, empresaId: 2, nombre: 'Prenda Ajena', categoriaId: 20, variantes: [variante(500, tallaId: 201, colorId: 201)]);
      });
      await _abrir(tester, db);

      expect(find.text('Prenda Ajena'), findsNothing);
      expect(_fila(10), findsOneWidget);
    });

    testWidgets('sin voseo', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db);

      expect(textosConVoseo(tester), isEmpty);
    });
  });

  group('SelectorPrenda - la búsqueda', () {
    testWidgets('espera 300 ms antes de buscar (debounce) y luego filtra', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db);

      await tester.enterText(_buscador(), 'camisa');
      await tester.pump(const Duration(milliseconds: 100));
      await asentar(tester);
      expect(_fila(10), findsOneWidget); // todavía no filtró
      expect(_fila(12), findsOneWidget);

      await tester.pump(const Duration(milliseconds: 250));
      await asentar(tester);
      await tester.pumpAndSettle();
      expect(_fila(11), findsOneWidget);
      expect(_fila(13), findsOneWidget);
      expect(_fila(10), findsNothing);
      expect(_fila(12), findsNothing);
    });

    testWidgets('escribir seguido busca una sola vez, con el último texto', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db);

      await tester.enterText(_buscador(), 'pol');
      await tester.pump(const Duration(milliseconds: 200));
      await tester.enterText(_buscador(), 'camisa lino');
      await tester.pump(const Duration(milliseconds: 200));
      await asentar(tester);
      expect(_fila(10), findsOneWidget); // los 300 ms de la segunda tecla aún no pasaron
      await tester.pump(const Duration(milliseconds: 150));
      await asentar(tester);
      await tester.pumpAndSettle();

      expect(_fila(11), findsOneWidget);
      expect(_fila(10), findsNothing);
      expect(_fila(13), findsNothing);
    });

    testWidgets('no distingue tildes ni mayúsculas', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db);

      await buscarEscribiendo(tester, _buscador(), 'PANTALON');
      expect(_fila(12), findsOneWidget);
      expect(_fila(10), findsNothing);

      await buscarEscribiendo(tester, _buscador(), 'polera basica');
      expect(_fila(10), findsOneWidget);
      expect(_fila(12), findsNothing);
    });

    testWidgets('busca por código y por SKU de alguna variante', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db);

      await buscarEscribiendo(tester, _buscador(), 'j12');
      expect(_fila(12), findsOneWidget);
      expect(_fila(10), findsNothing);

      await buscarEscribiendo(tester, _buscador(), 'sku-111');
      expect(_fila(11), findsOneWidget);
      expect(_fila(13), findsNothing);
    });

    testWidgets('sin coincidencias muestra el mensaje de la búsqueda', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db);

      await buscarEscribiendo(tester, _buscador(), 'zzzz');
      expect(find.text(textoSinPrendas), findsOneWidget);
      expect(_fila(10), findsNothing);
    });

    testWidgets('"Borrar búsqueda" devuelve la lista completa', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db);

      await buscarEscribiendo(tester, _buscador(), 'camisa');
      expect(_fila(10), findsNothing);
      await tester.tap(find.byTooltip('Borrar búsqueda'));
      await esperar(tester);

      for (final id in [10, 11, 12, 13]) {
        expect(_fila(id), findsOneWidget);
      }
      expect(find.byTooltip('Borrar búsqueda'), findsNothing);
    });
  });

  group('SelectorPrenda - paginado', () {
    testWidgets('carga la siguiente página al desplazarse hasta el final', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) => _sembrarMuchas(b, 25));
      await _abrir(tester, db, tamano: const Size(800, 900));

      // Primera página: 20 prendas (Camisa Lino, Camisa Oxford, Pantalón Jean, Polera Básica y Prenda 01..16).
      expect(_fila(1025), findsNothing);
      expect(_fila(11), findsOneWidget);

      for (var i = 0; i < 20 && _fila(1025).evaluate().isEmpty; i++) {
        await tester.drag(find.byType(ListView).first, const Offset(0, -500));
        await tester.pump();
        await asentar(tester);
      }
      await tester.pumpAndSettle();
      expect(_fila(1025), findsOneWidget);
    });
  });

  group('SelectorPrenda - talla, color y existencia', () {
    Future<void> elegirPolera(WidgetTester tester) async {
      await tester.tap(_fila(10));
      await esperar(tester);
    }

    testWidgets('elegir una prenda abre sus tallas con el nombre como título y la primera con existencia elegida', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db);
      await elegirPolera(tester);

      expect(find.text('Polera Básica'), findsOneWidget); // el título de la hoja
      expect(find.text('Elige una prenda'), findsNothing);
      expect(find.byKey(const Key('talla_S')), findsOneWidget);
      expect(find.byKey(const Key('talla_M')), findsOneWidget);
      expect(tester.widget<ChoiceChip>(find.byKey(const Key('talla_S'))).selected, isTrue);
      expect(tester.widget<ChoiceChip>(find.byKey(const Key('talla_M'))).selected, isFalse);
      expect(find.text('Color: Negro'), findsOneWidget);
      expect(find.byKey(const Key('buscador_prendas')), findsNothing);
    });

    testWidgets('muestra el precio y la existencia estimada de la variante, con la advertencia de que es estimada', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db);
      await elegirPolera(tester);

      expect(tester.widget<Text>(find.byKey(const Key('precio_variante'))).data, 'Bs 75.00');
      expect(find.descendant(of: find.byKey(const Key('existencia_variante')), matching: find.text('Hay (5)')), findsOneWidget);
      expect(find.text('Es una estimación: no incluye ventas de otros dispositivos.'), findsOneWidget);
    });

    testWidgets('cambiar de talla cambia la variante, su precio y su existencia', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        await b.update('variante', {'precio_centavos': 8200}, where: 'id = 101');
      });
      await _abrir(tester, db);
      await elegirPolera(tester);

      await tester.tap(find.byKey(const Key('talla_M')));
      await tester.pump();
      expect(tester.widget<ChoiceChip>(find.byKey(const Key('talla_M'))).selected, isTrue);
      expect(tester.widget<Text>(find.byKey(const Key('precio_variante'))).data, 'Bs 82.00');
      expect(find.descendant(of: find.byKey(const Key('existencia_variante')), matching: find.text('Hay (3)')), findsOneWidget);
    });

    testWidgets('la insignia dice "Quedan pocas" con 1 o 2 unidades', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db);
      await tester.tap(_fila(11));
      await esperar(tester);

      expect(find.descendant(of: find.byKey(const Key('existencia_variante')), matching: find.text('Quedan pocas (2)')), findsOneWidget);
      expect(find.byKey(const Key('aviso_agotada')), findsNothing);
    });

    testWidgets('elegir el color cambia la variante, el precio y la existencia', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        await _agregarColorRojo(b);
      });
      final e = await _abrir(tester, db);
      await elegirPolera(tester);

      expect(find.byKey(const Key('color_Negro')), findsOneWidget);
      expect(find.byKey(const Key('color_Rojo')), findsOneWidget);
      expect(find.text('Color: Negro'), findsOneWidget);

      await tester.tap(find.byKey(const Key('color_Rojo')));
      await tester.pump();
      expect(find.text('Color: Rojo'), findsOneWidget);
      expect(tester.widget<Text>(find.byKey(const Key('precio_variante'))).data, 'Bs 80.00');
      expect(find.descendant(of: find.byKey(const Key('existencia_variante')), matching: find.text('Hay (4)')), findsOneWidget);

      await tester.tap(find.byKey(const Key('boton_agregar')));
      await tester.pumpAndSettle();
      expect(_eleccion(e).variante.id, 102);
    });

    testWidgets('con descuento muestra el precio final y el original tachado', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        await b.update('variante', {'descuento_centavos': 500}, where: 'id = 100');
      });
      await _abrir(tester, db);
      await elegirPolera(tester);

      expect(tester.widget<Text>(find.byKey(const Key('precio_variante'))).data, 'Bs 70.00');
      final tachado = find.byWidgetPredicate(
        (w) => w is Text && w.data == 'Bs 75.00' && w.style?.decoration == TextDecoration.lineThrough,
      );
      expect(tachado, findsOneWidget);
    });

    testWidgets('si la primera variante está agotada se parte de una que tenga existencia', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        await b.update('stock_conocido', {'cantidad': 0}, where: 'variante_id = 110');
        await b.update('stock_conocido', {'cantidad': 3}, where: 'variante_id = 111');
      });
      await _abrir(tester, db);
      await tester.tap(_fila(11));
      await esperar(tester);

      expect(tester.widget<ChoiceChip>(find.byKey(const Key('talla_M'))).selected, isTrue);
      expect(find.descendant(of: find.byKey(const Key('existencia_variante')), matching: find.text('Hay (3)')), findsOneWidget);
    });

    testWidgets('una variante agotada se puede elegir, con un aviso de que el servidor decide', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      final e = await _abrir(tester, db);
      await tester.tap(_fila(11));
      await esperar(tester);

      await tester.tap(find.byKey(const Key('talla_M'))); // Camisa Lino M: 0
      await tester.pump();
      expect(find.descendant(of: find.byKey(const Key('existencia_variante')), matching: find.text('Agotado (0)')), findsOneWidget);
      expect(find.byKey(const Key('aviso_agotada')), findsOneWidget);
      expect(find.textContaining('Puedes agregarla igual'), findsOneWidget);
      expect(tester.widget<ElevatedButton>(find.byKey(const Key('boton_agregar'))).onPressed, isNotNull);

      await tester.tap(find.byKey(const Key('boton_agregar')));
      await tester.pumpAndSettle();
      expect(_eleccion(e).variante.id, 111);
      expect(_eleccion(e).producto.id, 11);
    });

    testWidgets('una prenda sin ninguna talla activa lo dice y no deja agregar', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        await b.update('variante', {'activo': 0}, where: 'producto_id = 13');
      });
      await _abrir(tester, db);
      await tester.tap(_fila(13));
      await esperar(tester);

      expect(find.text('Esta prenda no tiene tallas disponibles.'), findsOneWidget);
      expect(find.byKey(const Key('boton_agregar')), findsNothing);
    });

    testWidgets('la flecha de la cabecera vuelve a la lista', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db);
      await elegirPolera(tester);

      await tester.tap(find.byKey(const Key('volver_a_la_lista')));
      await tester.pump();
      expect(find.text('Elige una prenda'), findsOneWidget);
      expect(_fila(10), findsOneWidget);
      expect(find.byKey(const Key('talla_S')), findsNothing);
    });
  });

  group('SelectorPrenda - cantidad y resultado', () {
    testWidgets('empieza en 1 y "Menos" está desactivado', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db);
      await tester.tap(_fila(10));
      await esperar(tester);

      expect(tester.widget<Text>(find.descendant(of: find.byKey(const Key('selector_cantidad')), matching: find.byType(Text))).data, '1');
      expect(tester.widget<IconButton>(find.byKey(const Key('selector_menos'))).onPressed, isNull);
      expect(tester.widget<IconButton>(find.byKey(const Key('selector_mas'))).onPressed, isNotNull);
    });

    testWidgets('"Más" y "Menos" cambian la cantidad que se devuelve', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      final e = await _abrir(tester, db);
      await tester.tap(_fila(10));
      await esperar(tester);

      for (var i = 0; i < 4; i++) {
        await tester.tap(find.byKey(const Key('selector_mas')));
        await tester.pump();
      }
      await tester.tap(find.byKey(const Key('selector_menos')));
      await tester.pump();
      expect(find.descendant(of: find.byKey(const Key('selector_cantidad')), matching: find.text('4')), findsOneWidget);

      await tester.tap(find.byKey(const Key('boton_agregar')));
      await tester.pumpAndSettle();

      final r = _eleccion(e);
      expect(r.cantidad, 4);
      expect(r.variante.id, 100);
      expect(r.producto.id, 10);
      expect(r.variante.precioCentavos, 7500);
      expect(find.byKey(const Key('boton_agregar')), findsNothing); // la hoja se cerró
    });

    testWidgets('pedir más de lo que hay no se bloquea (el aviso viene al registrar)', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      final e = await _abrir(tester, db);
      await tester.tap(_fila(10));
      await esperar(tester);

      for (var i = 0; i < 7; i++) {
        await tester.tap(find.byKey(const Key('selector_mas')));
        await tester.pump();
      }
      await tester.tap(find.byKey(const Key('boton_agregar')));
      await tester.pumpAndSettle();
      expect(_eleccion(e).cantidad, 8); // la variante S tiene 5
    });

    testWidgets('cambiar de talla conserva la cantidad ya elegida', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      final e = await _abrir(tester, db);
      await tester.tap(_fila(10));
      await esperar(tester);

      await tester.tap(find.byKey(const Key('selector_mas')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('talla_M')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('boton_agregar')));
      await tester.pumpAndSettle();

      expect(_eleccion(e).cantidad, 2);
      expect(_eleccion(e).variante.id, 101);
    });

    testWidgets('al volver a la lista y elegir otra prenda la cantidad vuelve a 1', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db);
      await tester.tap(_fila(10));
      await esperar(tester);
      await tester.tap(find.byKey(const Key('selector_mas')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('volver_a_la_lista')));
      await tester.pump();

      await tester.tap(_fila(13));
      await esperar(tester);
      expect(find.descendant(of: find.byKey(const Key('selector_cantidad')), matching: find.text('1')), findsOneWidget);
    });

    testWidgets('cerrar sin elegir devuelve null', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      final e = await _abrir(tester, db);

      await tester.tap(find.byTooltip('Cerrar'));
      await tester.pumpAndSettle();
      expect(e.resultados, [null]);
    });

    testWidgets('los botones de cantidad y de agregar miden al menos 48', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db);
      await tester.tap(_fila(10));
      await esperar(tester);

      for (final k in ['selector_menos', 'selector_mas', 'boton_agregar', 'talla_S', 'color_Negro']) {
        final tam = tester.getSize(find.byKey(Key(k)));
        expect(tam.height, greaterThanOrEqualTo(48), reason: k);
      }
      expect(tester.getSize(find.byKey(const Key('selector_mas'))).width, greaterThanOrEqualTo(48));
    });

    testWidgets('sin voseo en el paso de talla y color', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrir(tester, db);
      await tester.tap(_fila(11));
      await esperar(tester);
      await tester.tap(find.byKey(const Key('talla_M')));
      await tester.pump();

      expect(textosConVoseo(tester), isEmpty);
    });
  });

  group('NivelExistencia', () {
    test('0 es agotado; 1 y 2 son pocas; 3 o más hay', () {
      expect(NivelExistencia.de(0), NivelExistencia.agotado);
      expect(NivelExistencia.de(-3), NivelExistencia.agotado);
      expect(NivelExistencia.de(1), NivelExistencia.pocas);
      expect(NivelExistencia.de(2), NivelExistencia.pocas);
      expect(NivelExistencia.de(3), NivelExistencia.hay);
    });
  });
}
