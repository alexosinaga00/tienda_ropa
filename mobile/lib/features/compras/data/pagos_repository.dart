import 'package:dio/dio.dart';
import '../models/pago.dart';

class PagosRepository {
  PagosRepository(this._dio);

  final Dio _dio;

  Future<PagoIniciado> iniciar({required int ventaId, required String metodoPago}) async {
    final respuesta = await _dio.post<Map<String, dynamic>>(
      '/pagos/iniciar',
      data: {'venta_id': ventaId, 'metodo_pago': metodoPago},
    );
    return PagoIniciado.fromJson(respuesta.data!);
  }

  /// Abandona una compra sin pagar: el backend libera el stock reservado y
  /// devuelve las prendas al carrito (409 si en realidad ya se pagó).
  Future<void> cancelarCompra(int ventaId) async {
    await _dio.post<Map<String, dynamic>>('/pagos/venta/$ventaId/cancelar');
  }

  Future<Pago> estado(int pagoId) async {
    final respuesta = await _dio.get<Map<String, dynamic>>('/pagos/$pagoId/estado');
    return Pago.fromJson(respuesta.data!);
  }
}
