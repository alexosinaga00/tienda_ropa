import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/sync/operacion_pendiente.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/dinero.dart';
import '../../../core/utils/reloj.dart';
import '../../../core/widgets/indicador_conexion.dart';
import '../models/sucursal_local.dart';
import '../state/catalogo_local_providers.dart';
import '../state/operaciones_vista_providers.dart';
import '../state/sincronizacion_providers.dart';
import 'aviso_bloqueo_sync.dart';
import 'aviso_vigencia.dart' show textoHace;
import 'textos_sync.dart';

const _tamanioPagina = 30;

enum _Filtro {
  porAtender('Por atender'),
  todas('Todas'),
  sincronizadas('Sincronizadas');

  const _Filtro(this.texto);

  final String texto;

  /// Los estados que muestra. Null = todos.
  Set<EstadoOperacion>? get estados => switch (this) {
    _Filtro.porAtender => const {
      EstadoOperacion.registrada,
      EstadoOperacion.enviada,
      EstadoOperacion.rechazada,
      EstadoOperacion.enConflicto,
    },
    _Filtro.todas => null,
    _Filtro.sincronizadas => const {EstadoOperacion.confirmada},
  };

  String get textoVacio => switch (this) {
    _Filtro.porAtender => 'No tienes operaciones por atender',
    _Filtro.todas => 'Aún no registraste operaciones',
    _Filtro.sincronizadas => 'Aún no tienes operaciones sincronizadas',
  };
}

/// Las ventas y reservas que el personal registró en este teléfono (D13): las que esperan conexión, las que el servidor
/// rechazó o dejó en conflicto y las ya sincronizadas. Se actualiza sola con cada cambio de la cola.
class OperacionesPendientesScreen extends ConsumerStatefulWidget {
  const OperacionesPendientesScreen({super.key});

  @override
  ConsumerState<OperacionesPendientesScreen> createState() => _OperacionesPendientesScreenState();
}

class _OperacionesPendientesScreenState extends ConsumerState<OperacionesPendientesScreen> {
  _Filtro _filtro = _Filtro.porAtender;
  List<OperacionPendiente> _items = const [];
  bool _hayMas = false;
  bool _cargando = false;
  bool _primeraCarga = true;
  Object? _error;

  /// Cada recarga invalida a las lecturas que estaban en vuelo (llegarían con la lista vieja).
  int _generacion = 0;

  @override
  void initState() {
    super.initState();
    // Se lee cuando la cola está lista y otra vez con cada cambio.
    ref.listenManual<AsyncValue<int>>(versionColaProvider, (anterior, actual) {
      if (actual.hasValue) unawaited(_recargar());
    }, fireImmediately: true);
  }

  void _cambiarFiltro(_Filtro filtro) {
    if (filtro == _filtro) return;
    setState(() {
      _filtro = filtro;
      _items = const [];
      _hayMas = false;
      _primeraCarga = true;
    });
    unawaited(_recargar());
  }

  /// Vuelve a leer lo que ya estaba cargado (al menos la primera página), para que un cambio no mueva la lista.
  Future<void> _recargar() async {
    final generacion = ++_generacion;
    final empresaId = ref.read(empresaLocalIdProvider);
    final usuarioId = ref.read(usuarioLocalIdProvider);
    if (empresaId == null || usuarioId == null) {
      setState(() {
        _items = const [];
        _hayMas = false;
        _primeraCarga = false;
        _cargando = false;
      });
      return;
    }
    final cantidad = math.max(_tamanioPagina, _items.length);
    if (!_cargando) setState(() => _cargando = true);
    try {
      final cola = await ref.read(colaOperacionesProvider.future);
      final lista = await cola.listar(
        empresaId: empresaId,
        usuarioId: usuarioId,
        estados: _filtro.estados,
        limite: cantidad + 1,
      );
      if (!mounted || generacion != _generacion) return;
      setState(() {
        _items = lista.take(cantidad).toList();
        _hayMas = lista.length > cantidad;
        _primeraCarga = false;
        _cargando = false;
        _error = null;
      });
    } catch (e) {
      if (!mounted || generacion != _generacion) return;
      setState(() {
        _error = e;
        _primeraCarga = false;
        _cargando = false;
      });
    }
  }

