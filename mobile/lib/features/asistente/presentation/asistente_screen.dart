import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:webview_flutter/webview_flutter.dart';
import '../../../core/theme/app_theme.dart';
import '../models/pagina_asistente.dart';
import '../state/asistente_controller.dart';

/// El asistente de FashionStore: el mismo bot de Botpress que la web, dentro de un WebView. Es público (también lo
/// usa el invitado) y no sabe quién es el cliente.
class AsistenteScreen extends ConsumerStatefulWidget {
  const AsistenteScreen({super.key});

  @override
  ConsumerState<AsistenteScreen> createState() => _AsistenteScreenState();
}

class _AsistenteScreenState extends ConsumerState<AsistenteScreen> {
  late final WebViewController _web;

  @override
  void initState() {
    super.initState();
    _web = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(AppColors.fondo)
      ..setNavigationDelegate(
        NavigationDelegate(
          // Solo se vigila el documento principal: lo que el chat cargue dentro de sus marcos no pasa por acá.
          onNavigationRequest: (request) =>
              !request.isMainFrame || navegacionPermitida(request.url) ? NavigationDecision.navigate : NavigationDecision.prevent,
          onWebResourceError: (error) {
            if (error.isForMainFrame ?? false) ref.read(asistenteControllerProvider.notifier).alFallar();
          },
        ),
      )
      ..addJavaScriptChannel(canalAsistente, onMessageReceived: (mensaje) => _alRecibir(mensaje.message))
      ..loadHtmlString(paginaAsistente);
  }

  void _alRecibir(String mensaje) {
    if (!mounted) return;
    switch (mensaje) {
      case mensajeListo:
        ref.read(asistenteControllerProvider.notifier).alListo();
      case mensajeCerrado:
        if (context.canPop()) context.pop();
    }
  }

  void _reintentar() {
    ref.read(asistenteControllerProvider.notifier).reintentar();
    _web.loadHtmlString(paginaAsistente);
  }

  @override
  Widget build(BuildContext context) {
    final estado = ref.watch(asistenteControllerProvider);
    return Scaffold(
      backgroundColor: AppColors.fondo,
      appBar: AppBar(title: const Text('Asistente')),
      body: CuerpoAsistente(estado: estado, alReintentar: _reintentar, child: WebViewWidget(controller: _web)),
    );
  }
}

/// El chat ([child]) con lo que corresponda encima según el [estado]: "conectando" o el error con su botón. El chat
/// se mantiene siempre en pantalla, aunque tapado, porque tiene que cargar para poder avisar que está listo.
@visibleForTesting
class CuerpoAsistente extends StatelessWidget {
  const CuerpoAsistente({required this.estado, required this.alReintentar, required this.child, super.key});

  final EstadoAsistente estado;
  final VoidCallback alReintentar;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        Positioned.fill(child: child),
        if (estado == EstadoAsistente.cargando)
          const Positioned.fill(
            child: ColoredBox(
              color: AppColors.fondo,
              child: Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    CircularProgressIndicator(color: AppColors.acento),
                    SizedBox(height: AppSpacing.md),
                    Text('Conectando con el asistente…', style: TextStyle(color: AppColors.textoTenue)),
                  ],
                ),
              ),
            ),
          ),
        if (estado == EstadoAsistente.error)
          Positioned.fill(
            child: ColoredBox(
              color: AppColors.fondo,
              child: Center(
                child: Padding(
                  padding: const EdgeInsets.all(AppSpacing.xl),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.cloud_off, size: 48, color: AppColors.textoTenue),
                      const SizedBox(height: AppSpacing.md),
                      const Text(
                        'No se pudo conectar con el asistente. Revisa tu conexión e inténtalo de nuevo.',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: AppColors.textoTenue),
                      ),
                      const SizedBox(height: AppSpacing.md),
                      FilledButton(onPressed: alReintentar, child: const Text('Reintentar')),
                    ],
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }
}
