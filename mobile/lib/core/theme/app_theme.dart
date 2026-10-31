import 'package:flutter/material.dart';

/// Tokens de diseño de CLAUDE.md. El cliente es al revés que el back
/// office: fondo claro, mucho espacio, la fotografía como protagonista
/// (ver AppSpacing, pensado para respirar, no para densidad).
class AppColors {
  static const fondo = Color(0xFFFFFFFF);
  static const fondoAlterno = Color(0xFFF7F7F5);
  static const texto = Color(0xFF1A1A1A);
  static const textoTenue = Color(0xFF6B6B6B);
  static const acento = Color(0xFF1F2937);
  static const exito = Color(0xFF16A34A);
  static const error = Color(0xFFDC2626);
  static const advertencia = Color(0xFFB45309);
  static const borde = Color(0xFFE5E5E5);
}

class AppRadius {
  static const base = 8.0;
}

/// Espaciado en múltiplos de 4px.
class AppSpacing {
  static const xs = 4.0;
  static const sm = 8.0;
  static const md = 16.0;
  static const lg = 24.0;
  static const xl = 32.0;
  static const xxl = 48.0;
}

/// Sin [acento] devuelve el tema base. Con [acento] (el color de la tienda ya validado con `colorAcentoSeguro`)
/// cambia el color primario, los botones, los botones de texto y el borde de foco de los campos. `AppColors.acento`
/// no cambia: los widgets que lo usan directo conservan el color base.
ThemeData buildAppTheme({Color? acento}) {
  final primario = acento ?? AppColors.acento;
  final colorScheme = ColorScheme.fromSeed(
    seedColor: primario,
    primary: primario,
    error: AppColors.error,
    surface: AppColors.fondo,
  );

  return ThemeData(
    useMaterial3: true,
    colorScheme: colorScheme,
    scaffoldBackgroundColor: AppColors.fondo,
    fontFamily: 'Roboto',
    textTheme: const TextTheme(
      headlineMedium: TextStyle(color: AppColors.texto, fontWeight: FontWeight.w600),
      bodyLarge: TextStyle(color: AppColors.texto),
      bodyMedium: TextStyle(color: AppColors.textoTenue),
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.fondo,
      foregroundColor: AppColors.texto,
      elevation: 0,
      centerTitle: false,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.fondoAlterno,
      contentPadding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.md),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppRadius.base),
        borderSide: const BorderSide(color: AppColors.borde),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppRadius.base),
        borderSide: const BorderSide(color: AppColors.borde),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppRadius.base),
        borderSide: BorderSide(color: primario, width: 1.5),
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: primario,
        foregroundColor: Colors.white,
        minimumSize: const Size.fromHeight(52),
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.md),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppRadius.base)),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(foregroundColor: primario),
    ),
  );
}
