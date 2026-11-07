import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/network/mensaje_error.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/boton_cargando.dart';
import '../../../core/widgets/fila_monto.dart';
import '../../../core/utils/fecha_servidor.dart';
import '../models/envio.dart';
import '../models/venta.dart';
import '../state/checkout_controller.dart';
import '../state/compras_providers.dart';
import 'comprobante_tarjeta.dart';
import 'solicitar_cambio_seccion.dart';

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
            ref.invalidate(plazoCambioProvider(ventaId));
            ref.invalidate(misSolicitudesCambioProvider(ventaId));
            ref.invalidate(opcionesCambioProvider(ventaId));
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
                      _TipoDeEntrega(venta: venta),
                      // La devolución no cambia el estado de la compra ("Pagada"): se dice aparte.
                      if (venta.etiquetaDevolucion != null) ...[
                        const SizedBox(height: AppSpacing.xs),
                        Chip(
                          label: Text(venta.etiquetaDevolucion!, style: const TextStyle(fontSize: 12)),
                          backgroundColor: AppColors.fondoAlterno,
                        ),
                      ],
                    ],
                  ),
                ),
              ),
              const SizedBox(height: AppSpacing.md),

              // El comprobante con QR y PDF: solo una compra pagada o entregada (la tarjeta lo decide).
              ComprobanteTarjeta(venta: venta),

              // Con la compra pendiente o anulada el envío no está en marcha.
              if (venta.esEnvioADomicilio && (venta.estado == 'pagada' || venta.estado == 'entregada')) ...[
                _SeguimientoEnvio(ventaId: venta.id),
                const SizedBox(height: AppSpacing.md),
              ],

              // Solo una compra pagada o entregada se puede cambiar: dice hasta cuándo. Si todas las prendas ya se
              // devolvieron no queda nada que cambiar: ni el plazo ni la sección (ni se pide el plazo al servidor).
              if ((venta.estado == 'pagada' || venta.estado == 'entregada') && venta.hayPrendasCambiables) ...[
                _PlazoDeCambio(ventaId: venta.id, sucursalId: venta.sucursalId),
                // Pedir el cambio de talla o color desde la app y ver cómo van las solicitudes.
                SolicitarCambioSeccion(venta: venta),
              ],

              for (final linea in venta.detalle) _TarjetaLinea(linea: linea),
              const SizedBox(height: AppSpacing.md),

              Card(
                child: Padding(
                  padding: const EdgeInsets.all(AppSpacing.md),
                  child: Column(
                    children: [
                      FilaMonto('Subtotal', venta.subtotal),
                      if (venta.descuento > 0) FilaMonto('Descuento', -venta.descuento, color: AppColors.exito),
                      if (venta.costoEnvio > 0) FilaMonto('Envío', venta.costoEnvio),
                      const Divider(),
                      FilaMonto('Total', venta.total, negrita: true),
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
                      'Entregado el ${formatearFechaHora(envio.fechaEntrega!)}',
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

/// "Retiro en sucursal · Centro" / "Envío a domicilio · despacha Centro". Si no se pudo saber la sucursal, queda
/// el texto de siempre.
class _TipoDeEntrega extends ConsumerWidget {
  const _TipoDeEntrega({required this.venta});

  final Venta venta;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final id = venta.sucursalId;
    final sucursal = id == null ? null : ref.watch(nombreSucursalProvider(id)).valueOrNull;
    final base = venta.esEnvioADomicilio ? 'Envío a domicilio' : 'Retiro en sucursal';
    final texto = sucursal == null ? base : '$base · ${venta.esEnvioADomicilio ? 'despacha ' : ''}$sucursal';
    return Text(texto, style: const TextStyle(color: AppColors.textoTenue, fontSize: 13));
  }
}

/// Hasta cuándo se puede cambiar la prenda (lo calcula el servidor). Si no se pudo saber, no se muestra nada.
/// El cambio se hace en la tienda: el cliente lleva la prenda y el cajero cambia la talla o el color.
class _PlazoDeCambio extends ConsumerWidget {
  const _PlazoDeCambio({required this.ventaId, this.sucursalId});

  final int ventaId;
  final int? sucursalId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final plazo = ref.watch(plazoCambioProvider(ventaId)).valueOrNull;
    if (plazo == null) return const SizedBox.shrink();
    final sucursal = sucursalId == null ? null : ref.watch(nombreSucursalProvider(sucursalId!)).valueOrNull;

    final vigente = plazo.vigente;
    final color = vigente ? AppColors.exito : AppColors.error;
    final hasta = formatearFechaHora(plazo.venceEn);

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(vigente ? Icons.schedule : Icons.error_outline, color: color, size: 28),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      vigente
                          ? 'Puedes cambiar tu prenda hasta el $hasta'
                          : 'El plazo para cambiar esta compra venció el $hasta',
                      style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
                    ),
                    if (vigente) ...[
                      const SizedBox(height: AppSpacing.xs),
                      Text(
                        'Lleva la prenda a ${sucursal != null ? 'la sucursal $sucursal' : 'la tienda'} y cambia la '
                        'talla o el color en caja. Te enviaremos el comprobante a tu correo.',
                        style: const TextStyle(color: AppColors.textoTenue, fontSize: 13),
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
          child: _ocupado ? const BotonCargando() : const Text('Pagar ahora'),
        ),
        const SizedBox(height: AppSpacing.sm),
        OutlinedButton(onPressed: _ocupado ? null : _cancelar, child: const Text('Cancelar compra')),
      ],
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
