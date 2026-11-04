import '../../../core/network/api_client.dart';
import '../models/solicitud_cambio.dart';

/// Las solicitudes de cambio de talla o color del cliente (`/solicitudes-cambio`). Los errores salen como `ErrorApp`:
/// 409 ya hay una pendiente para esa prenda (o venció el plazo), 429 demasiadas solicitudes, 400 cambio inválido
/// (otro producto, otro precio, la misma talla) y 404 compra o prenda que no existen.
class SolicitudesCambioRepository {
  SolicitudesCambioRepository(this._api);

  final ApiClient _api;

  Future<SolicitudCambio> solicitar({
    required int ventaId,
    required List<LineaSolicitudCambio> lineas,
    String? motivo,
  }) {
    final texto = motivo?.trim();
    return _api.postObjeto<SolicitudCambio>(
      '/solicitudes-cambio',
      cuerpo: {
        'venta_id': ventaId,
        if (texto != null && texto.isNotEmpty) 'motivo': texto,
        'detalle': [for (final l in lineas) l.toJson()],
      },
      desde: SolicitudCambio.fromJson,
    );
  }

  /// Las solicitudes del cliente, la más reciente primero. Con [ventaId], solo las de esa compra.
  Future<List<SolicitudCambio>> misSolicitudes({int? ventaId}) {
    return _api.getLista<SolicitudCambio>(
      '/solicitudes-cambio/mias',
      query: {'venta_id': ?ventaId},
      desde: SolicitudCambio.fromJson,
    );
  }

  Future<SolicitudCambio> cancelar(int solicitudId) {
    return _api.postObjeto<SolicitudCambio>(
      '/solicitudes-cambio/$solicitudId/cancelar',
      desde: SolicitudCambio.fromJson,
    );
  }
}
