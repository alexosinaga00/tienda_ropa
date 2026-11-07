import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/providers.dart';
import 'package:mobile/features/auth/data/auth_repository.dart';
import 'package:mobile/features/auth/models/usuario.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/auth/state/auth_state.dart';
import 'package:mobile/features/cliente_offline/models/linea_carrito_local.dart';
import 'package:mobile/features/cliente_offline/state/base_cliente.dart';
import 'package:mobile/features/cliente_offline/state/cliente_offline_providers.dart';
import 'package:mobile/features/tienda/models/tienda.dart';

import '../../helpers/sesion_storage_falso.dart';
import '../../helpers/token_storage_falso.dart';

const _chaski = Tienda(codigo: 'chaski', nombre: 'Chaski Sport');

Usuario _usuario({
  List<String> roles = const ['cliente'],
  List<String> permisos = const [],
  String empresaCodigo = 'chaski',
  int id = 9,
}) => Usuario(
  id: id,
  nombre: 'Luis',
  apellido: 'Mamani',
  email: 'luis@example.com',
  telefono: null,
  activo: true,
  roles: roles,
  permisos: permisos,
  empresaId: 7,
  empresaCodigo: empresaCodigo,
  empresaNombre: 'Chaski Sport',
);

DioException _sinRed() => DioException(
  requestOptions: RequestOptions(path: '/auth/yo'),
  type: DioExceptionType.connectionError,
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

class _LimpiezaFalsa extends LimpiezaCliente {
  _LimpiezaFalsa() : super(() async => throw StateError('sin base'));

  final cierres = <AlcanceCliente>[];

  @override
  Future<void> alCerrarSesion(AlcanceCliente alcance) async => cierres.add(alcance);
}

class _Mundo {
  _Mundo(this.contenedor, this.tokens, this.sesion, this.repo, this.limpieza);

  final ProviderContainer contenedor;
  final TokenStorageFalso tokens;
  final SesionStorageFalso sesion;
  final _RepoFalso repo;
  final _LimpiezaFalsa limpieza;

  AuthController get auth => contenedor.read(authControllerProvider.notifier);
  AuthState get estado => contenedor.read(authControllerProvider);
}

_Mundo _mundo({Usuario? usuario, Usuario? perfilCliente, bool conSesion = false}) {
  final tokens = TokenStorageFalso();
  if (conSesion) {
    tokens
      ..accessToken = 'ACCESS'
      ..refreshToken = 'REFRESH';
  }
  final sesion = SesionStorageFalso(tienda: _chaski)..perfilCliente = perfilCliente;
  final repo = _RepoFalso(tokens, usuario ?? _usuario());
  final limpieza = _LimpiezaFalsa();
  final contenedor = ProviderContainer(
    overrides: [
      tokenStorageProvider.overrideWithValue(tokens),
      sesionStorageProvider.overrideWithValue(sesion),
      authRepositoryProvider.overrideWithValue(repo),
      limpiezaClienteProvider.overrideWithValue(limpieza),
    ],
  );
  addTearDown(contenedor.dispose);
  return _Mundo(contenedor, tokens, sesion, repo, limpieza);
}

void main() {
  group('un cliente que reabre la tienda SIN conexión', () {
    test('con su perfil guardado de esta tienda: sigue adentro, sin verificar, con los tokens intactos', () async {
      final perfil = _usuario();
      final m = _mundo(perfilCliente: perfil, conSesion: true);
      m.repo.errorUsuario = _sinRed();

      await m.auth.restaurarSesion();

      expect(m.estado.estado, EstadoSesion.autenticado);
      expect(m.estado.verificada, isFalse);
      expect(m.estado.usuario, same(perfil));
      expect(m.tokens.accessToken, 'ACCESS');
      expect(m.tokens.vecesLimpiado, 0);
    });

    test('también con el servidor caído (5xx)', () async {
      final m = _mundo(perfilCliente: _usuario(), conSesion: true);
      m.repo.errorUsuario = DioException(
        requestOptions: RequestOptions(path: '/auth/yo'),
        type: DioExceptionType.badResponse,
        response: Response(requestOptions: RequestOptions(path: '/auth/yo'), statusCode: 503),
      );

      await m.auth.restaurarSesion();

      expect(m.estado.estaAutenticado, isTrue);
      expect(m.estado.verificada, isFalse);
    });

    test('sin perfil guardado queda como invitado, sin cerrar la sesión guardada (como antes)', () async {
      final m = _mundo(conSesion: true);
      m.repo.errorUsuario = _sinRed();

      await m.auth.restaurarSesion();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.tokens.accessToken, 'ACCESS');
    });

    test('el perfil de OTRA tienda nunca se usa', () async {
      final m = _mundo(perfilCliente: _usuario(empresaCodigo: 'andina'), conSesion: true);
      m.repo.errorUsuario = _sinRed();

      await m.auth.restaurarSesion();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
    });

    test('un perfil guardado que no es de cliente no abre una sesión de cliente', () async {
      final m = _mundo(
        perfilCliente: _usuario(roles: ['cajero'], permisos: ['ventas.presencial']),
        conSesion: true,
      );
      m.repo.errorUsuario = _sinRed();

      await m.auth.restaurarSesion();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
    });

    test('sin token no hay sesión aunque exista el perfil', () async {
      final m = _mundo(perfilCliente: _usuario());
      m.repo.errorUsuario = _sinRed();

      await m.auth.restaurarSesion();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
    });

    test('su alcance (empresa y persona) es el del perfil guardado', () async {
      final m = _mundo(perfilCliente: _usuario(), conSesion: true);
      m.repo.errorUsuario = _sinRed();

      await m.auth.restaurarSesion();

      expect(m.contenedor.read(alcanceClienteProvider), const AlcanceCliente(empresaId: 7, usuarioId: 9));
    });
  });

  group('el perfil del cliente se guarda cuando hay red', () {
    test('al restaurar con red', () async {
      final cliente = _usuario();
      final m = _mundo(usuario: cliente, conSesion: true);

      await m.auth.restaurarSesion();

      expect(m.estado.verificada, isTrue);
      expect(m.sesion.perfilCliente, same(cliente));
      expect(m.sesion.perfil, isNull, reason: 'el perfil del personal es otro');
    });

    test('al iniciar sesión', () async {
      final cliente = _usuario();
      final m = _mundo(usuario: cliente);

      await m.auth.login(email: 'luis@example.com', password: 'clave12345');

      expect(m.sesion.perfilCliente, same(cliente));
      expect(m.estado.estaAutenticado, isTrue);
    });
  });

  group('verificarSesion de un cliente restaurado sin red', () {
    Future<_Mundo> sinVerificar() async {
      final m = _mundo(perfilCliente: _usuario(), conSesion: true);
      m.repo.errorUsuario = _sinRed();
      await m.auth.restaurarSesion();
      expect(m.estado.verificada, isFalse);
      return m;
    }

    test('al volver la red se verifica y se refresca el perfil guardado', () async {
      final m = await sinVerificar();
      final nuevo = _usuario();
      m.repo
        ..errorUsuario = null
        ..usuario = nuevo;

      await m.auth.verificarSesion();

      expect(m.estado.verificada, isTrue);
      expect(m.estado.usuario, same(nuevo));
      expect(m.sesion.perfilCliente, same(nuevo));
    });

    test('si el servidor ya no lo reconoce como cliente, la sesión vence', () async {
      final m = await sinVerificar();
      m.repo
        ..errorUsuario = null
        ..usuario = _usuario(roles: ['proveedor'], permisos: ['catalogo.ver']);

      await m.auth.verificarSesion();

      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.estado.motivoCierre, MotivoCierre.vencida);
    });

    test('sin red sigue como estaba', () async {
      final m = await sinVerificar();

      await m.auth.verificarSesion();

      expect(m.estado.estaAutenticado, isTrue);
      expect(m.estado.verificada, isFalse);
    });
  });

  group('cerrar sesión de un cliente', () {
    test('borra su perfil guardado y limpia lo suyo (conservando los pedidos sin enviar)', () async {
      final m = _mundo(usuario: _usuario(), conSesion: true);
      await m.auth.restaurarSesion();
      expect(m.sesion.perfilCliente, isNotNull);

      await m.auth.logout();

      expect(m.sesion.perfilCliente, isNull);
      expect(m.limpieza.cierres, [const AlcanceCliente(empresaId: 7, usuarioId: 9)]);
      expect(m.estado.estado, EstadoSesion.noAutenticado);
      expect(m.tokens.vecesLimpiado, 1);
    });

    test('si la limpieza falla, cerrar sesión igual se completa', () async {
      final tokens = TokenStorageFalso()..accessToken = 'A';
      final contenedor = ProviderContainer(
        overrides: [
          tokenStorageProvider.overrideWithValue(tokens),
          sesionStorageProvider.overrideWithValue(SesionStorageFalso(tienda: _chaski)),
          authRepositoryProvider.overrideWithValue(_RepoFalso(tokens, _usuario())),
          limpiezaClienteProvider.overrideWithValue(_LimpiezaQueFalla()),
        ],
      );
      addTearDown(contenedor.dispose);
      await contenedor.read(authControllerProvider.notifier).restaurarSesion();

      await contenedor.read(authControllerProvider.notifier).logout();

      expect(contenedor.read(authControllerProvider).estado, EstadoSesion.noAutenticado);
      expect(tokens.accessToken, isNull);
    });
  });

  group('alcanceClienteProvider', () {
    test('sin sesión no hay alcance', () {
      final m = _mundo();
      expect(m.contenedor.read(alcanceClienteProvider), isNull);
    });

    test('el personal no tiene alcance de cliente', () async {
      final m = _mundo(
        usuario: _usuario(roles: ['cajero'], permisos: ['ventas.presencial']),
        conSesion: true,
      );
      await m.auth.restaurarSesion();

      expect(m.estado.estaAutenticado, isTrue);
      expect(m.contenedor.read(alcanceClienteProvider), isNull);
    });
  });
}

class _LimpiezaQueFalla extends LimpiezaCliente {
  _LimpiezaQueFalla() : super(() async => throw StateError('sin base'));

  @override
  Future<void> alCerrarSesion(AlcanceCliente alcance) async => throw StateError('falló la limpieza');
}
