import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/app_theme.dart';
import '../models/cotizacion_envio.dart';
import '../models/direccion_cliente.dart';
import '../state/checkout_controller.dart';
import '../state/compras_providers.dart';
class EntregaScreen extends ConsumerWidget {
  const EntregaScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final checkout = ref.watch(checkoutControllerProvider);
    final controller = ref.read(checkoutControllerProvider.notifier);

    // Cuando ya hay una dirección elegida, cotiza el envío y lo guarda en
    // el estado del checkout apenas llega la respuesta.
    if (checkout.tipoEntrega == TipoEntrega.domicilio && checkout.direccionId != null) {
      ref.listen<AsyncValue<CotizacionEnvio>>(cotizacionEnvioProvider(checkout.direccionId!), (previo, siguiente) {
        siguiente.whenData((cotizacion) => controller.fijarCotizacion(cotizacion));
      });
    }

    return Scaffold(
      backgroundColor: AppColors.fondo,
      appBar: AppBar(title: const Text('Entrega')),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.md),
        children: [
          const Text('¿Cómo querés recibir tu pedido?', style: TextStyle(color: AppColors.textoTenue, fontSize: 12)),
          const SizedBox(height: AppSpacing.xs),
          Wrap(
            spacing: AppSpacing.sm,
            children: [
              ChoiceChip(
                label: const Text('Retiro en sucursal'),
                selected: checkout.tipoEntrega == TipoEntrega.retiro,
                onSelected: (_) => controller.elegirTipoEntrega(TipoEntrega.retiro),
              ),
              ChoiceChip(
                label: const Text('Envío a domicilio'),
                selected: checkout.tipoEntrega == TipoEntrega.domicilio,
                onSelected: (_) => controller.elegirTipoEntrega(TipoEntrega.domicilio),
              ),
            ],
          ),

          if (checkout.tipoEntrega == TipoEntrega.domicilio) ...[
            const SizedBox(height: AppSpacing.lg),
            const Text('Dirección', style: TextStyle(color: AppColors.textoTenue, fontSize: 12)),
            const SizedBox(height: AppSpacing.xs),
            const _SelectorDireccion(),
            if (checkout.direccionId != null) ...[
              const SizedBox(height: AppSpacing.sm),
              _CostoEnvio(direccionId: checkout.direccionId!),
            ],
          ],

          if (checkout.tipoEntrega != null) ...[
            const SizedBox(height: AppSpacing.lg),
            Text(
              checkout.tipoEntrega == TipoEntrega.retiro
                  ? '¿En qué sucursal retirás?'
                  : 'Sucursal que despacha tu pedido',
              style: const TextStyle(color: AppColors.textoTenue, fontSize: 12),
            ),
            const SizedBox(height: AppSpacing.xs),
            const _SelectorSucursal(),
          ],

          const SizedBox(height: AppSpacing.xl),
          ElevatedButton(
            onPressed: checkout.listoParaPagar ? () => context.push('/checkout/pago') : null,
            child: const Text('Continuar'),
          ),
        ],
      ),
    );
  }
}

class _SelectorSucursal extends ConsumerWidget {
  const _SelectorSucursal();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncSucursales = ref.watch(sucursalesConStockCarritoProvider);
    final checkout = ref.watch(checkoutControllerProvider);
    final controller = ref.read(checkoutControllerProvider.notifier);
    return asyncSucursales.when(
      loading: () => const LinearProgressIndicator(),
      error: (e, s) => const Text('No se pudo cargar la disponibilidad.', style: TextStyle(color: AppColors.error)),
      data: (todas) {
        // Para retirar no sirve un depósito (no recibe clientes); un envío a
        // domicilio sí lo puede despachar.
        final sucursales = checkout.tipoEntrega == TipoEntrega.retiro
            ? todas.where((s) => !s.esDeposito).toList()
            : todas;
        if (sucursales.isEmpty) {
          return const Text(
            'Ninguna sucursal tiene stock de todas las prendas de tu carrito.',
            style: TextStyle(color: AppColors.error),
          );
        }
        return Wrap(
          spacing: AppSpacing.sm,
          children: [
            for (final sucursal in sucursales)
              ChoiceChip(
                label: Text(sucursal.nombre),
                selected: checkout.sucursalId == sucursal.id,
                onSelected: (_) => controller.elegirSucursal(sucursal.id),
              ),
          ],
        );
      },
    );
  }
}

class _SelectorDireccion extends ConsumerWidget {
  const _SelectorDireccion();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncDirecciones = ref.watch(misDireccionesProvider);
    final controller = ref.read(checkoutControllerProvider.notifier);

    return asyncDirecciones.when(
      loading: () => const LinearProgressIndicator(),
      error: (e, s) => const Text('No se pudieron cargar tus direcciones.', style: TextStyle(color: AppColors.error)),
      data: (direcciones) {
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (final direccion in direcciones) _TarjetaDireccion(direccion: direccion),
            OutlinedButton.icon(
              onPressed: () async {
                final creada = await context.push<DireccionCliente>('/checkout/direccion/nueva');
                if (creada != null) {
                  ref.invalidate(misDireccionesProvider);
                  controller.elegirDireccion(creada.id);
                }
              },
              icon: const Icon(Icons.add_location_alt_outlined),
              label: const Text('Nueva dirección'),
            ),
          ],
        );
      },
    );
  }
}

class _TarjetaDireccion extends ConsumerWidget {
  const _TarjetaDireccion({required this.direccion});

  final DireccionCliente direccion;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final checkout = ref.watch(checkoutControllerProvider);
    final seleccionada = checkout.direccionId == direccion.id;
    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      color: seleccionada ? AppColors.acento.withValues(alpha: 0.06) : null,
      child: ListTile(
        onTap: () => ref.read(checkoutControllerProvider.notifier).elegirDireccion(direccion.id),
        leading: Icon(
          seleccionada ? Icons.radio_button_checked : Icons.radio_button_off,
          color: seleccionada ? AppColors.acento : AppColors.textoTenue,
        ),
        title: Text(direccion.etiqueta),
        subtitle: direccion.referencia != null ? Text(direccion.referencia!) : null,
      ),
    );
  }
}

class _CostoEnvio extends ConsumerWidget {
  const _CostoEnvio({required this.direccionId});

  final int direccionId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncCotizacion = ref.watch(cotizacionEnvioProvider(direccionId));
    return asyncCotizacion.when(
      loading: () => const LinearProgressIndicator(),
      error: (e, s) => const Text('No se pudo cotizar el envío.', style: TextStyle(color: AppColors.error)),
      data: (cotizacion) => Text(
        'Envío a ${cotizacion.zonaNombre}: Bs ${cotizacion.costo.toStringAsFixed(2)}',
        style: const TextStyle(fontWeight: FontWeight.w600, color: AppColors.acento),
      ),
    );
  }
}
