import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/network/mensaje_error.dart';
import '../../../core/theme/app_theme.dart';
import '../models/envio.dart';
import '../models/venta.dart';
import '../state/checkout_controller.dart';
import '../state/compras_providers.dart';

class CompraDetalleScreen extends ConsumerWidget {
  const CompraDetalleScreen({required this.ventaId, super.key});

  final int ventaId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncVenta = ref.watch(compraDetalleProvider(ventaId));

    return Scaffold(
      backgroundColor: AppColors.fondo,
      appBar: AppBar(title: const Text('Comprobante')),
      body: asyncVenta.when(
        loading: () => const Center(child: CircularProgressIndicator(color: AppColors.acento)),
        error: (e, s) => const Center(child: Text('No se pudo cargar el comprobante.')),
        data: (venta) => RefreshIndicator(
          // El estado de la compra y del envío los cambia el personal: se vuelven a pedir al deslizar hacia abajo.
          onRefresh: () async {
            ref.invalidate(envioDeCompraProvider(ventaId));
            ref.invalidate(compraDetalleProvider(ventaId));
            await ref.read(compraDetalleProvider(ventaId).future);
          },
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(AppSpacing.md),
            children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(AppSpacing.md),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(venta.codigo, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                          Chip(label: Text(etiquetasEstadoVenta[venta.estado] ?? venta.estado)),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.xs),
                      Text(
                        venta.esEnvioADomicilio ? 'Envío a domicilio' : 'Retiro en sucursal',
                        style: const TextStyle(color: AppColors.textoTenue, fontSize: 13),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: AppSpacing.md),

              // Con la compra pendiente o anulada el envío no está en marcha.
              if (venta.esEnvioADomicilio && (venta.estado == 'pagada' || venta.estado == 'entregada')) ...[
                _SeguimientoEnvio(ventaId: venta.id),
                const SizedBox(height: AppSpacing.md),
              ],

              for (final linea in venta.detalle) _TarjetaLinea(linea: linea),
              const SizedBox(height: AppSpacing.md),

              Card(
                child: Padding(
                  padding: const EdgeInsets.all(AppSpacing.md),
                  child: Column(
                    children: [
                      _FilaResumen('Subtotal', venta.subtotal),
                      if (venta.descuento > 0) _FilaResumen('Descuento', -venta.descuento, color: AppColors.exito),
                      if (venta.costoEnvio > 0) _FilaResumen('Envío', venta.costoEnvio),
                      const Divider(),
                      _FilaResumen('Total', venta.total, negrita: true),
                    ],
                  ),
                ),
              ),
              if (venta.estado == 'pendiente_pago') ...[
                const SizedBox(height: AppSpacing.lg),
                _AccionesPendiente(venta: venta),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// Seguimiento del envío a domicilio: en qué punto va (programado, en camino, entregado o no se pudo
/// entregar), quién lo lleva y cuándo llegó. Si falla o la compra no tiene envío, no se muestra nada.
class _SeguimientoEnvio extends ConsumerWidget {
  const _SeguimientoEnvio({required this.ventaId});

  final int ventaId;

  static const _iconos = {
    'programado': Icons.event_available_outlined,
    'en_ruta': Icons.local_shipping_outlined,
    'entregado': Icons.check_circle_outline,
    'fallido': Icons.error_outline,
  };

  static String _dos(int n) => n.toString().padLeft(2, '0');

  static String _formatear(DateTime f) => '${_dos(f.day)}/${_dos(f.month)}/${f.year} ${_dos(f.hour)}:${_dos(f.minute)}';

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final envio = ref.watch(envioDeCompraProvider(ventaId)).valueOrNull;
    if (envio == null) return const SizedBox.shrink();

    final entregado = envio.estado == 'entregado';
    final fallido = envio.estado == 'fallido';
    final color = entregado ? AppColors.exito : (fallido ? AppColors.error : AppColors.acento);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(_iconos[envio.estado] ?? Icons.local_shipping_outlined, color: color, size: 28),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    etiquetasEstadoEnvio[envio.estado] ?? envio.estado,
                    style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16, color: color),
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  if (entregado && envio.fechaEntrega != null)
                    Text(
                      'Entregado el ${_formatear(envio.fechaEntrega!)}',
                      style: const TextStyle(color: AppColors.textoTenue, fontSize: 13),
                    ),
                  if (fallido)
                    const Text(
                      'No se pudo entregar tu pedido. Comunicate con la sucursal.',
                      style: TextStyle(color: AppColors.textoTenue, fontSize: 13),
                    ),
                  if (envio.repartidor != null && envio.repartidor!.isNotEmpty)
                    Text(
                      'Repartidor: ${envio.repartidor}',
                      style: const TextStyle(color: AppColors.textoTenue, fontSize: 13),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Una compra que quedó sin pagar (se salió de la pasarela, falló el pago):
/// se puede pagar desde acá o cancelar para liberar el stock.
class _AccionesPendiente extends ConsumerStatefulWidget {
  const _AccionesPendiente({required this.venta});

  final Venta venta;

  @override
  ConsumerState<_AccionesPendiente> createState() => _AccionesPendienteState();
}

class _AccionesPendienteState extends ConsumerState<_AccionesPendiente> {
  bool _ocupado = false;

  Future<void> _pagar() async {
    final metodo = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Padding(
              padding: EdgeInsets.only(bottom: AppSpacing.sm),
              child: Text('¿Con qué querés pagar?', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
            ),
            ListTile(
              leading: const Icon(Icons.qr_code_2),
              title: const Text('QR'),
              onTap: () => Navigator.pop(context, 'qr_online'),
            ),
            ListTile(
              leading: const Icon(Icons.account_balance_wallet_outlined),
              title: const Text('PayPal'),
              onTap: () => Navigator.pop(context, 'paypal'),
            ),
            ListTile(
              leading: const Icon(Icons.account_balance_outlined),
              title: const Text('Libélula'),
              onTap: () => Navigator.pop(context, 'libelula'),
            ),
          ],
        ),
      ),
    );
    if (metodo == null || !mounted) return;

    setState(() => _ocupado = true);
    try {
      final pagoIniciado = await ref.read(pagosRepositoryProvider).iniciar(ventaId: widget.venta.id, metodoPago: metodo);
      // La pantalla de estado lee la URL de la pasarela del checkout.
      ref.read(checkoutControllerProvider.notifier)
        ..reiniciar()
        ..confirmarVenta(widget.venta)
        ..confirmarPago(pagoIniciado);
      if (!mounted) return;
      context.push('/checkout/estado/${pagoIniciado.pago.id}');
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(mensajeDeError(e, 'No se pudo iniciar el pago. Probá de nuevo.'))));
      refrescarDespuesDeCompra(ref);
    } finally {
      if (mounted) setState(() => _ocupado = false);
    }
  }

  Future<void> _cancelar() async {
    final confirmado = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('¿Cancelar la compra?'),
        content: const Text('Se libera la prenda y vuelve a tu carrito.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('No')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Sí, cancelar')),
        ],
      ),
    );
    if (confirmado != true || !mounted) return;

    setState(() => _ocupado = true);
    try {
      await ref.read(pagosRepositoryProvider).cancelarCompra(widget.venta.id);
      refrescarDespuesDeCompra(ref);
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('Compra cancelada. Tus prendas volvieron al carrito.')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(mensajeDeError(e, 'No se pudo cancelar la compra. Probá de nuevo.'))));
      refrescarDespuesDeCompra(ref);
    } finally {
      if (mounted) setState(() => _ocupado = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text(
          'Esta compra todavía no está pagada. Si no se paga, se cancela sola a los 30 minutos.',
          style: TextStyle(color: AppColors.textoTenue, fontSize: 13),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: AppSpacing.sm),
        ElevatedButton(
          onPressed: _ocupado ? null : _pagar,
          child: _ocupado
              ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Text('Pagar ahora'),
        ),
        const SizedBox(height: AppSpacing.sm),
        OutlinedButton(onPressed: _ocupado ? null : _cancelar, child: const Text('Cancelar compra')),
      ],
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

class _TarjetaLinea extends StatelessWidget {
  const _TarjetaLinea({required this.linea});

  final VentaLinea linea;

  @override
  Widget build(BuildContext context) {
    final subtitulo = [
      if (linea.tallaCodigo != null) linea.tallaCodigo!,
      if (linea.colorNombre != null) linea.colorNombre!,
      'x${linea.cantidad}',
    ].join(' · ');

    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: ListTile(
        leading: ClipRRect(
          borderRadius: BorderRadius.circular(AppRadius.base),
          child: linea.imagenPrincipal != null
              ? CachedNetworkImage(imageUrl: linea.imagenPrincipal!, width: 48, height: 48, fit: BoxFit.cover)
              : Container(
                  width: 48,
                  height: 48,
                  color: AppColors.fondoAlterno,
                  child: const Icon(Icons.checkroom, color: AppColors.textoTenue),
                ),
        ),
        title: Text(linea.productoNombre ?? 'Prenda', maxLines: 1, overflow: TextOverflow.ellipsis),
        subtitle: Text(subtitulo),
        trailing: Text('Bs ${linea.subtotal.toStringAsFixed(2)}', style: const TextStyle(fontWeight: FontWeight.w600)),
      ),
    );
  }
}
