import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/providers.dart';
import 'package:mobile/features/auth/data/auth_repository.dart';
import 'package:mobile/features/auth/models/usuario.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/auth/state/auth_state.dart';

import '../../helpers/token_storage_falso.dart';

/// Repositorio sin red: el login guarda tokens en el almacenamiento falso y `/auth/yo` devuelve un usuario con los
/// roles dados (o falla, para simular credenciales inválidas).
class _RepositorioFalso extends AuthRepository {
  _RepositorioFalso(this.roles, this.almacenamiento, {this.falla = false})
    : super(dio: Dio(), tokenStorage: almacenamiento);

  final List<String> roles;
  final TokenStorageFalso almacenamiento;
  final bool falla;

  @override
  Future<void> login({required String email, required String password}) async {
    if (falla) throw Exception('401');
    await almacenamiento.guardar(accessToken: 'ACCESS', refreshToken: 'REFRESH');
  }

  @override
  Future<Usuario> obtenerUsuarioActual() async {
    if (falla) throw Exception('401');
    return Usuario(
      id: 1,
      nombre: 'Prueba',
      apellido: 'Rol',
      email: 'prueba@example.com',
      telefono: null,
      activo: true,
      roles: roles,
      permisos: const [],
    );
  }
}

ProviderContainer _contenedor(List<String> roles, TokenStorageFalso almacenamiento, {bool falla = false}) {
  final contenedor = ProviderContainer(
    overrides: [
      tokenStorageProvider.overrideWithValue(almacenamiento),
      authRepositoryProvider.overrideWithValue(_RepositorioFalso(roles, almacenamiento, falla: falla)),
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

    test('una sesión guardada de personal no se restaura y se limpian los tokens', () async {
      final almacenamiento = TokenStorageFalso()
        ..accessToken = 'ACCESS'
        ..refreshToken = 'REFRESH';
      final contenedor = _contenedor(['encargado_sucursal'], almacenamiento);

      await contenedor.read(authControllerProvider.notifier).restaurarSesion();

      expect(contenedor.read(authControllerProvider).estado, EstadoSesion.noAutenticado);
      expect(almacenamiento.accessToken, isNull);
      expect(almacenamiento.refreshToken, isNull);
    });
  });
}
