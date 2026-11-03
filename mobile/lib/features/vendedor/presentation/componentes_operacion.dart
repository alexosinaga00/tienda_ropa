import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/utils/dinero.dart';
import '../models/cliente_local.dart';
import '../models/sucursal_local.dart';
import '../state/carrito_operacion.dart';
import '../state/catalogo_local_providers.dart';
import '../state/descarga_controller.dart';
import 'catalogo_local_screen.dart' show FotoPrenda;

// El aviso de bloqueo del servidor es UNO solo para todas las pantallas del personal (vive en su propio archivo).
export 'aviso_bloqueo_sync.dart' show AvisoBloqueoSync;

/// Piezas que comparten "Nueva venta" y "Nueva reserva".

const textoAyudaGuardado = 'Se guardará en tu teléfono y se enviará cuando haya conexión. El servidor la confirmará.';

/// Un bloque de la pantalla: título y contenido sobre una tarjeta con borde.
class SeccionOperacion extends StatelessWidget {
  const SeccionOperacion({super.key, required this.titulo, required this.child});

  final String titulo;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: AppSpacing.md),
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.fondo,
        border: Border.all(color: AppColors.borde),
        borderRadius: BorderRadius.circular(AppRadius.base),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Semantics(
            header: true,
            child: Text(
              titulo,
              style: Theme.of(context).textTheme.titleMedium?.copyWith(color: AppColors.texto, fontWeight: FontWeight.w600),
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          child,
        ],
      ),
    );
  }
}

/// Un aviso de color con ícono y texto (nunca solo color).
class AvisoOperacion extends StatelessWidget {
  const AvisoOperacion({super.key, required this.texto, this.color = AppColors.advertencia, this.icono = Icons.info_outline});

  final String texto;
  final Color color;
  final IconData icono;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      container: true,
      liveRegion: true,
      child: Container(
        width: double.infinity,
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.08),
          border: Border(left: BorderSide(color: color, width: 4)),
        ),
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.sm),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Icon(icono, size: 20, color: color),
            ),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: Text(texto, style: TextStyle(color: color, fontSize: 14, fontWeight: FontWeight.w500)),
            ),
          ],
        ),
      ),
    );
  }
}

/// Cuando no hay sucursal con datos descargados no se puede armar nada: se invita a descargar el catálogo.
class EstadoSinCatalogoOperacion extends ConsumerWidget {
  const EstadoSinCatalogoOperacion({super.key, required this.alVolver});

  final VoidCallback alVolver;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final descargando = ref.watch(descargaControllerProvider.select((s) => s.descargando));
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_download_outlined, size: 48, color: AppColors.textoTenue),
            const SizedBox(height: AppSpacing.md),
            Text(
              'Aún no descargaste el catálogo',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyLarge,
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              'Descárgalo con conexión para poder registrar sin conexión.',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: AppSpacing.lg),
            ElevatedButton(
              style: ElevatedButton.styleFrom(minimumSize: const Size(200, 52)),
              onPressed: descargando ? null : () => ref.read(descargaControllerProvider.notifier).actualizar(),
              child: Text(descargando ? 'Actualizando…' : 'Actualizar datos'),
            ),
            const SizedBox(height: AppSpacing.sm),
            TextButton(
              style: TextButton.styleFrom(minimumSize: const Size(200, 48)),
              onPressed: alVolver,
              child: const Text('Volver'),
            ),
          ],
        ),
      ),
    );
  }
}

String _nombreSucursal(SucursalLocal s) => s.esDeposito ? '${s.nombre} (depósito)' : s.nombre;

/// La sucursal de la operación. Con varias autorizadas es un menú; si ya hay prendas agregadas, antes de cambiar se pregunta,
/// porque cambiar de sucursal las quita (la existencia y los precios dependen de ella). Al confirmar se cambia la sucursal activa
/// del teléfono; la pantalla escucha ese cambio y vacía las prendas.
class SeccionSucursalOperacion extends ConsumerWidget {
  const SeccionSucursalOperacion({super.key, required this.hayPrendas});

