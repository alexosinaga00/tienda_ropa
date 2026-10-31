import '../../../core/network/api_client.dart';
import '../models/tienda.dart';

/// Las tiendas son públicas y no dependen de la tienda elegida: sus rutas son absolutas (`/public/...`).
class TiendaRepository {
  TiendaRepository(this._api);

  final ApiClient _api;

  /// El backend admite hasta 50 por página; con las organizaciones de hoy alcanza una.
  static const tamanioPagina = 50;

  /// Las tiendas con suscripción activa, por nombre. `q` busca en el nombre y en el código.
  Future<List<Tienda>> listar({String? q, int pagina = 1}) {
    final texto = q?.trim();
    return _api.getLista<Tienda>(
      '/public/tiendas',
      query: {'pagina': pagina, 'tamanio': tamanioPagina, if (texto != null && texto.isNotEmpty) 'q': texto},
      desde: Tienda.fromJson,
      publica: true,
    );
  }

  /// Una tienda por su código; 404 (`ErrorApp` noEncontrado) si no existe o está inactiva.
  Future<Tienda> obtener(String codigo) {
    return _api.getObjeto<Tienda>(
      '/public/${Uri.encodeComponent(codigo.trim().toLowerCase())}/tienda',
      desde: Tienda.fromJson,
      publica: true,
    );
  }
}
