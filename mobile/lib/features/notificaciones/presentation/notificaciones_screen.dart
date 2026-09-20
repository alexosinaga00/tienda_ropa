import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/app_theme.dart';
import '../../reservas/models/notificacion_app.dart';
import '../models/ruta_notificacion.dart';
import '../state/notificaciones_controller.dart';

/// Todas las notificaciones del cliente, las más nuevas primero. Al tocar una se marca como leída y, si su tipo
/// tiene pantalla (reserva, compra), se abre.
class NotificacionesScreen extends ConsumerStatefulWidget {
  const NotificacionesScreen({super.key});

  @override
  ConsumerState<NotificacionesScreen> createState() => _NotificacionesScreenState();
}

class _NotificacionesScreenState extends ConsumerState<NotificacionesScreen> {
  @override
  void initState() {
    super.initState();
    // Al abrir la lista se pide de nuevo: puede haber algo más nuevo que lo que mostraba la campana.
    Future.microtask(() => ref.read(notificacionesProvider.notifier).refrescar());
  }

  void _abrir(NotificacionApp notificacion) {
    if (!notificacion.leida) ref.read(notificacionesProvider.notifier).marcarLeida(notificacion.id);
    final ruta = rutaDeNotificacion(notificacion);
    if (ruta != null) context.push(ruta);
  }

  @override
  Widget build(BuildContext context) {
    final asyncNotificaciones = ref.watch(notificacionesProvider);
    final hayNoLeidas = ref.watch(notificacionesNoLeidasProvider) > 0;

    return Scaffold(
      backgroundColor: AppColors.fondo,
      appBar: AppBar(
        title: const Text('Notificaciones'),
        actions: [
          if (hayNoLeidas)
            IconButton(
              icon: const Icon(Icons.done_all),
              tooltip: 'Marcar todas como leídas',
              onPressed: () => ref.read(notificacionesProvider.notifier).marcarTodasLeidas(),
            ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => ref.read(notificacionesProvider.notifier).refrescar(),
        child: asyncNotificaciones.when(
          loading: () => const Center(child: CircularProgressIndicator(color: AppColors.acento)),
          error: (error, stack) => _MensajeVacio('No se pudieron cargar tus notificaciones.', icono: Icons.cloud_off),
          data: (notificaciones) {
            if (notificaciones.isEmpty) {
              return _MensajeVacio('No tienes notificaciones', icono: Icons.notifications_none);
            }
            return ListView.separated(
              physics: const AlwaysScrollableScrollPhysics(),
              itemCount: notificaciones.length,
              separatorBuilder: (context, index) => const Divider(height: 1, color: AppColors.borde),
              itemBuilder: (context, index) {
                final notificacion = notificaciones[index];
                return _FilaNotificacion(notificacion: notificacion, onTap: () => _abrir(notificacion));
              },
            );
          },
        ),
      ),
    );
  }
}

class _FilaNotificacion extends StatelessWidget {
  const _FilaNotificacion({required this.notificacion, required this.onTap});

  final NotificacionApp notificacion;
  final VoidCallback onTap;

  static IconData _icono(String? tipo) => switch (tipo) {
    'reserva_preparada' => Icons.event_available_outlined,
    'envio' => Icons.local_shipping_outlined,
    _ => Icons.notifications_none,
  };

  @override
  Widget build(BuildContext context) {
    final sinLeer = !notificacion.leida;
    final mensaje = notificacion.mensaje;
    return ListTile(
      onTap: onTap,
      tileColor: sinLeer ? AppColors.acento.withValues(alpha: 0.06) : null,
      leading: Icon(_icono(notificacion.tipo), color: sinLeer ? AppColors.acento : AppColors.textoTenue),
      title: Text(
        notificacion.titulo,
        style: TextStyle(fontWeight: sinLeer ? FontWeight.w700 : FontWeight.w400),
      ),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (mensaje != null && mensaje.isNotEmpty) Text(mensaje),
          const SizedBox(height: AppSpacing.xs),
          Text(
            tiempoRelativo(notificacion.creadoEn),
            style: const TextStyle(fontSize: 12, color: AppColors.textoTenue),
          ),
        ],
      ),
      trailing: sinLeer
          ? const Icon(Icons.circle, size: 10, color: AppColors.error, semanticLabel: 'Sin leer')
          : null,
    );
  }
}

/// Es un ListView (y no un Center suelto) para que también se pueda deslizar y actualizar cuando no hay nada.
class _MensajeVacio extends StatelessWidget {
  const _MensajeVacio(this.texto, {required this.icono});

  final String texto;
  final IconData icono;

  @override
  Widget build(BuildContext context) {
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(AppSpacing.xl),
      children: [
        const SizedBox(height: AppSpacing.xxl),
        Icon(icono, size: 48, color: AppColors.textoTenue),
        const SizedBox(height: AppSpacing.md),
        Text(texto, textAlign: TextAlign.center, style: const TextStyle(color: AppColors.textoTenue)),
      ],
    );
  }
}
