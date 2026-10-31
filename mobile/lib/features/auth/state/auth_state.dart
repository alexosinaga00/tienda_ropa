import '../models/usuario.dart';

enum EstadoSesion { inicial, cargando, autenticado, noAutenticado }

/// Por qué se cerró la sesión: la persona lo pidió, o venció (el refresh token también caducó).
enum MotivoCierre { voluntario, vencida }

class AuthState {
  const AuthState({
    required this.estado,
    this.usuario,
    this.error,
    this.verificada = true,
    this.motivoCierre,
    this.modoPrevio,
  });

  const AuthState.inicial() : this(estado: EstadoSesion.inicial);

  final EstadoSesion estado;
  final Usuario? usuario;
  final String? error;

  /// Falso cuando la sesión se restauró sin poder consultar al servidor (el personal puede abrir la app sin red con el
  /// último perfil guardado). Pasa a verdadero cuando `verificarSesion` lo confirma.
  final bool verificada;

  /// Solo con la sesión cerrada: por qué se cerró y qué modo tenía. El router lo usa para mandar al personal cuya
  /// sesión venció a "Acceso del personal" en vez de al login de clientes.
  final MotivoCierre? motivoCierre;
  final ModoApp? modoPrevio;

  bool get estaAutenticado => estado == EstadoSesion.autenticado;

  bool tienePermiso(String codigo) => usuario?.permisos.contains(codigo) ?? false;

  AuthState copyWith({EstadoSesion? estado, Usuario? usuario, String? error}) {
    return AuthState(
      estado: estado ?? this.estado,
      usuario: usuario ?? this.usuario,
      error: error,
      verificada: verificada,
      motivoCierre: motivoCierre,
      modoPrevio: modoPrevio,
    );
  }
}
