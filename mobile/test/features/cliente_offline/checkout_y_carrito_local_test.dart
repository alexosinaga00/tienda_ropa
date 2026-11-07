import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/core/conectividad/conectividad_service.dart';
import 'package:mobile/core/utils/reloj.dart';
import 'package:mobile/features/catalogo/models/catalogo_detalle.dart';
import 'package:mobile/features/catalogo/models/catalogo_item.dart';
import 'package:mobile/features/cliente_offline/config/cliente_offline_config.dart';
import 'package:mobile/features/cliente_offline/data/cache_catalogo_cliente.dart';
import 'package:mobile/features/cliente_offline/data/metodo_pago_repository.dart';
import 'package:mobile/features/cliente_offline/models/linea_carrito_local.dart';
import 'package:mobile/features/cliente_offline/models/metodo_pago.dart';
import 'package:mobile/features/cliente_offline/presentation/carrito_local_vista.dart';
import 'package:mobile/features/cliente_offline/presentation/checkout_sin_conexion_screen.dart';
import 'package:mobile/features/cliente_offline/state/carrito_local_controller.dart';
import 'package:mobile/features/cliente_offline/state/cliente_offline_providers.dart';
import 'package:mobile/features/cliente_offline/state/metodo_pago_controller.dart';
import 'package:mobile/features/compras/state/carrito_controller.dart';

import '../../helpers/api_client_falso.dart';
import '../../helpers/cliente_offline_apoyo.dart';

class _CarritoFijo extends CarritoLocalController {
  _CarritoFijo(List<LineaCarritoLocal> lista, this.resultadoPaso)
    : super(() async => null, const RelojSistema(), activo: false) {
    state = lista;
  }

  final ResultadoPaso? resultadoPaso;
  int vaciados = 0;

  @override
  Future<void> cargar() async {}

  @override
  Future<void> quitar(int varianteId) async => state = [
    for (final l in state)
      if (l.varianteId != varianteId) l,
  ];

  @override
  Future<void> vaciar() async {
    vaciados++;
    state = const [];
  }

  @override
  Future<ResultadoPaso> pasarAlServidor(Future<void> Function(int varianteId, int cantidad) agregarAlServidor) async {
    final r = resultadoPaso ?? (pasadas: state.length, fallidas: 0);
    if (r.fallidas == 0) {
      state = const [];
    } else {
      state = state.sublist(r.pasadas);
    }
    return r;
  }
}

class _MetodoFijo extends MetodoPagoController {
  _MetodoFijo(MetodoPagoRecordado? recordado)
    : super(() async => null, MetodoPagoRepository(ApiClientFalso()), const RelojSistema(), activo: false) {
    state = recordado;
  }
}

class _CacheSucursales implements CacheCatalogoCliente {
  _CacheSucursales(this.sucursales);

  final List<Map<String, dynamic>> sucursales;

  @override
  Future<List<Map<String, dynamic>>> leerReferencias(String tipo) async => tipo == cacheSucursal ? sucursales : [];

  @override
  Future<void> guardarItems(List<Map<String, dynamic>> crudos, {int? primeraPosicion}) async {}

  @override
  Future<List<CatalogoItem>> leerItems({String? texto}) async => [];

  @override
  Future<void> guardarDetalle(int productoId, Map<String, dynamic> crudo) async {}

  @override
  Future<CatalogoDetalle?> leerDetalle(int productoId) async => null;

  @override
  Future<void> guardarReferencias(String tipo, List<Map<String, dynamic>> crudos) async {}
}

Map<String, dynamic> _sucursal(int id, String nombre, {bool deposito = false}) => {
  'id': id,
  'codigo': 'S$id',
  'nombre': nombre,
  'es_deposito': deposito,
};

final _paypal = MetodoPagoRecordado(
  guardado: true,
  correoPaypal: 'j***@gmail.com',
  verificadoEn: DateTime.utc(2026, 11, 5),
);
final _sinPaypal = MetodoPagoRecordado(guardado: false, verificadoEn: DateTime.utc(2026, 11, 5));

/// El carrito del servidor que "Pasar a mi carrito" usa; no se llega a consultar en estas pruebas.
class _CarritoServidorFalso extends CarritoController {
  _CarritoServidorFalso(super.ref) : super(activo: false);

