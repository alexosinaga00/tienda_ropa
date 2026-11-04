import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/app_theme.dart';
import '../models/venta.dart';
import '../state/compras_providers.dart';
import '../state/mis_compras_controller.dart';

const _colorEstadoVenta = {
  'pendiente_pago': AppColors.textoTenue,
  'pagada': AppColors.exito,
  'entregada': AppColors.exito,
  'anulada': AppColors.error,
};

class MisComprasScreen extends ConsumerWidget {
  const MisComprasScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncCompras = ref.watch(misComprasControllerProvider);

    return Scaffold(
      backgroundColor: AppColors.fondo,
      appBar: AppBar(title: const Text('Mis compras')),
      body: RefreshIndicator(
        onRefresh: () => ref.read(misComprasControllerProvider.notifier).cargar(),
        child: asyncCompras.when(
          loading: () => const Center(child: CircularProgressIndicator(color: AppColors.acento)),
          error: (error, stack) => ListView(
            children: const [
              Padding(
                padding: EdgeInsets.all(AppSpacing.xl),
                child: Text('No se pudieron cargar tus compras.', textAlign: TextAlign.center),
              ),
            ],
          ),
          data: (compras) {
            if (compras.isEmpty) {
              return ListView(
                children: const [
                  Padding(
                    padding: EdgeInsets.all(AppSpacing.xl),
                    child: Text(
                      'Todavía no hiciste ninguna compra.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: AppColors.textoTenue),
                    ),
                  ),
                ],
              );
            }
            return ListView(
              padding: const EdgeInsets.all(AppSpacing.md),
              children: [for (final venta in compras) _TarjetaVenta(venta: venta)],
            );
          },
        ),
      ),
    );
  }
}

class _TarjetaVenta extends ConsumerWidget {
  const _TarjetaVenta({required this.venta});

  final Venta venta;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Un cambio de talla o color que el cliente pidió y la tienda todavía no atendió.
    final conCambioPendiente = ref.watch(comprasConCambioPendienteProvider).valueOrNull?.contains(venta.id) ?? false;
    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: ListTile(
        onTap: () => context.push('/compras/${venta.id}'),
        title: Text(venta.codigo),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${venta.esEnvioADomicilio ? 'Envío a domicilio' : 'Retiro en sucursal'} · '
              'Bs ${venta.total.toStringAsFixed(2)}'
              '${venta.etiquetaDevolucion != null ? ' · ${venta.etiquetaDevolucion}' : ''}',
            ),
            if (conCambioPendiente)
              const Padding(
                padding: EdgeInsets.only(top: AppSpacing.xs),
                child: Chip(
                  key: Key('chip-cambio-pendiente'),
                  label: Text('Cambio pendiente', style: TextStyle(fontSize: 12)),
                  backgroundColor: AppColors.fondoAlterno,
                  visualDensity: VisualDensity.compact,
                ),
              ),
          ],
        ),
        trailing: Chip(
          label: Text(
            etiquetasEstadoVenta[venta.estado] ?? venta.estado,
            style: TextStyle(fontSize: 12, color: _colorEstadoVenta[venta.estado]),
          ),
        ),
      ),
    );
  }
}
