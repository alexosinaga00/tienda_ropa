import 'dart:async';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/conectividad/conectividad_service.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/dinero.dart';
import '../../../core/widgets/indicador_conexion.dart';
import '../data/politica_vigencia.dart';
import '../models/categoria_local.dart';
import '../models/producto_local.dart';
import '../state/catalogo_local_providers.dart';
import '../state/descarga_controller.dart';
import 'aviso_vigencia.dart';
import 'nivel_existencia.dart';
import 'selector_sucursal_activa.dart';

/// Cuántas prendas se leen de la base local por página.
const tamanoPaginaCatalogoLocal = 20;

/// Espera entre que la persona deja de escribir y se busca.
const esperaBusquedaCatalogoLocal = Duration(milliseconds: 300);

const textoSinDescargaCatalogo = 'Aún no descargaste el catálogo';
const textoSinResultadosCatalogo = 'No encontramos prendas con ese texto';

/// El catálogo del personal, leído de la copia local (SQLite): funciona SIN conexión. Las fotos solo se ven si ya estaban en
/// la caché del teléfono; si no, sale un recuadro con el nombre de la prenda.
class CatalogoLocalScreen extends ConsumerStatefulWidget {
  const CatalogoLocalScreen({super.key});

  @override
  ConsumerState<CatalogoLocalScreen> createState() => _CatalogoLocalScreenState();
}

class _CatalogoLocalScreenState extends ConsumerState<CatalogoLocalScreen> {
  final _busqueda = TextEditingController();
  final _scroll = ScrollController();
  Timer? _espera;

  String _texto = '';
  int? _categoriaId;
  List<CategoriaLocal> _categorias = const [];
  final List<ProductoLocal> _productos = [];

  bool _cargando = true;
  bool _cargandoMas = false;
  bool _hayMas = false;
  bool _hayCatalogo = true;
  bool _error = false;

