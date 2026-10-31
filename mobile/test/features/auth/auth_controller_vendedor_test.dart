import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/network/providers.dart';
import 'package:mobile/features/auth/data/auth_repository.dart';
import 'package:mobile/features/auth/models/usuario.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/auth/state/auth_state.dart';
import 'package:mobile/features/tienda/data/tienda_repository.dart';
import 'package:mobile/features/tienda/models/tienda.dart';
import 'package:mobile/features/tienda/state/tienda_controller.dart';

import '../../helpers/api_client_falso.dart';
import '../../helpers/sesion_storage_falso.dart';
import '../../helpers/token_storage_falso.dart';

const _chaski = Tienda(codigo: 'chaski', nombre: 'Chaski Sport');
const _andina = Tienda(codigo: 'andina', nombre: 'Boutique Andina');

const _mensajeSuscripcion = 'La suscripción de esta tienda no está activa. Contacta al administrador de la tienda.';
const _mensajeServidor = 'El servidor no pudo responder. Intenta de nuevo en unos minutos.';

/// Las respuestas de `GET /public/chaski/tienda` con el branding de la empresa.
const _brandingChaski = {
  'codigo': 'chaski',
  'nombre': 'Chaski Sport SRL',
  'logo_url': 'https://cdn.example.com/chaski.png',
  'color_acento': '#8FAE5B',
  'disponible': true,
};

Usuario _usuario({
  List<String> roles = const ['cajero'],
  List<String> permisos = const ['ventas.presencial'],
  String? empresaCodigo = 'chaski',
  String? empresaNombre = 'Chaski Sport',
  String email = 'ana@example.com',
}) {
  return Usuario(
    id: 4,
    nombre: 'Ana',
    apellido: 'Rojas',
    email: email,
    telefono: null,
    activo: true,
    roles: roles,
    permisos: permisos,
    empresaId: empresaCodigo == null ? null : 7,
    empresaCodigo: empresaCodigo,
    empresaNombre: empresaNombre,
  );
}

Usuario _cajero() => _usuario();
Usuario _cliente() => _usuario(roles: const ['cliente'], permisos: const []);
Usuario _proveedor() => _usuario(roles: const ['proveedor'], permisos: const ['catalogo.ver']);

DioException _errorDio(DioExceptionType tipo, {int? estado, Object? datos}) {
  final opciones = RequestOptions(path: '/auth/yo');
  return DioException(
    requestOptions: opciones,
    type: tipo,
    response: estado == null ? null : Response(requestOptions: opciones, statusCode: estado, data: datos),
  );
}

DioException _sinConexion() => _errorDio(DioExceptionType.connectionError);
DioException _http(int estado, {Object? datos}) => _errorDio(DioExceptionType.badResponse, estado: estado, datos: datos);

/// Repositorio sin red. Lo que devuelve `/auth/yo` y los errores de login o de `/auth/yo` se cambian durante la prueba.
class _RepoFalso extends AuthRepository {
  _RepoFalso(this.tokens, this.usuario) : super(dio: Dio(), tokenStorage: tokens);

  final TokenStorageFalso tokens;
  Usuario usuario;
  Object? errorLogin;
  Object? errorUsuario;

  /// La `empresa` con la que se llamó a `login`, tal cual (null = ninguna).
  final List<String?> empresasRecibidas = [];
  int consultasUsuario = 0;

  @override
  Future<void> login({required String email, required String password, String? empresa}) async {
    empresasRecibidas.add(empresa);
    if (errorLogin != null) throw errorLogin!;
    await tokens.guardar(accessToken: 'ACCESS', refreshToken: 'REFRESH');
  }

  @override
  Future<Usuario> obtenerUsuarioActual() async {
    consultasUsuario++;
    if (errorUsuario != null) throw errorUsuario!;
    return usuario;
  }
}

class _Mundo {
  _Mundo(this.contenedor, this.tokens, this.sesion, this.repo, this.api);

  final ProviderContainer contenedor;
  final TokenStorageFalso tokens;
  final SesionStorageFalso sesion;
  final _RepoFalso repo;
  final ApiClientFalso api;

  AuthController get auth => contenedor.read(authControllerProvider.notifier);
  AuthState get estado => contenedor.read(authControllerProvider);
  Tienda? get tienda => contenedor.read(tiendaActualProvider);
}

