import '../../../core/network/api_client.dart';
import '../../cliente_offline/config/cliente_offline_config.dart';
import '../../cliente_offline/data/cache_catalogo_cliente.dart';
import '../models/referencia.dart';
import 'catalogo_repository.dart' show esFalloDeRedOServidor;

/// Catálogos de referencia (categoría, talla, color, material, temporada,
/// sucursal) de la tienda elegida: son chicos, así que se pide una sola
/// página grande en vez de paginar. Todos son públicos.
///
/// Las tallas, los colores y las sucursales se recuerdan en el teléfono (si hay un [cache]) para poder mostrar una prenda
/// y elegir dónde retirar cuando no hay conexión. Fallar al guardar o leer lo recordado nunca falla la consulta.
class ReferenciaRepository {
  ReferenciaRepository(this._api, {this._cache});

  final ApiClient _api;
  final CacheCatalogoCliente? _cache;

  static const _tamanioMaximo = 100;

  Future<List<T>> _lista<T>(String ruta, DesdeJson<T> desde) {
    return _api.getLista<T>(ruta, query: {'tamanio': _tamanioMaximo}, desde: desde, publica: true);
  }

  /// Como [_lista], pero recordando lo que llega y, sin conexión, devolviendo lo recordado (si hay).
  Future<List<T>> _listaRecordada<T>(String ruta, String tipo, DesdeJson<T> desde) async {
    final crudos = <Map<String, dynamic>>[];
    try {
      final lista = await _lista<T>(ruta, (json) {
        crudos.add(json);
        return desde(json);
      });
      try {
        await _cache?.guardarReferencias(tipo, crudos);
      } catch (_) {
        // Lo recordado es un extra.
      }
      return lista;
    } catch (error) {
      if (!esFalloDeRedOServidor(error)) rethrow;
      List<Map<String, dynamic>>? guardadas;
      try {
        guardadas = await _cache?.leerReferencias(tipo);
      } catch (_) {
        guardadas = null;
      }
      if (guardadas == null || guardadas.isEmpty) rethrow;
      return [for (final g in guardadas) desde(g)];
    }
  }

  Future<List<CategoriaRef>> categorias() => _lista('/categorias', CategoriaRef.fromJson);

  Future<List<TallaRef>> tallas() => _listaRecordada('/tallas', cacheTalla, TallaRef.fromJson);

  Future<List<ColorRef>> colores() => _listaRecordada('/colores', cacheColor, ColorRef.fromJson);

  Future<List<MaterialRef>> materiales() => _lista('/materiales', MaterialRef.fromJson);

  Future<List<TemporadaRef>> temporadas() => _lista('/temporadas', TemporadaRef.fromJson);

  Future<List<SucursalRef>> sucursales() => _listaRecordada('/sucursales', cacheSucursal, SucursalRef.fromJson);
}
