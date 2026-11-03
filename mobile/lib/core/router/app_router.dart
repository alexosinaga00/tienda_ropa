import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../theme/app_theme.dart';
import '../../features/asistente/presentation/asistente_screen.dart';
import '../../features/auth/presentation/login_screen.dart';
import '../../features/auth/presentation/recuperar_screen.dart';
import '../../features/auth/presentation/registro_screen.dart';
import '../../features/auth/presentation/restablecer_screen.dart';
import '../../features/auth/state/auth_controller.dart';
import '../../features/auth/state/auth_state.dart';
import '../../features/catalogo/presentation/catalogo_screen.dart';
import '../../features/catalogo/presentation/detalle_screen.dart';
import '../../features/compras/presentation/carrito_screen.dart';
import '../../features/compras/presentation/compra_detalle_screen.dart';
import '../../features/compras/presentation/direccion_form_screen.dart';
import '../../features/compras/presentation/entrega_screen.dart';
import '../../features/compras/presentation/estado_pago_screen.dart';
import '../../features/compras/presentation/mis_compras_screen.dart';
import '../../features/compras/presentation/pago_screen.dart';
import '../../features/favoritos/presentation/favoritos_screen.dart';
import '../../features/notificaciones/presentation/notificaciones_screen.dart';
import '../../features/probador/presentation/probador_screen.dart';
import '../../features/reservas/presentation/confirmar_reserva_screen.dart';
import '../../features/reservas/presentation/mis_reservas_screen.dart';
import '../../features/reservas/presentation/reserva_detalle_screen.dart';
import '../../features/splash/presentation/splash_screen.dart';
import '../../features/auth/models/usuario.dart';
import '../../features/vendedor/presentation/acceso_vendedor_screen.dart';
import '../../features/vendedor/presentation/catalogo_local_screen.dart';
import '../../features/vendedor/presentation/detalle_local_screen.dart';
import '../../features/vendedor/presentation/nueva_reserva_screen.dart';
import '../../features/vendedor/presentation/nueva_venta_screen.dart';
import '../../features/vendedor/presentation/operaciones_pendientes_screen.dart';
import '../../features/vendedor/presentation/resultado_sync_screen.dart';
import '../../features/vendedor/presentation/inicio_vendedor_screen.dart';
import '../../features/tienda/presentation/elige_tienda_screen.dart';
import '../../features/tienda/presentation/entrar_a_tienda_screen.dart';
import '../../features/tienda/state/tienda_controller.dart';
import 'retroceso.dart';

class _RefrescoDelRouter extends ChangeNotifier {
  _RefrescoDelRouter(Ref ref) {
    ref.listen<AuthState>(authControllerProvider, (_, _) => notifyListeners());
    ref.listen<TiendaState>(tiendaControllerProvider, (_, _) => notifyListeners());
  }
}

final _refrescoDelRouterProvider = Provider<_RefrescoDelRouter>((ref) => _RefrescoDelRouter(ref));

bool _esRutaAuth(String ruta) =>
    ruta == '/login' ||
    ruta == '/registro' ||
    ruta == '/recuperar' ||
    ruta == '/restablecer' ||
    ruta == '/vendedor/acceso';

/// El área del personal (`/vendedor`, `/vendedor/acceso`).
bool _esRutaDeVendedor(String ruta) => ruta == '/vendedor' || ruta.startsWith('/vendedor/');

/// Elegir tienda y entrar por el enlace `/t/<codigo>` están siempre permitidos, con o sin sesión.
bool _esRutaDeTienda(String ruta) => ruta == '/tienda' || ruta.startsWith('/t/');

// El catálogo, el detalle de producto y el asistente son públicos (igual que
// en el web, que solo protege carrito/checkout/mis-compras/reservas con authGuard).
// Todo lo demás cae en la rama "protegida" del redirect de abajo.
bool _esRutaPublicaParaInvitado(String ruta) => ruta == '/home' || ruta == '/asistente' || ruta.startsWith('/producto/');

/// Un path parameter que debería ser numérico (id de producto/reserva/pago/
/// compra) puede llegar mal formado desde un deep link, notificación push o
/// link compartido a mano -- `int.tryParse` en vez de `int.parse` evita que
/// eso tire una FormatException sin capturar durante el build de la ruta.
int? _parseId(String? valor) => valor == null ? null : int.tryParse(valor);

