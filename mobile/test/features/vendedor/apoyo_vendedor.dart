import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/core/conectividad/conectividad_service.dart';
import 'package:mobile/core/sesion/contador_pendientes.dart';
import 'package:mobile/core/utils/reloj.dart';
import 'package:mobile/features/vendedor/data/descarga_repository.dart';
import 'package:mobile/features/vendedor/data/politica_limpieza_local.dart';
import 'package:mobile/features/vendedor/data/politica_vigencia.dart';
import 'package:mobile/features/vendedor/state/catalogo_local_providers.dart';
import 'package:mobile/features/vendedor/state/pendientes_providers.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:mobile/core/network/providers.dart';
import 'package:mobile/features/auth/data/auth_repository.dart';
import 'package:mobile/features/auth/models/usuario.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/auth/state/auth_state.dart';
import 'package:mobile/features/tienda/data/tienda_repository.dart';
import 'package:mobile/features/tienda/models/tienda.dart';
import 'package:mobile/features/tienda/state/tienda_controller.dart';
import 'package:mobile/features/vendedor/presentation/acceso_vendedor_screen.dart';
import 'package:mobile/features/vendedor/presentation/inicio_vendedor_screen.dart';

import '../../helpers/api_client_falso.dart';
import '../../helpers/base_local_falsa.dart';
import '../../helpers/conectividad_falsa.dart';
import '../../helpers/servicio_descarga_falso.dart';
import '../../helpers/sesion_storage_falso.dart';
import '../../helpers/token_storage_falso.dart';

const tiendaChaski = Tienda(codigo: 'chaski', nombre: 'Chaski Sport');

/// Una cuenta de la empresa `chaski` con los roles y permisos dados. Por defecto, un cajero (puede vender en caja).
Usuario usuarioDePrueba({
  List<String> roles = const ['cajero'],
  List<String> permisos = const ['ventas.presencial'],
  String nombre = 'Marta',
  String? empresaCodigo = 'chaski',
  String? empresaNombre = 'Chaski Sport',
}) {
  return Usuario(
    id: 7,
    nombre: nombre,
    apellido: 'Quispe',
    email: 'marta@chaski.bo',
    telefono: null,
    activo: true,
    roles: roles,
    permisos: permisos,
    empresaId: 3,
    empresaCodigo: empresaCodigo,
    empresaNombre: empresaNombre,
  );
}

DioException errorDio(DioExceptionType tipo, {int? estado, Object? datos}) {
  final opciones = RequestOptions(path: '/auth/login');
  return DioException(
    requestOptions: opciones,
    type: tipo,
    response: estado == null ? null : Response(requestOptions: opciones, statusCode: estado, data: datos),
  );
}

/// Una llamada a `login` que recibió el [RepositorioAuthFalso].
class LlamadaLogin {
  const LlamadaLogin({required this.email, required this.password, this.empresa});

  final String email;
  final String password;
  final String? empresa;
}

/// Repositorio de autenticación sin red: el login guarda tokens falsos (o falla con [errorLogin]) y `/auth/yo` devuelve
/// [usuario]. Con [puerta] el login no responde hasta que se complete (para ver el estado "cargando").
class RepositorioAuthFalso extends AuthRepository {
  RepositorioAuthFalso(this.tokens, {this.usuario, this.errorLogin, this.puerta}) : super(dio: Dio(), tokenStorage: tokens);

  final TokenStorageFalso tokens;
  final Usuario? usuario;
  final Object? errorLogin;
  final Completer<void>? puerta;
  final List<LlamadaLogin> logins = [];

  @override
  Future<void> login({required String email, required String password, String? empresa}) async {
    logins.add(LlamadaLogin(email: email, password: password, empresa: empresa));
    await puerta?.future;
    if (errorLogin != null) throw errorLogin!;
    await tokens.guardar(accessToken: 'ACCESS', refreshToken: 'REFRESH');
  }

  @override
  Future<Usuario> obtenerUsuarioActual() async => usuario ?? usuarioDePrueba();

  @override
  Future<void> logout() => tokens.limpiar();
}

/// Un [AuthController] real cuyo estado se fija en el constructor. Cuenta las llamadas a `verificarSesion` (que no consulta
/// nada) y a `olvidarMotivoCierre` (que sí hace lo suyo); `logout` es el real.
class AuthControllerFalso extends AuthController {
  AuthControllerFalso(super.ref, AuthState inicial) {
    state = inicial;
  }

