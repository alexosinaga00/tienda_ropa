class Envio {
  const Envio({
    required this.id,
    required this.ventaId,
    required this.direccionId,
    required this.zonaEnvioId,
    required this.costo,
    required this.estado,
    this.repartidor,
    this.fechaEntrega,
  });

  factory Envio.fromJson(Map<String, dynamic> json) => Envio(
    id: json['id'] as int,
    ventaId: json['venta_id'] as int,
    direccionId: json['direccion_id'] as int,
    zonaEnvioId: json['zona_envio_id'] as int,
    costo: double.parse(json['costo'].toString()),
    estado: json['estado'] as String,
    repartidor: json['repartidor'] as String?,
    fechaEntrega: _fecha(json['fecha_entrega']),
  );

  final int id;
  final int ventaId;
  final int direccionId;
  final int zonaEnvioId;
  final double costo;

  /// programado | en_ruta | entregado | fallido
  final String estado;
  final String? repartidor;
  final DateTime? fechaEntrega;

  /// El backend guarda las fechas en UTC y las manda sin zona
  /// ("2026-09-20T16:52:29"): sin la 'Z', Dart las tomaría como hora local.
  static DateTime? _fecha(Object? valor) {
    if (valor is! String) return null;
    final tieneZona = valor.endsWith('Z') || RegExp(r'[+-]\d{2}:?\d{2}$').hasMatch(valor);
    return DateTime.tryParse(tieneZona ? valor : '${valor}Z')?.toLocal();
  }
}

const etiquetasEstadoEnvio = {
  'programado': 'Programado',
  'en_ruta': 'En camino',
  'entregado': 'Entregado',
  'fallido': 'No se pudo entregar',
};
