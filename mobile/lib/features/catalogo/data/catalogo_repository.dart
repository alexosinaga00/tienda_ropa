import '../../../core/network/api_client.dart';
import '../../../core/network/error_app.dart';
import '../../cliente_offline/data/cache_catalogo_cliente.dart';
import '../models/catalogo_detalle.dart';
import '../models/catalogo_item.dart';
import '../models/filtros_catalogo.dart';
import '../models/variante_lookup.dart';

const mensajePrendaNoGuardada = 'Esta prenda no estaba guardada en tu teléfono. Conéctate para verla.';

/// Sin conexión (o con el servidor caído) se puede mostrar lo que ya se vio; con cualquier otro error, no.
bool esFalloDeRedOServidor(Object error) =>
    error is ErrorApp && (error.tipo == TipoErrorApp.sinConexion || error.tipo == TipoErrorApp.servidor);

/// El catálogo de la tienda elegida. Listar, buscar y ver el detalle son públicos (`/public/{codigo}/catalogo...`);
/// resolver las variantes del carrito exige sesión (la empresa sale del token).
///
/// Con un [cache], todo lo que se lee con conexión se recuerda en el teléfono y, si después no hay conexión, listar,
/// buscar y ver el detalle muestran lo recordado. Guardar o leer del cache NUNCA hace fallar una consulta: ante cualquier
/// problema con la base local simplemente se ignora.
class CatalogoRepository {
  CatalogoRepository(this._api, {this._cache});

  final ApiClient _api;
  final CacheCatalogoCliente? _cache;

  Future<List<CatalogoItem>> listar({required int pagina, required int tamanio}) async {
    final crudos = <Map<String, dynamic>>[];
    try {
      final items = await _api.getLista<CatalogoItem>(
        '/catalogo',
        query: {'pagina': pagina, 'tamanio': tamanio},
        desde: (json) {
          crudos.add(json);
          return CatalogoItem.fromJson(json);
        },
        publica: true,
      );
      await _guardar(() => _cache?.guardarItems(crudos, primeraPosicion: (pagina - 1) * tamanio));
      return items;
    } catch (error) {
      final guardadas = await _recordadas(error, null);
      if (guardadas == null) rethrow;
      return _pagina(guardadas, pagina, tamanio);
    }
  }

  Future<List<CatalogoItem>> buscar(FiltrosCatalogo filtros, {required int pagina, required int tamanio}) async {
    final crudos = <Map<String, dynamic>>[];
    try {
      final items = await _api.getLista<CatalogoItem>(
        '/catalogo/buscar',
        query: {'pagina': pagina, 'tamanio': tamanio, ...filtros.aQueryParams()},
        desde: (json) {
          crudos.add(json);
          return CatalogoItem.fromJson(json);
        },
        publica: true,
      );
      await _guardar(() => _cache?.guardarItems(crudos));
      return items;
    } catch (error) {
      // Sin conexión solo se puede buscar por texto entre lo guardado; los demás filtros necesitan al servidor.
      final guardadas = await _recordadas(error, filtros.texto);
      if (guardadas == null) rethrow;
      return _pagina(guardadas, pagina, tamanio);
    }
  }

  Future<CatalogoDetalle> detalle(int productoId) async {
    Map<String, dynamic>? crudo;
    try {
      final detalle = await _api.getObjeto<CatalogoDetalle>(
        '/catalogo/$productoId',
        desde: (json) {
          crudo = json;
          return CatalogoDetalle.fromJson(json);
        },
        publica: true,
      );
      final guardar = crudo;
      if (guardar != null) await _guardar(() => _cache?.guardarDetalle(productoId, guardar));
      return detalle;
    } catch (error) {
      if (!esFalloDeRedOServidor(error)) rethrow;
      final guardado = await _leer(() => _cache?.leerDetalle(productoId));
      if (guardado != null) return guardado;
      // Sin red y sin nada guardado: se dice claro por qué no se puede ver.
      throw const ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: mensajePrendaNoGuardada);
    }
  }

  /// El detalle de un producto con el stock de cada variante EN esa sucursal (`cantidad_disponible`).
  Future<CatalogoDetalle> detalleEnSucursal(int productoId, int sucursalId) {
    return _api.getObjeto<CatalogoDetalle>(
      '/catalogo/$productoId',
      query: {'sucursal_id': sucursalId},
      desde: CatalogoDetalle.fromJson,
      publica: true,
    );
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

  // ---- Lo recordado ------------------------------------------------------------------------------------------------

  /// Las prendas guardadas si [error] es de red y hay algo que mostrar; null si hay que propagar el error.
  Future<List<CatalogoItem>?> _recordadas(Object error, String? texto) async {
    if (!esFalloDeRedOServidor(error)) return null;
    final guardadas = await _leer(() => _cache?.leerItems(texto: texto));
    if (guardadas == null || guardadas.isEmpty) return null;
    return guardadas;
  }

  List<CatalogoItem> _pagina(List<CatalogoItem> todas, int pagina, int tamanio) {
    final desde = (pagina - 1) * tamanio;
    if (desde >= todas.length) return const [];
    final hasta = desde + tamanio > todas.length ? todas.length : desde + tamanio;
    return todas.sublist(desde, hasta);
  }

  Future<void> _guardar(Future<void>? Function() accion) async {
    try {
      await accion();
    } catch (_) {
      // El cache es un extra: si falla, la consulta sigue valiendo.
    }
  }

  Future<T?> _leer<T>(Future<T?>? Function() accion) async {
    try {
      return await accion();
    } catch (_) {
      return null;
    }
  }
}
