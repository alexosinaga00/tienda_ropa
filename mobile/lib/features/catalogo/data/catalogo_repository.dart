import '../../../core/network/api_client.dart';
import '../models/catalogo_detalle.dart';
import '../models/catalogo_item.dart';
import '../models/filtros_catalogo.dart';
import '../models/variante_lookup.dart';

/// El catálogo de la tienda elegida. Listar, buscar y ver el detalle son públicos (`/public/{codigo}/catalogo...`);
/// resolver las variantes del carrito exige sesión (la empresa sale del token).
class CatalogoRepository {
  CatalogoRepository(this._api);

  final ApiClient _api;

  Future<List<CatalogoItem>> listar({required int pagina, required int tamanio}) {
    return _api.getLista<CatalogoItem>(
      '/catalogo',
      query: {'pagina': pagina, 'tamanio': tamanio},
      desde: CatalogoItem.fromJson,
      publica: true,
    );
  }

  Future<List<CatalogoItem>> buscar(FiltrosCatalogo filtros, {required int pagina, required int tamanio}) {
    return _api.getLista<CatalogoItem>(
      '/catalogo/buscar',
      query: {'pagina': pagina, 'tamanio': tamanio, ...filtros.aQueryParams()},
      desde: CatalogoItem.fromJson,
      publica: true,
    );
  }

  Future<CatalogoDetalle> detalle(int productoId) {
    return _api.getObjeto<CatalogoDetalle>('/catalogo/$productoId', desde: CatalogoDetalle.fromJson, publica: true);
  }

  /// Resuelve nombre/foto/talla/color en lote para un conjunto de
  /// variantes -- lo usa el carrito de compra (features/compras), que del
  /// backend solo recibe variante_id/cantidad/precio. Exige sesión.
  Future<List<VarianteLookupItem>> detallePorVariantes(List<int> varianteIds) {
    if (varianteIds.isEmpty) return Future.value(const []);
    return _api.getLista<VarianteLookupItem>(
      '/catalogo/variantes/detalle',
      query: {'variante_ids': varianteIds.join(',')},
      desde: VarianteLookupItem.fromJson,
    );
  }
}
