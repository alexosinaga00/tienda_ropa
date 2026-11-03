import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/sync/cola_operaciones.dart';
import 'package:mobile/core/sync/motor_sincronizacion.dart';
import 'package:mobile/core/sync/operacion_pendiente.dart';
import 'package:mobile/core/widgets/indicador_conexion.dart';
import 'package:mobile/features/vendedor/presentation/componentes_operacion.dart';
import 'package:mobile/features/vendedor/state/nueva_venta_controller.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';
import 'apoyo_catalogo_local.dart';
import 'apoyo_nueva_operacion.dart';
import 'apoyo_pantallas_sync.dart' show textosConVoseo;

const _rutaNueva = '/vendedor/venta/nueva';

Finder get _botonRegistrar => find.byKey(const Key('boton_registrar_venta'));
Finder get _casilla => find.byKey(const Key('casilla_efectivo'));
Finder get _botonAgregarPrenda => find.byKey(const Key('boton_agregar_prenda'));

bool _registrarHabilitado(WidgetTester tester) => tester.widget<ElevatedButton>(_botonRegistrar).onPressed != null;

String _total(WidgetTester tester) => tester.widget<Text>(find.byKey(const Key('total_venta'))).data!;

String _cantidadEn(WidgetTester tester, int varianteId) =>
    tester.widget<Text>(find.descendant(of: find.byKey(Key('cantidad_$varianteId')), matching: find.byType(Text))).data!;

String _subtotalEn(WidgetTester tester, int varianteId) => tester.widget<Text>(find.byKey(Key('subtotal_$varianteId'))).data!;

/// El nombre de la prenda como título de la línea (el recuadro sin foto ya no repite el nombre, pero se distingue por el estilo).
Finder _nombreEnLinea(int varianteId, String nombre) => find.descendant(
  of: find.byKey(Key('linea_$varianteId')),
  matching: find.byWidgetPredicate((w) => w is Text && w.data == nombre),
);

Future<EscenarioNuevaOperacion> _abrir(
  WidgetTester tester,
  Database db, {
  bool enLinea = true,
  ColaEspia? cola,
  BloqueoSync? bloqueo,
}) => abrirNuevaOperacion(tester, db: db, ruta: _rutaNueva, enLinea: enLinea, cola: cola, bloqueo: bloqueo);

/// Agrega una prenda con el selector: abre la hoja, elige el producto, [talla] y [cantidad], y confirma.
Future<void> _agregar(WidgetTester tester, int productoId, {String? talla, int cantidad = 1}) async {
  await tester.tap(_botonAgregarPrenda);
  await esperar(tester);
  await tester.tap(find.byKey(Key('prenda_$productoId')));
  await esperar(tester);
  if (talla != null) {
    await tester.tap(find.byKey(Key('talla_$talla')));
    await tester.pump();
  }
  for (var i = 1; i < cantidad; i++) {
    await tester.tap(find.byKey(const Key('selector_mas')));
    await tester.pump();
  }
  await tester.tap(find.byKey(const Key('boton_agregar')));
  await tester.pumpAndSettle();
}

Future<void> _marcarEfectivo(WidgetTester tester) async {
  await tester.tap(_casilla);
  await tester.pump();
}

/// Una venta lista para registrar: Polera S x[cantidad] y el efectivo recibido.
Future<void> _prepararVenta(WidgetTester tester, {int cantidad = 1}) async {
  await _agregar(tester, 10, talla: 'S', cantidad: cantidad);
  await _marcarEfectivo(tester);
}

Future<void> _registrar(WidgetTester tester) async {
  await tester.tap(_botonRegistrar);
  await esperar(tester);
}

Future<Database> _dbBasica(WidgetTester tester, {bool descargaNorte = false}) =>
    abrirBaseSembrada(tester, siembra: (b) => sembrarEscenarioBasico(b, descargaNorte: descargaNorte));