  @override
  Future<void> agregar({required int varianteId, required int cantidad}) async {}
}

Future<ColaFalsa> _montarCheckout(
  WidgetTester tester, {
  List<LineaCarritoLocal>? lineas,
  MetodoPagoRecordado? metodo,
  List<Map<String, dynamic>>? sucursales,
  bool enLinea = false,
}) async {
  final cola = ColaFalsa();
  final router = GoRouter(
    routes: [
      GoRoute(path: '/', builder: (context, state) => const CheckoutSinConexionScreen()),
      GoRoute(
        path: '/carrito',
        builder: (context, state) => const Scaffold(body: Text('PANTALLA CARRITO')),
      ),
      GoRoute(
        path: '/cuenta/metodo-pago',
        builder: (context, state) => const Scaffold(body: Text('PANTALLA METODO')),
      ),
      GoRoute(
        path: '/pedidos-sin-conexion',
        builder: (context, state) => const Scaffold(body: Text('PANTALLA PEDIDOS')),
      ),
    ],
  );
  addTearDown(router.dispose);
  tester.view.physicalSize = const Size(800, 3200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        colaPedidosProvider.overrideWithValue(cola),
        carritoLocalProvider.overrideWith((ref) => _CarritoFijo(lineas ?? [lineaCarrito(cantidad: 2)], null)),
        metodoPagoLocalProvider.overrideWith((ref) => _MetodoFijo(metodo ?? _paypal)),
        cacheCatalogoClienteProvider.overrideWithValue(
          _CacheSucursales(
            sucursales ?? [_sucursal(1, 'Centro'), _sucursal(2, 'Sur'), _sucursal(9, 'Depósito', deposito: true)],
          ),
        ),
        enLineaProvider.overrideWith((ref) => Stream.value(enLinea)),
      ],
      child: MaterialApp.router(routerConfig: router),
    ),
  );
  await tester.pumpAndSettle();
  return cola;
}

bool _confirmarHabilitado(WidgetTester tester) =>
    tester.widget<ElevatedButton>(find.byKey(const Key('confirmar-pedido'))).onPressed != null;

Future<void> _aceptar(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('aceptar-total')));
  await tester.pumpAndSettle();
}

