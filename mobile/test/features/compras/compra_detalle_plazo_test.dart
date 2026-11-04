import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/compras/models/plazo_cambio.dart';
import 'package:mobile/features/compras/models/venta.dart';
import 'package:mobile/features/compras/presentation/compra_detalle_screen.dart';
import 'package:mobile/features/compras/state/compras_providers.dart';

import '../../helpers/solicitudes_cambio_falsas.dart';

Venta _venta(String estado) => Venta.fromJson({
  'id': 7,
  'codigo': 'V-0007',
  'estado': estado,
  'fecha': '2026-11-04T10:00:00',
  'subtotal': '100.00',
  'descuento': '0.00',
  'costo_envio': '0.00',
  'total': '100.00',
  'detalle': [
    {'id': 1, 'variante_id': 3, 'cantidad': 1, 'precio_unitario': '100.00', 'subtotal': '100.00'},
  ],
});

Widget _pantalla(String estado, Future<PlazoCambio?> Function() plazo) => ProviderScope(
  overrides: [
    compraDetalleProvider(7).overrideWith((ref) async => _venta(estado)),
    plazoCambioProvider(7).overrideWith((ref) => plazo()),
    envioDeCompraProvider(7).overrideWith((ref) async => null),
    ...solicitudesCambioFalsas(7),
  ],
  child: const MaterialApp(home: CompraDetalleScreen(ventaId: 7)),
);

PlazoCambio _plazo({required bool vigente}) =>
    PlazoCambio.fromJson({'vigente': vigente, 'vence_en': '2026-11-05T14:30:00Z', 'plazo_horas': 24});

void main() {
  testWidgets('una compra pagada dentro del plazo dice hasta cuándo se puede cambiar', (tester) async {
    await tester.pumpWidget(_pantalla('pagada', () async => _plazo(vigente: true)));
    await tester.pumpAndSettle();

    expect(find.textContaining('Puedes cambiar tu prenda hasta el'), findsOneWidget);
    expect(find.textContaining('cambia la talla o el color en caja'), findsOneWidget);
  });

  testWidgets('pasado el plazo lo dice y no ofrece el cambio', (tester) async {
    await tester.pumpWidget(_pantalla('entregada', () async => _plazo(vigente: false)));
    await tester.pumpAndSettle();

    expect(find.textContaining('El plazo para cambiar esta compra venció el'), findsOneWidget);
    expect(find.textContaining('Puedes cambiar'), findsNothing);
  });

  testWidgets('una compra pendiente de pago no muestra el plazo', (tester) async {
    await tester.pumpWidget(_pantalla('pendiente_pago', () async => _plazo(vigente: true)));
    await tester.pumpAndSettle();

    expect(find.textContaining('cambiar'), findsNothing);
    expect(find.text('V-0007'), findsOneWidget);
  });

  testWidgets('si no se pudo saber el plazo, el comprobante se ve igual y sin aviso', (tester) async {
    await tester.pumpWidget(_pantalla('pagada', () async => null));
    await tester.pumpAndSettle();

    expect(find.textContaining('Puedes cambiar'), findsNothing);
    expect(find.textContaining('venció'), findsNothing);
    expect(find.text('V-0007'), findsOneWidget);
  });

  test('PlazoCambio lee la fecha del servidor en UTC y la pasa a hora local', () {
    final plazo = _plazo(vigente: true);

    expect(plazo.venceEn.toUtc(), DateTime.utc(2026, 11, 5, 14, 30));
    expect(plazo.plazoHoras, 24);
  });
}
