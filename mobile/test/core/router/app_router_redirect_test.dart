import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/core/network/providers.dart';
import 'package:mobile/core/router/app_router.dart';
import 'package:mobile/core/sesion/sesion_storage.dart';
import 'package:mobile/features/auth/models/usuario.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/auth/state/auth_state.dart';
import 'package:mobile/features/tienda/data/tienda_repository.dart';
import 'package:mobile/features/tienda/models/tienda.dart';
import 'package:mobile/features/tienda/state/tienda_controller.dart';

import '../../helpers/api_client_falso.dart';
import '../../helpers/sesion_storage_falso.dart';
import '../../helpers/token_storage_falso.dart';

/// Un [AuthController] que arranca directamente en el estado dado, sin pasar por `restaurarSesion` (que iría a la red).
/// `logout` es el real: limpia los tokens del [TokenStorageFalso] y deja la sesión en `noAutenticado`.
class AuthControllerFalso extends AuthController {
  AuthControllerFalso(super.ref, AuthState inicial) {
    state = inicial;
  }
}

const _tienda = Tienda(codigo: 'chaski', nombre: 'Chaski Sport');

const _usuario = Usuario(
  id: 1,
  nombre: 'Ana',
  apellido: 'Rojas',
  email: 'ana@example.com',
  telefono: null,
  activo: true,
  roles: ['cliente'],
  permisos: [],
  empresaCodigo: 'chaski',
);

const _noAutenticado = AuthState(estado: EstadoSesion.noAutenticado);
const _autenticado = AuthState(estado: EstadoSesion.autenticado, usuario: _usuario);

/// El personal: el modo vendedor sale del permiso `ventas.presencial`, no del nombre del rol.
const _cajero = Usuario(
  id: 2,
  nombre: 'Beto',
  apellido: 'Quispe',
  email: 'beto@example.com',
  telefono: null,
  activo: true,
  roles: ['cajero'],
  permisos: ['ventas.presencial'],
  empresaCodigo: 'chaski',
);
const _vendedor = AuthState(estado: EstadoSesion.autenticado, usuario: _cajero);
const _vendedorSinVerificar = AuthState(estado: EstadoSesion.autenticado, usuario: _cajero, verificada: false);

/// La sesión del personal que venció: el router lo manda a su acceso, no al login de clientes.
const _vendedorVencido = AuthState(
  estado: EstadoSesion.noAutenticado,
  motivoCierre: MotivoCierre.vencida,
  modoPrevio: ModoApp.vendedor,
);
const _vendedorSalio = AuthState(
  estado: EstadoSesion.noAutenticado,
  motivoCierre: MotivoCierre.voluntario,
  modoPrevio: ModoApp.vendedor,
);
const _clienteVencido = AuthState(
  estado: EstadoSesion.noAutenticado,
  motivoCierre: MotivoCierre.vencida,
  modoPrevio: ModoApp.cliente,
);

/// Un almacenamiento cuya lectura de la tienda no termina hasta que se abre la puerta: simula "todavía leyendo el
/// dispositivo", es decir, el estado `cargada == false` del controlador de tienda.
class _SesionStorageLento extends SesionStorageFalso {
  final puerta = Completer<void>();

  @override
  Future<Tienda?> leerTienda() async {
    await puerta.future;
    return super.leerTienda();
  }
}

/// Monta la aplicación con el `routerProvider` REAL. Las pantallas reales se construyen, así que se sobreescribe lo
/// mínimo para que ninguna toque la red:
///  - `apiClientProvider` con un [ApiClientFalso] vacío (toda llamada sin respuesta preparada falla con un StateError que
///    las pantallas ya tratan como error de carga);
///  - `tiendaRepositoryProvider` con ese mismo cliente y una lista de tiendas vacía para "Elige tu tienda".
/// No se prueba aquí lo que muestran las pantallas, solo adónde lleva el redirect.
class _Escenario {
  _Escenario(this.contenedor, this.router);

  final ProviderContainer contenedor;
  final GoRouter router;

  String get ubicacion => router.routerDelegate.currentConfiguration.uri.toString();
}

