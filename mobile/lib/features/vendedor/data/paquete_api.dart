import '../../../core/network/api_client.dart';
import '../../../core/network/error_app.dart';
import '../models/paquete_sincronizacion.dart';

const mensajeDescargaIncompleta = 'La descarga quedó incompleta. Intenta de nuevo.';

const _rutaPaquete = '/sincronizacion/paquete';
const rutaPaqueteManifiesto = _rutaPaquete;
const rutaPaqueteCatalogo = '$_rutaPaquete/catalogo';
const rutaPaqueteStock = '$_rutaPaquete/stock';
const rutaPaqueteClientes = '$_rutaPaquete/clientes';

const _errorIncompleta = ErrorApp(tipo: TipoErrorApp.desconocido, mensaje: mensajeDescargaIncompleta);

/// Las cuatro rutas del paquete de descarga (`GET /sincronizacion/paquete...`). Requieren sesión del personal: nunca son
/// públicas. Los nombres de los parámetros son los del backend (`desde_id`, `desde_variante_id`, `sucursal_id`, `desde`,
/// `limite`); los que no se dan no se mandan y el servidor usa su valor por defecto.
class PaqueteApi {
  PaqueteApi(this._api, {this.topePaginas = 500, this.limiteCatalogo = 200, this.limiteStock = 500, this.limiteClientes = 500});

  final ApiClient _api;

  /// Seguridad contra un bucle infinito si el servidor nunca dejara de decir "hay más".
  final int topePaginas;
  final int limiteCatalogo;
  final int limiteStock;
  final int limiteClientes;

  // ---- Una página ----

  /// Sin [sucursalId]: todas las sucursales autorizadas del usuario. Con él, solo esa.
  Future<ManifiestoPaquete> manifiesto({int? sucursalId}) {
    return _api.getObjeto(
      rutaPaqueteManifiesto,
      query: {'sucursal_id': ?sucursalId},
      desde: ManifiestoPaquete.fromJson,
    );
  }

  Future<PaginaCatalogo> paginaCatalogo({int? desdeId, int? limite}) {
    return _api.getObjeto(
      rutaPaqueteCatalogo,
      query: {'desde_id': ?desdeId, 'limite': ?limite},
      desde: PaginaCatalogo.fromJson,
    );
  }

  /// [desde]: con él el servidor devuelve solo lo modificado desde ese instante (menos un solape que él mismo resta).
  Future<PaginaStock> paginaStock({required int sucursalId, DateTime? desde, int? desdeVarianteId, int? limite}) {
    return _api.getObjeto(
      rutaPaqueteStock,
      query: {
        'sucursal_id': sucursalId,
        'desde': ?(desde == null ? null : aIsoUtc(desde)),
        'desde_variante_id': ?desdeVarianteId,
        'limite': ?limite,
      },
      desde: PaginaStock.fromJson,
    );
  }

  Future<PaginaClientes> paginaClientes({int? desdeId, int? limite}) {
    return _api.getObjeto(
      rutaPaqueteClientes,
      query: {'desde_id': ?desdeId, 'limite': ?limite},
      desde: PaginaClientes.fromJson,
    );
  }

  // ---- Todas las páginas ----

  /// El catálogo completo. Verifica que la cantidad de productos recibida sea el `total` que dice el servidor.
  Future<CatalogoDescargado> descargarCatalogo() async {
    final productos = <ProductoPaquete>[];
    final ids = <int>{};
    DateTime? generadoEn;
    int? total;
    int? cursor;
    for (var pagina = 1;; pagina++) {
      if (pagina > topePaginas) throw _errorIncompleta;
      final datos = await paginaCatalogo(desdeId: cursor, limite: limiteCatalogo);
      generadoEn ??= datos.generadoEn;
      total ??= datos.total;
      for (final p in datos.items) {
        if (ids.add(p.id)) productos.add(p);
      }
      final siguiente = datos.siguienteDesdeId;
      if (siguiente == null) break;
      if (cursor != null && siguiente <= cursor) throw _errorIncompleta; // el cursor no avanza: bucle
      cursor = siguiente;
    }
    if (productos.length != total) throw _errorIncompleta;
    return CatalogoDescargado(productos: productos, generadoEn: generadoEn);
  }

  /// El stock de UNA sucursal (completo, o el delta si se da [desde]). No hay `total` que verificar: el cursor por
  /// `variante_id` es la garantía.
  Future<StockDescargado> descargarStock({required int sucursalId, DateTime? desde}) async {
    final items = <ItemStockPaquete>[];
    DateTime? generadoEn;
    int? cursor;
    for (var pagina = 1;; pagina++) {
      if (pagina > topePaginas) throw _errorIncompleta;
      final datos = await paginaStock(sucursalId: sucursalId, desde: desde, desdeVarianteId: cursor, limite: limiteStock);
      if (datos.sucursalId != sucursalId) throw _errorIncompleta; // el servidor contestó otra sucursal
      generadoEn ??= datos.generadoEn;
      items.addAll(datos.items);
      final siguiente = datos.siguienteDesdeVarianteId;
      if (siguiente == null) break;
      if (cursor != null && siguiente <= cursor) throw _errorIncompleta;
      cursor = siguiente;
    }
    return StockDescargado(sucursalId: sucursalId, items: items, incremental: desde != null, generadoEn: generadoEn);
  }

  /// Todos los clientes; también verifica el `total`.
  Future<ClientesDescargados> descargarClientes() async {
    final clientes = <ClientePaquete>[];
    final ids = <int>{};
    int? total;
    int? cursor;
    for (var pagina = 1;; pagina++) {
      if (pagina > topePaginas) throw _errorIncompleta;
      final datos = await paginaClientes(desdeId: cursor, limite: limiteClientes);
      total ??= datos.total;
      for (final c in datos.items) {
        if (ids.add(c.id)) clientes.add(c);
      }
      final siguiente = datos.siguienteDesdeId;
      if (siguiente == null) break;
      if (cursor != null && siguiente <= cursor) throw _errorIncompleta;
      cursor = siguiente;
    }
    if (clientes.length != total) throw _errorIncompleta;
    return ClientesDescargados(clientes: clientes);
  }
}
