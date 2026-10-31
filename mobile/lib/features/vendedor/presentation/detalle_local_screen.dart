import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/utils/dinero.dart';
import '../../../core/widgets/indicador_conexion.dart';
import '../data/politica_vigencia.dart';
import '../models/producto_local.dart';
import '../models/variante_local.dart';
import '../state/catalogo_local_providers.dart';
import 'aviso_vigencia.dart';
import 'catalogo_local_screen.dart';
import 'nivel_existencia.dart';

const textoPrendaNoEncontrada = 'No encontramos esta prenda.';
const textoSinExistencias = 'Sin existencias descargadas';

/// Lo que el detalle muestra de una prenda de la copia local.
class DatosDetalleLocal {
  const DatosDetalleLocal({required this.producto, required this.variantes, required this.sucursalId});

  final ProductoLocal producto;
  final List<VarianteLocal> variantes;
  final int? sucursalId;
}

/// Se recalcula al terminar una descarga o al cambiar la sucursal activa. `null` = la prenda no existe (o es de otra empresa).
final detalleLocalProvider = FutureProvider.autoDispose.family<DatosDetalleLocal?, int>((ref, productoId) async {
  ref.watch(descargaTerminadaProvider);
  final repositorio = await ref.watch(catalogoLocalProvider.future);
  final sucursal = await ref.watch(sucursalActivaProvider.future);
  if (repositorio == null) return null;
  final producto = await repositorio.productoPorId(productoId, sucursalId: sucursal);
  if (producto == null) return null;
  final variantes = sucursal == null ? const <VarianteLocal>[] : await repositorio.variantesDeProducto(productoId, sucursalId: sucursal);
  return DatosDetalleLocal(producto: producto, variantes: variantes, sucursalId: sucursal);
});

String _generoLegible(String genero) => switch (genero) {
  'masculino' => 'Hombre',
  'femenino' => 'Mujer',
  'unisex' => 'Unisex',
  'ninos' || 'niños' => 'Niños',
  final otro => otro.isEmpty ? otro : '${otro[0].toUpperCase()}${otro.substring(1)}',
};

Color? _colorDeHex(String? hex) {
  if (hex == null) return null;
  final limpio = hex.replaceFirst('#', '');
  if (limpio.length != 6) return null;
  final valor = int.tryParse(limpio, radix: 16);
  return valor == null ? null : Color(0xFF000000 | valor);
}

/// El detalle de una prenda sin conexión: foto, precio y la cuadrícula talla x color con la existencia ESTIMADA de la sucursal
/// activa. Aún no tiene botón de compra (llega con la caja).
class DetalleLocalScreen extends ConsumerWidget {
  const DetalleLocalScreen({super.key, required this.productoId});

  final int productoId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final datos = ref.watch(detalleLocalProvider(productoId));
    final prenda = datos.valueOrNull;

    return Scaffold(
      appBar: AppBar(title: Text(prenda?.producto.nombre ?? 'Prenda', maxLines: 1, overflow: TextOverflow.ellipsis)),
      body: datos.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (_, _) => _NoEncontrada(mensaje: 'No pudimos leer esta prenda del teléfono.'),
        data: (d) => d == null ? const _NoEncontrada(mensaje: textoPrendaNoEncontrada) : _Contenido(datos: d),
      ),
    );
  }
}

class _NoEncontrada extends StatelessWidget {
  const _NoEncontrada({required this.mensaje});

  final String mensaje;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.search_off, size: 48, color: AppColors.textoTenue),
            const SizedBox(height: AppSpacing.md),
            Text(mensaje, textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodyLarge),
            const SizedBox(height: AppSpacing.lg),
            ElevatedButton(
              onPressed: () => context.canPop() ? context.pop() : context.go('/vendedor/catalogo'),
              child: const Text('Volver al catálogo'),
            ),
          ],
        ),
      ),
    );
  }
}

class _Contenido extends ConsumerWidget {
  const _Contenido({required this.datos});

  final DatosDetalleLocal datos;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tema = Theme.of(context);
    final producto = datos.producto;
    final variantes = datos.variantes;
    final vigencia = ref.watch(vigenciaProvider).valueOrNull;
    final sinDescarga = vigencia == null || vigencia.estado == EstadoVigencia.nunca;

    // La hora del stock más reciente de las variantes (UTC en la base; se muestra en la hora del teléfono).
    final conocidas = variantes.map((v) => v.generadoEn).whereType<DateTime>().toList()..sort();
    final existenciaAl = conocidas.isEmpty ? null : conocidas.last;

