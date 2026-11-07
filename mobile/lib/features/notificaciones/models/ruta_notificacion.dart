import 'notificacion_app.dart';

/// La pantalla a la que lleva una notificación al tocarla, o null si ese tipo no abre nada (queda solo en la lista).
String? rutaDeNotificacion(NotificacionApp notificacion) =>
    rutaDeTipoNotificacion(notificacion.tipo, notificacion.referenciaId);

/// Lo mismo a partir del `tipo` y la `referencia_id` sueltos (los de un aviso push, que llegan en el `data` del mensaje).
String? rutaDeTipoNotificacion(String? tipo, int? referenciaId) {
  final id = referenciaId;
  if (id == null) return null;
  return switch (tipo) {
    'reserva_preparada' => '/reserva/$id',
    'envio' => '/compras/$id', // referencia_id es el id de la compra
    'pedido_diferido' => '/compras/$id', // un pedido sin conexión cobrado: referencia_id es la venta
    _ => null,
  };
}

/// "ahora", "hace 5 min", "hace 3 h", "hace 2 d" o la fecha si pasó más de una semana. Una fecha futura (reloj
/// desfasado) se muestra como "ahora".
String tiempoRelativo(DateTime fecha, {DateTime? ahora}) {
  final diferencia = (ahora ?? DateTime.now()).difference(fecha);
  if (diferencia.inMinutes < 1) return 'ahora';
  if (diferencia.inHours < 1) return 'hace ${diferencia.inMinutes} min';
  if (diferencia.inDays < 1) return 'hace ${diferencia.inHours} h';
  if (diferencia.inDays < 7) return 'hace ${diferencia.inDays} d';
  final dia = fecha.day.toString().padLeft(2, '0');
  final mes = fecha.month.toString().padLeft(2, '0');
  return '$dia/$mes/${fecha.year}';
}
