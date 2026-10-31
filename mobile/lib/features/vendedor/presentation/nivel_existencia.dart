import 'package:flutter/material.dart';

import '../../../core/theme/app_theme.dart';

/// Con esta cantidad o menos se avisa "quedan pocas".
const umbralPocasUnidades = 2;

/// Cómo se presenta una existencia ESTIMADA. Siempre va con color Y texto (nunca solo color).
enum NivelExistencia {
  hay,
  pocas,
  agotado;

  static NivelExistencia de(int cantidad) {
    if (cantidad <= 0) return NivelExistencia.agotado;
    if (cantidad <= umbralPocasUnidades) return NivelExistencia.pocas;
    return NivelExistencia.hay;
  }

  Color get color => switch (this) {
    NivelExistencia.hay => AppColors.exito,
    NivelExistencia.pocas => AppColors.advertencia,
    NivelExistencia.agotado => AppColors.textoTenue,
  };

  IconData get icono => switch (this) {
    NivelExistencia.hay => Icons.check_circle_outline,
    NivelExistencia.pocas => Icons.warning_amber_rounded,
    NivelExistencia.agotado => Icons.remove_circle_outline,
  };

  /// El texto de la insignia del detalle.
  String get etiqueta => switch (this) {
    NivelExistencia.hay => 'Hay',
    NivelExistencia.pocas => 'Quedan pocas',
    NivelExistencia.agotado => 'Agotado',
  };
}

/// El texto corto de la tarjeta del catálogo: "12 en tienda", "Quedan 2", "Queda 1" o "Agotado".
String textoExistenciaTarjeta(int cantidad) {
  if (cantidad <= 0) return 'Agotado';
  if (cantidad <= umbralPocasUnidades) return cantidad == 1 ? 'Queda 1' : 'Quedan $cantidad';
  return '$cantidad en tienda';
}
