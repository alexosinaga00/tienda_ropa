import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/app_theme.dart';
import '../../notificaciones/state/notificaciones_controller.dart';
import '../models/reserva.dart';
import '../state/reservas_providers.dart';

class MisReservasScreen extends ConsumerWidget {
  const MisReservasScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncReservas = ref.watch(misReservasControllerProvider);

    return Scaffold(
      backgroundColor: AppColors.fondo,
      appBar: AppBar(title: const Text('Mis reservas')),
      body: RefreshIndicator(
        onRefresh: () => ref.read(misReservasControllerProvider.notifier).cargar(),
        child: asyncReservas.when(
          loading: () => const Center(child: CircularProgressIndicator(color: AppColors.acento)),
          error: (error, stack) => ListView(
            children: const [
              Padding(
                padding: EdgeInsets.all(AppSpacing.xl),
                child: Text('No se pudieron cargar tus reservas.', textAlign: TextAlign.center),
              ),
            ],
          ),
          data: (reservas) {
            if (reservas.isEmpty) {
              return ListView(
                children: const [
                  Padding(
                    padding: EdgeInsets.all(AppSpacing.xl),
                    child: Text(
                      'Todavía no hiciste ninguna reserva.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: AppColors.textoTenue),
                    ),
                  ),
                ],
              );
            }
            return ListView(
              padding: const EdgeInsets.all(AppSpacing.md),
              children: [
                const _BannerNotificaciones(),
                for (final reserva in reservas) _TarjetaReserva(reserva: reserva),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _BannerNotificaciones extends ConsumerWidget {
  const _BannerNotificaciones();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncNotificaciones = ref.watch(notificacionesProvider);
    return asyncNotificaciones.maybeWhen(
      data: (notificaciones) {
        final pendientes = notificaciones
            .where((n) => n.tipo == 'reserva_preparada' && !n.leida)
            .toList();
        if (pendientes.isEmpty) return const SizedBox.shrink();
        return Column(
          children: [
            for (final notificacion in pendientes)
              Container(
                margin: const EdgeInsets.only(bottom: AppSpacing.sm),
                padding: const EdgeInsets.all(AppSpacing.md),
                decoration: BoxDecoration(
                  color: AppColors.acento.withValues(alpha: 0.08),
                  borderRadius: BorderRadius.circular(AppRadius.base),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.notifications_active, color: AppColors.acento),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(notificacion.titulo, style: const TextStyle(fontWeight: FontWeight.w600)),
                          if (notificacion.mensaje != null) Text(notificacion.mensaje!),
                        ],
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.close, size: 18),
                      onPressed: () => ref.read(notificacionesProvider.notifier).marcarLeida(notificacion.id),
                    ),
                  ],
                ),
              ),
          ],
        );
      },
      orElse: () => const SizedBox.shrink(),
    );
  }
}

class _TarjetaReserva extends ConsumerWidget {
  const _TarjetaReserva({required this.reserva});

  final Reserva reserva;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: ListTile(
        onTap: () => context.push('/reserva/${reserva.id}'),
        title: Text(reserva.codigo),
        subtitle: Text('${reserva.fechaVisita} · ${reserva.horaVisitaDesde.substring(0, 5)} - ${reserva.horaVisitaHasta.substring(0, 5)}'),
        trailing: Chip(
          label: Text(etiquetasEstadoReserva[reserva.estado] ?? reserva.estado, style: const TextStyle(fontSize: 12)),
        ),
      ),
    );
  }
}
