import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/utils/texto.dart';

void main() {
  group('normalizarBusqueda', () {
    test('quita tildes y diéresis', () {
      expect(normalizarBusqueda('Camisa Básica'), 'camisa basica');
      expect(normalizarBusqueda('Pantalón'), 'pantalon');
      expect(normalizarBusqueda('Pingüino'), 'pinguino');
      expect(normalizarBusqueda('áéíóú àèìòù äëïöü âêîôû'), 'aeiou aeiou aeiou aeiou');
    });

    test('la ñ y la ç pasan a n y c', () {
      expect(normalizarBusqueda('Ñandú'), 'nandu');
      expect(normalizarBusqueda('Canción'), 'cancion');
      expect(normalizarBusqueda('Ça va'), 'ca va');
    });

    test('pasa a minúsculas, también las mayúsculas con tilde', () {
      expect(normalizarBusqueda('CAMISA'), 'camisa');
      expect(normalizarBusqueda('CAMISÁ'), 'camisa');
      expect(normalizarBusqueda('ÁÉÍÓÚ Ñ'), 'aeiou n');
    });

    test('colapsa los espacios múltiples y los saltos de línea', () {
      expect(normalizarBusqueda('  polera   roja  '), 'polera roja');
      expect(normalizarBusqueda('a\t\tb\n c'), 'a b c');
    });

    test('vacío o solo espacios da vacío', () {
      expect(normalizarBusqueda(''), '');
      expect(normalizarBusqueda('    '), '');
    });

    test('deja intactos números, guiones y símbolos', () {
      expect(normalizarBusqueda('SKU-001_X 50%'), 'sku-001_x 50%');
    });

    test('es idempotente', () {
      final una = normalizarBusqueda('  Camisa   BÁSICA ñ ');
      expect(normalizarBusqueda(una), una);
    });
  });
}