  int verificaciones = 0;
  int olvidos = 0;

  @override
  Future<void> verificarSesion() async {
    verificaciones++;
  }

  @override
  void olvidarMotivoCierre() {
    olvidos++;
    super.olvidarMotivoCierre();
  }
}

/// Estado de una sesión abierta del personal.
AuthState sesionDePersonal({Usuario? usuario, bool verificada = true}) =>
    AuthState(estado: EstadoSesion.autenticado, usuario: usuario ?? usuarioDePrueba(), verificada: verificada);

/// Una sesión cerrada por vencimiento: el router mandaría a "Acceso del personal".
const sesionVencida = AuthState(
  estado: EstadoSesion.noAutenticado,
  motivoCierre: MotivoCierre.vencida,
  modoPrevio: ModoApp.vendedor,
);

class EscenarioVendedor {
  EscenarioVendedor({
    required this.router,
    required this.contenedor,
    required this.repo,
    required this.conectividad,
    required this.sesion,
    required this.tokens,
    required this.api,
    this.servicioDescarga,
    this.base,
  });

  final GoRouter router;
  final ProviderContainer contenedor;
  final RepositorioAuthFalso repo;
  final ConectividadFalsa conectividad;
  final SesionStorageFalso sesion;
  final TokenStorageFalso tokens;
  final ApiClientFalso api;

  /// La descarga del catálogo (doble sin red) y la base local en memoria que usa la pantalla.
  final ServicioDescargaFalso? servicioDescarga;
  final Database? base;

  /// La ruta que muestra el router ahora.
  String get ruta => router.routerDelegate.currentConfiguration.last.matchedLocation;

  AuthControllerFalso get authFalso => contenedor.read(authControllerProvider.notifier) as AuthControllerFalso;
  AuthState get auth => contenedor.read(authControllerProvider);
}

