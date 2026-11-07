import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/core/conectividad/conectividad_service.dart';
import 'package:mobile/features/cliente_offline/models/pedido_sin_conexion.dart';
import 'package:mobile/features/cliente_offline/presentation/pedidos_sin_conexion_screen.dart';
import 'package:mobile/features/cliente_offline/state/cliente_offline_providers.dart';
import 'package:mobile/features/cliente_offline/state/cola_pedidos.dart';
import 'package:mobile/features/notificaciones/data/notificaciones_repository.dart';
import 'package:mobile/features/notificaciones/models/notificacion_app.dart';
import 'package:mobile/features/notificaciones/state/notificaciones_controller.dart';

import '../../helpers/cliente_offline_apoyo.dart';

class _NotificacionesFalsas extends NotificacionesController {
  _NotificacionesFalsas(List<NotificacionApp> lista) : super(NotificacionesRepository(Dio()), activo: false) {
    state = AsyncValue.data(lista);
  }

  final leidas = <int>[];

  @override
  Future<void> marcarLeida(int id) async => leidas.add(id);
}

NotificacionApp _aviso(int id, String tipo, {bool leida = false, int? venta}) => NotificacionApp(
  id: id,
  titulo: 'Aviso $id',
  mensaje: 'Detalle $id',
  tipo: tipo,
  referenciaId: venta,
  leida: leida,
  creadoEn: DateTime.now(),
);

PedidoSinConexion _con(PedidoSinConexion base, Map<String, Object?> cambios) =>
    PedidoSinConexion.desdeFila({...base.aFila(), ...cambios});

class _Mundo {
  _Mundo(this.cola, this.notificaciones, this.router);

  final ColaFalsa cola;
  final _NotificacionesFalsas notificaciones;
  final GoRouter router;
}

Future<_Mundo> _montar(
  WidgetTester tester, {
  List<PedidoSinConexion> pedidos = const [],
  List<NotificacionApp> avisos = const [],
  EstadoCola estado = const EstadoCola(),
  bool enLinea = true,
}) async {
  final cola = ColaFalsa()..lista = pedidos;
  final notificaciones = _NotificacionesFalsas(avisos);
  final router = GoRouter(
    routes: [
      GoRoute(path: '/', builder: (context, state) => const PedidosSinConexionScreen()),
      GoRoute(
        path: '/compras/:id',
        builder: (context, state) => Scaffold(body: Text('COMPRA ${state.pathParameters['id']}')),
      ),
    ],
  );
  addTearDown(router.dispose);
  tester.view.physicalSize = const Size(800, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        colaPedidosProvider.overrideWithValue(cola),
        estadoColaProvider.overrideWith((ref) => Stream.value(estado)),
        enLineaProvider.overrideWith((ref) => Stream.value(enLinea)),
        notificacionesProvider.overrideWith((ref) => notificaciones),
      ],
      child: MaterialApp.router(routerConfig: router),
    ),
  );
  await tester.pumpAndSettle();
  return _Mundo(cola, notificaciones, router);
}

