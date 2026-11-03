import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_theme.dart';
import '../state/sincronizacion_providers.dart';
import 'textos_sync.dart';

/// Franja que avisa que el servidor no deja sincronizar: el plan o la suscripción de la empresa, una app que debe actualizarse
/// o una sesión vencida. No ocupa espacio si no pasa nada. Las operaciones NO se pierden: siguen guardadas en el teléfono.
///
/// Se reutiliza en el inicio, en la lista de operaciones y en la pantalla de resultado.
class AvisoBloqueoSync extends ConsumerWidget {
  const AvisoBloqueoSync({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final estado = ref.watch(estadoSyncProvider).valueOrNull;
    if (estado == null) return const SizedBox.shrink();

    final String texto;
    final Color color;
    if (estado.sesionVencida) {
      texto = textoSesionVencida;
      color = AppColors.error;
    } else if (estado.bloqueo != null) {
      texto = estado.bloqueo!.mensaje;
      color = AppColors.advertencia;
    } else {
      return const SizedBox.shrink();
    }

    return Semantics(
      container: true,
      liveRegion: true,
      child: Container(
        key: const Key('aviso_bloqueo_sync'),
        width: double.infinity,
        margin: const EdgeInsets.only(bottom: AppSpacing.md),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.08),
          border: Border(left: BorderSide(color: color, width: 4)),
        ),
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.sm),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Icon(Icons.sync_problem, size: 20, color: color),
            ),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: Text(texto, style: TextStyle(color: color, fontSize: 14, fontWeight: FontWeight.w500)),
            ),
          ],
        ),
      ),
    );
  }
}
