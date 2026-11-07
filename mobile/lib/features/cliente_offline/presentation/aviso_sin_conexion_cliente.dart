import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/conectividad/conectividad_service.dart';
import '../../../core/theme/app_theme.dart';
import '../config/cliente_offline_config.dart';

/// La franja "Sin conexión: ves lo que ya tenías cargado". No ocupa espacio mientras hay conexión (ni mientras se conoce
/// el primer valor).
class AvisoSinConexionCliente extends ConsumerWidget {
  const AvisoSinConexionCliente({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final enLinea = ref.watch(enLineaProvider).valueOrNull ?? true;
    if (enLinea) return const SizedBox.shrink();
    // Texto blanco sobre el color de advertencia (#B45309): contraste de 5,5 a 1.
    return Semantics(
      liveRegion: true,
      container: true,
      child: Container(
        key: const Key('aviso-sin-conexion'),
        width: double.infinity,
        color: AppColors.advertencia,
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.sm),
        child: const Row(
          children: [
            Icon(Icons.cloud_off, size: 20, color: Colors.white),
            SizedBox(width: AppSpacing.sm),
            Expanded(
              child: Text(
                avisoSinConexionCliente,
                style: TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w500),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// La conexión según la app, para usar dentro de `build` (se vuelve a construir al cambiar). Sin saberlo todavía se asume
/// que hay.
bool estaEnLinea(WidgetRef ref) => ref.watch(enLineaProvider).valueOrNull ?? true;

/// Lo mismo, para usar en un evento (un toque, una carga): lee el valor de ahora sin suscribirse.
bool enLineaAhora(WidgetRef ref) => ref.read(enLineaProvider).valueOrNull ?? true;