  final bool hayPrendas;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sucursales = ref.watch(sucursalesAutorizadasProvider).valueOrNull ?? const <SucursalLocal>[];
    final activaId = ref.watch(sucursalActivaProvider).valueOrNull;
    final activa = sucursales.where((s) => s.id == activaId).firstOrNull;

    final Widget contenido;
    if (activa == null) {
      contenido = const Text('Sin sucursal', style: TextStyle(color: AppColors.textoTenue));
    } else if (sucursales.length == 1) {
      contenido = _FilaSucursal(texto: _nombreSucursal(activa), conMenu: false);
    } else {
      contenido = PopupMenuButton<int>(
        key: const Key('menu_sucursal'),
        tooltip: 'Cambiar de sucursal',
        initialValue: activa.id,
        onSelected: (id) => _elegir(context, ref, sucursales, activa, id),
        itemBuilder: (context) => [
          for (final s in sucursales)
            PopupMenuItem<int>(
              value: s.id,
              child: Row(
                children: [
                  Icon(s.id == activa.id ? Icons.check : Icons.store_outlined, size: 20, color: AppColors.texto),
                  const SizedBox(width: AppSpacing.sm),
                  Flexible(child: Text(_nombreSucursal(s), overflow: TextOverflow.ellipsis)),
                ],
              ),
            ),
        ],
        child: _FilaSucursal(texto: _nombreSucursal(activa), conMenu: true),
      );
    }
    return SeccionOperacion(titulo: 'Sucursal', child: contenido);
  }

  Future<void> _elegir(BuildContext context, WidgetRef ref, List<SucursalLocal> sucursales, SucursalLocal activa, int id) async {
    if (id == activa.id) return;
    if (hayPrendas) {
      final nueva = sucursales.firstWhere((s) => s.id == id);
      final confirmo = await showDialog<bool>(
        context: context,
        builder: (_) => AlertDialog(
          title: const Text('Cambiar de sucursal'),
          content: Text(
            '¿Cambiar a ${_nombreSucursal(nueva)}? Se quitarán las prendas que agregaste, porque la existencia y los precios '
            'dependen de la sucursal.',
          ),
          actions: [
            TextButton(
              style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('Cancelar'),
            ),
            TextButton(
              style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
              onPressed: () => Navigator.of(context).pop(true),
              child: const Text('Cambiar y quitar prendas'),
            ),
          ],
        ),
      );
      if (confirmo != true) return;
    }
    await ref.read(descargaControllerProvider.notifier).alCambiarSucursal(id);
  }
}

class _FilaSucursal extends StatelessWidget {
  const _FilaSucursal({required this.texto, required this.conMenu});

  final String texto;
  final bool conMenu;

  @override
  Widget build(BuildContext context) {
    return ConstrainedBox(
      constraints: const BoxConstraints(minHeight: 48),
      child: Row(
        children: [
          const Icon(Icons.store_outlined, size: 24, color: AppColors.texto),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(
              texto,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: AppColors.texto, fontSize: 16, fontWeight: FontWeight.w500),
            ),
          ),
          if (conMenu) const Icon(Icons.arrow_drop_down, size: 24, color: AppColors.texto),
        ],
      ),
    );
  }
}

/// Las prendas agregadas y el botón para agregar más.
class SeccionPrendasOperacion extends StatelessWidget {
  const SeccionPrendasOperacion({
    super.key,
    required this.lineas,
    required this.alAgregar,
    required this.alCambiarCantidad,
    required this.alQuitar,
    this.mostrarPrecios = true,
  });

  final List<LineaCarrito> lineas;
  final VoidCallback alAgregar;
  final void Function(int varianteId, int cantidad) alCambiarCantidad;
  final ValueChanged<int> alQuitar;
  final bool mostrarPrecios;

