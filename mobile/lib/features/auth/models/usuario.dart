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

  /// La app móvil es solo para clientes: el personal (administrador, encargado, cajero, proveedor) trabaja en el panel
  /// web. Basta con tener el rol `cliente`, aunque tenga además otro.
  bool get esCliente => roles.contains('cliente');
}