/// [usuario] es lo que devuelve `/auth/yo`. [tienda] es la tienda guardada en el dispositivo (null = ninguna). [perfil]
/// es el último perfil del personal guardado. [conSesion] deja tokens guardados (como al abrir la app otra vez).
/// [branding] prepara la respuesta de la ruta pública de la tienda (si es null, esa ruta falla).
_Mundo _mundo({
  Usuario? usuario,
  Tienda? tienda = _chaski,
  Usuario? perfil,
  bool conSesion = false,
  Object? branding,
  List<Override> extraOverrides = const [],
}) {
  final tokens = TokenStorageFalso();
  if (conSesion) {
    tokens
      ..accessToken = 'ACCESS'
      ..refreshToken = 'REFRESH';
  }
  final sesion = SesionStorageFalso(tienda: tienda, perfil: perfil);
  final repo = _RepoFalso(tokens, usuario ?? _cajero());
  final api = ApiClientFalso();
  if (branding != null) api.responder('GET', '/public/chaski/tienda', branding);

  final contenedor = ProviderContainer(
    overrides: [
      tokenStorageProvider.overrideWithValue(tokens),
      sesionStorageProvider.overrideWithValue(sesion),
      authRepositoryProvider.overrideWithValue(repo),
      tiendaRepositoryProvider.overrideWithValue(TiendaRepository(api)),
      ...extraOverrides,
    ],
  );
  addTearDown(contenedor.dispose);
  return _Mundo(contenedor, tokens, sesion, repo, api);
}

Future<void> _loginPersonal(_Mundo m, {String empresa = 'chaski'}) =>
    m.auth.loginPersonal(empresa: empresa, email: 'ana@example.com', password: 'clave12345');

/// Deja una sesión de vendedor abierta sin red: tokens guardados, perfil guardado, `verificada` falsa.
Future<_Mundo> _vendedorSinVerificar() async {
  final perfil = _cajero();
  final m = _mundo(usuario: perfil, perfil: perfil, conSesion: true);
  m.repo.errorUsuario = _sinConexion();
  await m.auth.restaurarSesion();
  expect(m.estado.estaAutenticado, isTrue);
  expect(m.estado.verificada, isFalse);
  return m;
}