  @override
  Widget build(BuildContext context) {
    return SeccionOperacion(
      titulo: 'Prendas',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ElevatedButton.icon(
            key: const Key('boton_agregar_prenda'),
            style: ElevatedButton.styleFrom(minimumSize: const Size(48, 56)),
            onPressed: alAgregar,
            icon: const Icon(Icons.add, size: 24),
            label: const Text('Agregar prenda'),
          ),
          if (lineas.isEmpty)
            const Padding(
              padding: EdgeInsets.only(top: AppSpacing.md),
              child: Text('Todavía no agregaste prendas.', style: TextStyle(color: AppColors.textoTenue)),
            ),
          for (final l in lineas)
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.md),
              child: FilaLineaCarrito(
                linea: l,
                mostrarPrecio: mostrarPrecios,
                alCambiarCantidad: (c) => alCambiarCantidad(l.varianteId, c),
                alQuitar: () => alQuitar(l.varianteId),
              ),
            ),
        ],
      ),
    );
  }
}

/// Una prenda de la lista: foto pequeña, nombre, talla y color, cantidad con más y menos, precio y quitar.
class FilaLineaCarrito extends StatelessWidget {
  const FilaLineaCarrito({
    super.key,
    required this.linea,
    required this.alCambiarCantidad,
    required this.alQuitar,
    this.mostrarPrecio = true,
  });

  final LineaCarrito linea;
  final ValueChanged<int> alCambiarCantidad;
  final VoidCallback alQuitar;
  final bool mostrarPrecio;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final id = linea.varianteId;
    return Container(
      key: Key('linea_$id'),
      padding: const EdgeInsets.all(AppSpacing.sm),
      decoration: BoxDecoration(
        color: AppColors.fondoAlterno,
        border: Border.all(color: AppColors.borde),
        borderRadius: BorderRadius.circular(AppRadius.base),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(AppRadius.base),
            child: SizedBox(
              width: 64,
              height: 64,
              child: FotoPrenda(nombre: linea.nombre, productoId: linea.productoId, url: linea.imagenUrl, compacta: true),
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  linea.nombre,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: tema.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600),
                ),
                Text('${linea.talla} · ${linea.color}', style: tema.textTheme.bodyMedium),
                if (mostrarPrecio)
                  Wrap(
                    spacing: AppSpacing.sm,
                    children: [
                      if (linea.tieneDescuento)
                        Text(
                          formatearBs(linea.precioUnitarioCentavos),
                          style: tema.textTheme.bodyMedium?.copyWith(decoration: TextDecoration.lineThrough),
                        ),
                      Text('${formatearBs(linea.precioFinalCentavos)} c/u', style: tema.textTheme.bodyMedium),
                    ],
                  ),
                const SizedBox(height: AppSpacing.xs),
                Row(
                  children: [
                    IconButton(
                      key: Key('cantidad_menos_$id'),
                      tooltip: 'Quitar una unidad',
                      icon: const Icon(Icons.remove_circle_outline, size: 24),
                      onPressed: linea.cantidad > 1 ? () => alCambiarCantidad(linea.cantidad - 1) : null,
                    ),
                    Container(
                      key: Key('cantidad_$id'),
                      constraints: const BoxConstraints(minWidth: 32),
                      alignment: Alignment.center,
                      child: Text(
                        '${linea.cantidad}',
                        style: tema.textTheme.titleMedium?.copyWith(color: AppColors.texto, fontWeight: FontWeight.w600),
                      ),
                    ),
                    IconButton(
                      key: Key('cantidad_mas_$id'),
                      tooltip: 'Agregar una unidad',
                      icon: const Icon(Icons.add_circle_outline, size: 24),
                      onPressed: linea.cantidad < maxCantidadPorLinea ? () => alCambiarCantidad(linea.cantidad + 1) : null,
                    ),
                    const Spacer(),
                    IconButton(
                      key: Key('quitar_$id'),
                      tooltip: 'Quitar prenda',
                      icon: const Icon(Icons.delete_outline, size: 24),
                      color: AppColors.error,
                      onPressed: alQuitar,
                    ),
                  ],
                ),
                if (mostrarPrecio)
                  Text(
                    'Subtotal ${formatearBs(linea.subtotalCentavos)}',
                    key: Key('subtotal_$id'),
                    style: tema.textTheme.titleMedium?.copyWith(color: AppColors.texto, fontWeight: FontWeight.w600),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// El cliente de la operación. Opcional en la venta; obligatorio en la reserva (el botón sale resaltado).
class SeccionClienteOperacion extends StatelessWidget {
  const SeccionClienteOperacion({
    super.key,
    required this.cliente,
    required this.obligatorio,
    required this.alElegir,
    required this.alQuitar,
  });

  final ClienteLocal? cliente;
  final bool obligatorio;
  final VoidCallback alElegir;
  final VoidCallback alQuitar;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final c = cliente;
    return SeccionOperacion(
      titulo: obligatorio ? 'Cliente (obligatorio)' : 'Cliente (opcional)',
      child: c == null
          ? Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (obligatorio)
                  ElevatedButton.icon(
                    key: const Key('boton_elegir_cliente'),
                    style: ElevatedButton.styleFrom(minimumSize: const Size(48, 56)),
                    onPressed: alElegir,
                    icon: const Icon(Icons.person_search_outlined, size: 24),
                    label: const Text('Elegir cliente'),
                  )
                else
                  OutlinedButton.icon(
                    key: const Key('boton_elegir_cliente'),
                    style: OutlinedButton.styleFrom(minimumSize: const Size(48, 56)),
                    onPressed: alElegir,
                    icon: const Icon(Icons.person_search_outlined, size: 24),
                    label: const Text('Elegir cliente'),
                  ),
                const SizedBox(height: AppSpacing.sm),
                Text(
                  obligatorio
                      ? 'La reserva se guarda a nombre de un cliente que ya esté en tus datos descargados.'
                      : 'Puedes dejar la venta sin cliente.',
                  style: tema.textTheme.bodyMedium,
                ),
              ],
            )
          : Row(
              children: [
                const Icon(Icons.person_outline, size: 24, color: AppColors.texto),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        c.nombreCompleto,
                        key: const Key('cliente_elegido'),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: tema.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600),
                      ),
                      if (c.ciNit != null && c.ciNit!.trim().isNotEmpty)
                        Text('CI/NIT: ${c.ciNit}', style: tema.textTheme.bodyMedium),
                    ],
                  ),
                ),
                TextButton(
                  key: const Key('boton_cambiar_cliente'),
                  style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
                  onPressed: obligatorio ? alElegir : alQuitar,
                  child: Text(obligatorio ? 'Cambiar' : 'Quitar'),
                ),
              ],
            ),
    );
  }
}

