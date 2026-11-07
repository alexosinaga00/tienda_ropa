import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/push/servicio_push.dart';
import 'package:mobile/features/notificaciones/models/ruta_notificacion.dart';

void main() {
  group('AvisoPush.desdeDatos', () {
    test('lee tipo, referencia y notificación (llegan como texto) y el título y cuerpo', () {
      final aviso = AvisoPush.desdeDatos(
        {'tipo': 'pedido_diferido', 'referencia_id': '55', 'notificacion_id': '9'},
        titulo: 'Cobramos tu pedido',
        cuerpo: 'Compra V-55',
      );

      expect(aviso.tipo, 'pedido_diferido');
      expect(aviso.referenciaId, 55);
      expect(aviso.notificacionId, 9);
      expect(aviso.titulo, 'Cobramos tu pedido');
      expect(aviso.cuerpo, 'Compra V-55');
    });

    test('un número ilegible o vacío queda en null y no lanza', () {
      final aviso = AvisoPush.desdeDatos({'tipo': 'envio', 'referencia_id': 'abc', 'notificacion_id': ''});

      expect(aviso.tipo, 'envio');
      expect(aviso.referenciaId, isNull);
      expect(aviso.notificacionId, isNull);
    });

    test('sin datos todo queda en null', () {
      final aviso = AvisoPush.desdeDatos({});

      expect(aviso.tipo, isNull);
      expect(aviso.referenciaId, isNull);
    });
  });

  group('rutaDeTipoNotificacion', () {
    test('pedido_diferido abre la compra', () {
      expect(rutaDeTipoNotificacion('pedido_diferido', 55), '/compras/55');
    });

    test('envío abre la compra y la reserva preparada abre la reserva', () {
      expect(rutaDeTipoNotificacion('envio', 7), '/compras/7');
      expect(rutaDeTipoNotificacion('reserva_preparada', 3), '/reserva/3');
    });

    test('sin referencia o con un tipo desconocido no hay pantalla', () {
      expect(rutaDeTipoNotificacion('pedido_diferido', null), isNull);
      expect(rutaDeTipoNotificacion('otra_cosa', 1), isNull);
      expect(rutaDeTipoNotificacion(null, 1), isNull);
    });
  });
}
