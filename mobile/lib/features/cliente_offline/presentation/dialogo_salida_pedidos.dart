import 'package:flutter/material.dart';

/// Qué elige el cliente al salir con pedidos sin enviar.
enum OpcionSalidaPedidos {
  /// Salir dejando los pedidos: se envían cuando la misma cuenta vuelva a entrar.
  conservar,

  /// Salir y borrar del teléfono los pedidos sin enviar, el carrito local y lo recordado.
  borrar,
}

/// "Tienes 1 pedido sin enviar" / "Tienes 3 pedidos sin enviar".
String tituloPedidosSinEnviar(int cantidad) =>
    'Tienes $cantidad ${cantidad == 1 ? 'pedido sin enviar' : 'pedidos sin enviar'}';

/// El aviso al salir (cerrar sesión o cambiar de tienda) cuando hay pedidos hechos sin conexión que todavía no salieron.
/// "Conservarlos" es lo predeterminado. Devuelve null si el cliente se arrepiente (Cancelar o tocar fuera): entonces no se
/// sale.
Future<OpcionSalidaPedidos?> mostrarDialogoSalidaPedidos(BuildContext context, int cantidad, {String? aviso}) {
  return showDialog<OpcionSalidaPedidos>(
    context: context,
    builder: (contexto) => AlertDialog(
      key: const Key('dialogo-salida-pedidos'),
      title: Text(tituloPedidosSinEnviar(cantidad)),
      content: Text(
        '${aviso == null ? '' : '$aviso\n\n'}'
        'Si los conservas, se envían y se cobran de tu PayPal cuando vuelvas a entrar con esta misma cuenta y haya '
        'conexión. Si los borras, no se cobrará nada y tendrás que armarlos de nuevo.',
      ),
      actions: [
        TextButton(
          key: const Key('cancelar-salida'),
          onPressed: () => Navigator.pop(contexto),
          child: const Text('Cancelar'),
        ),
        TextButton(
          key: const Key('borrar-pedidos'),
          onPressed: () => Navigator.pop(contexto, OpcionSalidaPedidos.borrar),
          child: const Text('Borrarlos y salir'),
        ),
        FilledButton(
          key: const Key('conservar-pedidos'),
          autofocus: true,
          onPressed: () => Navigator.pop(contexto, OpcionSalidaPedidos.conservar),
          child: const Text('Conservarlos'),
        ),
      ],
    ),
  );
}
