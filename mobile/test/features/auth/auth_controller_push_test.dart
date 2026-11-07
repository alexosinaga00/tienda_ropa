import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/network/providers.dart';
import 'package:mobile/core/push/dispositivos_push_repository.dart';
import 'package:mobile/core/push/registro_push.dart' show almacenPushProvider, dispositivosPushRepositoryProvider;
import 'package:mobile/core/push/servicio_push.dart';
import 'package:mobile/features/auth/data/auth_repository.dart';
import 'package:mobile/features/auth/models/usuario.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/auth/state/auth_state.dart';
import 'package:mobile/features/tienda/data/tienda_repository.dart';
import 'package:mobile/features/tienda/models/tienda.dart';
import 'package:mobile/features/tienda/state/tienda_controller.dart';

import '../../helpers/api_client_falso.dart';
import '../../helpers/push_falso.dart';
import '../../helpers/sesion_storage_falso.dart';
import '../../helpers/token_storage_falso.dart';

const _chaski = Tienda(codigo: 'chaski', nombre: 'Chaski Sport');
const _sinRed = ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: 'Sin conexión.');

Usuario _usuario({List<String> roles = const ['cliente'], List<String> permisos = const []}) => Usuario(
  id: 4,
  nombre: 'Ana',
  apellido: 'Rojas',
  email: 'ana@example.com',
  telefono: null,
  activo: true,
  roles: roles,
  permisos: permisos,
  empresaCodigo: 'chaski',
);

class _RepoFalso extends AuthRepository {
  _RepoFalso(this.tokens, this.usuario) : super(dio: Dio(), tokenStorage: tokens);

  final TokenStorageFalso tokens;
  Usuario usuario;
  Object? errorUsuario;

  @override
  Future<void> login({required String email, required String password, String? empresa}) async {
    await tokens.guardar(accessToken: 'ACCESS', refreshToken: 'REFRESH');
  }

  @override
  Future<Usuario> obtenerUsuarioActual() async {
    if (errorUsuario != null) throw errorUsuario!;
    return usuario;
  }
}

/// Anota con qué token de sesión estaba la app cuando se pidió la baja (tiene que ser ANTES de borrarlo).
class _ApiQueMiraLaSesion extends ApiClientFalso {
  _ApiQueMiraLaSesion(this.tokens);

  final TokenStorageFalso tokens;
  final List<String?> accessAlPedirBaja = [];

  @override
  Future<void> postVacio(String ruta, {Object? cuerpo, bool publica = false}) {
    if (ruta == '/dispositivos-push/baja') accessAlPedirBaja.add(tokens.accessToken);
    return super.postVacio(ruta, cuerpo: cuerpo, publica: publica);
  }
}

class _Mundo {
  _Mundo(this.contenedor, this.tokens, this.repo, this.api, this.servicio, this.almacen);

  final ProviderContainer contenedor;
  final TokenStorageFalso tokens;
  final _RepoFalso repo;
  final _ApiQueMiraLaSesion api;
  final ServicioPushFalso servicio;
  final AlmacenPushFalso almacen;

  AuthController get auth => contenedor.read(authControllerProvider.notifier);
  AuthState get estado => contenedor.read(authControllerProvider);
  List<LlamadaApi> get altas => api.de('POST', '/dispositivos-push');
  List<LlamadaApi> get bajas => api.de('POST', '/dispositivos-push/baja');
}

_Mundo _mundo({
  Usuario? usuario,
  Usuario? perfil,
  bool conSesion = false,
  bool permiso = true,
  List<Object?> bajas = const [null],
  String? pendiente,
}) {
  final tokens = TokenStorageFalso();
  if (conSesion) {
    tokens
      ..accessToken = 'ACCESS'
      ..refreshToken = 'REFRESH';
  }
  final repo = _RepoFalso(tokens, usuario ?? _usuario());
  final api = _ApiQueMiraLaSesion(tokens)..responder('POST', '/dispositivos-push', null);
  for (final respuesta in bajas) {
    api.responder('POST', '/dispositivos-push/baja', respuesta);
  }
  final servicio = ServicioPushFalso(permiso: permiso);
  final almacen = AlmacenPushFalso(pendiente: pendiente);
  final contenedor = ProviderContainer(
    overrides: [
      tokenStorageProvider.overrideWithValue(tokens),
      sesionStorageProvider.overrideWithValue(SesionStorageFalso(tienda: _chaski, perfil: perfil)),
      authRepositoryProvider.overrideWithValue(repo),
      tiendaRepositoryProvider.overrideWithValue(TiendaRepository(ApiClientFalso())),
      servicioPushProvider.overrideWithValue(servicio),
      almacenPushProvider.overrideWithValue(almacen),
      dispositivosPushRepositoryProvider.overrideWithValue(DispositivosPushRepository(() => api)),
    ],
  );
  addTearDown(contenedor.dispose);
  return _Mundo(contenedor, tokens, repo, api, servicio, almacen);
}

Future<void> _entrarComoCliente(_Mundo m) async {
  await m.auth.login(email: 'ana@example.com', password: 'clave12345');
  await pumpEventQueue();
}

