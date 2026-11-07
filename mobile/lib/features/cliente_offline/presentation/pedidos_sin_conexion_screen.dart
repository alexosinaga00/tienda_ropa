import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/utils/dinero.dart';
import '../../../core/utils/fecha_servidor.dart';
import '../../notificaciones/models/notificacion_app.dart';
import '../../notificaciones/models/ruta_notificacion.dart';
import '../../notificaciones/state/notificaciones_controller.dart';
import '../models/pedido_sin_conexion.dart';
import '../state/cliente_offline_providers.dart';
import '../state/cola_pedidos.dart';
import 'aviso_sin_conexion_cliente.dart';
import 'checkout_sin_conexion_screen.dart' show MiniaturaPrenda;

/// El tipo de notificación del servidor para estos pedidos.
const tipoNotificacionPedido = 'pedido_diferido';

const _colorEstado = {
  EstadoPedidoLocal.pendiente: AppColors.advertencia,
  EstadoPedidoLocal.enviando: AppColors.advertencia,
  EstadoPedidoLocal.cobrado: AppColors.exito,
  EstadoPedidoLocal.rechazado: AppColors.error,
  EstadoPedidoLocal.vencido: AppColors.error,
};

/// Pedidos sin conexión: lo que el cliente pidió sin red y paga con su PayPal guardado. Cada pedido está Pendiente de envío,
/// Enviando, Cobrado (con enlace a la compra), Rechazado (con el motivo en palabras) o Vencido. Un pedido que todavía no
/// salió, o que venció, se puede descartar. Debajo, los avisos que el servidor guardó de tipo `pedido_diferido`.
class PedidosSinConexionScreen extends ConsumerStatefulWidget {
  const PedidosSinConexionScreen({super.key});

  @override
  ConsumerState<PedidosSinConexionScreen> createState() => _PedidosSinConexionScreenState();
}

