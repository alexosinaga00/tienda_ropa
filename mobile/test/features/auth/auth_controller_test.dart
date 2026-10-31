import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/providers.dart';
import 'package:mobile/features/auth/data/auth_repository.dart';
import 'package:mobile/features/auth/models/usuario.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/auth/state/auth_state.dart';
import 'package:mobile/features/tienda/models/tienda.dart';

import '../../helpers/sesion_storage_falso.dart';
import '../../helpers/token_storage_falso.dart';

/// La tienda guardada en el dispositivo en estas pruebas. AJUSTE multitenant: `restaurarSesion` ahora espera y lee la
/// tienda elegida; sin una tienda guardada descarta los tokens. Por eso el contenedor sobreescribe
/// `sesionStorageProvider` con esta tienda, cuyo código coincide con `empresaCodigo` del usuario de prueba.
const _tiendaPrueba = Tienda(codigo: 'chaski', nombre: 'Chaski Sport');

/// Repositorio sin red: el login guarda tokens en el almacenamiento falso y `/auth/yo` devuelve un usuario con los
/// roles dados (o falla, para simular credenciales inválidas).
class _RepositorioFalso extends AuthRepository {
  _RepositorioFalso(
    this.roles,
    this.almacenamiento, {
    this.falla = false,
    this.errorAlObtenerUsuario,
    this.empresaCodigo = 'chaski',
    this.permisos = const [],
  }) : super(dio: Dio(), tokenStorage: almacenamiento);

  final List<String> roles;

  /// Ajuste E18b: los permisos deciden el modo de la cuenta (vendedor, cliente o sin acceso).
  final List<String> permisos;
  final TokenStorageFalso almacenamiento;
  final bool falla;

  /// La empresa del usuario que devuelve `/auth/yo` (null = sin empresa en la respuesta).
  final String? empresaCodigo;

  /// Si se da, `/auth/yo` falla con este error (p. ej. un DioException de red o un 500).
  final Object? errorAlObtenerUsuario;

  @override
  Future<void> login({required String email, required String password, String? empresa}) async {
    if (falla) throw Exception('401');
    await almacenamiento.guardar(accessToken: 'ACCESS', refreshToken: 'REFRESH');
  }

  @override
  Future<Usuario> obtenerUsuarioActual() async {
    if (errorAlObtenerUsuario != null) throw errorAlObtenerUsuario!;
    if (falla) throw Exception('401');
    return Usuario(
      id: 1,
      nombre: 'Prueba',
      apellido: 'Rol',
      email: 'prueba@example.com',
      telefono: null,
      activo: true,
      roles: roles,
      permisos: permisos,
      empresaCodigo: empresaCodigo,
    );
  }
}

ProviderContainer _contenedor(
  List<String> roles,
  TokenStorageFalso almacenamiento, {
  bool falla = false,
  Object? errorAlObtenerUsuario,
  String? empresaCodigo = 'chaski',
  bool sinTienda = false,
  List<String> permisos = const [],
}) {
  final contenedor = ProviderContainer(
    overrides: [
      tokenStorageProvider.overrideWithValue(almacenamiento),
      sesionStorageProvider.overrideWithValue(SesionStorageFalso(tienda: sinTienda ? null : _tiendaPrueba)),
      authRepositoryProvider.overrideWithValue(
        _RepositorioFalso(
          roles,
          almacenamiento,
          falla: falla,
          errorAlObtenerUsuario: errorAlObtenerUsuario,
          empresaCodigo: empresaCodigo,
          permisos: permisos,
        ),
      ),
    ],
  );
  addTearDown(contenedor.dispose);
  return contenedor;
}