void main() {
  final cobrado = _con(pedidoDePrueba(n: 1, estado: EstadoPedidoLocal.cobrado), {
    'codigo_venta': 'V-0055',
    'venta_id': 55,
    'total_centavos': 39800,
    'mensaje': 'Cobramos tu pedido.',
  });
  final rechazado = _con(pedidoDePrueba(n: 2, estado: EstadoPedidoLocal.rechazado), {
    'motivo': 'stock_insuficiente',
    'mensaje': 'Ya no queda esa talla.',
  });
  final vencido = _con(pedidoDePrueba(n: 3, estado: EstadoPedidoLocal.vencido), {
    'motivo': 'pedido_vencido',
    'mensaje': 'Venció: pasaron más de 7 días sin conexión',
  });
  final pendiente = pedidoDePrueba(n: 4);

  testWidgets('sin pedidos lo explica', (tester) async {
    await _montar(tester);

    expect(find.byKey(const Key('sin-pedidos')), findsOneWidget);
    expect(find.text('No tienes pedidos hechos sin conexión.'), findsOneWidget);
    expect(find.byKey(const Key('enviar-ahora')), findsNothing);
  });

  testWidgets('lista cada pedido con su estado: Pendiente de envío, Cobrado, Rechazado y Vencido', (tester) async {
    await _montar(tester, pedidos: [pendiente, cobrado, rechazado, vencido]);

    expect(find.text('Pendiente de envío'), findsOneWidget);
    expect(find.text('Cobrado'), findsOneWidget);
    expect(find.text('Rechazado'), findsOneWidget);
    expect(find.text('Vencido'), findsOneWidget);
  });

  testWidgets('un pendiente muestra el tope aceptado; un cobrado, el total cobrado y su código', (tester) async {
    await _montar(tester, pedidos: [pendiente, cobrado]);

    expect(find.text('Hasta Bs 398.00'), findsOneWidget);
    expect(find.text('V-0055'), findsOneWidget);
    expect(find.text('Bs 398.00'), findsOneWidget);
    expect(find.textContaining('2 × Polera Nike · M · Azul'), findsNWidgets(2));
    expect(find.textContaining('Retiro en Centro'), findsNWidgets(2));
  });

  testWidgets('un rechazado muestra el mensaje del servidor', (tester) async {
    await _montar(tester, pedidos: [rechazado]);

    expect(find.byKey(const Key('mensaje-rechazo')), findsOneWidget);
    expect(find.text('Ya no queda esa talla.'), findsOneWidget);
  });

  testWidgets('un vencido dice que venció, que no se cobró nada y que se puede descartar', (tester) async {
    await _montar(tester, pedidos: [vencido]);

    expect(
      find.text('Venció: pasaron más de 7 días sin conexión. No se cobró nada: puedes descartarlo.'),
      findsOneWidget,
    );
    expect(find.byKey(const Key('descartar-pedido')), findsOneWidget);
  });

  testWidgets('un cobrado enlaza a la compra', (tester) async {
    await _montar(tester, pedidos: [cobrado]);

    await tester.tap(find.byKey(const Key('ver-compra')));
    await tester.pumpAndSettle();

    expect(find.text('COMPRA 55'), findsOneWidget);
  });

  testWidgets('"Descartar" solo está en los pendientes y vencidos, y pide confirmar', (tester) async {
    final m = await _montar(tester, pedidos: [pendiente, cobrado, rechazado, vencido]);

    expect(find.byKey(const Key('descartar-pedido')), findsNWidgets(2));

    await tester.tap(find.byKey(const Key('descartar-pedido')).first);
    await tester.pumpAndSettle();
    expect(find.text('¿Descartar este pedido?'), findsOneWidget);
    expect(m.cola.descartados, isEmpty);

    await tester.tap(find.byKey(const Key('descartar-si')));
    await tester.pumpAndSettle();
    expect(m.cola.descartados, hasLength(1));
  });

  testWidgets('si se arrepiente al descartar no pasa nada', (tester) async {
    final m = await _montar(tester, pedidos: [pendiente]);

    await tester.tap(find.byKey(const Key('descartar-pedido')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('descartar-no')));
    await tester.pumpAndSettle();

    expect(m.cola.descartados, isEmpty);
  });

  testWidgets('"Enviar ahora" aparece con pedidos sin enviar y manda la cola', (tester) async {
    final m = await _montar(tester, pedidos: [pendiente]);

    await tester.tap(find.byKey(const Key('enviar-ahora')));
    await tester.pump();

    expect(m.cola.enviosManuales, 1);
  });

  testWidgets('"Enviar ahora" no aparece si no hay nada por enviar', (tester) async {
    await _montar(tester, pedidos: [cobrado, rechazado, vencido]);

    expect(find.byKey(const Key('enviar-ahora')), findsNothing);
  });

  testWidgets('al abrirla marca los resultados como vistos', (tester) async {
    final m = await _montar(tester, pedidos: [cobrado]);

    expect(m.cola.vistos, 1);
  });

  group('avisos del servidor (tipo pedido_diferido)', () {
    testWidgets('muestra solo los de pedidos y deja marcar como leído', (tester) async {
      final m = await _montar(
        tester,
        avisos: [
          _aviso(1, 'pedido_diferido', venta: 55),
          _aviso(2, 'envio', venta: 9),
          _aviso(3, 'pedido_diferido', leida: true),
        ],
      );

      expect(find.byKey(const Key('aviso-1')), findsOneWidget);
      expect(find.byKey(const Key('aviso-2')), findsNothing);
      expect(find.byKey(const Key('aviso-3')), findsOneWidget);
      expect(find.byKey(const Key('marcar-leida-3')), findsNothing, reason: 'ya está leído');

      await tester.tap(find.byKey(const Key('marcar-leida-1')));
      await tester.pump();
      expect(m.notificaciones.leidas, [1]);
    });

    testWidgets('un aviso de un cobro lleva a la compra', (tester) async {
      await _montar(tester, avisos: [_aviso(1, 'pedido_diferido', venta: 55)]);

      await tester.tap(find.byKey(const Key('aviso-1')));
      await tester.pumpAndSettle();

      expect(find.text('COMPRA 55'), findsOneWidget);
    });

    testWidgets('sin avisos no hay sección', (tester) async {
      await _montar(tester, pedidos: [pendiente]);

      expect(find.text('Avisos'), findsNothing);
    });
  });

  group('lo que dice la cola', () {
    testWidgets('sin conexión', (tester) async {
      await _montar(
        tester,
        pedidos: [pendiente],
        estado: const EstadoCola(fase: FaseCola.sinConexion),
        enLinea: false,
      );

      expect(find.byKey(const Key('aviso-cola-sinConexion')), findsOneWidget);
      expect(find.textContaining('se cobran de tu PayPal cuando vuelva la conexión'), findsOneWidget);
      expect(find.byKey(const Key('aviso-sin-conexion')), findsOneWidget);
    });

    testWidgets('esperando un reintento: botón "Reintentar ahora"', (tester) async {
      final m = await _montar(
        tester,
        pedidos: [pendiente],
        estado: const EstadoCola(fase: FaseCola.esperandoReintento),
      );

      expect(find.text('Reintentar ahora'), findsOneWidget);
      await tester.tap(find.byKey(const Key('reintentar-ahora')));
      await tester.pump();
      expect(m.cola.enviosManuales, 1);
    });

    testWidgets('detenida por fallos: muestra el motivo y "Reintentar"', (tester) async {
      final m = await _montar(
        tester,
        pedidos: [pendiente],
        estado: const EstadoCola(fase: FaseCola.detenidaPorFallos, motivoPausa: 'No se pudo enviar tu pedido.'),
      );

      expect(find.text('No se pudo enviar tu pedido.'), findsOneWidget);
      await tester.tap(find.byKey(const Key('reintentar-ahora')));
      await tester.pump();
      expect(m.cola.enviosManuales, 1);
    });

    testWidgets('sesión vencida: lo dice y no ofrece reintentar (hay que volver a entrar)', (tester) async {
      await _montar(
        tester,
        pedidos: [pendiente],
        estado: const EstadoCola(fase: FaseCola.pausadaSesion, motivoPausa: 'Inicia sesión para enviar tu pedido.'),
      );

      expect(find.text('Inicia sesión para enviar tu pedido.'), findsOneWidget);
      expect(find.byKey(const Key('reintentar-ahora')), findsNothing);
    });

    testWidgets('en reposo no muestra ningún aviso de la cola', (tester) async {
      await _montar(tester, pedidos: [pendiente]);

      for (final fase in FaseCola.values) {
        expect(find.byKey(Key('aviso-cola-${fase.name}')), findsNothing);
      }
    });
  });
}
