import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/theme/app_theme.dart';
import 'package:mobile/core/widgets/indicador_conexion.dart';
import 'package:mobile/features/vendedor/presentation/aviso_vigencia.dart';
import 'package:mobile/features/vendedor/presentation/detalle_local_screen.dart';
import 'package:mobile/features/vendedor/state/catalogo_local_providers.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';
import 'apoyo_catalogo_local.dart';

Finder _celda(int varianteId) => find.byKey(Key('celda_variante_$varianteId'));

Finder _enCelda(int varianteId, String texto) => find.descendant(of: _celda(varianteId), matching: find.text(texto));

Future<EscenarioCatalogoLocal> _abrirDetalle(
  WidgetTester tester,
  Database db, {
  int id = 10,
  bool enLinea = true,
}) {
  return abrirCatalogoLocal(tester, db: db, inicial: '/vendedor/producto/$id', enLinea: enLinea);
}

void main() {
  group('DetalleLocalScreen - contenido', () {
    testWidgets('muestra el nombre en la barra y el código, la categoría y el género', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrirDetalle(tester, db);

      expect(find.descendant(of: find.byType(AppBar), matching: find.text('Polera Básica')), findsOneWidget);
      expect(find.text('Polera Básica'), findsNWidgets(3)); // barra, título y recuadro sin foto
      expect(find.text('Código: P10'), findsOneWidget);
      expect(find.text('Categoría: Poleras'), findsOneWidget);
      expect(find.text('Género: Unisex'), findsOneWidget);
    });

    testWidgets('sin foto muestra el recuadro con el nombre de la prenda', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrirDetalle(tester, db);

      expect(find.byKey(const Key('foto_alterna_10')), findsOneWidget);
    });

    testWidgets('el género se muestra legible', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        await b.update('producto', {'genero': 'masculino'}, where: 'id = 10');
        await b.update('producto', {'genero': 'femenino'}, where: 'id = 11');
      });
      final e = await _abrirDetalle(tester, db);
      expect(find.text('Género: Hombre'), findsOneWidget);

      e.router!.go('/vendedor/producto/11');
      await tester.pump();
      await asentar(tester);
      expect(find.text('Género: Mujer'), findsOneWidget);
    });

    testWidgets('una celda por variante activa, con talla y color', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        await b.insert('variante', {
          'id': 102,
          'producto_id': 10,
          'talla_id': 3,
          'color_id': 1,
          'sku': 'SKU-102',
          'precio_centavos': 7500,
          'descuento_centavos': 0,
          'activo': 0,
        });
      });
      await _abrirDetalle(tester, db);

      expect(_celda(100), findsOneWidget);
      expect(_celda(101), findsOneWidget);
      expect(_celda(102), findsNothing); // dada de baja
      expect(_enCelda(100, 'S · Negro'), findsOneWidget);
      expect(_enCelda(101, 'M · Negro'), findsOneWidget);
    });
  });

  group('DetalleLocalScreen - precio', () {
    testWidgets('sin descuento muestra solo el precio final', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrirDetalle(tester, db);

      expect(find.byKey(const Key('precio_final')), findsOneWidget);
      expect(tester.widget<Text>(find.byKey(const Key('precio_final'))).data, 'Bs 75.00');
      expect(find.byKey(const Key('precio_tachado')), findsNothing);
    });

    testWidgets('con descuento muestra el precio tachado y el precio final', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        await b.update('variante', {'descuento_centavos': 1500}, where: 'producto_id = 10');
      });
      await _abrirDetalle(tester, db);

      final tachado = tester.widget<Text>(find.byKey(const Key('precio_tachado')));
      expect(tachado.data, 'Bs 75.00');
      expect(tachado.style?.decoration, TextDecoration.lineThrough);
      expect(tester.widget<Text>(find.byKey(const Key('precio_final'))).data, 'Bs 60.00');
    });

    testWidgets('con varios precios muestra "Desde" el menor y el precio de cada celda', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrirDetalle(tester, db, id: 11);

      expect(find.text('Desde'), findsOneWidget);
      expect(tester.widget<Text>(find.byKey(const Key('precio_final'))).data, 'Bs 50.00');
      expect(_enCelda(110, 'Bs 50.00'), findsOneWidget);
      expect(_enCelda(111, 'Bs 90.00'), findsOneWidget);
    });
  });

  group('DetalleLocalScreen - existencias', () {
    testWidgets('las insignias dicen "Hay", "Quedan pocas" y "Agotado" con su texto', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrirDetalle(tester, db, id: 11);

      // 110: 2 unidades -> pocas; 111: 0 -> agotado.
      expect(_enCelda(110, 'Quedan pocas'), findsOneWidget);
      expect(_enCelda(111, 'Agotado'), findsOneWidget);
      expect(_enCelda(110, '(2)'), findsOneWidget);
      expect(_enCelda(111, '(0)'), findsOneWidget);
    });

    testWidgets('"Hay" cuando quedan más de 2 unidades', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrirDetalle(tester, db);

      expect(_enCelda(100, 'Hay'), findsOneWidget);
      expect(_enCelda(100, '(5)'), findsOneWidget);
      expect(_enCelda(101, 'Hay'), findsOneWidget);
      expect(_enCelda(101, '(3)'), findsOneWidget);
    });

    testWidgets('el límite: con 3 unidades es "Hay" y con 2 es "Quedan pocas"', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        await b.update('stock_conocido', {'cantidad': 3}, where: 'variante_id = 100');
        await b.update('stock_conocido', {'cantidad': 2}, where: 'variante_id = 101');
      });
      await _abrirDetalle(tester, db);

      expect(_enCelda(100, 'Hay'), findsOneWidget);
      expect(_enCelda(101, 'Quedan pocas'), findsOneWidget);
    });

    testWidgets('la insignia combina color, ícono y texto (nunca solo color)', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrirDetalle(tester, db, id: 11);
      await asentar(tester, rondas: 2);

      Color? colorTexto(int v, String t) => tester.widget<Text>(_enCelda(v, t)).style?.color;
      Finder icono(int v, IconData i) => find.descendant(of: _celda(v), matching: find.byIcon(i));

      expect(colorTexto(110, 'Quedan pocas'), AppColors.advertencia);
      expect(icono(110, Icons.warning_amber_rounded), findsOneWidget);
      expect(colorTexto(111, 'Agotado'), AppColors.textoTenue);
      expect(icono(111, Icons.remove_circle_outline), findsOneWidget);
    });

    testWidgets('la insignia verde de "Hay" usa el color de éxito y su ícono', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrirDetalle(tester, db);

      expect(tester.widget<Text>(_enCelda(100, 'Hay')).style?.color, AppColors.exito);
      expect(find.descendant(of: _celda(100), matching: find.byIcon(Icons.check_circle_outline)), findsOneWidget);
    });

    testWidgets('la leyenda dice a qué hora se conoce la existencia (hora local)', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrirDetalle(tester, db);

      final esperado = fechaLocalEsperada(DateTime.utc(2026, 10, 31, 10));
      expect(find.text('Existencia conocida al $esperado'), findsOneWidget);
    });

    testWidgets('la leyenda usa la hora de stock más reciente de las variantes', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        await b.update('stock_conocido', {'generado_en': '2026-10-31T11:15:00Z'}, where: 'variante_id = 101');
      });
      await _abrirDetalle(tester, db);

      expect(find.text('Existencia conocida al ${fechaLocalEsperada(DateTime.utc(2026, 10, 31, 11, 15))}'), findsOneWidget);
    });

    testWidgets('una sucursal sin existencias descargadas dice "Sin existencias descargadas" y "Sin dato"', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        await b.insert('meta', {'clave': 'sucursal_activa:1:7', 'valor': '2'});
      });
      // Norte nunca se descargó y no hay stock de la variante 101 allí.
      await _abrirDetalle(tester, db, id: 11, enLinea: false);

      expect(find.text('Sin existencias descargadas'), findsOneWidget);
      expect(find.textContaining('Existencia conocida al'), findsNothing);
      expect(_enCelda(110, 'Sin dato'), findsOneWidget);
      expect(_enCelda(111, 'Sin dato'), findsOneWidget);
      expect(find.text('Agotado'), findsNothing);
    });

    testWidgets('descuenta lo vendido sin conexión que el servidor aún no refleja (existencia ESTIMADA)', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
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
          'total_centavos': 15000,
        });
        await b.insert('venta_detalle', {'venta_id': venta, 'variante_id': 100, 'cantidad': 4, 'precio_unitario_centavos': 7500});
      });
      await _abrirDetalle(tester, db);

      expect(_enCelda(100, '(1)'), findsOneWidget); // 5 conocidas - 4 vendidas
      expect(_enCelda(100, 'Quedan pocas'), findsOneWidget);
    });

    testWidgets('al cambiar de sucursal se muestran las existencias de la otra', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) => sembrarEscenarioBasico(b, descargaNorte: true));
      final e = await _abrirDetalle(tester, db);
      expect(_enCelda(100, '(5)'), findsOneWidget);

      await enBase(tester, db, (b) => b.insert('meta', {'clave': 'sucursal_activa:1:7', 'valor': '2'}));
      e.contenedor.invalidate(sucursalActivaProvider);
      await asentar(tester, rondas: 15);

      expect(_enCelda(100, '(1)'), findsOneWidget);
      expect(_enCelda(101, 'Agotado'), findsOneWidget);
    });
  });

  group('DetalleLocalScreen - estados', () {
    testWidgets('una prenda que no existe dice "No encontramos esta prenda." y deja volver', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      final e = await _abrirDetalle(tester, db, id: 999);

      expect(find.text(textoPrendaNoEncontrada), findsOneWidget);
      expect(find.text('No encontramos esta prenda.'), findsOneWidget);

      await tester.tap(find.widgetWithText(ElevatedButton, 'Volver al catálogo'));
      await tester.pump();
      await asentar(tester);
      expect(e.ruta, '/vendedor/catalogo');
    });

    testWidgets('si se llegó desde el catálogo, "Volver" regresa a él', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      final e = await abrirCatalogoLocal(tester, db: db);
      e.router!.push('/vendedor/producto/999');
      await tester.pump();
      await asentar(tester);
      expect(find.text('No encontramos esta prenda.'), findsOneWidget);

      await tester.tap(find.widgetWithText(ElevatedButton, 'Volver al catálogo'));
      await tester.pumpAndSettle();
      expect(e.ruta, '/vendedor/catalogo');
    });

    testWidgets('una prenda de otra empresa se ve como si no existiera', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        await sembrarEmpresa(b, id: 2, codigo: 'andes', nombre: 'Andes');
        await sembrarReferencias(b, empresaId: 2, categoriaId: 20, categoria: 'Ajenas');
        await sembrarProducto(b, id: 50, empresaId: 2, nombre: 'Prenda Ajena', categoriaId: 20, variantes: [variante(500, tallaId: 201, colorId: 201)]);
      });
      await _abrirDetalle(tester, db, id: 50);

      expect(find.text('No encontramos esta prenda.'), findsOneWidget);
      expect(find.text('Prenda Ajena'), findsNothing);
    });

    testWidgets('una prenda dada de baja se ve como si no existiera', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        await b.update('producto', {'activo': 0}, where: 'id = 12');
      });
      await _abrirDetalle(tester, db, id: 12);

      expect(find.text('No encontramos esta prenda.'), findsOneWidget);
    });

    testWidgets('no tiene botón de compra', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrirDetalle(tester, db);

      expect(find.byType(ElevatedButton), findsNothing);
      expect(find.byType(FilledButton), findsNothing);
      expect(find.textContaining('Comprar'), findsNothing);
      expect(find.textContaining('Agregar'), findsNothing);
      expect(find.textContaining('Vender'), findsNothing);
    });

    testWidgets('con el servicio de conectividad en "sin conexión" todo se ve y avisa', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrirDetalle(tester, db, enLinea: false);

      expect(find.text(textoSinConexion), findsOneWidget);
      expect(find.byType(AvisoVigencia), findsOneWidget);
      expect(find.textContaining('Sin conexión. Los datos se actualizaron el'), findsOneWidget);
      expect(_celda(100), findsOneWidget);
      expect(_enCelda(100, 'Hay'), findsOneWidget);
    });

    testWidgets('el aviso de vigencia va arriba y no bloquea el detalle', (tester) async {
      final db = await abrirBaseSembrada(
        tester,
        siembra: (b) => sembrarEscenarioBasico(b, descargadoEn: instanteBase.subtract(const Duration(hours: 4))),
      );
      await _abrirDetalle(tester, db);

      expect(find.textContaining('(hace 4 h). Pueden estar desactualizados.'), findsOneWidget);
      expect(tester.getTopLeft(find.byType(AvisoVigencia)).dy, lessThan(tester.getTopLeft(find.byKey(const Key('foto_alterna_10'))).dy));
      expect(_celda(100), findsOneWidget);
    });

    testWidgets('las celdas miden al menos 48 de alto', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await _abrirDetalle(tester, db);

      expect(tester.getSize(_celda(100)).height, greaterThanOrEqualTo(48));
    });
  });
}
