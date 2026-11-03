import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/utils/dinero.dart';
import '../../../core/widgets/indicador_conexion.dart';
import '../state/catalogo_local_providers.dart';
import '../state/nueva_venta_controller.dart';
import 'aviso_vigencia.dart';
import 'componentes_operacion.dart';
import 'selector_cliente.dart';
import 'selector_prenda.dart';

/// Registrar una venta de contado en efectivo, con o sin conexión. Queda guardada en el teléfono (la cola de operaciones) y se
/// envía sola cuando hay conexión; el servidor la confirma o la rechaza. La casilla "Efectivo recibido" la marca la persona: NO
/// es la aprobación del servidor.
class NuevaVentaScreen extends ConsumerStatefulWidget {
  const NuevaVentaScreen({super.key});

  @override
  ConsumerState<NuevaVentaScreen> createState() => _NuevaVentaScreenState();
}

class _NuevaVentaScreenState extends ConsumerState<NuevaVentaScreen> {
  bool _navegando = false;
  bool _ocupada = false;

  @override
  void initState() {
    super.initState();
    // El controlador (y con él el id de la operación) vive mientras esté abierta la pantalla.
    ref.listenManual(nuevaVentaControllerProvider, (anterior, actual) {});
    // La sucursal de la venta es la activa del teléfono; si cambia, el controlador vacía las prendas.
    ref.listenManual<AsyncValue<int?>>(sucursalActivaProvider, (anterior, actual) {
      final id = actual.valueOrNull;
      if (id != null) ref.read(nuevaVentaControllerProvider.notifier).elegirSucursal(id);
    }, fireImmediately: true);
  }

  void _volver() {
    if (context.canPop()) {
      context.pop();
    } else {
      context.go('/vendedor');
    }
  }

  Future<void> _agregarPrenda() async {
    final sucursalId = ref.read(nuevaVentaControllerProvider).sucursalId;
    if (sucursalId == null) return;
    final eleccion = await mostrarSelectorPrenda(context, ref, sucursalId: sucursalId);
    if (eleccion == null || !mounted) return;
    ref.read(nuevaVentaControllerProvider.notifier).agregar(eleccion.variante, eleccion.producto, eleccion.cantidad);
  }

  Future<void> _elegirCliente() async {
    final cliente = await mostrarSelectorCliente(context, ref);
    if (cliente == null || !mounted) return;
    ref.read(nuevaVentaControllerProvider.notifier).elegirCliente(cliente);
  }

  /// Un toque a "Registrar venta". Mientras uno sigue en curso (guardando o con el diálogo de stock abierto) los demás se
  /// ignoran: un doble toque nunca abre dos diálogos ni navega dos veces.
  Future<void> _registrar() async {
    if (_ocupada || _navegando) return;
    _ocupada = true;
    try {
      var permitirSinStock = false;
      while (true) {
        final resultado = await ref.read(nuevaVentaControllerProvider.notifier).registrar(permitirSinStock: permitirSinStock);
        if (!mounted) return;
        switch (resultado) {
          case RegistroConAdvertencias(:final textos):
            final registrarIgual = await preguntarRegistrarSinStock(context, textos);
            if (!registrarIgual || !mounted) return;
            permitirSinStock = true;
          case RegistroConError():
            return; // el mensaje ya está en la barra inferior
          case RegistroExitoso(:final operacionId):
            _navegando = true;
            context.pushReplacement('/vendedor/operaciones/$operacionId?nuevo=1');
            return;
        }
      }
    } finally {
      _ocupada = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final estado = ref.watch(nuevaVentaControllerProvider);
    final controlador = ref.read(nuevaVentaControllerProvider.notifier);
    final sucursalActiva = ref.watch(sucursalActivaProvider);
    final hayCatalogo = sucursalActiva.valueOrNull != null;

    return Scaffold(
      appBar: AppBar(title: const Text('Nueva venta')),
      body: Column(
        children: [
          const AvisoVigencia(),
          const IndicadorConexion.banner(),
          const AvisoBloqueoSync(),
          Expanded(
            child: sucursalActiva.isLoading && !sucursalActiva.hasValue
                ? const Center(child: CircularProgressIndicator())
                : !hayCatalogo
                ? EstadoSinCatalogoOperacion(alVolver: _volver)
                : ListView(
                    padding: const EdgeInsets.all(AppSpacing.md),
                    children: [
                      SeccionSucursalOperacion(hayPrendas: estado.lineas.isNotEmpty),
                      SeccionPrendasOperacion(
                        lineas: estado.lineas,
                        alAgregar: () => unawaited(_agregarPrenda()),
                        alCambiarCantidad: controlador.cambiarCantidad,
                        alQuitar: controlador.quitar,
                      ),
                      SeccionClienteOperacion(
                        cliente: estado.cliente,
                        obligatorio: false,
                        alElegir: () => unawaited(_elegirCliente()),
                        alQuitar: controlador.quitarCliente,
                      ),
                      _SeccionCobro(efectivoConfirmado: estado.efectivoConfirmado, alCambiar: controlador.confirmarEfectivo),
                    ],
                  ),
          ),
        ],
      ),
      bottomNavigationBar: hayCatalogo ? _BarraRegistro(estado: estado, alRegistrar: () => unawaited(_registrar())) : null,
    );
  }
}

class _SeccionCobro extends StatelessWidget {
  const _SeccionCobro({required this.efectivoConfirmado, required this.alCambiar});

