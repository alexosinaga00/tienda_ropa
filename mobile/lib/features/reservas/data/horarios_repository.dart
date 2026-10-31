import '../../../core/network/api_client.dart';
import '../models/horario_sucursal.dart';

class HorariosRepository {
  HorariosRepository(this._api);

  final ApiClient _api;

  Future<List<HorarioSucursal>> porSucursal(int sucursalId) {
    return _api.getLista<HorarioSucursal>(
      '/sucursales/$sucursalId/horarios',
      desde: HorarioSucursal.fromJson,
      publica: true,
    );
  }
}
