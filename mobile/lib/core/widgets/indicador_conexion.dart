import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../conectividad/conectividad_service.dart';
import '../theme/app_theme.dart';

const textoSinConexion = 'Sin conexión. Los datos pueden estar desactualizados.';

enum _Forma { banner, icono }

/// Avisa que no hay conexión. No ocupa espacio mientras hay conexión o mientras se conoce el primer valor.
///
/// - [IndicadorConexion.banner]: una franja con el aviso, para el cuerpo de las pantallas.
/// - [IndicadorConexion.icono]: un ícono con tooltip, para la barra superior.
class IndicadorConexion extends ConsumerWidget {
  const IndicadorConexion.banner({super.key}) : _forma = _Forma.banner;

  const IndicadorConexion.icono({super.key}) : _forma = _Forma.icono;

  final _Forma _forma;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Mientras carga el primer valor (o si falla el flujo) se asume que hay conexión: no se avisa de más.
    final enLinea = ref.watch(enLineaProvider).valueOrNull ?? true;
    if (enLinea) return const SizedBox.shrink();

    switch (_forma) {
      case _Forma.banner:
        // Texto blanco sobre el color de advertencia (#B45309): contraste de 5,5 a 1.
        return Semantics(
          liveRegion: true,
          container: true,
          child: Container(
            width: double.infinity,
            color: AppColors.advertencia,
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.sm),
            child: const Row(
              children: [
                Icon(Icons.cloud_off, size: 20, color: Colors.white),
                SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(
                    textoSinConexion,
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 14,
                      fontWeight: FontWeight.w500,
                      decoration: TextDecoration.none,
                    ),
                  ),
                ),
              ],
            ),
          ),
        );
      case _Forma.icono:
        return const Tooltip(
          message: 'Sin conexión',
          child: Padding(
            padding: EdgeInsets.all(AppSpacing.sm),
            child: Icon(Icons.cloud_off, size: 24, color: AppColors.advertencia, semanticLabel: 'Sin conexión'),
          ),
        );
    }
  }
}
