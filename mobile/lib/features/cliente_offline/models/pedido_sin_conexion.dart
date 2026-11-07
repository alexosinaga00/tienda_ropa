import 'dart:convert';

import '../../../core/utils/fecha_servidor.dart';

/// `pendiente`: esperando salir; `enviando`: la petición está en el aire; `cobrado` y `rechazado`: decisión final del
/// servidor; `vencido`: pasaron más de 7 días sin enviarse (decisión local, no se envía nunca).
enum EstadoPedidoLocal {
  pendiente,
  enviando,
  cobrado,
  rechazado,
  vencido;

  /// Lo que todavía no salió o está saliendo: lo que cuenta como "pedido sin enviar".
  bool get sinEnviar => this == pendiente || this == enviando;

  /// Decisión final: ya no cambia de estado.
  bool get esFinal => this == cobrado || this == rechazado || this == vencido;

  String get etiqueta => switch (this) {
    pendiente => 'Pendiente de envío',
    enviando => 'Enviando…',
    cobrado => 'Cobrado',
    rechazado => 'Rechazado',
    vencido => 'Vencido',
  };

  static EstadoPedidoLocal desdeNombre(String nombre) =>
      EstadoPedidoLocal.values.firstWhere((e) => e.name == nombre, orElse: () => EstadoPedidoLocal.pendiente);
}

/// Una prenda de un pedido en cola, con lo necesario para mostrarla sin red. El precio es el que el cliente vio.
class LineaPedidoLocal {
  const LineaPedidoLocal({
    required this.varianteId,
    required this.cantidad,
    required this.productoNombre,
    required this.precioUnitarioCentavos,
    this.talla,
    this.color,
    this.imagen,
  });

  factory LineaPedidoLocal.fromJson(Map<String, dynamic> json) => LineaPedidoLocal(
    varianteId: json['variante_id'] as int,
    cantidad: json['cantidad'] as int,
    productoNombre: json['producto_nombre'] as String,
    talla: json['talla'] as String?,
    color: json['color'] as String?,
    precioUnitarioCentavos: json['precio_centavos'] as int,
    imagen: json['imagen'] as String?,
  );

  final int varianteId;
  final int cantidad;
  final String productoNombre;
  final String? talla;
  final String? color;
  final int precioUnitarioCentavos;
  final String? imagen;

  /// "M · Azul" (o lo que haya); vacío si no hay talla ni color.
  String get detalle => [?talla, ?color].join(' · ');

  Map<String, dynamic> toJson() => {
    'variante_id': varianteId,
    'cantidad': cantidad,
    'producto_nombre': productoNombre,
    'talla': talla,
    'color': color,
    'precio_centavos': precioUnitarioCentavos,
    'imagen': imagen,
  };
}

/// Un pedido hecho sin conexión que se paga con el PayPal guardado al volver la red.
class PedidoSinConexion {
  const PedidoSinConexion({
    required this.empresaId,
    required this.usuarioId,
    required this.operacionId,
    required this.estado,
    required this.sucursalId,
    required this.sucursalNombre,
    required this.costoEnvioCentavos,
    required this.lineas,
    required this.totalMaximoCentavos,
    required this.fechaPedido,
    required this.creadoEn,
    this.intentos = 0,
    this.ultimoIntentoEn,
    this.proximoIntentoEn,
    this.ultimoError,
    this.motivo,
    this.mensaje,
    this.ventaId,
    this.codigoVenta,
    this.totalCentavos,
    this.totalUsd,
    this.resueltoEn,
    this.visto = false,
  });

  factory PedidoSinConexion.desdeFila(Map<String, Object?> fila) => PedidoSinConexion(
    empresaId: fila['empresa_id']! as int,
    usuarioId: fila['usuario_id']! as int,
    operacionId: fila['operacion_id']! as String,
    estado: EstadoPedidoLocal.desdeNombre(fila['estado']! as String),
    sucursalId: fila['sucursal_id']! as int,
    sucursalNombre: fila['sucursal_nombre']! as String,
    costoEnvioCentavos: fila['costo_envio_centavos']! as int,
    lineas: [
      for (final l in jsonDecode(fila['lineas_json']! as String) as List<dynamic>)
        LineaPedidoLocal.fromJson(l as Map<String, dynamic>),
    ],
    totalMaximoCentavos: fila['total_maximo_centavos']! as int,
    fechaPedido: fila['fecha_pedido']! as String,
    creadoEn: instanteUtcDelServidor(fila['creado_en']! as String),
    intentos: fila['intentos']! as int,
    ultimoIntentoEn: _fecha(fila['ultimo_intento_en']),
    proximoIntentoEn: _fecha(fila['proximo_intento_en']),
    ultimoError: fila['ultimo_error'] as String?,
    motivo: fila['motivo'] as String?,
    mensaje: fila['mensaje'] as String?,
    ventaId: fila['venta_id'] as int?,
    codigoVenta: fila['codigo_venta'] as String?,
    totalCentavos: fila['total_centavos'] as int?,
    totalUsd: fila['total_usd'] as String?,
    resueltoEn: _fecha(fila['resuelto_en']),
    visto: (fila['visto']! as int) == 1,
  );

  final int empresaId;
  final int usuarioId;

  /// UUID v4: se manda igual en cada reintento.
  final String operacionId;
  final EstadoPedidoLocal estado;
  final int sucursalId;
  final String sucursalNombre;
  final int costoEnvioCentavos;
  final List<LineaPedidoLocal> lineas;

  /// El tope que el cliente aceptó ("Se cobrará hasta Bs X").
  final int totalMaximoCentavos;

  /// ISO 8601 en UTC con `Z` (informativa para el servidor).
  final String fechaPedido;
  final DateTime creadoEn;
  final int intentos;
  final DateTime? ultimoIntentoEn;
  final DateTime? proximoIntentoEn;
  final String? ultimoError;
  final String? motivo;
  final String? mensaje;
  final int? ventaId;
  final String? codigoVenta;
  final int? totalCentavos;
  final String? totalUsd;
  final DateTime? resueltoEn;

  /// Falso mientras el cliente no haya visto el resultado (cobrado, rechazado o vencido).
  final bool visto;

  int get cantidadPrendas => lineas.fold(0, (suma, l) => suma + l.cantidad);

  Map<String, Object?> aFila() => {
    'empresa_id': empresaId,
    'usuario_id': usuarioId,
    'operacion_id': operacionId,
    'estado': estado.name,
    'sucursal_id': sucursalId,
    'sucursal_nombre': sucursalNombre,
    'costo_envio_centavos': costoEnvioCentavos,
    'lineas_json': jsonEncode([for (final l in lineas) l.toJson()]),
    'total_maximo_centavos': totalMaximoCentavos,
    'fecha_pedido': fechaPedido,
    'creado_en': creadoEn.toUtc().toIso8601String(),
    'intentos': intentos,
    'ultimo_intento_en': ultimoIntentoEn?.toUtc().toIso8601String(),
    'proximo_intento_en': proximoIntentoEn?.toUtc().toIso8601String(),
    'ultimo_error': ultimoError,
    'motivo': motivo,
    'mensaje': mensaje,
    'venta_id': ventaId,
    'codigo_venta': codigoVenta,
    'total_centavos': totalCentavos,
    'total_usd': totalUsd,
    'resuelto_en': resueltoEn?.toUtc().toIso8601String(),
    'visto': visto ? 1 : 0,
  };
}

DateTime? _fecha(Object? valor) => leerInstanteUtc(valor);