void main() {
  group('NuevaVentaScreen - al abrir', () {
    testWidgets('muestra la venta vacía: sucursal, sin prendas, total en cero y el botón desactivado', (tester) async {
      final db = await _dbBasica(tester);
      await _abrir(tester, db);

      expect(find.descendant(of: find.byType(AppBar), matching: find.text('Nueva venta')), findsOneWidget);
      expect(find.text('Sucursal'), findsOneWidget);
      expect(find.text('Todavía no agregaste prendas.'), findsOneWidget);
      expect(find.text('Cliente (opcional)'), findsOneWidget);
      expect(find.text('Puedes dejar la venta sin cliente.'), findsOneWidget);
      expect(find.byKey(const Key('forma_pago')), findsOneWidget);
      expect(find.text('Forma de pago: Efectivo'), findsOneWidget);
      expect(find.text('Efectivo recibido'), findsOneWidget);
      expect(_total(tester), 'Total Bs 0.00');
      expect(_registrarHabilitado(tester), isFalse);
      expect(find.byKey(const Key('ayuda_registro')), findsNothing); // sin prendas no hay nada que corregir todavía
    });

    testWidgets('dice que la venta queda en el teléfono y que el servidor la confirmará (no es una aprobación)', (tester) async {
      final db = await _dbBasica(tester);
      await _abrir(tester, db);

      expect(find.text(textoAyudaGuardado), findsOneWidget);
      expect(find.textContaining('El servidor la confirmará'), findsOneWidget);
    });

    testWidgets('el id de la operación se pide UNA vez, al abrir la pantalla, y no cambia al editar', (tester) async {
      final db = await _dbBasica(tester);
      final e = await _abrir(tester, db);

      expect(e.generador.pedidos, 1);
      await _prepararVenta(tester);
      await _registrar(tester);
      expect(e.generador.pedidos, 1);
      expect(e.cola.ventas.single.operacionId, GeneradorUuidFijo.idUno);
    });

    testWidgets('la sucursal es la activa del teléfono (una sola: sin menú)', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        await b.delete('sucursal_autorizada', where: 'sucursal_id = 2');
      });
      await _abrir(tester, db);

      expect(find.text('Centro'), findsOneWidget);
      expect(find.byKey(const Key('menu_sucursal')), findsNothing);
    });

    testWidgets('sin datos descargados explica qué hacer y no deja registrar', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEmpresa);
      await _abrir(tester, db);

      expect(find.text('Aún no descargaste el catálogo'), findsOneWidget);
      expect(find.text('Descárgalo con conexión para poder registrar sin conexión.'), findsOneWidget);
      expect(_botonRegistrar, findsNothing);
      expect(_botonAgregarPrenda, findsNothing);
      expect(find.widgetWithText(ElevatedButton, 'Actualizar datos'), findsOneWidget);
      expect(textosConVoseo(tester), isEmpty);
    });

    testWidgets('sin datos descargados, "Actualizar datos" pide la descarga y "Volver" regresa al inicio', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEmpresa);
      final e = await _abrir(tester, db);

      await tester.tap(find.widgetWithText(ElevatedButton, 'Actualizar datos'));
      await esperar(tester);
      expect(e.servicio.llamadas, 1);

      await tester.tap(find.widgetWithText(TextButton, 'Volver'));
      await esperar(tester);
      expect(e.ruta, '/vendedor');
      expect(find.text('PANTALLA INICIO'), findsOneWidget);
    });

    testWidgets('un bloqueo del plan o la suscripción muestra el aviso pero deja registrar', (tester) async {
      final db = await _dbBasica(tester);
      final e = await _abrir(
        tester,
        db,
        bloqueo: const BloqueoSync(tipo: TipoBloqueo.planNoIncluye, mensaje: 'Tu plan no incluye operar sin conexión.'),
      );

      expect(find.byKey(const Key('aviso_bloqueo_sync')), findsOneWidget);
      expect(find.text('Tu plan no incluye operar sin conexión.'), findsOneWidget);
      expect(find.byType(AvisoBloqueoSync), findsOneWidget);

      await _prepararVenta(tester);
      expect(_registrarHabilitado(tester), isTrue);
      await _registrar(tester);
      expect(e.cola.ventas.single.operacionId, GeneradorUuidFijo.idUno);
      expect(e.ruta, '/vendedor/operaciones/${GeneradorUuidFijo.idUno}');
    });

    testWidgets('sin bloqueo no hay aviso', (tester) async {
      final db = await _dbBasica(tester);
      await _abrir(tester, db);

      expect(find.byKey(const Key('aviso_bloqueo_sync')), findsNothing);
    });

    testWidgets('sin conexión muestra el banner pero todo funciona igual y no se sincroniza', (tester) async {
      final db = await _dbBasica(tester);
      final e = await _abrir(tester, db, enLinea: false);

      expect(find.text(textoSinConexion), findsOneWidget);
      await _prepararVenta(tester);
      await _registrar(tester);

      expect(e.cola.ventas.single.lineas.single.cantidad, 1);
      expect(e.cola.de('marcarEnviadas'), isEmpty); // la pantalla solo guarda: el disparador sincroniza
      expect(e.cola.todas.single.estado, EstadoOperacion.registrada);
      expect(e.ruta, '/vendedor/operaciones/${GeneradorUuidFijo.idUno}');
    });
  });

  group('NuevaVentaScreen - las prendas', () {
    testWidgets('agregar una prenda la muestra con nombre, talla y color, precio, cantidad y subtotal', (tester) async {
      final db = await _dbBasica(tester);
      await _abrir(tester, db);
      await _agregar(tester, 10, talla: 'S');

      expect(find.byKey(const Key('linea_100')), findsOneWidget);
      expect(_nombreEnLinea(100, 'Polera Básica'), findsWidgets);
      expect(find.text('S · Negro'), findsOneWidget);
      expect(find.text('Bs 75.00 c/u'), findsOneWidget);
      expect(_cantidadEn(tester, 100), '1');
      expect(_subtotalEn(tester, 100), 'Subtotal Bs 75.00');
      expect(_total(tester), 'Total Bs 75.00');
      expect(find.text('Todavía no agregaste prendas.'), findsNothing);
    });

    testWidgets('la cantidad elegida en el selector se respeta', (tester) async {
      final db = await _dbBasica(tester);
      await _abrir(tester, db);
      await _agregar(tester, 10, talla: 'S', cantidad: 3);

      expect(_cantidadEn(tester, 100), '3');
      expect(_total(tester), 'Total Bs 225.00');
    });

    testWidgets('agregar la misma variante otra vez suma a su línea (no crea otra)', (tester) async {
      final db = await _dbBasica(tester);
      await _abrir(tester, db);
      await _agregar(tester, 10, talla: 'S');
      await _agregar(tester, 10, talla: 'S', cantidad: 2);

      expect(find.byKey(const Key('linea_100')), findsOneWidget);
      expect(_cantidadEn(tester, 100), '3');
    });

    testWidgets('variantes y prendas distintas son líneas distintas y el total las suma', (tester) async {
      final db = await _dbBasica(tester);
      await _abrir(tester, db);
      await _agregar(tester, 10, talla: 'S', cantidad: 2); // 2 x 75,00
      await _agregar(tester, 10, talla: 'M'); // 1 x 75,00
      await _agregar(tester, 11, talla: 'S'); // 1 x 50,00

      expect(find.byKey(const Key('linea_100')), findsOneWidget);
      expect(find.byKey(const Key('linea_101')), findsOneWidget);
      expect(find.byKey(const Key('linea_110')), findsOneWidget);
      expect(_total(tester), 'Total Bs 275.00');
    });

    testWidgets('el descuento se resta del precio: se ve el precio tachado y el total lo descuenta', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        await b.update('variante', {'descuento_centavos': 500}, where: 'id = 100');
      });
      final e = await _abrir(tester, db);
      await _agregar(tester, 10, talla: 'S', cantidad: 2);
      await _agregar(tester, 11, talla: 'S');

      expect(find.text('Bs 70.00 c/u'), findsOneWidget);
      expect(
        find.byWidgetPredicate((w) => w is Text && w.data == 'Bs 75.00' && w.style?.decoration == TextDecoration.lineThrough),
        findsOneWidget,
      );
      expect(_subtotalEn(tester, 100), 'Subtotal Bs 140.00');
      expect(_total(tester), 'Total Bs 190.00'); // (75 - 5) x 2 + 50

      await _marcarEfectivo(tester);
      await _registrar(tester);
      final venta = e.cola.ventas.single;
      expect(venta.lineas.map((l) => (l.varianteId, l.cantidad, l.precioUnitarioCentavos, l.descuentoUnitarioCentavos)), [
        (100, 2, 7500, 500),
        (110, 1, 5000, 0),
      ]);
      expect(venta.totalCentavos, 19000);
    });

    testWidgets('"Más" y "Menos" cambian la cantidad y el total; "Menos" se desactiva en 1', (tester) async {
      final db = await _dbBasica(tester);
      await _abrir(tester, db);
      await _agregar(tester, 10, talla: 'S');

      expect(tester.widget<IconButton>(find.byKey(const Key('cantidad_menos_100'))).onPressed, isNull);
      await tester.tap(find.byKey(const Key('cantidad_mas_100')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('cantidad_mas_100')));
      await tester.pump();
      expect(_cantidadEn(tester, 100), '3');
      expect(_subtotalEn(tester, 100), 'Subtotal Bs 225.00');
      expect(_total(tester), 'Total Bs 225.00');

      await tester.tap(find.byKey(const Key('cantidad_menos_100')));
      await tester.pump();
      expect(_cantidadEn(tester, 100), '2');
      expect(_total(tester), 'Total Bs 150.00');
    });

    testWidgets('quitar una línea la saca y deja las demás; sin prendas vuelve el mensaje y se desactiva el botón', (tester) async {
      final db = await _dbBasica(tester);
      await _abrir(tester, db);
      await _agregar(tester, 10, talla: 'S');
      await _agregar(tester, 11, talla: 'S');
      await _marcarEfectivo(tester);
      expect(_registrarHabilitado(tester), isTrue);

      await tester.tap(find.byKey(const Key('quitar_100')));
      await tester.pump();
      expect(find.byKey(const Key('linea_100')), findsNothing);
      expect(find.byKey(const Key('linea_110')), findsOneWidget);
      expect(_total(tester), 'Total Bs 50.00');

      await tester.tap(find.byKey(const Key('quitar_110')));
      await tester.pump();
      expect(find.text('Todavía no agregaste prendas.'), findsOneWidget);
      expect(_total(tester), 'Total Bs 0.00');
      expect(_registrarHabilitado(tester), isFalse);
    });

    testWidgets('cerrar el selector sin elegir no agrega nada', (tester) async {
      final db = await _dbBasica(tester);
      await _abrir(tester, db);

      await tester.tap(_botonAgregarPrenda);
      await esperar(tester);
      await tester.tap(find.byTooltip('Cerrar'));
      await tester.pumpAndSettle();

      expect(find.text('Todavía no agregaste prendas.'), findsOneWidget);
    });

    testWidgets('los botones de cantidad, quitar y registrar miden al menos 48', (tester) async {
      final db = await _dbBasica(tester);
      await _abrir(tester, db);
      await _agregar(tester, 10, talla: 'S');

      for (final k in ['cantidad_mas_100', 'quitar_100', 'boton_agregar_prenda', 'boton_registrar_venta', 'boton_elegir_cliente']) {
        final tam = tester.getSize(find.byKey(Key(k)));
        expect(tam.height, greaterThanOrEqualTo(48), reason: k);
        expect(tam.width, greaterThanOrEqualTo(48), reason: k);
      }
      expect(tester.getSize(_casilla).height, greaterThanOrEqualTo(48));
    });
  });

  group('NuevaVentaScreen - el cobro y el botón', () {
    testWidgets('con prendas pero sin marcar el efectivo, el botón está desactivado y dice qué falta', (tester) async {
      final db = await _dbBasica(tester);
      await _abrir(tester, db);
      await _agregar(tester, 10, talla: 'S');

      expect(_registrarHabilitado(tester), isFalse);
      expect(tester.widget<Text>(find.byKey(const Key('ayuda_registro'))).data, 'Confirma que recibiste el efectivo.');
    });

    testWidgets('efectivo marcado sin prendas tampoco deja registrar', (tester) async {
      final db = await _dbBasica(tester);
      await _abrir(tester, db);
      await _marcarEfectivo(tester);

      expect(tester.widget<CheckboxListTile>(_casilla).value, isTrue);
      expect(_registrarHabilitado(tester), isFalse);
    });

    testWidgets('con prendas y efectivo el botón se activa, y al desmarcar vuelve a desactivarse', (tester) async {
      final db = await _dbBasica(tester);
      await _abrir(tester, db);
      await _prepararVenta(tester);

      expect(_registrarHabilitado(tester), isTrue);
      expect(find.byKey(const Key('ayuda_registro')), findsNothing);

      await _marcarEfectivo(tester);
      expect(tester.widget<CheckboxListTile>(_casilla).value, isFalse);
      expect(_registrarHabilitado(tester), isFalse);
    });

    testWidgets('el botón dice "Registrar venta"', (tester) async {
      final db = await _dbBasica(tester);
      await _abrir(tester, db);

      expect(find.descendant(of: _botonRegistrar, matching: find.text('Registrar venta')), findsOneWidget);
    });
  });

  group('NuevaVentaScreen - el cliente', () {
    testWidgets('elegir un cliente descargado lo muestra con su CI/NIT y "Quitar" lo deja sin cliente', (tester) async {
      late int anaId;
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        anaId = await sembrarClienteServidor(b, servidorId: 501, nombre: 'Ana', apellido: 'Pérez', ciNit: '1234567');
        await sembrarClienteServidor(b, servidorId: 502, nombre: 'Beto', apellido: null);
      });
      await _abrir(tester, db);

      await tester.tap(find.byKey(const Key('boton_elegir_cliente')));
      await esperar(tester);
      expect(find.text('Elige un cliente'), findsOneWidget);
      await tester.tap(find.byKey(Key('cliente_$anaId')));
      await tester.pumpAndSettle();

      expect(tester.widget<Text>(find.byKey(const Key('cliente_elegido'))).data, 'Ana Pérez');
      expect(find.text('CI/NIT: 1234567'), findsOneWidget);
      expect(find.byKey(const Key('boton_elegir_cliente')), findsNothing);

      await tester.tap(find.byKey(const Key('boton_cambiar_cliente')));
      await tester.pump();
      expect(find.byKey(const Key('cliente_elegido')), findsNothing);
      expect(find.byKey(const Key('boton_elegir_cliente')), findsOneWidget);
    });

    testWidgets('el selector solo ofrece clientes que el servidor conoce', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        await sembrarClienteServidor(b, servidorId: 501, nombre: 'Ana', apellido: 'Pérez');
        await b.insert('cliente_minimo', {'empresa_id': 1, 'nombre': 'Solo Teléfono', 'creado_en': '2026-10-31T09:00:00Z'});
      });
      await _abrir(tester, db);

      await tester.tap(find.byKey(const Key('boton_elegir_cliente')));
      await esperar(tester);
      expect(find.text('Ana Pérez'), findsOneWidget);
      expect(find.text('Solo Teléfono'), findsNothing);
    });

    testWidgets('sin clientes descargados el selector lo explica y la venta sigue sin cliente', (tester) async {
      final db = await _dbBasica(tester);
      final e = await _abrir(tester, db);

      await tester.tap(find.byKey(const Key('boton_elegir_cliente')));
      await esperar(tester);
      expect(find.textContaining('Sin conexión solo se pueden usar los clientes ya descargados'), findsOneWidget);
      await tester.tap(find.byTooltip('Cerrar'));
      await tester.pumpAndSettle();

      await _prepararVenta(tester);
      await _registrar(tester);
      expect(e.cola.ventas.single.clienteMinimoId, isNull);
    });
  });

  group('NuevaVentaScreen - la sucursal', () {
    testWidgets('con varias sucursales autorizadas hay un menú con la activa', (tester) async {
      final db = await _dbBasica(tester, descargaNorte: true);
      await _abrir(tester, db);

      expect(find.byKey(const Key('menu_sucursal')), findsOneWidget);
      expect(find.descendant(of: find.byKey(const Key('menu_sucursal')), matching: find.text('Centro')), findsOneWidget);
    });

    testWidgets('sin prendas, cambiar de sucursal no pregunta; la venta usa la nueva', (tester) async {
      final db = await _dbBasica(tester, descargaNorte: true);
      final e = await _abrir(tester, db);

      await tester.tap(find.byKey(const Key('menu_sucursal')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Norte'));
      await esperar(tester);

      expect(find.text('Cambiar de sucursal'), findsNothing);
      expect(find.descendant(of: find.byKey(const Key('menu_sucursal')), matching: find.text('Norte')), findsOneWidget);

      await _prepararVenta(tester); // en Norte queda 1 de la Polera S: alcanza
      await _registrar(tester);
      expect(e.cola.ventas.single.sucursalId, 2);
    });

    testWidgets('con prendas pregunta antes de cambiar y, al confirmar, las quita', (tester) async {
      final db = await _dbBasica(tester, descargaNorte: true);
      await _abrir(tester, db);
      await _agregar(tester, 10, talla: 'S', cantidad: 2);
      await _marcarEfectivo(tester);

      await tester.tap(find.byKey(const Key('menu_sucursal')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Norte'));
      await tester.pumpAndSettle();
      expect(find.text('Cambiar de sucursal'), findsOneWidget);
      expect(find.textContaining('Se quitarán las prendas que agregaste'), findsOneWidget);

      await tester.tap(find.text('Cambiar y quitar prendas'));
      await esperar(tester);

      expect(find.byKey(const Key('linea_100')), findsNothing);
      expect(find.text('Todavía no agregaste prendas.'), findsOneWidget);
      expect(_total(tester), 'Total Bs 0.00');
      expect(find.descendant(of: find.byKey(const Key('menu_sucursal')), matching: find.text('Norte')), findsOneWidget);
      expect(_registrarHabilitado(tester), isFalse);
    });

    testWidgets('si se cancela el cambio, las prendas y la sucursal quedan como estaban', (tester) async {
      final db = await _dbBasica(tester, descargaNorte: true);
      await _abrir(tester, db);
      await _agregar(tester, 10, talla: 'S', cantidad: 2);

      await tester.tap(find.byKey(const Key('menu_sucursal')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Norte'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancelar'));
      await esperar(tester);

      expect(find.byKey(const Key('linea_100')), findsOneWidget);
      expect(_cantidadEn(tester, 100), '2');
      expect(find.descendant(of: find.byKey(const Key('menu_sucursal')), matching: find.text('Centro')), findsOneWidget);
    });

    testWidgets('el aviso de stock usa la existencia de la sucursal elegida', (tester) async {
      final db = await _dbBasica(tester, descargaNorte: true);
      final e = await _abrir(tester, db);
      await tester.tap(find.byKey(const Key('menu_sucursal')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Norte'));
      await esperar(tester);

      await _prepararVenta(tester, cantidad: 2); // en Norte queda 1
      await _registrar(tester);
      expect(find.text('Puede faltar stock'), findsOneWidget);
      expect(find.text('Queda 1 de Polera Básica (S, Negro)'), findsOneWidget);
      expect(e.cola.ventas, isEmpty);
    });
  });

  group('NuevaVentaScreen - registrar', () {
    testWidgets('flujo completo: la cola recibe la venta con todos sus datos y se abre el resultado', (tester) async {
      late int anaId;
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        anaId = await sembrarClienteServidor(b, servidorId: 501, nombre: 'Ana', apellido: 'Pérez');
      });
      final e = await _abrir(tester, db);

      await _agregar(tester, 10, talla: 'S', cantidad: 2);
      await _agregar(tester, 11, talla: 'S');
      await tester.tap(find.byKey(const Key('boton_elegir_cliente')));
      await esperar(tester);
      await tester.tap(find.byKey(Key('cliente_$anaId')));
      await tester.pumpAndSettle();
      await _marcarEfectivo(tester);
      expect(_registrarHabilitado(tester), isTrue);
      await _registrar(tester);

      final venta = e.cola.ventas.single;
      expect(venta.operacionId, GeneradorUuidFijo.idUno);
      expect(venta.empresaId, 1);
      expect(venta.usuarioId, 7);
      expect(venta.sucursalId, 1);
      expect(venta.fechaOperacion, instanteBase);
      expect(venta.clienteMinimoId, anaId);
      expect(venta.efectivoConfirmado, isTrue);
      expect(venta.lineas.map((l) => (l.varianteId, l.cantidad, l.precioUnitarioCentavos, l.descuentoUnitarioCentavos)), [
        (100, 2, 7500, 0),
        (110, 1, 5000, 0),
      ]);
      expect(venta.totalCentavos, 20000);
      expect(e.cola.todas.single.estado, EstadoOperacion.registrada);

      expect(e.ruta, '/vendedor/operaciones/${GeneradorUuidFijo.idUno}');
      expect(find.text('RESULTADO ${GeneradorUuidFijo.idUno} nuevo=1'), findsOneWidget);
      expect(find.text('Nueva venta'), findsNothing); // se reemplazó la pantalla: atrás no vuelve a una venta ya registrada
    });

    testWidgets('el precio queda congelado: si el catálogo cambia después, la línea conserva el precio con que entró (D17)', (tester) async {
      final db = await _dbBasica(tester);
      final e = await _abrir(tester, db);
      await _agregar(tester, 10, talla: 'S');

      await enBase(tester, db, (b) => b.update('variante', {'precio_centavos': 9900}, where: 'id = 100'));
      await _agregar(tester, 10, talla: 'S');

      expect(_cantidadEn(tester, 100), '2');
      expect(find.text('Bs 75.00 c/u'), findsOneWidget);
      expect(_total(tester), 'Total Bs 150.00');

      await _marcarEfectivo(tester);
      await _registrar(tester);
      expect(e.cola.ventas.single.lineas.single.precioUnitarioCentavos, 7500);
      expect(e.cola.ventas.single.totalCentavos, 15000);
    });

    testWidgets('sin cliente la venta va sin cliente', (tester) async {
      final db = await _dbBasica(tester);
      final e = await _abrir(tester, db);
      await _prepararVenta(tester);
      await _registrar(tester);

      expect(e.cola.ventas.single.clienteMinimoId, isNull);
    });

    testWidgets('mientras guarda, el botón muestra un indicador y queda desactivado', (tester) async {
      final db = await _dbBasica(tester);
      final e = await _abrir(tester, db);
      await _prepararVenta(tester);

      e.cola.puerta = Completer<void>();
      await tester.tap(_botonRegistrar);
      await tester.pump();
      await asentar(tester);

      expect(find.descendant(of: _botonRegistrar, matching: find.byType(CircularProgressIndicator)), findsOneWidget);
      expect(_registrarHabilitado(tester), isFalse);
      e.cola.puerta!.complete();
      await esperar(tester);
      expect(e.ruta, '/vendedor/operaciones/${GeneradorUuidFijo.idUno}');
    });

    testWidgets('un doble toque en "Registrar venta" registra UNA sola vez y navega una vez', (tester) async {
      final db = await _dbBasica(tester);
      final e = await _abrir(tester, db);
      await _prepararVenta(tester);

      e.cola.puerta = Completer<void>();
      await tester.tap(_botonRegistrar);
      await tester.tap(_botonRegistrar); // el segundo toque llega antes de que la pantalla se redibuje
      await tester.pump();
      await asentar(tester);
      expect(e.cola.ventas.length, 1);

      e.cola.puerta!.complete();
      await esperar(tester);
      expect(e.cola.ventas.length, 1);
      expect(e.cola.todas.length, 1);
      expect(e.ruta, '/vendedor/operaciones/${GeneradorUuidFijo.idUno}');
      expect(find.byKey(const Key('error_registro')), findsNothing);
    });

    testWidgets('un ColaError muestra su mensaje, deja la pantalla como estaba y permite reintentar con el MISMO id', (tester) async {
      final db = await _dbBasica(tester);
      final e = await _abrir(tester, db);
      await _prepararVenta(tester);

      e.cola.errorAlRegistrar = const ColaError('Una de las prendas ya no está disponible. Actualiza tus datos e intenta de nuevo.');
      await _registrar(tester);

      expect(find.byKey(const Key('error_registro')), findsOneWidget);
      expect(
        tester.widget<Text>(find.byKey(const Key('error_registro'))).data,
        'Una de las prendas ya no está disponible. Actualiza tus datos e intenta de nuevo.',
      );
      expect(e.ruta, _rutaNueva);
      expect(find.byKey(const Key('linea_100')), findsOneWidget);
      expect(_registrarHabilitado(tester), isTrue);
      expect(e.cola.todas, isEmpty);

      await _registrar(tester);
      expect(e.cola.ventas.map((v) => v.operacionId), [GeneradorUuidFijo.idUno, GeneradorUuidFijo.idUno]);
      expect(e.cola.todas.single.operacionId, GeneradorUuidFijo.idUno);
      expect(e.ruta, '/vendedor/operaciones/${GeneradorUuidFijo.idUno}');
    });

    testWidgets('un fallo inesperado de la cola muestra un texto claro, no la excepción', (tester) async {
      final db = await _dbBasica(tester);
      final e = await _abrir(tester, db);
      await _prepararVenta(tester);

      e.cola.errorAlRegistrar = StateError('boom');
      await _registrar(tester);

      expect(tester.widget<Text>(find.byKey(const Key('error_registro'))).data, textoFalloGuardarVenta);
      expect(find.textContaining('boom'), findsNothing);
      expect(textosConVoseo(tester), isEmpty);
    });

    testWidgets('editar la venta borra el error anterior', (tester) async {
      final db = await _dbBasica(tester);
      final e = await _abrir(tester, db);
      await _prepararVenta(tester);
      e.cola.errorAlRegistrar = const ColaError('No se pudo.');
      await _registrar(tester);
      expect(find.byKey(const Key('error_registro')), findsOneWidget);

      await tester.tap(find.byKey(const Key('cantidad_mas_100')));
      await tester.pump();
      expect(find.byKey(const Key('error_registro')), findsNothing);
    });
  });

  group('NuevaVentaScreen - puede faltar stock', () {
    testWidgets('si se pide más de lo que se estima, el diálogo avisa SIN registrar', (tester) async {
      final db = await _dbBasica(tester);
      final e = await _abrir(tester, db);
      await _prepararVenta(tester, cantidad: 6); // Polera S: quedan 5
      await _registrar(tester);

      expect(find.text('Puede faltar stock'), findsOneWidget);
      expect(find.text('Quedan 5 de Polera Básica (S, Negro)'), findsOneWidget);
      expect(find.textContaining('El servidor decide al sincronizar'), findsOneWidget);
      expect(find.text('Revisar'), findsOneWidget);
      expect(find.text('Registrar igual'), findsOneWidget);
      expect(e.cola.ventas, isEmpty);
      expect(textosConVoseo(tester), isEmpty);
    });

    testWidgets('"Revisar" vuelve a la venta sin registrar y el botón sigue activo', (tester) async {
      final db = await _dbBasica(tester);
      final e = await _abrir(tester, db);
      await _prepararVenta(tester, cantidad: 6);
      await _registrar(tester);

      await tester.tap(find.text('Revisar'));
      await tester.pumpAndSettle();

      expect(find.text('Puede faltar stock'), findsNothing);
      expect(e.cola.ventas, isEmpty);
      expect(e.ruta, _rutaNueva);
      expect(_cantidadEn(tester, 100), '6');
      expect(_registrarHabilitado(tester), isTrue);

      // Corrige la cantidad: ahora alcanza y registra sin preguntar.
      for (var i = 0; i < 4; i++) {
        await tester.tap(find.byKey(const Key('cantidad_menos_100')));
        await tester.pump();
      }
      await _registrar(tester);
      expect(find.text('Puede faltar stock'), findsNothing);
      expect(e.cola.ventas.single.lineas.single.cantidad, 2);
    });

    testWidgets('"Registrar igual" guarda la venta con la cantidad pedida y abre el resultado', (tester) async {
      final db = await _dbBasica(tester);
      final e = await _abrir(tester, db);
      await _prepararVenta(tester, cantidad: 6);
      await _registrar(tester);

      await tester.tap(find.text('Registrar igual'));
      await esperar(tester);

      expect(e.cola.ventas.single.lineas.single.cantidad, 6);
      expect(e.cola.ventas.single.operacionId, GeneradorUuidFijo.idUno);
      expect(find.text('RESULTADO ${GeneradorUuidFijo.idUno} nuevo=1'), findsOneWidget);
    });

    testWidgets('una variante agotada avisa que no queda ninguna', (tester) async {
      final db = await _dbBasica(tester);
      final e = await _abrir(tester, db);
      await _agregar(tester, 11, talla: 'M'); // Camisa Lino M: 0
      await _marcarEfectivo(tester);
      await _registrar(tester);

      expect(find.text('No queda ninguna de Camisa Lino (M, Negro)'), findsOneWidget);
      expect(e.cola.ventas, isEmpty);
    });

    testWidgets('pedir exactamente lo que queda no avisa', (tester) async {
      final db = await _dbBasica(tester);
      final e = await _abrir(tester, db);
      await _prepararVenta(tester, cantidad: 5);
      await _registrar(tester);

      expect(find.text('Puede faltar stock'), findsNothing);
      expect(e.cola.ventas.single.lineas.single.cantidad, 5);
    });

    testWidgets('lista cada línea que se pasa y no las que alcanzan', (tester) async {
      final db = await _dbBasica(tester);
      await _abrir(tester, db);
      await _agregar(tester, 10, talla: 'S'); // alcanza
      await _agregar(tester, 11, talla: 'S', cantidad: 3); // quedan 2
      await _agregar(tester, 11, talla: 'M'); // 0
      await _marcarEfectivo(tester);
      await _registrar(tester);

      expect(find.text('Quedan 2 de Camisa Lino (S, Negro)'), findsOneWidget);
      expect(find.text('No queda ninguna de Camisa Lino (M, Negro)'), findsOneWidget);
      expect(find.textContaining('Polera Básica (S, Negro)'), findsNothing);
    });

    testWidgets('un doble toque con el diálogo de stock abre UN solo diálogo', (tester) async {
      final db = await _dbBasica(tester);
      final e = await _abrir(tester, db);
      await _prepararVenta(tester, cantidad: 6);

      await tester.tap(_botonRegistrar);
      await tester.tap(_botonRegistrar);
      await esperar(tester);

      expect(find.text('Puede faltar stock'), findsOneWidget);
      await tester.tap(find.text('Registrar igual'));
      await esperar(tester);
      expect(e.cola.ventas.length, 1);
    });
  });

  group('NuevaVentaScreen - lenguaje', () {
    testWidgets('los textos de la pantalla armada van en tuteo (sin voseo)', (tester) async {
      late int anaId;
      final db = await abrirBaseSembrada(tester, siembra: (b) async {
        await sembrarEscenarioBasico(b);
        anaId = await sembrarClienteServidor(b, servidorId: 501, nombre: 'Ana', apellido: 'Pérez', ciNit: '1234567');
      });
      await _abrir(
        tester,
        db,
        bloqueo: const BloqueoSync(tipo: TipoBloqueo.suscripcionNoActiva, mensaje: 'La suscripción de tu empresa no está activa.'),
      );
      await _agregar(tester, 10, talla: 'S');
      await tester.tap(find.byKey(const Key('boton_elegir_cliente')));
      await esperar(tester);
      await tester.tap(find.byKey(Key('cliente_$anaId')));
      await tester.pumpAndSettle();

      expect(textosConVoseo(tester), isEmpty);
      expect(find.text('Confirma que recibiste el efectivo.'), findsOneWidget);
    });
  });
}
