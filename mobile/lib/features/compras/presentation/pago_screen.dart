import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/network/mensaje_error.dart';
import '../../../core/theme/app_theme.dart';
import '../state/carrito_controller.dart';
import '../state/checkout_controller.dart';
import '../state/compras_providers.dart';

const _metodos = {'libelula': 'Libélula', 'paypal': 'PayPal', 'qr_online': 'QR'};

class PagoScreen extends ConsumerStatefulWidget {
  const PagoScreen({super.key});

  @override
  ConsumerState<PagoScreen> createState() => _PagoScreenState();
}

class _PagoScreenState extends ConsumerState<PagoScreen> {
  String _metodo = 'libelula';
  bool _procesando = false;

  Future<void> _pagar() async {
    final checkout = ref.read(checkoutControllerProvider);
    final controller = ref.read(checkoutControllerProvider.notifier);
    if (!checkout.listoParaPagar) return;

    setState(() => _procesando = true);
    try {
      // Si un intento anterior ya creó la venta (y falló después, al crear
      // el envío o iniciar el pago), se reusa: el carrito ya se vació, así
      // que registrar otra fallaría con "carrito vacío" y dejaría la primera
      // colgada reteniendo stock. Mismo criterio que la tienda web.
      final venta = checkout.venta?.estado == 'pendiente_pago'
          ? checkout.venta!
          : await ref
                .read(ventasRepositoryProvider)
                .registrarVentaDigital(sucursalId: checkout.sucursalId!, costoEnvio: checkout.costoEnvio);
      controller.confirmarVenta(venta);
      // El backend ya vació el carrito al registrar la venta -- si no se
      // refresca acá, el carrito local queda desincronizado (sigue
      // mostrando la prenda ya comprada) hasta el próximo pull-to-refresh.
      unawaited(ref.read(carritoControllerProvider.notifier).cargar());

      if (checkout.tipoEntrega == TipoEntrega.domicilio) {
        try {
          await ref
              .read(enviosRepositoryProvider)
              .crear(ventaId: venta.id, direccionId: checkout.direccionId!);
        } catch (e) {
          if (!esConflicto(e)) rethrow; // 409: el envío ya se creó en el intento anterior
        }
      }

      final pagoIniciado = await ref
          .read(pagosRepositoryProvider)
          .iniciar(ventaId: venta.id, metodoPago: _metodo);
      controller.confirmarPago(pagoIniciado);

      if (!mounted) return;
      context.push('/checkout/estado/${pagoIniciado.pago.id}');
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(mensajeDeError(e, 'No se pudo iniciar el pago. Probá de nuevo.'))),
      );
    } finally {
      if (mounted) setState(() => _procesando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final checkout = ref.watch(checkoutControllerProvider);

    return Scaffold(
      backgroundColor: AppColors.fondo,
      appBar: AppBar(title: const Text('Pago')),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.md),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(AppSpacing.md),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    checkout.tipoEntrega == TipoEntrega.retiro ? 'Retiro en sucursal' : 'Envío a domicilio',
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  if (checkout.costoEnvio > 0)
                    Text(
                      'Costo de envío: Bs ${checkout.costoEnvio.toStringAsFixed(2)}',
                      style: const TextStyle(color: AppColors.textoTenue, fontSize: 13),
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.lg),

          const Text('Método de pago', style: TextStyle(color: AppColors.textoTenue, fontSize: 12)),
          const SizedBox(height: AppSpacing.xs),
          Wrap(
            spacing: AppSpacing.sm,
            children: [
              for (final entrada in _metodos.entries)
                ChoiceChip(
                  label: Text(entrada.value),
                  selected: _metodo == entrada.key,
                  onSelected: (_) => setState(() => _metodo = entrada.key),
                ),
            ],
          ),

          const SizedBox(height: AppSpacing.xl),
          ElevatedButton(
            onPressed: _procesando ? null : _pagar,
            child: _procesando
                ? const SizedBox(
                    height: 20,
                    width: 20,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                  )
                : Text('Pagar con ${_metodos[_metodo]}'),
          ),
        ],
      ),
    );
  }
}
