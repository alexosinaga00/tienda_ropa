import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/network/providers.dart';
import '../data/auth_repository.dart';
import 'auth_state.dart';

const mensajeSoloClientes = 'Esta app es solo para clientes. Ingresá al panel web con tu cuenta de personal.';

/// Se lanza cuando inicia sesión alguien sin el rol `cliente`: la sesión no se abre.
class AccesoSoloClientesException implements Exception {
  const AccesoSoloClientesException();
}

final authRepositoryProvider = Provider<AuthRepository>((ref) {
  return AuthRepository(dio: ref.watch(dioProvider), tokenStorage: ref.watch(tokenStorageProvider));
});

final authControllerProvider = StateNotifierProvider<AuthController, AuthState>((ref) {
  return AuthController(ref);
});

class AuthController extends StateNotifier<AuthState> {
  AuthController(this._ref) : super(const AuthState.inicial()) {
    // El refresh falló de verdad (el refresh token también venció): cerrar
    // la sesión para que el router mande a login.
    _ref.listen<int>(sesionExpiradaProvider, (anterior, actual) {
      if (anterior != null && anterior != actual) {
        logout();
      }
    });
  }

  final Ref _ref;

  AuthRepository get _repository => _ref.read(authRepositoryProvider);

  Future<void> restaurarSesion() async {
    state = state.copyWith(estado: EstadoSesion.cargando);
    final tokenStorage = _ref.read(tokenStorageProvider);
    final token = await tokenStorage.leerAccessToken();

    if (token == null) {
      state = const AuthState(estado: EstadoSesion.noAutenticado);
      return;
    }

    try {
      final usuario = await _repository.obtenerUsuarioActual();
      if (!usuario.esCliente) {
        // Una sesión guardada de personal no se restaura: la app es solo para clientes.
        await tokenStorage.limpiar();
        state = const AuthState(estado: EstadoSesion.noAutenticado);
        return;
      }
      state = AuthState(estado: EstadoSesion.autenticado, usuario: usuario);
    } catch (_) {
      await tokenStorage.limpiar();
      state = const AuthState(estado: EstadoSesion.noAutenticado);
    }
  }

  Future<void> login({required String email, required String password}) async {
    state = state.copyWith(estado: EstadoSesion.cargando);
    try {
      await _repository.login(email: email, password: password);
      final usuario = await _repository.obtenerUsuarioActual();
      if (!usuario.esCliente) throw const AccesoSoloClientesException();
      state = AuthState(estado: EstadoSesion.autenticado, usuario: usuario);
    } on AccesoSoloClientesException {
      // Las credenciales eran correctas: se cierra la sesión que el login acaba de guardar y se explica por qué.
      await _repository.logout();
      state = const AuthState(estado: EstadoSesion.noAutenticado, error: mensajeSoloClientes);
      rethrow;
    } catch (_) {
      state = const AuthState(
        estado: EstadoSesion.noAutenticado,
        error: 'Email o contraseña incorrectos.',
      );
      rethrow;
    }
  }

  Future<void> registrar({
    required String nombre,
    required String apellido,
    required String email,
    required String password,
    String? telefono,
  }) async {
    state = state.copyWith(estado: EstadoSesion.cargando);
    try {
      await _repository.registro(
        nombre: nombre,
        apellido: apellido,
        email: email,
        password: password,
        telefono: telefono,
      );
      await login(email: email, password: password);
    } catch (_) {
      state = const AuthState(
        estado: EstadoSesion.noAutenticado,
        error: 'No se pudo completar el registro.',
      );
      rethrow;
    }
  }

  Future<void> logout() async {
    await _repository.logout();
    state = const AuthState(estado: EstadoSesion.noAutenticado);
  }
}
