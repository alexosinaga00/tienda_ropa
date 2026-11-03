import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/indicador_conexion.dart';
import '../state/catalogo_local_providers.dart';
import '../state/nueva_reserva_controller.dart';
import 'aviso_vigencia.dart';
import 'componentes_operacion.dart';
import 'selector_cliente.dart';
import 'selector_prenda.dart';

String _dos(int n) => n.toString().padLeft(2, '0');

/// "02/11/2026".
String fechaVisitaLegible(DateTime fecha) => '${_dos(fecha.day)}/${_dos(fecha.month)}/${fecha.year}';

/// "10:00" para el contrato.
String horaComoTexto(TimeOfDay hora) => '${_dos(hora.hour)}:${_dos(hora.minute)}';

TimeOfDay? _horaDeTexto(String? texto) {
  if (texto == null) return null;
  final partes = texto.split(':');
  if (partes.length != 2) return null;
  final h = int.tryParse(partes[0]);
  final m = int.tryParse(partes[1]);
  return h == null || m == null ? null : TimeOfDay(hour: h, minute: m);
}

const textoHorarioLoValidaElServidor = 'El horario de la sucursal lo valida el servidor al sincronizar.';

/// Registrar una reserva (un cliente que está en tienda viene a ver unas prendas), con o sin conexión. Queda guardada en el
/// teléfono y se envía sola cuando hay conexión; el servidor la confirma o la rechaza.
class NuevaReservaScreen extends ConsumerStatefulWidget {
  const NuevaReservaScreen({super.key});

  @override
  ConsumerState<NuevaReservaScreen> createState() => _NuevaReservaScreenState();
}

class _NuevaReservaScreenState extends ConsumerState<NuevaReservaScreen> {
  final _observacion = TextEditingController();
  bool _navegando = false;

  @override
  void initState() {
    super.initState();
    ref.listenManual(nuevaReservaControllerProvider, (anterior, actual) {});
    ref.listenManual<AsyncValue<int?>>(sucursalActivaProvider, (anterior, actual) {
      final id = actual.valueOrNull;
      if (id != null) ref.read(nuevaReservaControllerProvider.notifier).elegirSucursal(id);
    }, fireImmediately: true);
  }

  @override
  void dispose() {
    _observacion.dispose();
    super.dispose();
  }

  void _volver() {
    if (context.canPop()) {
      context.pop();
    } else {
      context.go('/vendedor');
    }
  }

  Future<void> _agregarPrenda() async {
    final sucursalId = ref.read(nuevaReservaControllerProvider).sucursalId;
    if (sucursalId == null) return;
    final eleccion = await mostrarSelectorPrenda(context, ref, sucursalId: sucursalId);
    if (eleccion == null || !mounted) return;
    ref.read(nuevaReservaControllerProvider.notifier).agregar(eleccion.variante, eleccion.producto, eleccion.cantidad);
  }

  Future<void> _elegirCliente() async {
    final cliente = await mostrarSelectorCliente(context, ref);
    if (cliente == null || !mounted) return;
    ref.read(nuevaReservaControllerProvider.notifier).elegirCliente(cliente);
  }

  Future<void> _elegirFecha() async {
    final estado = ref.read(nuevaReservaControllerProvider);
    final inicial = estado.fechaVisita ?? estado.hoy;
    final fecha = await showDatePicker(
      context: context,
      initialDate: inicial.isBefore(estado.hoy) ? estado.hoy : inicial,
      firstDate: estado.hoy,
      lastDate: DateTime(estado.hoy.year + 1, estado.hoy.month, estado.hoy.day),
      helpText: 'Fecha de la visita',
    );
    if (fecha == null || !mounted) return;
    ref.read(nuevaReservaControllerProvider.notifier).elegirFecha(fecha);
  }

