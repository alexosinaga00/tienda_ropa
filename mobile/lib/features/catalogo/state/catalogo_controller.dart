import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../features/tracking/models/evento.dart';
import '../../../features/tracking/state/tracking_service.dart';
import '../../../features/tienda/state/tienda_controller.dart';
import '../models/catalogo_item.dart';
import '../models/filtros_catalogo.dart';
import 'catalogo_providers.dart';

class CatalogoState {
  const CatalogoState({
    this.items = const [],
    this.pagina = 1,
    this.cargando = false,
    this.cargandoPrimeraPagina = true,
    this.hayMas = true,
    this.error = false,
    this.filtros = const FiltrosCatalogo(),
    this.etiquetasVoz = const {},
  });

  final List<CatalogoItem> items;
  final int pagina;
  final bool cargando;
  final bool cargandoPrimeraPagina;
  final bool hayMas;
  final bool error;
  final FiltrosCatalogo filtros;
  // Etiquetas legibles de los filtros que puso la búsqueda por voz (P6.1),
  // clave = mismo nombre de campo que usa VozResultado.etiquetas (categoria,
  // material, color, talla, temporada, genero, precio_max). Vacío si los
  // filtros actuales no vinieron de una búsqueda por voz.
  final Map<String, String> etiquetasVoz;

  CatalogoState copyWith({
    List<CatalogoItem>? items,
    int? pagina,
    bool? cargando,
    bool? cargandoPrimeraPagina,
    bool? hayMas,
    bool? error,
    FiltrosCatalogo? filtros,
    Map<String, String>? etiquetasVoz,
  }) {
    return CatalogoState(
      items: items ?? this.items,
      pagina: pagina ?? this.pagina,
      cargando: cargando ?? this.cargando,
      cargandoPrimeraPagina: cargandoPrimeraPagina ?? this.cargandoPrimeraPagina,
      hayMas: hayMas ?? this.hayMas,
      error: error ?? false,
      filtros: filtros ?? this.filtros,
      etiquetasVoz: etiquetasVoz ?? this.etiquetasVoz,
    );
  }
}

class CatalogoController extends StateNotifier<CatalogoState> {
  CatalogoController(this._ref) : super(const CatalogoState()) {
    cargarPrimeraPagina();
  }

  final Ref _ref;
  static const _tamanioPagina = 20;

  Future<void> cargarPrimeraPagina() async {
    state = state.copyWith(cargandoPrimeraPagina: true, error: false);
    try {
      final items = await _obtenerPagina(1);
      // Al cambiar de tienda este controlador se descarta: una carga en vuelo no debe escribir en uno ya liberado.
      if (!mounted) return;
      state = state.copyWith(
        items: items,
        pagina: 1,
        hayMas: items.length == _tamanioPagina,
        cargandoPrimeraPagina: false,
      );
    } catch (_) {
      if (!mounted) return;
      state = state.copyWith(cargandoPrimeraPagina: false, error: true);
    }
  }

  Future<void> cargarSiguientePagina() async {
    if (state.cargando || state.cargandoPrimeraPagina || !state.hayMas) return;

    state = state.copyWith(cargando: true);
    try {
      final siguiente = state.pagina + 1;
      final nuevos = await _obtenerPagina(siguiente);
      if (!mounted) return;
      state = state.copyWith(
        items: [...state.items, ...nuevos],
        pagina: siguiente,
        hayMas: nuevos.length == _tamanioPagina,
        cargando: false,
      );
    } catch (_) {
      // Si falla al pedir "una página más", no se rompe la grilla que ya
      // se veía: se deja de cargar y listo.
      if (!mounted) return;
      state = state.copyWith(cargando: false);
    }
  }

  Future<void> aplicarFiltros(FiltrosCatalogo filtros) async {
    // etiquetasVoz: const {} -- cualquier cambio de filtros que no venga de
    // la búsqueda por voz (buscador de texto, hoja de filtros) invalida las
    // etiquetas viejas; quitarFiltroVoz es la única vía que las conserva.
    state = state.copyWith(filtros: filtros, etiquetasVoz: const {});
    await cargarPrimeraPagina();
    if (!mounted) return;

    if (filtros.texto != null && filtros.texto!.isNotEmpty) {
      _ref.read(trackingServiceProvider).track(tipo: TipoEvento.busqueda, texto: filtros.texto);
    }
  }

  Future<void> limpiarFiltros() => aplicarFiltros(const FiltrosCatalogo());

  /// Búsqueda por voz (P6.1): a diferencia de [aplicarFiltros], acá los
  /// resultados ya vienen resueltos por POST /ia/voz -- se setean directo
  /// en el estado en vez de volver a pedirle la primera página a
  /// /catalogo/buscar con los mismos filtros.
  void aplicarFiltrosDesdeVoz(FiltrosCatalogo filtros, List<CatalogoItem> resultados, Map<String, String> etiquetas) {
    state = state.copyWith(
      filtros: filtros,
      items: resultados,
      pagina: 1,
      hayMas: resultados.length == _tamanioPagina,
      cargandoPrimeraPagina: false,
      etiquetasVoz: etiquetas,
    );
  }

  /// Saca un único filtro que había puesto la búsqueda por voz (un chip
  /// removido) y vuelve a buscar con el resto -- reusa el mismo camino de
  /// /catalogo/buscar que la búsqueda manual, no hace falta un endpoint
  /// nuevo para "quitar un filtro".
  Future<void> quitarFiltroVoz(String campo) async {
    final actuales = state.filtros;
    final filtros = switch (campo) {
      'categoria' => actuales.copyWith(limpiarCategoria: true),
      'material' => actuales.copyWith(limpiarMaterial: true),
      'color' => actuales.copyWith(limpiarColor: true),
      'talla' => actuales.copyWith(limpiarTalla: true),
      'temporada' => actuales.copyWith(limpiarTemporada: true),
      'genero' => actuales.copyWith(limpiarGenero: true),
      'precio_max' => actuales.copyWith(limpiarPrecioMax: true),
      _ => actuales,
    };
    final etiquetas = Map<String, String>.from(state.etiquetasVoz)..remove(campo);
    state = state.copyWith(filtros: filtros, etiquetasVoz: etiquetas);
    await cargarPrimeraPagina();
  }

  Future<List<CatalogoItem>> _obtenerPagina(int pagina) {
    final repo = _ref.read(catalogoRepositoryProvider);
    if (state.filtros.tieneFiltros) {
      return repo.buscar(state.filtros, pagina: pagina, tamanio: _tamanioPagina);
    }
    return repo.listar(pagina: pagina, tamanio: _tamanioPagina);
  }
}

/// Una instancia por tienda: al cambiarla se descarta la lista, los filtros y la página de la anterior.
final catalogoControllerProvider = StateNotifierProvider<CatalogoController, CatalogoState>((ref) {
  ref.watch(tiendaCodigoProvider);
  return CatalogoController(ref);
});
