import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_theme.dart';
import '../models/sucursal_local.dart';
import '../state/catalogo_local_providers.dart';
import '../state/descarga_controller.dart';

String _nombre(SucursalLocal s) => s.esDeposito ? '${s.nombre} (depósito)' : s.nombre;

/// La sucursal con la que trabaja la persona. Con varias autorizadas es un menú para cambiarla (al elegir, se guarda y, si esa
/// sucursal nunca se descargó y hay conexión, se descarga); con una sola solo muestra su nombre.
class SelectorSucursalActiva extends ConsumerWidget {
  const SelectorSucursalActiva({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sucursales = ref.watch(sucursalesAutorizadasProvider).valueOrNull ?? const <SucursalLocal>[];
    final activaId = ref.watch(sucursalActivaProvider).valueOrNull;
    final activa = sucursales.where((s) => s.id == activaId).firstOrNull;

    if (sucursales.isEmpty || activa == null) return const _Etiqueta('Sin sucursal');
    if (sucursales.length == 1) return _Etiqueta(_nombre(activa));

    return PopupMenuButton<int>(
      tooltip: 'Cambiar de sucursal',
      initialValue: activa.id,
      onSelected: (id) {
        if (id != activa.id) ref.read(descargaControllerProvider.notifier).alCambiarSucursal(id);
      },
      itemBuilder: (context) => [
        for (final s in sucursales)
          PopupMenuItem<int>(
            value: s.id,
            child: Row(
              children: [
                Icon(s.id == activa.id ? Icons.check : Icons.store_outlined, size: 20, color: AppColors.texto),
                const SizedBox(width: AppSpacing.sm),
                Flexible(child: Text(_nombre(s), overflow: TextOverflow.ellipsis)),
              ],
            ),
          ),
      ],
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 48),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.store_outlined, size: 20, color: AppColors.texto),
              const SizedBox(width: AppSpacing.xs),
              Flexible(
                child: Text(
                  _nombre(activa),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: AppColors.texto, fontSize: 14, fontWeight: FontWeight.w500),
                ),
              ),
              const Icon(Icons.arrow_drop_down, size: 24, color: AppColors.texto),
            ],
          ),
        ),
      ),
    );
  }
}

class _Etiqueta extends StatelessWidget {
  const _Etiqueta(this.texto);

  final String texto;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.store_outlined, size: 20, color: AppColors.textoTenue),
          const SizedBox(width: AppSpacing.xs),
          Flexible(
            child: Text(
              texto,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: AppColors.textoTenue, fontSize: 14),
            ),
          ),
        ],
      ),
    );
  }
}
