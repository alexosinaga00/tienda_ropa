import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/utils/dinero.dart';
import '../../compras/state/carrito_controller.dart';
import '../config/cliente_offline_config.dart';
import '../models/linea_carrito_local.dart';
import '../state/cliente_offline_providers.dart';
import 'checkout_sin_conexion_screen.dart' show MiniaturaPrenda;

/// El carrito LOCAL, para mostrar en lugar del carrito del servidor cuando no hay conexión: las prendas que el cliente
/// agregó sin red, con los precios que vio, y el pago con su PayPal guardado.
class CarritoLocalVista extends ConsumerWidget {
  const CarritoLocalVista({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final lineas = ref.watch(carritoLocalProvider);
    final tienePaypal = ref.watch(tienePaypalGuardadoProvider);

    if (lineas.isEmpty) {
      return ListView(
        key: const Key('carrito-local-vacio'),
        padding: const EdgeInsets.all(AppSpacing.xl),
        children: [
          const Text(
            'No agregaste prendas sin conexión. Cuando vuelva la conexión verás tu carrito de siempre.',
            textAlign: TextAlign.center,
            style: TextStyle(color: AppColors.textoTenue),
          ),
          const SizedBox(height: AppSpacing.md),
          OutlinedButton(onPressed: () => context.go('/home'), child: const Text('Ver catálogo')),
        ],
      );
    }

    return ListView(
      key: const Key('carrito-local'),
      padding: const EdgeInsets.all(AppSpacing.md),
      children: [
        const Padding(
          padding: EdgeInsets.only(bottom: AppSpacing.sm),
          child: Text(
            'Estas prendas se guardaron sin conexión, con los precios que viste. El stock se confirma al cobrar.',
            style: TextStyle(color: AppColors.textoTenue, fontSize: 13),
          ),
        ),
        for (final linea in lineas) _TarjetaLineaLocal(linea: linea),
        const SizedBox(height: AppSpacing.md),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.md),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text('Subtotal', style: TextStyle(fontWeight: FontWeight.w700)),
                Text(
                  formatearBs(totalDeLineasCentavos(lineas)),
                  key: const Key('subtotal-local'),
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: AppSpacing.lg),
        if (tienePaypal)
          ElevatedButton.icon(
            key: const Key('pagar-paypal-guardado'),
            onPressed: () => context.push('/checkout/sin-conexion'),
            icon: const Icon(Icons.lock_outline),
            label: const Text('Pagar con mi PayPal guardado'),
          )
        else ...[
          const ElevatedButton(
            key: Key('pagar-paypal-deshabilitado'),
            onPressed: null,
            child: Text('Pagar con mi PayPal guardado'),
          ),
          const SizedBox(height: AppSpacing.xs),
          const Text(
            '$textoPaypalSinGuardar.',
            key: Key('texto-paypal-sin-guardar'),
            textAlign: TextAlign.center,
            style: TextStyle(color: AppColors.textoTenue, fontSize: 13),
          ),
          TextButton(
            key: const Key('ir-a-metodo-de-pago'),
            onPressed: () => context.push('/cuenta/metodo-pago'),
            child: const Text('Ir a Método de pago'),
          ),
        ],
      ],
    );
  }
}

class _TarjetaLineaLocal extends ConsumerWidget {
  const _TarjetaLineaLocal({required this.linea});