  Future<void> _elegirHora({required bool desde}) async {
    final estado = ref.read(nuevaReservaControllerProvider);
    final actual = _horaDeTexto(desde ? estado.horaDesde : estado.horaHasta);
    final base = _horaDeTexto(estado.horaDesde);
    final TimeOfDay predeterminada = desde
        ? const TimeOfDay(hour: 10, minute: 0)
        : (base == null ? const TimeOfDay(hour: 11, minute: 0) : base.replacing(hour: (base.hour + 1) % 24));
    final sugerida = actual ?? predeterminada;
    final hora = await showTimePicker(
      context: context,
      initialTime: sugerida,
      helpText: desde ? 'Hora de inicio' : 'Hora de fin',
      builder: (contexto, hijo) => MediaQuery(
        data: MediaQuery.of(contexto).copyWith(alwaysUse24HourFormat: true),
        child: hijo!,
      ),
    );
    if (hora == null || !mounted) return;
    final controlador = ref.read(nuevaReservaControllerProvider.notifier);
    if (desde) {
      controlador.elegirHoraDesde(horaComoTexto(hora));
    } else {
      controlador.elegirHoraHasta(horaComoTexto(hora));
    }
  }

  Future<void> _registrar({bool permitirSinStock = false}) async {
    if (_navegando) return;
    final resultado = await ref.read(nuevaReservaControllerProvider.notifier).registrar(permitirSinStock: permitirSinStock);
    if (!mounted || _navegando) return;
    switch (resultado) {
      case RegistroConAdvertencias(:final textos):
        final registrarIgual = await preguntarRegistrarSinStock(context, textos);
        if (registrarIgual && mounted) await _registrar(permitirSinStock: true);
      case RegistroConError():
        break; // el mensaje ya está en la barra inferior
      case RegistroExitoso(:final operacionId):
        _navegando = true;
        context.pushReplacement('/vendedor/operaciones/$operacionId?nuevo=1');
    }
  }

  @override
  Widget build(BuildContext context) {
    final estado = ref.watch(nuevaReservaControllerProvider);
    final controlador = ref.read(nuevaReservaControllerProvider.notifier);
    final sucursalActiva = ref.watch(sucursalActivaProvider);
    final hayCatalogo = sucursalActiva.valueOrNull != null;

    return Scaffold(
      appBar: AppBar(title: const Text('Nueva reserva')),
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
                      SeccionClienteOperacion(
                        cliente: estado.cliente,
                        obligatorio: true,
                        alElegir: () => unawaited(_elegirCliente()),
                        alQuitar: controlador.quitarCliente,
                      ),
                      SeccionPrendasOperacion(
                        lineas: estado.lineas,
                        mostrarPrecios: false,
                        alAgregar: () => unawaited(_agregarPrenda()),
                        alCambiarCantidad: controlador.cambiarCantidad,
                        alQuitar: controlador.quitar,
                      ),
                      _SeccionVisita(
                        estado: estado,
                        observacion: _observacion,
                        alElegirFecha: () => unawaited(_elegirFecha()),
                        alElegirDesde: () => unawaited(_elegirHora(desde: true)),
                        alElegirHasta: () => unawaited(_elegirHora(desde: false)),
                        alCambiarObservacion: controlador.cambiarObservacion,
                      ),
                      const Padding(
                        padding: EdgeInsets.only(bottom: AppSpacing.md),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              textoHorarioLoValidaElServidor,
                              key: Key('aviso_horario'),
                              style: TextStyle(color: AppColors.textoTenue, fontSize: 14),
                            ),
                            SizedBox(height: AppSpacing.xs),
                            Text(textoAyudaGuardado, style: TextStyle(color: AppColors.textoTenue, fontSize: 14)),
                          ],
                        ),
                      ),
                    ],
                  ),
          ),
        ],
      ),
      bottomNavigationBar: hayCatalogo ? _BarraRegistro(estado: estado, alRegistrar: () => unawaited(_registrar())) : null,
    );
  }
}

