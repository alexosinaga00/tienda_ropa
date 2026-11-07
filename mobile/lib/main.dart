import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'core/push/almacen_push.dart';
import 'core/push/registro_push.dart' show almacenPushProvider;
import 'core/push/servicio_push.dart';
import 'core/push/servicio_push_firebase.dart';
import 'core/router/app_router.dart';
import 'core/sync/disparador_sincronizacion.dart';
import 'core/theme/tema_empresa.dart';
import 'features/cliente_offline/presentation/disparador_cola_pedidos.dart';
import 'features/notificaciones/presentation/disparador_push.dart';

void main() {
  runApp(
    // El servicio push real (Firebase) solo se conecta aquí: por defecto la app y las pruebas usan uno que no hace nada.
    ProviderScope(
      overrides: [
        servicioPushProvider.overrideWithValue(ServicioPushFirebase()),
        almacenPushProvider.overrideWithValue(const AlmacenPush()),
      ],
      child: const FashionStoreApp(),
    ),
  );
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
      // Dispara la sincronización sola (solo actúa con una sesión del personal), la cola de pedidos sin conexión (solo
      // actúa con una sesión de cliente) y los avisos push (con cualquier sesión).
      builder: (context, child) => DisparadorSincronizacion(
        child: DisparadorColaPedidos(child: DisparadorPush(child: child ?? const SizedBox.shrink())),
      ),
      routeInformationProvider: router.routeInformationProvider,
      routeInformationParser: router.routeInformationParser,
      routerDelegate: router.routerDelegate,
      backButtonDispatcher: ref.watch(retrocesoProvider),
    );
  }
}
