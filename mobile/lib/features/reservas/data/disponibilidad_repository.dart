import '../../../core/network/api_client.dart';
import '../models/disponibilidad_sucursal.dart';

class DisponibilidadRepository {
  DisponibilidadRepository(this._api);

  final ApiClient _api;

  /// Endpoint público de la tienda elegida: no requiere sesión de cliente.
  Future<List<DisponibilidadSucursal>> porVariante(int varianteId) {
    return _api.getLista<DisponibilidadSucursal>(
      '/inventario/disponibilidad',
      query: {'variante_id': varianteId},
      desde: DisponibilidadSucursal.fromJson,
      publica: true,
    );
  }
}