Future<_Escenario> _montar(
  WidgetTester tester, {
  Tienda? tienda,
  AuthState auth = _noAutenticado,
  SesionStorage? storage,
  bool esperarTienda = true,
}) async {
  final api = ApiClientFalso()..responder('GET', '/public/tiendas', []);
  final contenedor = ProviderContainer(
    overrides: [
      sesionStorageProvider.overrideWithValue(storage ?? SesionStorageFalso(tienda: tienda)),
      tokenStorageProvider.overrideWithValue(TokenStorageFalso()),
      authControllerProvider.overrideWith((ref) => AuthControllerFalso(ref, auth)),
      apiClientProvider.overrideWithValue(api),
      tiendaRepositoryProvider.overrideWithValue(TiendaRepository(api)),
    ],
  );
  addTearDown(contenedor.dispose);

  // Se lee la tienda guardada ANTES de montar la app: así el redirect sale del splash sin construirlo (el splash tiene
  // un Timer de 3 s).
  if (esperarTienda) await contenedor.read(tiendaControllerProvider.notifier).cargadaFuture;

  final router = contenedor.read(routerProvider);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: contenedor,
      child: MaterialApp.router(routerConfig: router),
    ),
  );
  await _asentar(tester);
  return _Escenario(contenedor, router);
}

