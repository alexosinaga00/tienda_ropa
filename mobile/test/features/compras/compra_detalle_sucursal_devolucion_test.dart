import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/compras/models/plazo_cambio.dart';
import 'package:mobile/features/compras/models/venta.dart';
import 'package:mobile/features/compras/presentation/compra_detalle_screen.dart';
import 'package:mobile/features/compras/state/compras_providers.dart';

import '../../helpers/solicitudes_cambio_falsas.dart';

Venta _venta({
  int? sucursalId = 2,
  int devueltas = 0,
  int cantidad = 4,
  double envio = 0,
}) => Venta.fromJson({
  'id': 7,
  'codigo': 'V-0007',
  'estado': 'pagada',
  'fecha': '2026-11-04T10:00:00',
  'subtotal': '100.00',
  'descuento': '0.00',
  'costo_envio': envio.toStringAsFixed(2),
  'total': '100.00',
  'sucursal_id': sucursalId,
  'unidades_devueltas': devueltas,
  'detalle': [
    {
      'id': 1,
      'variante_id': 3,
      'cantidad': cantidad,
      'precio_unitario': '25.00',
      'subtotal': '100.00',
    },
  ],
});

Widget _pantalla(Venta venta, {Future<String?> Function()? sucursal}) =>
    ProviderScope(
      overrides: [
        compraDetalleProvider(7).overrideWith((ref) async => venta),
        plazoCambioProvider(7).overrideWith(
          (ref) async => PlazoCambio.fromJson({
            'vigente': true,
            'vence_en': '2026-11-05T14:30:00Z',
            'plazo_horas': 24,
          }),
        ),
        envioDeCompraProvider(7).overrideWith((ref) async => null),
        ...solicitudesCambioFalsas(7),
        if (venta.sucursalId != null)
          nombreSucursalProvider(
            venta.sucursalId!,
          ).overrideWith((ref) => (sucursal ?? () async => 'Centro')()),
      ],
      child: const MaterialApp(home: CompraDetalleScreen(ventaId: 7)),
    );

void main() {
  testWidgets(
    'dice en qué sucursal es la compra y adónde llevar la prenda a cambiar',
    (tester) async {
      await tester.pumpWidget(_pantalla(_venta()));
      await tester.pumpAndSettle();

      expect(find.text('Retiro en sucursal · Centro'), findsOneWidget);
      expect(
        find.textContaining('Lleva la prenda a la sucursal Centro'),
        findsOneWidget,
      );
    },
  );

  testWidgets('en un envío a domicilio dice qué sucursal despacha', (
    tester,
  ) async {
    await tester.pumpWidget(_pantalla(_venta(envio: 15)));
    await tester.pumpAndSettle();

    expect(find.text('Envío a domicilio · despacha Centro'), findsOneWidget);
  });

  testWidgets('si no se pudo saber la sucursal, queda el texto de siempre', (
    tester,
  ) async {
    await tester.pumpWidget(_pantalla(_venta(), sucursal: () async => null));
    await tester.pumpAndSettle();

    expect(find.text('Retiro en sucursal'), findsOneWidget);
    expect(find.textContaining('Lleva la prenda a la tienda'), findsOneWidget);
  });

  testWidgets('una compra con devolución sigue "Pagada" pero lo dice', (
    tester,
  ) async {
    await tester.pumpWidget(_pantalla(_venta(devueltas: 1)));
    await tester.pumpAndSettle();

    expect(find.text('Pagada'), findsOneWidget);
    expect(find.text('Con devolución (1 de 4)'), findsOneWidget);
  });

  testWidgets('devuelta por completo dice "Devuelta"', (tester) async {
    await tester.pumpWidget(_pantalla(_venta(devueltas: 4)));
    await tester.pumpAndSettle();

    expect(find.text('Devuelta'), findsOneWidget);
  });

  testWidgets('sin devoluciones no dice nada de devolución', (tester) async {
    await tester.pumpWidget(_pantalla(_venta()));
    await tester.pumpAndSettle();

    expect(find.textContaining('devolución'), findsNothing);
    expect(find.text('Devuelta'), findsNothing);
  });

  test(
    'Venta lee la sucursal y las unidades devueltas, y una respuesta vieja sin ellas queda en cero',
    () {
      final nueva = _venta(devueltas: 2);
      expect(nueva.sucursalId, 2);
      expect(nueva.unidadesDevueltas, 2);
      expect(nueva.etiquetaDevolucion, 'Con devolución (2 de 4)');

      final vieja = Venta.fromJson({
        'id': 1,
        'codigo': 'V-1',
        'estado': 'pagada',
        'fecha': '2026-11-04T10:00:00',
        'subtotal': '10.00',
        'descuento': '0.00',
        'costo_envio': '0.00',
        'total': '10.00',
        'detalle': <Map<String, dynamic>>[],
      });
      expect(vieja.sucursalId, isNull);
      expect(vieja.unidadesDevueltas, 0);
      expect(vieja.etiquetaDevolucion, isNull);
    },
  );
}
