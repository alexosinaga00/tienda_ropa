import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:webview_flutter/webview_flutter.dart';
import '../../../core/network/mensaje_error.dart';
import '../../../core/theme/app_theme.dart';
import '../state/checkout_controller.dart';
import '../state/compras_providers.dart';
import '../state/estado_pago_controller.dart';

// Mismas URLs hardcodeadas que backend/app/pagos/pasarela.py -- no hace
// falta que resuelvan de verdad: el WebView intercepta la navegación
// ANTES de intentar cargarlas.
const _prefijoRetorno = 'https://fashionstore.example.com/pago/retorno';
const _prefijoCancelado = 'https://fashionstore.example.com/pago/cancelado';

class EstadoPagoScreen extends ConsumerStatefulWidget {
  const EstadoPagoScreen({required this.pagoId, super.key});

  final int pagoId;

  @override
  ConsumerState<EstadoPagoScreen> createState() => _EstadoPagoScreenState();
}

class _EstadoPagoScreenState extends ConsumerState<EstadoPagoScreen> {
  late final WebViewController _webViewController;
  bool _webviewCerrado = false;
  bool _reintentando = false;
  bool _cancelando = false;

  @override
  void initState() {
    super.initState();
    final urlRedireccion = ref.read(checkoutControllerProvider).pagoIniciado?.urlRedireccion;

    _webViewController = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(
        NavigationDelegate(
          onNavigationRequest: (request) {
            if (request.url.startsWith(_prefijoRetorno) || request.url.startsWith(_prefijoCancelado)) {
              _cerrarWebView();
              return NavigationDecision.prevent;
            }
            return NavigationDecision.navigate;
          },
          // Libélula es un simulador de sandbox: su "checkout" no existe de
          // verdad, así que esta URL nunca carga. No es un error fatal --
          // se cierra el WebView y el polling de GET /pagos/{id}/estado
          // (que ya está corriendo desde que se abrió la pantalla) sigue
          // siendo la fuente de verdad.
          onWebResourceError: (_) => _cerrarWebView(),
        ),
      );
    if (urlRedireccion != null) {
      _webViewController.loadRequest(Uri.parse(urlRedireccion));
    } else {
      _webviewCerrado = true;
    }
  }

  void _cerrarWebView() {
    if (!mounted || _webviewCerrado) return;
    setState(() => _webviewCerrado = true);
    ref.read(estadoPagoControllerProvider(widget.pagoId).notifier).consultarAhora();
  }

