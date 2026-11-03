/// Un cliente de la copia local que el servidor conoce (tiene [servidorId]): el único tipo que una venta o una reserva sin
/// conexión puede usar, porque el backend pide el `cliente_id` del servidor.
class ClienteLocal {
  const ClienteLocal({required this.id, required this.servidorId, required this.nombre, this.apellido, this.ciNit});

  /// El id en la base del teléfono (`cliente_minimo.id`): es el que lleva `clienteMinimoId` al registrar.
  final int id;

  /// El id en el servidor: el que viaja en el payload.
  final int servidorId;
  final String nombre;
  final String? apellido;
  final String? ciNit;

  /// "Nombre Apellido", o solo el nombre si no tiene apellido.
  String get nombreCompleto {
    final a = apellido?.trim();
    return a == null || a.isEmpty ? nombre : '$nombre $a';
  }

  @override
  bool operator ==(Object other) =>
      other is ClienteLocal &&
      other.id == id &&
      other.servidorId == servidorId &&
      other.nombre == nombre &&
      other.apellido == apellido &&
      other.ciNit == ciNit;

  @override
  int get hashCode => Object.hash(id, servidorId, nombre, apellido, ciNit);

  @override
  String toString() => 'ClienteLocal($id, servidor $servidorId, $nombreCompleto)';
}
