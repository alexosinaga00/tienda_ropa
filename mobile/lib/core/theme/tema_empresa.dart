import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../features/tienda/state/tienda_controller.dart';
import 'app_theme.dart';

/// Contraste mínimo de texto normal (WCAG AA) entre el texto blanco de los botones y el color de fondo.
const double contrasteMinimoConBlanco = 4.5;

final _formatoHex = RegExp(r'^#[0-9A-Fa-f]{6}$');

double _canalLineal(double c) => c <= 0.03928 ? c / 12.92 : math.pow((c + 0.055) / 1.055, 2.4).toDouble();

/// Luminancia relativa WCAG de un color (0 negro, 1 blanco).
double _luminancia(Color c) {
  return 0.2126 * _canalLineal(c.r) + 0.7152 * _canalLineal(c.g) + 0.0722 * _canalLineal(c.b);
}

/// Contraste WCAG entre [c] y el blanco: 1 (blanco) a 21 (negro).
double contrasteConBlanco(Color c) => 1.05 / (_luminancia(c) + 0.05);

/// Convierte el `color_acento` de la tienda (`#RRGGBB`, con el `#`) en un color seguro para el texto blanco de los
/// botones. Devuelve null si el formato es inválido (el tema base se queda como está). Si el contraste con el blanco
/// es menor a 4,5 lo oscurece, mezclándolo poco a poco con negro, hasta alcanzarlo (el tono se conserva).
Color? colorAcentoSeguro(String? hex) {
  if (hex == null || !_formatoHex.hasMatch(hex)) return null;
  final base = Color(0xFF000000 | int.parse(hex.substring(1), radix: 16));
  var color = base;
  var paso = 0;
  while (contrasteConBlanco(color) < contrasteMinimoConBlanco && paso < 20) {
    paso++;
    color = Color.lerp(base, const Color(0xFF000000), paso * 0.05)!;
  }
  return color;
}

/// El tema de la tienda elegida: el base con su color de acento, o el base solo si no tiene uno válido.
final temaEmpresaProvider = Provider<ThemeData>((ref) {
  final tienda = ref.watch(tiendaActualProvider);
  return buildAppTheme(acento: colorAcentoSeguro(tienda?.colorAcento));
});
