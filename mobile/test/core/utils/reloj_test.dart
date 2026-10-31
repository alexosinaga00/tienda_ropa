import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/utils/reloj.dart';

class _RelojFijo implements Reloj {
  _RelojFijo(this.fijo);

  DateTime fijo;

  @override
  DateTime ahora() => fijo;
}

void main() {
  group('RelojSistema', () {
    test('ahora() es UTC', () {
      expect(const RelojSistema().ahora().isUtc, isTrue);
    });

    test('ahora() está cerca de la hora real', () {
      final antes = DateTime.now().toUtc();
      final ahora = const RelojSistema().ahora();
      final despues = DateTime.now().toUtc();
      expect(ahora.isBefore(antes), isFalse);
      expect(ahora.isAfter(despues), isFalse);
    });

    test('avanza entre dos llamadas (no queda congelado)', () async {
      final a = const RelojSistema().ahora();
      await Future<void>.delayed(const Duration(milliseconds: 5));
      expect(const RelojSistema().ahora().isAfter(a), isTrue);
    });
  });

  group('Reloj falso', () {
    test('un reloj fijo siempre devuelve la misma hora', () {
      final reloj = _RelojFijo(DateTime.utc(2026, 10, 31, 10));
      expect(reloj.ahora(), DateTime.utc(2026, 10, 31, 10));
      expect(reloj.ahora(), DateTime.utc(2026, 10, 31, 10));
      reloj.fijo = DateTime.utc(2026, 11);
      expect(reloj.ahora(), DateTime.utc(2026, 11));
    });

    test('relojProvider entrega el del sistema y se puede sustituir', () {
      final normal = ProviderContainer();
      addTearDown(normal.dispose);
      expect(normal.read(relojProvider), isA<RelojSistema>());

      final fijo = _RelojFijo(DateTime.utc(2026, 1, 2));
      final sustituido = ProviderContainer(overrides: [relojProvider.overrideWithValue(fijo)]);
      addTearDown(sustituido.dispose);
      expect(sustituido.read(relojProvider).ahora(), DateTime.utc(2026, 1, 2));
    });
  });
}
