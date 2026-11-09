import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/conectividad/conectividad_service.dart';
import 'package:mobile/core/utils/fecha_servidor.dart';
import 'package:mobile/features/compras/data/ventas_repository.dart';
import 'package:mobile/features/compras/models/reembolso.dart';
import 'package:mobile/features/compras/models/venta.dart';
import 'package:mobile/features/compras/presentation/compra_detalle_screen.dart';
import 'package:mobile/features/compras/state/compras_providers.dart';

import '../../helpers/solicitudes_cambio_falsas.dart';

Map<String, dynamic> _json({
  int id = 70,
  String metodo = 'efectivo',
  String monto = '25.50',
  String estado = 'reembolsado',
  String? completadoEn = '2026-11-05T15:10:00Z',
}) => {
  'id': id,
  'devolucion_id': 5,
  'pago_id': 3,
  'venta_id': 7,
  'sucursal_id': 2,
  'metodo': metodo,
  'monto': monto,
  'monto_usd': null,
  'estado': estado,
  'referencia_externa': null,
  'motivo_fallo': null,
  'creado_en': '2026-11-05T15:00:00Z',
  'completado_en': completadoEn,
};

Reembolso _reembolso({
  int id = 70,
  String metodo = 'efectivo',
  String monto = '25.50',
  String estado = 'reembolsado',
  String? completadoEn = '2026-11-05T15:10:00Z',
}) => Reembolso.fromJson(_json(id: id, metodo: metodo, monto: monto, estado: estado, completadoEn: completadoEn));

class _Adaptador implements HttpClientAdapter {
  _Adaptador(this.responder);

