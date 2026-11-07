import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/core/network/providers.dart';
import 'package:mobile/core/sesion/contador_pendientes.dart';
import 'package:mobile/core/sesion/dialogos_sesion.dart';
import 'package:mobile/features/auth/models/usuario.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/auth/state/auth_state.dart';
import 'package:mobile/features/cliente_offline/models/linea_carrito_local.dart';
import 'package:mobile/features/cliente_offline/state/base_cliente.dart';
import 'package:mobile/features/cliente_offline/state/cliente_offline_providers.dart';
import 'package:mobile/features/tienda/models/tienda.dart';
import 'package:mobile/features/tienda/state/tienda_controller.dart';

import '../../helpers/cliente_offline_apoyo.dart';
import '../../helpers/sesion_storage_falso.dart';
import '../../helpers/token_storage_falso.dart';

class _AuthFalso extends AuthController {
  _AuthFalso(super.ref, AuthState inicial) {
    state = inicial;
  }
}

class _LimpiezaFalsa extends LimpiezaCliente {
  _LimpiezaFalsa() : super(() async => throw StateError('sin base'));

  final cierres = <AlcanceCliente>[];
  final borrados = <AlcanceCliente>[];

  @override
  Future<void> alCerrarSesion(AlcanceCliente alcance) async => cierres.add(alcance);

  @override
  Future<void> borrarTodo(AlcanceCliente alcance) async => borrados.add(alcance);
}

class _SinContador implements ContadorPendientes {
  @override
  Future<int> pendientesDe({int? empresaId, int? usuarioId}) async => 0;
}

const _tienda = Tienda(codigo: 'chaski', nombre: 'Chaski Sport');

const _cliente = Usuario(
  id: 9,
  nombre: 'Luis',
  apellido: 'Mamani',
  email: 'luis@example.com',
  telefono: null,
  activo: true,
  roles: ['cliente'],
  permisos: [],
  empresaId: 7,
  empresaCodigo: 'chaski',
);

const _cajero = Usuario(
  id: 5,
  nombre: 'Ana',
  apellido: 'Rojas',
  email: 'ana@example.com',
  telefono: null,
  activo: true,
  roles: ['cajero'],
  permisos: ['ventas.presencial'],
  empresaId: 7,
  empresaCodigo: 'chaski',
);

class _Pantalla extends ConsumerWidget {
  const _Pantalla();

  @override
  Widget build(BuildContext context, WidgetRef ref) => Scaffold(
    body: Column(
      children: [
        TextButton(onPressed: () => cerrarSesionConAviso(context, ref), child: const Text('BOTON CERRAR')),
        TextButton(onPressed: () => cambiarDeTiendaConAviso(context, ref), child: const Text('BOTON CAMBIAR')),
      ],
    ),
  );
}

class _Escenario {
  _Escenario(this.contenedor, this.cola, this.limpieza, this.tokens);

  final ProviderContainer contenedor;
  final ColaFalsa cola;
  final _LimpiezaFalsa limpieza;
  final TokenStorageFalso tokens;

  AuthState get auth => contenedor.read(authControllerProvider);
}

Future<_Escenario> _montar(WidgetTester tester, {int sinEnviar = 0, Usuario usuario = _cliente}) async {
  final tokens = TokenStorageFalso()
    ..accessToken = 'ACCESS'
    ..refreshToken = 'REFRESH';
  final cola = ColaFalsa(sinEnviar: sinEnviar);
  final limpieza = _LimpiezaFalsa();
  final contenedor = ProviderContainer(
    overrides: [
      tokenStorageProvider.overrideWithValue(tokens),
      sesionStorageProvider.overrideWithValue(SesionStorageFalso(tienda: _tienda)),
      authControllerProvider.overrideWith(
        (ref) => _AuthFalso(ref, AuthState(estado: EstadoSesion.autenticado, usuario: usuario)),
      ),
      contadorPendientesProvider.overrideWithValue(_SinContador()),
      colaPedidosProvider.overrideWithValue(cola),
      limpiezaClienteProvider.overrideWithValue(limpieza),
    ],
  );
  addTearDown(contenedor.dispose);
  await contenedor.read(tiendaControllerProvider.notifier).cargadaFuture;
  final router = GoRouter(
    routes: [
      GoRoute(path: '/', builder: (context, state) => const _Pantalla()),
      GoRoute(
        path: '/tienda',
        builder: (context, state) => const Scaffold(body: Text('PANTALLA ELIGE TIENDA')),
      ),
    ],
  );
  addTearDown(router.dispose);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: contenedor,
      child: MaterialApp.router(routerConfig: router),
    ),
  );
  await tester.pump();
  return _Escenario(contenedor, cola, limpieza, tokens);
}

Future<void> _tocar(WidgetTester tester, Finder f) async {
  await tester.tap(f);
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
}

Finder get _dialogo => find.byKey(const Key('dialogo-salida-pedidos'));

