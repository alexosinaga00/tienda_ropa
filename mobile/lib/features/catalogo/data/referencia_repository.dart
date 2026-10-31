import '../../../core/network/api_client.dart';
import '../models/referencia.dart';

/// Catálogos de referencia (categoría, talla, color, material, temporada,
/// sucursal) de la tienda elegida: son chicos, así que se pide una sola
/// página grande en vez de paginar. Todos son públicos.
class ReferenciaRepository {
  ReferenciaRepository(this._api);

  final ApiClient _api;

  static const _tamanioMaximo = 100;

  Future<List<T>> _lista<T>(String ruta, DesdeJson<T> desde) {
    return _api.getLista<T>(ruta, query: {'tamanio': _tamanioMaximo}, desde: desde, publica: true);
  }

  Future<List<CategoriaRef>> categorias() => _lista('/categorias', CategoriaRef.fromJson);

  Future<List<TallaRef>> tallas() => _lista('/tallas', TallaRef.fromJson);

  Future<List<ColorRef>> colores() => _lista('/colores', ColorRef.fromJson);

  Future<List<MaterialRef>> materiales() => _lista('/materiales', MaterialRef.fromJson);

  Future<List<TemporadaRef>> temporadas() => _lista('/temporadas', TemporadaRef.fromJson);

  Future<List<SucursalRef>> sucursales() => _lista('/sucursales', SucursalRef.fromJson);
}
