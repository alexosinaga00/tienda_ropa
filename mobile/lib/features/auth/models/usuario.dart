/// Qué experiencia le corresponde a la cuenta en la app: la del cliente, la del personal que vende, o ninguna (el
/// proveedor y el superadministrador trabajan en el panel web).
enum ModoApp { cliente, vendedor, sinAcceso }

class Usuario {
  const Usuario({
    required this.id,
    required this.nombre,
    required this.apellido,
    required this.email,
    required this.telefono,
    required this.activo,
    required this.roles,
    required this.permisos,
    this.empresaId,
    this.empresaCodigo,
    this.empresaNombre,
  });

  factory Usuario.fromJson(Map<String, dynamic> json) {
    return Usuario(
      id: json['id'] as int,
      nombre: json['nombre'] as String,
      apellido: json['apellido'] as String,
      email: json['email'] as String,
      telefono: json['telefono'] as String?,
      activo: json['activo'] as bool,
      roles: (json['roles'] as List<dynamic>).cast<String>(),
      permisos: (json['permisos'] as List<dynamic>? ?? const []).cast<String>(),
      // `/auth/yo` los trae; null para el superadministrador (no pertenece a ninguna empresa) o si faltan.
      empresaId: json['empresa_id'] as int?,
      empresaCodigo: json['empresa_codigo'] as String?,
      empresaNombre: json['empresa_nombre'] as String?,
    );
  }

  final int id;
  final String nombre;
  final String apellido;
  final String email;
  final String? telefono;
  final bool activo;
  final List<String> roles;
  final List<String> permisos;

  /// La empresa a la que pertenece la cuenta (`/auth/yo`).
  final int? empresaId;
  final String? empresaCodigo;
  final String? empresaNombre;

  /// Basta con tener el rol `cliente`, aunque tenga además otro.
  bool get esCliente => roles.contains('cliente');

  /// El modo se decide por PERMISOS, no por el nombre del rol: el sistema no tiene un rol llamado "vendedor". Quien
  /// puede vender en caja o atender reservas de su sucursal (cajero, encargado y administrador) entra como vendedor.
  ModoApp get modo {
    if (esCliente) return ModoApp.cliente;
    if (permisos.contains('ventas.presencial') || permisos.contains('reservas.gestionar_sucursal')) {
      return ModoApp.vendedor;
    }
    return ModoApp.sinAcceso;
  }

  /// Para guardar el último perfil verificado (sin contraseñas ni tokens).
  Map<String, dynamic> toJson() => {
    'id': id,
    'nombre': nombre,
    'apellido': apellido,
    'email': email,
    'telefono': telefono,
    'activo': activo,
    'roles': roles,
    'permisos': permisos,
    'empresa_id': empresaId,
    'empresa_codigo': empresaCodigo,
    'empresa_nombre': empresaNombre,
  };
}
