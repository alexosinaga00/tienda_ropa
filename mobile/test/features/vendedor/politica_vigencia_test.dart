import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/vendedor/data/politica_vigencia.dart';

final _ahora = DateTime.utc(2026, 10, 31, 12);

void main() {
  group('umbrales', () {
    test('por defecto el aviso es a las 2 horas y lo crítico a las 24', () {
      const politica = PoliticaVigencia();

      expect(PoliticaVigencia.avisoPorDefecto, const Duration(hours: 2));
      expect(PoliticaVigencia.criticoPorDefecto, const Duration(hours: 24));
      expect(politica.umbralAviso, const Duration(hours: 2));
      expect(politica.umbralCritico, const Duration(hours: 24));
    });

    test('conAvisoHoras(null) usa los de por defecto', () {
      final politica = PoliticaVigencia.conAvisoHoras(null);

      expect(politica.umbralAviso, PoliticaVigencia.avisoPorDefecto);
      expect(politica.umbralCritico, PoliticaVigencia.criticoPorDefecto);
    });

    test('conAvisoHoras con 0 o negativo también usa los de por defecto', () {
      for (final horas in [0, -3]) {
        final politica = PoliticaVigencia.conAvisoHoras(horas);
        expect(politica.umbralAviso, PoliticaVigencia.avisoPorDefecto, reason: '$horas');
        expect(politica.umbralCritico, PoliticaVigencia.criticoPorDefecto, reason: '$horas');
      }
    });

    test('conAvisoHoras(1) baja el umbral de aviso y deja lo crítico en 24 h', () {
      final politica = PoliticaVigencia.conAvisoHoras(1);

      expect(politica.umbralAviso, const Duration(hours: 1));
      expect(politica.umbralCritico, const Duration(hours: 24));
    });

    test('conAvisoHoras(12) usa 12 h de aviso', () {
      final politica = PoliticaVigencia.conAvisoHoras(12);

      expect(politica.umbralAviso, const Duration(hours: 12));
      expect(politica.umbralCritico, const Duration(hours: 24));
    });

    test('lo crítico sube a aviso + 1 h cuando el aviso alcanza las 24 h', () {
      expect(PoliticaVigencia.conAvisoHoras(24).umbralCritico, const Duration(hours: 25));
      expect(PoliticaVigencia.conAvisoHoras(48).umbralCritico, const Duration(hours: 49));
    });

    test('con 23 h de aviso lo crítico queda en 24 h (justo aviso + 1 h)', () {
      expect(PoliticaVigencia.conAvisoHoras(23).umbralCritico, const Duration(hours: 24));
    });

    test('lo crítico nunca es menor que el aviso más una hora, para cualquier aviso', () {
      for (var horas = -2; horas <= 200; horas++) {
        final politica = PoliticaVigencia.conAvisoHoras(horas);
        expect(
          politica.umbralCritico >= politica.umbralAviso + const Duration(hours: 1),
          isTrue,
          reason: 'aviso de $horas h',
        );
        expect(politica.umbralCritico >= PoliticaVigencia.criticoPorDefecto, isTrue, reason: 'aviso de $horas h');
      }
    });
  });

  group('estadoDe', () {
    const politica = PoliticaVigencia();

    test('sin descarga es "nunca"', () {
      expect(politica.estadoDe(null, _ahora), EstadoVigencia.nunca);
    });

    test('recién descargado es fresca', () {
      expect(politica.estadoDe(_ahora, _ahora), EstadoVigencia.fresca);
    });

    test('un segundo antes del umbral de aviso sigue fresca', () {
      final descargado = _ahora.subtract(const Duration(hours: 2)).add(const Duration(seconds: 1));

      expect(politica.estadoDe(descargado, _ahora), EstadoVigencia.fresca);
    });

    test('exactamente en el umbral de aviso ya es antigua', () {
      expect(politica.estadoDe(_ahora.subtract(const Duration(hours: 2)), _ahora), EstadoVigencia.antigua);
    });

    test('un segundo antes del umbral crítico sigue antigua', () {
      final descargado = _ahora.subtract(const Duration(hours: 24)).add(const Duration(seconds: 1));

      expect(politica.estadoDe(descargado, _ahora), EstadoVigencia.antigua);
    });

    test('exactamente en el umbral crítico ya es crítica', () {
      expect(politica.estadoDe(_ahora.subtract(const Duration(hours: 24)), _ahora), EstadoVigencia.critica);
    });

    test('mucho tiempo después sigue siendo crítica', () {
      expect(politica.estadoDe(_ahora.subtract(const Duration(days: 40)), _ahora), EstadoVigencia.critica);
    });

    test('una descarga con hora futura (reloj atrasado) cuenta como fresca', () {
      expect(politica.estadoDe(_ahora.add(const Duration(minutes: 10)), _ahora), EstadoVigencia.fresca);
    });

    test('con el aviso del servidor en 1 hora, 90 minutos ya es antigua (con 2 h sería fresca)', () {
      final descargado = _ahora.subtract(const Duration(minutes: 90));

      expect(const PoliticaVigencia().estadoDe(descargado, _ahora), EstadoVigencia.fresca);
      expect(PoliticaVigencia.conAvisoHoras(1).estadoDe(descargado, _ahora), EstadoVigencia.antigua);
    });

    test('con aviso de 30 h: a 30 h es antigua y a 31 h es crítica', () {
      final p = PoliticaVigencia.conAvisoHoras(30);

      expect(p.estadoDe(_ahora.subtract(const Duration(hours: 30)), _ahora), EstadoVigencia.antigua);
      expect(p.estadoDe(_ahora.subtract(const Duration(hours: 31)), _ahora), EstadoVigencia.critica);
    });
  });

  group('debeAvisar', () {
    const politica = PoliticaVigencia();

    test('fresca y en línea: no avisa', () {
      expect(politica.debeAvisar(EstadoVigencia.fresca, enLinea: true), isFalse);
    });

    test('fresca pero sin conexión: avisa', () {
      expect(politica.debeAvisar(EstadoVigencia.fresca, enLinea: false), isTrue);
    });

    test('antigua, crítica y nunca avisan con y sin conexión', () {
      for (final estado in [EstadoVigencia.antigua, EstadoVigencia.critica, EstadoVigencia.nunca]) {
        expect(politica.debeAvisar(estado, enLinea: true), isTrue, reason: '$estado en línea');
        expect(politica.debeAvisar(estado, enLinea: false), isTrue, reason: '$estado sin conexión');
      }
    });
  });

  group('ResumenVigencia', () {
    test('guarda el estado, la hora y la edad', () {
      final r = ResumenVigencia(
        estado: EstadoVigencia.antigua,
        descargadoEn: _ahora,
        edad: const Duration(hours: 3),
      );

      expect(r.estado, EstadoVigencia.antigua);
      expect(r.descargadoEn, _ahora);
      expect(r.edad, const Duration(hours: 3));
    });

    test('para "nunca" no hay hora ni edad', () {
      const r = ResumenVigencia(estado: EstadoVigencia.nunca);

      expect(r.descargadoEn, isNull);
      expect(r.edad, isNull);
    });
  });
}
