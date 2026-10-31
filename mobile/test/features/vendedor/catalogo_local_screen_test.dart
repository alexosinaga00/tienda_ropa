import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/theme/app_theme.dart';
import 'package:mobile/core/widgets/indicador_conexion.dart';
import 'package:mobile/features/vendedor/presentation/catalogo_local_screen.dart';
import 'package:mobile/features/vendedor/presentation/selector_sucursal_activa.dart';
import 'package:mobile/features/vendedor/presentation/aviso_vigencia.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';
import 'apoyo_catalogo_local.dart';

Finder _tarjeta(int id) => find.byKey(Key('tarjeta_prenda_$id'));

Future<void> _escribir(WidgetTester tester, String texto) async {
  await tester.enterText(find.byType(TextField), texto);
  await tester.pump(esperaBusquedaCatalogoLocal);
  await asentar(tester);
}

Finder _enTarjeta(int id, String texto) => find.descendant(of: _tarjeta(id), matching: find.text(texto));

/// El nombre de la prenda como título de la tarjeta (el recuadro sin foto repite el nombre: se distingue por el estilo).
Finder _nombreEnTarjeta(int id, String nombre) => find.descendant(
  of: _tarjeta(id),
  matching: find.byWidgetPredicate((w) => w is Text && w.data == nombre && w.style?.fontWeight == FontWeight.w600),
);

