import '../../../core/network/api_client.dart';
import '../models/recomendacion_item.dart';

class RecomendadorRepository {
  /// [invitado]: sin sesión se usa la ruta pública de la tienda elegida (`/public/{codigo}/ia/recomendaciones`); con
  /// sesión, la empresa sale del token.
  RecomendadorRepository(this._api, {this._invitado = false});

  final ApiClient _api;
  final bool _invitado;

  Future<List<RecomendacionItem>> obtenerRecomendaciones({int? excluirProductoId}) async {
    final respuesta = await _api.postObjeto<List<RecomendacionItem>>(
      '/ia/recomendaciones',
      query: {'excluir_producto_id': ?excluirProductoId},
      desde: (json) => (json['recomendaciones'] as List<dynamic>)
          .map((e) => RecomendacionItem.fromJson(e as Map<String, dynamic>))
          .toList(),
      publica: _invitado,
    );
    return respuesta;
  }
}
