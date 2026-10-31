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
import 'package:mobile/features/tienda/models/tienda.dart';
import 'package:mobile/features/tienda/state/tienda_controller.dart';

import '../../helpers/sesion_storage_falso.dart';
import '../../helpers/token_storage_falso.dart';

/// Un [AuthController] que arranca directamente en el estado dado. `logout` es el real: limpia los tokens y deja la
/// sesión en `noAutenticado`.
class AuthControllerFalso extends AuthController {
  AuthControllerFalso(super.ref, AuthState inicial) {
    state = inicial;
  }
}

/// Un contador que responde siempre lo mismo y recuerda con qué argumentos se le preguntó.
class _ContadorFijo implements ContadorPendientes {
  _ContadorFijo(this.pendientes);

  final int pendientes;
  final consultas = <({int? empresaId, int? usuarioId})>[];

  @override
  Future<int> pendientesDe({int? empresaId, int? usuarioId}) async {
    consultas.add((empresaId: empresaId, usuarioId: usuarioId));
    return pendientes;
  }
}

const _tienda = Tienda(codigo: 'chaski', nombre: 'Chaski Sport');

const _usuario = Usuario(
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

/// Un cliente: no tiene base local, así que no se le cuentan pendientes.
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

const _conSesion = AuthState(estado: EstadoSesion.autenticado, usuario: _usuario);
const _sinSesion = AuthState(estado: EstadoSesion.noAutenticado);

/// Una pantalla de prueba con un botón por cada función que se prueba.
class _PantallaPrueba extends ConsumerWidget {
  const _PantallaPrueba();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      body: Column(
        children: [
          TextButton(onPressed: () => cerrarSesionConAviso(context, ref), child: const Text('BOTON CERRAR')),
          TextButton(onPressed: () => cambiarDeTiendaConAviso(context, ref), child: const Text('BOTON CAMBIAR')),
        ],
      ),
    );
  }
}

class _Escenario {
  _Escenario(this.contenedor, this.router, this.tokens, this.contador);

  final ProviderContainer contenedor;
  final GoRouter router;
  final TokenStorageFalso tokens;
  final _ContadorFijo contador;

  AuthState get auth => contenedor.read(authControllerProvider);
}

