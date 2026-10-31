import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../features/auth/state/auth_controller.dart';
import '../../features/tienda/state/tienda_controller.dart';
import 'contador_pendientes.dart';

Future<int> _pendientes(WidgetRef ref) async {
  final usuario = ref.read(authControllerProvider).usuario;
  if (usuario == null) return 0;
  return ref.read(contadorPendientesProvider).pendientesDe(empresaId: usuario.empresaId, usuarioId: usuario.id);
}

String _avisoDePendientes(int pendientes) {
  final operaciones = pendientes == 1 ? '1 operación sin enviar' : '$pendientes operaciones sin enviar';
  return 'Tienes $operaciones. No se pierden, pero tendrás que ingresar de nuevo para enviarlas.';
}

Future<bool> _confirmar(
  BuildContext context, {
  required String titulo,
  required String texto,
  required String accion,
}) async {
  final confirmado = await showDialog<bool>(
    context: context,
    builder: (contexto) => AlertDialog(
      title: Text(titulo),
      content: Text(texto),
      actions: [
        TextButton(onPressed: () => Navigator.pop(contexto, false), child: const Text('Cancelar')),
        TextButton(onPressed: () => Navigator.pop(contexto, true), child: Text(accion)),
      ],
    ),
  );
  return confirmado ?? false;
}

/// Cierra la sesión. Si hay operaciones sin enviar avisa y pide confirmar; si no, cierra sin preguntar (para el cliente
/// se ve igual que antes).
Future<void> cerrarSesionConAviso(BuildContext context, WidgetRef ref) async {
  if (!ref.read(authControllerProvider).estaAutenticado) return;
  final pendientes = await _pendientes(ref);
  if (pendientes > 0) {
    if (!context.mounted) return;
    final confirmado = await _confirmar(
      context,
      titulo: 'Cerrar sesión',
      texto: _avisoDePendientes(pendientes),
      accion: 'Cerrar sesión',
    );
    if (!confirmado) return;
  }
  await ref.read(authControllerProvider.notifier).logout();
}

/// Lleva a "Elige tu tienda". Con sesión abierta pide confirmar primero, porque cambiar de tienda cierra la sesión
/// (la cuenta pertenece a una sola tienda). Sin sesión va directo. La pantalla de tiendas se apila encima: la flecha
/// de volver sirve si la persona se arrepiente.
Future<void> cambiarDeTiendaConAviso(BuildContext context, WidgetRef ref) async {
  if (ref.read(authControllerProvider).estaAutenticado) {
    final pendientes = await _pendientes(ref);
    if (!context.mounted) return;
    final nombre = ref.read(tiendaActualProvider)?.nombre ?? 'esta tienda';
    final confirmado = await _confirmar(
      context,
      titulo: 'Cambiar de tienda',
      texto: 'Se cerrará tu sesión en $nombre.${pendientes > 0 ? '\n\n${_avisoDePendientes(pendientes)}' : ''}',
      accion: 'Cambiar de tienda',
    );
    if (!confirmado) return;
    await ref.read(authControllerProvider.notifier).logout();
  }
  if (!context.mounted) return;
  context.push('/tienda');
}