class _SeccionVisita extends StatelessWidget {
  const _SeccionVisita({
    required this.estado,
    required this.observacion,
    required this.alElegirFecha,
    required this.alElegirDesde,
    required this.alElegirHasta,
    required this.alCambiarObservacion,
  });

  final NuevaReservaState estado;
  final TextEditingController observacion;
  final VoidCallback alElegirFecha;
  final VoidCallback alElegirDesde;
  final VoidCallback alElegirHasta;
  final ValueChanged<String> alCambiarObservacion;

  @override
  Widget build(BuildContext context) {
    final fecha = estado.fechaVisita;
    final desde = estado.horaDesde;
    final hasta = estado.horaHasta;
    final horasInvertidas = desde != null && hasta != null && hasta.compareTo(desde) <= 0;

    return SeccionOperacion(
      titulo: 'Visita',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          OutlinedButton.icon(
            key: const Key('boton_fecha'),
            style: OutlinedButton.styleFrom(minimumSize: const Size(48, 56), alignment: Alignment.centerLeft),
            onPressed: alElegirFecha,
            icon: const Icon(Icons.event_outlined, size: 24),
            label: Text(fecha == null ? 'Elegir fecha de la visita' : 'Fecha: ${fechaVisitaLegible(fecha)}'),
          ),
          const SizedBox(height: AppSpacing.sm),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  key: const Key('boton_hora_desde'),
                  style: OutlinedButton.styleFrom(minimumSize: const Size(48, 56)),
                  onPressed: alElegirDesde,
                  icon: const Icon(Icons.schedule, size: 24),
                  label: Text(desde == null ? 'Desde' : 'Desde $desde'),
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: OutlinedButton.icon(
                  key: const Key('boton_hora_hasta'),
                  style: OutlinedButton.styleFrom(minimumSize: const Size(48, 56)),
                  onPressed: alElegirHasta,
                  icon: const Icon(Icons.schedule, size: 24),
                  label: Text(hasta == null ? 'Hasta' : 'Hasta $hasta'),
                ),
              ),
            ],
          ),
          if (horasInvertidas)
            const Padding(
              padding: EdgeInsets.only(top: AppSpacing.sm),
              child: Text(
                'La hora de fin debe ser posterior a la hora de inicio.',
                key: Key('error_horas'),
                style: TextStyle(color: AppColors.error, fontSize: 14, fontWeight: FontWeight.w500),
              ),
            ),
          const SizedBox(height: AppSpacing.md),
          TextField(
            key: const Key('campo_observacion'),
            controller: observacion,
            onChanged: alCambiarObservacion,
            maxLength: maxObservacionReserva,
            minLines: 2,
            maxLines: 4,
            textCapitalization: TextCapitalization.sentences,
            decoration: const InputDecoration(labelText: 'Observación (opcional)', alignLabelWithHint: true),
          ),
        ],
      ),
    );
  }
}

class _BarraRegistro extends StatelessWidget {
  const _BarraRegistro({required this.estado, required this.alRegistrar});

  final NuevaReservaState estado;
  final VoidCallback alRegistrar;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final ayuda = estado.problema;
    final prendas = estado.cantidadPrendas;
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
                    flex: 4,
                    child: Text(
                      prendas == 1 ? '1 prenda' : '$prendas prendas',
                      key: const Key('resumen_prendas'),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: tema.textTheme.titleLarge?.copyWith(color: AppColors.texto, fontWeight: FontWeight.w700),
                    ),
                  ),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    flex: 5,
                    child: ElevatedButton(
                      key: const Key('boton_registrar_reserva'),
                      style: ElevatedButton.styleFrom(minimumSize: const Size(48, 56)),
                      onPressed: estado.puedeRegistrar ? alRegistrar : null,
                      child: estado.registrando
                          ? const SizedBox(
                              width: 24,
                              height: 24,
                              child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white),
                            )
                          : const Text('Registrar reserva'),
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
