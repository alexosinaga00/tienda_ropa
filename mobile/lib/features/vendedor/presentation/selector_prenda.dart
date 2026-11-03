import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/utils/dinero.dart';
import '../data/catalogo_local_repository.dart';
import '../models/producto_local.dart';
import '../models/variante_local.dart';
import '../state/carrito_operacion.dart';
import '../state/catalogo_local_providers.dart';
import 'catalogo_local_screen.dart';
import 'nivel_existencia.dart';

/// Lo que la persona eligió en el selector: la prenda, la variante (talla y color) y cuántas.
class SeleccionPrenda {
  const SeleccionPrenda({required this.producto, required this.variante, required this.cantidad});

  final ProductoLocal producto;
  final VarianteLocal variante;
  final int cantidad;
}

const textoSinPrendas = 'No encontramos prendas con ese texto';

/// Abre el selector de prendas (hoja inferior) y devuelve lo elegido, o `null` si se cerró sin elegir. Lee la copia local del
/// catálogo: sirve sin conexión. Las prendas agotadas se pueden elegir, con un aviso: el servidor decide al sincronizar.
Future<SeleccionPrenda?> mostrarSelectorPrenda(BuildContext context, WidgetRef ref, {required int sucursalId}) async {
  final repositorio = await ref.read(catalogoLocalProvider.future);
  if (repositorio == null || !context.mounted) return null;
  return showModalBottomSheet<SeleccionPrenda>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    showDragHandle: true,
    builder: (sheet) => Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(sheet).bottom),
      child: SizedBox(
        height: MediaQuery.sizeOf(sheet).height * 0.9,
        child: SelectorPrenda(repositorio: repositorio, sucursalId: sucursalId),
      ),
    ),
  );
}

/// El contenido del selector (separado para poder probarlo sin la hoja).
class SelectorPrenda extends StatefulWidget {
  const SelectorPrenda({super.key, required this.repositorio, required this.sucursalId});

  final CatalogoLocalRepository repositorio;
  final int sucursalId;

  @override
  State<SelectorPrenda> createState() => _SelectorPrendaState();
}

class _SelectorPrendaState extends State<SelectorPrenda> {
  final _busqueda = TextEditingController();
  final _scroll = ScrollController();
  Timer? _espera;

  String _texto = '';
  final List<ProductoLocal> _productos = [];
  bool _cargando = true;
  bool _cargandoMas = false;
  bool _hayMas = false;
  bool _error = false;
  int _generacion = 0;

