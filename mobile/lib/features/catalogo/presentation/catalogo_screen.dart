import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/app_theme.dart';
import '../../auth/state/auth_controller.dart';
import '../../compras/state/carrito_controller.dart';
import '../../notificaciones/presentation/boton_notificaciones.dart';
import '../../recomendador/presentation/carrusel_recomendaciones.dart';
import '../../recomendador/state/recomendador_providers.dart';
import '../../voz/presentation/voz_boton.dart';
import '../models/catalogo_item.dart';
import '../models/filtros_catalogo.dart';
import '../state/catalogo_controller.dart';
import 'filtros_sheet.dart';

const _etiquetasCampoVoz = {
  'categoria': 'Categoría',
  'material': 'Material',
  'color': 'Color',
  'talla': 'Talla',
  'temporada': 'Temporada',
  'genero': 'Género',
  'precio_max': 'Hasta Bs',
};

enum _AccionMenu { favoritos, carrito, compras, reservas, salir, iniciarSesion }

class CatalogoScreen extends ConsumerStatefulWidget {
  const CatalogoScreen({super.key});

  @override
  ConsumerState<CatalogoScreen> createState() => _CatalogoScreenState();
}

class _CatalogoScreenState extends ConsumerState<CatalogoScreen> {
  final _scrollController = ScrollController();
  final _busquedaController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _scrollController.addListener(_onScroll);
  }

  @override
  void dispose() {
    _scrollController.removeListener(_onScroll);
    _scrollController.dispose();
    _busquedaController.dispose();
    super.dispose();
  }

  void _onScroll() {
    // Scroll infinito: al acercarse al final, pide la próxima página.
    final faltaPoco = _scrollController.position.pixels >= _scrollController.position.maxScrollExtent - 400;
    if (faltaPoco) {
      ref.read(catalogoControllerProvider.notifier).cargarSiguientePagina();
    }
  }

  Future<void> _abrirFiltros() async {
    final filtrosActuales = ref.read(catalogoControllerProvider).filtros;
    final nuevosFiltros = await showModalBottomSheet<FiltrosCatalogo>(
      context: context,
      isScrollControlled: true,
      builder: (context) => FiltrosSheet(filtrosIniciales: filtrosActuales),
    );
    if (nuevosFiltros != null) {
      await ref.read(catalogoControllerProvider.notifier).aplicarFiltros(nuevosFiltros);
    }
  }

  void _buscar(String texto) {
    final actuales = ref.read(catalogoControllerProvider).filtros;
    ref.read(catalogoControllerProvider.notifier).aplicarFiltros(actuales.copyWith(texto: texto));
  }

  @override
  Widget build(BuildContext context) {
    final estado = ref.watch(catalogoControllerProvider);
    final autenticado = ref.watch(authControllerProvider.select((s) => s.estaAutenticado));
    // Para un invitado no se debe ni mirar carritoControllerProvider: su
    // constructor dispara un GET /carrito (autenticado) apenas se instancia.
    final cantidadEnCarrito = autenticado ? ref.watch(carritoControllerProvider).valueOrNull?.detalle.length ?? 0 : 0;

    return Scaffold(
      backgroundColor: AppColors.fondo,
      appBar: AppBar(
        title: const Text('FashionStore'),
        actions: [
          if (autenticado) const BotonNotificaciones(),
          IconButton(
            icon: const Icon(Icons.chat_bubble_outline),
            tooltip: 'Asistente',
            onPressed: () => context.push('/asistente'),
          ),
          IconButton(
            icon: const Icon(Icons.accessibility_new_outlined),
            tooltip: 'Probador virtual',
            onPressed: () => context.push('/probador'),
          ),
          PopupMenuButton<_AccionMenu>(
            tooltip: 'Más opciones',
            icon: Badge(
              label: Text('$cantidadEnCarrito'),
              isLabelVisible: cantidadEnCarrito > 0,
              child: const Icon(Icons.more_vert),
            ),
            onSelected: (accion) {
              switch (accion) {
                case _AccionMenu.favoritos:
                  context.push('/favoritos');
                case _AccionMenu.carrito:
                  context.push('/carrito');
                case _AccionMenu.compras:
                  context.push('/compras');
                case _AccionMenu.reservas:
                  context.push('/reservas');
                case _AccionMenu.salir:
                  ref.read(authControllerProvider.notifier).logout();
                case _AccionMenu.iniciarSesion:
                  context.push('/login');
              }
            },
            itemBuilder: (context) => [
              const PopupMenuItem(
                value: _AccionMenu.favoritos,
                child: ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(Icons.favorite_border),
                  title: Text('Favoritos'),
                ),
              ),
              PopupMenuItem(
                value: _AccionMenu.carrito,
                child: ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Badge(
                    label: Text('$cantidadEnCarrito'),
                    isLabelVisible: cantidadEnCarrito > 0,
                    child: const Icon(Icons.shopping_bag_outlined),
                  ),
                  title: const Text('Carrito'),
                ),
              ),
              const PopupMenuItem(
                value: _AccionMenu.compras,
                child: ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(Icons.receipt_long_outlined),
                  title: Text('Mis compras'),
                ),
              ),
              const PopupMenuItem(
                value: _AccionMenu.reservas,
                child: ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(Icons.calendar_month_outlined),
                  title: Text('Mis reservas'),
                ),
              ),
              const PopupMenuDivider(),
              autenticado
                  ? const PopupMenuItem(
                      value: _AccionMenu.salir,
                      child: ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: Icon(Icons.logout),
                        title: Text('Cerrar sesión'),
                      ),
                    )
                  : const PopupMenuItem(
                      value: _AccionMenu.iniciarSesion,
                      child: ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: Icon(Icons.login),
                        title: Text('Iniciar sesión'),
                      ),
                    ),
            ],
          ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(AppSpacing.md, AppSpacing.md, AppSpacing.md, 0),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _busquedaController,
                    decoration: const InputDecoration(
                      hintText: 'Buscar prendas...',
                      prefixIcon: Icon(Icons.search),
                    ),
                    textInputAction: TextInputAction.search,
                    onSubmitted: _buscar,
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                const VozBoton(),
                const SizedBox(width: AppSpacing.sm),
                IconButton.filledTonal(
                  icon: Icon(estado.filtros.tieneFiltros ? Icons.filter_alt : Icons.filter_alt_outlined),
                  tooltip: 'Filtros',
                  onPressed: _abrirFiltros,
                ),
              ],
            ),
          ),
          if (estado.etiquetasVoz.isNotEmpty) _ChipsFiltrosVoz(etiquetas: estado.etiquetasVoz),
          CarruselRecomendaciones(provider: recomendacionesHomeProvider, titulo: 'Para vos'),
          Expanded(child: _Contenido(estado: estado, scrollController: _scrollController)),
        ],
      ),
    );
  }
}

