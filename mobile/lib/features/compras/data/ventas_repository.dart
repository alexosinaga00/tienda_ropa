import 'package:dio/dio.dart';
import '../models/plazo_cambio.dart';
import '../models/reembolso.dart';
import '../models/venta.dart';

class VentasRepository {
  VentasRepository(this._dio);

  final Dio _dio;

  Future<Venta> registrarVentaDigital({required int sucursalId, required double costoEnvio}) async {
    final respuesta = await _dio.post<Map<String, dynamic>>(
      '/ventas/digital',
      data: {'sucursal_id': sucursalId, 'costo_envio': costoEnvio},
    );
    return Venta.fromJson(respuesta.data!);
  }

  Future<List<Venta>> misCompras() async {
    final respuesta = await _dio.get<List<dynamic>>('/ventas/mis-compras');
    return respuesta.data!.map((e) => Venta.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<Venta> comprobante(int ventaId) async {
    final respuesta = await _dio.get<Map<String, dynamic>>('/ventas/$ventaId/comprobante');
    return Venta.fromJson(respuesta.data!);
  }

  /// Hasta cuándo se puede cambiar la compra. Solo la consulta quien la compró (o el personal de su sucursal).
  Future<PlazoCambio> plazoCambio(int ventaId) async {
    final respuesta = await _dio.get<Map<String, dynamic>>('/ventas/$ventaId/plazo-cambio');
    return PlazoCambio.fromJson(respuesta.data!);
  }

  /// El dinero que se le devolvió al cliente por esta compra (devoluciones sin cambio de prenda y pagos anulados), el
  /// más reciente primero. Lista vacía si no se devolvió nada. Solo lo consulta quien la compró.
  Future<List<Reembolso>> reembolsos(int ventaId) async {
    final respuesta = await _dio.get<List<dynamic>>('/ventas/$ventaId/reembolsos');
    return [
      for (final e in respuesta.data ?? const [])
        if (e is Map<String, dynamic>) Reembolso.fromJson(e),
    ];
  }
}
