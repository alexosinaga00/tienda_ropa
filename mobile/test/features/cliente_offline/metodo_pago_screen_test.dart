import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/conectividad/conectividad_service.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/features/cliente_offline/data/metodo_pago_repository.dart';
import 'package:mobile/features/cliente_offline/models/metodo_pago.dart';
import 'package:mobile/features/cliente_offline/presentation/metodo_pago_screen.dart';
import 'package:mobile/features/cliente_offline/presentation/paypal_aprobacion_screen.dart';
import 'package:mobile/features/cliente_offline/presentation/retorno_paypal.dart';
import 'package:mobile/features/cliente_offline/state/cliente_offline_providers.dart';

import '../../helpers/api_client_falso.dart';

const _guardado = {'guardado': true, 'correo_paypal': 'j***@gmail.com', 'guardado_en': '2026-11-05T15:00:00Z'};
const _sinGuardar = {'guardado': false, 'correo_paypal': null, 'guardado_en': null};

class _Mundo {
  _Mundo(this.api, this.urlsAbiertas);

  final ApiClientFalso api;
  final List<String> urlsAbiertas;
}

Future<_Mundo> _montar(
  WidgetTester tester, {
  Object? estado = _sinGuardar,
  bool enLinea = true,
  RetornoPaypal? retorno = const RetornoCancelado(),
  Object? recordado,
}) async {
  final api = ApiClientFalso();
  if (estado != null) api.responder('GET', '/metodos-pago/paypal', estado);
  final urls = <String>[];
  tester.view.physicalSize = const Size(800, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        enLineaProvider.overrideWith((ref) => Stream.value(enLinea)),
        metodoPagoRepositoryProvider.overrideWithValue(MetodoPagoRepository(api)),
        repositorioClienteProvider.overrideWithValue(() async => null),
        abridorAprobacionPaypalProvider.overrideWithValue((context, url) async {
          urls.add(url);
          return retorno;
        }),
      ],
      child: const MaterialApp(home: MetodoPagoScreen()),
    ),
  );
  if (recordado != null) {
    final contenedor = ProviderScope.containerOf(tester.element(find.byType(MetodoPagoScreen)));
    await contenedor
        .read(metodoPagoLocalProvider.notifier)
        .recordar(MetodoPagoPaypal.fromJson(recordado as Map<String, dynamic>));
  }
  await tester.pumpAndSettle();
  return _Mundo(api, urls);
}

bool _habilitado(WidgetTester tester, String clave) {
  final w = tester.widget(find.byKey(Key(clave)));
  return switch (w) {
    ElevatedButton b => b.onPressed != null,
    OutlinedButton b => b.onPressed != null,
    _ => throw StateError('no es un botón'),
  };
}