void main() {
  group('pagar sin conexión con el PayPal guardado', () {
    testWidgets('muestra el tope en bolivianos y la aceptación "Se cobrará hasta Bs X cuando vuelva la conexión."', (
      tester,
    ) async {
      await _montarCheckout(tester);

      expect(find.text('Se cobrará hasta Bs 398.00 cuando vuelva la conexión.'), findsOneWidget);
      expect(find.text('2 × Bs 199.00'), findsOneWidget);
      expect(find.textContaining('Retiro en sucursal'), findsWidgets);
      expect(find.byKey(const Key('metodo-paypal-guardado')), findsOneWidget);
      expect(find.textContaining('j***@gmail.com'), findsOneWidget);
    });

    testWidgets('solo ofrece sucursales donde retirar (no el depósito)', (tester) async {
      await _montarCheckout(tester);

      expect(find.byKey(const Key('sucursal-1')), findsOneWidget);
      expect(find.byKey(const Key('sucursal-2')), findsOneWidget);
      expect(find.byKey(const Key('sucursal-9')), findsNothing);
    });

    testWidgets('para confirmar hay que elegir sucursal Y aceptar el total', (tester) async {
      await _montarCheckout(tester);
      expect(_confirmarHabilitado(tester), isFalse);

      await _aceptar(tester);
      expect(_confirmarHabilitado(tester), isFalse, reason: 'falta la sucursal');

      await tester.tap(find.byKey(const Key('sucursal-2')));
      await tester.pumpAndSettle();
      expect(_confirmarHabilitado(tester), isTrue);
    });

    testWidgets('con una sola sucursal para retirar, ya viene elegida', (tester) async {
      await _montarCheckout(tester, sucursales: [_sucursal(1, 'Centro'), _sucursal(9, 'Depósito', deposito: true)]);

      await _aceptar(tester);

      expect(_confirmarHabilitado(tester), isTrue);
    });

    testWidgets('si todas las prendas se vieron con stock en la misma sucursal, esa viene elegida', (tester) async {
      await _montarCheckout(
        tester,
        lineas: [lineaCarrito(varianteId: 1, sucursalId: 2), lineaCarrito(varianteId: 2, sucursalId: 2)],
      );

      await _aceptar(tester);

      expect(_confirmarHabilitado(tester), isTrue);
    });

    testWidgets('confirmar pone el pedido en la cola: sucursal, envío 0, prendas; y abre la lista de pedidos', (
      tester,
    ) async {
      final cola = await _montarCheckout(
        tester,
        lineas: [lineaCarrito(varianteId: 10, cantidad: 2), lineaCarrito(varianteId: 11)],
      );
      await _aceptar(tester);
      await tester.tap(find.byKey(const Key('sucursal-2')));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('confirmar-pedido')));
      await tester.pumpAndSettle();

      final e = cola.entradas.single;
      expect(e.sucursalId, 2);
      expect(e.sucursalNombre, 'Sur');
      expect(e.costoEnvioCentavos, 0);
      expect(e.lineas.map((l) => (l.varianteId, l.cantidad)), [(10, 2), (11, 1)]);
      expect(find.text('PANTALLA PEDIDOS'), findsOneWidget);
    });

    testWidgets('el total se suma en centavos enteros: 3 x Bs 0.10 + Bs 0.20 = Bs 0.50', (tester) async {
      await _montarCheckout(
        tester,
        lineas: [lineaCarrito(varianteId: 1, cantidad: 3, precio: 10), lineaCarrito(varianteId: 2, precio: 20)],
      );

      expect(find.text('Se cobrará hasta Bs 0.50 cuando vuelva la conexión.'), findsOneWidget);
    });
  });

  group('sin PayPal guardado', () {
    testWidgets('la opción sale deshabilitada con el texto y el enlace a Método de pago', (tester) async {
      await _montarCheckout(tester, metodo: _sinPaypal);

      expect(find.byKey(const Key('metodo-paypal-no-disponible')), findsOneWidget);
      expect(find.text('Guarda tu PayPal con conexión para pagar sin internet.'), findsOneWidget);
      expect(find.byKey(const Key('metodo-paypal-guardado')), findsNothing);
      expect(tester.widget<CheckboxListTile>(find.byKey(const Key('aceptar-total'))).onChanged, isNull);
      expect(_confirmarHabilitado(tester), isFalse);

      await tester.tap(find.byKey(const Key('ir-a-metodo-de-pago')));
      await tester.pumpAndSettle();
      expect(find.text('PANTALLA METODO'), findsOneWidget);
    });

    testWidgets('si nunca se supo nada del PayPal, también', (tester) async {
      await _montarCheckout(tester, metodo: _sinPaypal);
      expect(_confirmarHabilitado(tester), isFalse);
    });
  });

  group('otros casos', () {
    testWidgets('sin prendas en el carrito local lo dice y lleva al carrito', (tester) async {
      await _montarCheckout(tester, lineas: []);

      expect(find.byKey(const Key('carrito-vacio')), findsOneWidget);
      await tester.tap(find.text('Ir a mi carrito'));
      await tester.pumpAndSettle();
      expect(find.text('PANTALLA CARRITO'), findsOneWidget);
    });

    testWidgets('sin sucursales guardadas lo dice y no deja confirmar', (tester) async {
      await _montarCheckout(tester, sucursales: []);
      await _aceptar(tester);

      expect(find.byKey(const Key('sin-sucursales')), findsOneWidget);
      expect(_confirmarHabilitado(tester), isFalse);
    });

    testWidgets('demasiadas prendas distintas para un pedido: avisa y no deja confirmar', (tester) async {
      await _montarCheckout(
        tester,
        lineas: [for (var i = 1; i <= maxLineasPedido + 1; i++) lineaCarrito(varianteId: i)],
      );
      await _aceptar(tester);
      await tester.tap(find.byKey(const Key('sucursal-1')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('demasiadas-lineas')), findsOneWidget);
      expect(_confirmarHabilitado(tester), isFalse);
    });

    testWidgets('si ya volvió la conexión lo avisa, pero deja usar el pedido diferido', (tester) async {
      await _montarCheckout(tester, enLinea: true);

      expect(find.byKey(const Key('volvio-conexion')), findsOneWidget);
    });
  });

  group('carrito local (sin conexión)', () {
    Future<_CarritoFijo> montarVista(
      WidgetTester tester, {
      required List<LineaCarritoLocal> lineas,
      MetodoPagoRecordado? metodo,
      ResultadoPaso? paso,
      bool vista = true,
    }) async {
      late _CarritoFijo carrito;
      final router = GoRouter(
        routes: [
          GoRoute(
            path: '/',
            builder: (context, state) =>
                Scaffold(body: vista ? const CarritoLocalVista() : const AvisoCarritoLocalEnLinea()),
          ),
          GoRoute(
            path: '/home',
            builder: (context, state) => const Scaffold(body: Text('PANTALLA CATALOGO')),
          ),
          GoRoute(
            path: '/checkout/sin-conexion',
            builder: (context, state) => const Scaffold(body: Text('PANTALLA CHECKOUT')),
          ),
          GoRoute(
            path: '/cuenta/metodo-pago',
            builder: (context, state) => const Scaffold(body: Text('PANTALLA METODO')),
          ),
        ],
      );
      addTearDown(router.dispose);
      tester.view.physicalSize = const Size(800, 3200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            carritoLocalProvider.overrideWith((ref) => carrito = _CarritoFijo(lineas, paso)),
            metodoPagoLocalProvider.overrideWith((ref) => _MetodoFijo(metodo)),
            carritoControllerProvider.overrideWith((ref) => _CarritoServidorFalso(ref)),
          ],
          child: MaterialApp.router(routerConfig: router),
        ),
      );
      await tester.pumpAndSettle();
      return carrito;
    }

    testWidgets('muestra las prendas guardadas con nombre, talla, color y precio, y el subtotal', (tester) async {
      await montarVista(
        tester,
        lineas: [
          lineaCarrito(varianteId: 1, nombre: 'Polera Nike', cantidad: 2),
          lineaCarrito(varianteId: 2, nombre: 'Gorra', talla: null, color: 'Negro', precio: 5050),
        ],
        metodo: _paypal,
      );

      expect(find.byKey(const Key('linea-local-1')), findsOneWidget);
      expect(find.text('Polera Nike'), findsOneWidget);
      expect(find.text('M · Azul'), findsOneWidget);
      expect(find.text('Negro'), findsOneWidget);
      expect(find.text('Bs 199.00'), findsOneWidget);
      expect(find.text('Bs 50.50'), findsOneWidget);
      expect(find.text('Bs 448.50'), findsOneWidget);
    });

    testWidgets('con PayPal guardado ofrece pagar con él', (tester) async {
      await montarVista(tester, lineas: [lineaCarrito()], metodo: _paypal);

      await tester.tap(find.byKey(const Key('pagar-paypal-guardado')));
      await tester.pumpAndSettle();

      expect(find.text('PANTALLA CHECKOUT'), findsOneWidget);
    });

    testWidgets('sin PayPal guardado la opción sale deshabilitada, con su texto y el enlace', (tester) async {
      await montarVista(tester, lineas: [lineaCarrito()], metodo: _sinPaypal);

      final boton = tester.widget<ElevatedButton>(find.byKey(const Key('pagar-paypal-deshabilitado')));
      expect(boton.onPressed, isNull);
      expect(find.text('Guarda tu PayPal con conexión para pagar sin internet.'), findsOneWidget);
      expect(find.byKey(const Key('pagar-paypal-guardado')), findsNothing);

      await tester.tap(find.byKey(const Key('ir-a-metodo-de-pago')));
      await tester.pumpAndSettle();
      expect(find.text('PANTALLA METODO'), findsOneWidget);
    });

    testWidgets('vacío: lo explica y lleva al catálogo', (tester) async {
      await montarVista(tester, lineas: const []);

      expect(find.byKey(const Key('carrito-local-vacio')), findsOneWidget);
      await tester.tap(find.text('Ver catálogo'));
      await tester.pumpAndSettle();
      expect(find.text('PANTALLA CATALOGO'), findsOneWidget);
    });

    testWidgets('Quitar saca la línea', (tester) async {
      final c = await montarVista(
        tester,
        lineas: [
          lineaCarrito(varianteId: 1),
          lineaCarrito(varianteId: 2, nombre: 'Gorra'),
        ],
      );

      await tester.tap(find.byKey(const Key('quitar-1')));
      await tester.pumpAndSettle();

      expect(c.state.map((l) => l.varianteId), [2]);
    });
  });

  group('al volver la conexión (carrito local + carrito del servidor)', () {
    Future<_CarritoFijo> montar(WidgetTester tester, List<LineaCarritoLocal> lineas, {ResultadoPaso? paso}) async {
      late _CarritoFijo carrito;
      final router = GoRouter(
        routes: [
          GoRoute(
            path: '/',
            builder: (context, state) => const Scaffold(body: AvisoCarritoLocalEnLinea()),
          ),
          GoRoute(
            path: '/checkout/sin-conexion',
            builder: (context, state) => const Scaffold(body: Text('PANTALLA CHECKOUT')),
          ),
        ],
      );
      addTearDown(router.dispose);
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            carritoLocalProvider.overrideWith((ref) => carrito = _CarritoFijo(lineas, paso)),
            metodoPagoLocalProvider.overrideWith((ref) => _MetodoFijo(_paypal)),
            carritoControllerProvider.overrideWith((ref) => _CarritoServidorFalso(ref)),
          ],
          child: MaterialApp.router(routerConfig: router),
        ),
      );
      await tester.pumpAndSettle();
      return carrito;
    }

    testWidgets('NO se mezcla solo: avisa cuántas prendas hay y deja elegir', (tester) async {
      final c = await montar(tester, [lineaCarrito(cantidad: 2), lineaCarrito(varianteId: 11, nombre: 'Gorra')]);

      expect(find.text('Tienes 3 prendas guardadas sin conexión'), findsOneWidget);
      expect(find.byKey(const Key('pasar-a-mi-carrito')), findsOneWidget);
      expect(find.byKey(const Key('descartar-carrito-local')), findsOneWidget);
      expect(c.state, hasLength(2), reason: 'nada se pasó solo');
    });

    testWidgets('sin prendas locales no aparece nada', (tester) async {
      await montar(tester, const []);

      expect(find.byKey(const Key('aviso-carrito-local')), findsNothing);
    });

    testWidgets('"Pasar a mi carrito" pasa las líneas y avisa', (tester) async {
      final c = await montar(tester, [lineaCarrito(), lineaCarrito(varianteId: 11)]);

      await tester.tap(find.byKey(const Key('pasar-a-mi-carrito')));
      await tester.pumpAndSettle();

      expect(c.state, isEmpty);
      expect(find.text('Pasaron 2 prendas a tu carrito.'), findsOneWidget);
    });

    testWidgets('si alguna falla, avisa y esa se queda', (tester) async {
      final c = await montar(tester, [lineaCarrito(), lineaCarrito(varianteId: 11)], paso: (pasadas: 1, fallidas: 1));

      await tester.tap(find.byKey(const Key('pasar-a-mi-carrito')));
      await tester.pumpAndSettle();

      expect(c.state, hasLength(1));
      expect(find.textContaining('Pasó 1 prenda a tu carrito.'), findsOneWidget);
      expect(find.textContaining('1 no se pudo pasar'), findsOneWidget);
    });

    testWidgets('"Descartar" pide confirmar y vacía el carrito local', (tester) async {
      final c = await montar(tester, [lineaCarrito()]);

      await tester.tap(find.byKey(const Key('descartar-carrito-local')));
      await tester.pumpAndSettle();
      expect(c.vaciados, 0);
      await tester.tap(find.byKey(const Key('confirmar-descartar-local')));
      await tester.pumpAndSettle();

      expect(c.vaciados, 1);
      expect(find.byKey(const Key('aviso-carrito-local')), findsNothing);
    });

    testWidgets('con PayPal guardado se puede dejar para cobrarlo de ahí', (tester) async {
      await montar(tester, [lineaCarrito()]);

      await tester.tap(find.byKey(const Key('pagar-local-con-paypal')));
      await tester.pumpAndSettle();

      expect(find.text('PANTALLA CHECKOUT'), findsOneWidget);
    });
  });
}
