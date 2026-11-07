import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/features/cliente_offline/data/metodo_pago_repository.dart';
import 'package:mobile/features/cliente_offline/data/pedidos_diferidos_api.dart';
import 'package:mobile/features/cliente_offline/models/metodo_pago.dart';
import 'package:mobile/features/cliente_offline/models/pedido_diferido_api.dart';
import 'package:mobile/features/cliente_offline/models/pedido_sin_conexion.dart';
import 'package:mobile/features/cliente_offline/presentation/dialogo_salida_pedidos.dart';
import 'package:mobile/features/cliente_offline/presentation/retorno_paypal.dart';
import 'package:mobile/features/cliente_offline/state/cliente_offline_providers.dart';
import 'package:mobile/features/notificaciones/models/notificacion_app.dart';
import 'package:mobile/features/notificaciones/models/ruta_notificacion.dart';

import '../../helpers/api_client_falso.dart';
import '../../helpers/cliente_offline_apoyo.dart';

void main() {
  group('PedidoDiferidoCrear (el cuerpo de POST /pedidos-diferidos)', () {
    test('lleva el contrato exacto: montos en texto, solo variante y cantidad, sin precios', () {
      const pedido = PedidoDiferidoCrear(
        operacionId: 'aaaaaaaa-0000-4000-8000-bbbbbbbbbbbb',
        sucursalId: 3,
        costoEnvioCentavos: 0,
        lineas: [(varianteId: 10, cantidad: 2), (varianteId: 11, cantidad: 1)],
        totalMaximoCentavos: 39805,
        fechaPedido: '2026-11-06T14:03:00.000Z',
      );

      expect(pedido.toJson(), {
        'operacion_id': 'aaaaaaaa-0000-4000-8000-bbbbbbbbbbbb',
        'sucursal_id': 3,
        'costo_envio': '0.00',
        'lineas': [
          {'variante_id': 10, 'cantidad': 2},
          {'variante_id': 11, 'cantidad': 1},
        ],
        'total_maximo': '398.05',
        'fecha_pedido': '2026-11-06T14:03:00.000Z',
      });
    });

    test('los centavos se escriben siempre con dos decimales', () {
      const base = PedidoDiferidoCrear(
        operacionId: 'x',
        sucursalId: 1,
        costoEnvioCentavos: 5,
        lineas: [],
        totalMaximoCentavos: 100,
        fechaPedido: 'f',
      );

      expect(base.toJson()['costo_envio'], '0.05');
      expect(base.toJson()['total_maximo'], '1.00');
    });
  });

  group('PedidoDiferidoRespuesta', () {
    test('un cobro trae venta, código y total', () {
      final r = PedidoDiferidoRespuesta.fromJson({
        'operacion_id': 'op',
        'estado': 'cobrado',
        'motivo': null,
        'mensaje': 'Cobramos tu pedido',
        'venta_id': 55,
        'codigo_venta': 'V-0055',
        'total': '398.00',
        'total_usd': '57.18',
        'duplicada': true,
      });

      expect(r.cobrado, isTrue);
      expect(r.ventaId, 55);
      expect(r.codigoVenta, 'V-0055');
      expect(r.totalCentavos, 39800);
      expect(r.totalUsd, '57.18');
      expect(r.duplicada, isTrue);
      expect(r.motivo, isNull);
    });

    test('un rechazo trae su motivo y su mensaje, sin venta', () {
      final r = PedidoDiferidoRespuesta.fromJson({
        'operacion_id': 'op',
        'estado': 'rechazado',
        'motivo': 'stock_insuficiente',
        'mensaje': 'Ya no hay esa talla.',
        'venta_id': null,
        'codigo_venta': null,
        'total': null,
        'total_usd': null,
        'duplicada': false,
      });

      expect(r.cobrado, isFalse);
      expect(r.motivo, 'stock_insuficiente');
      expect(r.mensaje, 'Ya no hay esa talla.');
      expect(r.ventaId, isNull);
      expect(r.totalCentavos, isNull);
    });

    test('un estado que no es cobrado ni rechazado NO es una decisión: lanza', () {
      expect(
        () => PedidoDiferidoRespuesta.fromJson({'operacion_id': 'op', 'estado': 'en_proceso'}),
        throwsFormatException,
      );
    });
  });

  group('PedidosDiferidosApiHttp', () {
    test('POST /pedidos-diferidos (ruta NO pública: la empresa sale del token)', () async {
      final api = ApiClientFalso()
        ..responder('POST', '/pedidos-diferidos', {
          'operacion_id': 'op',
          'estado': 'cobrado',
          'motivo': null,
          'mensaje': 'ok',
          'venta_id': 1,
          'codigo_venta': 'V-1',
          'total': '10.00',
          'total_usd': '1.44',
          'duplicada': false,
        });

      final r = await PedidosDiferidosApiHttp(api).enviar(
        const PedidoDiferidoCrear(
          operacionId: 'op',
          sucursalId: 3,
          costoEnvioCentavos: 0,
          lineas: [(varianteId: 10, cantidad: 1)],
          totalMaximoCentavos: 1000,
          fechaPedido: 'f',
        ),
      );

      expect(r.cobrado, isTrue);
      final llamada = api.de('POST', '/pedidos-diferidos').single;
      expect(llamada.publica, isFalse);
      expect((llamada.cuerpo! as Map)['operacion_id'], 'op');
    });
  });

  group('MetodoPagoRepository', () {
    test('GET estado: guardado con el correo enmascarado', () async {
      final api = ApiClientFalso()
        ..responder('GET', '/metodos-pago/paypal', {
          'guardado': true,
          'correo_paypal': 'j***@gmail.com',
          'guardado_en': '2026-11-05T15:00:00Z',
        });

      final estado = await MetodoPagoRepository(api).estado();

      expect(estado.guardado, isTrue);
      expect(estado.correoPaypal, 'j***@gmail.com');
      expect(estado.guardadoEn, isNotNull);
    });

    test('GET estado: sin guardar', () async {
      final api = ApiClientFalso()
        ..responder('GET', '/metodos-pago/paypal', {'guardado': false, 'correo_paypal': null, 'guardado_en': null});

      final estado = await MetodoPagoRepository(api).estado();

      expect(estado.guardado, isFalse);
      expect(estado.correoPaypal, isNull);
      expect(estado.guardadoEn, isNull);
    });

    test('iniciar manda canal "app" y devuelve la URL de aprobación y el token de preparación', () async {
      final api = ApiClientFalso()
        ..responder('POST', '/metodos-pago/paypal/iniciar', {
          'url_aprobacion': 'https://sandbox.paypal.com/aprobar?t=1',
          'token_preparacion': 'tok-1',
        });

      final r = await MetodoPagoRepository(api).iniciar();

      expect(r.urlAprobacion, 'https://sandbox.paypal.com/aprobar?t=1');
      expect(r.tokenPreparacion, 'tok-1');
      expect(api.de('POST', '/metodos-pago/paypal/iniciar').single.cuerpo, {'canal': 'app'});
    });

    test('confirmar manda el token de preparación', () async {
      final api = ApiClientFalso()
        ..responder('POST', '/metodos-pago/paypal/confirmar', {
          'guardado': true,
          'correo_paypal': 'a***@x.com',
          'guardado_en': '2026-11-06T10:00:00Z',
        });

      final r = await MetodoPagoRepository(api).confirmar('tok-1');

      expect(r.guardado, isTrue);
      expect(api.de('POST', '/metodos-pago/paypal/confirmar').single.cuerpo, {'token_preparacion': 'tok-1'});
    });

    test('quitar es un DELETE', () async {
      final api = ApiClientFalso()..responder('DELETE', '/metodos-pago/paypal', null);

      await MetodoPagoRepository(api).quitar();

      expect(api.de('DELETE', '/metodos-pago/paypal'), hasLength(1));
    });

    test('los errores del servidor llegan como ErrorApp (409 paypal_no_aprobado)', () async {
      final api = ApiClientFalso()
        ..responder(
          'POST',
          '/metodos-pago/paypal/confirmar',
          const ErrorApp(tipo: TipoErrorApp.conflicto, mensaje: 'x', estado: 409, codigo: 'paypal_no_aprobado'),
        );

      await expectLater(
        MetodoPagoRepository(api).confirmar('tok'),
        throwsA(isA<ErrorApp>().having((e) => e.codigo, 'codigo', 'paypal_no_aprobado')),
      );
    });
  });

  group('MetodoPagoRecordado (lo único que se recuerda del PayPal)', () {
    test('guarda solo el estado y el correo enmascarado, y vuelve igual', () {
      final recordado = MetodoPagoRecordado.desde(
        MetodoPagoPaypal(guardado: true, correoPaypal: 'j***@gmail.com', guardadoEn: DateTime.utc(2026, 11, 5, 15)),
        DateTime.utc(2026, 11, 6, 9),
      );

      final texto = recordado.aTexto();
      final leido = MetodoPagoRecordado.desdeTexto(texto)!;

      expect(leido.guardado, isTrue);
      expect(leido.correoPaypal, 'j***@gmail.com');
      expect(leido.guardadoEn, DateTime.utc(2026, 11, 5, 15));
      expect(leido.verificadoEn, DateTime.utc(2026, 11, 6, 9));
      // Nada de tokens ni de datos de tarjeta en lo guardado.
      expect(texto, isNot(contains('token')));
      expect(texto, isNot(contains('tarjeta')));
      expect(texto, isNot(contains('vault')));
    });

    test('sin PayPal guardado no recuerda correo ni fecha', () {
      final recordado = MetodoPagoRecordado.desde(
        MetodoPagoPaypal(guardado: false, correoPaypal: 'sobra@x.com', guardadoEn: DateTime.utc(2026, 1, 1)),
        DateTime.utc(2026, 11, 6),
      );

      expect(recordado.guardado, isFalse);
      expect(recordado.correoPaypal, isNull);
      expect(recordado.guardadoEn, isNull);
    });

    test('un valor dañado se descarta en vez de romper', () {
      expect(MetodoPagoRecordado.desdeTexto(null), isNull);
      expect(MetodoPagoRecordado.desdeTexto('no es json'), isNull);
      expect(MetodoPagoRecordado.desdeTexto('{"guardado": 1}'), isNull);
    });
  });

  group('PedidoSinConexion', () {
    test('ida y vuelta por la fila de la base', () {
      final original = pedidoDePrueba(n: 3, cantidad: 2, precio: 12550, intentos: 2);

      final leido = PedidoSinConexion.desdeFila(original.aFila());

      expect(leido.operacionId, original.operacionId);
      expect(leido.estado, EstadoPedidoLocal.pendiente);
      expect(leido.totalMaximoCentavos, 25100);
      expect(leido.lineas.single.productoNombre, 'Polera Nike');
      expect(leido.intentos, 2);
      expect(leido.creadoEn, original.creadoEn);
      expect(leido.cantidadPrendas, 2);
    });

    test('los estados que cuentan como "sin enviar" y los finales', () {
      expect(EstadoPedidoLocal.pendiente.sinEnviar, isTrue);
      expect(EstadoPedidoLocal.enviando.sinEnviar, isTrue);
      for (final e in [EstadoPedidoLocal.cobrado, EstadoPedidoLocal.rechazado, EstadoPedidoLocal.vencido]) {
        expect(e.sinEnviar, isFalse, reason: '$e');
        expect(e.esFinal, isTrue, reason: '$e');
      }
      expect(EstadoPedidoLocal.pendiente.esFinal, isFalse);
      expect(EstadoPedidoLocal.enviando.esFinal, isFalse);
    });

    test('etiquetas de la lista', () {
      expect(EstadoPedidoLocal.pendiente.etiqueta, 'Pendiente de envío');
      expect(EstadoPedidoLocal.cobrado.etiqueta, 'Cobrado');
      expect(EstadoPedidoLocal.rechazado.etiqueta, 'Rechazado');
      expect(EstadoPedidoLocal.vencido.etiqueta, 'Vencido');
    });
  });

  group('textoAvisoPedido', () {
    test('cobrado dice el código y el total en bolivianos', () {
      final cobrado = PedidoSinConexion.desdeFila({
        ...pedidoDePrueba(estado: EstadoPedidoLocal.cobrado).aFila(),
        'codigo_venta': 'V-0055',
        'total_centavos': 39800,
      });

      expect(textoAvisoPedido(cobrado), 'Cobramos tu pedido V-0055 por Bs 398.00.');
    });

    test('rechazado muestra el mensaje del servidor', () {
      final rechazado = PedidoSinConexion.desdeFila({
        ...pedidoDePrueba(estado: EstadoPedidoLocal.rechazado).aFila(),
        'mensaje': 'Ya no queda esa talla.',
      });

      expect(textoAvisoPedido(rechazado), 'Ya no queda esa talla.');
    });

    test('rechazado sin mensaje usa uno genérico', () {
      expect(textoAvisoPedido(pedidoDePrueba(estado: EstadoPedidoLocal.rechazado)), contains('No pudimos cobrar'));
    });
  });

  group('retorno de PayPal (la URL que el WebView intercepta)', () {
    const base = 'https://fashionstore.example.com/t/chaski/mi-cuenta/paypal-guardado';

    test('aprobado: lee el approval_token_id', () {
      final r = interpretarRetornoPaypal('$base?approval_token_id=5O190127TN364715T&approval_session_id=xyz');

      expect(r, isA<RetornoAprobado>());
      expect((r! as RetornoAprobado).token, '5O190127TN364715T');
    });

    test('cancelado: ?cancelado=1', () {
      expect(interpretarRetornoPaypal('$base?cancelado=1'), isA<RetornoCancelado>());
    });

    test('si trae cancelado gana sobre el token', () {
      expect(interpretarRetornoPaypal('$base?cancelado=1&approval_token_id=abc'), isA<RetornoCancelado>());
    });

    test('la URL de retorno sin token ni cancelado es "sin datos"', () {
      expect(interpretarRetornoPaypal(base), isA<RetornoSinDatos>());
      expect(interpretarRetornoPaypal('$base?approval_token_id='), isA<RetornoSinDatos>());
    });

    test('sirve con cualquier dominio y con localhost', () {
      expect(
        interpretarRetornoPaypal('http://localhost:4200/t/x/mi-cuenta/paypal-guardado?approval_token_id=t'),
        isA<RetornoAprobado>(),
      );
    });

    test('cualquier otra página (la de PayPal) no es un retorno', () {
      expect(interpretarRetornoPaypal('https://www.sandbox.paypal.com/agreements/approve?ba_token=BA-1'), isNull);
      expect(interpretarRetornoPaypal('https://fashionstore.example.com/t/chaski/mi-cuenta/metodo-pago'), isNull);
      expect(interpretarRetornoPaypal('no es una url'), isNull);
    });

    test('solo se abren direcciones http y https', () {
      expect(esUrlAbrible('https://sandbox.paypal.com/x'), isTrue);
      expect(esUrlAbrible('http://localhost:8000/x'), isTrue);
      expect(esUrlAbrible('javascript:alert(1)'), isFalse);
      expect(esUrlAbrible('file:///etc/passwd'), isFalse);
      expect(esUrlAbrible('sandbox.paypal.com'), isFalse);
      expect(esUrlAbrible(''), isFalse);
    });
  });

  group('ErrorApp.reintentarDespues (Retry-After)', () {
    DioException con(Map<String, List<String>> cabeceras, int estado) {
      final opciones = RequestOptions(path: '/pedidos-diferidos');
      return DioException(
        requestOptions: opciones,
        type: DioExceptionType.badResponse,
        response: Response(requestOptions: opciones, statusCode: estado, headers: Headers.fromMap(cabeceras)),
      );
    }

    test('lee los segundos de un 429', () {
      final e = ErrorApp.desde(
        con({
          'retry-after': ['45'],
        }, 429),
      );

      expect(e.estado, 429);
      expect(e.reintentarDespues, const Duration(seconds: 45));
    });

    test('sin cabecera, o con una fecha, queda en null', () {
      expect(ErrorApp.desde(con({}, 429)).reintentarDespues, isNull);
      expect(
        ErrorApp.desde(
          con({
            'retry-after': ['Wed, 21 Oct 2026 07:28:00 GMT'],
          }, 429),
        ).reintentarDespues,
        isNull,
      );
    });

    test('un valor absurdo se acota a una hora', () {
      final e = ErrorApp.desde(
        con({
          'retry-after': ['999999'],
        }, 429),
      );

      expect(e.reintentarDespues, const Duration(hours: 1));
    });
  });

  group('textos del aviso de salida', () {
    test('singular y plural', () {
      expect(tituloPedidosSinEnviar(1), 'Tienes 1 pedido sin enviar');
      expect(tituloPedidosSinEnviar(2), 'Tienes 2 pedidos sin enviar');
      expect(tituloPedidosSinEnviar(11), 'Tienes 11 pedidos sin enviar');
    });
  });

  group('notificaciones de pedido diferido', () {
    test('una notificación pedido_diferido con venta lleva a la compra', () {
      final n = NotificacionApp(
        id: 1,
        titulo: 'Cobramos tu pedido',
        mensaje: null,
        tipo: 'pedido_diferido',
        referenciaId: 55,
        leida: false,
        creadoEn: DateTime.utc(2026, 11, 6),
      );

      expect(rutaDeNotificacion(n), '/compras/55');
    });

    test('un rechazo (sin venta) no abre nada', () {
      final n = NotificacionApp(
        id: 2,
        titulo: 'No pudimos cobrar tu pedido',
        mensaje: 'Sin stock',
        tipo: 'pedido_diferido',
        referenciaId: null,
        leida: false,
        creadoEn: DateTime.utc(2026, 11, 6),
      );

      expect(rutaDeNotificacion(n), isNull);
    });
  });
}
