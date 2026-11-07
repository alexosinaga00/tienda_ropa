import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/network/error_app.dart';
import '../../../core/network/mensaje_error.dart';
import '../../../core/network/providers.dart';
import '../../tienda/models/tienda.dart';
import '../../cliente_offline/models/linea_carrito_local.dart';
import '../../cliente_offline/state/base_cliente.dart';
import '../../tienda/state/tienda_controller.dart';
import '../../vendedor/state/pendientes_providers.dart';
import '../data/auth_repository.dart';
import '../models/usuario.dart';
import 'auth_state.dart';

const mensajeSoloClientes = 'Este acceso es para clientes. Si trabajas en una tienda, usa "Acceso del personal".';
const mensajeCuentaDeCliente = 'Esta cuenta es de cliente. Usa "Iniciar sesión".';
const mensajeSinAccesoMovil = 'Tu cuenta no tiene acceso a la app móvil. Usa el panel web.';
const mensajeCredencialesPersonal = 'Empresa, correo o contraseña incorrectos.';
const mensajePrimeraVezSinConexion = 'Sin conexión: la primera vez necesitas internet.';

/// Lo máximo que cerrar sesión espera a la limpieza de la base local.
const tiempoMaximoLimpiezaAlCerrar = Duration(seconds: 3);

/// Se lanza cuando inicia sesión alguien sin el rol `cliente`: la sesión no se abre.
class AccesoSoloClientesException implements Exception {
  const AccesoSoloClientesException();
}

/// Se lanza cuando el personal no puede entrar: la cuenta es de cliente o no tiene acceso a la app móvil.
class AccesoPersonalException implements Exception {
  const AccesoPersonalException(this.modo);

  final ModoApp modo;

  String get mensaje => modo == ModoApp.cliente ? mensajeCuentaDeCliente : mensajeSinAccesoMovil;
}

