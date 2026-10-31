import '../../../core/network/api_client.dart';
import '../models/voz_resultado.dart';

class VozRepository {
  /// [invitado]: sin sesión se usa la ruta pública de la tienda elegida (`/public/{codigo}/ia/voz`); con sesión, la
  /// empresa sale del token.
  VozRepository(this._api, {this._invitado = false});

  final ApiClient _api;
  final bool _invitado;

  Future<VozResultado> buscarPorVoz(String texto) {
    return _api.postObjeto<VozResultado>(
      '/ia/voz',
      cuerpo: {'texto': texto},
      desde: VozResultado.fromJson,
      publica: _invitado,
    );
  }
}
