import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/core/avisos/avisos_mostrados.dart';
import 'package:mobile/core/conectividad/conectividad_service.dart';
import 'package:mobile/core/push/dispositivos_push_repository.dart';
import 'package:mobile/core/push/registro_push.dart';
import 'package:mobile/core/push/servicio_push.dart';
import 'package:mobile/core/router/app_router.dart';
import 'package:mobile/core/sync/disparador_sincronizacion.dart' show mensajeroGlobal;
import 'package:mobile/features/auth/models/usuario.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/auth/state/auth_state.dart';
import 'package:mobile/features/catalogo/models/referencia.dart';
import 'package:mobile/features/catalogo/state/catalogo_providers.dart';
import 'package:mobile/features/cliente_offline/data/metodo_pago_repository.dart';
import 'package:mobile/features/cliente_offline/models/pedido_sin_conexion.dart';
import 'package:mobile/features/cliente_offline/presentation/disparador_cola_pedidos.dart';
import 'package:mobile/features/cliente_offline/state/cliente_offline_providers.dart';
import 'package:mobile/features/cliente_offline/state/metodo_pago_controller.dart';
import 'package:mobile/features/cliente_offline/models/metodo_pago.dart';
import 'package:mobile/core/utils/reloj.dart';
import 'package:mobile/features/notificaciones/presentation/disparador_push.dart';
import 'package:mobile/features/notificaciones/state/notificaciones_controller.dart'
    show notificacionesRepositoryProvider;

import '../../helpers/api_client_falso.dart';
import '../../helpers/cliente_offline_apoyo.dart';
import '../../helpers/push_falso.dart';
import 'apoyo_notificaciones.dart';

/// El aviso de "compra confirmada" puede llegar por la cola de pedidos sin conexión, por el push en primer plano o por la
/// pantalla del pago. Estas pruebas montan las dos fuentes de la app a la vez y comprueban que sale UN solo SnackBar.

const _textoCola = 'Cobramos tu pedido V-0055 por Bs 398.00.';
const _tituloPush = 'Compra confirmada';

class _AuthControlado extends AuthController {
  _AuthControlado(super.ref, AuthState inicial) {
    state = inicial;
  }

  void poner(AuthState nuevo) => state = nuevo;
}

Usuario _usuario(int id) => Usuario(
  id: id,
  nombre: 'Ana',
  apellido: 'Rojas',
  email: 'ana$id@example.com',
  telefono: null,
  activo: true,
  roles: const ['cliente'],
  permisos: const [],
  empresaId: 7,
);

AuthState _sesionDe(int id) => AuthState(estado: EstadoSesion.autenticado, usuario: _usuario(id));

class _MetodoContado extends MetodoPagoController {
  _MetodoContado()
    : super(() async => null, MetodoPagoRepository(ApiClientFalso()), const RelojSistema(), activo: false);

  @override
  Future<MetodoPagoPaypal?> refrescar() async => null;
}

class _Mundo {
  _Mundo(this.cola, this.push, this.router, this.contenedor, this.avisos);

  final ColaFalsa cola;
  final ServicioPushFalso push;
  final GoRouter router;
  final ProviderContainer contenedor;
  final AvisosMostrados avisos;

  PedidoSinConexion cobrado(int ventaId) => PedidoSinConexion.desdeFila({
    ...pedidoDePrueba(estado: EstadoPedidoLocal.cobrado).aFila(),
    'codigo_venta': 'V-00$ventaId',
    'venta_id': ventaId,
    'total_centavos': 39800,
  });

  Future<void> colaCobraPedido(WidgetTester tester, int ventaId) async {
    cola.anunciarResuelto(cobrado(ventaId));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
  }

