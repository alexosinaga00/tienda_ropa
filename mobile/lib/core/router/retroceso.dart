import 'package:flutter/widgets.dart';
import 'package:go_router/go_router.dart';

/// A qué pantalla sube el botón "atrás" cuando la pila ya no tiene historial (la pantalla se abrió con `context.go`,
/// que reemplaza toda la pila, o desde un enlace). `null` significa que no hay padre: ahí "atrás" cierra la app
/// (solo debería pasar en el catálogo, en "Elige tu tienda" y en el splash).
String? rutaPadreDe(String ruta) {
  switch (ruta) {
    case '/home':
    case '/tienda':
    case '/splash':
    // Sin padre a propósito: si la sesión del personal venció, el router lo reenvía a su acceso, y un padre lo dejaría
    // atrapado ahí. "Atrás" debe poder cerrar la app.
    case '/vendedor':
    case '/vendedor/acceso':
      return null;
    case '/registro':
    case '/recuperar':
    case '/restablecer':
      return '/login';
    case '/checkout/direccion/nueva':
    case '/checkout/pago':
      return '/checkout/entrega';
    case '/checkout/entrega':
      return '/carrito';
  }
  if (ruta.startsWith('/checkout/estado/')) return '/compras';
  if (ruta.startsWith('/compras/')) return '/compras';  if (ruta.startsWith('/reserva/') && ruta != '/reserva/confirmar') return '/reservas';
  // Todo lo demás (detalle, favoritos, carrito, login, reservas...) cuelga del catálogo.
  return '/home';
}

/// Botón "atrás" del sistema: primero lo que hace el router (cerrar un diálogo o volver a la pantalla anterior); si no
/// hay a dónde volver, sube a la pantalla padre en vez de cerrar la app.
class RetrocesoDelRouter extends RootBackButtonDispatcher {
  RetrocesoDelRouter(this._router);

  final GoRouter _router;

  @override
  Future<bool> invokeCallback(Future<bool> defaultValue) async {
    final manejado = await super.invokeCallback(defaultValue);
    if (manejado) return true;
    final padre = rutaPadreDe(_router.routerDelegate.currentConfiguration.uri.path);
    if (padre == null) return false;
    _router.go(padre);
    return true;
  }
}