/// Filtros que puso la última búsqueda por voz (P6.1), como chips que se
/// pueden quitar uno por uno sin perder los demás.
class _ChipsFiltrosVoz extends ConsumerWidget {
  const _ChipsFiltrosVoz({required this.etiquetas});

  final Map<String, String> etiquetas;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(AppSpacing.md, AppSpacing.sm, AppSpacing.md, 0),
      child: Wrap(
        spacing: AppSpacing.sm,
        runSpacing: AppSpacing.xs,
        children: [
          for (final entrada in etiquetas.entries)
            InputChip(
              label: Text('${_etiquetasCampoVoz[entrada.key] ?? entrada.key}: ${entrada.value}'),
              onDeleted: () => ref.read(catalogoControllerProvider.notifier).quitarFiltroVoz(entrada.key),
            ),
        ],
      ),
    );
  }
}

class _Contenido extends StatelessWidget {
  const _Contenido({required this.estado, required this.scrollController});

  final CatalogoState estado;
  final ScrollController scrollController;

  @override
  Widget build(BuildContext context) {
    if (estado.cargandoPrimeraPagina) {
      return const Center(child: CircularProgressIndicator(color: AppColors.acento));
    }

    if (estado.error && estado.items.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(AppSpacing.xl),
          child: Text('No se pudo cargar el catálogo. Deslizá para reintentar.', textAlign: TextAlign.center),
        ),
      );
    }

    if (estado.items.isEmpty) {
      return const Center(child: Text('No se encontraron prendas.', style: TextStyle(color: AppColors.textoTenue)));
    }

    return GridView.builder(
      controller: scrollController,
      padding: const EdgeInsets.all(AppSpacing.md),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: 2,
        mainAxisSpacing: AppSpacing.md,
        crossAxisSpacing: AppSpacing.md,
        childAspectRatio: 0.68,
      ),
      itemCount: estado.items.length + (estado.hayMas ? 1 : 0),
      itemBuilder: (context, index) {
        if (index >= estado.items.length) {
          return const Center(child: CircularProgressIndicator(color: AppColors.acento));
        }
        return _TarjetaProducto(item: estado.items[index]);
      },
    );
  }
}

class _TarjetaProducto extends StatelessWidget {
  const _TarjetaProducto({required this.item});

  final CatalogoItem item;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => context.push('/producto/${item.id}'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: ClipRRect(
              borderRadius: BorderRadius.circular(AppRadius.base),
              child: item.imagenPrincipal != null
                  ? CachedNetworkImage(
                      imageUrl: item.imagenPrincipal!,
                      fit: BoxFit.cover,
                      width: double.infinity,
                      placeholder: (context, url) => Container(color: AppColors.fondoAlterno),
                      errorWidget: (context, url, error) => Container(
                        color: AppColors.fondoAlterno,
                        child: const Icon(Icons.checkroom, color: AppColors.textoTenue),
                      ),
                    )
                  : Container(
                      color: AppColors.fondoAlterno,
                      child: const Icon(Icons.checkroom, color: AppColors.textoTenue),
                    ),
            ),
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(item.nombre, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 14)),
          Text(
            'Bs ${item.precioBase.toStringAsFixed(2)}',
            style: const TextStyle(fontWeight: FontWeight.w600, color: AppColors.acento),
          ),
        ],
      ),
    );
  }
}
