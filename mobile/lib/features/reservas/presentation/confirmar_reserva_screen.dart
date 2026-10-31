import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/app_theme.dart';
import '../../catalogo/models/referencia.dart';
import '../models/horario_sucursal.dart';
import '../models/item_reserva_temporal.dart';
import '../state/carrito_reserva_controller.dart';
import '../state/reservas_providers.dart';

int _minutos(TimeOfDay t) => t.hour * 60 + t.minute;

String _dosDigitos(int n) => n.toString().padLeft(2, '0');

String _fechaIso(DateTime fecha) => '${fecha.year}-${_dosDigitos(fecha.month)}-${_dosDigitos(fecha.day)}';

String _horaIso(TimeOfDay hora) => '${_dosDigitos(hora.hour)}:${_dosDigitos(hora.minute)}:00';

class ConfirmarReservaScreen extends ConsumerStatefulWidget {
  const ConfirmarReservaScreen({super.key});

  @override
  ConsumerState<ConfirmarReservaScreen> createState() => _ConfirmarReservaScreenState();
}

class _ConfirmarReservaScreenState extends ConsumerState<ConfirmarReservaScreen> {
  int? _sucursalId;
  DateTime? _fecha;
  TimeOfDay? _horaDesde;
  TimeOfDay? _horaHasta;
  bool _enviando = false;

  Future<void> _elegirFecha() async {
    final ahora = DateTime.now();
    final elegida = await showDatePicker(
      context: context,
      initialDate: ahora.add(const Duration(days: 1)),
      firstDate: ahora,
      lastDate: ahora.add(const Duration(days: 60)),
    );
    if (elegida != null) {
      setState(() {
        _fecha = elegida;
        _horaDesde = null;
        _horaHasta = null;
      });
    }
  }

  Future<void> _elegirHora({required bool esDesde, required HorarioSucursal? horario}) async {
    final inicial = (esDesde ? _horaDesde : _horaHasta) ?? horario?.apertura ?? TimeOfDay.now();
    final elegida = await showTimePicker(context: context, initialTime: inicial);
    if (elegida != null) {
      setState(() {
        if (esDesde) {
          _horaDesde = elegida;
        } else {
          _horaHasta = elegida;
        }
      });
    }
  }

  String? _errorFranja(HorarioSucursal? horario) {
    if (horario == null) return null;
    if (_horaDesde == null || _horaHasta == null) return null;
    if (_minutos(_horaDesde!) < _minutos(horario.apertura) || _minutos(_horaHasta!) > _minutos(horario.cierre)) {
      return 'La franja tiene que estar dentro de ${horario.horaApertura.substring(0, 5)} - ${horario.horaCierre.substring(0, 5)}';
    }
    if (_minutos(_horaHasta!) <= _minutos(_horaDesde!)) {
      return 'La hora de salida tiene que ser después de la de llegada';
    }
    return null;
  }

