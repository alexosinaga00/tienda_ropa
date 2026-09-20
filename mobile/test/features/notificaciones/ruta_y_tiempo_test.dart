import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/utils/fecha_servidor.dart';
import 'package:mobile/features/notificaciones/models/ruta_notificacion.dart';

import 'apoyo_notificaciones.dart';

void main() {
  group('rutaDeNotificacion', () {
    test('una reserva preparada abre esa reserva', () {
      expect(rutaDeNotificacion(notificacion(1, tipo: 'reserva_preparada', referenciaId: 5)), '/reserva/5');
    });

    test('el estado de un envío abre esa compra', () {
      expect(rutaDeNotificacion(notificacion(1, tipo: 'envio', referenciaId: 9)), '/compras/9');
    });

    test('un tipo desconocido, o sin referencia, no abre nada', () {
      expect(rutaDeNotificacion(notificacion(1, tipo: 'promocion', referenciaId: 3)), isNull);
      expect(rutaDeNotificacion(notificacion(1, tipo: null, referenciaId: 3)), isNull);
      expect(rutaDeNotificacion(notificacion(1, tipo: 'envio', referenciaId: null)), isNull);
    });
  });

  group('tiempoRelativo', () {
    final ahora = DateTime(2026, 9, 20, 12, 0);

    test('menos de un minuto es "ahora", también con una fecha del futuro', () {
      expect(tiempoRelativo(ahora.subtract(const Duration(seconds: 30)), ahora: ahora), 'ahora');
      expect(tiempoRelativo(ahora.add(const Duration(minutes: 3)), ahora: ahora), 'ahora');
    });

    test('minutos, horas y días', () {
      expect(tiempoRelativo(ahora.subtract(const Duration(minutes: 5)), ahora: ahora), 'hace 5 min');
      expect(tiempoRelativo(ahora.subtract(const Duration(minutes: 59)), ahora: ahora), 'hace 59 min');
      expect(tiempoRelativo(ahora.subtract(const Duration(hours: 3)), ahora: ahora), 'hace 3 h');
      expect(tiempoRelativo(ahora.subtract(const Duration(days: 2)), ahora: ahora), 'hace 2 d');
    });

    test('pasada una semana muestra la fecha', () {
      expect(tiempoRelativo(DateTime(2026, 9, 3, 8), ahora: ahora), '03/09/2026');
    });
  });

  group('fechaDelServidor', () {
    test('una fecha sin zona se toma como UTC (así la manda el backend)', () {
      expect(fechaDelServidor('2026-09-20T16:52:29').toUtc(), DateTime.utc(2026, 9, 20, 16, 52, 29));
    });

    test('si ya trae zona, se respeta', () {
      expect(fechaDelServidor('2026-09-20T16:52:29Z').toUtc(), DateTime.utc(2026, 9, 20, 16, 52, 29));
      expect(fechaDelServidor('2026-09-20T16:52:29-04:00').toUtc(), DateTime.utc(2026, 9, 20, 20, 52, 29));
    });

    test('con microsegundos también', () {
      expect(fechaDelServidor('2026-09-20T16:52:29.123456').toUtc(), DateTime.utc(2026, 9, 20, 16, 52, 29, 123, 456));
    });
  });
}