void main() {
  group('AuthController.login - solo clientes', () {
    test('un cliente inicia sesión', () async {
      final almacenamiento = TokenStorageFalso();
      final contenedor = _contenedor(['cliente'], almacenamiento);

      await contenedor.read(authControllerProvider.notifier).login(email: 'a@b.com', password: 'clave12345');

      final estado = contenedor.read(authControllerProvider);
      expect(estado.estaAutenticado, isTrue);
      expect(estado.error, isNull);
      expect(almacenamiento.accessToken, 'ACCESS');
    });

    test('quien tiene el rol cliente y además otro también entra', () async {
      final contenedor = _contenedor(['administrador', 'cliente'], TokenStorageFalso());

      await contenedor.read(authControllerProvider.notifier).login(email: 'a@b.com', password: 'clave12345');

      expect(contenedor.read(authControllerProvider).estaAutenticado, isTrue);
    });

    for (final roles in [
      ['administrador'],
      ['encargado_sucursal'],
      ['cajero'],
      ['proveedor'],
      <String>[],
    ]) {
      test('el personal ($roles) no entra: se cierra la sesión y se explica por qué', () async {
        final almacenamiento = TokenStorageFalso();
        final contenedor = _contenedor(roles, almacenamiento);

        await expectLater(
          contenedor.read(authControllerProvider.notifier).login(email: 'a@b.com', password: 'clave12345'),
          throwsA(isA<AccesoSoloClientesException>()),
        );

        final estado = contenedor.read(authControllerProvider);
        expect(estado.estado, EstadoSesion.noAutenticado);
        expect(estado.usuario, isNull);
        expect(estado.error, mensajeSoloClientes);
        expect(almacenamiento.accessToken, isNull, reason: 'los tokens que guardó el login se limpian');
        expect(almacenamiento.vecesLimpiado, greaterThanOrEqualTo(1));
      });
    }

    test('credenciales inválidas siguen mostrando el mensaje de siempre', () async {
      final contenedor = _contenedor(['cliente'], TokenStorageFalso(), falla: true);

      await expectLater(
        contenedor.read(authControllerProvider.notifier).login(email: 'a@b.com', password: 'mala'),
        throwsA(isA<Exception>()),
      );

      expect(contenedor.read(authControllerProvider).error, 'Email o contraseña incorrectos.');
    });
  });

  group('AuthController.restaurarSesion - solo clientes', () {
    test('restaura la sesión guardada de un cliente', () async {
      final almacenamiento = TokenStorageFalso()..accessToken = 'ACCESS';
      final contenedor = _contenedor(['cliente'], almacenamiento);

      await contenedor.read(authControllerProvider.notifier).restaurarSesion();

      expect(contenedor.read(authControllerProvider).estaAutenticado, isTrue);
    });

    // Ajuste E18b: antes la app era solo para clientes y toda sesión de personal se descartaba. Ahora quien tiene
    // `ventas.presencial` se restaura como vendedor y conserva sus tokens.
    test('una sesión guardada de personal con permiso de venta se restaura como vendedor', () async {
      final almacenamiento = TokenStorageFalso()
        ..accessToken = 'ACCESS'
        ..refreshToken = 'REFRESH';
      final contenedor = _contenedor(['cajero'], almacenamiento, permisos: ['ventas.presencial']);

      await contenedor.read(authControllerProvider.notifier).restaurarSesion();

      final estado = contenedor.read(authControllerProvider);
      expect(estado.estaAutenticado, isTrue);
      expect(estado.usuario?.modo, ModoApp.vendedor);
      expect(almacenamiento.accessToken, 'ACCESS');
      expect(almacenamiento.refreshToken, 'REFRESH');
      expect(almacenamiento.vecesLimpiado, 0);
    });

    DioException errorDio(DioExceptionType tipo, {int? estado}) {
      final opciones = RequestOptions(path: '/auth/yo');
      return DioException(
        requestOptions: opciones,
        type: tipo,
        response: estado == null ? null : Response(requestOptions: opciones, statusCode: estado),
      );
    }

    final fallosQueNoInvalidanLaSesion = {
      'sin conexión': errorDio(DioExceptionType.connectionError),
      'timeout': errorDio(DioExceptionType.connectionTimeout),
      'error 500': errorDio(DioExceptionType.badResponse, estado: 500),
    };
    fallosQueNoInvalidanLaSesion.forEach((nombre, error) {
      test('$nombre al verificar la sesión: se conservan los tokens y no se cierra la sesión guardada', () async {
        final almacenamiento = TokenStorageFalso()
          ..accessToken = 'ACCESS'
          ..refreshToken = 'REFRESH';
        final contenedor = _contenedor(['cliente'], almacenamiento, errorAlObtenerUsuario: error);

        await contenedor.read(authControllerProvider.notifier).restaurarSesion();

        expect(contenedor.read(authControllerProvider).estado, EstadoSesion.noAutenticado);
        expect(almacenamiento.accessToken, 'ACCESS');
        expect(almacenamiento.refreshToken, 'REFRESH');
        expect(almacenamiento.vecesLimpiado, 0);
      });
    });

    test('un 401 al verificar la sesión (token inválido) sí limpia los tokens', () async {
      final almacenamiento = TokenStorageFalso()
        ..accessToken = 'ACCESS'
        ..refreshToken = 'REFRESH';
      final contenedor = _contenedor(
        ['cliente'],
        almacenamiento,
        errorAlObtenerUsuario: errorDio(DioExceptionType.badResponse, estado: 401),
      );

      await contenedor.read(authControllerProvider.notifier).restaurarSesion();

      expect(contenedor.read(authControllerProvider).estado, EstadoSesion.noAutenticado);
      expect(almacenamiento.accessToken, isNull);
      expect(almacenamiento.refreshToken, isNull);
    });
  });

  group('AuthController.restaurarSesion - multitenant', () {
    test('sin token no hay sesión y no se toca nada', () async {
      final almacenamiento = TokenStorageFalso();
      final contenedor = _contenedor(['cliente'], almacenamiento);

      await contenedor.read(authControllerProvider.notifier).restaurarSesion();

      expect(contenedor.read(authControllerProvider).estado, EstadoSesion.noAutenticado);
      expect(almacenamiento.vecesLimpiado, 0);
    });

    test('token pero sin tienda guardada: se limpian los tokens y queda noAutenticado', () async {
      final almacenamiento = TokenStorageFalso()
        ..accessToken = 'ACCESS'
        ..refreshToken = 'REFRESH';
      final contenedor = _contenedor(['cliente'], almacenamiento, sinTienda: true);

      await contenedor.read(authControllerProvider.notifier).restaurarSesion();

      final estado = contenedor.read(authControllerProvider);
      expect(estado.estado, EstadoSesion.noAutenticado);
      expect(estado.usuario, isNull);
      expect(almacenamiento.accessToken, isNull);
      expect(almacenamiento.refreshToken, isNull);
      expect(almacenamiento.vecesLimpiado, 1);
    });

    test('con tienda guardada y el mismo empresa_codigo la sesión se restaura', () async {
      final almacenamiento = TokenStorageFalso()
        ..accessToken = 'ACCESS'
        ..refreshToken = 'REFRESH';
      final contenedor = _contenedor(['cliente'], almacenamiento, empresaCodigo: 'chaski');

      await contenedor.read(authControllerProvider.notifier).restaurarSesion();

      final estado = contenedor.read(authControllerProvider);
      expect(estado.estaAutenticado, isTrue);
      expect(estado.usuario?.empresaCodigo, 'chaski');
      expect(almacenamiento.vecesLimpiado, 0);
    });

    test('/auth/yo con un empresa_codigo distinto de la tienda: se limpian los tokens', () async {
      final almacenamiento = TokenStorageFalso()
        ..accessToken = 'ACCESS'
        ..refreshToken = 'REFRESH';
      final contenedor = _contenedor(['cliente'], almacenamiento, empresaCodigo: 'andina');

      await contenedor.read(authControllerProvider.notifier).restaurarSesion();

      final estado = contenedor.read(authControllerProvider);
      expect(estado.estado, EstadoSesion.noAutenticado);
      expect(estado.usuario, isNull);
      expect(almacenamiento.accessToken, isNull);
      expect(almacenamiento.refreshToken, isNull);
      expect(almacenamiento.vecesLimpiado, 1);
    });

    test('un usuario sin empresa_codigo en /auth/yo no se descarta por la tienda', () async {
      final almacenamiento = TokenStorageFalso()
        ..accessToken = 'ACCESS'
        ..refreshToken = 'REFRESH';
      final contenedor = _contenedor(['cliente'], almacenamiento, empresaCodigo: null);

      await contenedor.read(authControllerProvider.notifier).restaurarSesion();

      expect(contenedor.read(authControllerProvider).estaAutenticado, isTrue);
      expect(almacenamiento.vecesLimpiado, 0);
    });

    // Ajuste E18b: el personal con permisos de venta ya no se descarta (ver arriba); sigue descartándose quien no es
    // cliente ni tiene `ventas.presencial` / `reservas.gestionar_sucursal` (p. ej. el proveedor), con tokens limpios.
    test('una cuenta sin acceso a la app (proveedor) se descarta aunque la tienda coincida', () async {
      final almacenamiento = TokenStorageFalso()..accessToken = 'ACCESS';
      final contenedor = _contenedor(['proveedor'], almacenamiento, empresaCodigo: 'chaski');

      await contenedor.read(authControllerProvider.notifier).restaurarSesion();

      expect(contenedor.read(authControllerProvider).estado, EstadoSesion.noAutenticado);
      expect(almacenamiento.accessToken, isNull);
    });
  });
}
