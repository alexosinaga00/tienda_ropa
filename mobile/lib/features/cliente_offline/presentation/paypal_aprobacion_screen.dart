import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../../../core/theme/app_theme.dart';
import 'retorno_paypal.dart';

/// Abre la página de PayPal y espera a que el cliente vuelva. Devuelve cómo salió (null si cerró sin terminar). En las
/// pruebas se reemplaza con `abridorAprobacionPaypalProvider.overrideWithValue(...)`: el WebView no existe fuera de un
/// teléfono.
typedef AbridorAprobacionPaypal = Future<RetornoPaypal?> Function(BuildContext context, String url);

final abridorAprobacionPaypalProvider = Provider<AbridorAprobacionPaypal>(
  (ref) =>
      (context, url) => Navigator.of(
        context,
      ).push<RetornoPaypal>(MaterialPageRoute(builder: (_) => PaypalAprobacionScreen(url: url))),
);

/// El WebView de PayPal. Intercepta la URL de retorno (`.../mi-cuenta/paypal-guardado?approval_token_id=...` o
/// `?cancelado=1`) ANTES de cargarla: esa página es de la web, no hace falta verla. El mismo patrón que el pago de la compra.
class PaypalAprobacionScreen extends StatefulWidget {
  const PaypalAprobacionScreen({required this.url, super.key});

  final String url;

  @override
  State<PaypalAprobacionScreen> createState() => _PaypalAprobacionScreenState();
}

class _PaypalAprobacionScreenState extends State<PaypalAprobacionScreen> {
  late final WebViewController _controlador;
  bool _terminado = false;
  bool _cargando = true;
  String? _falla;

  @override
  void initState() {
    super.initState();
    _controlador = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(
        NavigationDelegate(
          onNavigationRequest: (peticion) {
            final retorno = interpretarRetornoPaypal(peticion.url);
            if (retorno == null) return NavigationDecision.navigate;
            _terminar(retorno);
            return NavigationDecision.prevent;
          },
          // Por si PayPal redirige y la navegación no pasa por la petición de arriba.
          onPageStarted: (url) {
            final retorno = interpretarRetornoPaypal(url);
            if (retorno != null) _terminar(retorno);
          },
          onPageFinished: (_) {
            if (mounted) setState(() => _cargando = false);
          },
          onWebResourceError: (error) {
            if (error.isForMainFrame ?? true) {
              if (mounted) {
                setState(() {
                  _cargando = false;
                  _falla = 'No pudimos abrir PayPal. Revisa tu conexión e intenta de nuevo.';
                });
              }
            }
          },
        ),
      );
    if (esUrlAbrible(widget.url)) {
      _controlador.loadRequest(Uri.parse(widget.url));
    } else {
      _falla = 'No pudimos abrir PayPal. Prueba de nuevo en unos minutos.';
      _cargando = false;
    }
  }

  void _terminar(RetornoPaypal retorno) {
    if (_terminado || !mounted) return;
    _terminado = true;
    Navigator.of(context).pop(retorno);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.fondo,
      appBar: AppBar(
        title: const Text('Guardar mi PayPal'),
        leading: IconButton(
          icon: const Icon(Icons.close),
          tooltip: 'Cancelar',
          onPressed: () => _terminar(const RetornoCancelado()),
        ),
      ),
      body: _falla != null
          ? Center(
              child: Padding(
                padding: const EdgeInsets.all(AppSpacing.xl),
                child: Text(_falla!, textAlign: TextAlign.center),
              ),
            )
          : Stack(
              children: [
                WebViewWidget(controller: _controlador),
                if (_cargando) const LinearProgressIndicator(),
              ],
            ),
    );
  }
}