Future<_Escenario> _montar(
  WidgetTester tester, {
  AuthState auth = _conSesion,
  int pendientes = 0,
  Tienda? tienda = _tienda,
}) async {
  final tokens = TokenStorageFalso()
    ..accessToken = 'ACCESS'
    ..refreshToken = 'REFRESH';
  final contador = _ContadorFijo(pendientes);
  final contenedor = ProviderContainer(
    overrides: [
      tokenStorageProvider.overrideWithValue(tokens),
      sesionStorageProvider.overrideWithValue(SesionStorageFalso(tienda: tienda)),
      authControllerProvider.overrideWith((ref) => AuthControllerFalso(ref, auth)),
      contadorPendientesProvider.overrideWithValue(contador),
    ],
  );
  addTearDown(contenedor.dispose);
  await contenedor.read(tiendaControllerProvider.notifier).cargadaFuture;

  final router = GoRouter(
    routes: [
      GoRoute(path: '/', builder: (context, state) => const _PantallaPrueba()),
      GoRoute(path: '/tienda', builder: (context, state) => const Scaffold(body: Text('PANTALLA ELIGE TIENDA'))),
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
  return _Escenario(contenedor, router, tokens, contador);
}

Future<void> _tocar(WidgetTester tester, String texto) async {
  await tester.tap(find.text(texto));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
}

Finder get _dialogo => find.byType(AlertDialog);

void main() {
  group('cerrarSesionConAviso', () {
    testWidgets('sin sesión no hace nada ni pregunta', (tester) async {
      final e = await _montar(tester, auth: _sinSesion, pendientes: 4);

      await _tocar(tester, 'BOTON CERRAR');

      expect(_dialogo, findsNothing);
      expect(e.contador.consultas, isEmpty);
      expect(e.tokens.vecesLimpiado, 0);
      expect(e.auth.estado, EstadoSesion.noAutenticado);
    });

    testWidgets('con sesión y 0 pendientes cierra sin preguntar', (tester) async {
      final e = await _montar(tester, pendientes: 0);

      await _tocar(tester, 'BOTON CERRAR');

      expect(_dialogo, findsNothing);
      expect(e.auth.estado, EstadoSesion.noAutenticado);
      expect(e.auth.usuario, isNull);
      expect(e.tokens.vecesLimpiado, 1);
      expect(e.tokens.accessToken, isNull);
      expect(e.tokens.refreshToken, isNull);
    });

    testWidgets('consulta los pendientes de ESA empresa y ESE usuario', (tester) async {
      final e = await _montar(tester, pendientes: 0);

      await _tocar(tester, 'BOTON CERRAR');

      expect(e.contador.consultas, hasLength(1));
      expect(e.contador.consultas.single.empresaId, 7);
      expect(e.contador.consultas.single.usuarioId, 5);
    });

    testWidgets('a un cliente no se le consulta el contador (no abre la base local) y cierra sin preguntar', (tester) async {
      final e = await _montar(
        tester,
        auth: const AuthState(estado: EstadoSesion.autenticado, usuario: _cliente),
        pendientes: 5,
      );

      await _tocar(tester, 'BOTON CERRAR');

      expect(e.contador.consultas, isEmpty);
      expect(_dialogo, findsNothing);
      expect(e.auth.estado, EstadoSesion.noAutenticado);
      expect(e.tokens.vecesLimpiado, 1);
    });

    testWidgets('con 3 pendientes avisa con el número en plural', (tester) async {
      final e = await _montar(tester, pendientes: 3);

      await _tocar(tester, 'BOTON CERRAR');

      expect(_dialogo, findsOneWidget);
      expect(find.textContaining('Tienes 3 operaciones sin enviar'), findsOneWidget);
      expect(find.textContaining('tendrás que ingresar de nuevo'), findsOneWidget);
      // Mientras el aviso está abierto la sesión sigue en pie.
      expect(e.auth.estado, EstadoSesion.autenticado);
      expect(e.tokens.vecesLimpiado, 0);
    });

    testWidgets('con 1 pendiente avisa en singular', (tester) async {
      await _montar(tester, pendientes: 1);

      await _tocar(tester, 'BOTON CERRAR');

      expect(find.textContaining('Tienes 1 operación sin enviar'), findsOneWidget);
      expect(find.textContaining('1 operaciones'), findsNothing);
    });

    testWidgets('con pendientes, Cancelar no cierra la sesión', (tester) async {
      final e = await _montar(tester, pendientes: 3);
      await _tocar(tester, 'BOTON CERRAR');

      await _tocar(tester, 'Cancelar');

      expect(_dialogo, findsNothing);
      expect(e.auth.estado, EstadoSesion.autenticado);
      expect(e.auth.usuario, _usuario);
      expect(e.tokens.vecesLimpiado, 0);
      expect(e.tokens.accessToken, 'ACCESS');
    });

    testWidgets('con pendientes, Cerrar sesión cierra la sesión', (tester) async {
      final e = await _montar(tester, pendientes: 3);
      await _tocar(tester, 'BOTON CERRAR');

      await tester.tap(find.widgetWithText(TextButton, 'Cerrar sesión'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));

      expect(_dialogo, findsNothing);
      expect(e.auth.estado, EstadoSesion.noAutenticado);
      expect(e.tokens.vecesLimpiado, 1);
      expect(e.tokens.accessToken, isNull);
    });

    testWidgets('el aviso se puede descartar tocando fuera y entonces no se cierra', (tester) async {
      final e = await _montar(tester, pendientes: 2);
      await _tocar(tester, 'BOTON CERRAR');
      expect(_dialogo, findsOneWidget);

      await tester.tapAt(const Offset(2, 2));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));

      expect(_dialogo, findsNothing);
      expect(e.auth.estado, EstadoSesion.autenticado);
      expect(e.tokens.vecesLimpiado, 0);
    });
  });

  group('cambiarDeTiendaConAviso', () {
    testWidgets('sin sesión navega directo a /tienda sin preguntar', (tester) async {
      final e = await _montar(tester, auth: _sinSesion, pendientes: 4);

      await _tocar(tester, 'BOTON CAMBIAR');

      expect(_dialogo, findsNothing);
      expect(find.text('PANTALLA ELIGE TIENDA'), findsOneWidget);
      expect(e.contador.consultas, isEmpty);
    });

    testWidgets('la pantalla de tiendas se apila encima: se puede volver atrás', (tester) async {
      final e = await _montar(tester, auth: _sinSesion);

      await _tocar(tester, 'BOTON CAMBIAR');
      expect(e.router.canPop(), isTrue);

      e.router.pop();
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));

      expect(find.text('BOTON CAMBIAR'), findsOneWidget);
      expect(find.text('PANTALLA ELIGE TIENDA'), findsNothing);
    });

    testWidgets('con sesión pregunta y nombra la tienda', (tester) async {
      final e = await _montar(tester, pendientes: 0);

      await _tocar(tester, 'BOTON CAMBIAR');

      expect(_dialogo, findsOneWidget);
      // El título del aviso y su botón de confirmar dicen lo mismo.
      expect(find.text('Cambiar de tienda'), findsNWidgets(2));
      expect(find.textContaining('Se cerrará tu sesión en Chaski Sport.'), findsOneWidget);
      expect(find.textContaining('sin enviar'), findsNothing);
      expect(find.text('PANTALLA ELIGE TIENDA'), findsNothing);
      expect(e.auth.estado, EstadoSesion.autenticado);
    });

    testWidgets('con sesión y sin tienda guardada dice "esta tienda"', (tester) async {
      await _montar(tester, tienda: null);

      await _tocar(tester, 'BOTON CAMBIAR');

      expect(find.textContaining('Se cerrará tu sesión en esta tienda.'), findsOneWidget);
    });

    testWidgets('con sesión y pendientes suma el aviso de operaciones sin enviar', (tester) async {
      await _montar(tester, pendientes: 2);

      await _tocar(tester, 'BOTON CAMBIAR');

      expect(find.textContaining('Se cerrará tu sesión en Chaski Sport.'), findsOneWidget);
      expect(find.textContaining('Tienes 2 operaciones sin enviar'), findsOneWidget);
    });

    testWidgets('Cancelar no hace nada: sigue la sesión y no se navega', (tester) async {
      final e = await _montar(tester, pendientes: 1);
      await _tocar(tester, 'BOTON CAMBIAR');

      await _tocar(tester, 'Cancelar');

      expect(_dialogo, findsNothing);
      expect(e.auth.estado, EstadoSesion.autenticado);
      expect(e.tokens.vecesLimpiado, 0);
      expect(find.text('PANTALLA ELIGE TIENDA'), findsNothing);
      expect(find.text('BOTON CAMBIAR'), findsOneWidget);
    });

    testWidgets('confirmar cierra la sesión y navega a /tienda', (tester) async {
      final e = await _montar(tester, pendientes: 0);
      await _tocar(tester, 'BOTON CAMBIAR');

      await tester.tap(find.widgetWithText(TextButton, 'Cambiar de tienda'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));

      expect(_dialogo, findsNothing);
      expect(e.auth.estado, EstadoSesion.noAutenticado);
      expect(e.tokens.vecesLimpiado, 1);
      expect(e.tokens.accessToken, isNull);
      expect(find.text('PANTALLA ELIGE TIENDA'), findsOneWidget);
    });

    testWidgets('cambiar de tienda NO borra la tienda guardada (eso lo hace elegir otra)', (tester) async {
      final e = await _montar(tester, pendientes: 0);
      await _tocar(tester, 'BOTON CAMBIAR');
      await tester.tap(find.widgetWithText(TextButton, 'Cambiar de tienda'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));

      expect(e.contenedor.read(tiendaActualProvider), _tienda);
    });
  });
}
