import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/sync/backoff.dart';

/// Un `Random` que devuelve siempre el mismo `nextDouble` (0 = el extremo bajo del jitter, 1 = el alto).
class _AzarFijo implements Random {
  _AzarFijo(this.valor);

  final double valor;

  @override
  double nextDouble() => valor;

  @override
  bool nextBool() => false;

  @override
  int nextInt(int max) => 0;
}

void main() {
  Duration espera(int intentos, {double jitter = 0, Random? azar}) => calcularEspera(intentos, jitter: jitter, azar: azar);

  group('sin variación aleatoria', () {
    test('5 s, 10 s, 20 s, 40 s, 80 s, 160 s', () {
      expect(espera(1), const Duration(seconds: 5));
      expect(espera(2), const Duration(seconds: 10));
      expect(espera(3), const Duration(seconds: 20));
      expect(espera(4), const Duration(seconds: 40));
      expect(espera(5), const Duration(seconds: 80));
      expect(espera(6), const Duration(seconds: 160));
    });

    test('desde el séptimo intento llega al tope de 5 minutos', () {
      expect(espera(7), const Duration(minutes: 5));
      expect(espera(8), const Duration(minutes: 5));
      expect(espera(20), const Duration(minutes: 5));
    });

    test('con jitter 0 el resultado es exacto aunque se pase un Random', () {
      expect(espera(3, azar: _AzarFijo(0.9)), const Duration(seconds: 20));
      expect(espera(3, azar: _AzarFijo(0)), const Duration(seconds: 20));
    });

    test('intentos 0 o negativos cuentan como el primero', () {
      expect(espera(0), const Duration(seconds: 5));
      expect(espera(-1), const Duration(seconds: 5));
      expect(espera(-1000), const Duration(seconds: 5));
    });

    test('muchísimos intentos no desbordan ni dan una espera negativa', () {
      for (final n in [31, 32, 64, 100, 1000, 1000000, 9007199254740991]) {
        final e = espera(n);
        expect(e, const Duration(minutes: 5), reason: 'intentos=$n');
      }
    });

    test('la espera nunca baja con más intentos', () {
      var anterior = Duration.zero;
      for (var n = 1; n <= 50; n++) {
        final e = espera(n);
        expect(e >= anterior, isTrue, reason: 'intentos=$n');
        anterior = e;
      }
    });
  });

  group('con variación aleatoria (jitter 20 %)', () {
    test('el extremo bajo es 20 % menos', () {
      expect(calcularEspera(2, azar: _AzarFijo(0)), const Duration(seconds: 8));
    });

    test('el centro no cambia la espera', () {
      expect(calcularEspera(2, azar: _AzarFijo(0.5)), const Duration(seconds: 10));
    });

    test('el extremo alto es 20 % más', () {
      expect(calcularEspera(2, azar: _AzarFijo(1)), const Duration(seconds: 12));
    });

    test('con Random fijo (semilla) siempre queda dentro de ±20 %', () {
      final azar = Random(42);
      for (var n = 1; n <= 6; n++) {
        final base = 5000 * pow(2, n - 1);
        for (var i = 0; i < 200; i++) {
          final ms = calcularEspera(n, azar: azar).inMilliseconds;
          expect(ms, greaterThanOrEqualTo((base * 0.8).floor() - 1), reason: 'n=$n');
          expect(ms, lessThanOrEqualTo((base * 1.2).ceil() + 1), reason: 'n=$n');
        }
      }
    });

    test('con la misma semilla da la misma secuencia', () {
      final a = [for (var n = 1; n <= 8; n++) calcularEspera(n, azar: Random(7))];
      final b = [for (var n = 1; n <= 8; n++) calcularEspera(n, azar: Random(7))];
      expect(a, b);
    });

    test('NUNCA pasa del tope, ni con el jitter en su extremo alto', () {
      for (final n in [7, 8, 12, 40, 1000]) {
        expect(calcularEspera(n, azar: _AzarFijo(1)), const Duration(minutes: 5), reason: 'n=$n');
      }
      final azar = Random(1);
      for (var i = 0; i < 500; i++) {
        expect(calcularEspera(30 + i, azar: azar) <= const Duration(minutes: 5), isTrue);
      }
    });

    test('en el tope el jitter solo puede bajar la espera', () {
      final bajo = calcularEspera(10, azar: _AzarFijo(0));
      expect(bajo, const Duration(minutes: 4));
    });

    test('sin Random inyectado también cae dentro del rango', () {
      for (var i = 0; i < 100; i++) {
        final ms = calcularEspera(3).inMilliseconds;
        expect(ms, inInclusiveRange(16000, 24000));
      }
    });
  });

  group('parámetros propios', () {
    test('base y factor distintos', () {
      expect(calcularEspera(3, base: const Duration(seconds: 1), factor: 3, jitter: 0), const Duration(seconds: 9));
    });

    test('un tope menor corta antes', () {
      expect(calcularEspera(5, tope: const Duration(seconds: 30), jitter: 0), const Duration(seconds: 30));
    });
  });
}
