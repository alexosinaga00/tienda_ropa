import '../../../core/network/api_client.dart';
import '../models/metodo_pago.dart';

/// El PayPal guardado del cliente (`/metodos-pago/paypal`). Todas las rutas exigen sesión (la empresa sale del token).
/// Los errores salen como `ErrorApp`: 409 `paypal_no_aprobado` si el cliente no aprobó, 503 `paypal_no_disponible` si
/// PayPal no responde, 404 si el token de preparación no es suyo.
class MetodoPagoRepository {
  MetodoPagoRepository(this._api);

  final ApiClient _api;

  static const _ruta = '/metodos-pago/paypal';

  Future<MetodoPagoPaypal> estado() => _api.getObjeto<MetodoPagoPaypal>(_ruta, desde: MetodoPagoPaypal.fromJson);

  /// Pide a PayPal guardar el medio de pago. Con `canal: "app"` el servidor devuelve a la app (no a la web) al terminar.
  Future<PaypalIniciarRespuesta> iniciar() => _api.postObjeto<PaypalIniciarRespuesta>(
    '$_ruta/iniciar',
    cuerpo: const {'canal': 'app'},
    desde: PaypalIniciarRespuesta.fromJson,
  );

  /// Cambia el token de preparación (el `approval_token_id` con que PayPal devolvió al cliente) por el medio de pago
  /// guardado. Es idempotente: confirmar dos veces el mismo token da lo mismo.
  Future<MetodoPagoPaypal> confirmar(String tokenPreparacion) => _api.postObjeto<MetodoPagoPaypal>(
    '$_ruta/confirmar',
    cuerpo: {'token_preparacion': tokenPreparacion},
    desde: MetodoPagoPaypal.fromJson,
  );

  /// Quita el PayPal guardado (204, idempotente).
  Future<void> quitar() => _api.eliminar(_ruta);
}
