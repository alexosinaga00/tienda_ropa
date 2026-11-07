import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/utils/fecha_servidor.dart';
import 'package:mobile/features/compras/models/pago.dart';
import 'package:mobile/features/favoritos/models/favorito.dart';
import 'package:mobile/features/reservas/models/reserva.dart';

void main() {
  group('fechaDelServidor', () {
    test('una fecha sin zona se toma como UTC, no como hora local', () {
      expect(fechaDelServidor('2026-09-20T16:52:29').toUtc(), DateTime.utc(2026, 9, 20, 16, 52, 29));
    });

    test('una fecha con Z o con desfase conserva su instante', () {
      expect(fechaDelServidor('2026-09-20T16:52:29Z').toUtc(), DateTime.utc(2026, 9, 20, 16, 52, 29));
      expect(fechaDelServidor('2026-09-20T12:52:29-04:00').toUtc(), DateTime.utc(2026, 9, 20, 16, 52, 29));
    });
  });

  test('formatearFechaHora da dd/MM/yyyy HH:mm con ceros a la izquierda', () {
    expect(formatearFechaHora(DateTime(2026, 3, 5, 7, 4)), '05/03/2026 07:04');
    expect(formatearFechaHora(DateTime(2026, 12, 31, 23, 59)), '31/12/2026 23:59');
  });

  group('un instante del servidor, con o sin "Z", es el mismo en cualquier zona de la máquina', () {
    final instante = DateTime.utc(2026, 11, 7, 3, 12);

    test('con y sin Z dan el mismo instante UTC', () {
      expect(instanteUtcDelServidor('2026-11-07T03:12:00Z'), instante);
      expect(instanteUtcDelServidor('2026-11-07T03:12:00'), instante);
      expect(instanteUtcDelServidor('2026-11-07T03:12:00Z').isUtc, isTrue);
      expect(instanteUtcDelServidor('2026-11-07T03:12:00').isUtc, isTrue);
    });

    test('fechaDelServidor lo entrega en hora local', () {
      for (final texto in ['2026-11-07T03:12:00Z', '2026-11-07T03:12:00', '2026-11-06T23:12:00-04:00']) {
        final f = fechaDelServidor(texto);
        expect(f.isUtc, isFalse, reason: texto);
        expect(f.toUtc(), instante, reason: texto);
        expect(f, instante.toLocal(), reason: texto);
      }
    });

    test('formatearFechaHora muestra la hora local aunque se le pase un instante UTC', () {
      final local = instante.toLocal();
      String dos(int n) => n.toString().padLeft(2, '0');
      final esperado = '${dos(local.day)}/${dos(local.month)}/${local.year} ${dos(local.hour)}:${dos(local.minute)}';

      expect(formatearFechaHora(instante), esperado);
      expect(formatearFechaHora(fechaDelServidor('2026-11-07T03:12:00')), esperado);
      expect(formatearFechaHora(fechaDelServidor('2026-11-07T03:12:00Z')), esperado);
    });

    test('con fracción de segundo y con desfase', () {
      expect(instanteUtcDelServidor('2026-11-07T03:12:00.250'), DateTime.utc(2026, 11, 7, 3, 12, 0, 250));
      expect(instanteUtcDelServidor('2026-11-07T03:12:00.250Z'), DateTime.utc(2026, 11, 7, 3, 12, 0, 250));
      expect(instanteUtcDelServidor('2026-11-07T04:12:00+01:00'), instante);
      expect(instanteUtcDelServidor('2026-11-07T03:12:00-00:00'), instante);
    });

    test('comparar por día se hace en hora local', () {
      final a = fechaDelServidor('2026-11-07T03:12:00');
      final b = a.add(const Duration(minutes: 5));
      expect(a.isBefore(b), isTrue);
      final local = instante.toLocal();
      expect(DateTime(a.year, a.month, a.day), DateTime(local.year, local.month, local.day));
    });
  });

  group('leerInstanteUtc (lector tolerante)', () {
    test('devuelve UTC, o null si falta o no se entiende', () {
      expect(leerInstanteUtc('2026-11-07T03:12:00'), DateTime.utc(2026, 11, 7, 3, 12));
      expect(leerInstanteUtc('2026-11-07T03:12:00Z'), DateTime.utc(2026, 11, 7, 3, 12));
      expect(leerInstanteUtc('  2026-11-07T03:12:00Z '), DateTime.utc(2026, 11, 7, 3, 12));
      expect(leerInstanteUtc(null), isNull);
      expect(leerInstanteUtc(''), isNull);
      expect(leerInstanteUtc(42), isNull);
      expect(leerInstanteUtc('ayer por la tarde'), isNull);
    });

    test('una fecha sin hora se toma como medianoche UTC, sin fallar', () {
      expect(leerInstanteUtc('2026-11-07'), DateTime.utc(2026, 11, 7));
    });
  });

  group('los modelos leen las fechas del backend como UTC', () {
    final esperado = DateTime.utc(2026, 9, 20, 16, 52, 29);

    test('Pago', () {
      final pago = Pago.fromJson({
        'id': 1,
        'venta_id': 2,
        'monto': '10.00',
        'fecha': '2026-09-20T16:52:29',
        'metodo_pago': 'paypal',
        'estado': 'aprobado',
      });
      expect(pago.fecha.toUtc(), esperado);
    });

    test('Favorito', () {
      final favorito = Favorito.fromJson({
        'variante_id': 1,
        'producto_id': 2,
        'nombre_producto': 'Polera',
        'sku': 'P-1',
        'creado_en': '2026-09-20T16:52:29',
      });
      expect(favorito.creadoEn.toUtc(), esperado);
    });

    test('ReservaHistorialItem', () {
      final item = ReservaHistorialItem.fromJson({
        'id': 1,
        'estado': 'pendiente',
        'comentario': null,
        'creado_en': '2026-09-20T16:52:29',
      });
      expect(item.creadoEn.toUtc(), esperado);
    });
  });
}
