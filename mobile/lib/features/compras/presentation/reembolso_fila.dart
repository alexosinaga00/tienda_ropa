import 'package:flutter/material.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/fecha_servidor.dart';
import '../models/reembolso.dart';

/// Un reembolso dicho para el cliente: cuánto, cómo vuelve el dinero, cuándo y en qué punto va ("Reembolsado" o "En
/// proceso"). Un reembolso fallido se ve como "En proceso": el detalle técnico nunca se muestra.
class FilaReembolso extends StatelessWidget {
  const FilaReembolso({required this.reembolso, super.key});

  final Reembolso reembolso;

  @override
  Widget build(BuildContext context) {
    final listo = reembolso.estaReembolsado;
    final color = listo ? AppColors.exito : AppColors.advertencia;
    final como = reembolso.comoSeDevuelve;
    final fecha = formatearFechaHora(reembolso.fecha);
    return Padding(
      padding: const EdgeInsets.only(top: AppSpacing.xs),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(listo ? Icons.check_circle_outline : Icons.hourglass_empty, color: color, size: 22),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  reembolso.montoTexto,
                  key: Key('reembolso-monto-${reembolso.id}'),
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
                Text(
                  listo ? 'Te lo devolvimos $como' : 'Te lo devolveremos $como',
                  key: Key('reembolso-como-${reembolso.id}'),
                  style: const TextStyle(fontSize: 13),
                ),
                Text(
                  listo ? 'Devuelto el $fecha' : 'Pedido el $fecha',
                  key: Key('reembolso-fecha-${reembolso.id}'),
                  style: const TextStyle(color: AppColors.textoTenue, fontSize: 13),
                ),
              ],
            ),
          ),
          Text(
            reembolso.etiquetaEstado,
            key: Key('reembolso-estado-${reembolso.id}'),
            style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }
}