void main() {
  group('estado del método de pago', () {
    testWidgets('con PayPal guardado muestra "Guardado" y el correo enmascarado', (tester) async {
      await _montar(tester, estado: _guardado);

      expect(find.byKey(const Key('paypal-guardado')), findsOneWidget);
      expect(find.text('Cuenta j***@gmail.com'), findsOneWidget);
      expect(find.text('Cambiar mi PayPal'), findsOneWidget);
      expect(find.byKey(const Key('quitar-paypal')), findsOneWidget);
      expect(find.byKey(const Key('dato-recordado')), findsNothing);
    });

    testWidgets('sin PayPal guardado invita a guardarlo y no ofrece quitar', (tester) async {
      await _montar(tester);

      expect(find.byKey(const Key('paypal-no-guardado')), findsOneWidget);
      expect(find.text('Guardar mi PayPal'), findsOneWidget);
      expect(find.byKey(const Key('quitar-paypal')), findsNothing);
      expect(find.textContaining('Sin él no puedes pagar un pedido hecho sin conexión'), findsOneWidget);
    });

    testWidgets('explica que FashionStore nunca ve ni guarda datos de tarjeta y que se cobra hasta el total aceptado', (
      tester,
    ) async {
      await _montar(tester);

      expect(find.textContaining('nunca ve ni guarda los datos de tu tarjeta'), findsOneWidget);
      expect(find.textContaining('hasta el total que veas y aceptes'), findsOneWidget);
    });

    testWidgets('sin conexión: se ve lo recordado, con su aviso, y guardar/quitar quedan desactivados', (tester) async {
      await _montar(tester, estado: null, enLinea: false, recordado: _guardado);

      expect(find.byKey(const Key('aviso-sin-conexion')), findsOneWidget);
      expect(find.text('Sin conexión: ves lo que ya tenías cargado'), findsOneWidget);
      expect(find.byKey(const Key('paypal-guardado')), findsOneWidget);
      expect(find.text('Cuenta j***@gmail.com'), findsOneWidget);
      expect(find.byKey(const Key('dato-recordado')), findsOneWidget);
      expect(find.byKey(const Key('motivo-sin-conexion')), findsOneWidget);
      expect(_habilitado(tester, 'guardar-paypal'), isFalse);
      expect(_habilitado(tester, 'quitar-paypal'), isFalse);
    });

    testWidgets('sin conexión y sin nada recordado dice que no se pudo consultar', (tester) async {
      await _montar(tester, estado: null, enLinea: false);

      expect(find.byKey(const Key('paypal-desconocido')), findsOneWidget);
      expect(_habilitado(tester, 'guardar-paypal'), isFalse);
    });
  });

  group('guardar mi PayPal', () {
    testWidgets('abre la URL de aprobación, confirma con el token que devolvió PayPal y queda guardado', (
      tester,
    ) async {
      final m = await _montar(tester, retorno: const RetornoAprobado('APPROVAL-1'));
      m.api
        ..responder('POST', '/metodos-pago/paypal/iniciar', {
          'url_aprobacion': 'https://sandbox.paypal.com/aprobar?t=1',
          'token_preparacion': 'APPROVAL-1',
        })
        ..responder('POST', '/metodos-pago/paypal/confirmar', _guardado);

      await tester.tap(find.byKey(const Key('guardar-paypal')));
      await tester.pumpAndSettle();

      expect(m.api.de('POST', '/metodos-pago/paypal/iniciar').single.cuerpo, {'canal': 'app'});
      expect(m.urlsAbiertas, ['https://sandbox.paypal.com/aprobar?t=1']);
      expect(m.api.de('POST', '/metodos-pago/paypal/confirmar').single.cuerpo, {'token_preparacion': 'APPROVAL-1'});
      expect(find.byKey(const Key('paypal-guardado')), findsOneWidget);
      expect(find.text('Cuenta j***@gmail.com'), findsOneWidget);
      expect(find.text(textoPaypalGuardadoExito), findsOneWidget);
    });

    testWidgets('si el cliente cancela en PayPal no se confirma nada', (tester) async {
      final m = await _montar(tester);
      m.api.responder('POST', '/metodos-pago/paypal/iniciar', {
        'url_aprobacion': 'https://sandbox.paypal.com/aprobar',
        'token_preparacion': 't',
      });

      await tester.tap(find.byKey(const Key('guardar-paypal')));
      await tester.pumpAndSettle();

      expect(m.api.de('POST', '/metodos-pago/paypal/confirmar'), isEmpty);
      expect(find.text(textoPaypalCancelado), findsOneWidget);
      expect(find.byKey(const Key('paypal-no-guardado')), findsOneWidget);
    });

    testWidgets('si PayPal volvió sin token lo dice y no confirma', (tester) async {
      final m = await _montar(tester, retorno: const RetornoSinDatos());
      m.api.responder('POST', '/metodos-pago/paypal/iniciar', {
        'url_aprobacion': 'https://sandbox.paypal.com/aprobar',
        'token_preparacion': 't',
      });

      await tester.tap(find.byKey(const Key('guardar-paypal')));
      await tester.pumpAndSettle();

      expect(m.api.de('POST', '/metodos-pago/paypal/confirmar'), isEmpty);
      expect(find.byKey(const Key('error-metodo')), findsOneWidget);
    });

    testWidgets('409 paypal_no_aprobado: mensaje claro y no queda guardado', (tester) async {
      final m = await _montar(tester, retorno: const RetornoAprobado('t'));
      m.api
        ..responder('POST', '/metodos-pago/paypal/iniciar', {
          'url_aprobacion': 'https://sandbox.paypal.com/aprobar',
          'token_preparacion': 't',
        })
        ..responder(
          'POST',
          '/metodos-pago/paypal/confirmar',
          const ErrorApp(tipo: TipoErrorApp.conflicto, mensaje: 'x', estado: 409, codigo: 'paypal_no_aprobado'),
        );

      await tester.tap(find.byKey(const Key('guardar-paypal')));
      await tester.pumpAndSettle();

      expect(find.textContaining('No se aprobó tu PayPal'), findsOneWidget);
      expect(find.byKey(const Key('paypal-no-guardado')), findsOneWidget);
    });

    testWidgets('503 paypal_no_disponible al iniciar: no se abre PayPal', (tester) async {
      final m = await _montar(tester);
      m.api.responder(
        'POST',
        '/metodos-pago/paypal/iniciar',
        const ErrorApp(tipo: TipoErrorApp.servidor, mensaje: 'x', estado: 503, codigo: 'paypal_no_disponible'),
      );

      await tester.tap(find.byKey(const Key('guardar-paypal')));
      await tester.pumpAndSettle();

      expect(m.urlsAbiertas, isEmpty);
      expect(find.textContaining('PayPal no responde por ahora'), findsOneWidget);
    });

    testWidgets('una URL de aprobación que no es http(s) no se abre', (tester) async {
      final m = await _montar(tester);
      m.api.responder('POST', '/metodos-pago/paypal/iniciar', {
        'url_aprobacion': 'javascript:alert(1)',
        'token_preparacion': 't',
      });

      await tester.tap(find.byKey(const Key('guardar-paypal')));
      await tester.pumpAndSettle();

      expect(m.urlsAbiertas, isEmpty);
      expect(find.byKey(const Key('error-metodo')), findsOneWidget);
    });
  });

  group('quitar', () {
    testWidgets('pide confirmación y, al aceptar, borra y queda "Sin guardar"', (tester) async {
      final m = await _montar(tester, estado: _guardado);
      m.api.responder('DELETE', '/metodos-pago/paypal', null);

      await tester.tap(find.byKey(const Key('quitar-paypal')));
      await tester.pumpAndSettle();
      expect(find.text('¿Quitar tu PayPal?'), findsOneWidget);
      expect(m.api.de('DELETE', '/metodos-pago/paypal'), isEmpty, reason: 'todavía no');

      await tester.tap(find.byKey(const Key('confirmar-quitar-paypal')));
      await tester.pumpAndSettle();

      expect(m.api.de('DELETE', '/metodos-pago/paypal'), hasLength(1));
      expect(find.byKey(const Key('paypal-no-guardado')), findsOneWidget);
      expect(find.byKey(const Key('quitar-paypal')), findsNothing);
    });

    testWidgets('si se arrepiente no se borra nada', (tester) async {
      final m = await _montar(tester, estado: _guardado);

      await tester.tap(find.byKey(const Key('quitar-paypal')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('cancelar-quitar-paypal')));
      await tester.pumpAndSettle();

      expect(m.api.de('DELETE', '/metodos-pago/paypal'), isEmpty);
      expect(find.byKey(const Key('paypal-guardado')), findsOneWidget);
    });
  });

  test('mensajeErrorMetodoPago traduce los códigos del servidor', () {
    ErrorApp con(int estado, String? codigo) =>
        ErrorApp(tipo: TipoErrorApp.desconocido, mensaje: 'x', estado: estado, codigo: codigo);

    expect(mensajeErrorMetodoPago(con(409, 'paypal_no_aprobado')), contains('No se aprobó'));
    expect(mensajeErrorMetodoPago(con(503, 'paypal_no_disponible')), contains('no responde'));
    expect(mensajeErrorMetodoPago(con(429, null)), contains('muchos intentos'));
    expect(
      mensajeErrorMetodoPago(const ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: 'x')),
      contains('Necesitas conexión'),
    );
  });
}