  Future<void> _reintentar() async {
    final checkout = ref.read(checkoutControllerProvider);
    final ventaId = _ventaId;
    final metodoPago = checkout.pagoIniciado?.pago.metodoPago;
    if (ventaId == null || metodoPago == null) return;

    setState(() => _reintentando = true);
    try {
      final pagoIniciado = await ref
          .read(pagosRepositoryProvider)
          .iniciar(ventaId: ventaId, metodoPago: metodoPago);
      ref.read(checkoutControllerProvider.notifier).confirmarPago(pagoIniciado);
      if (!mounted) return;
      context.pushReplacement('/checkout/estado/${pagoIniciado.pago.id}');
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(mensajeDeError(e, 'No se pudo reintentar el pago. Probá de nuevo.'))),
      );
      if (esConflicto(e)) refrescarDespuesDeCompra(ref); // p. ej. ya estaba pagada
    } finally {
      if (mounted) setState(() => _reintentando = false);
    }
  }

  int? get _ventaId =>
      ref.read(estadoPagoControllerProvider(widget.pagoId)).pago.valueOrNull?.ventaId ??
      ref.read(checkoutControllerProvider).pagoIniciado?.pago.ventaId;

  /// Cancela la compra sin pagar: el backend libera el stock y devuelve las
  /// prendas al carrito.
  Future<void> _cancelarCompra() async {
    final ventaId = _ventaId;
    if (ventaId == null) return;
    setState(() => _cancelando = true);
    try {
      await ref.read(pagosRepositoryProvider).cancelarCompra(ventaId);
      ref.read(checkoutControllerProvider.notifier).reiniciar();
      refrescarDespuesDeCompra(ref);
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('Compra cancelada. Tus prendas volvieron al carrito.')));
      context.go('/carrito');
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(mensajeDeError(e, 'No se pudo cancelar la compra. Probá de nuevo.'))));
      // 409 "ya fue pagada": el polling lo va a mostrar como aprobado.
      ref.read(estadoPagoControllerProvider(widget.pagoId).notifier).consultarAhora();
    } finally {
      if (mounted) setState(() => _cancelando = false);
    }
  }

  void _volverAlCarrito() {
    ref.read(checkoutControllerProvider.notifier).reiniciar();
    refrescarDespuesDeCompra(ref);
    context.go('/carrito');
  }

  /// Salir con el pago todavía sin confirmar: antes la app volvía atrás en
  /// silencio y la compra quedaba pendiente reteniendo el stock.
  Future<void> _preguntarAlSalir() async {
    final opcion = await showModalBottomSheet<_OpcionSalida>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.lg),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text('¿Salir sin terminar el pago?', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
              const SizedBox(height: AppSpacing.xs),
              const Text(
                'Tu compra todavía no está pagada. Si la dejás pendiente, se cancela sola en 30 minutos.',
                style: TextStyle(color: AppColors.textoTenue),
              ),
              const SizedBox(height: AppSpacing.lg),
              ElevatedButton(
                onPressed: () => Navigator.pop(context, _OpcionSalida.seguir),
                child: const Text('Seguir con el pago'),
              ),
              const SizedBox(height: AppSpacing.sm),
              OutlinedButton(
                onPressed: () => Navigator.pop(context, _OpcionSalida.cancelar),
                child: const Text('Cancelar compra (vuelve al carrito)'),
              ),
              TextButton(
                onPressed: () => Navigator.pop(context, _OpcionSalida.despues),
                child: const Text('Pagar después desde Mis compras'),
              ),
            ],
          ),
        ),
      ),
    );
    if (!mounted) return;
    switch (opcion) {
      case _OpcionSalida.cancelar:
        await _cancelarCompra();
      case _OpcionSalida.despues:
        refrescarDespuesDeCompra(ref);
        context.go('/compras');
      case _OpcionSalida.seguir:
      case null:
        break;
    }
  }

  @override
  Widget build(BuildContext context) {
    // Se mira siempre, no solo cuando se cierra el WebView: el polling
    // tiene que arrancar desde que se abre la pantalla, en paralelo a la
    // pasarela, no depender de que el WebView llegue a cerrarse.
    final estado = ref.watch(estadoPagoControllerProvider(widget.pagoId));
    final resuelto = estado.pago.valueOrNull?.aprobado == true || estado.pago.valueOrNull?.rechazado == true;

    ref.listen(estadoPagoControllerProvider(widget.pagoId), (previo, siguiente) {
      final pago = siguiente.pago.valueOrNull;
      if (pago != null && (pago.aprobado || pago.rechazado) && previo?.pago.valueOrNull?.estado != pago.estado) {
        refrescarDespuesDeCompra(ref); // aprobado descuenta stock; rechazado lo libera y devuelve el carrito
        // El pago ya se resolvió (p. ej. "Confirmar pago" de la pantalla QR):
        // el WebView no hace falta más, sin depender de una URL de retorno.
        if (!_webviewCerrado) setState(() => _webviewCerrado = true);
      }
    });

    return PopScope(
      canPop: resuelto,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop && !_cancelando) _preguntarAlSalir();
      },
      child: Scaffold(
        backgroundColor: AppColors.fondo,
        appBar: AppBar(
          title: const Text('Pago'),
          actions: [
            if (!_webviewCerrado)
              TextButton(onPressed: _cerrarWebView, child: const Text('Ya completé el pago')),
          ],
        ),
        body: _webviewCerrado
            ? _PanelEstado(
                estado: estado,
                reintentando: _reintentando,
                cancelando: _cancelando,
                onReintentar: _reintentar,
                onCancelar: _cancelarCompra,
                onVolverAlCarrito: _volverAlCarrito,
              )
            : WebViewWidget(controller: _webViewController),
      ),
    );
  }
}

enum _OpcionSalida { seguir, cancelar, despues }