  Future<void> _confirmar(List<ItemReservaTemporal> carrito) async {
    setState(() => _enviando = true);
    try {
      await ref
          .read(reservasRepositoryProvider)
          .crear(
            sucursalId: _sucursalId!,
            fechaVisita: _fechaIso(_fecha!),
            horaVisitaDesde: _horaIso(_horaDesde!),
            horaVisitaHasta: _horaIso(_horaHasta!),
            variantesIds: carrito.map((item) => item.varianteId).toList(),
          );
      ref.read(carritoReservaProvider.notifier).vaciar();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Reserva creada')));
      // Reemplaza solo esta pantalla (no toda la pila): "atrás" desde Mis reservas vuelve a donde estaba la persona.
      context.pushReplacement('/reservas');
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('No se pudo crear la reserva. Probá de nuevo.')));
    } finally {
      if (mounted) setState(() => _enviando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final carrito = ref.watch(carritoReservaProvider);
    final asyncSucursales = ref.watch(sucursalesDisponiblesProvider);
    final asyncHorarios = _sucursalId == null
        ? null
        : ref.watch(horariosSucursalProvider(_sucursalId!));

    HorarioSucursal? horarioDelDia;
    if (_fecha != null && asyncHorarios != null) {
      horarioDelDia = asyncHorarios.maybeWhen(
        data: (horarios) {
          for (final horario in horarios) {
            if (horario.diaSemana == _fecha!.weekday) return horario;
          }
          return null;
        },
        orElse: () => null,
      );
    }

    final errorFranja = _errorFranja(horarioDelDia);
    final puedeConfirmar =
        !_enviando &&
        carrito.isNotEmpty &&
        _sucursalId != null &&
        _fecha != null &&
        horarioDelDia != null &&
        _horaDesde != null &&
        _horaHasta != null &&
        errorFranja == null;

    return Scaffold(
      backgroundColor: AppColors.fondo,
      appBar: AppBar(title: const Text('Confirmar reserva')),
      body: carrito.isEmpty
          ? const Center(
              child: Padding(
                padding: EdgeInsets.all(AppSpacing.xl),
                child: Text(
                  'Todavía no agregaste ninguna prenda. Volvé al catálogo y usá "Agregar a reserva".',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: AppColors.textoTenue),
                ),
              ),
            )
          : ListView(
              padding: const EdgeInsets.all(AppSpacing.md),
              children: [
                const Text('Prendas', style: TextStyle(color: AppColors.textoTenue, fontSize: 12)),
                const SizedBox(height: AppSpacing.xs),
                for (final item in carrito) _TarjetaItem(item: item),
                const SizedBox(height: AppSpacing.lg),

                const Text('Sucursal', style: TextStyle(color: AppColors.textoTenue, fontSize: 12)),
                const SizedBox(height: AppSpacing.xs),
                asyncSucursales.when(
                  loading: () => const LinearProgressIndicator(),
                  error: (e, s) => const Text('No se pudo cargar la disponibilidad.', style: TextStyle(color: AppColors.error)),
                  data: (sucursales) {
                    if (sucursales.isEmpty) {
                      return const Text(
                        'Ninguna sucursal tiene disponibles todas las prendas elegidas.',
                        style: TextStyle(color: AppColors.error),
                      );
                    }
                    return _SelectorSucursal(
                      sucursales: sucursales,
                      seleccionadaId: _sucursalId,
                      onSeleccionar: (id) => setState(() {
                        _sucursalId = id;
                        _horaDesde = null;
                        _horaHasta = null;
                      }),
                    );
                  },
                ),
                const SizedBox(height: AppSpacing.lg),

                const Text('Fecha', style: TextStyle(color: AppColors.textoTenue, fontSize: 12)),
                const SizedBox(height: AppSpacing.xs),
                OutlinedButton.icon(
                  onPressed: _sucursalId == null ? null : _elegirFecha,
                  icon: const Icon(Icons.calendar_month_outlined),
                  label: Text(_fecha == null ? 'Elegí una fecha' : _fechaIso(_fecha!)),
                ),

                if (_fecha != null && asyncHorarios != null) ...[
                  const SizedBox(height: AppSpacing.lg),
                  const Text('Franja horaria', style: TextStyle(color: AppColors.textoTenue, fontSize: 12)),
                  const SizedBox(height: AppSpacing.xs),
                  asyncHorarios.when(
                    loading: () => const LinearProgressIndicator(),
                    error: (e, s) => const Text('No se pudo cargar el horario.', style: TextStyle(color: AppColors.error)),
                    data: (_) {
                      if (horarioDelDia == null) {
                        return const Text(
                          'Esta sucursal no atiende ese día. Elegí otra fecha.',
                          style: TextStyle(color: AppColors.error),
                        );
                      }
                      return Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Atiende de ${horarioDelDia.horaApertura.substring(0, 5)} a ${horarioDelDia.horaCierre.substring(0, 5)}',
                            style: const TextStyle(color: AppColors.textoTenue, fontSize: 12),
                          ),
                          const SizedBox(height: AppSpacing.sm),
                          Row(
                            children: [
                              Expanded(
                                child: OutlinedButton.icon(
                                  onPressed: () => _elegirHora(esDesde: true, horario: horarioDelDia),
                                  icon: const Icon(Icons.schedule),
                                  label: Text(_horaDesde == null ? 'Desde' : _horaDesde!.format(context)),
                                ),
                              ),
                              const SizedBox(width: AppSpacing.sm),
                              Expanded(
                                child: OutlinedButton.icon(
                                  onPressed: () => _elegirHora(esDesde: false, horario: horarioDelDia),
                                  icon: const Icon(Icons.schedule),
                                  label: Text(_horaHasta == null ? 'Hasta' : _horaHasta!.format(context)),
                                ),
                              ),
                            ],
                          ),
                          if (errorFranja != null) ...[
                            const SizedBox(height: AppSpacing.xs),
                            Text(errorFranja, style: const TextStyle(color: AppColors.error, fontSize: 12)),
                          ],
                        ],
                      );
                    },
                  ),
                ],

                const SizedBox(height: AppSpacing.xl),
                ElevatedButton(
                  onPressed: puedeConfirmar ? () => _confirmar(carrito) : null,
                  child: _enviando
                      ? const SizedBox(
                          height: 20,
                          width: 20,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : const Text('Confirmar reserva'),
                ),
              ],
            ),
    );
  }
}

class _SelectorSucursal extends StatelessWidget {
  const _SelectorSucursal({required this.sucursales, required this.seleccionadaId, required this.onSeleccionar});

  final List<SucursalRef> sucursales;
  final int? seleccionadaId;
  final ValueChanged<int> onSeleccionar;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: AppSpacing.sm,
      children: [
        for (final sucursal in sucursales)
          ChoiceChip(
            label: Text(sucursal.nombre),
            selected: seleccionadaId == sucursal.id,
            onSelected: (_) => onSeleccionar(sucursal.id),
          ),
      ],
    );
  }
}

class _TarjetaItem extends StatelessWidget {
  const _TarjetaItem({required this.item});

  final ItemReservaTemporal item;

  @override
  Widget build(BuildContext context) {
    return Consumer(
      builder: (context, ref, _) {
        return Card(
          margin: const EdgeInsets.only(bottom: AppSpacing.sm),
          child: ListTile(
            leading: ClipRRect(
              borderRadius: BorderRadius.circular(AppRadius.base),
              child: item.imagenUrl != null
                  ? CachedNetworkImage(imageUrl: item.imagenUrl!, width: 48, height: 48, fit: BoxFit.cover)
                  : Container(
                      width: 48,
                      height: 48,
                      color: AppColors.fondoAlterno,
                      child: const Icon(Icons.checkroom, color: AppColors.textoTenue),
                    ),
            ),
            title: Text(item.productoNombre, maxLines: 1, overflow: TextOverflow.ellipsis),
            subtitle: Text('${item.tallaCodigo} · ${item.colorNombre} · ${item.sku}'),
            trailing: IconButton(
              icon: const Icon(Icons.close),
              onPressed: () => ref.read(carritoReservaProvider.notifier).quitar(item.varianteId),
            ),
          ),
        );
      },
    );
  }
}
