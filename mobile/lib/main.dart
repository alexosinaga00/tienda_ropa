import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'core/router/app_router.dart';
import 'core/sync/disparador_sincronizacion.dart';
import 'core/theme/tema_empresa.dart';
import 'features/cliente_offline/presentation/disparador_cola_pedidos.dart';

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
      // Español: calendario, reloj, botones y menús nativos de Flutter.
      locale: const Locale('es'),
      supportedLocales: const [Locale('es')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      // Para avisar el resultado de una sincronización automática desde cualquier pantalla.
      scaffoldMessengerKey: mensajeroGlobal,
      // Dispara la sincronización sola (solo actúa con una sesión del personal) y la cola de pedidos sin conexión (solo
      // actúa con una sesión de cliente).
      builder: (context, child) =>
          DisparadorSincronizacion(child: DisparadorColaPedidos(child: child ?? const SizedBox.shrink())),
      routeInformationProvider: router.routeInformationProvider,
      routeInformationParser: router.routeInformationParser,
      routerDelegate: router.routerDelegate,
      backButtonDispatcher: ref.watch(retrocesoProvider),
    );
  }
}
