import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/network/mensaje_error.dart';
import '../../../core/theme/app_theme.dart';
import '../../reservas/state/reservas_providers.dart' show disponibilidadPorVarianteProvider, disponibleTotalProvider;
import '../models/carrito.dart';
import '../state/carrito_controller.dart';
import '../state/checkout_controller.dart';
import '../state/compras_providers.dart';

class CarritoScreen extends ConsumerWidget {
  const CarritoScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncCarrito = ref.watch(carritoControllerProvider);

    return Scaffold(
      backgroundColor: AppColors.fondo,
      appBar: AppBar(title: const Text('Tu carrito')),
      body: RefreshIndicator(
        onRefresh: () {
          ref.invalidate(disponibilidadPorVarianteProvider);
          return ref.read(carritoControllerProvider.notifier).cargar();
        },
        child: asyncCarrito.when(
          loading: () => const Center(child: CircularProgressIndicator(color: AppColors.acento)),
          error: (error, stack) => ListView(
            children: const [
              Padding(
                padding: EdgeInsets.all(AppSpacing.xl),
                child: Text('No se pudo cargar tu carrito.', textAlign: TextAlign.center),
              ),
            ],
          ),
          data: (carrito) {
            if (carrito.vacio) {
              return ListView(
                children: [
                  Padding(
                    padding: const EdgeInsets.all(AppSpacing.xl),
                    child: Column(
                      children: [
                        const Text(
                          'Todavía no agregaste ninguna prenda.',
                          textAlign: TextAlign.center,
                          style: TextStyle(color: AppColors.textoTenue),
                        ),
                        const SizedBox(height: AppSpacing.md),
                        OutlinedButton(onPressed: () => context.go('/home'), child: const Text('Ver catálogo')),
                      ],
                    ),
                  ),
                ],
              );
            }
            return ListView(
              padding: const EdgeInsets.all(AppSpacing.md),
              children: [
                for (final linea in carrito.detalle) _TarjetaLinea(linea: linea),
                const SizedBox(height: AppSpacing.md),
                const _ResumenCarrito(),
                const SizedBox(height: AppSpacing.lg),
                ElevatedButton(
                  onPressed: () {
                    ref.read(checkoutControllerProvider.notifier).reiniciar();
                    context.push('/checkout/entrega');
                  },
                  child: const Text('Continuar'),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _ResumenCarrito extends ConsumerWidget {
  const _ResumenCarrito();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncResumen = ref.watch(resumenCarritoProvider);
    return asyncResumen.when(
      loading: () => const Padding(padding: EdgeInsets.all(AppSpacing.md), child: LinearProgressIndicator()),
      error: (e, s) => const SizedBox.shrink(),
      data: (resumen) {
        if (resumen == null) return const SizedBox.shrink();
        return Card(
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.md),
            child: Column(
              children: [
                _FilaResumen('Subtotal', resumen.subtotal),
                if (resumen.descuento > 0) _FilaResumen('Descuento', -resumen.descuento, color: AppColors.exito),
                const Divider(),
                _FilaResumen('Total', resumen.total, negrita: true),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _FilaResumen extends StatelessWidget {
  const _FilaResumen(this.etiqueta, this.monto, {this.negrita = false, this.color});

  final String etiqueta;
  final double monto;
  final bool negrita;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final estilo = TextStyle(
      fontWeight: negrita ? FontWeight.w700 : FontWeight.w400,
      fontSize: negrita ? 16 : 14,
      color: color ?? AppColors.texto,
    );
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(etiqueta, style: estilo),
          Text('Bs ${monto.toStringAsFixed(2)}', style: estilo),
        ],
      ),
    );
  }
}

class _TarjetaLinea extends ConsumerStatefulWidget {
  const _TarjetaLinea({required this.linea});

  final CarritoLinea linea;

  @override
  ConsumerState<_TarjetaLinea> createState() => _TarjetaLineaState();
}

class _TarjetaLineaState extends ConsumerState<_TarjetaLinea> {
  // Sin este flag, taps rápidos en +/- disparan varios PATCH concurrentes
  // sin orden garantizado de respuesta: la cantidad final mostrada puede no
  // corresponder al último tap del usuario (M-4 de la auditoría). Mismo
  // patrón que _BotonAgregarCarrito/_BotonFavorito en el detalle de producto.
  bool _actualizando = false;

  Future<void> _ejecutar(Future<void> Function() accion) async {
    setState(() => _actualizando = true);
    try {
      await accion();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(mensajeDeError(e, 'No se pudo actualizar el carrito. Probá de nuevo.'))));
      ref.invalidate(disponibilidadPorVarianteProvider(widget.linea.varianteId));
    } finally {
      if (mounted) setState(() => _actualizando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final linea = widget.linea;
    final controller = ref.read(carritoControllerProvider.notifier);
    final disponible = ref.watch(disponibleTotalProvider(linea.varianteId)).valueOrNull;
    final enElMaximo = disponible != null && linea.cantidad >= disponible;
    final (String? avisoStock, Color colorAviso) = switch (disponible) {
      null => (null, AppColors.textoTenue),
      <= 0 => ('Agotado: quitala para continuar', AppColors.error),
      final d when linea.cantidad > d => ('Solo quedan $d disponibles', AppColors.error),
      final d when d <= 3 => ('Quedan $d', AppColors.advertencia),
      _ => (null, AppColors.textoTenue),
    };
    final subtitulo = [
      if (linea.tallaCodigo != null) linea.tallaCodigo!,
      if (linea.colorNombre != null) linea.colorNombre!,
    ].join(' · ');

    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.sm),
        child: Row(
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(AppRadius.base),
              child: linea.imagenPrincipal != null
                  ? CachedNetworkImage(imageUrl: linea.imagenPrincipal!, width: 56, height: 56, fit: BoxFit.cover)
                  : Container(
                      width: 56,
                      height: 56,
                      color: AppColors.fondoAlterno,
                      child: const Icon(Icons.checkroom, color: AppColors.textoTenue),
                    ),
            ),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    linea.productoNombre ?? 'Prenda',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  if (subtitulo.isNotEmpty)
                    Text(subtitulo, style: const TextStyle(color: AppColors.textoTenue, fontSize: 12)),
                  Text(
                    'Bs ${linea.precioUnitario.toStringAsFixed(2)}',
                    style: const TextStyle(color: AppColors.acento, fontWeight: FontWeight.w600),
                  ),
                  if (avisoStock != null)
                    Text(avisoStock, style: TextStyle(color: colorAviso, fontSize: 12, fontWeight: FontWeight.w600)),
                ],
              ),
            ),
            Column(
              children: [
                Row(
                  children: [
                    IconButton(
                      icon: const Icon(Icons.remove_circle_outline, size: 20),
                      onPressed: _actualizando
                          ? null
                          : (linea.cantidad <= 1
                              ? () => _ejecutar(() => controller.quitar(linea.varianteId))
                              : () => _ejecutar(
                                  () => controller.actualizarCantidad(
                                    varianteId: linea.varianteId,
                                    cantidad: linea.cantidad - 1,
                                  ),
                                )),
                    ),
                    _actualizando
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.acento),
                          )
                        : Text('${linea.cantidad}', style: const TextStyle(fontWeight: FontWeight.w600)),
                    IconButton(
                      icon: const Icon(Icons.add_circle_outline, size: 20),
                      onPressed: _actualizando || enElMaximo
                          ? null
                          : () => _ejecutar(
                              () => controller.actualizarCantidad(
                                varianteId: linea.varianteId,
                                cantidad: linea.cantidad + 1,
                              ),
                            ),
                    ),
                  ],
                ),
                TextButton(
                  onPressed: _actualizando ? null : () => _ejecutar(() => controller.quitar(linea.varianteId)),
                  child: const Text('Quitar', style: TextStyle(fontSize: 12, color: AppColors.error)),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