/// Se muestra en vez de crashear cuando un path parameter no es válido, o
/// cuando GoRouter no reconoce la ruta pedida (deep link roto/viejo).
class _RutaInvalidaScreen extends StatelessWidget {
  const _RutaInvalidaScreen({this.mensaje = 'No encontramos lo que buscabas.'});

  final String mensaje;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.fondo,
      appBar: AppBar(title: const Text('No encontrado')),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.search_off, size: 48, color: AppColors.textoTenue),
              const SizedBox(height: AppSpacing.md),
              Text(mensaje, textAlign: TextAlign.center, style: const TextStyle(color: AppColors.textoTenue)),
              const SizedBox(height: AppSpacing.md),
              FilledButton(onPressed: () => context.go('/home'), child: const Text('Volver al inicio')),
            ],
          ),
        ),
      ),
    );
  }
}

/// El botón "atrás" del sistema: si no hay historial sube a la pantalla padre en vez de cerrar la app (ver `retroceso.dart`).
final retrocesoProvider = Provider<BackButtonDispatcher>((ref) => RetrocesoDelRouter(ref.watch(routerProvider)));

final routerProvider = Provider<GoRouter>((ref) {
  final refresco = ref.watch(_refrescoDelRouterProvider);

  return GoRouter(
    initialLocation: '/splash',
    refreshListenable: refresco,
    errorBuilder: (context, state) => const _RutaInvalidaScreen(mensaje: 'Esa página no existe.'),
    redirect: (context, state) {
      final authState = ref.read(authControllerProvider);
      final tiendaState = ref.read(tiendaControllerProvider);
      final ruta = state.matchedLocation;
      final esAuth = _esRutaAuth(ruta);
      final esSplash = ruta == '/splash';
      final esTienda = _esRutaDeTienda(ruta);
      final haySesionTienda = tiendaState.tienda != null;

      // Hasta leer la tienda guardada no se sabe adónde ir.
      if (!tiendaState.cargada) return esSplash ? null : '/splash';

      switch (authState.estado) {
        case EstadoSesion.inicial:
          return esSplash ? null : '/splash';
        case EstadoSesion.cargando:
          // No redirigir mientras carga: login()/registrar() también ponen
          // este estado al tocar "Ingresar" desde /login, y si acá se
          // forzara volver a /splash, su initState llamaría restaurarSesion()
          // de nuevo en paralelo con el login en curso -- una carrera que
          // podía pisar el resultado real del login. Cada pantalla (splash,
          // login, registro) ya muestra su propio indicador de carga.
          return null;
        case EstadoSesion.noAutenticado:
          // Sin tienda elegida lo único posible es elegirla.
          if (esSplash) return haySesionTienda ? '/home' : '/tienda';
          if (esTienda) return null;
          // El personal escribe su empresa al entrar: no necesita haber elegido tienda antes.
          if (ruta == '/vendedor/acceso') return null;
          if (!haySesionTienda) return '/tienda';
          if (esAuth) return null;
          // El área del personal exige entrar por su pantalla de acceso.
          if (_esRutaDeVendedor(ruta)) return '/vendedor/acceso';
          // Al personal cuya sesión venció se le manda a su acceso (para reenviar lo pendiente), no al login de clientes.
          if (authState.motivoCierre == MotivoCierre.vencida && authState.modoPrevio == ModoApp.vendedor) {
            return '/vendedor/acceso';
          }
          if (_esRutaPublicaParaInvitado(ruta)) return null;
          return '/login?returnTo=${Uri.encodeComponent(state.uri.toString())}';
        case EstadoSesion.autenticado:
          final esVendedor = authState.usuario?.modo == ModoApp.vendedor;
          if (esSplash) return esVendedor ? '/vendedor' : '/home';
          if (esTienda) return null;
          // El personal vive en su área; el cliente no puede entrar a ella.
          if (esVendedor) return _esRutaDeVendedor(ruta) && ruta != '/vendedor/acceso' ? null : '/vendedor';
          if (_esRutaDeVendedor(ruta)) return '/home';
          if (esAuth) {
            final returnTo = state.uri.queryParameters['returnTo'];
            return (returnTo != null && returnTo.isNotEmpty) ? returnTo : '/home';
          }
          return null;
      }
    },
    routes: [
      GoRoute(path: '/splash', builder: (context, state) => const SplashScreen()),
      GoRoute(path: '/tienda', builder: (context, state) => const EligeTiendaScreen()),
      GoRoute(
        path: '/t/:codigo',
        builder: (context, state) => EntrarATiendaScreen(codigo: state.pathParameters['codigo'] ?? ''),
      ),
      GoRoute(path: '/vendedor/acceso', builder: (context, state) => const AccesoVendedorScreen()),
      GoRoute(path: '/vendedor', builder: (context, state) => const InicioVendedorScreen()),
      GoRoute(path: '/vendedor/catalogo', builder: (context, state) => const CatalogoLocalScreen()),
      GoRoute(path: '/vendedor/venta/nueva', builder: (context, state) => const NuevaVentaScreen()),
      GoRoute(path: '/vendedor/reserva/nueva', builder: (context, state) => const NuevaReservaScreen()),
      GoRoute(path: '/vendedor/operaciones', builder: (context, state) => const OperacionesPendientesScreen()),
      GoRoute(
        path: '/vendedor/operaciones/:operacionId',
        builder: (context, state) => ResultadoSyncScreen(
          operacionId: (state.pathParameters['operacionId'] ?? '').toLowerCase(),
          esNueva: state.uri.queryParameters['nuevo'] == '1',
        ),
      ),
      GoRoute(
        path: '/vendedor/producto/:id',
        builder: (context, state) {
          final id = _parseId(state.pathParameters['id']);
          if (id == null) return const _RutaInvalidaScreen(mensaje: 'Ese producto no existe.');
          return DetalleLocalScreen(productoId: id);
        },
      ),
      GoRoute(path: '/login', builder: (context, state) => const LoginScreen()),
      GoRoute(path: '/registro', builder: (context, state) => const RegistroScreen()),
      GoRoute(path: '/recuperar', builder: (context, state) => const RecuperarScreen()),
      GoRoute(
        path: '/restablecer',
        builder: (context, state) => RestablecerScreen(token: state.uri.queryParameters['token']),
      ),
      GoRoute(path: '/home', builder: (context, state) => const CatalogoScreen()),
      GoRoute(
        path: '/producto/:id',
        builder: (context, state) {
          final id = _parseId(state.pathParameters['id']);
          if (id == null) return const _RutaInvalidaScreen(mensaje: 'Ese producto no existe.');
          return DetalleScreen(productoId: id);
        },
      ),
      GoRoute(path: '/favoritos', builder: (context, state) => const FavoritosScreen()),
      GoRoute(path: '/notificaciones', builder: (context, state) => const NotificacionesScreen()),
      GoRoute(path: '/asistente', builder: (context, state) => const AsistenteScreen()),
      GoRoute(
        path: '/probador',
        // `?variante=ID`: la prenda elegida en el detalle o en el carrito; sin él (ícono del catálogo) abre como siempre.
        builder: (context, state) => ProbadorScreen(varianteInicial: _parseId(state.uri.queryParameters['variante'])),
      ),
      GoRoute(path: '/reserva/confirmar', builder: (context, state) => const ConfirmarReservaScreen()),
      GoRoute(path: '/reservas', builder: (context, state) => const MisReservasScreen()),
      GoRoute(
        path: '/reserva/:id',
        builder: (context, state) {
          final id = _parseId(state.pathParameters['id']);
          if (id == null) return const _RutaInvalidaScreen(mensaje: 'Esa reserva no existe.');
          return ReservaDetalleScreen(reservaId: id);
        },
      ),
      GoRoute(path: '/carrito', builder: (context, state) => const CarritoScreen()),
      GoRoute(path: '/checkout/entrega', builder: (context, state) => const EntregaScreen()),
      GoRoute(path: '/checkout/direccion/nueva', builder: (context, state) => const DireccionFormScreen()),
      GoRoute(path: '/checkout/pago', builder: (context, state) => const PagoScreen()),
      GoRoute(
        path: '/checkout/estado/:pagoId',
        builder: (context, state) {
          final id = _parseId(state.pathParameters['pagoId']);
          if (id == null) return const _RutaInvalidaScreen(mensaje: 'Ese pago no existe.');
          return EstadoPagoScreen(pagoId: id);
        },
      ),
      GoRoute(path: '/compras', builder: (context, state) => const MisComprasScreen()),
      GoRoute(
        path: '/compras/:id',
        builder: (context, state) {
          final id = _parseId(state.pathParameters['id']);
          if (id == null) return const _RutaInvalidaScreen(mensaje: 'Esa compra no existe.');
          return CompraDetalleScreen(ventaId: id);
        },
      ),
    ],
  );
});