class _PanelEstado extends StatelessWidget {
  const _PanelEstado({
    required this.estado,
    required this.reintentando,
    required this.cancelando,
    required this.onReintentar,
    required this.onCancelar,
    required this.onVolverAlCarrito,
  });

  final EstadoPagoEstado estado;
  final bool reintentando;
  final bool cancelando;
  final VoidCallback onReintentar;
  final VoidCallback onCancelar;
  final VoidCallback onVolverAlCarrito;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: estado.pago.when(
          loading: () => const Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              CircularProgressIndicator(color: AppColors.acento),
              SizedBox(height: AppSpacing.md),
              Text('Consultando el estado del pago...'),
            ],
          ),
          error: (e, s) => _MensajeEstado(
            icono: Icons.error_outline,
            color: AppColors.error,
            titulo: 'No se pudo consultar el pago',
            subtitulo: 'Revisá tu conexión y volvé a intentar.',
            reintentando: reintentando,
            onReintentar: onReintentar,
          ),
          data: (pago) {
            if (pago.aprobado) {
              return Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.check_circle, color: AppColors.exito, size: 56),
                  const SizedBox(height: AppSpacing.md),
                  const Text('¡Pago aprobado!', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
                  const SizedBox(height: AppSpacing.lg),
                  ElevatedButton(
                    onPressed: () => context.go('/compras/${pago.ventaId}'),
                    child: const Text('Ver mi compra'),
                  ),
                ],
              );
            }
            if (pago.rechazado) {
              // El backend ya anuló la venta y devolvió las prendas al
              // carrito: "Reintentar" sobre esta venta daría 409.
              return Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.cancel_outlined, color: AppColors.error, size: 56),
                  const SizedBox(height: AppSpacing.md),
                  const Text(
                    'El pago fue rechazado',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  const Text(
                    'No se cobró nada. Tus prendas volvieron al carrito para que intentes de nuevo.',
                    style: TextStyle(color: AppColors.textoTenue),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: AppSpacing.lg),
                  ElevatedButton(onPressed: onVolverAlCarrito, child: const Text('Volver al carrito')),
                ],
              );
            }
            if (estado.agotado) {
              return Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.hourglass_top, color: AppColors.textoTenue, size: 48),
                  const SizedBox(height: AppSpacing.md),
                  const Text(
                    'Pago pendiente de confirmación',
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  const Text(
                    'Todavía no tenemos la confirmación de la pasarela. Podés reintentar el pago, cancelar la compra o '
                    'pagarla más tarde desde "Mis compras" (si no se paga, se cancela sola en 30 minutos).',
                    style: TextStyle(color: AppColors.textoTenue, fontSize: 13),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: AppSpacing.lg),
                  ElevatedButton(
                    onPressed: reintentando ? null : onReintentar,
                    child: reintentando
                        ? const SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                          )
                        : const Text('Reintentar'),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  OutlinedButton(
                    onPressed: cancelando || reintentando ? null : onCancelar,
                    child: cancelando
                        ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Text('Cancelar compra'),
                  ),
                  TextButton(onPressed: () => context.go('/compras'), child: const Text('Ver mis compras')),
                ],
              );
            }
            return const Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                CircularProgressIndicator(color: AppColors.acento),
                SizedBox(height: AppSpacing.md),
                Text('Esperando la confirmación de la pasarela...'),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _MensajeEstado extends StatelessWidget {
  const _MensajeEstado({
    required this.icono,
    required this.color,
    required this.titulo,
    required this.subtitulo,
    required this.reintentando,
    required this.onReintentar,
  });

  final IconData icono;
  final Color color;
  final String titulo;
  final String subtitulo;
  final bool reintentando;
  final VoidCallback onReintentar;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icono, color: color, size: 56),
        const SizedBox(height: AppSpacing.md),
        Text(titulo, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700), textAlign: TextAlign.center),
        const SizedBox(height: AppSpacing.xs),
        Text(subtitulo, style: const TextStyle(color: AppColors.textoTenue), textAlign: TextAlign.center),
        const SizedBox(height: AppSpacing.lg),
        ElevatedButton(
          onPressed: reintentando ? null : onReintentar,
          child: reintentando
              ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Text('Reintentar'),
        ),
      ],
    );
  }
}
