import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/compras/models/plazo_cambio.dart';
import 'package:mobile/features/compras/models/solicitud_cambio.dart';
import 'package:mobile/features/compras/models/venta.dart';
import 'package:mobile/features/compras/presentation/compra_detalle_screen.dart';
import 'package:mobile/features/compras/presentation/mis_compras_screen.dart';
import 'package:mobile/features/compras/state/compras_providers.dart';
import 'package:mobile/features/compras/state/mis_compras_controller.dart';

import '../../helpers/solicitudes_cambio_falsas.dart';

/// `devueltas` por línea: null = el servidor no manda `cantidad_devuelta` (respuesta de una versión anterior).
Venta _venta({List<int?> devueltas = const [null, null], int unidadesDevueltas = 0}) => Venta.fromJson({
  'id': 7,
  'codigo': 'V-0007',
  'estado': 'pagada',
  'fecha': '2026-11-04T10:00:00Z',
  'subtotal': '400.00',
  'descuento': '0.00',
  'costo_envio': '0.00',
  'total': '400.00',
  'sucursal_id': 2,
  'unidades_devueltas': unidadesDevueltas,
  'detalle': [
    {
      'id': 1,
      'variante_id': 3,
      'cantidad': 3,
      'precio_unitario': '100.00',
      'subtotal': '300.00',
      if (devueltas[0] != null) 'cantidad_devuelta': devueltas[0],
    },
    {
      'id': 2,
      'variante_id': 8,
      'cantidad': 1,
      'precio_unitario': '100.00',
      'subtotal': '100.00',
      if (devueltas[1] != null) 'cantidad_devuelta': devueltas[1],
    },
  ],
});

/// La venta con nombres de prenda, como la deja `compraDetalleProvider` (lo que ve la pantalla).
Venta _conNombres(Venta v) => v.conDetalle([
  for (final (i, nombre) in ['Polera Nike', 'Pantalón Adidas'].indexed)
    v.detalle[i].conExhibicion(productoNombre: nombre, imagenPrincipal: null, tallaCodigo: 'M', colorNombre: null),
]);

const _opciones = {
  1: [OpcionCambio(varianteId: 4, etiqueta: 'L', disponible: 5)],
  2: [OpcionCambio(varianteId: 9, etiqueta: '34', disponible: 2)],
};

Future<int> _abrir(WidgetTester tester, Venta venta) async {
  tester.view.physicalSize = const Size(800, 3200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  var pedidosDePlazo = 0;
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        compraDetalleProvider(7).overrideWith((ref) async => _conNombres(venta)),
        plazoCambioProvider(7).overrideWith((ref) async {
          pedidosDePlazo++;
          return PlazoCambio.fromJson({'vigente': true, 'vence_en': '2026-11-05T14:30:00Z', 'plazo_horas': 24});
        }),
        envioDeCompraProvider(7).overrideWith((ref) async => null),
        nombreSucursalProvider(2).overrideWith((ref) async => 'Centro'),
        ...solicitudesCambioFalsas(7, opciones: _opciones),
      ],
      child: const MaterialApp(home: CompraDetalleScreen(ventaId: 7)),
    ),
  );
  await tester.pumpAndSettle();
  return pedidosDePlazo;
}

