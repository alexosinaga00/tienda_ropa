import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/utils/dinero.dart';

void main() {
  group('aCentavos', () {
    test('suma exacta: 0.1 + 0.2 desde texto da 0.3 (sin el error de los double)', () {
      expect(aCentavos('0.1') + aCentavos('0.2'), 30);
      expect(aCentavos('0.1') + aCentavos('0.2'), aCentavos('0.3'));
    });

    test('texto con y sin decimales', () {
      expect(aCentavos('75.00'), 7500);
      expect(aCentavos('75'), 7500);
      expect(aCentavos('75.5'), 7550);
      expect(aCentavos('0'), 0);
      expect(aCentavos('0.05'), 5);
    });

    test('acepta int y double', () {
      expect(aCentavos(75), 7500);
      expect(aCentavos(75.5), 7550);
      expect(aCentavos(0), 0);
    });

    test('redondea hacia arriba desde la mitad', () {
      expect(aCentavos(10.005), 1001);
      expect(aCentavos('10.005'), 1001);
      expect(aCentavos('10.004'), 1000);
      expect(aCentavos('10.0049999'), 1000);
      expect(aCentavos('0.005'), 1);
      expect(aCentavos('0.004'), 0);
      expect(aCentavos('99.999'), 10000);
    });

    test('montos grandes', () {
      expect(aCentavos('1234567.89'), 123456789);
      expect(aCentavos('99999999.99'), 9999999999);
    });

    test('ignora espacios alrededor del texto', () {
      expect(aCentavos('  75.00 '), 7500);
    });

    test('rechaza negativos', () {
      expect(() => aCentavos('-5'), throwsFormatException);
      expect(() => aCentavos('-0.01'), throwsFormatException);
      expect(() => aCentavos(-5), throwsFormatException);
      expect(() => aCentavos(-1.5), throwsFormatException);
    });

    test('rechaza vacío y texto que no es un número', () {
      expect(() => aCentavos(''), throwsFormatException);
      expect(() => aCentavos('   '), throwsFormatException);
      expect(() => aCentavos('abc'), throwsFormatException);
      expect(() => aCentavos('Bs 5'), throwsFormatException);
      expect(() => aCentavos('1e3'), throwsFormatException);
    });

    test('rechaza la coma decimal y los puntos mal puestos', () {
      expect(() => aCentavos('1,5'), throwsFormatException);
      expect(() => aCentavos('1.2.3'), throwsFormatException);
      expect(() => aCentavos('.5'), throwsFormatException);
      expect(() => aCentavos('1.'), throwsFormatException);
    });

    test('rechaza tipos que no son monto y los double no finitos', () {
      expect(() => aCentavos(true), throwsFormatException);
      expect(() => aCentavos(double.nan), throwsFormatException);
      expect(() => aCentavos(double.infinity), throwsFormatException);
    });
  });

  group('deCentavos y formatearBs', () {
    test('deCentavos da el formato del JSON', () {
      expect(deCentavos(7500), '75.00');
      expect(deCentavos(5), '0.05');
      expect(deCentavos(0), '0.00');
      expect(deCentavos(10), '0.10');
      expect(deCentavos(123456789), '1234567.89');
    });

    test('deCentavos rechaza negativos con RangeError', () {
      expect(() => deCentavos(-1), throwsRangeError);
    });

    test('formatearBs antepone Bs', () {
      expect(formatearBs(7500), 'Bs 75.00');
      expect(formatearBs(5), 'Bs 0.05');
    });

    test('ida y vuelta texto -> centavos -> texto', () {
      for (final s in ['0.00', '0.01', '75.00', '1234567.89', '10.10']) {
        expect(deCentavos(aCentavos(s)), s);
      }
    });
  });
}
