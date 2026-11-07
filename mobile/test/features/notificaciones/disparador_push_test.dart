import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/core/conectividad/conectividad_service.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/push/dispositivos_push_repository.dart';
import 'package:mobile/core/push/registro_push.dart';
import 'package:mobile/core/push/servicio_push.dart';
import 'package:mobile/core/router/app_router.dart';
import 'package:mobile/core/sync/disparador_sincronizacion.dart' show mensajeroGlobal;
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/auth/state/auth_state.dart';
import 'package:mobile/features/notificaciones/presentation/disparador_push.dart';
import 'package:mobile/features/notificaciones/presentation/notificaciones_screen.dart';
import 'package:mobile/features/notificaciones/state/notificaciones_controller.dart'
    show notificacionesRepositoryProvider;

import '../../helpers/api_client_falso.dart';
import '../../helpers/push_falso.dart';
import 'apoyo_notificaciones.dart';

/// Un AuthController que no habla con el backend: el estado de la sesión se cambia a mano.
class _AuthControlado extends AuthController {
  _AuthControlado(super.ref, EstadoSesion inicial) {
    state = AuthState(estado: inicial);
  }

  void poner(EstadoSesion estado) => state = AuthState(estado: estado);
}

const _sinRed = ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: 'Sin conexión.');

class _Mundo {
  _Mundo(this.servicio, this.api, this.almacen, this.repositorio, this.router, this.contenedor, this.red);

  final ServicioPushFalso servicio;
  final ApiClientFalso api;
  final AlmacenPushFalso almacen;
  final RepositorioNotificacionesFalso repositorio;
  final GoRouter router;
  final ProviderContainer contenedor;
  final StreamController<bool> red;

  _AuthControlado get auth => contenedor.read(authControllerProvider.notifier) as _AuthControlado;
}

Widget _pantalla(String texto) => Scaffold(body: Center(child: Text(texto)));

Future<_Mundo> _montar(
  WidgetTester tester, {
  EstadoSesion sesion = EstadoSesion.autenticado,
  ServicioPushFalso? servicio,
  String rutaInicial = '/',
  List<Object?> altas = const [null],
  bool enLinea = true,
  Widget? inicio,
}) async {
  final servicioPush = servicio ?? ServicioPushFalso();
  final api = ApiClientFalso();
  for (final respuesta in altas) {
    api.responder('POST', '/dispositivos-push', respuesta);
  }
  api.responder('POST', '/dispositivos-push/baja', null);
  final almacen = AlmacenPushFalso();
  final repositorio = RepositorioNotificacionesFalso([
    notificacion(9, titulo: 'Cobramos tu pedido', mensaje: 'Compra V-55', tipo: 'pedido_diferido', referenciaId: 55),
  ]);
  final red = StreamController<bool>();
  final router = GoRouter(
    initialLocation: rutaInicial,
    routes: [
      GoRoute(path: '/', builder: (context, state) => inicio ?? _pantalla('INICIO')),
      GoRoute(path: '/splash', builder: (context, state) => _pantalla('SPLASH')),
      GoRoute(path: '/notificaciones', builder: (context, state) => _pantalla('LISTA')),
      GoRoute(
        path: '/compras/:id',
        builder: (context, state) => _pantalla('COMPRA ${state.pathParameters['id']}'),
      ),
      GoRoute(
        path: '/reserva/:id',
        builder: (context, state) => _pantalla('RESERVA ${state.pathParameters['id']}'),
      ),
    ],
  );
  final contenedor = ProviderContainer(
    overrides: [
      servicioPushProvider.overrideWithValue(servicioPush),
      almacenPushProvider.overrideWithValue(almacen),
      dispositivosPushRepositoryProvider.overrideWithValue(DispositivosPushRepository(() => api)),
      notificacionesRepositoryProvider.overrideWithValue(repositorio),
      authControllerProvider.overrideWith((ref) => _AuthControlado(ref, sesion)),
      routerProvider.overrideWithValue(router),
      enLineaProvider.overrideWith((ref) {
        ref.onDispose(red.close);
        return (() async* {
          yield enLinea;
          yield* red.stream;
        })();
      }),
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
        builder: (context, child) => DisparadorPush(
          esperaConexion: const Duration(milliseconds: 10),
          intervaloNavegacion: const Duration(milliseconds: 20),
          child: child ?? const SizedBox.shrink(),
        ),
      ),
    ),
  );
  await tester.pump();
  return _Mundo(servicioPush, api, almacen, repositorio, router, contenedor, red);
}

