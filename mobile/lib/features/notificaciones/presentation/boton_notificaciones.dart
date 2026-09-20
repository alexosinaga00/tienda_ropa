import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../state/notificaciones_controller.dart';

/// La campana de la barra del catálogo, con el número de notificaciones sin leer. Solo se muestra con sesión (lo decide
/// quien la pone). Al aparecer vuelve a pedir la lista, así el número está al día cada vez que se llega al catálogo.
class BotonNotificaciones extends ConsumerStatefulWidget {
  const BotonNotificaciones({super.key});

  @override
  ConsumerState<BotonNotificaciones> createState() => _BotonNotificacionesState();
}

class _BotonNotificacionesState extends ConsumerState<BotonNotificaciones> {
  @override
  void initState() {
    super.initState();
    Future.microtask(() => ref.read(notificacionesProvider.notifier).refrescar());
  }

  @override
  Widget build(BuildContext context) {
    final noLeidas = ref.watch(notificacionesNoLeidasProvider);
    return IconButton(
      tooltip: 'Notificaciones',
      icon: Badge(
        label: Text(noLeidas > 99 ? '99+' : '$noLeidas'),
        isLabelVisible: noLeidas > 0,
        child: const Icon(Icons.notifications_outlined),
      ),
      onPressed: () => context.push('/notificaciones'),
    );
  }
}
