import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../features/auth/models/usuario.dart';
import '../../features/auth/state/auth_controller.dart';
import '../../features/cliente_offline/presentation/dialogo_salida_pedidos.dart';
import '../../features/cliente_offline/state/cliente_offline_providers.dart';
import '../../features/tienda/state/tienda_controller.dart';
import 'contador_pendientes.dart';

Future<int> _pendientes(WidgetRef ref) async {
  final usuario = ref.read(authControllerProvider).usuario;
  // Solo el personal tiene base local del personal: a un cliente no se le abre sin necesidad.
  if (usuario == null || usuario.modo != ModoApp.vendedor) return 0;
  return ref.read(contadorPendientesProvider).pendientesDe(empresaId: usuario.empresaId, usuarioId: usuario.id);
}

/// Cuántos pedidos hechos sin conexión de este CLIENTE siguen sin enviar. Los vencidos y los resueltos no cuentan. 0 si no
/// es un cliente o ante cualquier problema con la base local.
Future<int> _pedidosSinEnviar(WidgetRef ref) async {
  final usuario = ref.read(authControllerProvider).usuario;
  if (usuario == null || usuario.modo != ModoApp.cliente) return 0;
  return ref.read(colaPedidosProvider).contarSinEnviar();
}

/// Si hay pedidos sin enviar, pregunta qué hacer con ellos. Devuelve false si la persona se arrepiente (no se sale). Con
/// "Borrarlos y salir" los borra del teléfono ANTES de que el llamador cierre la sesión.
Future<bool> _resolverPedidosAlSalir(BuildContext context, WidgetRef ref, int pedidos, {String? aviso}) async {
  final opcion = await mostrarDialogoSalidaPedidos(context, pedidos, aviso: aviso);
  if (opcion == null) return false;
  if (opcion == OpcionSalidaPedidos.borrar) await ref.read(colaPedidosProvider).borrarTodoDeEstaCuenta();
  return true;
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

/// Cierra la sesión. Si hay operaciones sin enviar (del personal) o pedidos sin enviar (de un cliente) avisa y pide decidir;
/// si no, cierra sin preguntar. Un cierre FORZADO (la sesión venció) no pasa por aquí: conserva todo sin preguntar.
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
  final pedidos = await _pedidosSinEnviar(ref);
  if (pedidos > 0) {
    if (!context.mounted) return;
    if (!await _resolverPedidosAlSalir(context, ref, pedidos)) return;
  }
  await ref.read(authControllerProvider.notifier).logout();
}

/// Lleva a "Elige tu tienda". Con sesión abierta pide confirmar primero, porque cambiar de tienda cierra la sesión
/// (la cuenta pertenece a una sola tienda). Sin sesión va directo. La pantalla de tiendas se apila encima: la flecha
/// de volver sirve si la persona se arrepiente.
Future<void> cambiarDeTiendaConAviso(BuildContext context, WidgetRef ref) async {
  if (ref.read(authControllerProvider).estaAutenticado) {
    final pendientes = await _pendientes(ref);
    final pedidos = await _pedidosSinEnviar(ref);
    if (!context.mounted) return;
    final nombre = ref.read(tiendaActualProvider)?.nombre ?? 'esta tienda';
    if (pedidos > 0) {
      // Un cliente con pedidos sin enviar: el aviso de salir ya explica que cambiar de tienda cierra la sesión.
      if (!await _resolverPedidosAlSalir(context, ref, pedidos, aviso: 'Se cerrará tu sesión en $nombre.')) return;
    } else {
      final confirmado = await _confirmar(
        context,
        titulo: 'Cambiar de tienda',
        texto: 'Se cerrará tu sesión en $nombre.${pendientes > 0 ? '\n\n${_avisoDePendientes(pendientes)}' : ''}',
        accion: 'Cambiar de tienda',
      );
      if (!confirmado) return;
    }
    await ref.read(authControllerProvider.notifier).logout();
  }
  if (!context.mounted) return;
  context.push('/tienda');
}