  // Paso 2: la prenda elegida.
  ProductoLocal? _producto;
  List<VarianteLocal> _variantes = const [];
  bool _cargandoVariantes = false;
  bool _errorVariantes = false;
  int? _tallaId;
  int? _colorId;
  int _cantidad = 1;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_alDesplazar);
    unawaited(_recargar());
  }

  @override
  void dispose() {
    _espera?.cancel();
    _scroll.dispose();
    _busqueda.dispose();
    super.dispose();
  }

  void _alDesplazar() {
    if (_scroll.hasClients && _scroll.position.extentAfter < 400) unawaited(_cargarMas());
  }

  Future<void> _recargar() async {
    final generacion = ++_generacion;
    setState(() {
      _cargando = _productos.isEmpty;
      _cargandoMas = false;
      _error = false;
    });
    try {
      final pagina = await widget.repositorio.buscarProductos(
        texto: _texto,
        sucursalId: widget.sucursalId,
        limite: tamanoPaginaCatalogoLocal,
      );
      if (!mounted || generacion != _generacion) return;
      setState(() {
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
      final pagina = await widget.repositorio.buscarProductos(
        texto: _texto,
        sucursalId: widget.sucursalId,
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
      setState(() {
        _hayMas = false;
        _cargandoMas = false;
      });
    }
  }

  /// Si la primera página no llena la hoja no habrá desplazamiento que pida la siguiente: se pide sola.
  void _revisarSiHayHueco() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && _producto == null && _scroll.hasClients && _scroll.position.extentAfter < 400) unawaited(_cargarMas());
    });
  }

  void _alEscribir(String valor) {
    _espera?.cancel();
    _espera = Timer(esperaBusquedaCatalogoLocal, () => _aplicarTexto(valor));
    setState(() {});
  }

  void _aplicarTexto(String valor) {
    _espera?.cancel();
    if (!mounted) return;
    if (valor.trim() == _texto) return;
    _texto = valor.trim();
    unawaited(_recargar());
  }

  // ---- Paso 2 ----

  Future<void> _elegirProducto(ProductoLocal producto) async {
    setState(() {
      _producto = producto;
      _variantes = const [];
      _cargandoVariantes = true;
      _errorVariantes = false;
      _tallaId = null;
      _colorId = null;
      _cantidad = 1;
    });
    try {
      final variantes = await widget.repositorio.variantesDeProducto(producto.id, sucursalId: widget.sucursalId);
      if (!mounted || _producto?.id != producto.id) return;
      // Se parte de una variante con existencia, si hay (lo más común es vender lo que hay).
      final inicial = variantes.where((v) => v.cantidadEstimada > 0).firstOrNull ?? variantes.firstOrNull;
      setState(() {
        _variantes = variantes;
        _cargandoVariantes = false;
        _tallaId = inicial?.tallaId;
        _colorId = inicial?.colorId;
      });
    } catch (_) {
      if (!mounted || _producto?.id != producto.id) return;
      setState(() {
        _cargandoVariantes = false;
        _errorVariantes = true;
      });
    }
  }

  void _volverALista() {
    setState(() {
      _producto = null;
      _variantes = const [];
    });
  }

  void _elegirTalla(int tallaId) {
    final delaTalla = _variantes.where((v) => v.tallaId == tallaId).toList();
    if (delaTalla.isEmpty) return;
    // Se conserva el color si esa talla también lo tiene.
    final conservado = delaTalla.where((v) => v.colorId == _colorId).firstOrNull;
    setState(() {
      _tallaId = tallaId;
      _colorId = (conservado ?? delaTalla.first).colorId;
    });
  }

  VarianteLocal? get _varianteElegida =>
      _variantes.where((v) => v.tallaId == _tallaId && v.colorId == _colorId).firstOrNull;

  void _agregar() {
    final producto = _producto;
    final variante = _varianteElegida;
    if (producto == null || variante == null) return;
    Navigator.of(context).pop(SeleccionPrenda(producto: producto, variante: variante, cantidad: _cantidad));
  }

  @override
  Widget build(BuildContext context) {
    final producto = _producto;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _Cabecera(
          titulo: producto?.nombre ?? 'Elige una prenda',
          alVolver: producto == null ? null : _volverALista,
        ),
        if (producto == null) ...[
          Padding(
            padding: const EdgeInsets.fromLTRB(AppSpacing.md, AppSpacing.sm, AppSpacing.md, AppSpacing.sm),
            child: TextField(
              key: const Key('buscador_prendas'),
              controller: _busqueda,
              textInputAction: TextInputAction.search,
              onChanged: _alEscribir,
              onSubmitted: _aplicarTexto,
              decoration: InputDecoration(
                hintText: 'Buscar por nombre, código o SKU',
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
          Expanded(child: _lista()),
        ] else
          Expanded(child: _detalle(producto)),
      ],
    );
  }

  Widget _lista() {
    if (_cargando) return const Center(child: CircularProgressIndicator());
    if (_error) {
      return _MensajeCentrado(
        icono: Icons.error_outline,
        texto: 'No pudimos leer el catálogo guardado en el teléfono.',
        boton: 'Reintentar',
        alPulsar: () => unawaited(_recargar()),
      );
    }
    if (_productos.isEmpty) {
      return _MensajeCentrado(
        icono: Icons.search_off,
        texto: _texto.isNotEmpty ? textoSinPrendas : 'Aún no hay prendas descargadas en el teléfono.',
      );
    }
    return ListView.builder(
      controller: _scroll,
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
      itemCount: _productos.length + 1,
      itemBuilder: (context, i) {
        if (i == _productos.length) {
          return Padding(
            padding: const EdgeInsets.all(AppSpacing.md),
            child: Center(child: _cargandoMas ? const CircularProgressIndicator() : const SizedBox(height: 4)),
          );
        }
        final p = _productos[i];
        return _FilaPrenda(producto: p, alTocar: () => unawaited(_elegirProducto(p)));
      },
    );
  }

  Widget _detalle(ProductoLocal producto) {
    if (_cargandoVariantes) return const Center(child: CircularProgressIndicator());
    if (_errorVariantes) {
      return _MensajeCentrado(
        icono: Icons.error_outline,
        texto: 'No pudimos leer las tallas de esta prenda.',
        boton: 'Reintentar',
        alPulsar: () => unawaited(_elegirProducto(producto)),
      );
    }
    if (_variantes.isEmpty) {
      return const _MensajeCentrado(icono: Icons.search_off, texto: 'Esta prenda no tiene tallas disponibles.');
    }

    final tema = Theme.of(context);
    final tallas = <int, VarianteLocal>{};
    for (final v in _variantes) {
      tallas.putIfAbsent(v.tallaId, () => v);
    }
    final tallasOrdenadas = tallas.values.toList()..sort((a, b) => a.tallaOrden.compareTo(b.tallaOrden));
    final colores = _variantes.where((v) => v.tallaId == _tallaId).toList();
    final variante = _varianteElegida;

    return Column(
      children: [
        Expanded(
          child: ListView(
            padding: const EdgeInsets.all(AppSpacing.md),
            children: [
              Text('Talla', style: tema.textTheme.titleMedium?.copyWith(color: AppColors.texto)),
              const SizedBox(height: AppSpacing.sm),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.xs,
                children: [
                  for (final t in tallasOrdenadas)
                    ChoiceChip(
                      key: Key('talla_${t.tallaCodigo}'),
                      label: Text(t.tallaCodigo),
                      selected: t.tallaId == _tallaId,
                      onSelected: (_) => _elegirTalla(t.tallaId),
                      materialTapTargetSize: MaterialTapTargetSize.padded,
                    ),
                ],
              ),
              const SizedBox(height: AppSpacing.md),
              Text(
                variante == null ? 'Color' : 'Color: ${variante.colorNombre}',
                style: tema.textTheme.titleMedium?.copyWith(color: AppColors.texto),
              ),
              const SizedBox(height: AppSpacing.xs),
              Wrap(
                spacing: AppSpacing.xs,
                children: [
                  for (final v in colores)
                    _CirculoColor(variante: v, elegido: v.colorId == _colorId, alTocar: () => setState(() => _colorId = v.colorId)),
                ],
              ),
              const SizedBox(height: AppSpacing.md),
              if (variante != null) _InfoVariante(variante: variante),
            ],
          ),
        ),
        _BarraAgregar(
          cantidad: _cantidad,
          alCambiar: (c) => setState(() => _cantidad = c),
          alAgregar: variante == null ? null : _agregar,
        ),
      ],
    );
  }
}