  Future<void> llegaPush(
    WidgetTester tester, {
    String tipo = 'compra_confirmada',
    int ventaId = 55,
    int notificacionId = 20,
  }) async {
    push.recibirEnPrimerPlano(
      AvisoPush(
        tipo: tipo,
        referenciaId: ventaId,
        notificacionId: notificacionId,
        titulo: _tituloPush,
        cuerpo: 'Tu compra V-00$ventaId está pagada.',
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
  }
}

Widget _pantalla(String texto) => Scaffold(body: Center(child: Text(texto)));

Future<_Mundo> _montar(
  WidgetTester tester, {
  String rutaInicial = '/',
  AvisosMostrados? avisos,
  List<Override> extra = const [],
}) async {
  final cola = ColaFalsa();
  final push = ServicioPushFalso();
  final api = ApiClientFalso()
    ..responder('POST', '/dispositivos-push', null)
    ..responder('POST', '/dispositivos-push/baja', null);
  final repositorio = RepositorioNotificacionesFalso([]);
  final conjunto = avisos ?? AvisosMostrados();
  final router = GoRouter(
    initialLocation: rutaInicial,
    routes: [
      GoRoute(path: '/', builder: (context, state) => _pantalla('INICIO')),
      GoRoute(path: '/splash', builder: (context, state) => _pantalla('SPLASH')),
      GoRoute(path: '/notificaciones', builder: (context, state) => _pantalla('LISTA')),
      GoRoute(path: '/compras/:id', builder: (context, state) => _pantalla('COMPRA ${state.pathParameters['id']}')),
      GoRoute(
        path: '/checkout/estado/:id',
        builder: (context, state) => _pantalla('PAGO ${state.pathParameters['id']}'),
      ),
    ],
  );
  final contenedor = ProviderContainer(
    overrides: [
      servicioPushProvider.overrideWithValue(push),
      almacenPushProvider.overrideWithValue(AlmacenPushFalso()),
      dispositivosPushRepositoryProvider.overrideWithValue(DispositivosPushRepository(() => api)),
      notificacionesRepositoryProvider.overrideWithValue(repositorio),
      authControllerProvider.overrideWith((ref) => _AuthControlado(ref, _sesionDe(4))),
      routerProvider.overrideWithValue(router),
      avisosMostradosProvider.overrideWithValue(conjunto),
      colaPedidosProvider.overrideWithValue(cola),
      alcanceClienteProvider.overrideWithValue(alcanceAna),
      enLineaProvider.overrideWith((ref) => Stream.value(true)),
      metodoPagoLocalProvider.overrideWith((ref) => _MetodoContado()),
      sucursalesRefProvider.overrideWith((ref) async => const <SucursalRef>[]),
      tallasRefProvider.overrideWith((ref) async => const <TallaRef>[]),
      coloresRefProvider.overrideWith((ref) async => const <ColorRef>[]),
      ...extra,
    ],
  );
  addTearDown(contenedor.dispose);
  contenedor.listen(enLineaProvider, (_, _) {});
  await tester.pump();
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: contenedor,
      child: MaterialApp.router(
        routerConfig: router,
        scaffoldMessengerKey: mensajeroGlobal,
        builder: (context, child) => DisparadorColaPedidos(
          esperaConexion: const Duration(milliseconds: 10),
          intervalo: const Duration(minutes: 10),
          child: DisparadorPush(
            esperaConexion: const Duration(milliseconds: 10),
            intervaloNavegacion: const Duration(milliseconds: 20),
            child: child ?? const SizedBox.shrink(),
          ),
        ),
      ),
    ),
  );
  await tester.pump();
  return _Mundo(cola, push, router, contenedor, conjunto);
}

