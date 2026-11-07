import '../../../core/network/api_client.dart';
import '../models/pedido_diferido_api.dart';

/// El único punto de red de la cola de pedidos sin conexión. Los falsos de prueba implementan esta interfaz. Todo error
/// sale como `ErrorApp`: la cola decide qué hacer según su estado HTTP.
abstract interface class PedidosDiferidosApi {
  /// `POST /pedidos-diferidos`. Responde 200 con una decisión FINAL (cobrado o rechazado), también al reenviar la misma
  /// `operacion_id` (`duplicada: true`).
  Future<PedidoDiferidoRespuesta> enviar(PedidoDiferidoCrear pedido);
}

class PedidosDiferidosApiHttp implements PedidosDiferidosApi {
  PedidosDiferidosApiHttp(this._api);

  final ApiClient _api;

  @override
  Future<PedidoDiferidoRespuesta> enviar(PedidoDiferidoCrear pedido) {
    return _api.postObjeto<PedidoDiferidoRespuesta>(
      '/pedidos-diferidos',
      cuerpo: pedido.toJson(),
      desde: PedidoDiferidoRespuesta.fromJson,
    );
  }
}
