import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/theme/app_theme.dart';
import 'package:mobile/core/theme/tema_empresa.dart';
import 'package:mobile/features/tienda/models/tienda.dart';
import 'package:mobile/features/tienda/state/tienda_controller.dart';

final _tiendaFalsa = StateProvider<Tienda?>((ref) => null);

Color _fondoBoton(ThemeData tema) => tema.elevatedButtonTheme.style!.backgroundColor!.resolve({})!;

Color _fondoTextoBoton(ThemeData tema) => tema.textButtonTheme.style!.foregroundColor!.resolve({})!;

Color _bordeFoco(ThemeData tema) => (tema.inputDecorationTheme.focusedBorder! as OutlineInputBorder).borderSide.color;

void main() {
  group('contrasteConBlanco', () {
    test('el blanco contra blanco es 1', () {
      expect(contrasteConBlanco(Colors.white), closeTo(1, 0.001));
    });

    test('el negro contra blanco es 21', () {
      expect(contrasteConBlanco(Colors.black), closeTo(21, 0.001));
    });

    test('un amarillo claro contrasta poco con el blanco', () {
      expect(contrasteConBlanco(const Color(0xFFFFEB3B)), lessThan(2));
    });
  });

  group('colorAcentoSeguro', () {
    test('un color que ya contrasta queda sin cambios', () {
      final color = colorAcentoSeguro('#1F2937');
      expect(color, const Color(0xFF1F2937));
    });

    test('acepta mayúsculas y minúsculas', () {
      expect(colorAcentoSeguro('#1f2937'), const Color(0xFF1F2937));
      expect(colorAcentoSeguro('#1F2937'), const Color(0xFF1F2937));
    });

    test('un hex claro se oscurece hasta contrastar al menos 4,5', () {
      final color = colorAcentoSeguro('#FFEB3B')!;
      expect(contrasteConBlanco(color), greaterThanOrEqualTo(4.5));
      expect(color, isNot(const Color(0xFFFFEB3B)));
    });

    test('al oscurecer conserva el mismo tono general', () {
      final original = HSLColor.fromColor(const Color(0xFFFFEB3B));
      final seguro = HSLColor.fromColor(colorAcentoSeguro('#FFEB3B')!);
      expect((seguro.hue - original.hue).abs(), lessThan(5));
    });

    test('oscurece lo justo: no llega al negro si no hace falta', () {
      final color = colorAcentoSeguro('#8FAE5B')!;
      expect(contrasteConBlanco(color), greaterThanOrEqualTo(4.5));
      expect(contrasteConBlanco(color), lessThan(6));
    });

    test('el blanco puro también termina con contraste suficiente', () {
      final color = colorAcentoSeguro('#FFFFFF')!;
      expect(contrasteConBlanco(color), greaterThanOrEqualTo(4.5));
    });

    test('hex inválidos devuelven null', () {
      for (final invalido in ['rojo', '#12345', '#GGGGGG', '', '1F2937', '#1F29371', ' #1F2937', '#1F2937 ']) {
        expect(colorAcentoSeguro(invalido), isNull, reason: '"$invalido"');
      }
      expect(colorAcentoSeguro(null), isNull);
    });
  });

  group('buildAppTheme', () {
    test('sin acento es exactamente el tema de siempre', () {
      final tema = buildAppTheme();
      final base = ColorScheme.fromSeed(
        seedColor: AppColors.acento,
        primary: AppColors.acento,
        error: AppColors.error,
        surface: AppColors.fondo,
      );
      expect(tema.colorScheme, base);
      expect(tema.colorScheme.primary, AppColors.acento);
      expect(_fondoBoton(tema), AppColors.acento);
      expect(_fondoTextoBoton(tema), AppColors.acento);
      expect(_bordeFoco(tema), AppColors.acento);
    });

    test('con acento null equivale a no pasarlo', () {
      expect(buildAppTheme(acento: null).colorScheme, buildAppTheme().colorScheme);
    });

    test('con acento reemplaza primario, botón, botón de texto y borde de foco', () {
      const acento = Color(0xFF7B1FA2);
      final tema = buildAppTheme(acento: acento);
      expect(tema.colorScheme.primary, acento);
      expect(_fondoBoton(tema), acento);
      expect(_fondoTextoBoton(tema), acento);
      expect(_bordeFoco(tema), acento);
    });

    test('con acento no cambia lo demás (fondo, error, texto del botón)', () {
      final tema = buildAppTheme(acento: const Color(0xFF7B1FA2));
      expect(tema.scaffoldBackgroundColor, AppColors.fondo);
      expect(tema.colorScheme.error, AppColors.error);
      expect(tema.elevatedButtonTheme.style!.foregroundColor!.resolve({}), Colors.white);
    });
  });

  group('temaEmpresaProvider', () {
    ProviderContainer crear() {
      final container = ProviderContainer(
        overrides: [tiendaActualProvider.overrideWith((ref) => ref.watch(_tiendaFalsa))],
      );
      addTearDown(container.dispose);
      return container;
    }

    test('sin tienda usa el tema base', () {
      final container = crear();
      expect(container.read(temaEmpresaProvider).colorScheme.primary, AppColors.acento);
    });

    test('con la tienda elegida usa su color de acento', () {
      final container = crear();
      container.read(_tiendaFalsa.notifier).state = const Tienda(codigo: 'a', nombre: 'A', colorAcento: '#1B5E20');
      expect(container.read(temaEmpresaProvider).colorScheme.primary, const Color(0xFF1B5E20));
    });

    test('cambia al cambiar la tienda', () {
      final container = crear();
      container.read(_tiendaFalsa.notifier).state = const Tienda(codigo: 'a', nombre: 'A', colorAcento: '#1B5E20');
      final verde = container.read(temaEmpresaProvider).colorScheme.primary;
      container.read(_tiendaFalsa.notifier).state = const Tienda(codigo: 'b', nombre: 'B', colorAcento: '#0D47A1');
      final azul = container.read(temaEmpresaProvider).colorScheme.primary;
      expect(azul, isNot(verde));
      expect(azul, const Color(0xFF0D47A1));
    });

    test('un color claro de la tienda llega ya oscurecido al tema', () {
      final container = crear();
      container.read(_tiendaFalsa.notifier).state = const Tienda(codigo: 'a', nombre: 'A', colorAcento: '#FFEB3B');
      final primario = container.read(temaEmpresaProvider).colorScheme.primary;
      expect(contrasteConBlanco(primario), greaterThanOrEqualTo(4.5));
    });

    test('un color inválido o ausente deja el tema base', () {
      final container = crear();
      container.read(_tiendaFalsa.notifier).state = const Tienda(codigo: 'a', nombre: 'A', colorAcento: 'rojo');
      expect(container.read(temaEmpresaProvider).colorScheme.primary, AppColors.acento);
      container.read(_tiendaFalsa.notifier).state = const Tienda(codigo: 'a', nombre: 'A');
      expect(container.read(temaEmpresaProvider).colorScheme.primary, AppColors.acento);
    });
  });
}