/// Varios cuadros seguidos. No se usa `pumpAndSettle`: hay indicadores de carga que animan para siempre.
Future<void> _asentar(WidgetTester tester) async {
  for (var i = 0; i < 6; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

Future<String> _ir(WidgetTester tester, _Escenario e, String destino) async {
  e.router.go(destino);
  await _asentar(tester);
  return e.ubicacion;
}

void main() {
  group('sin tienda elegida y sin sesión', () {
    testWidgets('/home lleva a /tienda', (tester) async {
      final e = await _montar(tester);
      expect(await _ir(tester, e, '/home'), '/tienda');
    });

    testWidgets('al arrancar (splash) lleva a /tienda', (tester) async {
      final e = await _montar(tester);
      expect(e.ubicacion, '/tienda');
      expect(find.text('Elige tu tienda'), findsWidgets);
    });

    testWidgets('/carrito lleva a /tienda (no a /login)', (tester) async {
      final e = await _montar(tester);
      expect(await _ir(tester, e, '/carrito'), '/tienda');
    });

    testWidgets('/producto/5 lleva a /tienda', (tester) async {
      final e = await _montar(tester);
      expect(await _ir(tester, e, '/producto/5'), '/tienda');
    });

    testWidgets('/login lleva a /tienda: primero se elige tienda', (tester) async {
      final e = await _montar(tester);
      expect(await _ir(tester, e, '/login'), '/tienda');
    });

    testWidgets('/tienda se queda', (tester) async {
      final e = await _montar(tester);
      expect(await _ir(tester, e, '/tienda'), '/tienda');
    });

    testWidgets('/t/abc se queda (entrada por enlace)', (tester) async {
      final e = await _montar(tester);
      expect(await _ir(tester, e, '/t/abc'), '/t/abc');
    });
  });

  group('con tienda elegida y sin sesión (invitado)', () {
    testWidgets('al arrancar (splash) lleva al catálogo', (tester) async {
      final e = await _montar(tester, tienda: _tienda);
      expect(e.ubicacion, '/home');
    });

    testWidgets('/home se queda', (tester) async {
      final e = await _montar(tester, tienda: _tienda);
      expect(await _ir(tester, e, '/home'), '/home');
    });

    testWidgets('/producto/5 se queda', (tester) async {
      final e = await _montar(tester, tienda: _tienda);
      expect(await _ir(tester, e, '/producto/5'), '/producto/5');
    });

    // /asistente también es pública para el invitado, pero su pantalla usa un WebView que no existe en `flutter test`
    // (WebViewPlatform.instance == null), así que no se puede montar aquí.

    testWidgets('/carrito lleva a /login?returnTo=%2Fcarrito', (tester) async {
      final e = await _montar(tester, tienda: _tienda);
      expect(await _ir(tester, e, '/carrito'), '/login?returnTo=%2Fcarrito');
    });

    testWidgets('/compras/3 lleva a /login conservando el destino', (tester) async {
      final e = await _montar(tester, tienda: _tienda);
      expect(await _ir(tester, e, '/compras/3'), '/login?returnTo=%2Fcompras%2F3');
    });

    testWidgets('/registro se queda', (tester) async {
      final e = await _montar(tester, tienda: _tienda);
      expect(await _ir(tester, e, '/registro'), '/registro');
    });

    testWidgets('/tienda se queda', (tester) async {
      final e = await _montar(tester, tienda: _tienda);
      expect(await _ir(tester, e, '/tienda'), '/tienda');
    });

    testWidgets('/t/abc se queda', (tester) async {
      final e = await _montar(tester, tienda: _tienda);
      expect(await _ir(tester, e, '/t/abc'), '/t/abc');
    });
  });

  group('con tienda elegida y con sesión', () {
    testWidgets('al arrancar (splash) lleva al catálogo', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _autenticado);
      expect(e.ubicacion, '/home');
    });

    testWidgets('/login lleva a /home', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _autenticado);
      expect(await _ir(tester, e, '/login'), '/home');
    });

    testWidgets('/login?returnTo=%2Fcarrito lleva a /carrito', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _autenticado);
      expect(await _ir(tester, e, '/login?returnTo=%2Fcarrito'), '/carrito');
    });

    testWidgets('/registro lleva a /home', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _autenticado);
      expect(await _ir(tester, e, '/registro'), '/home');
    });

    testWidgets('/carrito se queda', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _autenticado);
      expect(await _ir(tester, e, '/carrito'), '/carrito');
    });

    testWidgets('/tienda se queda (cambiar de tienda está permitido)', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _autenticado);
      expect(await _ir(tester, e, '/tienda'), '/tienda');
    });

    testWidgets('/t/abc se queda', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _autenticado);
      expect(await _ir(tester, e, '/t/abc'), '/t/abc');
    });
  });

  group('reaccionar a cambios de estado', () {
    testWidgets('al cerrar la sesión en una ruta protegida, el router manda a /login con returnTo', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _autenticado);
      await _ir(tester, e, '/carrito');
      expect(e.ubicacion, '/carrito');

      await e.contenedor.read(authControllerProvider.notifier).logout();
      await _asentar(tester);

      expect(e.ubicacion, '/login?returnTo=%2Fcarrito');
    });

    testWidgets('al olvidar la tienda siendo invitado, el router manda a /tienda', (tester) async {
      final e = await _montar(tester, tienda: _tienda);
      expect(await _ir(tester, e, '/home'), '/home');

      await e.contenedor.read(tiendaControllerProvider.notifier).olvidar();
      await _asentar(tester);

      expect(e.ubicacion, '/tienda');
    });
  });

  group('tienda sin leer todavía', () {
    for (final destino in ['/home', '/carrito', '/tienda', '/login', '/t/abc']) {
      testWidgets('$destino lleva a /splash', (tester) async {
        final lento = _SesionStorageLento();
        addTearDown(() {
          if (!lento.puerta.isCompleted) lento.puerta.complete();
        });
        final e = await _montar(tester, storage: lento, esperarTienda: false, auth: _noAutenticado);
        expect(e.ubicacion, '/splash');

        expect(await _ir(tester, e, destino), '/splash');
        // El splash espera 3 s antes de seguir: se deja correr el reloj para no dejar el Timer pendiente.
        await tester.pump(const Duration(seconds: 3));
      });
    }

    testWidgets('al terminar de leer la tienda sale del splash', (tester) async {
      final lento = _SesionStorageLento()..tienda = _tienda;
      final e = await _montar(tester, storage: lento, esperarTienda: false, auth: _noAutenticado);
      expect(e.ubicacion, '/splash');

      lento.puerta.complete();
      await e.contenedor.read(tiendaControllerProvider.notifier).cargadaFuture;
      await _asentar(tester);
      await tester.pump(const Duration(seconds: 3));
      await _asentar(tester);

      expect(e.ubicacion, '/home');
    });
  });

  group('área del personal - sin sesión', () {
    testWidgets('/vendedor lleva a /vendedor/acceso', (tester) async {
      final e = await _montar(tester, tienda: _tienda);
      expect(await _ir(tester, e, '/vendedor'), '/vendedor/acceso');
    });

    testWidgets('/vendedor/acceso se queda', (tester) async {
      final e = await _montar(tester, tienda: _tienda);
      expect(await _ir(tester, e, '/vendedor/acceso'), '/vendedor/acceso');
    });

    testWidgets('/vendedor/otra-cosa también lleva a /vendedor/acceso', (tester) async {
      final e = await _montar(tester, tienda: _tienda);
      expect(await _ir(tester, e, '/vendedor/otra-cosa'), '/vendedor/acceso');
    });

    testWidgets('sin tienda elegida /vendedor lleva a /tienda (primero se elige tienda)', (tester) async {
      final e = await _montar(tester);
      expect(await _ir(tester, e, '/vendedor'), '/tienda');
    });

    testWidgets('/home y /login siguen como siempre para el invitado', (tester) async {
      final e = await _montar(tester, tienda: _tienda);
      expect(await _ir(tester, e, '/home'), '/home');
      expect(await _ir(tester, e, '/carrito'), '/login?returnTo=%2Fcarrito');
    });
  });

  group('área del personal - sesión vencida', () {
    testWidgets('/carrito lleva a /vendedor/acceso', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedorVencido);
      expect(await _ir(tester, e, '/carrito'), '/vendedor/acceso');
    });

    testWidgets('/home lleva a /vendedor/acceso', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedorVencido);
      expect(await _ir(tester, e, '/home'), '/vendedor/acceso');
    });

    testWidgets('/producto/5 lleva a /vendedor/acceso', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedorVencido);
      expect(await _ir(tester, e, '/producto/5'), '/vendedor/acceso');
    });

    testWidgets('/vendedor lleva a /vendedor/acceso', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedorVencido);
      expect(await _ir(tester, e, '/vendedor'), '/vendedor/acceso');
    });

    testWidgets('/tienda se queda (puede elegir otra tienda)', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedorVencido);
      expect(await _ir(tester, e, '/tienda'), '/tienda');
    });

    testWidgets('/t/abc se queda', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedorVencido);
      expect(await _ir(tester, e, '/t/abc'), '/t/abc');
    });

    testWidgets('/vendedor/acceso se queda', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedorVencido);
      expect(await _ir(tester, e, '/vendedor/acceso'), '/vendedor/acceso');
    });

    testWidgets('/login se queda (el cliente puede entrar por su acceso)', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedorVencido);
      expect(await _ir(tester, e, '/login'), '/login');
    });

    testWidgets('al arrancar (splash) con la sesión vencida termina en /vendedor/acceso', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedorVencido);
      expect(e.ubicacion, '/vendedor/acceso');
    });

    testWidgets('un motivo voluntario NO redirige: /home se queda', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedorSalio);
      expect(await _ir(tester, e, '/home'), '/home');
    });

    testWidgets('un motivo voluntario: /carrito lleva al login de clientes', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedorSalio);
      expect(await _ir(tester, e, '/carrito'), '/login?returnTo=%2Fcarrito');
    });

    testWidgets('un cliente cuya sesión venció sigue yendo al login de clientes', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _clienteVencido);
      expect(await _ir(tester, e, '/carrito'), '/login?returnTo=%2Fcarrito');
    });

    testWidgets('un cliente cuya sesión venció puede ver /home', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _clienteVencido);
      expect(await _ir(tester, e, '/home'), '/home');
    });

    testWidgets('olvidar el motivo de cierre libera a la persona del acceso del personal', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedorVencido);
      expect(await _ir(tester, e, '/home'), '/vendedor/acceso');

      e.contenedor.read(authControllerProvider.notifier).olvidarMotivoCierre();
      await _asentar(tester);

      expect(await _ir(tester, e, '/home'), '/home');
      expect(await _ir(tester, e, '/carrito'), '/login?returnTo=%2Fcarrito');
    });
  });

  group('área del personal - vendedor autenticado', () {
    testWidgets('al arrancar (splash) lleva a /vendedor', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedor);
      expect(e.ubicacion, '/vendedor');
    });

    testWidgets('/home lleva a /vendedor', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedor);
      expect(await _ir(tester, e, '/home'), '/vendedor');
    });

    testWidgets('/carrito lleva a /vendedor', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedor);
      expect(await _ir(tester, e, '/carrito'), '/vendedor');
    });

    testWidgets('/producto/5 lleva a /vendedor', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedor);
      expect(await _ir(tester, e, '/producto/5'), '/vendedor');
    });

    testWidgets('/login lleva a /vendedor', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedor);
      expect(await _ir(tester, e, '/login'), '/vendedor');
    });

    testWidgets('/login con returnTo también lleva a /vendedor (ignora el destino de cliente)', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedor);
      expect(await _ir(tester, e, '/login?returnTo=%2Fcarrito'), '/vendedor');
    });

    testWidgets('/registro lleva a /vendedor', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedor);
      expect(await _ir(tester, e, '/registro'), '/vendedor');
    });

    testWidgets('/vendedor/acceso lleva a /vendedor', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedor);
      expect(await _ir(tester, e, '/vendedor/acceso'), '/vendedor');
    });

    testWidgets('/vendedor se queda', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedor);
      expect(await _ir(tester, e, '/vendedor'), '/vendedor');
    });

    testWidgets('/tienda se queda', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedor);
      expect(await _ir(tester, e, '/tienda'), '/tienda');
    });

    testWidgets('/t/abc se queda', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedor);
      expect(await _ir(tester, e, '/t/abc'), '/t/abc');
    });

    testWidgets('con la sesión sin verificar (abierta sin red) también va a /vendedor', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedorSinVerificar);
      expect(e.ubicacion, '/vendedor');
      expect(await _ir(tester, e, '/home'), '/vendedor');
    });

    testWidgets('un encargado (reservas.gestionar_sucursal) también va a /vendedor', (tester) async {
      const encargado = Usuario(
        id: 5,
        nombre: 'Eva',
        apellido: 'Mamani',
        email: 'eva@example.com',
        telefono: null,
        activo: true,
        roles: ['encargado_sucursal'],
        permisos: ['reservas.gestionar_sucursal'],
        empresaCodigo: 'chaski',
      );
      final e = await _montar(
        tester,
        tienda: _tienda,
        auth: const AuthState(estado: EstadoSesion.autenticado, usuario: encargado),
      );
      expect(await _ir(tester, e, '/home'), '/vendedor');
    });
  });

  group('área del personal - cliente autenticado', () {
    testWidgets('/vendedor lleva a /home', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _autenticado);
      expect(await _ir(tester, e, '/vendedor'), '/home');
    });

    testWidgets('/vendedor/acceso lleva a /home', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _autenticado);
      expect(await _ir(tester, e, '/vendedor/acceso'), '/home');
    });

    testWidgets('al arrancar (splash) lleva a /home', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _autenticado);
      expect(e.ubicacion, '/home');
    });

    testWidgets('un cliente que además tiene permisos de venta sigue siendo cliente: /vendedor lleva a /home', (
      tester,
    ) async {
      const mixto = Usuario(
        id: 6,
        nombre: 'Mixto',
        apellido: 'Cuenta',
        email: 'mixto@example.com',
        telefono: null,
        activo: true,
        roles: ['cajero', 'cliente'],
        permisos: ['ventas.presencial'],
        empresaCodigo: 'chaski',
      );
      final e = await _montar(
        tester,
        tienda: _tienda,
        auth: const AuthState(estado: EstadoSesion.autenticado, usuario: mixto),
      );
      expect(e.ubicacion, '/home');
      expect(await _ir(tester, e, '/vendedor'), '/home');
    });
  });

  group('área del personal - reaccionar a cambios de estado', () {
    testWidgets('al vencer la sesión del vendedor en /vendedor, el router manda a /vendedor/acceso', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedor);
      expect(e.ubicacion, '/vendedor');

      await e.contenedor.read(authControllerProvider.notifier).logout(motivo: MotivoCierre.vencida);
      await _asentar(tester);

      expect(e.ubicacion, '/vendedor/acceso');
    });

    testWidgets('al cerrar sesión el vendedor voluntariamente, también termina en /vendedor/acceso', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedor);

      await e.contenedor.read(authControllerProvider.notifier).logout();
      await _asentar(tester);

      expect(e.ubicacion, '/vendedor/acceso');
    });

    testWidgets('al cerrar sesión, el estado deja motivo y modo previo del vendedor', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: _vendedor);

      await e.contenedor.read(authControllerProvider.notifier).logout(motivo: MotivoCierre.vencida);
      await _asentar(tester);

      final estado = e.contenedor.read(authControllerProvider);
      expect(estado.motivoCierre, MotivoCierre.vencida);
      expect(estado.modoPrevio, ModoApp.vendedor);
    });
  });

  group('sesión en curso', () {
    testWidgets('mientras la sesión se restaura (inicial) todo va a /splash', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: const AuthState.inicial());
      expect(e.ubicacion, '/splash');
      expect(await _ir(tester, e, '/home'), '/splash');
      await tester.pump(const Duration(seconds: 3));
    });

    testWidgets('con el login en curso (cargando) no se redirige', (tester) async {
      final e = await _montar(tester, tienda: _tienda, auth: const AuthState(estado: EstadoSesion.cargando));
      // Con `cargando` no se redirige ni siquiera desde el splash: es la pantalla la que muestra su propio indicador.
      expect(e.ubicacion, '/splash');
      expect(await _ir(tester, e, '/login'), '/login');
      expect(await _ir(tester, e, '/carrito'), '/carrito');
      // El splash de arriba ya se desmontó, pero su Timer de 3 s sigue vivo: se deja correr el reloj.
      await tester.pump(const Duration(seconds: 3));
    });
  });
}