class _PedidosSinConexionScreenState extends ConsumerState<PedidosSinConexionScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return;
      // Verlos aquí es "haberlos visto": el contador de resultados nuevos baja a cero.
      await ref.read(colaPedidosProvider).marcarVistos();
      // En silencio: si no hay conexión o el servidor no responde, simplemente no se actualizan los avisos.
      if (mounted && enLineaAhora(ref)) await ref.read(notificacionesProvider.notifier).refrescar();
    });
  }

  Future<void> _descartar(PedidoSinConexion pedido) async {
    final yaIntento = pedido.estado == EstadoPedidoLocal.pendiente && pedido.intentos > 0;
    final confirmado = await showDialog<bool>(
      context: context,
      builder: (contexto) => AlertDialog(
        title: const Text('¿Descartar este pedido?'),
        content: Text(
          yaIntento ? 'Ya intentamos enviarlo; si llegó a cobrarse, lo verás en Mis compras.' : 'No se cobrará nada.',
        ),
        actions: [
          TextButton(
            key: const Key('descartar-no'),
            onPressed: () => Navigator.pop(contexto, false),
            child: const Text('Cancelar'),
          ),
          TextButton(
            key: const Key('descartar-si'),
            onPressed: () => Navigator.pop(contexto, true),
            child: const Text('Sí, descartar'),
          ),
        ],
      ),
    );
    if (confirmado != true || !mounted) return;
    await ref.read(colaPedidosProvider).descartar(pedido.operacionId);
  }

  @override
  Widget build(BuildContext context) {
    final asyncPedidos = ref.watch(pedidosSinConexionProvider);
    final estadoCola = ref.watch(estadoColaProvider).valueOrNull ?? const EstadoCola();
    final avisos = [
      for (final n in ref.watch(notificacionesProvider).valueOrNull ?? const <NotificacionApp>[])
        if (n.tipo == tipoNotificacionPedido) n,
    ];
    final pedidos = asyncPedidos.valueOrNull ?? const <PedidoSinConexion>[];
    final haySinEnviar = pedidos.any((p) => p.estado.sinEnviar);

    return Scaffold(
      backgroundColor: AppColors.fondo,
      appBar: AppBar(
        title: const Text('Pedidos sin conexión'),
        actions: [
          if (haySinEnviar)
            TextButton(
              key: const Key('enviar-ahora'),
              onPressed: () => ref.read(colaPedidosProvider).enviarAhora(),
              child: const Text('Enviar ahora'),
            ),
        ],
      ),
      body: Column(
        children: [
          const AvisoSinConexionCliente(),
          _AvisoCola(estado: estadoCola),
          Expanded(
            child: asyncPedidos.when(
              loading: () => const Center(child: CircularProgressIndicator(color: AppColors.acento)),
              error: (e, s) => const Center(child: Text('No se pudieron leer tus pedidos.')),
              data: (lista) => ListView(
                padding: const EdgeInsets.all(AppSpacing.md),
                children: [
                  if (lista.isEmpty)
                    const _SinPedidos()
                  else
                    for (final pedido in lista) _TarjetaPedido(pedido: pedido, onDescartar: () => _descartar(pedido)),
                  if (avisos.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.lg),
                    const Text('Avisos', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                    const SizedBox(height: AppSpacing.sm),
                    for (final aviso in avisos) _TarjetaAviso(aviso: aviso),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Lo que dice la cola cuando está esperando, pausada o detenida.
class _AvisoCola extends ConsumerWidget {
  const _AvisoCola({required this.estado});

  final EstadoCola estado;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final (texto, icono, conBoton) = switch (estado.fase) {
      FaseCola.sinConexion => (
        'Sin conexión: tus pedidos salen solos y se cobran de tu PayPal cuando vuelva la conexión.',
        Icons.cloud_off,
        false,
      ),
      FaseCola.esperandoReintento => (
        'El servidor no respondió. Lo intentaremos otra vez en un momento; tu pedido sigue guardado.',
        Icons.schedule,
        true,
      ),
      FaseCola.pausadaSesion => (
        estado.motivoPausa ?? 'Inicia sesión para enviar tu pedido.',
        Icons.lock_outline,
        false,
      ),
      FaseCola.pausada ||
      FaseCola.detenidaPorFallos => (estado.motivoPausa ?? 'Tu pedido está en pausa.', Icons.error_outline, true),
      FaseCola.inactiva || FaseCola.sincronizando => ('', Icons.info_outline, false),
    };
    if (texto.isEmpty) return const SizedBox.shrink();
    final esError =
        estado.fase == FaseCola.pausada ||
        estado.fase == FaseCola.pausadaSesion ||
        estado.fase == FaseCola.detenidaPorFallos;
    final color = esError ? AppColors.error : AppColors.advertencia;
    return Container(
      key: Key('aviso-cola-${estado.fase.name}'),
      width: double.infinity,
      color: color.withValues(alpha: 0.1),
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.sm),
      child: Row(
        children: [
          Icon(icono, color: color, size: 20),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(texto, style: TextStyle(color: color, fontSize: 13)),
          ),
          if (conBoton)
            TextButton(
              key: const Key('reintentar-ahora'),
              onPressed: () => ref.read(colaPedidosProvider).enviarAhora(),
              child: Text(estado.fase == FaseCola.esperandoReintento ? 'Reintentar ahora' : 'Reintentar'),
            ),
        ],
      ),
    );
  }
}

class _SinPedidos extends StatelessWidget {
  const _SinPedidos();

  @override
  Widget build(BuildContext context) {
    return const Padding(
      key: Key('sin-pedidos'),
      padding: EdgeInsets.all(AppSpacing.xl),
      child: Column(
        children: [
          Icon(Icons.schedule, size: 40, color: AppColors.textoTenue),
          SizedBox(height: AppSpacing.md),
          Text('No tienes pedidos hechos sin conexión.', textAlign: TextAlign.center),
          SizedBox(height: AppSpacing.sm),
          Text(
            'Si te quedas sin internet, agrega prendas a tu carrito y págalas con tu PayPal guardado: '
            'se cobran solas cuando vuelva la conexión.',
            textAlign: TextAlign.center,
            style: TextStyle(color: AppColors.textoTenue),
          ),
        ],
      ),
    );
  }
}

class _TarjetaPedido extends StatelessWidget {
  const _TarjetaPedido({required this.pedido, required this.onDescartar});

  final PedidoSinConexion pedido;
  final VoidCallback onDescartar;

  @override
  Widget build(BuildContext context) {
    final estado = pedido.estado;
    final color = _colorEstado[estado]!;
    final prendas = pedido.cantidadPrendas;
    final total = estado == EstadoPedidoLocal.cobrado && pedido.totalCentavos != null
        ? formatearBs(pedido.totalCentavos!)
        : 'Hasta ${formatearBs(pedido.totalMaximoCentavos)}';
    final puedeDescartar = estado == EstadoPedidoLocal.pendiente || estado == EstadoPedidoLocal.vencido;
    final mensaje = pedido.mensaje;

    return Card(
      key: Key('pedido-${estado.name}'),
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        pedido.codigoVenta ?? 'Pedido del ${formatearFechaHora(pedido.creadoEn.toLocal())}',
                        style: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                      Text(
                        '$prendas ${prendas == 1 ? 'prenda' : 'prendas'} · Retiro en ${pedido.sucursalNombre}',
                        style: const TextStyle(color: AppColors.textoTenue, fontSize: 13),
                      ),
                    ],
                  ),
                ),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Chip(
                      key: const Key('chip-estado'),
                      label: Text(estado.etiqueta, style: TextStyle(fontSize: 12, color: color)),
                      backgroundColor: AppColors.fondoAlterno,
                      visualDensity: VisualDensity.compact,
                    ),
                    Text(total, style: const TextStyle(fontWeight: FontWeight.w600)),
                  ],
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            for (final linea in pedido.lineas)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.xs),
                child: Row(
                  children: [
                    MiniaturaPrenda(url: linea.imagen, tamano: 36),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Text(
                        '${linea.cantidad} × ${linea.productoNombre}${linea.detalle.isEmpty ? '' : ' · ${linea.detalle}'}',
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
              ),
            if (estado == EstadoPedidoLocal.rechazado)
              _Nota(
                clave: const Key('mensaje-rechazo'),
                texto: mensaje ?? 'No pudimos cobrar este pedido. No se cobró nada.',
                color: AppColors.error,
              ),
            if (estado == EstadoPedidoLocal.vencido)
              _Nota(
                clave: const Key('mensaje-vencido'),
                texto: '${mensaje ?? 'Venció'}. No se cobró nada: puedes descartarlo.',
                color: AppColors.error,
              ),
            if (estado == EstadoPedidoLocal.cobrado && mensaje != null && mensaje.isNotEmpty)
              _Nota(clave: const Key('mensaje-cobrado'), texto: mensaje, color: AppColors.textoTenue),
            if (estado == EstadoPedidoLocal.pendiente && pedido.ultimoError != null)
              const _Nota(
                clave: Key('nota-reintento'),
                texto: 'Todavía no pudimos enviarlo; lo intentaremos de nuevo.',
                color: AppColors.textoTenue,
              ),
            Wrap(
              spacing: AppSpacing.sm,
              children: [
                if (estado == EstadoPedidoLocal.cobrado && pedido.ventaId != null)
                  TextButton(
                    key: const Key('ver-compra'),
                    onPressed: () => context.push('/compras/${pedido.ventaId}'),
                    child: const Text('Ver mi compra'),
                  ),
                if (puedeDescartar)
                  TextButton.icon(
                    key: const Key('descartar-pedido'),
                    onPressed: onDescartar,
                    icon: const Icon(Icons.delete_outline, size: 20),
                    label: const Text('Descartar'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Nota extends StatelessWidget {
  const _Nota({required this.clave, required this.texto, required this.color});

  final Key clave;
  final String texto;
  final Color color;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: AppSpacing.xs),
    child: Text(
      texto,
      key: clave,
      style: TextStyle(color: color, fontSize: 13),
    ),
  );
}

class _TarjetaAviso extends ConsumerWidget {
  const _TarjetaAviso({required this.aviso});

  final NotificacionApp aviso;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ruta = rutaDeNotificacion(aviso);
    return Card(
      key: Key('aviso-${aviso.id}'),
      color: aviso.leida ? null : AppColors.fondoAlterno,
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: ListTile(
        onTap: ruta == null ? null : () => context.push(ruta),
        leading: const Icon(Icons.notifications_none),
        title: Text(aviso.titulo, style: TextStyle(fontWeight: aviso.leida ? FontWeight.w400 : FontWeight.w700)),
        subtitle: Text(
          [
            if (aviso.mensaje != null && aviso.mensaje!.isNotEmpty) aviso.mensaje!,
            tiempoRelativo(aviso.creadoEn),
          ].join('\n'),
        ),
        isThreeLine: aviso.mensaje != null && aviso.mensaje!.isNotEmpty,
        trailing: aviso.leida
            ? null
            : TextButton(
                key: Key('marcar-leida-${aviso.id}'),
                onPressed: () => ref.read(notificacionesProvider.notifier).marcarLeida(aviso.id),
                child: const Text('Marcar leído'),
              ),
      ),
    );
  }
}
