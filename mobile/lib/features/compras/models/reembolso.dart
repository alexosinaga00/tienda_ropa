import '../../../core/utils/dinero.dart';
import '../../../core/utils/fecha_servidor.dart';

/// Los estados de un reembolso que manda el backend.
const estadoReembolsoCompletado = 'reembolsado';

/// Dinero que la tienda le devuelve a quien compró: una devolución SIN cambio de prenda o un pago anulado. Un cambio de
/// talla o color no mueve dinero y no crea reembolsos.
///
/// El cliente solo ve dos situaciones: "Reembolsado" y "En proceso". Un reembolso `fallido` (o cualquier estado que la
/// app no conozca) se le muestra como "En proceso": el detalle técnico del fallo nunca llega a la pantalla.
class Reembolso {
  const Reembolso({
    required this.id,
    required this.ventaId,
    required this.metodo,
    required this.monto,
    required this.estado,
    required this.creadoEn,
    this.devolucionId,
    this.pagoId,
    this.sucursalId,
    this.montoUsd,
    this.completadoEn,
  });

  /// Lectura defensiva: lo que falta o viene raro queda en un valor neutro en vez de romper la pantalla. Los montos
  /// viajan como texto y se quedan como texto (se formatean con el helper de dinero, sin pasar por `double`).
  factory Reembolso.fromJson(Map<String, dynamic> json) => Reembolso(
    id: (json['id'] as num?)?.toInt() ?? 0,
    devolucionId: (json['devolucion_id'] as num?)?.toInt(),
    pagoId: (json['pago_id'] as num?)?.toInt(),
    ventaId: (json['venta_id'] as num?)?.toInt() ?? 0,
    sucursalId: (json['sucursal_id'] as num?)?.toInt(),
    metodo: (json['metodo'] as String?) ?? '',
    monto: json['monto']?.toString() ?? '',
    montoUsd: json['monto_usd']?.toString(),
    estado: (json['estado'] as String?) ?? '',
    creadoEn: leerInstanteUtc(json['creado_en'])?.toLocal() ?? DateTime.fromMillisecondsSinceEpoch(0),
    completadoEn: leerInstanteUtc(json['completado_en'])?.toLocal(),
  );

  final int id;
  final int? devolucionId;
  final int? pagoId;
  final int ventaId;
  final int? sucursalId;

  /// `efectivo`, `qr`, `qr_online`, `tarjeta`, `transferencia`, `paypal`...
  final String metodo;

  /// En bolivianos, como texto decimal ("25.00").
  final String monto;
  final String? montoUsd;

  /// `pendiente`, `reembolsado` o `fallido`.
  final String estado;

  /// En hora local.
  final DateTime creadoEn;
  final DateTime? completadoEn;

  bool get estaReembolsado => estado == estadoReembolsoCompletado;

  /// "Reembolsado" o "En proceso" (lo pendiente, lo fallido y lo desconocido).
  String get etiquetaEstado => estaReembolsado ? 'Reembolsado' : 'En proceso';

  /// "Bs 25.00". Si el monto no es un decimal válido se muestra tal cual, sin romper.
  String get montoTexto {
    try {
      return formatearBs(aCentavos(monto));
    } on FormatException {
      return monto.isEmpty ? 'Bs' : 'Bs $monto';
    }
  }

  /// Cuándo pasó: el momento en que se completó o, si sigue en proceso, cuando se pidió. En hora local.
  DateTime get fecha => estaReembolsado ? (completadoEn ?? creadoEn) : creadoEn;

  /// Cómo se devuelve el dinero: "en efectivo, en la tienda", "a tu PayPal"...
  String get comoSeDevuelve => comoSeDevuelveElDinero(metodo);
}

/// El medio por el que vuelve el dinero, dicho para el cliente.
String comoSeDevuelveElDinero(String metodo) => switch (metodo) {
  'efectivo' => 'en efectivo, en la tienda',
  'paypal' => 'a tu PayPal',
  'qr' || 'qr_online' => 'por QR',
  'tarjeta' => 'a tu tarjeta',
  'transferencia' => 'por transferencia',
  _ => 'por el mismo medio con que pagaste',
};