  final LineaCarritoLocal linea;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controlador = ref.read(carritoLocalProvider.notifier);
    return Card(
      key: Key('linea-local-${linea.varianteId}'),
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.sm),
        child: Row(
          children: [
            MiniaturaPrenda(url: linea.imagen, tamano: 56),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    linea.productoNombre,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  if (linea.detalle.isNotEmpty)
                    Text(linea.detalle, style: const TextStyle(color: AppColors.textoTenue, fontSize: 12)),
                  Text(
                    formatearBs(linea.precioUnitarioCentavos),
                    style: const TextStyle(color: AppColors.acento, fontWeight: FontWeight.w600),
                  ),
                ],
              ),
            ),
            Column(
              children: [
                Row(
                  children: [
                    IconButton(
                      key: Key('menos-${linea.varianteId}'),
                      icon: const Icon(Icons.remove_circle_outline, size: 20),
                      onPressed: () => controlador.cambiarCantidad(linea.varianteId, linea.cantidad - 1),
                    ),
                    Text('${linea.cantidad}', style: const TextStyle(fontWeight: FontWeight.w600)),
                    IconButton(
                      key: Key('mas-${linea.varianteId}'),
                      icon: const Icon(Icons.add_circle_outline, size: 20),
                      onPressed: linea.cantidad >= maxUnidadesLinea
                          ? null
                          : () => controlador.cambiarCantidad(linea.varianteId, linea.cantidad + 1),
                    ),
                  ],
                ),
                TextButton(
                  key: Key('quitar-${linea.varianteId}'),
                  onPressed: () => controlador.quitar(linea.varianteId),
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

/// Con conexión y prendas guardadas sin red: NO se mezclan solas con el carrito del servidor. El cliente decide: pasarlas
/// (una por una; las que el servidor rechaza se quedan aquí) o descartarlas.
class AvisoCarritoLocalEnLinea extends ConsumerStatefulWidget {
  const AvisoCarritoLocalEnLinea({super.key});

  @override
  ConsumerState<AvisoCarritoLocalEnLinea> createState() => _AvisoCarritoLocalEnLineaState();
}

class _AvisoCarritoLocalEnLineaState extends ConsumerState<AvisoCarritoLocalEnLinea> {
  bool _pasando = false;

  Future<void> _pasar() async {
    setState(() => _pasando = true);
    final carrito = ref.read(carritoControllerProvider.notifier);
    final resultado = await ref
        .read(carritoLocalProvider.notifier)
        .pasarAlServidor((varianteId, cantidad) => carrito.agregar(varianteId: varianteId, cantidad: cantidad));
    if (!mounted) return;
    setState(() => _pasando = false);
    final pasadas = resultado.pasadas;
    final fallidas = resultado.fallidas;
    final texto = StringBuffer(
      pasadas == 0
          ? 'No pudimos pasar tus prendas.'
          : pasadas == 1
          ? 'Pasó 1 prenda a tu carrito.'
          : 'Pasaron $pasadas prendas a tu carrito.',
    );
    if (fallidas > 0) {
      texto.write(
        ' ${fallidas == 1 ? '1 no se pudo pasar' : '$fallidas no se pudieron pasar'} (sin stock o ya no existe): '
        'sigue guardada aquí.',
      );
    }
    ScaffoldMessenger.of(context)
      ..clearSnackBars()
      ..showSnackBar(SnackBar(content: Text(texto.toString()), behavior: SnackBarBehavior.floating));
  }

  Future<void> _descartar() async {
    final confirmado = await showDialog<bool>(
      context: context,
      builder: (contexto) => AlertDialog(
        title: const Text('¿Descartar las prendas guardadas sin conexión?'),
        content: const Text('Se borran de este teléfono. No afecta a tu carrito de siempre.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(contexto, false), child: const Text('Cancelar')),
          TextButton(
            key: const Key('confirmar-descartar-local'),
            onPressed: () => Navigator.pop(contexto, true),
            child: const Text('Sí, descartar'),
          ),
        ],
      ),
    );
    if (confirmado == true) await ref.read(carritoLocalProvider.notifier).vaciar();
  }

  @override
  Widget build(BuildContext context) {
    final lineas = ref.watch(carritoLocalProvider);
    if (lineas.isEmpty) return const SizedBox.shrink();
    final cantidad = lineas.fold(0, (suma, l) => suma + l.cantidad);
    final tienePaypal = ref.watch(tienePaypalGuardadoProvider);
    return Card(
      key: const Key('aviso-carrito-local'),
      margin: const EdgeInsets.fromLTRB(AppSpacing.md, AppSpacing.md, AppSpacing.md, 0),
      color: AppColors.fondoAlterno,
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Tienes $cantidad ${cantidad == 1 ? 'prenda guardada' : 'prendas guardadas'} sin conexión',
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              [for (final l in lineas) '${l.cantidad} × ${l.productoNombre}'].join(', '),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: AppColors.textoTenue, fontSize: 13),
            ),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              children: [
                FilledButton(
                  key: const Key('pasar-a-mi-carrito'),
                  onPressed: _pasando ? null : _pasar,
                  child: Text(_pasando ? 'Pasando…' : 'Pasar a mi carrito'),
                ),
                OutlinedButton(
                  key: const Key('descartar-carrito-local'),
                  onPressed: _pasando ? null : _descartar,
                  child: const Text('Descartar'),
                ),
                if (tienePaypal)
                  TextButton(
                    key: const Key('pagar-local-con-paypal'),
                    onPressed: _pasando ? null : () => context.push('/checkout/sin-conexion'),
                    child: const Text('Pagar con mi PayPal guardado'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