  /// Cada carga nueva invalida a las que seguían en vuelo (llegarían con filtros viejos).
  int _generacion = 0;
  int? _sucursalVista;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_alDesplazar);
    unawaited(_recargar(conCategorias: true));
  }

  @override
  void dispose() {
    _espera?.cancel();
    _scroll.dispose();
    _busqueda.dispose();
    super.dispose();
  }

  void _alDesplazar() {
    if (_scroll.hasClients && _scroll.position.extentAfter < 600) unawaited(_cargarMas());
  }

  Future<void> _recargar({bool conCategorias = false}) async {
    final generacion = ++_generacion;
    setState(() {
      _cargando = _productos.isEmpty;
      _cargandoMas = false;
      _error = false;
    });
    try {
      final repositorio = await ref.read(catalogoLocalProvider.future);
      final sucursal = await ref.read(sucursalActivaProvider.future);
      if (!mounted || generacion != _generacion) return;
      _sucursalVista = sucursal;
      if (repositorio == null) {
        setState(() {
          _productos.clear();
          _hayCatalogo = false;
          _hayMas = false;
          _cargando = false;
        });
        return;
      }
      final categorias = conCategorias || _categorias.isEmpty ? await repositorio.categorias() : _categorias;
      final total = await repositorio.contarProductos();
      final pagina = await repositorio.buscarProductos(
        texto: _texto,
        categoriaId: _categoriaId,
        sucursalId: sucursal,
        limite: tamanoPaginaCatalogoLocal,
      );
      if (!mounted || generacion != _generacion) return;
      setState(() {
        _categorias = categorias;
        _hayCatalogo = total > 0;
        _productos
          ..clear()
          ..addAll(pagina);
        _hayMas = pagina.length == tamanoPaginaCatalogoLocal;
        _cargando = false;
      });
      _revisarSiHayHueco();
    } catch (_) {
      if (!mounted || generacion != _generacion) return;
      setState(() {
        _error = true;
        _cargando = false;
      });
    }
  }

  Future<void> _cargarMas() async {
    if (_cargando || _cargandoMas || !_hayMas || _error) return;
    final generacion = _generacion;
    setState(() => _cargandoMas = true);
    try {
      final repositorio = await ref.read(catalogoLocalProvider.future);
      if (repositorio == null) return;
      final pagina = await repositorio.buscarProductos(
        texto: _texto,
        categoriaId: _categoriaId,
        sucursalId: _sucursalVista,
        limite: tamanoPaginaCatalogoLocal,
        desplazamiento: _productos.length,
      );
      if (!mounted || generacion != _generacion) return;
      final conocidos = {for (final p in _productos) p.id};
      setState(() {
        _productos.addAll(pagina.where((p) => !conocidos.contains(p.id)));
        _hayMas = pagina.length == tamanoPaginaCatalogoLocal;
        _cargandoMas = false;
      });
      _revisarSiHayHueco();
    } catch (_) {
      if (!mounted || generacion != _generacion) return;
      // Sin romper lo que ya se ve: se deja de paginar hasta la próxima recarga.
      setState(() {
        _hayMas = false;
        _cargandoMas = false;
      });
    }
  }

  /// Si la primera página no llena la pantalla no habrá desplazamiento que pida la siguiente: se pide sola.
  void _revisarSiHayHueco() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && _scroll.hasClients && _scroll.position.extentAfter < 600) unawaited(_cargarMas());
    });
  }

  void _alEscribir(String valor) {
    _espera?.cancel();
    _espera = Timer(esperaBusquedaCatalogoLocal, () => _aplicarTexto(valor));
    setState(() {}); // el botón de borrar
  }

  void _aplicarTexto(String valor) {
    _espera?.cancel();
    if (!mounted) return;
    if (valor.trim() == _texto) return;
    _texto = valor.trim();
    unawaited(_recargar());
  }

  void _elegirCategoria(int? id) {
    if (id == _categoriaId) return;
    _categoriaId = id;
    unawaited(_recargar());
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<int>(descargaTerminadaProvider, (anterior, actual) => unawaited(_recargar(conCategorias: true)));
    ref.listen<AsyncValue<int?>>(sucursalActivaProvider, (anterior, actual) {
      if (actual.isLoading || actual.hasError) return;
      if (actual.valueOrNull != _sucursalVista) unawaited(_recargar());
    });

    final enLinea = ref.watch(enLineaProvider).valueOrNull ?? true;
    final descargando = ref.watch(descargaControllerProvider.select((s) => s.descargando));
    final puedeActualizar = enLinea && !descargando;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Catálogo sin conexión'),
        actions: [
          IconButton(
            tooltip: 'Actualizar datos',
            icon: const Icon(Icons.sync, size: 24),
            onPressed: puedeActualizar ? () => ref.read(descargaControllerProvider.notifier).actualizar() : null,
          ),
        ],
        bottom: const PreferredSize(
          preferredSize: Size.fromHeight(48),
          child: Align(alignment: Alignment.centerLeft, child: SelectorSucursalActiva()),
        ),
      ),
      body: Column(
        children: [
          const AvisoVigencia(),
          const IndicadorConexion.banner(),
          Padding(
            padding: const EdgeInsets.fromLTRB(AppSpacing.md, AppSpacing.md, AppSpacing.md, AppSpacing.sm),
            child: TextField(
              controller: _busqueda,
              textInputAction: TextInputAction.search,
              onChanged: _alEscribir,
              onSubmitted: _aplicarTexto,
              decoration: InputDecoration(
                hintText: 'Buscar prendas...',
                prefixIcon: const Icon(Icons.search, size: 24),
                suffixIcon: _busqueda.text.isEmpty
                    ? null
                    : IconButton(
                        tooltip: 'Borrar búsqueda',
                        icon: const Icon(Icons.close, size: 24),
                        onPressed: () {
                          _busqueda.clear();
                          _aplicarTexto('');
                          setState(() {});
                        },
                      ),
              ),
            ),
          ),
          _FilaCategorias(categorias: _categorias, seleccionada: _categoriaId, alElegir: _elegirCategoria),
          Expanded(child: _cuerpo(enLinea: enLinea, puedeActualizar: puedeActualizar)),
        ],
      ),
    );
  }

  Widget _cuerpo({required bool enLinea, required bool puedeActualizar}) {
    if (_cargando) return const Center(child: CircularProgressIndicator());
    if (_error) {
      return _MensajeVacio(
        icono: Icons.error_outline,
        titulo: 'No pudimos leer el catálogo guardado en el teléfono.',
        boton: 'Reintentar',
        alPulsar: () => unawaited(_recargar(conCategorias: true)),
      );
    }
    if (_productos.isEmpty && !_hayCatalogo) {
      return _MensajeVacio(
        icono: Icons.cloud_download_outlined,
        titulo: textoSinDescargaCatalogo,
        detalle: enLinea ? 'Descárgalo para consultarlo sin conexión.' : 'Conéctate a internet para descargarlo.',
        boton: 'Actualizar datos',
        alPulsar: puedeActualizar ? () => ref.read(descargaControllerProvider.notifier).actualizar() : null,
      );
    }
    if (_productos.isEmpty) {
      return _MensajeVacio(
        icono: Icons.search_off,
        titulo: _texto.isNotEmpty ? textoSinResultadosCatalogo : 'No hay prendas en esta categoría.',
      );
    }

    final vigencia = ref.watch(vigenciaProvider).valueOrNull;
    // Una sucursal que nunca se descargó no tiene existencias: no se pinta "Agotado" por falta de datos.
    final mostrarExistencia = vigencia != null && vigencia.estado != EstadoVigencia.nunca;

    final ancho = MediaQuery.sizeOf(context).width;
    final celda = (ancho - AppSpacing.md * 3) / 2;
    final altoTexto = MediaQuery.textScalerOf(context).scale(112);

    return CustomScrollView(
      controller: _scroll,
      slivers: [
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.md, AppSpacing.sm, AppSpacing.md, 0),
          sliver: SliverGrid(
            gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 2,
              mainAxisSpacing: AppSpacing.md,
              crossAxisSpacing: AppSpacing.md,
              mainAxisExtent: celda * 1.1 + altoTexto,
            ),
            delegate: SliverChildBuilderDelegate(
              (context, i) => _TarjetaPrenda(
                producto: _productos[i],
                mostrarExistencia: mostrarExistencia,
                alTocar: () => context.push('/vendedor/producto/${_productos[i].id}'),
              ),
              childCount: _productos.length,
            ),
          ),
        ),
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Center(
              child: _cargandoMas ? const CircularProgressIndicator() : const SizedBox(height: 4),
            ),
          ),
        ),
      ],
    );
  }
}