class _Cabecera extends StatelessWidget {
  const _Cabecera({required this.titulo, this.alVolver});

  final String titulo;
  final VoidCallback? alVolver;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: AppSpacing.sm, right: AppSpacing.sm),
      child: Row(
        children: [
          if (alVolver != null)
            IconButton(
              key: const Key('volver_a_la_lista'),
              tooltip: 'Volver a la lista',
              icon: const Icon(Icons.arrow_back, size: 24),
              onPressed: alVolver,
            )
          else
            const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Semantics(
              header: true,
              child: Text(
                titulo,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.titleLarge?.copyWith(color: AppColors.texto, fontWeight: FontWeight.w600),
              ),
            ),
          ),
          IconButton(
            tooltip: 'Cerrar',
            icon: const Icon(Icons.close, size: 24),
            onPressed: () => Navigator.of(context).pop(),
          ),
        ],
      ),
    );
  }
}

class _FilaPrenda extends StatelessWidget {
  const _FilaPrenda({required this.producto, required this.alTocar});

  final ProductoLocal producto;
  final VoidCallback alTocar;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final existencia = producto.existenciaEstimada;
    final nivel = existencia == null ? null : NivelExistencia.de(existencia);
    final precio = formatearBs(producto.precioDesdeCentavos);
    return Semantics(
      button: true,
      label: producto.nombre,
      child: InkWell(
        key: Key('prenda_${producto.id}'),
        onTap: alTocar,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 72),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
            child: Row(
              children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(AppRadius.base),
                  child: SizedBox(
                    width: 64,
                    height: 64,
                    child: FotoPrenda(nombre: producto.nombre, productoId: producto.id, url: producto.imagenUrl, compacta: true),
                  ),
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        producto.nombre,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: tema.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600),
                      ),
                      Text(producto.tieneRangoDePrecio ? 'Desde $precio' : precio, style: tema.textTheme.bodyMedium),
                      if (nivel != null)
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
                  ),
                ),
                const Icon(Icons.chevron_right, size: 24, color: AppColors.textoTenue),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

Color? _colorDeHex(String? hex) {
  if (hex == null) return null;
  final limpio = hex.replaceFirst('#', '');
  if (limpio.length != 6) return null;
  final valor = int.tryParse(limpio, radix: 16);
  return valor == null ? null : Color(0xFF000000 | valor);
}

class _CirculoColor extends StatelessWidget {
  const _CirculoColor({required this.variante, required this.elegido, required this.alTocar});

  final VarianteLocal variante;
  final bool elegido;
  final VoidCallback alTocar;

  @override
  Widget build(BuildContext context) {
    final muestra = _colorDeHex(variante.colorHex);
    return Semantics(
      button: true,
      selected: elegido,
      label: 'Color ${variante.colorNombre}',
      child: InkResponse(
        key: Key('color_${variante.colorNombre}'),
        onTap: alTocar,
        radius: 28,
        child: SizedBox(
          width: 48,
          height: 48,
          child: Center(
            child: Container(
              width: 36,
              height: 36,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: muestra ?? AppColors.fondoAlterno,
                shape: BoxShape.circle,
                border: Border.all(color: elegido ? AppColors.acento : AppColors.borde, width: elegido ? 3 : 1),
              ),
              // Sin código de color se muestra la inicial: nunca un círculo mudo.
              child: muestra == null
                  ? Text(
                      variante.colorNombre.isEmpty ? '?' : variante.colorNombre[0].toUpperCase(),
                      style: const TextStyle(color: AppColors.texto, fontSize: 14, fontWeight: FontWeight.w600),
                    )
                  : (elegido ? const Icon(Icons.check, size: 20, color: Colors.white) : null),
            ),
          ),
        ),
      ),
    );
  }
}