  Future<void> _cargarMas() async {
    if (_cargando || !_hayMas) return;
    final generacion = _generacion;
    final empresaId = ref.read(empresaLocalIdProvider);
    final usuarioId = ref.read(usuarioLocalIdProvider);
    if (empresaId == null || usuarioId == null) return;
    setState(() => _cargando = true);
    try {
      final cola = await ref.read(colaOperacionesProvider.future);
      final lista = await cola.listar(
        empresaId: empresaId,
        usuarioId: usuarioId,
        estados: _filtro.estados,
        limite: _tamanioPagina + 1,
        desplazamiento: _items.length,
      );
      if (!mounted || generacion != _generacion) return;
      setState(() {
        _items = [..._items, ...lista.take(_tamanioPagina)];
        _hayMas = lista.length > _tamanioPagina;
        _cargando = false;
      });
    } catch (e) {
      if (!mounted || generacion != _generacion) return;
      setState(() {
        _error = e;
        _cargando = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final sucursales = ref.watch(sucursalesAutorizadasProvider).valueOrNull ?? const <SucursalLocal>[];
    final hayVarias = sucursales.length > 1;
    final ahora = ref.watch(relojProvider).ahora();

    final Widget? cuerpoVacio;
    if (_primeraCarga) {
      cuerpoVacio = const Padding(
        padding: EdgeInsets.all(AppSpacing.xl),
        child: Center(child: CircularProgressIndicator()),
      );
    } else if (_error != null && _items.isEmpty) {
      cuerpoVacio = _MensajeVacio(
        icono: Icons.error_outline,
        texto: 'No pudimos leer tus operaciones.',
        accion: TextButton(
          style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
          onPressed: () => unawaited(_recargar()),
          child: const Text('Reintentar'),
        ),
      );
    } else if (_items.isEmpty) {
      cuerpoVacio = _MensajeVacio(icono: Icons.inbox_outlined, texto: _filtro.textoVacio);
    } else {
      cuerpoVacio = null;
    }

    final filas = cuerpoVacio != null ? 1 : _items.length + (_hayMas ? 1 : 0);

    return Scaffold(
      appBar: AppBar(title: const Text('Operaciones')),
      body: Column(
        children: [
          const IndicadorConexion.banner(),
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.only(bottom: AppSpacing.xl),
              itemCount: 1 + filas,
              itemBuilder: (context, indice) {
                if (indice == 0) {
                  return _Cabecera(filtro: _filtro, alElegir: _cambiarFiltro);
                }
                if (cuerpoVacio != null) return cuerpoVacio;
                final i = indice - 1;
                if (i >= _items.length) {
                  // La última fila es el aviso de "hay más": al llegar a ella se pide la siguiente página.
                  WidgetsBinding.instance.addPostFrameCallback((_) {
                    if (mounted) unawaited(_cargarMas());
                  });
                  return const Padding(
                    padding: EdgeInsets.all(AppSpacing.md),
                    child: Center(child: SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2))),
                  );
                }
                final op = _items[i];
                final sucursal = hayVarias ? sucursales.where((s) => s.id == op.sucursalId).firstOrNull?.nombre : null;
                return _FilaOperacion(
                  key: ValueKey(op.operacionId),
                  operacion: op,
                  sucursal: sucursal,
                  ahora: ahora,
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

/// Resumen, última sincronización, botón, avisos y filtros: lo de arriba de la lista.
class _Cabecera extends ConsumerStatefulWidget {
  const _Cabecera({required this.filtro, required this.alElegir});

  final _Filtro filtro;
  final ValueChanged<_Filtro> alElegir;

  @override
  ConsumerState<_Cabecera> createState() => _CabeceraState();
}

class _CabeceraState extends ConsumerState<_Cabecera> {
  bool _sincronizando = false;

  Future<void> _sincronizar() async {
    setState(() => _sincronizando = true);
    try {
      await sincronizarYAvisar(context, ref);
    } finally {
      if (mounted) setState(() => _sincronizando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final conteo = ref.watch(conteoOperacionesProvider).valueOrNull;
    final estado = ref.watch(estadoSyncProvider).valueOrNull;
    final ahora = ref.watch(relojProvider).ahora();
    final ocupado = _sincronizando || (estado?.enCurso ?? false);
    final ultima = estado?.ultimaSincronizacion;

    return Padding(
      padding: const EdgeInsets.all(AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const AvisoBloqueoSync(),
          if (conteo != null)
            Text(
              _resumenDeConteo(conteo),
              key: const Key('resumen_conteo'),
              style: tema.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600),
            ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            ultima == null ? 'Aún no se ha sincronizado' : 'Última sincronización: ${textoHace(ahora.difference(ultima))}',
            key: const Key('ultima_sincronizacion'),
            style: tema.textTheme.bodyMedium,
          ),
          const SizedBox(height: AppSpacing.md),
          ElevatedButton(
            style: ElevatedButton.styleFrom(minimumSize: const Size.fromHeight(48)),
            onPressed: ocupado ? null : _sincronizar,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              mainAxisSize: MainAxisSize.min,
              children: [
                if (ocupado) ...[
                  const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  const Text('Sincronizando…'),
                ] else ...[
                  const Icon(Icons.sync, size: 20),
                  const SizedBox(width: AppSpacing.sm),
                  const Text('Sincronizar ahora'),
                ],
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.xs,
            children: [
              for (final f in _Filtro.values)
                ChoiceChip(
                  label: Text(f.texto),
                  selected: f == widget.filtro,
                  onSelected: (_) => widget.alElegir(f),
                ),
            ],
          ),
        ],
      ),
    );
  }

  String _resumenDeConteo(Map<EstadoOperacion, int> conteo) {
    final rechazadas = conteo[EstadoOperacion.rechazada] ?? 0;
    final sincronizadas = conteo[EstadoOperacion.confirmada] ?? 0;
    final partes = [
      '${porEnviar(conteo)} por enviar',
      '${conteo[EstadoOperacion.enConflicto] ?? 0} en conflicto',
      if (rechazadas > 0) rechazadas == 1 ? '1 rechazada' : '$rechazadas rechazadas',
      sincronizadas == 1 ? '1 sincronizada' : '$sincronizadas sincronizadas',
    ];
    return partes.join(' · ');
  }
}

class _MensajeVacio extends StatelessWidget {
  const _MensajeVacio({required this.icono, required this.texto, this.accion});

  final IconData icono;
  final String texto;
  final Widget? accion;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(AppSpacing.xl),
      child: Column(
        children: [
          Icon(icono, size: 36, color: AppColors.textoTenue),
          const SizedBox(height: AppSpacing.md),
          Text(texto, textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodyLarge),
          ?accion,
        ],
      ),
    );
  }
}

/// Una operación de la lista: qué es, cuándo ocurrió, en qué estado está y, si no se aceptó, por qué.
class _FilaOperacion extends ConsumerWidget {
  const _FilaOperacion({super.key, required this.operacion, required this.sucursal, required this.ahora});

  final OperacionPendiente operacion;
  final String? sucursal;
  final DateTime ahora;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tema = Theme.of(context);
    final resumen = ref.watch(resumenFilaProvider(operacion.operacionId)).valueOrNull;
    final detalle = resumen?.detalle;
    final esVenta = operacion.tipo == TipoOperacion.ventaContado;

    var titulo = tituloDeTipo(operacion.tipo);
    if (esVenta && detalle?.totalCentavos != null) {
      titulo = '$titulo · ${formatearBs(detalle!.totalCentavos!)}';
    } else if (!esVenta && detalle?.clienteNombre != null) {
      titulo = '$titulo · ${detalle!.clienteNombre}';
    }

    final fecha = textoFechaOperacion(operacion.fechaOperacion, ahora);
    final cuando = sucursal == null ? fecha : '$sucursal · $fecha';
    final motivo = resumen?.motivo;
    final colorMotivo = operacion.estado == EstadoOperacion.rechazada ? AppColors.error : AppColors.advertencia;

    return Column(
      children: [
        InkWell(
          onTap: () => context.push('/vendedor/operaciones/${operacion.operacionId}'),
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 64),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.sm),
              child: Row(
                children: [
                  Icon(
                    esVenta ? Icons.point_of_sale : Icons.event_available_outlined,
                    size: 24,
                    color: AppColors.textoTenue,
                  ),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(titulo, style: tema.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600)),
                        const SizedBox(height: AppSpacing.xs),
                        Wrap(
                          spacing: AppSpacing.sm,
                          runSpacing: AppSpacing.xs,
                          crossAxisAlignment: WrapCrossAlignment.center,
                          children: [
                            EtiquetaEstadoSync(estado: operacion.estado),
                            Text(cuando, style: tema.textTheme.bodyMedium),
                          ],
                        ),
                        if (motivo != null)
                          Padding(
                            padding: const EdgeInsets.only(top: AppSpacing.xs),
                            child: Text(motivo.titulo, style: TextStyle(color: colorMotivo, fontSize: 14)),
                          ),
                      ],
                    ),
                  ),
                  const Icon(Icons.chevron_right, size: 24, color: AppColors.textoTenue),
                ],
              ),
            ),
          ),
        ),
        const Divider(height: 1, color: AppColors.borde),
      ],
    );
  }
}