class _FilaCategorias extends StatelessWidget {
  const _FilaCategorias({required this.categorias, required this.seleccionada, required this.alElegir});

  final List<CategoriaLocal> categorias;
  final int? seleccionada;
  final ValueChanged<int?> alElegir;

  @override
  Widget build(BuildContext context) {
    final raices = categorias.where((c) => c.padreId == null).toList();
    return SizedBox(
      height: 56,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.xs),
        children: [
          _Chip(texto: 'Todas', activa: seleccionada == null, alPulsar: () => alElegir(null)),
          for (final c in raices) _Chip(texto: c.nombre, activa: seleccionada == c.id, alPulsar: () => alElegir(c.id)),
        ],
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.texto, required this.activa, required this.alPulsar});

  final String texto;
  final bool activa;
  final VoidCallback alPulsar;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(right: AppSpacing.sm),
      child: ChoiceChip(
        label: Text(texto),
        selected: activa,
        onSelected: (_) => alPulsar(),
        visualDensity: VisualDensity.standard,
        materialTapTargetSize: MaterialTapTargetSize.padded,
      ),
    );
  }
}

class _TarjetaPrenda extends StatelessWidget {
  const _TarjetaPrenda({required this.producto, required this.mostrarExistencia, required this.alTocar});

  final ProductoLocal producto;
  final bool mostrarExistencia;
  final VoidCallback alTocar;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final existencia = mostrarExistencia ? producto.existenciaEstimada : null;
    final nivel = existencia == null ? null : NivelExistencia.de(existencia);
    final precio = formatearBs(producto.precioDesdeCentavos);