  final bool efectivoConfirmado;
  final ValueChanged<bool> alCambiar;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return SeccionOperacion(
      titulo: 'Cobro',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Forma de pago: Efectivo',
            key: const Key('forma_pago'),
            style: tema.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: AppSpacing.sm),
          // Un Material (no un Container con fondo) para que el fondo de la casilla y su efecto al tocar se vean.
          Material(
            color: efectivoConfirmado ? Color.alphaBlend(AppColors.exito.withValues(alpha: 0.08), AppColors.fondo) : AppColors.fondoAlterno,
            clipBehavior: Clip.antiAlias,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(AppRadius.base),
              side: BorderSide(color: efectivoConfirmado ? AppColors.exito : AppColors.borde),
            ),
            child: CheckboxListTile(
              key: const Key('casilla_efectivo'),
              value: efectivoConfirmado,
              onChanged: (v) => alCambiar(v ?? false),
              controlAffinity: ListTileControlAffinity.leading,
              minTileHeight: 64,
              title: Text(
                'Efectivo recibido',
                style: tema.textTheme.titleMedium?.copyWith(color: AppColors.texto, fontWeight: FontWeight.w600),
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(textoAyudaGuardado, style: tema.textTheme.bodyMedium),
        ],
      ),
    );
  }
}

class _BarraRegistro extends StatelessWidget {
  const _BarraRegistro({required this.estado, required this.alRegistrar});

  final NuevaVentaState estado;
  final VoidCallback alRegistrar;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final ayuda = estado.lineas.isNotEmpty && estado.problema != null ? estado.problema : null;
    return Material(
      color: AppColors.fondo,
      elevation: 8,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (estado.error != null) ErrorOperacion(mensaje: estado.error!),
              if (ayuda != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                  child: Text(ayuda, key: const Key('ayuda_registro'), style: tema.textTheme.bodyMedium),
                ),
              Row(
                children: [
                  Expanded(
                    flex: 5,
                    child: Text(
                      'Total ${formatearBs(estado.totalCentavos)}',
                      key: const Key('total_venta'),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: tema.textTheme.titleLarge?.copyWith(color: AppColors.texto, fontWeight: FontWeight.w700),
                    ),
                  ),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    flex: 4,
                    child: ElevatedButton(
                      key: const Key('boton_registrar_venta'),
                      style: ElevatedButton.styleFrom(minimumSize: const Size(48, 56)),
                      onPressed: estado.puedeRegistrar ? alRegistrar : null,
                      child: estado.registrando
                          ? const SizedBox(
                              width: 24,
                              height: 24,
                              child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white),
                            )
                          : const Text('Registrar venta'),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