/// `n` prendas "Prenda 01".."Prenda NN" (todas de la categoría 1) con una variante y 5 unidades en Centro.
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
  group('CatalogoLocalScreen - contenido', () {
    testWidgets('muestra el título, las prendas con nombre y precio, ordenadas por nombre', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db);

      expect(find.descendant(of: find.byType(AppBar), matching: find.text('Catálogo sin conexión')), findsOneWidget);
      for (final id in [10, 11, 12, 13]) {
        expect(_tarjeta(id), findsOneWidget);
      }
      expect(_nombreEnTarjeta(10, 'Polera Básica'), findsOneWidget);
      expect(_nombreEnTarjeta(11, 'Camisa Lino'), findsOneWidget);
      expect(_nombreEnTarjeta(12, 'Pantalón Jean'), findsOneWidget);
      expect(_nombreEnTarjeta(13, 'Camisa Oxford'), findsOneWidget);
      // Orden por nombre: Camisa Lino, Camisa Oxford, Pantalón Jean, Polera Básica.
      Offset arriba(int id) => tester.getTopLeft(_tarjeta(id));
      expect(arriba(11).dy, arriba(13).dy); // primera fila, de izquierda a derecha
      expect(arriba(11).dx, lessThan(arriba(13).dx));
      expect(arriba(12).dy, greaterThan(arriba(11).dy)); // segunda fila
      expect(arriba(12).dx, lessThan(arriba(10).dx));
    });

    testWidgets('el precio es "Bs ..." con un solo precio y "Desde Bs ..." con varios', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db);

      expect(_enTarjeta(10, 'Bs 75.00'), findsOneWidget);
      expect(_enTarjeta(11, 'Desde Bs 50.00'), findsOneWidget);
      expect(_enTarjeta(13, 'Bs 120.00'), findsOneWidget);
    });

    testWidgets('muestra la existencia estimada de la sucursal activa', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db);

      expect(_enTarjeta(10, '8 en tienda'), findsOneWidget); // 5 + 3 en Centro
      expect(_enTarjeta(11, 'Quedan 2'), findsOneWidget); // 2 + 0
      expect(_enTarjeta(12, 'Agotado'), findsOneWidget); // sin stock
      expect(_enTarjeta(13, '4 en tienda'), findsOneWidget);
    });

    testWidgets('"Queda 1" en singular', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        await b.update('stock_conocido', {'cantidad': 1}, where: 'variante_id = 130');
      });
      await abrirCatalogoLocal(tester, db: db);

      expect(_enTarjeta(13, 'Queda 1'), findsOneWidget);
    });

    testWidgets('la existencia lleva ícono y texto, con color según el nivel', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db);

      Color? color(int id, String texto) => tester.widget<Text>(_enTarjeta(id, texto)).style?.color;
      expect(color(10, '8 en tienda'), AppColors.exito);
      expect(color(11, 'Quedan 2'), AppColors.advertencia);
      expect(color(12, 'Agotado'), AppColors.textoTenue);
    });

    testWidgets('las prendas sin foto muestran un recuadro con su nombre', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db);

      expect(find.byKey(const Key('foto_alterna_10')), findsOneWidget);
      expect(find.descendant(of: find.byKey(const Key('foto_alterna_10')), matching: find.text('Polera Básica')), findsOneWidget);
      expect(find.byIcon(Icons.checkroom), findsNWidgets(4));
    });

    testWidgets('los datos de otra empresa no aparecen', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        await sembrarEmpresa(b, id: 2, codigo: 'andes', nombre: 'Andes');
        await sembrarReferencias(b, empresaId: 2, categoriaId: 20, categoria: 'Ajenas');
        await sembrarProducto(b, id: 50, empresaId: 2, nombre: 'Prenda Ajena', categoriaId: 20, variantes: [variante(500, tallaId: 201, colorId: 201)]);
      });
      await abrirCatalogoLocal(tester, db: db);

      expect(find.text('Prenda Ajena'), findsNothing);
      expect(_tarjeta(10), findsOneWidget);
    });

    testWidgets('tocar una tarjeta abre el detalle de esa prenda', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      final e = await abrirCatalogoLocal(tester, db: db);

      await tester.tap(_tarjeta(10));
      await tester.pump();
      await asentar(tester);

      expect(e.ruta, '/vendedor/producto/10');
      expect(find.descendant(of: find.byType(AppBar), matching: find.text('Polera Básica')), findsOneWidget);
    });

    testWidgets('las tarjetas y los botones miden al menos 48 de alto', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db);

      expect(tester.getSize(_tarjeta(10)).height, greaterThanOrEqualTo(48));
      expect(tester.getSize(find.widgetWithIcon(IconButton, Icons.sync)).shortestSide, greaterThanOrEqualTo(48));
      expect(tester.getSize(find.widgetWithText(ChoiceChip, 'Todas')).height, greaterThanOrEqualTo(32));
    });
  });

  group('CatalogoLocalScreen - búsqueda y categorías', () {
    testWidgets('busca por nombre sin importar mayúsculas ni tildes', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db);

      await _escribir(tester, 'CAMISA');
      expect(_tarjeta(11), findsOneWidget);
      expect(_tarjeta(13), findsOneWidget);
      expect(_tarjeta(10), findsNothing);
      expect(_tarjeta(12), findsNothing);

      await _escribir(tester, 'pantalon');
      expect(_tarjeta(12), findsOneWidget);
      expect(_tarjeta(11), findsNothing);

      await _escribir(tester, 'básica');
      expect(_tarjeta(10), findsOneWidget);
      expect(_tarjeta(12), findsNothing);
    });

    testWidgets('busca por código y por SKU', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db);

      await _escribir(tester, 'j12');
      expect(_tarjeta(12), findsOneWidget);
      expect(_tarjeta(10), findsNothing);

      await _escribir(tester, 'sku-130');
      expect(_tarjeta(13), findsOneWidget);
      expect(_tarjeta(12), findsNothing);
    });

    testWidgets('espera 300 ms sin escribir antes de buscar', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db);

      await tester.enterText(find.byType(TextField), 'camisa');
      await tester.pump(const Duration(milliseconds: 250));
      await asentar(tester, rondas: 4);
      expect(_tarjeta(10), findsOneWidget); // todavía no filtró

      await tester.pump(const Duration(milliseconds: 100));
      await asentar(tester);
      expect(_tarjeta(10), findsNothing);
      expect(_tarjeta(11), findsOneWidget);
    });

    testWidgets('sin resultados dice "No encontramos prendas con ese texto"', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db);

      await _escribir(tester, 'zzzz');

      expect(find.text('No encontramos prendas con ese texto'), findsOneWidget);
      expect(find.text('Aún no descargaste el catálogo'), findsNothing);
      expect(find.byType(ElevatedButton), findsNothing);
    });

    testWidgets('borrar la búsqueda devuelve todas las prendas', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db);
      await _escribir(tester, 'zzzz');

      await tester.tap(find.byTooltip('Borrar búsqueda'));
      await tester.pump();
      await asentar(tester);

      expect(_tarjeta(10), findsOneWidget);
      expect(_tarjeta(12), findsOneWidget);
    });

    testWidgets('los chips son "Todas" y las categorías raíz (no las subcategorías)', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db);

      expect(find.byType(ChoiceChip), findsNWidgets(4));
      expect(find.widgetWithText(ChoiceChip, 'Todas'), findsOneWidget);
      expect(find.widgetWithText(ChoiceChip, 'Poleras'), findsOneWidget);
      expect(find.widgetWithText(ChoiceChip, 'Camisas'), findsOneWidget);
      expect(find.widgetWithText(ChoiceChip, 'Pantalones'), findsOneWidget);
      expect(find.widgetWithText(ChoiceChip, 'Camisas manga larga'), findsNothing);
      expect(tester.widget<ChoiceChip>(find.widgetWithText(ChoiceChip, 'Todas')).selected, isTrue);
    });

    testWidgets('filtrar por una categoría incluye sus subcategorías', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db);

      await tester.tap(find.widgetWithText(ChoiceChip, 'Camisas'));
      await tester.pump();
      await asentar(tester);

      expect(_tarjeta(11), findsOneWidget); // Camisas
      expect(_tarjeta(13), findsOneWidget); // Camisas manga larga, hija de Camisas
      expect(_tarjeta(10), findsNothing);
      expect(_tarjeta(12), findsNothing);
      expect(tester.widget<ChoiceChip>(find.widgetWithText(ChoiceChip, 'Camisas')).selected, isTrue);
    });

    testWidgets('"Todas" quita el filtro de categoría', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db);
      await tester.tap(find.widgetWithText(ChoiceChip, 'Pantalones'));
      await tester.pump();
      await asentar(tester);
      expect(_tarjeta(10), findsNothing);

      await tester.tap(find.widgetWithText(ChoiceChip, 'Todas'));
      await tester.pump();
      await asentar(tester);

      expect(_tarjeta(10), findsOneWidget);
      expect(_tarjeta(12), findsOneWidget);
    });

    testWidgets('el texto y la categoría se combinan', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db);
      await tester.tap(find.widgetWithText(ChoiceChip, 'Camisas'));
      await tester.pump();
      await asentar(tester);

      await _escribir(tester, 'oxford');

      expect(_tarjeta(13), findsOneWidget);
      expect(_tarjeta(11), findsNothing);
    });

    testWidgets('una categoría sin prendas que coincidan con el texto no muestra el estado "sin descargar"', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db);
      await tester.tap(find.widgetWithText(ChoiceChip, 'Poleras'));
      await tester.pump();
      await asentar(tester);

      await _escribir(tester, 'jean');

      expect(find.text('No encontramos prendas con ese texto'), findsOneWidget);
    });
  });

  group('CatalogoLocalScreen - paginación', () {
    testWidgets('carga de 20 en 20 sin duplicar (pantalla alta: llena sola)', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) => _sembrarMuchas(b, 21));
      // 25 prendas en total (4 + 21). Con una pantalla enorme caben todas: debe pedir la segunda página sola.
      await abrirCatalogoLocal(tester, db: db, tamano: const Size(800, 30000));
      await asentar(tester, rondas: 20);

      expect(find.byType(Card), findsNWidgets(25));
      expect(_tarjeta(1021), findsOneWidget);
    });

    testWidgets('en una pantalla normal pide más al llegar al final', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) => _sembrarMuchas(b, 41));
      await abrirCatalogoLocal(tester, db: db);
      // 45 prendas; por orden de nombre la última es "Prenda 41" (después de las cuatro del escenario base).
      expect(_tarjeta(1041), findsNothing);

      final lista = find.byType(CustomScrollView);
      for (var i = 0; i < 20 && _tarjeta(1041).evaluate().isEmpty; i++) {
        await tester.drag(lista, const Offset(0, -2500));
        await tester.pump();
        await asentar(tester, rondas: 5);
      }

      expect(_tarjeta(1041), findsOneWidget); // pidió la segunda y la tercera página
    });

    testWidgets('con menos de 20 resultados no pide más páginas', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db, tamano: const Size(800, 30000));
      await asentar(tester, rondas: 10);

      expect(find.byType(Card), findsNWidgets(4));
      expect(find.byType(CircularProgressIndicator), findsNothing);
    });
  });

  group('CatalogoLocalScreen - estados', () {
    testWidgets('sin catálogo descargado muestra el aviso y el botón "Actualizar datos"', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEmpresa(b);
      });
      await abrirCatalogoLocal(tester, db: db);

      expect(find.text('Aún no descargaste el catálogo'), findsOneWidget);
      expect(find.text('Descárgalo para consultarlo sin conexión.'), findsOneWidget);
      expect(find.widgetWithText(ElevatedButton, 'Actualizar datos'), findsOneWidget);
      expect(find.text('Sin sucursal'), findsOneWidget);
    });

    testWidgets('el botón del estado vacío descarga y, al terminar, aparecen las prendas', (tester) async {
      final db = await abrirBaseSembrada(tester);
      final servicio = ServicioDescargaFalso();
      servicio.alDescargar = () async {
        await sembrarEscenarioBasico(db, descargaCentro: true);
      };
      await abrirCatalogoLocal(tester, db: db, servicio: servicio);

      await tester.tap(find.widgetWithText(ElevatedButton, 'Actualizar datos'));
      await tester.pump();
      await asentar(tester, rondas: 25);

      expect(servicio.llamadas, 1);
      expect(find.text('Aún no descargaste el catálogo'), findsNothing);
      expect(_tarjeta(10), findsOneWidget);
      expect(find.text('Centro'), findsOneWidget);
    });

    testWidgets('sin conexión y sin catálogo, el botón está deshabilitado y lo explica', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEmpresa);
      final e = await abrirCatalogoLocal(tester, db: db, enLinea: false);

      expect(find.text('Conéctate a internet para descargarlo.'), findsOneWidget);
      expect(tester.widget<ElevatedButton>(find.widgetWithText(ElevatedButton, 'Actualizar datos')).onPressed, isNull);
      expect(e.servicio.llamadas, 0);
    });

    testWidgets('mientras lee la base muestra un indicador de carga y luego las prendas', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      final e = await abrirCatalogoLocal(tester, db: db);
      // Se vuelve a abrir la pantalla y se mira ANTES de dar tiempo a SQLite.
      e.router!.go('/vendedor');
      await tester.pump();
      e.router!.go('/vendedor/catalogo');
      await tester.pump();
      await tester.pump();

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(_tarjeta(10), findsNothing);

      await asentar(tester);
      expect(find.byType(CircularProgressIndicator), findsNothing);
      expect(_tarjeta(10), findsOneWidget);
    });
  });

  group('CatalogoLocalScreen - sin conexión y vigencia', () {
    testWidgets('con el servicio de conectividad en "sin conexión" todo se ve igual y avisa', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db, enLinea: false);

      expect(find.text(textoSinConexion), findsOneWidget);
      expect(find.byType(IndicadorConexion), findsOneWidget);
      expect(find.textContaining('Sin conexión. Los datos se actualizaron el'), findsOneWidget);
      expect(_tarjeta(10), findsOneWidget);
      expect(_enTarjeta(10, '8 en tienda'), findsOneWidget);
    });

    testWidgets('el botón de la barra se deshabilita sin conexión', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      final e = await abrirCatalogoLocal(tester, db: db, enLinea: false);

      expect(tester.widget<IconButton>(find.widgetWithIcon(IconButton, Icons.sync)).onPressed, isNull);

      e.conectividad.emitir(true);
      await asentar(tester, rondas: 3);
      expect(tester.widget<IconButton>(find.widgetWithIcon(IconButton, Icons.sync)).onPressed, isNotNull);
    });

    testWidgets('el botón de la barra descarga y se deshabilita mientras tanto', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      final servicio = ServicioDescargaFalso()..puerta = Completer<void>();
      await abrirCatalogoLocal(tester, db: db, servicio: servicio);

      await tester.tap(find.byTooltip('Actualizar datos'));
      await tester.pump();
      await tester.pump();

      expect(servicio.llamadas, 1);
      expect(tester.widget<IconButton>(find.widgetWithIcon(IconButton, Icons.sync)).onPressed, isNull);
      expect(find.text('Actualizando datos…'), findsOneWidget);

      servicio.puerta!.complete();
      await asentar(tester, rondas: 15);
      expect(tester.widget<IconButton>(find.widgetWithIcon(IconButton, Icons.sync)).onPressed, isNotNull);
    });

    testWidgets('muestra el aviso de vigencia cuando los datos son viejos', (tester) async {
      final db = await abrirBaseSembrada(
        tester,
        siembra: (b) => sembrarEscenarioBasico(b, descargadoEn: instanteBase.subtract(const Duration(hours: 5))),
      );
      await abrirCatalogoLocal(tester, db: db);

      expect(find.byType(AvisoVigencia), findsOneWidget);
      expect(find.textContaining('(hace 5 h). Pueden estar desactualizados.'), findsOneWidget);
      expect(_tarjeta(10), findsOneWidget); // no bloquea nada
    });

    testWidgets('al terminar una descarga se recargan las existencias', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      final servicio = ServicioDescargaFalso();
      servicio.alDescargar = () async {
        await db.update('stock_conocido', {'cantidad': 9}, where: 'variante_id = 130');
        await db.insert('producto', {
          'id': 14,
          'empresa_id': 1,
          'codigo': 'N14',
          'nombre': 'Camisa Nueva',
          'nombre_busqueda': 'camisa nueva',
          'categoria_id': 2,
          'genero': 'unisex',
        });
        await db.insert('variante', {
          'id': 140,
          'producto_id': 14,
          'talla_id': 1,
          'color_id': 1,
          'sku': 'SKU-140',
          'precio_centavos': 3000,
          'descuento_centavos': 0,
          'activo': 1,
        });
      };
      await abrirCatalogoLocal(tester, db: db, servicio: servicio);
      expect(_enTarjeta(13, '4 en tienda'), findsOneWidget);
      expect(find.text('Camisa Nueva'), findsNothing);

      await tester.tap(find.byTooltip('Actualizar datos'));
      await tester.pump();
      await asentar(tester, rondas: 25);

      expect(_enTarjeta(13, '9 en tienda'), findsOneWidget);
      expect(_tarjeta(14), findsOneWidget);
    });
  });

  group('CatalogoLocalScreen - sucursal activa', () {
    testWidgets('el selector está en la barra y muestra la sucursal activa', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db);

      expect(find.descendant(of: find.byType(AppBar), matching: find.byType(SelectorSucursalActiva)), findsOneWidget);
      expect(find.descendant(of: find.byType(SelectorSucursalActiva), matching: find.text('Centro')), findsOneWidget);
    });

    testWidgets('cambiar de sucursal recarga las existencias de esa sucursal', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) => sembrarEscenarioBasico(b, descargaNorte: true));
      await abrirCatalogoLocal(tester, db: db);
      expect(_enTarjeta(10, '8 en tienda'), findsOneWidget);

      await tester.tap(find.byType(PopupMenuButton<int>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Norte'));
      await tester.pumpAndSettle();
      await asentar(tester, rondas: 15);

      expect(_enTarjeta(10, 'Queda 1'), findsOneWidget); // en Norte, la variante 100 tiene 1
      expect(_enTarjeta(11, 'Agotado'), findsOneWidget);
      expect(_enTarjeta(13, 'Agotado'), findsOneWidget);
    });

    testWidgets('una sucursal que nunca se descargó no muestra "Agotado" por falta de datos', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirCatalogoLocal(tester, db: db, enLinea: false);

      await tester.tap(find.byType(PopupMenuButton<int>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Norte'));
      await tester.pumpAndSettle();
      await asentar(tester, rondas: 15);

      expect(_tarjeta(10), findsOneWidget);
      expect(find.text('Agotado'), findsNothing);
      expect(find.textContaining('en tienda'), findsNothing);
      expect(find.text('Aún no descargaste el catálogo de esta sucursal.'), findsOneWidget);
    });

    testWidgets('descuenta lo vendido sin conexión que el servidor aún no refleja', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
      });
      await abrirCatalogoLocal(tester, db: db);
      expect(_enTarjeta(13, '4 en tienda'), findsOneWidget);

      // Una venta registrada sin conexión de 3 unidades de la variante 130: quedan 1.
      await enBase(tester, db, (b) async {
        await b.insert('operacion_pendiente', {
          'operacion_id': 'op-1',
          'empresa_id': 1,
          'sucursal_id': 1,
          'usuario_id': 7,
          'tipo': 'venta_contado',
          'estado': 'registrada',
          'payload': '{}',
          'version_contrato': 1,
          'fecha_operacion': '2026-10-31T11:00:00Z',
          'creada_en': '2026-10-31T11:00:00Z',
        });
        final venta = await b.insert('venta', {
          'operacion_id': 'op-1',
          'empresa_id': 1,
          'sucursal_id': 1,
          'usuario_id': 7,
          'fecha_operacion': '2026-10-31T11:00:00Z',
          'forma_pago': 'efectivo',
          'total_centavos': 36000,
        });
        await b.insert('venta_detalle', {'venta_id': venta, 'variante_id': 130, 'cantidad': 3, 'precio_unitario_centavos': 12000});
      });
      await tester.tap(find.widgetWithText(ChoiceChip, 'Camisas')); // fuerza una recarga
      await tester.pump();
      await asentar(tester);

      expect(_enTarjeta(13, 'Queda 1'), findsOneWidget);
    });
  });
}