void main() {
  group('cerrar sesión de un cliente', () {
    testWidgets('sin pedidos sin enviar sale directo, sin preguntar', (tester) async {
      final e = await _montar(tester);

      await _tocar(tester, find.text('BOTON CERRAR'));

      expect(_dialogo, findsNothing);
      expect(e.auth.estado, EstadoSesion.noAutenticado);
      expect(e.cola.borrados, 0);
    });

    testWidgets('con 3 pedidos: "Tienes 3 pedidos sin enviar" y todavía no sale', (tester) async {
      final e = await _montar(tester, sinEnviar: 3);

      await _tocar(tester, find.text('BOTON CERRAR'));

      expect(_dialogo, findsOneWidget);
      expect(find.text('Tienes 3 pedidos sin enviar'), findsOneWidget);
      expect(find.text('Conservarlos'), findsOneWidget);
      expect(find.text('Borrarlos y salir'), findsOneWidget);
      expect(e.auth.estado, EstadoSesion.autenticado);
    });

    testWidgets('con 1 pedido, en singular', (tester) async {
      await _montar(tester, sinEnviar: 1);

      await _tocar(tester, find.text('BOTON CERRAR'));

      expect(find.text('Tienes 1 pedido sin enviar'), findsOneWidget);
    });

    testWidgets('"Conservarlos" es lo predeterminado (el botón lleno con el foco) y sale sin borrar nada', (
      tester,
    ) async {
      final e = await _montar(tester, sinEnviar: 2);
      await _tocar(tester, find.text('BOTON CERRAR'));

      final conservar = tester.widget<FilledButton>(find.byKey(const Key('conservar-pedidos')));
      expect(conservar.autofocus, isTrue);
      await _tocar(tester, find.byKey(const Key('conservar-pedidos')));

      expect(_dialogo, findsNothing);
      expect(e.auth.estado, EstadoSesion.noAutenticado);
      expect(e.cola.borrados, 0, reason: 'los pedidos se quedan en el teléfono');
      expect(e.limpieza.borrados, isEmpty);
      expect(e.limpieza.cierres, [
        alcanceLuis,
      ], reason: 'se limpia lo de la sesión pero la limpieza conserva los pedidos');
      expect(e.tokens.vecesLimpiado, 1);
    });

    testWidgets('"Borrarlos y salir" borra los pedidos de esa cuenta y luego sale', (tester) async {
      final e = await _montar(tester, sinEnviar: 2);
      await _tocar(tester, find.text('BOTON CERRAR'));

      await _tocar(tester, find.byKey(const Key('borrar-pedidos')));

      expect(e.cola.borrados, 1);
      expect(e.auth.estado, EstadoSesion.noAutenticado);
      expect(e.tokens.vecesLimpiado, 1);
    });

    testWidgets('"Cancelar" no sale ni borra nada', (tester) async {
      final e = await _montar(tester, sinEnviar: 2);
      await _tocar(tester, find.text('BOTON CERRAR'));

      await _tocar(tester, find.byKey(const Key('cancelar-salida')));

      expect(_dialogo, findsNothing);
      expect(e.auth.estado, EstadoSesion.autenticado);
      expect(e.cola.borrados, 0);
      expect(e.tokens.vecesLimpiado, 0);
    });

    testWidgets('tocar fuera del aviso tampoco sale', (tester) async {
      final e = await _montar(tester, sinEnviar: 2);
      await _tocar(tester, find.text('BOTON CERRAR'));

      await tester.tapAt(const Offset(2, 2));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));

      expect(_dialogo, findsNothing);
      expect(e.auth.estado, EstadoSesion.autenticado);
      expect(e.cola.borrados, 0);
    });

    testWidgets('un cierre FORZADO (la sesión venció) conserva los pedidos sin preguntar', (tester) async {
      final e = await _montar(tester, sinEnviar: 4);

      await e.contenedor.read(authControllerProvider.notifier).logout(motivo: MotivoCierre.vencida);
      await tester.pump();

      expect(_dialogo, findsNothing);
      expect(e.auth.estado, EstadoSesion.noAutenticado);
      expect(e.cola.borrados, 0);
      expect(e.limpieza.borrados, isEmpty);
      expect(e.limpieza.cierres, [alcanceLuis], reason: 'la limpieza normal conserva los pedidos sin enviar');
    });
  });

  group('cambiar de tienda de un cliente', () {
    testWidgets('con pedidos sin enviar el aviso nombra la tienda y pregunta qué hacer', (tester) async {
      final e = await _montar(tester, sinEnviar: 2);

      await _tocar(tester, find.text('BOTON CAMBIAR'));

      expect(find.text('Tienes 2 pedidos sin enviar'), findsOneWidget);
      expect(find.textContaining('Se cerrará tu sesión en Chaski Sport.'), findsOneWidget);
      expect(e.auth.estado, EstadoSesion.autenticado);
    });

    testWidgets('"Conservarlos" cierra la sesión y lleva a elegir tienda', (tester) async {
      final e = await _montar(tester, sinEnviar: 2);
      await _tocar(tester, find.text('BOTON CAMBIAR'));

      await _tocar(tester, find.byKey(const Key('conservar-pedidos')));

      expect(e.auth.estado, EstadoSesion.noAutenticado);
      expect(e.cola.borrados, 0);
      expect(find.text('PANTALLA ELIGE TIENDA'), findsOneWidget);
    });

    testWidgets('"Cancelar" se queda donde está', (tester) async {
      final e = await _montar(tester, sinEnviar: 2);
      await _tocar(tester, find.text('BOTON CAMBIAR'));

      await _tocar(tester, find.byKey(const Key('cancelar-salida')));

      expect(e.auth.estado, EstadoSesion.autenticado);
      expect(find.text('PANTALLA ELIGE TIENDA'), findsNothing);
    });

    testWidgets('sin pedidos pide la confirmación de siempre', (tester) async {
      await _montar(tester);

      await _tocar(tester, find.text('BOTON CAMBIAR'));

      expect(_dialogo, findsNothing);
      expect(find.textContaining('Se cerrará tu sesión en Chaski Sport.'), findsOneWidget);
    });
  });

  testWidgets('el personal no ve este aviso aunque la cola del cliente tenga pedidos', (tester) async {
    final e = await _montar(tester, sinEnviar: 5, usuario: _cajero);

    await _tocar(tester, find.text('BOTON CERRAR'));

    expect(_dialogo, findsNothing);
    expect(e.auth.estado, EstadoSesion.noAutenticado);
  });
}