class _InfoVariante extends StatelessWidget {
  const _InfoVariante({required this.variante});

  final VarianteLocal variante;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final nivel = NivelExistencia.de(variante.cantidadEstimada);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: AppSpacing.sm,
          children: [
            if (variante.tieneDescuento)
              Text(
                formatearBs(variante.precioCentavos),
                style: tema.textTheme.bodyMedium?.copyWith(decoration: TextDecoration.lineThrough),
              ),
            Text(
              formatearBs(variante.precioFinalCentavos),
              key: const Key('precio_variante'),
              style: tema.textTheme.titleLarge?.copyWith(color: AppColors.texto, fontWeight: FontWeight.w600),
            ),
          ],
        ),
        const SizedBox(height: AppSpacing.sm),
        Container(
          key: const Key('existencia_variante'),
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm, vertical: AppSpacing.xs),
          decoration: BoxDecoration(
            color: nivel.color.withValues(alpha: 0.12),
            borderRadius: BorderRadius.circular(AppRadius.base),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(nivel.icono, size: 20, color: nivel.color),
              const SizedBox(width: AppSpacing.xs),
              Flexible(
                child: Text(
                  '${nivel.etiqueta} (${variante.cantidadEstimada})',
                  style: TextStyle(color: nivel.color, fontSize: 14, fontWeight: FontWeight.w600),
                ),
              ),
            ],
          ),
        ),
        if (nivel == NivelExistencia.agotado)
          const Padding(
            padding: EdgeInsets.only(top: AppSpacing.sm),
            child: Text(
              'Esta variante figura agotada en tu sucursal. Puedes agregarla igual: el servidor lo confirmará al sincronizar.',
              key: Key('aviso_agotada'),
              style: TextStyle(color: AppColors.advertencia, fontSize: 14),
            ),
          ),
        const SizedBox(height: AppSpacing.xs),
        Text('Es una estimación: no incluye ventas de otros dispositivos.', style: tema.textTheme.bodyMedium?.copyWith(fontSize: 12)),
      ],
    );
  }
}

class _BarraAgregar extends StatelessWidget {
  const _BarraAgregar({required this.cantidad, required this.alCambiar, required this.alAgregar});

  final int cantidad;
  final ValueChanged<int> alCambiar;
  final VoidCallback? alAgregar;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(AppSpacing.md, AppSpacing.sm, AppSpacing.md, AppSpacing.md),
      decoration: const BoxDecoration(
        color: AppColors.fondo,
        border: Border(top: BorderSide(color: AppColors.borde)),
      ),
      child: Row(
        children: [
          IconButton(
            key: const Key('selector_menos'),
            tooltip: 'Menos',
            icon: const Icon(Icons.remove_circle_outline, size: 28),
            onPressed: cantidad > 1 ? () => alCambiar(cantidad - 1) : null,
          ),
          Container(
            key: const Key('selector_cantidad'),
            constraints: const BoxConstraints(minWidth: 40),
            alignment: Alignment.center,
            child: Text(
              '$cantidad',
              style: Theme.of(context).textTheme.titleLarge?.copyWith(color: AppColors.texto, fontWeight: FontWeight.w600),
            ),
          ),
          IconButton(
            key: const Key('selector_mas'),
            tooltip: 'Más',
            icon: const Icon(Icons.add_circle_outline, size: 28),
            onPressed: cantidad < maxCantidadPorLinea ? () => alCambiar(cantidad + 1) : null,
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: ElevatedButton(
              key: const Key('boton_agregar'),
              style: ElevatedButton.styleFrom(minimumSize: const Size(48, 52)),
              onPressed: alAgregar,
              child: const Text('Agregar'),
            ),
          ),
        ],
      ),
    );
  }
}

class _MensajeCentrado extends StatelessWidget {
  const _MensajeCentrado({required this.icono, required this.texto, this.boton, this.alPulsar});

  final IconData icono;
  final String texto;
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
            Text(texto, textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodyLarge),
            if (boton != null) ...[
              const SizedBox(height: AppSpacing.lg),
              ElevatedButton(
                style: ElevatedButton.styleFrom(minimumSize: const Size(160, 52)),
                onPressed: alPulsar,
                child: Text(boton!),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
