import '../network/api_client.dart';

/// `POST /dispositivos-push` y `POST /dispositivos-push/baja`: el servidor guarda (o desactiva) el token de este teléfono
/// para mandarle avisos. Cualquier usuario con sesión, personal o cliente. Ambas son idempotentes y responden 204.
///
/// Recibe una función en vez del [ApiClient] para no armarlo hasta que haga falta (se reconstruye al cambiar de tienda).
class DispositivosPushRepository {
  DispositivosPushRepository(this._api);

  final ApiClient Function() _api;

  /// Alta del token; si ya era de otra cuenta, el servidor lo reasigna a la sesión actual.
  Future<void> registrar(String token) =>
      _api().postVacio('/dispositivos-push', cuerpo: {'token': token, 'plataforma': 'android'});

  /// Baja del token; el servidor solo lo desactiva si es de la cuenta de la sesión.
  Future<void> baja(String token) => _api().postVacio('/dispositivos-push/baja', cuerpo: {'token': token});
}
