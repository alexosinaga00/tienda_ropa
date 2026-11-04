import '../../../core/utils/fecha_servidor.dart';

/// `GET /ventas/{id}/plazo-cambio`: hasta cuándo se puede cambiar o devolver una compra. Lo calcula el servidor (el
/// reloj del teléfono no decide).
class PlazoCambio {
  const PlazoCambio({required this.vigente, required this.venceEn, required this.plazoHoras});

  factory PlazoCambio.fromJson(Map<String, dynamic> json) => PlazoCambio(
    vigente: json['vigente'] as bool,
    venceEn: fechaDelServidor(json['vence_en'] as String),
    plazoHoras: json['plazo_horas'] as int,
  );

  final bool vigente;

  /// En hora local.
  final DateTime venceEn;
  final int plazoHoras;
}