void main() {
  group('la misma compra por la cola y por el push', () {
    testWidgets('cola cobrada y luego push de la misma venta: un solo SnackBar (el de la cola)', (tester) async {
      final m = await _montar(tester);

      await m.colaCobraPedido(tester, 55);
      expect(find.text(_textoCola), findsOneWidget);

      await m.llegaPush(tester, tipo: 'pedido_diferido');
      await m.llegaPush(tester, tipo: 'compra_confirmada', notificacionId: 21);

      expect(find.text(_textoCola), findsOneWidget);
      expect(find.text(_tituloPush), findsNothing);
      expect(find.byType(SnackBar), findsOneWidget);
    });

    testWidgets('push y luego cola cobrada de la misma venta: un solo SnackBar (el del push)', (tester) async {
      final m = await _montar(tester);

      await m.llegaPush(tester);
      expect(find.text(_tituloPush), findsOneWidget);

      await m.colaCobraPedido(tester, 55);

      expect(find.text(_tituloPush), findsOneWidget);
      expect(find.text(_textoCola), findsNothing);
      expect(find.byType(SnackBar), findsOneWidget);
    });

    testWidgets('un push de otra venta sí se muestra', (tester) async {
      final m = await _montar(tester);

      await m.colaCobraPedido(tester, 55);
      await m.llegaPush(tester, ventaId: 56);

      expect(find.text(_tituloPush), findsOneWidget);
    });

    testWidgets('pedido_diferido y compra_confirmada con la misma referencia cuentan como el mismo hecho', (
      tester,
    ) async {
      final m = await _montar(tester);

      await m.llegaPush(tester, tipo: 'pedido_diferido', notificacionId: 20);
      expect(find.byType(SnackBar), findsOneWidget);
      ScaffoldMessenger.of(tester.element(find.text('INICIO'))).clearSnackBars();
      await tester.pump(const Duration(seconds: 1));

      await m.llegaPush(tester, tipo: 'compra_confirmada', notificacionId: 21);

      expect(find.byType(SnackBar), findsNothing);
      expect(m.avisos.contiene('venta:55'), isTrue);
    });

    testWidgets('el mismo push repetido (misma notificación) sale una sola vez', (tester) async {
      final m = await _montar(tester);

      await m.llegaPush(tester, tipo: 'reserva_preparada', notificacionId: 30);
      ScaffoldMessenger.of(tester.element(find.text('INICIO'))).clearSnackBars();
      await tester.pump(const Duration(seconds: 1));
      await m.llegaPush(tester, tipo: 'reserva_preparada', notificacionId: 30);

      expect(find.byType(SnackBar), findsNothing);
    });

    testWidgets('el pago aprobado en pantalla ya contó: el push de esa venta no muestra SnackBar', (tester) async {
      final m = await _montar(tester);
      // Lo que hace EstadoPagoScreen al aprobarse el pago.
      m.avisos.marcar(AvisosMostrados.claveDeVenta(55));

      await m.llegaPush(tester);

      expect(find.byType(SnackBar), findsNothing);
    });

    testWidgets('el push que no muestra SnackBar igual refresca la lista y la campana', (tester) async {
      final m = await _montar(tester);
      m.avisos.marcar(AvisosMostrados.claveDeVenta(55));
      final repositorio = m.contenedor.read(notificacionesRepositoryProvider) as RepositorioNotificacionesFalso;
      final antes = repositorio.consultas;

      await m.llegaPush(tester);

      expect(find.byType(SnackBar), findsNothing);
      expect(repositorio.consultas, greaterThan(antes));
    });
  });

  group('la persona ya está mirando la compra', () {
    testWidgets('en /compras/<id> de esa venta, ni el push ni la cola muestran SnackBar', (tester) async {
      final m = await _montar(tester, rutaInicial: '/compras/55');
      expect(find.text('COMPRA 55'), findsOneWidget);

      await m.llegaPush(tester);
      await m.colaCobraPedido(tester, 55);

      expect(find.byType(SnackBar), findsNothing);
    });

    testWidgets('en /compras/<otra venta> el aviso de esta sí sale', (tester) async {
      final m = await _montar(tester, rutaInicial: '/compras/99');

      await m.llegaPush(tester);

      expect(find.text(_tituloPush), findsOneWidget);
    });

    testWidgets('en la pantalla del estado del pago no sale SnackBar', (tester) async {
      final m = await _montar(tester, rutaInicial: '/checkout/estado/3');
      expect(find.text('PAGO 3'), findsOneWidget);

      await m.llegaPush(tester);
      await m.colaCobraPedido(tester, 55);

      expect(find.byType(SnackBar), findsNothing);
    });
  });

  group('un push solo', () {
    testWidgets('sin que la cola ni la pantalla hayan avisado, sale el SnackBar', (tester) async {
      final m = await _montar(tester);

      await m.llegaPush(tester);

      expect(find.text(_tituloPush), findsOneWidget);
      expect(find.text('Ver'), findsOneWidget);
      expect(m.avisos.contiene('venta:55'), isTrue);
      expect(m.avisos.contiene('notif:20'), isTrue);
    });

    testWidgets('un pedido rechazado nunca se calla (no es una compra pagada)', (tester) async {
      final m = await _montar(tester);
      m.avisos.marcar(AvisosMostrados.claveDeVenta(55));
      final rechazado = PedidoSinConexion.desdeFila({
        ...pedidoDePrueba(estado: EstadoPedidoLocal.rechazado).aFila(),
        'mensaje': 'Ya no queda esa talla.',
      });

      m.cola.anunciarResuelto(rechazado);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));

      expect(find.text('Ya no queda esa talla.'), findsOneWidget);
    });
  });

  group('el conjunto se reinicia con la sesión', () {
    ProviderContainer contenedor() {
      final c = ProviderContainer(
        overrides: [authControllerProvider.overrideWith((ref) => _AuthControlado(ref, _sesionDe(4)))],
      );
      addTearDown(c.dispose);
      return c;
    }

    test('al cerrar la sesión empieza vacío', () {
      final c = contenedor();
      c.listen(avisosMostradosProvider, (_, _) {});
      final auth = c.read(authControllerProvider.notifier) as _AuthControlado;

      expect(c.read(avisosMostradosProvider).marcar('venta:55'), isTrue);
      expect(c.read(avisosMostradosProvider).marcar('venta:55'), isFalse, reason: 'misma sesión: ya estaba');

      auth.poner(const AuthState(estado: EstadoSesion.noAutenticado));
      expect(c.read(avisosMostradosProvider).cantidad, 0);

      auth.poner(_sesionDe(4));
      expect(c.read(avisosMostradosProvider).marcar('venta:55'), isTrue, reason: 'sesión nueva: vuelve a avisar');
    });

    test('al entrar otra persona empieza vacío', () {
      final c = contenedor();
      c.listen(avisosMostradosProvider, (_, _) {});
      final auth = c.read(authControllerProvider.notifier) as _AuthControlado;
      c.read(avisosMostradosProvider).marcar('venta:55');

      auth.poner(_sesionDe(9));

      expect(c.read(avisosMostradosProvider).contiene('venta:55'), isFalse);
    });

    test('un cambio que no es de persona (se refresca el perfil) conserva lo anotado', () {
      final c = contenedor();
      c.listen(avisosMostradosProvider, (_, _) {});
      final auth = c.read(authControllerProvider.notifier) as _AuthControlado;
      c.read(avisosMostradosProvider).marcar('venta:55');

      auth.poner(_sesionDe(4));

      expect(c.read(avisosMostradosProvider).contiene('venta:55'), isTrue);
    });
  });

  group('yaViendoLaCompra', () {
    test('solo cuenta la compra de esa venta o el estado de un pago', () {
      expect(yaViendoLaCompra('/compras/55', 55), isTrue);
      expect(yaViendoLaCompra('/compras/56', 55), isFalse);
      expect(yaViendoLaCompra('/checkout/estado/3', 55), isTrue);
      expect(yaViendoLaCompra('/checkout/estado/3', null), isTrue);
      expect(yaViendoLaCompra('/compras', 55), isFalse);
      expect(yaViendoLaCompra(null, 55), isFalse);
    });
  });
}