/// Monta las pantallas del personal en un router mínimo (`/vendedor/acceso`, `/vendedor`, `/home`, `/tienda`).
///
/// - [estadoAuth]: si se da, el controlador de sesión es un [AuthControllerFalso] con ese estado; si no, es el real
///   (para probar `loginPersonal` contra el [RepositorioAuthFalso]).
/// - [tienda]: la tienda guardada en el dispositivo (null = ninguna).
/// - [usuarioLogin], [errorLogin] y [puerta]: lo que responde el repositorio falso.
Future<EscenarioVendedor> abrirVendedor(
  WidgetTester tester, {
  String inicial = '/vendedor/acceso',
  AuthState? estadoAuth,
  Tienda? tienda = tiendaChaski,
  Usuario? usuarioLogin,
  Object? errorLogin,
  Completer<void>? puerta,
  bool enLinea = true,
  List<Override> overrides = const [],
  Database? base,
  ServicioDescargaFalso? servicioDescarga,
  Reloj? reloj,
}) async {
  tester.view.physicalSize = const Size(800, 1800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);

  final tokens = TokenStorageFalso();
  final sesion = SesionStorageFalso(tienda: tienda);
  final repo = RepositorioAuthFalso(tokens, usuario: usuarioLogin, errorLogin: errorLogin, puerta: puerta);
  final conectividad = ConectividadFalsa(enLinea: enLinea);
  addTearDown(conectividad.cerrar);
  // Sin red ni plugins: la base local es la REAL en memoria (vacía si no se da otra) y la descarga es un doble.
  final baseLocal = base ?? await _abrirBaseVacia(tester);
  final descarga = servicioDescarga ?? ServicioDescargaFalso();
  final api = ApiClientFalso()
    ..responder('GET', '/public/chaski/tienda', {'codigo': 'chaski', 'nombre': 'Chaski Sport', 'disponible': true})
    ..responder('GET', '/public/andina/tienda', {'codigo': 'andina', 'nombre': 'Boutique Andina', 'disponible': true});

  final router = GoRouter(
    initialLocation: inicial,
    routes: [
      GoRoute(path: '/vendedor/acceso', builder: (context, state) => const AccesoVendedorScreen()),
      GoRoute(path: '/vendedor', builder: (context, state) => const InicioVendedorScreen()),
      GoRoute(path: '/home', builder: (context, state) => const Scaffold(body: Text('PANTALLA HOME'))),
      GoRoute(path: '/tienda', builder: (context, state) => const Scaffold(body: Text('PANTALLA TIENDAS'))),
      GoRoute(path: '/vendedor/catalogo', builder: (context, state) => const Scaffold(body: Text('PANTALLA CATALOGO'))),
      GoRoute(path: '/vendedor/venta/nueva', builder: (context, state) => const Scaffold(body: Text('PANTALLA NUEVA VENTA'))),
      GoRoute(path: '/vendedor/reserva/nueva', builder: (context, state) => const Scaffold(body: Text('PANTALLA NUEVA RESERVA'))),
      GoRoute(path: '/vendedor/operaciones', builder: (context, state) => const Scaffold(body: Text('PANTALLA OPERACIONES'))),
    ],
  );
  addTearDown(router.dispose);

  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        sesionStorageProvider.overrideWithValue(sesion),
        tokenStorageProvider.overrideWithValue(tokens),
        authRepositoryProvider.overrideWithValue(repo),
        tiendaRepositoryProvider.overrideWithValue(TiendaRepository(api)),
        conectividadServiceProvider.overrideWithValue(conectividad),
        if (estadoAuth != null) authControllerProvider.overrideWith((ref) => AuthControllerFalso(ref, estadoAuth)),
        baseLocalProvider.overrideWith((ref) => baseLocal),
        descargaServiceProvider.overrideWith((ref) => descarga),
        if (reloj != null) relojProvider.overrideWithValue(reloj),
        // Sin una base propia, las pantallas no leen la base local: SQLite deja temporizadores pendientes dentro de las
        // pruebas de widgets. Estas pruebas (E18b) no hablan de catálogo, así que se simula lo que el inicio consulta.
        if (base == null) ...[
          vigenciaProvider.overrideWith((ref) async => const ResumenVigencia(estado: EstadoVigencia.nunca)),
          sucursalesAutorizadasProvider.overrideWith((ref) async => const []),
          sucursalActivaProvider.overrideWith((ref) async => null),
          pendientesAjenosProvider.overrideWith((ref) async => 0),
          contadorPendientesProvider.overrideWithValue(const ContadorPendientesVacio()),
          politicaLimpiezaLocalProvider.overrideWith((ref) async => const _LimpiezaNula()),
          descargaRepositoryProvider.overrideWith((ref) async => _RepositorioDescargaNulo()),
        ],
        ...overrides,
      ],
      child: MaterialApp.router(routerConfig: router),
    ),
  );
  // El primer frame lee la tienda guardada; el segundo la pinta.
  await tester.pump();
  await tester.pump();
  final contenedor = ProviderScope.containerOf(tester.element(find.byType(MaterialApp)));
  return EscenarioVendedor(
    router: router,
    contenedor: contenedor,
    repo: repo,
    conectividad: conectividad,
    sesion: sesion,
    tokens: tokens,
    api: api,
    servicioDescarga: descarga,
    base: baseLocal,
  );
}

/// El estado de la descarga sin base: nunca descargó nada y no recuerda la sucursal.
class _RepositorioDescargaNulo implements DescargaRepository {
  @override
  Future<UltimaDescarga?> ultimaDescarga(int empresaId, int sucursalId) async => null;

  @override
  Future<int?> sucursalActiva(int empresaId, int usuarioId) async => null;

  @override
  Future<void> fijarSucursalActiva(int empresaId, int usuarioId, int sucursalId) async {}

  @override
  Future<bool> hayOperacionesEnviadas(int empresaId) async => false;

  @override
  Future<int?> avisoHoras(int empresaId) async => null;

  @override
  Future<int?> empresaDeSucursal(int sucursalId) async => null;

  @override
  Future<String?> formatoDescarga(int empresaId, int sucursalId) async => null;
}

/// Una limpieza al cerrar sesión que no toca ninguna base.
class _LimpiezaNula implements PoliticaLimpiezaLocal {
  const _LimpiezaNula();

  @override
  Future<ResultadoLimpieza> alCerrarSesion({required int empresaId, required int usuarioId}) async =>
      const ResultadoLimpieza(pendientes: 0, purgo: false);
}

Future<Database> _abrirBaseVacia(WidgetTester tester) async {
  final db = (await tester.runAsync(abrirBaseDePrueba))!;
  addTearDown(() async {
    try {
      await db.close();
    } catch (_) {}
  });
  return db;
}