final authRepositoryProvider = Provider<AuthRepository>((ref) {
  // La tienda se lee al llamar (no se observa): la empresa del login y del registro es la que esté elegida en ese momento.
  return AuthRepository(
    dio: ref.watch(dioProvider),
    tokenStorage: ref.watch(tokenStorageProvider),
    codigoEmpresa: () => ref.read(tiendaCodigoProvider),
  );
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
        logout(motivo: MotivoCierre.vencida);
      }
    });
  }

  final Ref _ref;

  AuthRepository get _repository => _ref.read(authRepositoryProvider);

  Future<void> restaurarSesion() async {
    state = state.copyWith(estado: EstadoSesion.cargando);
    final tokenStorage = _ref.read(tokenStorageProvider);
    final sesionStorage = _ref.read(sesionStorageProvider);
    final token = await tokenStorage.leerAccessToken();

    if (token == null) {
      state = const AuthState(estado: EstadoSesion.noAutenticado);
      return;
    }

    // Sin tienda guardada no se sabe de qué empresa es la sesión (una instalación anterior al multitenant): se descarta.
    await _ref.read(tiendaControllerProvider.notifier).cargadaFuture;
    final tienda = _ref.read(tiendaActualProvider);
    if (tienda == null) {
      await _descartarSesionGuardada();
      return;
    }

    try {
      final usuario = await _repository.obtenerUsuarioActual();
      // Sin acceso a la app (proveedor, superadministrador) o de otra tienda que la elegida: nunca se mezclan empresas.
      if (usuario.modo == ModoApp.sinAcceso ||
          (usuario.empresaCodigo != null && usuario.empresaCodigo != tienda.codigo)) {
        await _descartarSesionGuardada();
        return;
      }
      if (usuario.modo == ModoApp.vendedor) await sesionStorage.guardarPerfil(usuario);
      if (usuario.modo == ModoApp.cliente) await _guardarPerfilCliente(usuario);
      state = AuthState(estado: EstadoSesion.autenticado, usuario: usuario);
    } catch (e) {
      if (esSinConexion(e) || esErrorDeServidor(e)) {
        // No se pudo verificar la sesión (sin red, timeout o 5xx): eso NO es un token inválido. Se conservan los tokens
        // para que la próxima apertura con conexión la restaure.
        final perfil = await sesionStorage.leerPerfil();
        if (perfil != null && perfil.modo == ModoApp.vendedor && perfil.empresaCodigo == tienda.codigo) {
          // El personal debe poder abrir la app sin red: sigue adentro con el último perfil, marcado sin verificar.
          state = AuthState(estado: EstadoSesion.autenticado, usuario: perfil, verificada: false);
          return;
        }
        // Un cliente que ya había entrado a ESTA tienda también: sigue adentro con su último perfil para ver su carrito
        // y sus pedidos guardados. El servidor vuelve a validar la sesión en cuanto hay red (`verificarSesion`).
        final perfilCliente = await sesionStorage.leerPerfilCliente();
        if (perfilCliente != null &&
            perfilCliente.modo == ModoApp.cliente &&
            perfilCliente.empresaCodigo == tienda.codigo) {
          state = AuthState(estado: EstadoSesion.autenticado, usuario: perfilCliente, verificada: false);
          return;
        }
        // Sin perfil guardado queda como invitado (catálogo público) sin cerrar la sesión guardada.
        state = const AuthState(estado: EstadoSesion.noAutenticado);
        return;
      }
      await _descartarSesionGuardada();
    }
  }

  /// Guarda el perfil del cliente para reabrir la tienda sin red. Es un extra: si falla, entrar o restaurar sigue valiendo.
  Future<void> _guardarPerfilCliente(Usuario usuario) async {
    try {
      await _ref.read(sesionStorageProvider).guardarPerfilCliente(usuario);
    } catch (_) {
      // Sin perfil guardado, un cliente sin red queda como invitado, igual que antes.
    }
  }

  Future<void> _descartarSesionGuardada() async {
    await _ref.read(tokenStorageProvider).limpiar();
    await _ref.read(sesionStorageProvider).borrarPerfil();
    await _ref.read(sesionStorageProvider).borrarPerfilCliente();
    state = const AuthState(estado: EstadoSesion.noAutenticado);
  }

  /// Acceso de los CLIENTES (el de `login_screen.dart`): la empresa es la de la tienda elegida.
  Future<void> login({required String email, required String password}) async {
    state = state.copyWith(estado: EstadoSesion.cargando);
    try {
      await _repository.login(email: email, password: password);
      final usuario = await _repository.obtenerUsuarioActual();
      if (!usuario.esCliente) throw const AccesoSoloClientesException();
      await _guardarPerfilCliente(usuario);
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

  /// Acceso del PERSONAL (cajero, encargado, administrador): la empresa la escribe la persona (nombre o código). Solo
  /// entra quien tiene el modo vendedor; si la cuenta es de cliente o no tiene acceso a la app, la sesión que el login
  /// acaba de abrir se cierra y se explica por qué.
  Future<void> loginPersonal({required String empresa, required String email, required String password}) async {
    state = state.copyWith(estado: EstadoSesion.cargando);
    try {
      await _repository.login(email: email, password: password, empresa: empresa.trim());
      final usuario = await _repository.obtenerUsuarioActual();
      if (usuario.modo != ModoApp.vendedor) throw AccesoPersonalException(usuario.modo);
      // La tienda es la de la empresa de la cuenta (puede no ser la que estaba elegida).
      final tienda = await _tiendaDe(usuario);
      if (tienda != null) await _ref.read(tiendaControllerProvider.notifier).elegir(tienda);
      await _ref.read(sesionStorageProvider).guardarPerfil(usuario);
      state = AuthState(estado: EstadoSesion.autenticado, usuario: usuario);
    } on AccesoPersonalException catch (e) {
      await _repository.logout();
      state = AuthState(estado: EstadoSesion.noAutenticado, error: e.mensaje);
      rethrow;
    } catch (e) {
      await _repository.logout();
      state = AuthState(estado: EstadoSesion.noAutenticado, error: _mensajeDeLoginPersonal(e));
      rethrow;
    }
  }

  /// El logo y el color de la empresa se piden a la ruta pública; si no responde se usa lo mínimo que trae la cuenta.
  Future<Tienda?> _tiendaDe(Usuario usuario) async {
    final codigo = usuario.empresaCodigo ?? _ref.read(tiendaCodigoProvider) ?? '';
    if (codigo.isEmpty) return null; // sin código no hay tienda que elegir
    try {
      return await _ref.read(tiendaRepositoryProvider).obtener(codigo);
    } catch (_) {
      return Tienda(codigo: codigo, nombre: usuario.empresaNombre ?? codigo);
    }
  }

  String _mensajeDeLoginPersonal(Object e) {
    if (esSinConexion(e)) return mensajePrimeraVezSinConexion;
    final app = ErrorApp.desde(e);
    if (app.esFuncional) return app.mensaje;
    if (app.estado == 429 || app.tipo == TipoErrorApp.servidor) return mensajeDeError(e, app.mensaje);
    return mensajeCredencialesPersonal;
  }

  /// Vuelve a consultar al servidor una sesión restaurada sin red (`verificada` falsa), p. ej. cuando regresa la
  /// conexión. Si el servidor la rechaza (401 o 403 después del refresh) la sesión venció; sin conexión no cambia nada.
  Future<void> verificarSesion() async {
    final actual = state;
    if (!actual.estaAutenticado || actual.verificada) return;
    try {
      final usuario = await _repository.obtenerUsuarioActual();
      if (!mounted) return;
      // Las sesiones sin verificar son del personal o de un cliente que reabrió la tienda sin red. Si el servidor ya no lo
      // reconoce con el mismo modo, la sesión no sirve.
      final modoGuardado = actual.usuario?.modo;
      if (usuario.modo != modoGuardado || (usuario.modo != ModoApp.vendedor && usuario.modo != ModoApp.cliente)) {
        await logout(motivo: MotivoCierre.vencida);
        return;
      }
      if (usuario.modo == ModoApp.vendedor) {
        await _ref.read(sesionStorageProvider).guardarPerfil(usuario);
      } else {
        await _guardarPerfilCliente(usuario);
      }
      state = AuthState(estado: EstadoSesion.autenticado, usuario: usuario);
    } catch (e) {
      final estado = ErrorApp.desde(e).estado;
      if (estado == 401 || estado == 403) await logout(motivo: MotivoCierre.vencida);
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

  /// Olvida por qué se cerró la sesión. Sin esto, a quien cerró sesión por vencimiento siendo personal el router lo
  /// seguiría mandando a "Acceso del personal"; "Soy cliente" y "Elegir otra tienda" lo llaman para poder salir de ahí.
  void olvidarMotivoCierre() {
    if (state.estado != EstadoSesion.noAutenticado || state.motivoCierre == null) return;
    state = const AuthState(estado: EstadoSesion.noAutenticado);
  }

  /// Depura la base local del personal que se va (ver `PoliticaLimpiezaLocal`). Cerrar sesión NUNCA debe fallar ni
  /// quedarse esperando por esto: cualquier error se ignora y a los pocos segundos se sigue sin esperar más.
  Future<void> _limpiarBaseLocal(Usuario usuario) async {
    final empresaId = usuario.empresaId;
    if (empresaId == null) return;
    try {
      await (() async {
        final politica = await _ref.read(politicaLimpiezaLocalProvider.future);
        await politica.alCerrarSesion(empresaId: empresaId, usuarioId: usuario.id);
      })().timeout(tiempoMaximoLimpiezaAlCerrar);
    } catch (_) {
      // La limpieza es de mejor esfuerzo: la próxima vez se vuelve a intentar.
    }
  }

  /// Limpia la base local del cliente que se va: el carrito local, lo recordado y los pedidos ya resueltos. Los pedidos
  /// SIN ENVIAR se conservan (salen cuando la misma cuenta vuelva a entrar); borrarlos es una decisión de la persona que
  /// toma ANTES, en el aviso de cerrar sesión. Igual que la del personal, nunca falla ni espera más de unos segundos.
  Future<void> _limpiarBaseCliente(Usuario usuario) async {
    final empresaId = usuario.empresaId;
    if (empresaId == null) return;
    try {
      await _ref
          .read(limpiezaClienteProvider)
          .alCerrarSesion(AlcanceCliente(empresaId: empresaId, usuarioId: usuario.id))
          .timeout(tiempoMaximoLimpiezaAlCerrar);
    } catch (_) {
      // La limpieza es de mejor esfuerzo: la próxima vez se vuelve a intentar.
    }
  }

  /// Cierra la sesión: borra los tokens y el perfil guardado, pero NO la tienda. Deja el motivo y el modo que tenía para
  /// que el router mande al personal cuya sesión venció a "Acceso del personal".
  Future<void> logout({MotivoCierre motivo = MotivoCierre.voluntario}) async {
    final usuarioPrevio = state.usuario;
    final modoPrevio = usuarioPrevio?.modo;
    if (modoPrevio == ModoApp.vendedor) await _limpiarBaseLocal(usuarioPrevio!);
    if (modoPrevio == ModoApp.cliente) await _limpiarBaseCliente(usuarioPrevio!);
    await _repository.logout();
    await _ref.read(sesionStorageProvider).borrarPerfil();
    try {
      await _ref.read(sesionStorageProvider).borrarPerfilCliente();
    } catch (_) {
      // Nada que borrar o no se pudo: el perfil del cliente solo sirve con tokens guardados.
    }
    if (!mounted) return;
    state = AuthState(estado: EstadoSesion.noAutenticado, motivoCierre: motivo, modoPrevio: modoPrevio);
  }
}
