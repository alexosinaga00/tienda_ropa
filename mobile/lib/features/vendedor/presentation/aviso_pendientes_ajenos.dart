import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../state/pendientes_providers.dart';

/// El texto de la franja: singular con una sola operación.
String textoPendientesAjenos(int pendientes) {
  final operaciones = pendientes == 1 ? '1 operación pendiente' : '$pendientes operaciones pendientes';
  return 'Hay $operaciones de otro usuario. Ingresa con esa cuenta para enviarlas.';
}

/// Franja ámbar que avisa que en este teléfono quedaron operaciones sin enviar de OTRA cuenta de la misma tienda. No se
/// muestra si no hay ninguna (ni mientras se calcula o si falla el cálculo).
class AvisoPendientesAjenos extends ConsumerWidget {
  const AvisoPendientesAjenos({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final pendientes = ref.watch(pendientesAjenosProvider).valueOrNull ?? 0;
    if (pendientes <= 0) return const SizedBox.shrink();
    return Semantics(
      container: true,
      liveRegion: true,
      child: Container(
        width: double.infinity,
        color: const Color(0xFFFFF3CD),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Row(
          children: [
            const Icon(Icons.info_outline, size: 22, color: Color(0xFF7A4A00)),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                textoPendientesAjenos(pendientes),
                style: const TextStyle(fontSize: 14, color: Color(0xFF5C3A00)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
