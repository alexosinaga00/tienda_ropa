/// Cómo volvió el cliente de la página de PayPal al guardar su medio de pago.
sealed class RetornoPaypal {
  const RetornoPaypal();
}

/// Aprobó: PayPal devolvió el `approval_token_id` (el mismo token de preparación) para confirmar con el servidor.
class RetornoAprobado extends RetornoPaypal {
  const RetornoAprobado(this.token);

  final String token;
}

/// Canceló en PayPal (la URL de retorno trae `cancelado=1`).
class RetornoCancelado extends RetornoPaypal {
  const RetornoCancelado();
}

/// Volvió a la URL de retorno pero sin el token ni la marca de cancelado.
class RetornoSinDatos extends RetornoPaypal {
  const RetornoSinDatos();
}

/// La ruta a la que el servidor manda a PayPal a devolver al cliente: `.../t/<codigo>/mi-cuenta/paypal-guardado`. El
/// servidor arma la URL completa; la app solo la reconoce por su final, sea cual sea el dominio.
const rutaRetornoPaypal = '/mi-cuenta/paypal-guardado';

/// Si [url] es la de retorno de PayPal devuelve cómo salió; si es cualquier otra página (la de PayPal mismo), null.
RetornoPaypal? interpretarRetornoPaypal(String url) {
  final uri = Uri.tryParse(url);
  if (uri == null || !uri.path.endsWith(rutaRetornoPaypal)) return null;
  if (uri.queryParameters['cancelado'] == '1') return const RetornoCancelado();
  final token = uri.queryParameters['approval_token_id'];
  if (token != null && token.isNotEmpty) return RetornoAprobado(token);
  return const RetornoSinDatos();
}

/// Solo se abre en el WebView una dirección https (o http en pruebas locales); nada de `javascript:` ni `file:`.
bool esUrlAbrible(String url) {
  final uri = Uri.tryParse(url);
  return uri != null && (uri.scheme == 'https' || uri.scheme == 'http') && uri.host.isNotEmpty;
}