    return Semantics(
      button: true,
      label: producto.nombre,
      child: Card(
        key: Key('tarjeta_prenda_${producto.id}'),
        elevation: 0,
        clipBehavior: Clip.antiAlias,
        color: AppColors.fondo,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.base),
          side: const BorderSide(color: AppColors.borde),
        ),
        child: InkWell(
          onTap: alTocar,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: FotoPrenda(nombre: producto.nombre, productoId: producto.id, url: producto.imagenUrl)),
              Padding(
                padding: const EdgeInsets.all(AppSpacing.sm),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      producto.nombre,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: tema.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      producto.tieneRangoDePrecio ? 'Desde $precio' : precio,
                      style: tema.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w500),
                    ),
                    if (nivel != null) ...[
                      const SizedBox(height: AppSpacing.xs),
                      Row(
                        children: [
                          Icon(nivel.icono, size: 20, color: nivel.color),
                          const SizedBox(width: AppSpacing.xs),
                          Expanded(
                            child: Text(
                              textoExistenciaTarjeta(existencia!),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(color: nivel.color, fontSize: 14, fontWeight: FontWeight.w500),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// La foto de una prenda: la de la caché si hay (sin red solo se ven las ya guardadas) y, si no, un recuadro neutro con el
/// nombre. Reutilizable por el detalle.
class FotoPrenda extends StatelessWidget {
  const FotoPrenda({super.key, required this.nombre, required this.productoId, this.url, this.compacta = false});

  final String nombre;
  final int productoId;
  final String? url;

  /// Para miniaturas (64 px): el recuadro sin foto muestra solo el ícono, porque el nombre no cabe.
  final bool compacta;

  @override
  Widget build(BuildContext context) {
    final alterna = _Alterna(nombre: nombre, productoId: productoId, compacta: compacta);
    final direccion = url;
    if (direccion == null || direccion.isEmpty) return alterna;
    return CachedNetworkImage(
      imageUrl: direccion,
      fit: BoxFit.cover,
      width: double.infinity,
      placeholder: (context, url) => const ColoredBox(color: AppColors.fondoAlterno),
      errorWidget: (context, url, error) => alterna,
    );
  }
}

class _Alterna extends StatelessWidget {
  const _Alterna({required this.nombre, required this.productoId, this.compacta = false});

  final String nombre;
  final int productoId;
  final bool compacta;

  @override
  Widget build(BuildContext context) {
    if (compacta) {
      return ExcludeSemantics(
        child: Container(
          key: Key('foto_alterna_$productoId'),
          width: double.infinity,
          color: AppColors.fondoAlterno,
          alignment: Alignment.center,
          child: const Icon(Icons.checkroom, size: 28, color: AppColors.textoTenue),
        ),
      );
    }
    return ExcludeSemantics(
      child: Container(
        key: Key('foto_alterna_$productoId'),
        width: double.infinity,
        color: AppColors.fondoAlterno,
        padding: const EdgeInsets.all(AppSpacing.sm),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.checkroom, size: 36, color: AppColors.textoTenue),
            const SizedBox(height: AppSpacing.xs),
            Text(
              nombre,
              textAlign: TextAlign.center,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: AppColors.textoTenue, fontSize: 14),
            ),
          ],
        ),
      ),
    );
  }
}

class _MensajeVacio extends StatelessWidget {
  const _MensajeVacio({required this.icono, required this.titulo, this.detalle, this.boton, this.alPulsar});

  final IconData icono;
  final String titulo;
  final String? detalle;
  final String? boton;
  final VoidCallback? alPulsar;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icono, size: 48, color: AppColors.textoTenue),
            const SizedBox(height: AppSpacing.md),
            Text(titulo, textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodyLarge),
            if (detalle != null) ...[
              const SizedBox(height: AppSpacing.xs),
              Text(detalle!, textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodyMedium),
            ],
            if (boton != null) ...[
              const SizedBox(height: AppSpacing.lg),
              ElevatedButton(onPressed: alPulsar, child: Text(boton!)),
            ],
          ],
        ),
      ),
    );
  }
}
