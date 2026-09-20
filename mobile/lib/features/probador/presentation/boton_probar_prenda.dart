import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/app_theme.dart';
import '../state/probador_providers.dart';

/// Abre el probador virtual con esta variante ya puesta. Solo se muestra si la variante tiene un overlay validado
/// (la misma regla que usa el probador para listar prendas); mientras se consulta, o si la consulta falla, no muestra
/// nada, para no meter parpadeos ni errores en el detalle o el carrito.
///
/// - Detalle: botón completo. Con [avisarSiNoHay] avisa que esa variante aún no tiene probador, en vez de callar.
/// - Carrito ([compacto]): un "Probar" chico, junto a "Quitar".
class BotonProbarPrenda extends ConsumerWidget {
  const BotonProbarPrenda({required this.varianteId, this.compacto = false, this.avisarSiNoHay = false, super.key});

  final int varianteId;
  final bool compacto;
  final bool avisarSiNoHay;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return ref
        .watch(assetsProbadorProvider(varianteId))
        .maybeWhen(
          data: (assets) {
            if (assets == null) {
              return avisarSiNoHay
                  ? const Text(
                      'Esta variante aún no tiene probador',
                      style: TextStyle(color: AppColors.textoTenue, fontSize: 12),
                    )
                  : const SizedBox.shrink();
            }
            void abrir() => context.push('/probador?variante=$varianteId');
            if (compacto) {
              return TextButton(onPressed: abrir, child: const Text('Probar', style: TextStyle(fontSize: 12)));
            }
            return OutlinedButton.icon(
              onPressed: abrir,
              icon: const Icon(Icons.accessibility_new_outlined),
              label: const Text('Probar en el probador virtual'),
            );
          },
          orElse: () => const SizedBox.shrink(),
        );
  }
}