  final ResponseBody Function(RequestOptions options) responder;
  final peticiones = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(RequestOptions options, Stream<Uint8List>? requestStream, Future<void>? cancelFuture) async {
    peticiones.add(options);
    return responder(options);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody _cuerpo(String json, [int estado = 200]) => ResponseBody.fromString(
  json,
  estado,
  headers: {
    Headers.contentTypeHeader: [Headers.jsonContentType],
  },
);

Venta _venta({String estado = 'pagada'}) => Venta(
  id: 7,
  codigo: 'V-0007',
  estado: estado,
  fecha: DateTime(2026, 11, 4, 10),
  subtotal: 100,
  descuento: 0,
  costoEnvio: 0,
  total: 100,
  sucursalId: 2,
  detalle: const [
    VentaLinea(
      id: 1,
      varianteId: 3,
      cantidad: 1,
      precioUnitario: 100,
      subtotal: 100,
      productoNombre: 'Polera Nike',
      tallaCodigo: 'M',
      colorNombre: 'Blanco',
    ),
  ],
);

Future<void> _abrir(WidgetTester tester, List<Override> reembolsos, {Venta? venta}) async {
  tester.view.physicalSize = const Size(800, 3200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final compra = venta ?? _venta();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        compraDetalleProvider(7).overrideWith((ref) async => compra),
        plazoCambioProvider(7).overrideWith((ref) async => null),
        envioDeCompraProvider(7).overrideWith((ref) async => null),
        nombreSucursalProvider(2).overrideWith((ref) async => 'Centro'),
        ...solicitudesCambioFalsas(7),
        ...reembolsos,
      ],
      child: const MaterialApp(home: CompraDetalleScreen(ventaId: 7)),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('Reembolso', () {
    test('lee el contrato del servidor: montos como texto y fechas UTC pasadas a hora local', () {
      final r = Reembolso.fromJson({..._json(metodo: 'paypal'), 'monto_usd': '3.66'});

      expect(r.id, 70);
      expect(r.devolucionId, 5);
      expect(r.pagoId, 3);
      expect(r.ventaId, 7);
      expect(r.sucursalId, 2);
      expect(r.metodo, 'paypal');
      expect(r.monto, '25.50');
      expect(r.montoUsd, '3.66');
      expect(r.estaReembolsado, isTrue);
      expect(r.creadoEn.toUtc(), DateTime.utc(2026, 11, 5, 15));
      expect(r.completadoEn!.toUtc(), DateTime.utc(2026, 11, 5, 15, 10));
    });

    test('es defensivo: lo que falta o viene raro no rompe', () {
      final r = Reembolso.fromJson({'id': 1, 'venta_id': 7, 'monto': 25, 'creado_en': 'no es fecha'});

      expect(r.metodo, '');
      expect(r.estado, '');
      expect(r.estaReembolsado, isFalse);
      expect(r.devolucionId, isNull);
      expect(r.completadoEn, isNull);
      expect(r.monto, '25');
      expect(r.montoTexto, 'Bs 25.00');
      expect(r.comoSeDevuelve, 'por el mismo medio con que pagaste');
    });

    test('el monto se formatea sin pasar por double', () {
      expect(_reembolso(monto: '25.5').montoTexto, 'Bs 25.50');
      expect(_reembolso(monto: '0.10').montoTexto, 'Bs 0.10');
      expect(_reembolso(monto: '1234.00').montoTexto, 'Bs 1234.00');
      // Un monto raro se muestra tal cual en vez de lanzar.
      expect(_reembolso(monto: 'abc').montoTexto, 'Bs abc');
    });

    test('"Reembolsado" solo cuando está reembolsado; pendiente, fallido y desconocido son "En proceso"', () {
      expect(_reembolso(estado: 'reembolsado').etiquetaEstado, 'Reembolsado');
      expect(_reembolso(estado: 'pendiente', completadoEn: null).etiquetaEstado, 'En proceso');
      expect(_reembolso(estado: 'fallido', completadoEn: null).etiquetaEstado, 'En proceso');
      expect(_reembolso(estado: 'algo_nuevo', completadoEn: null).etiquetaEstado, 'En proceso');
    });

    test('cómo se devolvió el dinero según el método', () {
      const esperado = {
        'efectivo': 'en efectivo, en la tienda',
        'paypal': 'a tu PayPal',
        'qr': 'por QR',
        'qr_online': 'por QR',
        'tarjeta': 'a tu tarjeta',
        'transferencia': 'por transferencia',
        'cripto': 'por el mismo medio con que pagaste',
        '': 'por el mismo medio con que pagaste',
      };
      esperado.forEach((metodo, texto) {
        expect(_reembolso(metodo: metodo).comoSeDevuelve, texto, reason: metodo);
      });
    });

    test('la fecha es la de cuando se completó; en proceso, la de cuando se pidió', () {
      expect(_reembolso().fecha.toUtc(), DateTime.utc(2026, 11, 5, 15, 10));
      expect(_reembolso(estado: 'pendiente', completadoEn: null).fecha.toUtc(), DateTime.utc(2026, 11, 5, 15));
      // Reembolsado pero el servidor no mandó la fecha de cierre: no se rompe.
      expect(_reembolso(completadoEn: null).fecha.toUtc(), DateTime.utc(2026, 11, 5, 15));
    });
  });

  group('VentasRepository.reembolsos', () {
    test('pide los reembolsos de la compra y los lee en orden', () async {
      final adaptador = _Adaptador(
        (o) => _cuerpo('[${_jsonTexto(70, "efectivo")}, ${_jsonTexto(71, "paypal")}]'),
      );
      final repositorio = VentasRepository(Dio(BaseOptions(baseUrl: 'http://test'))..httpClientAdapter = adaptador);

      final lista = await repositorio.reembolsos(7);

      expect(adaptador.peticiones.single.method, 'GET');
      expect(adaptador.peticiones.single.path, '/ventas/7/reembolsos');
      expect(lista.map((r) => r.id), [70, 71]);
      expect(lista.last.metodo, 'paypal');
    });

    test('sin reembolsos, lista vacía', () async {
      final repositorio = VentasRepository(
        Dio(BaseOptions(baseUrl: 'http://test'))..httpClientAdapter = _Adaptador((o) => _cuerpo('[]')),
      );

      expect(await repositorio.reembolsos(7), isEmpty);
    });
  });

  group('reembolsosDeCompraProvider', () {
    test('si la consulta falla (sin conexión) queda vacío, sin lanzar', () async {
      final adaptador = _Adaptador((o) => _cuerpo('{"detail":"error"}', 500));
      final contenedor = ProviderContainer(
        overrides: [
          ventasRepositoryProvider.overrideWithValue(
            VentasRepository(Dio(BaseOptions(baseUrl: 'http://test'))..httpClientAdapter = adaptador),
          ),
        ],
      );
      addTearDown(contenedor.dispose);

      expect(await contenedor.read(reembolsosDeCompraProvider(7).future), isEmpty);
    });

    test('con reembolsos los devuelve', () async {
      final adaptador = _Adaptador((o) => _cuerpo('[${_jsonTexto(70, "efectivo")}]'));
      final contenedor = ProviderContainer(
        overrides: [
          ventasRepositoryProvider.overrideWithValue(
            VentasRepository(Dio(BaseOptions(baseUrl: 'http://test'))..httpClientAdapter = adaptador),
          ),
        ],
      );
      addTearDown(contenedor.dispose);

      final lista = await contenedor.read(reembolsosDeCompraProvider(7).future);

      expect(lista.single.id, 70);
    });
  });

  group('detalle de la compra: dinero devuelto', () {
    testWidgets('sin reembolsos no aparece la sección', (tester) async {
      await _abrir(tester, []);

      expect(find.byKey(const Key('reembolsos-compra')), findsNothing);
      expect(find.text('Dinero devuelto'), findsNothing);
    });

    testWidgets('muestra monto, cómo se devolvió, fecha local y estado de cada reembolso', (tester) async {
      await _abrir(tester, [
        reembolsosDeCompraProvider(7).overrideWith(
          (ref) async => [
            _reembolso(),
            _reembolso(id: 71, metodo: 'paypal', monto: '10.00', estado: 'pendiente', completadoEn: null),
          ],
        ),
      ]);

      expect(find.text('Dinero devuelto'), findsOneWidget);
      expect(find.text('Bs 25.50'), findsOneWidget);
      expect(find.text('Te lo devolvimos en efectivo, en la tienda'), findsOneWidget);
      final devuelto = formatearFechaHora(fechaDelServidor('2026-11-05T15:10:00Z'));
      expect(find.text('Devuelto el $devuelto'), findsOneWidget);
      expect(find.text('Reembolsado'), findsOneWidget);

      expect(find.text('Bs 10.00'), findsOneWidget);
      expect(find.text('Te lo devolveremos a tu PayPal'), findsOneWidget);
      final pedido = formatearFechaHora(fechaDelServidor('2026-11-05T15:00:00Z'));
      expect(find.text('Pedido el $pedido'), findsOneWidget);
      expect(find.text('En proceso'), findsOneWidget);
    });

    testWidgets('un reembolso fallido se le muestra al cliente como "En proceso", sin detalle técnico', (tester) async {
      await _abrir(tester, [
        reembolsosDeCompraProvider(7).overrideWith(
          (ref) async => [
            Reembolso.fromJson({
              ..._json(estado: 'fallido', completadoEn: null),
              'motivo_fallo': 'PayPal devolvió INSTRUMENT_DECLINED',
            }),
          ],
        ),
      ]);

      expect(find.text('En proceso'), findsOneWidget);
      expect(find.text('Reembolsado'), findsNothing);
      expect(find.textContaining('INSTRUMENT'), findsNothing);
      expect(find.textContaining('fall'), findsNothing);
    });

    testWidgets('sin conexión (la consulta falla) el comprobante se ve igual y no aparece la sección', (tester) async {
      tester.view.physicalSize = const Size(800, 3200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final adaptador = _Adaptador((o) => _cuerpo('{"detail":"sin red"}', 503));
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            compraDetalleProvider(7).overrideWith((ref) async => _venta()),
            plazoCambioProvider(7).overrideWith((ref) async => null),
            envioDeCompraProvider(7).overrideWith((ref) async => null),
            nombreSucursalProvider(2).overrideWith((ref) async => 'Centro'),
            // Lo de la sección de cambios, sin sustituir el provider de reembolsos: ese va por el repositorio, que falla.
            misSolicitudesCambioProvider(7).overrideWith((ref) async => const []),
            opcionesCambioProvider(7).overrideWith((ref) async => const {}),
            comprasConCambioPendienteProvider.overrideWith((ref) async => <int>{}),
            enLineaProvider.overrideWith((ref) => Stream.value(true)),
            ventasRepositoryProvider.overrideWithValue(
              VentasRepository(Dio(BaseOptions(baseUrl: 'http://test'))..httpClientAdapter = adaptador),
            ),
          ],
          child: const MaterialApp(home: CompraDetalleScreen(ventaId: 7)),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('V-0007'), findsOneWidget);
      expect(find.text('Dinero devuelto'), findsNothing);
    });

    testWidgets('una compra pendiente de pago no consulta reembolsos', (tester) async {
      await _abrir(tester, [
        reembolsosDeCompraProvider(7).overrideWith((ref) async => [_reembolso()]),
      ], venta: _venta(estado: 'pendiente_pago'));

      expect(find.text('Dinero devuelto'), findsNothing);
    });
  });
}

/// El JSON de un reembolso como texto (para el cuerpo de una respuesta HTTP).
String _jsonTexto(int id, String metodo) =>
    '{"id":$id,"devolucion_id":5,"pago_id":3,"venta_id":7,"sucursal_id":2,"metodo":"$metodo","monto":"25.50",'
    '"monto_usd":null,"estado":"reembolsado","referencia_externa":null,"motivo_fallo":null,'
    '"creado_en":"2026-11-05T15:00:00Z","completado_en":"2026-11-05T15:10:00Z"}';
