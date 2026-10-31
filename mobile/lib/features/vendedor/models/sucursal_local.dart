/// Una sucursal de la copia local. El depósito también viene aquí (`esDeposito`): la pantalla decide si lo ofrece.
class SucursalLocal {
  const SucursalLocal({
    required this.id,
    required this.codigo,
    required this.nombre,
    required this.direccion,
    required this.esDeposito,
    required this.activo,
  });

  final int id;
  final String codigo;
  final String nombre;
  final String direccion;
  final bool esDeposito;
  final bool activo;

  @override
  String toString() => 'SucursalLocal($id, $nombre)';
}