void main() {
  group('registro del token al abrir la sesión', () {
    test('un cliente que inicia sesión registra el token', () async {
      final m = _mundo();

      await _entrarComoCliente(m);

      expect(m.altas, hasLength(1));
      expect(m.altas.single.cuerpo, {'token': 'TOKEN-A', 'plataforma': 'android'});
    });

    test('al iniciar sesión pide el permiso de notificaciones si falta', () async {
      final m = _mundo(permiso: false);

      await _entrarComoCliente(m);

      expect(m.servicio.permisosPedidos, 1);
      expect(m.altas, hasLength(1));
    });

    test('si el usuario niega el permiso, entra igual y no se registra nada', () async {
      final m = _mundo(permiso: false);
      m.servicio.concedeAlPedir = false;

      await _entrarComoCliente(m);

      expect(m.estado.estaAutenticado, isTrue);
      expect(m.altas, isEmpty);
    });

    test('el personal que inicia sesión también lo registra', () async {
      final m = _mundo(usuario: _usuario(roles: const ['cajero'], permisos: const ['ventas.presencial']));

      await m.auth.loginPersonal(empresa: 'chaski', email: 'ana@example.com', password: 'clave12345');
      await pumpEventQueue();

      expect(m.estado.usuario?.modo, ModoApp.vendedor);
      expect(m.altas, hasLength(1));
    });

    test('un fallo de Firebase al registrar no rompe el inicio de sesión', () async {
      final m = _mundo();
      m.servicio.fallaAlObtenerToken = true;

      await _entrarComoCliente(m);

      expect(m.estado.estaAutenticado, isTrue);
      expect(m.altas, isEmpty);
    });

    test('un cliente que no puede entrar (cuenta de personal) no registra nada', () async {
      final m = _mundo(usuario: _usuario(roles: const ['cajero']));

      await expectLater(
        m.auth.login(email: 'ana@example.com', password: 'clave12345'),
        throwsA(isA<AccesoSoloClientesException>()),
      );
      await pumpEventQueue();

      expect(m.altas, isEmpty);
    });

    test('al restaurar la sesión con red registra el token, sin pedir permiso', () async {
      final m = _mundo(conSesion: true, permiso: false);

      await m.auth.restaurarSesion();
      await pumpEventQueue();

      expect(m.estado.estaAutenticado, isTrue);
      expect(m.servicio.permisosPedidos, 0, reason: 'abrir la app en frío no debe mostrar el diálogo');
      expect(m.altas, isEmpty, reason: 'sin permiso no hay registro');
    });

    test('al restaurar la sesión con red y con permiso, registra', () async {
      final m = _mundo(conSesion: true);

      await m.auth.restaurarSesion();
      await pumpEventQueue();

      expect(m.altas, hasLength(1));
    });

    test('restaurar la sesión sin red no registra; al verificarla después sí', () async {
      final perfil = _usuario(roles: const ['cajero'], permisos: const ['ventas.presencial']);
      final m = _mundo(usuario: perfil, perfil: perfil, conSesion: true);
      m.repo.errorUsuario = DioException(
        requestOptions: RequestOptions(path: '/auth/yo'),
        type: DioExceptionType.connectionError,
      );

      await m.auth.restaurarSesion();
      await pumpEventQueue();
      expect(m.estado.verificada, isFalse);
      expect(m.altas, isEmpty);

      m.repo.errorUsuario = null;
      await m.auth.verificarSesion();
      await pumpEventQueue();

      expect(m.altas, hasLength(1));
    });
  });

  group('baja al cerrar la sesión', () {
    test('avisa al servidor ANTES de borrar la sesión', () async {
      final m = _mundo();
      await _entrarComoCliente(m);

      await m.auth.logout();

      expect(m.bajas, hasLength(1));
      expect(m.bajas.single.cuerpo, {'token': 'TOKEN-A'});
      expect(m.api.accessAlPedirBaja, ['ACCESS'], reason: 'la baja necesita la sesión todavía abierta');
      expect(m.tokens.accessToken, isNull);
      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.almacen.pendiente, isNull);
    });

    test('sin red cierra la sesión igual y deja la baja pendiente', () async {
      final m = _mundo(bajas: [_sinRed]);
      await _entrarComoCliente(m);

      await m.auth.logout();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.tokens.accessToken, isNull);
      expect(m.almacen.pendiente, 'TOKEN-A');
    });

    test('con la sesión vencida no pide la baja (evita otro cierre) y queda pendiente', () async {
      final m = _mundo();
      await _entrarComoCliente(m);

      await m.auth.logout(motivo: MotivoCierre.vencida);

      expect(m.bajas, isEmpty);
      expect(m.almacen.pendiente, 'TOKEN-A');
      expect(m.estado.motivoCierre, MotivoCierre.vencida);
    });

    test('sin token registrado cerrar sesión no llama al servidor', () async {
      final m = _mundo(permiso: false);
      m.servicio.concedeAlPedir = false;
      await _entrarComoCliente(m);

      await m.auth.logout();

      expect(m.bajas, isEmpty);
      expect(m.estado.estado, EstadoSesion.noAutenticado);
    });

    test('la baja pendiente se resuelve en el siguiente inicio de sesión sin duplicarse', () async {
      final m = _mundo(bajas: [_sinRed]);
      await _entrarComoCliente(m);
      await m.auth.logout(); // sin red: queda pendiente
      expect(m.almacen.pendiente, 'TOKEN-A');

      await _entrarComoCliente(m); // mismo token: el alta lo reasigna y se olvida la baja

      expect(m.almacen.pendiente, isNull);
      expect(m.bajas, hasLength(1));
      expect(m.altas, hasLength(2));
    });
  });
}
