import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'core/router/app_router.dart';
import 'core/sync/disparador_sincronizacion.dart';
import 'core/theme/tema_empresa.dart';

void main() {
  runApp(const ProviderScope(child: FashionStoreApp()));
}

class FashionStoreApp extends ConsumerWidget {
  const FashionStoreApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);

    // Equivale a `routerConfig: router`, pero con nuestro botón "atrás": si no hay historial sube a la pantalla padre
    // en vez de cerrar la app.
    return MaterialApp.router(
      title: 'FashionStore',
      debugShowCheckedModeBanner: false,
      theme: ref.watch(temaEmpresaProvider),
      // Para avisar el resultado de una sincronización automática desde cualquier pantalla.
      scaffoldMessengerKey: mensajeroGlobal,
      // Dispara la sincronización sola (solo actúa con una sesión del personal).
      builder: (context, child) => DisparadorSincronizacion(child: child ?? const SizedBox.shrink()),
      routeInformationProvider: router.routeInformationProvider,
      routeInformationParser: router.routeInformationParser,
      routerDelegate: router.routerDelegate,
      backButtonDispatcher: ref.watch(retrocesoProvider),
    );
  }
}
