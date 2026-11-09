import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/auth/state/auth_controller.dart';

/// Qué avisos de la sesión ya se mostraron, para que un mismo hecho no salga dos veces. Una compra confirmada puede
/// enterarse de tres maneras (la pantalla del pago, la cola de pedidos sin conexión y el push): el PRIMERO que llega
/// muestra el aviso y los demás se callan.
///
/// Las claves son `venta:{id}` (una compra pagada, venga de donde venga) y `notif:{id}` (una notificación concreta).
/// Vive en memoria: no hace falta guardarlo, y un aviso viejo no debe tapar uno nuevo tras reiniciar la app.
class AvisosMostrados {
  final Set<String> _claves = {};

  /// Anota la clave. Devuelve `true` si es nueva (hay que mostrar el aviso) y `false` si ya estaba (ya se mostró).
  bool marcar(String clave) => _claves.add(clave);

  bool contiene(String clave) => _claves.contains(clave);

  /// Cuántas claves hay (para las pruebas).
  int get cantidad => _claves.length;

  /// Todo lo que cuenta como "el mismo hecho" para una compra pagada.
  static String claveDeVenta(int ventaId) => 'venta:$ventaId';

  static String claveDeNotificacion(int notificacionId) => 'notif:$notificacionId';
}

/// Un conjunto por sesión: al cerrar la sesión o entrar otra persona se crea uno vacío.
final avisosMostradosProvider = Provider<AvisosMostrados>((ref) {
  ref.watch(authControllerProvider.select((s) => s.estaAutenticado ? s.usuario?.id ?? -1 : null));
  return AvisosMostrados();
});

/// Los tipos de notificación que dicen "tu compra está pagada": para el mismo `referencia_id` son el mismo hecho.
/// `reembolso` NO entra aquí: aunque su `referencia_id` también es la venta, es otro hecho (te devolvieron dinero) y no
/// debe callarse porque la compra ya se avisó, ni callar a la compra.
const tiposDeCompraConfirmada = {'compra_confirmada', 'pedido_diferido'};

/// La ruta que muestra la app ahora (la de arriba de la pila), o null si no se puede saber.
String? rutaActualDe(GoRouter router) {
  try {
    return router.routerDelegate.currentConfiguration.uri.path;
  } catch (_) {
    return null;
  }
}

/// Si la persona ya está mirando esta compra (`/compras/{id}`) o el estado de un pago (`/checkout/estado/...`): en ese
/// caso un SnackBar sobra, la pantalla ya se lo dice.
bool yaViendoLaCompra(String? rutaActual, int? ventaId) {
  if (rutaActual == null) return false;
  if (rutaActual.startsWith('/checkout/estado/')) return true;
  return ventaId != null && rutaActual == '/compras/$ventaId';
}