void main() {
  group('arranque', () {
    testWidgets('inicia el servicio una vez y muestra la app', (tester) async {
      final m = await _montar(tester);

      expect(m.servicio.iniciadas, 1);
      expect(find.text('INICIO'), findsOneWidget);
    });

    testWidgets('un fallo de Firebase al iniciar no rompe la app', (tester) async {
      final servicio = ServicioPushFalso()..fallaAlIniciar = true;

      await _montar(tester, servicio: servicio);

      expect(find.text('INICIO'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });

  group('token que cambia', () {
    testWidgets('con sesión lo reenvía al servidor', (tester) async {
      final m = await _montar(tester);

      m.servicio.refrescarToken('TOKEN-NUEVO');
      await tester.pump();

      final altas = m.api.de('POST', '/dispositivos-push');
      expect(altas, hasLength(1));
      expect(altas.single.cuerpo, {'token': 'TOKEN-NUEVO', 'plataforma': 'android'});
    });

    testWidgets('sin sesión no manda nada', (tester) async {
      final m = await _montar(tester, sesion: EstadoSesion.noAutenticado);

      m.servicio.refrescarToken('TOKEN-NUEVO');
      await tester.pump();

      expect(m.api.de('POST', '/dispositivos-push'), isEmpty);
    });
  });

  group('al tocar el aviso del sistema', () {
    testWidgets('pedido_diferido abre la compra', (tester) async {
      final m = await _montar(tester);

      m.servicio.tocarAviso(const AvisoPush(tipo: 'pedido_diferido', referenciaId: 55, notificacionId: 9));
      await tester.pumpAndSettle();

      expect(find.text('COMPRA 55'), findsOneWidget);
    });

    testWidgets('actualiza la campana y marca como leída la notificación abierta', (tester) async {
      final m = await _montar(tester);

      m.servicio.tocarAviso(const AvisoPush(tipo: 'pedido_diferido', referenciaId: 55, notificacionId: 9));
      await tester.pumpAndSettle();

      expect(m.repositorio.consultas, greaterThanOrEqualTo(1));
      expect(m.repositorio.marcadas, contains(9));
    });

    testWidgets('un tipo sin pantalla propia abre la lista de notificaciones', (tester) async {
      final m = await _montar(tester);

      m.servicio.tocarAviso(const AvisoPush(tipo: 'promocion', referenciaId: 1));
      await tester.pumpAndSettle();

      expect(find.text('LISTA'), findsOneWidget);
    });

    testWidgets('sin sesión no abre nada', (tester) async {
      final m = await _montar(tester, sesion: EstadoSesion.noAutenticado);

      m.servicio.tocarAviso(const AvisoPush(tipo: 'pedido_diferido', referenciaId: 55));
      await tester.pumpAndSettle();

      expect(find.text('INICIO'), findsOneWidget);
      expect(find.text('COMPRA 55'), findsNothing);
    });

    testWidgets('app abierta en frío desde la notificación: espera a que la sesión se restaure', (tester) async {
      final servicio = ServicioPushFalso()
        ..avisoInicial = const AvisoPush(tipo: 'pedido_diferido', referenciaId: 55);
      final m = await _montar(tester, sesion: EstadoSesion.cargando, servicio: servicio);
      await tester.pumpAndSettle();
      expect(find.text('COMPRA 55'), findsNothing, reason: 'todavía no se sabe si hay sesión');

      m.auth.poner(EstadoSesion.autenticado);
      await tester.pumpAndSettle();

      expect(find.text('COMPRA 55'), findsOneWidget);
    });

    testWidgets('app abierta en frío y la sesión no se restaura: el aviso se descarta', (tester) async {
      final servicio = ServicioPushFalso()
        ..avisoInicial = const AvisoPush(tipo: 'pedido_diferido', referenciaId: 55);
      final m = await _montar(tester, sesion: EstadoSesion.cargando, servicio: servicio);

      m.auth.poner(EstadoSesion.noAutenticado);
      await tester.pumpAndSettle();
      m.auth.poner(EstadoSesion.autenticado);
      await tester.pumpAndSettle();

      expect(find.text('COMPRA 55'), findsNothing);
    });

    testWidgets('si la app sigue en la pantalla de arranque, abre el aviso cuando sale de ella', (tester) async {
      final m = await _montar(tester, rutaInicial: '/splash');
      expect(find.text('SPLASH'), findsOneWidget);

      m.servicio.tocarAviso(const AvisoPush(tipo: 'pedido_diferido', referenciaId: 55));
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.text('COMPRA 55'), findsNothing);

      m.router.go('/');
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      await tester.pumpAndSettle();

      expect(find.text('COMPRA 55'), findsOneWidget);
    });
  });

  group('con la app en primer plano', () {
    testWidgets('muestra el aviso dentro de la app con la acción "Ver" y NO abre nada solo', (tester) async {
      final m = await _montar(tester);

      m.servicio.recibirEnPrimerPlano(
        const AvisoPush(
          tipo: 'pedido_diferido',
          referenciaId: 55,
          notificacionId: 9,
          titulo: 'Cobramos tu pedido',
          cuerpo: 'Compra V-55',
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));

      expect(find.text('Cobramos tu pedido'), findsOneWidget);
      expect(find.text('Compra V-55'), findsOneWidget);
      expect(find.text('Ver'), findsOneWidget);
      expect(find.text('COMPRA 55'), findsNothing);
    });

    testWidgets('actualiza la lista de notificaciones (la campana)', (tester) async {
      final m = await _montar(tester);
      final antes = m.repositorio.consultas;

      m.servicio.recibirEnPrimerPlano(const AvisoPush(titulo: 'Hola'));
      await tester.pump();

      expect(m.repositorio.consultas, greaterThan(antes));
    });

    testWidgets('"Ver" abre la pantalla del aviso', (tester) async {
      final m = await _montar(tester);

      m.servicio.recibirEnPrimerPlano(
        const AvisoPush(tipo: 'pedido_diferido', referenciaId: 55, notificacionId: 9, titulo: 'Cobramos tu pedido'),
      );
      await tester.pump();
      await tester.pump(const Duration(seconds: 1));
      await tester.pump(const Duration(seconds: 1)); // la animación del SnackBar arranca en el cuadro siguiente
      await tester.tap(find.text('Ver'));
      await tester.pumpAndSettle();

      expect(find.text('COMPRA 55'), findsOneWidget);
    });

    testWidgets('sin sesión no muestra nada', (tester) async {
      final m = await _montar(tester, sesion: EstadoSesion.noAutenticado);

      m.servicio.recibirEnPrimerPlano(const AvisoPush(titulo: 'Cobramos tu pedido'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));

      expect(find.text('Cobramos tu pedido'), findsNothing);
    });
  });

  group('conexión', () {
    testWidgets('al volver la red reintenta el alta que había fallado', (tester) async {
      final m = await _montar(tester, altas: [_sinRed, null], enLinea: false);
      await m.contenedor.read(registroPushProvider).alIniciarSesion();
      expect(m.contenedor.read(registroPushProvider).registrado, isFalse);

      m.red.add(true);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 30));

      expect(m.api.de('POST', '/dispositivos-push'), hasLength(2));
      expect(m.contenedor.read(registroPushProvider).registrado, isTrue);
    });

    testWidgets('sin sesión, volver la red no hace nada', (tester) async {
      final m = await _montar(tester, sesion: EstadoSesion.noAutenticado, enLinea: false);

      m.red.add(true);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 30));

      expect(m.api.de('POST', '/dispositivos-push'), isEmpty);
    });
  });

  group('permiso en la pantalla de notificaciones', () {
    testWidgets('lo pide si falta y, concedido, registra el token', (tester) async {
      final servicio = ServicioPushFalso(permiso: false, concedeAlPedir: true);
      final m = await _montar(tester, servicio: servicio, inicio: const NotificacionesScreen());
      await tester.pumpAndSettle();

      expect(servicio.permisosPedidos, 1);
      expect(m.api.de('POST', '/dispositivos-push'), hasLength(1));
    });

    testWidgets('si lo niega, la lista funciona igual y no se registra nada', (tester) async {
      final servicio = ServicioPushFalso(permiso: false, concedeAlPedir: false);
      final m = await _montar(tester, servicio: servicio, inicio: const NotificacionesScreen());
      await tester.pumpAndSettle();

      expect(servicio.permisosPedidos, 1);
      expect(m.api.de('POST', '/dispositivos-push'), isEmpty);
      expect(find.text('Cobramos tu pedido'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });
}