    return Column(
      children: [
        const AvisoVigencia(),
        const IndicadorConexion.banner(),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.all(AppSpacing.md),
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(AppRadius.base),
                child: AspectRatio(
                  aspectRatio: 1,
                  child: FotoPrenda(nombre: producto.nombre, productoId: producto.id, url: producto.imagenUrl),
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              Text(producto.nombre, style: tema.textTheme.headlineMedium),
              const SizedBox(height: AppSpacing.xs),
              Text('Código: ${producto.codigo}', style: tema.textTheme.bodyMedium),
              Text('Categoría: ${producto.categoriaNombre}', style: tema.textTheme.bodyMedium),
              Text('Género: ${_generoLegible(producto.genero)}', style: tema.textTheme.bodyMedium),
              const SizedBox(height: AppSpacing.md),
              _Precio(producto: producto, variantes: variantes),
              const SizedBox(height: AppSpacing.lg),
              Text('Tallas y colores', style: tema.textTheme.titleMedium?.copyWith(color: AppColors.texto)),
              const SizedBox(height: AppSpacing.sm),
              if (variantes.isEmpty)
                Text('Esta prenda no tiene tallas disponibles.', style: tema.textTheme.bodyMedium)
              else
                _CuadriculaVariantes(variantes: variantes, sinDescarga: sinDescarga),
              const SizedBox(height: AppSpacing.md),
              Text(
                existenciaAl == null ? textoSinExistencias : 'Existencia conocida al ${fechaCortaLocal(existenciaAl)}',
                key: const Key('leyenda_existencia'),
                style: tema.textTheme.bodyMedium,
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                'Es una estimación: no incluye ventas de otros dispositivos posteriores a esa hora.',
                style: tema.textTheme.bodyMedium?.copyWith(fontSize: 12),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _Precio extends StatelessWidget {
  const _Precio({required this.producto, required this.variantes});

  final ProductoLocal producto;
  final List<VarianteLocal> variantes;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    if (variantes.isEmpty) {
      return Text(formatearBs(producto.precioDesdeCentavos), style: tema.textTheme.titleLarge?.copyWith(color: AppColors.texto));
    }
    // La variante más barata (ya con descuento): si tiene descuento se muestra el precio tachado y el final.
    final ordenadas = [...variantes]..sort((a, b) => a.precioFinalCentavos.compareTo(b.precioFinalCentavos));
    final menor = ordenadas.first;
    final mayor = ordenadas.last;
    final hayRango = mayor.precioFinalCentavos > menor.precioFinalCentavos;
    return Wrap(
      crossAxisAlignment: WrapCrossAlignment.center,
      spacing: AppSpacing.sm,
      children: [
        if (hayRango) Text('Desde', style: tema.textTheme.bodyMedium),
        if (menor.tieneDescuento)
          Text(
            formatearBs(menor.precioCentavos),
            key: const Key('precio_tachado'),
            style: tema.textTheme.bodyMedium?.copyWith(decoration: TextDecoration.lineThrough),
          ),
        Text(
          formatearBs(menor.precioFinalCentavos),
          key: const Key('precio_final'),
          style: tema.textTheme.titleLarge?.copyWith(color: AppColors.texto, fontWeight: FontWeight.w600),
        ),
      ],
    );
  }
}

class _CuadriculaVariantes extends StatelessWidget {
  const _CuadriculaVariantes({required this.variantes, required this.sinDescarga});

  final List<VarianteLocal> variantes;
  final bool sinDescarga;

  @override
  Widget build(BuildContext context) {
    final preciosDistintos = variantes.map((v) => v.precioFinalCentavos).toSet().length > 1;
    return LayoutBuilder(
      builder: (context, restricciones) {
        final ancho = (restricciones.maxWidth - AppSpacing.sm) / 2;
        return Wrap(
          spacing: AppSpacing.sm,
          runSpacing: AppSpacing.sm,
          children: [
            for (final v in variantes)
              SizedBox(
                width: ancho,
                child: _CeldaVariante(variante: v, sinDescarga: sinDescarga, mostrarPrecio: preciosDistintos),
              ),
          ],
        );
      },
    );
  }
}

class _CeldaVariante extends StatelessWidget {
  const _CeldaVariante({required this.variante, required this.sinDescarga, required this.mostrarPrecio});

  final VarianteLocal variante;
  final bool sinDescarga;
  final bool mostrarPrecio;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final muestra = _colorDeHex(variante.colorHex);
    final sinDato = sinDescarga && variante.generadoEn == null;
    final nivel = NivelExistencia.de(variante.cantidadEstimada);
    final color = sinDato ? AppColors.textoTenue : nivel.color;

    return Container(
      key: Key('celda_variante_${variante.id}'),
      constraints: const BoxConstraints(minHeight: 48),
      padding: const EdgeInsets.all(AppSpacing.sm),
      decoration: BoxDecoration(
        color: AppColors.fondo,
        border: Border.all(color: AppColors.borde),
        borderRadius: BorderRadius.circular(AppRadius.base),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              if (muestra != null) ...[
                Container(
                  width: 16,
                  height: 16,
                  decoration: BoxDecoration(
                    color: muestra,
                    shape: BoxShape.circle,
                    border: Border.all(color: AppColors.borde),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
              ],
              Expanded(
                child: Text(
                  '${variante.tallaCodigo} · ${variante.colorNombre}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: tema.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600),
                ),
              ),
            ],
          ),
          if (mostrarPrecio) Text(formatearBs(variante.precioFinalCentavos), style: tema.textTheme.bodyMedium),
          const SizedBox(height: AppSpacing.xs),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm, vertical: AppSpacing.xs),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(AppRadius.base),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(sinDato ? Icons.help_outline : nivel.icono, size: 20, color: color),
                const SizedBox(width: AppSpacing.xs),
                Flexible(
                  child: Text(
                    sinDato ? 'Sin dato' : nivel.etiqueta,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(color: color, fontSize: 14, fontWeight: FontWeight.w600),
                  ),
                ),
                if (!sinDato) ...[
                  const SizedBox(width: AppSpacing.xs),
                  Text('(${variante.cantidadEstimada})', style: TextStyle(color: color, fontSize: 14)),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}
