import 'package:dio/dio.dart';
import '../models/cotizacion_envio.dart';
import '../models/envio.dart';

class EnviosRepository {
  EnviosRepository(this._dio);

  final Dio _dio;

  Future<CotizacionEnvio> cotizar({required int direccionId, required int cantidadPrendas}) async {
    final respuesta = await _dio.post<Map<String, dynamic>>(
      '/envios/cotizar',
      data: {'direccion_id': direccionId, 'cantidad_prendas': cantidadPrendas},
    );
    return CotizacionEnvio.fromJson(respuesta.data!);
  }

  /// GET /envios/venta/{id}: el seguimiento del envío de una compra. Devuelve
  /// null si la compra no tiene envío (404); cualquier otro error se propaga.
  Future<Envio?> obtenerPorVenta(int ventaId) async {
    try {
      final respuesta = await _dio.get<Map<String, dynamic>>('/envios/venta/$ventaId');
      return Envio.fromJson(respuesta.data!);
    } on DioException catch (e) {
      if (e.response?.statusCode == 404) return null;
      rethrow;
    }
  }

  Future<Envio> crear({required int ventaId, required int direccionId}) async {
    final respuesta = await _dio.post<Map<String, dynamic>>(
      '/envios',
      data: {'venta_id': ventaId, 'direccion_id': direccionId},
    );
    return Envio.fromJson(respuesta.data!);
  }
}