/// Pregunta si se registra aunque pueda faltar stock. `true` = "Registrar igual".
Future<bool> preguntarRegistrarSinStock(BuildContext context, List<String> avisos) async {
  final respuesta = await showDialog<bool>(
    context: context,
    builder: (dialogo) => AlertDialog(
      title: const Text('Puede faltar stock'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (final a in avisos)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.xs),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Padding(
                      padding: EdgeInsets.only(top: 2),
                      child: Icon(Icons.warning_amber_rounded, size: 20, color: AppColors.advertencia),
                    ),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(child: Text(a)),
                  ],
                ),
              ),
            const SizedBox(height: AppSpacing.sm),
            const Text(
              'La existencia es una estimación. El servidor decide al sincronizar y podría dejar la operación en conflicto.',
              style: TextStyle(color: AppColors.textoTenue, fontSize: 14),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
          onPressed: () => Navigator.of(dialogo).pop(false),
          child: const Text('Revisar'),
        ),
        TextButton(
          style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
          onPressed: () => Navigator.of(dialogo).pop(true),
          child: const Text('Registrar igual'),
        ),
      ],
    ),
  );
  return respuesta == true;
}

/// El texto de error de la barra inferior.
class ErrorOperacion extends StatelessWidget {
  const ErrorOperacion({super.key, required this.mensaje});

  final String mensaje;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      child: Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.sm),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.error_outline, size: 20, color: AppColors.error),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: Text(
                mensaje,
                key: const Key('error_registro'),
                style: const TextStyle(color: AppColors.error, fontSize: 14, fontWeight: FontWeight.w500),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
