import '../network/api_client.dart';
import '../network/error_app.dart';
import 'contrato_sync.dart';

/// El único punto de red del motor de sincronización. Los falsos de prueba implementan esta interfaz.
///
/// Todo error sale como `ErrorApp` (lo traduce el `ApiClient`): el motor decide qué hacer según su tipo.
abstract interface class SincronizacionApi {
  /// POST /sincronizacion/lote. Respuesta 200 con un resultado por operación.
  Future<RespuestaLote> enviarLote(LoteEnvio lote);

  /// GET /sincronizacion/operaciones/{id}: cómo está UNA operación del propio usuario (para saber si un encargado resolvió un
  /// conflicto), sin volver a enviarla. Null si el servidor no la conoce (404).
  Future<ResultadoOperacionSync?> consultar(String operacionId);
}

class SincronizacionApiHttp implements SincronizacionApi {
  SincronizacionApiHttp(this._api);

  final ApiClient _api;

  @override
  Future<RespuestaLote> enviarLote(LoteEnvio lote) {
    return _api.postObjeto<RespuestaLote>('/sincronizacion/lote', cuerpo: lote.toJson(), desde: RespuestaLote.fromJson);
  }

  @override
  Future<ResultadoOperacionSync?> consultar(String operacionId) async {
    try {
      return await _api.getObjeto<ResultadoOperacionSync>(
        '/sincronizacion/operaciones/${Uri.encodeComponent(operacionId)}',
        desde: ResultadoOperacionSync.fromJson,
      );
    } on ErrorApp catch (e) {
      // 404: el servidor no la conoce (nunca llegó). Cualquier otro error se propaga al motor.
      if (e.tipo == TipoErrorApp.noEncontrado) return null;
      rethrow;
    }
  }
}
