import 'dart:convert';

import '../../../core/utils/fecha_servidor.dart';

/// `GET /metodos-pago/paypal` y `POST /metodos-pago/paypal/confirmar`. El servidor es el dueño de estos datos: la app
/// solo ve si hay un PayPal guardado y su correo ENMASCARADO ("j***@gmail.com"). Nunca llega ni se guarda un token de
/// PayPal ni un dato de tarjeta.
class MetodoPagoPaypal {
  const MetodoPagoPaypal({required this.guardado, this.correoPaypal, this.guardadoEn});

  factory MetodoPagoPaypal.fromJson(Map<String, dynamic> json) {
    final guardadoEn = json['guardado_en'] as String?;
    return MetodoPagoPaypal(
      guardado: json['guardado'] as bool,
      correoPaypal: json['correo_paypal'] as String?,
      guardadoEn: guardadoEn == null ? null : fechaDelServidor(guardadoEn),
    );
  }

  static const sinGuardar = MetodoPagoPaypal(guardado: false);

  final bool guardado;
  final String? correoPaypal;
  final DateTime? guardadoEn;
}

/// `POST /metodos-pago/paypal/iniciar`.
class PaypalIniciarRespuesta {
  const PaypalIniciarRespuesta({required this.urlAprobacion, required this.tokenPreparacion});

  factory PaypalIniciarRespuesta.fromJson(Map<String, dynamic> json) => PaypalIniciarRespuesta(
    urlAprobacion: json['url_aprobacion'] as String,
    tokenPreparacion: json['token_preparacion'] as String,
  );

  final String urlAprobacion;
  final String tokenPreparacion;
}

/// Lo que el teléfono recuerda del método de pago para decidir SIN red: solo "tiene PayPal guardado" y el correo
/// enmascarado que devolvió el servidor, con el momento en que se confirmó.
class MetodoPagoRecordado {
  const MetodoPagoRecordado({required this.guardado, required this.verificadoEn, this.correoPaypal, this.guardadoEn});

  factory MetodoPagoRecordado.desde(MetodoPagoPaypal estado, DateTime ahora) => MetodoPagoRecordado(
    guardado: estado.guardado,
    correoPaypal: estado.guardado ? estado.correoPaypal : null,
    guardadoEn: estado.guardado ? estado.guardadoEn : null,
    verificadoEn: ahora,
  );

  factory MetodoPagoRecordado.fromJson(Map<String, dynamic> json) => MetodoPagoRecordado(
    guardado: json['guardado'] as bool,
    correoPaypal: json['correo_paypal'] as String?,
    guardadoEn: leerInstanteUtc(json['guardado_en']),
    verificadoEn: instanteUtcDelServidor(json['verificado_en'] as String),
  );

  /// Lee lo guardado en `cli_meta`; algo dañado se descarta (null) en vez de romper la pantalla.
  static MetodoPagoRecordado? desdeTexto(String? texto) {
    if (texto == null) return null;
    try {
      return MetodoPagoRecordado.fromJson(jsonDecode(texto) as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }

  final bool guardado;
  final String? correoPaypal;
  final DateTime? guardadoEn;
  final DateTime verificadoEn;

  String aTexto() => jsonEncode({
    'guardado': guardado,
    'correo_paypal': correoPaypal,
    'guardado_en': guardadoEn?.toUtc().toIso8601String(),
    'verificado_en': verificadoEn.toUtc().toIso8601String(),
  });
}