void main() {
  group('VentaLinea y Venta con cantidad_devuelta', () {
    test('la lee y, si falta o es nula, queda en cero', () {
      final venta = _venta(devueltas: [2, null]);
      expect(venta.detalle[0].cantidadDevuelta, 2);
      expect(venta.detalle[0].cantidadRestante, 1);
      expect(venta.detalle[1].cantidadDevuelta, 0);
      expect(venta.detalle[1].cantidadRestante, 1);

      final nula = Venta.fromJson({
        ..._jsonBase,
        'detalle': [
          {
            'id': 1,
            'variante_id': 3,
            'cantidad': 1,
            'precio_unitario': '1',
            'subtotal': '1',
            'cantidad_devuelta': null,
          },
        ],
      });
      expect(nula.detalle.single.cantidadDevuelta, 0);
    });

    test('lo restante nunca es negativo', () {
      final venta = _venta(devueltas: [9, 0]);
      expect(venta.detalle[0].cantidadRestante, 0);
    });

    test('conExhibicion conserva lo devuelto', () {
      final venta = _conNombres(_venta(devueltas: [2, 0]));
      expect(venta.detalle[0].cantidadDevuelta, 2);
      expect(venta.detalle[0].productoNombre, 'Polera Nike');
    });

    test('solo las líneas con algo por cambiar son cambiables', () {
      expect(_venta(devueltas: [3, 0]).lineasCambiables.map((l) => l.id), [2]);
      expect(_venta(devueltas: [0, 0]).lineasCambiables.map((l) => l.id), [1, 2]);
      expect(_venta(devueltas: [3, 1]).hayPrendasCambiables, isFalse);
      expect(_venta(devueltas: [3, 0]).hayPrendasCambiables, isTrue);
    });

    test('un servidor que no manda la cantidad por línea se calcula con el total devuelto', () {
      expect(_venta(unidadesDevueltas: 4).hayPrendasCambiables, isFalse);
      expect(_venta(unidadesDevueltas: 1).hayPrendasCambiables, isTrue);
      expect(_venta().hayPrendasCambiables, isTrue);
    });

    test('el aviso de devolución parcial dice cuántas se devolvieron', () {
      expect(
        _venta(devueltas: [1, 0], unidadesDevueltas: 1).avisoDevolucionParcial,
        'Ya devolviste 1 de 4 prendas de esta compra.',
      );
      expect(_venta(devueltas: [1, 1]).avisoDevolucionParcial, 'Ya devolviste 2 de 4 prendas de esta compra.');
      expect(_venta().avisoDevolucionParcial, isNull);
    });
  });

  group('detalle de una compra ya devuelta', () {
    testWidgets('devuelta por completo: ni el plazo ni la sección, y no se pide el plazo al servidor', (tester) async {
      final pedidos = await _abrir(tester, _venta(devueltas: [3, 1], unidadesDevueltas: 4));

      expect(find.text('Devuelta'), findsOneWidget);
      expect(find.text('Cambiar talla o color'), findsNothing);
      expect(find.textContaining('Puedes cambiar tu prenda'), findsNothing);
      expect(find.textContaining('plazo'), findsNothing);
      expect(find.byKey(const Key('enviar-solicitud-cambio')), findsNothing);
      expect(pedidos, 0);
    });

    testWidgets('devuelta por completo según el total (servidor sin cantidad por línea): tampoco se ofrece', (
      tester,
    ) async {
      final pedidos = await _abrir(tester, _venta(unidadesDevueltas: 4));

      expect(find.text('Cambiar talla o color'), findsNothing);
      expect(pedidos, 0);
    });

    testWidgets('devolución parcial: solo ofrece lo que queda y lo dice', (tester) async {
      final pedidos = await _abrir(tester, _venta(devueltas: [3, 0], unidadesDevueltas: 3));

      expect(pedidos, 1);
      expect(find.text('Cambiar talla o color'), findsOneWidget);
      expect(find.text('Ya devolviste 3 de 4 prendas de esta compra.'), findsOneWidget);
      // La polera se devolvió entera: no se ofrece; el pantalón sí.
      expect(find.byKey(const Key('cambiar-por-1')), findsNothing);
      expect(find.byKey(const Key('cambiar-por-2')), findsOneWidget);
    });

    testWidgets('devolución parcial en una línea: el máximo por prenda es lo que queda', (tester) async {
      await _abrir(tester, _venta(devueltas: [2, 0], unidadesDevueltas: 2));

      expect(find.byKey(const Key('cambiar-por-1')), findsOneWidget);
      await tester.tap(find.byKey(const Key('cambiar-por-1')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('L · quedan 5').last);
      await tester.pumpAndSettle();

      // Elegir cuenta una unidad; de 3 compradas se devolvieron 2, así que queda 1 y no se puede subir.
      expect(tester.widget<IconButton>(find.byKey(const Key('mas-1'))).onPressed, isNull);
      expect(find.textContaining('· devolviste 2'), findsOneWidget);
    });

    testWidgets('sin devoluciones se ofrece todo y no hay aviso de devolución', (tester) async {
      await _abrir(tester, _venta(devueltas: [0, 0]));

      expect(find.byKey(const Key('cambiar-por-1')), findsOneWidget);
      expect(find.byKey(const Key('cambiar-por-2')), findsOneWidget);
      expect(find.byKey(const Key('aviso-devolucion-parcial')), findsNothing);
      await tester.tap(find.byKey(const Key('cambiar-por-1')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('L · quedan 5').last);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('mas-1')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('mas-1')));
      await tester.pump();
      expect(tester.widget<IconButton>(find.byKey(const Key('mas-1'))).onPressed, isNull); // llegó a 3
    });
  });

  group('Mis compras', () {
    testWidgets('una compra devuelta por completo se ve "Devuelta" y no ofrece cambio', (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            misComprasControllerProvider.overrideWith(
              (ref) => _ComprasFalsas(ref, [
                _venta(devueltas: [3, 1], unidadesDevueltas: 4),
              ]),
            ),
            comprasConCambioPendienteProvider.overrideWith((ref) async => <int>{}),
          ],
          child: const MaterialApp(home: MisComprasScreen()),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.textContaining('Devuelta'), findsOneWidget);
      expect(find.textContaining('Cambiar'), findsNothing);
    });
  });
}

const _jsonBase = {
  'id': 7,
  'codigo': 'V-0007',
  'estado': 'pagada',
  'fecha': '2026-11-04T10:00:00Z',
  'subtotal': '1.00',
  'descuento': '0.00',
  'costo_envio': '0.00',
  'total': '1.00',
};

class _ComprasFalsas extends MisComprasController {
  _ComprasFalsas(super.ref, List<Venta> ventas) : super(activo: false) {
    state = AsyncValue.data(ventas);
  }
}
