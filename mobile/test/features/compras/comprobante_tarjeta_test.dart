import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/compras/models/plazo_cambio.dart';
import 'package:mobile/features/compras/models/venta.dart';
import 'package:mobile/features/compras/pdf/comprobante_pdf.dart';
import 'package:mobile/features/compras/pdf/servicio_comprobante.dart';
import 'package:mobile/features/compras/presentation/compra_detalle_screen.dart';
import 'package:mobile/features/compras/state/compras_providers.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../../helpers/solicitudes_cambio_falsas.dart';

const _enlace = 'https://tienda.example/caja?venta=V-0007';

Venta _venta({String estado = 'pagada', Object? enlace = _enlace}) => Venta.fromJson({
  'id': 7,
  'codigo': 'V-0007',
  'estado': estado,
  'fecha': '2026-11-07T15:30:00Z',
  'subtotal': '300.00',
  'descuento': '0.00',
  'costo_envio': '0.00',
  'total': '300.00',
  'sucursal_id': 2,
  'enlace_verificacion': ?enlace,
  'detalle': [
    {'id': 1, 'variante_id': 3, 'cantidad': 3, 'precio_unitario': '100.00', 'subtotal': '300.00'},
  ],
});

class _ServicioFalso implements ServicioComprobante {
  _ServicioFalso({this.falla = false});

  final bool falla;
  final entregados = <DatosComprobante>[];

  @override
  Future<void> compartirPdf(DatosComprobante datos) async {
    if (falla) throw StateError('sin disco');
    entregados.add(datos);
  }
}

Future<void> _abrir(WidgetTester tester, Venta venta, {_ServicioFalso? servicio}) async {
  tester.view.physicalSize = const Size(800, 3600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        compraDetalleProvider(7).overrideWith((ref) async => venta),
        plazoCambioProvider(7).overrideWith(
          (ref) async => PlazoCambio.fromJson({'vigente': true, 'vence_en': '2026-11-08T14:30:00Z', 'plazo_horas': 24}),
        ),
        envioDeCompraProvider(7).overrideWith((ref) async => null),
        nombreSucursalProvider(2).overrideWith((ref) async => 'Centro'),
        servicioComprobanteProvider.overrideWithValue(servicio ?? _ServicioFalso()),
        ...solicitudesCambioFalsas(7),
      ],
      child: const MaterialApp(home: CompraDetalleScreen(ventaId: 7)),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('Venta.enlaceVerificacion', () {
    test('lo lee y es tolerante si falta, es null o está vacío', () {
      expect(_venta().enlaceVerificacion, _enlace);
      expect(_venta(enlace: null).enlaceVerificacion, isNull);
      expect(Venta.fromJson({..._json(), 'enlace_verificacion': null}).enlaceVerificacion, isNull);
      expect(Venta.fromJson({..._json(), 'enlace_verificacion': '  '}).enlaceVerificacion, isNull);
    });

    test('conDetalle lo conserva', () {
      expect(_venta().conDetalle(const []).enlaceVerificacion, _enlace);
    });

    test('solo una compra pagada o entregada tiene comprobante', () {
      expect(_venta(estado: 'pagada').tieneComprobante, isTrue);
      expect(_venta(estado: 'entregada').tieneComprobante, isTrue);
      expect(_venta(estado: 'pendiente_pago').tieneComprobante, isFalse);
      expect(_venta(estado: 'anulada').tieneComprobante, isFalse);
    });
  });

  group('tarjeta Comprobante', () {
    for (final estado in ['pagada', 'entregada']) {
      testWidgets('compra $estado: muestra código, fecha, sucursal, total y el QR del enlace', (tester) async {
        await _abrir(tester, _venta(estado: estado));

        expect(find.byKey(const Key('tarjeta-comprobante')), findsOneWidget);
        // El QR codifica EXACTAMENTE el enlace que manda el servidor (la llave lleva el texto dibujado).
        expect(find.byKey(const ValueKey('qr-comprobante:$_enlace')), findsOneWidget);
        expect(find.text('Descargar PDF'), findsOneWidget);
        final tarjeta = find.byKey(const Key('tarjeta-comprobante'));
        expect(find.descendant(of: tarjeta, matching: find.text('Comprobante V-0007')), findsOneWidget);
        expect(find.descendant(of: tarjeta, matching: find.text('Centro')), findsOneWidget);
        expect(find.descendant(of: tarjeta, matching: find.text('Bs 300.00')), findsOneWidget);
        // Dos fechas en hora local: la de la tarjeta tiene formato dd/MM/yyyy HH:mm.
        expect(
          find.descendant(of: tarjeta, matching: find.textContaining(RegExp(r'^\d{2}/\d{2}/2026 \d{2}:\d{2}$'))),
          findsOneWidget,
        );
      });
    }

    testWidgets('pendiente de pago: no hay comprobante', (tester) async {
      await _abrir(tester, _venta(estado: 'pendiente_pago'));

      expect(find.byKey(const Key('tarjeta-comprobante')), findsNothing);
      expect(find.byType(QrImageView), findsNothing);
      expect(find.text('Descargar PDF'), findsNothing);
    });

    testWidgets('anulada: no hay comprobante', (tester) async {
      await _abrir(tester, _venta(estado: 'anulada'));

      expect(find.byKey(const Key('tarjeta-comprobante')), findsNothing);
      expect(find.byType(QrImageView), findsNothing);
    });

    testWidgets('sin enlace no dibuja el QR, pero sí el resto y el botón', (tester) async {
      await _abrir(tester, _venta(enlace: null));

      expect(find.byKey(const Key('tarjeta-comprobante')), findsOneWidget);
      expect(find.byType(QrImageView), findsNothing);
      expect(find.byKey(const Key('descargar-pdf')), findsOneWidget);
      expect(find.text('Bs 300.00'), findsWidgets);
    });

    testWidgets('"Descargar PDF" entrega al servicio los datos de la compra', (tester) async {
      final servicio = _ServicioFalso();
      await _abrir(tester, _venta(), servicio: servicio);

      await tester.tap(find.byKey(const Key('descargar-pdf')));
      await tester.pumpAndSettle();

      expect(servicio.entregados, hasLength(1));
      final datos = servicio.entregados.single;
      expect(datos.codigo, 'V-0007');
      expect(datos.sucursal, 'Centro');
      expect(datos.total, 300);
      expect(datos.enlaceVerificacion, _enlace);
      expect(find.text('No se pudo generar el PDF. Inténtalo de nuevo.'), findsNothing);
    });

    testWidgets('si el PDF falla, avisa con un mensaje claro y el botón vuelve a estar disponible', (tester) async {
      await _abrir(tester, _venta(), servicio: _ServicioFalso(falla: true));

      await tester.tap(find.byKey(const Key('descargar-pdf')));
      await tester.pumpAndSettle();

      expect(find.text('No se pudo generar el PDF. Inténtalo de nuevo.'), findsOneWidget);
      expect(tester.widget<OutlinedButton>(find.byKey(const Key('descargar-pdf'))).onPressed, isNotNull);
      expect(tester.takeException(), isNull);
    });
  });
}

Map<String, dynamic> _json() => {
  'id': 7,
  'codigo': 'V-0007',
  'estado': 'pagada',
  'fecha': '2026-11-07T15:30:00Z',
  'subtotal': '1.00',
  'descuento': '0.00',
  'costo_envio': '0.00',
  'total': '1.00',
  'detalle': <Object>[],
};