void main() {
  group('loginPersonal - personal que entra', () {
    test('un cajero entra: autenticado, verificada y con el perfil guardado', () async {
      final cajero = _cajero();
      final m = _mundo(usuario: cajero, branding: _brandingChaski);

      await _loginPersonal(m);

      expect(m.estado.estado, EstadoSesion.autenticado);
      expect(m.estado.verificada, isTrue);
      expect(m.estado.error, isNull);
      expect(m.estado.usuario, same(cajero));
      expect(m.estado.usuario!.modo, ModoApp.vendedor);
      expect(m.sesion.perfil, same(cajero), reason: 'el perfil se guarda para abrir la app sin red');
      expect(m.tokens.accessToken, 'ACCESS');
    });

    test('un encargado con reservas.gestionar_sucursal también entra', () async {
      final encargado = _usuario(roles: const ['encargado_sucursal'], permisos: const ['reservas.gestionar_sucursal']);
      final m = _mundo(usuario: encargado, branding: _brandingChaski);

      await _loginPersonal(m);

      expect(m.estado.estaAutenticado, isTrue);
      expect(m.sesion.perfil, same(encargado));
    });

    test('un administrador con ambos permisos entra', () async {
      final admin = _usuario(
        roles: const ['administrador'],
        permisos: const ['ventas.presencial', 'reservas.gestionar_sucursal'],
      );
      final m = _mundo(usuario: admin, branding: _brandingChaski);

      await _loginPersonal(m);

      expect(m.estado.estaAutenticado, isTrue);
    });

    test('la tienda elegida pasa a ser la de la empresa del usuario, con el branding de la ruta pública', () async {
      final m = _mundo(branding: _brandingChaski);

      await _loginPersonal(m);

      const esperada = Tienda(
        codigo: 'chaski',
        nombre: 'Chaski Sport SRL',
        logoUrl: 'https://cdn.example.com/chaski.png',
        colorAcento: '#8FAE5B',
      );
      expect(m.tienda, esperada);
      expect(m.sesion.tienda, esperada, reason: 'queda guardada en el dispositivo');
      expect(m.api.de('GET', '/public/chaski/tienda'), hasLength(1));
    });

    test('reemplaza la tienda que estaba elegida si la cuenta es de otra empresa', () async {
      final m = _mundo(tienda: _andina, branding: _brandingChaski);

      await _loginPersonal(m);

      expect(m.tienda?.codigo, 'chaski');
      expect(m.sesion.tienda?.codigo, 'chaski');
    });

    test('entra aunque no hubiera ninguna tienda elegida', () async {
      final m = _mundo(tienda: null, branding: _brandingChaski);

      await _loginPersonal(m);

      expect(m.estado.estaAutenticado, isTrue);
      expect(m.tienda?.codigo, 'chaski');
    });

    test('si la ruta pública falla usa el código y el nombre de la empresa de la cuenta', () async {
      final m = _mundo(
        branding: const ErrorApp(tipo: TipoErrorApp.noEncontrado, mensaje: 'No encontramos lo que buscabas.', estado: 404),
      );

      await _loginPersonal(m);

      expect(m.estado.estaAutenticado, isTrue);
      expect(m.tienda, const Tienda(codigo: 'chaski', nombre: 'Chaski Sport'));
      expect(m.sesion.tienda, const Tienda(codigo: 'chaski', nombre: 'Chaski Sport'));
    });

    test('si la ruta pública falla y la cuenta no trae nombre de empresa, el nombre es el código', () async {
      final m = _mundo(usuario: _usuario(empresaNombre: null));

      await _loginPersonal(m);

      expect(m.estado.estaAutenticado, isTrue, reason: 'sin respuesta preparada el falso lanza un StateError');
      expect(m.tienda, const Tienda(codigo: 'chaski', nombre: 'chaski'));
    });

    test('sin empresa_codigo en la cuenta usa la tienda que ya estaba elegida', () async {
      final m = _mundo(usuario: _usuario(empresaCodigo: null, empresaNombre: null), branding: _brandingChaski);
      // En la app el controlador de tienda ya está cargado cuando la persona toca "Ingresar".
      await m.contenedor.read(tiendaControllerProvider.notifier).cargadaFuture;

      await _loginPersonal(m);

      expect(m.estado.estaAutenticado, isTrue);
      expect(m.tienda?.codigo, 'chaski');
    });

    test('el repositorio recibe la empresa tal como se escribió, con los espacios recortados', () async {
      final m = _mundo(branding: _brandingChaski);

      await _loginPersonal(m, empresa: '   Chaski Sport  ');

      expect(m.repo.empresasRecibidas, ['Chaski Sport'], reason: 'no se normaliza: el backend acepta nombre o código');
    });

    test('mientras el repositorio responde el estado es cargando', () async {
      final m = _mundo(branding: _brandingChaski);

      final futuro = _loginPersonal(m);
      expect(m.estado.estado, EstadoSesion.cargando);
      await futuro;

      expect(m.estado.estado, EstadoSesion.autenticado);
    });
  });

  group('loginPersonal - personal que no entra', () {
    test('una cuenta de cliente no entra: error, tokens limpios y AccesoPersonalException', () async {
      final m = _mundo(usuario: _cliente(), branding: _brandingChaski);

      await expectLater(
        _loginPersonal(m),
        throwsA(isA<AccesoPersonalException>().having((e) => e.modo, 'modo', ModoApp.cliente)),
      );

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.estado.usuario, isNull);
      expect(m.estado.error, mensajeCuentaDeCliente);
      expect(m.tokens.accessToken, isNull);
      expect(m.tokens.refreshToken, isNull);
      expect(m.tokens.vecesLimpiado, greaterThanOrEqualTo(1));
      expect(m.sesion.perfil, isNull);
    });

    test('un cliente que además es cajero tampoco entra por el acceso del personal', () async {
      final m = _mundo(
        usuario: _usuario(roles: const ['cajero', 'cliente'], permisos: const ['ventas.presencial']),
        branding: _brandingChaski,
      );

      await expectLater(_loginPersonal(m), throwsA(isA<AccesoPersonalException>()));

      expect(m.estado.error, mensajeCuentaDeCliente);
    });

    test('un proveedor (sin acceso) no entra: mensajeSinAccesoMovil', () async {
      final m = _mundo(usuario: _proveedor(), branding: _brandingChaski);

      await expectLater(
        _loginPersonal(m),
        throwsA(isA<AccesoPersonalException>().having((e) => e.modo, 'modo', ModoApp.sinAcceso)),
      );

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.estado.error, mensajeSinAccesoMovil);
      expect(m.tokens.accessToken, isNull);
      expect(m.sesion.perfil, isNull);
    });

    test('un superadministrador (sin empresa) no entra', () async {
      final m = _mundo(
        usuario: _usuario(
          roles: const ['superadministrador'],
          permisos: const ['plataforma.gestionar'],
          empresaCodigo: null,
          empresaNombre: null,
        ),
      );

      await expectLater(_loginPersonal(m), throwsA(isA<AccesoPersonalException>()));

      expect(m.estado.error, mensajeSinAccesoMovil);
    });

    test('al rechazar la cuenta no se cambia la tienda elegida ni se pide su branding', () async {
      final m = _mundo(usuario: _cliente(), tienda: _andina, branding: _brandingChaski);

      await expectLater(_loginPersonal(m), throwsA(isA<AccesoPersonalException>()));

      await m.contenedor.read(tiendaControllerProvider.notifier).cargadaFuture;
      expect(m.tienda, _andina);
      expect(m.sesion.tienda, _andina);
      expect(m.api.llamadas, isEmpty);
    });

    test('mensaje de AccesoPersonalException según el modo', () {
      expect(const AccesoPersonalException(ModoApp.cliente).mensaje, mensajeCuentaDeCliente);
      expect(const AccesoPersonalException(ModoApp.sinAcceso).mensaje, mensajeSinAccesoMovil);
    });
  });

  group('loginPersonal - errores del servidor', () {
    test('credenciales malas (401): mensajeCredencialesPersonal y tokens limpios', () async {
      final m = _mundo();
      m.repo.errorLogin = _http(401, datos: {'detail': 'Credenciales inválidas'});

      await expectLater(_loginPersonal(m), throwsA(isA<DioException>()));

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.estado.error, mensajeCredencialesPersonal);
      expect(m.tokens.vecesLimpiado, greaterThanOrEqualTo(1));
      expect(m.sesion.perfil, isNull);
    });

    test('un error cualquiera sin respuesta se muestra como credenciales incorrectas', () async {
      final m = _mundo();
      m.repo.errorLogin = Exception('algo raro');

      await expectLater(_loginPersonal(m), throwsA(isA<Exception>()));

      expect(m.estado.error, mensajeCredencialesPersonal);
    });

    test('sin conexión: mensajePrimeraVezSinConexion', () async {
      final m = _mundo();
      m.repo.errorLogin = _sinConexion();

      await expectLater(_loginPersonal(m), throwsA(isA<DioException>()));

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.estado.error, mensajePrimeraVezSinConexion);
    });

    test('timeout: también es sin conexión', () async {
      final m = _mundo();
      m.repo.errorLogin = _errorDio(DioExceptionType.connectionTimeout);

      await expectLater(_loginPersonal(m), throwsA(isA<DioException>()));

      expect(m.estado.error, mensajePrimeraVezSinConexion);
    });

    test('sin conexión al pedir /auth/yo después de un login correcto', () async {
      final m = _mundo();
      m.repo.errorUsuario = _sinConexion();

      await expectLater(_loginPersonal(m), throwsA(isA<DioException>()));

      expect(m.estado.error, mensajePrimeraVezSinConexion);
      expect(m.tokens.accessToken, isNull, reason: 'los tokens que guardó el login se limpian');
    });

    test('403 suscripcion_no_activa: mensaje fijo de la suscripción', () async {
      final m = _mundo();
      m.repo.errorLogin = _http(
        403,
        datos: {'detail': 'suscripcion_no_activa', 'codigo': 'suscripcion_no_activa', 'mensaje': 'texto del servidor'},
      );

      await expectLater(_loginPersonal(m), throwsA(isA<DioException>()));

      expect(m.estado.error, _mensajeSuscripcion);
    });

    test('403 plan_no_incluye_funcionalidad: mensaje fijo del plan', () async {
      final m = _mundo();
      m.repo.errorLogin = _http(403, datos: {'detail': 'plan_no_incluye_funcionalidad'});

      await expectLater(_loginPersonal(m), throwsA(isA<DioException>()));

      expect(m.estado.error, contains('Tu plan no incluye esta función'));
    });

    test('429: muestra el mensaje del backend', () async {
      final m = _mundo();
      m.repo.errorLogin = _http(429, datos: {'detail': 'Demasiados intentos. Espera 15 minutos.'});

      await expectLater(_loginPersonal(m), throwsA(isA<DioException>()));

      expect(m.estado.error, 'Demasiados intentos. Espera 15 minutos.');
    });

    test('429 sin detalle: usa el mensaje genérico, nunca el de credenciales', () async {
      final m = _mundo();
      m.repo.errorLogin = _http(429);

      await expectLater(_loginPersonal(m), throwsA(isA<DioException>()));

      expect(m.estado.error, isNot(mensajeCredencialesPersonal));
      expect(m.estado.error, isNotEmpty);
    });

    test('500: mensaje de servidor, no de credenciales', () async {
      final m = _mundo();
      m.repo.errorLogin = _http(500);

      await expectLater(_loginPersonal(m), throwsA(isA<DioException>()));

      expect(m.estado.error, _mensajeServidor);
    });

    test('tras un error se puede volver a intentar y entrar', () async {
      final m = _mundo(branding: _brandingChaski);
      m.repo.errorLogin = _http(401);
      await expectLater(_loginPersonal(m), throwsA(isA<DioException>()));

      m.repo.errorLogin = null;
      await _loginPersonal(m);

      expect(m.estado.estaAutenticado, isTrue);
      expect(m.estado.error, isNull);
    });
  });

  group('login (clientes) - cuenta del personal', () {
    test('una cuenta de personal con permisos de venta se rechaza con mensajeSoloClientes', () async {
      final m = _mundo();

      await expectLater(
        m.auth.login(email: 'ana@example.com', password: 'clave12345'),
        throwsA(isA<AccesoSoloClientesException>()),
      );

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.estado.error, mensajeSoloClientes);
      expect(m.tokens.accessToken, isNull);
      expect(m.sesion.perfil, isNull, reason: 'el login de clientes nunca guarda un perfil de personal');
    });

    test('el login de clientes no manda empresa: usa la de la tienda elegida', () async {
      final m = _mundo(usuario: _cliente());

      await m.auth.login(email: 'ana@example.com', password: 'clave12345');

      expect(m.estado.estaAutenticado, isTrue);
      expect(m.repo.empresasRecibidas, [null]);
    });
  });

  group('restaurarSesion - vendedor', () {
    test('con red: autenticado, verificada y perfil guardado', () async {
      final cajero = _cajero();
      final m = _mundo(usuario: cajero, conSesion: true);

      await m.auth.restaurarSesion();

      expect(m.estado.estado, EstadoSesion.autenticado);
      expect(m.estado.verificada, isTrue);
      expect(m.estado.usuario, same(cajero));
      expect(m.sesion.perfil, same(cajero));
    });

    test('sin red y con perfil de la misma tienda: autenticado sin verificar, con el perfil', () async {
      final perfil = _cajero();
      final m = _mundo(perfil: perfil, conSesion: true);
      m.repo.errorUsuario = _sinConexion();

      await m.auth.restaurarSesion();

      expect(m.estado.estado, EstadoSesion.autenticado);
      expect(m.estado.verificada, isFalse);
      expect(m.estado.usuario, same(perfil));
      expect(m.tokens.accessToken, 'ACCESS');
      expect(m.tokens.vecesLimpiado, 0);
    });

    test('timeout con perfil guardado: también sigue adentro sin verificar', () async {
      final m = _mundo(perfil: _cajero(), conSesion: true);
      m.repo.errorUsuario = _errorDio(DioExceptionType.receiveTimeout);

      await m.auth.restaurarSesion();

      expect(m.estado.estaAutenticado, isTrue);
      expect(m.estado.verificada, isFalse);
    });

    test('error 500 con perfil guardado: también sigue adentro sin verificar', () async {
      final m = _mundo(perfil: _cajero(), conSesion: true);
      m.repo.errorUsuario = _http(500);

      await m.auth.restaurarSesion();

      expect(m.estado.estaAutenticado, isTrue);
      expect(m.estado.verificada, isFalse);
    });

    test('sin red y sin perfil guardado: noAutenticado y los tokens quedan intactos', () async {
      final m = _mundo(conSesion: true);
      m.repo.errorUsuario = _sinConexion();

      await m.auth.restaurarSesion();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.estado.usuario, isNull);
      expect(m.tokens.accessToken, 'ACCESS');
      expect(m.tokens.refreshToken, 'REFRESH');
      expect(m.tokens.vecesLimpiado, 0);
    });

    test('sin red con el perfil de OTRA tienda: noAutenticado (nunca se mezclan empresas)', () async {
      final perfilAjeno = _usuario(empresaCodigo: 'andina', empresaNombre: 'Boutique Andina');
      final m = _mundo(perfil: perfilAjeno, conSesion: true);
      m.repo.errorUsuario = _sinConexion();

      await m.auth.restaurarSesion();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.estado.usuario, isNull);
    });

    test('sin red con un perfil guardado que ya no es de vendedor: noAutenticado', () async {
      final m = _mundo(perfil: _cliente(), conSesion: true);
      m.repo.errorUsuario = _sinConexion();

      await m.auth.restaurarSesion();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
    });

    test('con red pero la cuenta es de otra tienda que la elegida: se descarta todo', () async {
      final m = _mundo(
        usuario: _usuario(empresaCodigo: 'andina'),
        perfil: _cajero(),
        conSesion: true,
      );

      await m.auth.restaurarSesion();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.tokens.accessToken, isNull);
      expect(m.sesion.perfil, isNull);
    });

    test('401 al verificar: se limpian los tokens y el perfil', () async {
      final m = _mundo(perfil: _cajero(), conSesion: true);
      m.repo.errorUsuario = _http(401);

      await m.auth.restaurarSesion();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.tokens.accessToken, isNull);
      expect(m.sesion.perfil, isNull);
    });

    test('sin token no hay sesión y no se consulta al servidor', () async {
      final m = _mundo(perfil: _cajero());

      await m.auth.restaurarSesion();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.repo.consultasUsuario, 0);
    });

    test('token pero sin tienda guardada: se descarta la sesión y el perfil', () async {
      final m = _mundo(tienda: null, perfil: _cajero(), conSesion: true);

      await m.auth.restaurarSesion();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.tokens.accessToken, isNull);
      expect(m.sesion.perfil, isNull);
    });
  });

  group('restaurarSesion - cliente y sin acceso', () {
    test('un cliente con red: autenticado y NO se guarda perfil', () async {
      final m = _mundo(usuario: _cliente(), conSesion: true);

      await m.auth.restaurarSesion();

      expect(m.estado.estaAutenticado, isTrue);
      expect(m.estado.usuario!.modo, ModoApp.cliente);
      expect(m.sesion.perfil, isNull);
    });

    test('un cliente sin red: noAutenticado sin limpiar los tokens (como antes)', () async {
      final m = _mundo(usuario: _cliente(), conSesion: true);
      m.repo.errorUsuario = _sinConexion();

      await m.auth.restaurarSesion();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.tokens.accessToken, 'ACCESS');
      expect(m.tokens.refreshToken, 'REFRESH');
      expect(m.tokens.vecesLimpiado, 0);
    });

    test('un cliente sin red aunque exista un perfil de vendedor guardado de esa tienda: usa el perfil', () async {
      // El estado de la sesión lo decide el perfil guardado, no el rol que tenga el usuario en el servidor.
      final m = _mundo(usuario: _cliente(), perfil: _cajero(), conSesion: true);
      m.repo.errorUsuario = _sinConexion();

      await m.auth.restaurarSesion();

      expect(m.estado.estaAutenticado, isTrue);
      expect(m.estado.verificada, isFalse);
    });

    test('sin acceso (proveedor): se limpian los tokens y el perfil', () async {
      final m = _mundo(usuario: _proveedor(), perfil: _cajero(), conSesion: true);

      await m.auth.restaurarSesion();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.estado.usuario, isNull);
      expect(m.tokens.accessToken, isNull);
      expect(m.tokens.refreshToken, isNull);
      expect(m.sesion.perfil, isNull);
      expect(m.sesion.vecesPerfilBorrado, 1);
    });

    test('sin acceso: la tienda elegida no se toca', () async {
      final m = _mundo(usuario: _proveedor(), conSesion: true);

      await m.auth.restaurarSesion();

      expect(m.sesion.tienda, _chaski);
      expect(m.sesion.vecesBorrada, 0);
    });
  });

  group('verificarSesion', () {
    test('con verificada=false y red OK: pasa a verificada y actualiza el perfil', () async {
      final m = await _vendedorSinVerificar();
      final actualizado = _usuario(permisos: const ['ventas.presencial', 'reservas.gestionar_sucursal']);
      m.repo
        ..errorUsuario = null
        ..usuario = actualizado;

      await m.auth.verificarSesion();

      expect(m.estado.estado, EstadoSesion.autenticado);
      expect(m.estado.verificada, isTrue);
      expect(m.estado.usuario, same(actualizado));
      expect(m.sesion.perfil, same(actualizado), reason: 'el perfil guardado se refresca');
    });

    test('401: cierra la sesión con motivo vencida y modoPrevio vendedor', () async {
      final m = await _vendedorSinVerificar();
      m.repo.errorUsuario = _http(401);

      await m.auth.verificarSesion();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.estado.motivoCierre, MotivoCierre.vencida);
      expect(m.estado.modoPrevio, ModoApp.vendedor);
      expect(m.tokens.accessToken, isNull);
      expect(m.sesion.perfil, isNull);
    });

    test('403: también cierra la sesión por vencida', () async {
      final m = await _vendedorSinVerificar();
      m.repo.errorUsuario = _http(403);

      await m.auth.verificarSesion();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.estado.motivoCierre, MotivoCierre.vencida);
      expect(m.estado.modoPrevio, ModoApp.vendedor);
    });

    test('sin conexión: sigue igual (autenticado y sin verificar)', () async {
      final m = await _vendedorSinVerificar();
      final antes = m.estado.usuario;

      await m.auth.verificarSesion();

      expect(m.estado.estado, EstadoSesion.autenticado);
      expect(m.estado.verificada, isFalse);
      expect(m.estado.usuario, same(antes));
      expect(m.tokens.accessToken, 'ACCESS');
    });

    test('error 500: sigue igual', () async {
      final m = await _vendedorSinVerificar();
      m.repo.errorUsuario = _http(500);

      await m.auth.verificarSesion();

      expect(m.estado.estaAutenticado, isTrue);
      expect(m.estado.verificada, isFalse);
    });

    test('si el servidor ya no le da acceso a la app: cierra la sesión por vencida', () async {
      final m = await _vendedorSinVerificar();
      m.repo
        ..errorUsuario = null
        ..usuario = _usuario(permisos: const []);

      await m.auth.verificarSesion();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.estado.motivoCierre, MotivoCierre.vencida);
      expect(m.estado.modoPrevio, ModoApp.vendedor);
      expect(m.sesion.perfil, isNull);
    });

    test('no hace nada si la sesión ya está verificada', () async {
      final m = _mundo(usuario: _cajero(), conSesion: true);
      await m.auth.restaurarSesion();
      expect(m.estado.verificada, isTrue);
      final consultas = m.repo.consultasUsuario;

      await m.auth.verificarSesion();

      expect(m.repo.consultasUsuario, consultas, reason: 'no se vuelve a consultar al servidor');
      expect(m.estado.estaAutenticado, isTrue);
    });

    test('no hace nada si no hay sesión', () async {
      final m = _mundo();
      await m.auth.restaurarSesion(); // sin token: noAutenticado

      await m.auth.verificarSesion();

      expect(m.repo.consultasUsuario, 0);
      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.estado.motivoCierre, isNull);
    });

    test('no hace nada con la sesión sin iniciar (estado inicial)', () async {
      final m = _mundo(conSesion: true);

      await m.auth.verificarSesion();

      expect(m.estado.estado, EstadoSesion.inicial);
      expect(m.repo.consultasUsuario, 0);
    });
  });

  group('logout', () {
    test('borra tokens y perfil pero NO la tienda', () async {
      final m = _mundo(branding: _brandingChaski);
      await _loginPersonal(m);
      expect(m.sesion.perfil, isNotNull);

      await m.auth.logout();

      expect(m.tokens.accessToken, isNull);
      expect(m.tokens.refreshToken, isNull);
      expect(m.sesion.perfil, isNull);
      expect(m.sesion.tienda?.codigo, 'chaski');
      expect(m.sesion.vecesBorrada, 0);
      expect(m.tienda?.codigo, 'chaski');
    });

    test('deja motivoCierre voluntario y el modoPrevio vendedor', () async {
      final m = _mundo(branding: _brandingChaski);
      await _loginPersonal(m);

      await m.auth.logout();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.estado.usuario, isNull);
      expect(m.estado.motivoCierre, MotivoCierre.voluntario);
      expect(m.estado.modoPrevio, ModoApp.vendedor);
    });

    test('con motivo vencida lo deja guardado', () async {
      final m = _mundo(branding: _brandingChaski);
      await _loginPersonal(m);

      await m.auth.logout(motivo: MotivoCierre.vencida);

      expect(m.estado.motivoCierre, MotivoCierre.vencida);
      expect(m.estado.modoPrevio, ModoApp.vendedor);
    });

    test('un cliente que cierra sesión deja modoPrevio cliente', () async {
      final m = _mundo(usuario: _cliente());
      await m.auth.login(email: 'a@b.com', password: 'clave12345');

      await m.auth.logout();

      expect(m.estado.modoPrevio, ModoApp.cliente);
      expect(m.estado.motivoCierre, MotivoCierre.voluntario);
    });

    test('sin sesión previa el modoPrevio queda en null', () async {
      final m = _mundo();

      await m.auth.logout();

      expect(m.estado.modoPrevio, isNull);
      expect(m.estado.estado, EstadoSesion.noAutenticado);
    });

    test('el listener de sesionExpiradaProvider cierra la sesión con motivo vencida', () async {
      final m = _mundo(branding: _brandingChaski);
      await _loginPersonal(m);
      expect(m.estado.estaAutenticado, isTrue);

      m.contenedor.read(sesionExpiradaProvider.notifier).state++;
      await pumpEventQueue();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.estado.motivoCierre, MotivoCierre.vencida);
      expect(m.estado.modoPrevio, ModoApp.vendedor);
      expect(m.tokens.accessToken, isNull);
      expect(m.sesion.perfil, isNull);
    });

    test('la sesión vencida de un cliente deja modoPrevio cliente', () async {
      final m = _mundo(usuario: _cliente());
      await m.auth.login(email: 'a@b.com', password: 'clave12345');

      m.contenedor.read(sesionExpiradaProvider.notifier).state++;
      await pumpEventQueue();

      expect(m.estado.motivoCierre, MotivoCierre.vencida);
      expect(m.estado.modoPrevio, ModoApp.cliente);
    });
  });

  group('olvidarMotivoCierre', () {
    test('limpia el motivo y el modo previo cuando está noAutenticado', () async {
      final m = _mundo(branding: _brandingChaski);
      await _loginPersonal(m);
      await m.auth.logout(motivo: MotivoCierre.vencida);
      expect(m.estado.motivoCierre, isNotNull);

      m.auth.olvidarMotivoCierre();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.estado.motivoCierre, isNull);
      expect(m.estado.modoPrevio, isNull);
    });

    test('no toca una sesión autenticada', () async {
      final m = _mundo(branding: _brandingChaski);
      await _loginPersonal(m);
      final antes = m.estado;

      m.auth.olvidarMotivoCierre();

      expect(m.estado, same(antes));
      expect(m.estado.estaAutenticado, isTrue);
    });

    test('no cambia nada si ya no hay motivo', () async {
      final m = _mundo();
      await m.auth.restaurarSesion();
      final antes = m.estado;

      m.auth.olvidarMotivoCierre();

      expect(m.estado, same(antes));
    });

    test('no toca el estado inicial', () {
      final m = _mundo();

      m.auth.olvidarMotivoCierre();

      expect(m.estado.estado, EstadoSesion.inicial);
    });
  });
}
