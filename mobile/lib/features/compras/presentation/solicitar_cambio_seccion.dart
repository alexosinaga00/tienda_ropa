import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/conectividad/conectividad_service.dart';
import '../../../core/network/mensaje_error.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/fecha_servidor.dart';
import '../../../core/widgets/boton_cargando.dart';
import '../models/solicitud_cambio.dart';
import '../models/venta.dart';
import '../state/compras_providers.dart';

const _colorEstadoSolicitud = {
  'pendiente': AppColors.advertencia,
  'aprobada': AppColors.exito,
  'rechazada': AppColors.error,
};

/// El cliente pide cambiar la talla o el color de una prenda de su compra (CU-17, Etapa 2) y ve cómo van sus
/// solicitudes. El pedido no mueve stock ni reserva la prenda nueva: el personal de la sucursal lo aprueba o lo
/// rechaza cuando el cliente lleva la prenda. Se pueden pedir varias prendas en una sola solicitud.
///
/// El formulario solo aparece con el plazo de cambio vigente; la lista de solicitudes se ve siempre que haya alguna.
class SolicitarCambioSeccion extends ConsumerStatefulWidget {
  const SolicitarCambioSeccion({required this.venta, super.key});

  final Venta venta;

  @override
  ConsumerState<SolicitarCambioSeccion> createState() => _SolicitarCambioSeccionState();
}

class _SolicitarCambioSeccionState extends ConsumerState<SolicitarCambioSeccion> {
  /// Por línea de la compra (id del detalle): cuántas unidades se cambian y por cuál variante.
  final _cantidades = <int, int>{};
  final _elegidas = <int, int>{};
  final _motivo = TextEditingController();
  final _cancelando = <int>{};
  bool _enviando = false;
  String? _error;
  String? _exito;

  @override
  void dispose() {
    _motivo.dispose();
    super.dispose();
  }

  Venta get _venta => widget.venta;

  Future<void> _enviar(Map<int, List<OpcionCambio>> porLinea) async {
    final lineas = <LineaSolicitudCambio>[];
    for (final linea in _venta.lineasCambiables) {
      final cantidad = (_cantidades[linea.id] ?? 0).clamp(0, linea.cantidadRestante);
      if (cantidad <= 0) continue;
      final nombre = linea.productoNombre ?? 'la prenda';
      final nueva = _elegidas[linea.id];
      if (nueva == null) {
        setState(() => _error = 'Elige la talla o el color nuevo de $nombre.');
        return;
      }
      final opcion = (porLinea[linea.id] ?? const <OpcionCambio>[]).where((o) => o.varianteId == nueva).firstOrNull;
      if (opcion != null && cantidad > opcion.disponible) {
        setState(() => _error = 'Solo quedan ${opcion.disponible} de ${opcion.etiqueta}. Pide menos unidades.');
        return;
      }
      lineas.add(LineaSolicitudCambio(ventaDetalleId: linea.id, cantidad: cantidad, varianteNuevaId: nueva));
    }
    if (lineas.isEmpty) {
      setState(() => _error = 'Indica cuántas unidades quieres cambiar y por cuál talla o color.');
      return;
    }

    setState(() {
      _enviando = true;
      _error = null;
      _exito = null;
    });
    try {
      final solicitud = await ref
          .read(solicitudesCambioRepositoryProvider)
          .solicitar(ventaId: _venta.id, lineas: lineas, motivo: _motivo.text);
      refrescarDespuesDeSolicitudCambio(ref, _venta.id);
      final sucursal = await ref.read(nombreSucursalProvider(solicitud.sucursalId).future);
      if (!mounted) return;
      setState(() {
        _enviando = false;
        _cantidades.clear();
        _elegidas.clear();
        _motivo.clear();
        _exito =
            'Solicitud ${solicitud.codigo} enviada. Lleva la prenda a '
            '${sucursal != null ? 'la sucursal $sucursal' : 'la tienda'} antes del '
            '${formatearFechaHora(solicitud.atenderHasta)}.';
      });
    } catch (e) {
      // Ya había una pendiente o cambió algo: se vuelve a leer para que la pantalla diga la verdad.
      refrescarDespuesDeSolicitudCambio(ref, _venta.id);
      if (!mounted) return;
      setState(() {
        _enviando = false;
        _error = esSinConexion(e)
            ? 'Requiere conexión. Revisa tu internet e intenta de nuevo.'
            : mensajeDeError(e, 'No se pudo enviar la solicitud. Intenta de nuevo.');
      });
    }
  }

  Future<void> _cancelar(SolicitudCambio solicitud) async {
    final confirmado = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('¿Cancelar la solicitud?'),
        content: const Text('Ya no tendrás que llevar la prenda a la tienda por este pedido.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('No')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Sí, cancelar')),
        ],
      ),
    );
    if (confirmado != true || !mounted) return;

    setState(() => _cancelando.add(solicitud.id));
    try {
      await ref.read(solicitudesCambioRepositoryProvider).cancelar(solicitud.id);
      refrescarDespuesDeSolicitudCambio(ref, _venta.id);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Solicitud cancelada.')));
    } catch (e) {
      refrescarDespuesDeSolicitudCambio(ref, _venta.id);
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(mensajeDeError(e, 'No se pudo cancelar la solicitud. Intenta de nuevo.'))));
    } finally {
      if (mounted) setState(() => _cancelando.remove(solicitud.id));
    }
  }

  @override
  Widget build(BuildContext context) {
    // Toda la compra ya se devolvió: no hay nada que cambiar, así que ni siquiera se pide el plazo al servidor.
    if (!_venta.hayPrendasCambiables) return const SizedBox.shrink();
    final plazo = ref.watch(plazoCambioProvider(_venta.id)).valueOrNull;
    final solicitudes = ref.watch(misSolicitudesCambioProvider(_venta.id));
    final enLinea = ref.watch(enLineaProvider).valueOrNull ?? true;
    final pendientes = <int>{
      for (final s in solicitudes.valueOrNull ?? const <SolicitudCambio>[])
        if (s.estaPendiente) ...s.detalle.map((l) => l.ventaDetalleId),
    };

    final hijos = <Widget>[
      if (plazo != null && plazo.vigente) _formulario(pendientes, enLinea),
      if (_exito != null) _MensajeExito(texto: _exito!),
      ...solicitudes.when(
        loading: () => const <Widget>[],
        error: (e, s) => [_ErrorLista(alReintentar: () => ref.invalidate(misSolicitudesCambioProvider(_venta.id)))],
        data: (lista) => [
          if (lista.isNotEmpty) const _TituloLista(),
          for (final s in lista)
            _TarjetaSolicitud(solicitud: s, cancelando: _cancelando.contains(s.id), alCancelar: () => _cancelar(s)),
        ],
      ),
    ];
    if (hijos.isEmpty) return const SizedBox.shrink();

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < hijos.length; i++) ...[if (i > 0) const SizedBox(height: AppSpacing.sm), hijos[i]],
        ],
      ),
    );
  }

  Widget _formulario(Set<int> bloqueadas, bool enLinea) {
    final opciones = ref.watch(opcionesCambioProvider(_venta.id));
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Cambiar talla o color', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
            const SizedBox(height: AppSpacing.xs),
            const Text(
              'Elige la prenda y la talla o el color que quieres en su lugar. Después llévala a la tienda para que '
              'aprueben el pedido.',
              style: TextStyle(color: AppColors.textoTenue, fontSize: 13),
            ),
            if (_venta.avisoDevolucionParcial != null) ...[
              const SizedBox(height: AppSpacing.xs),
              Text(
                _venta.avisoDevolucionParcial!,
                key: const Key('aviso-devolucion-parcial'),
                style: const TextStyle(color: AppColors.advertencia, fontSize: 13),
              ),
            ],
            const SizedBox(height: AppSpacing.sm),
            opciones.when(
              loading: () => const Padding(
                padding: EdgeInsets.all(AppSpacing.md),
                child: Center(child: CircularProgressIndicator(color: AppColors.acento)),
              ),
              error: (e, s) => Row(
                children: [
                  const Expanded(
                    child: Text(
                      'No se pudieron cargar las tallas disponibles.',
                      style: TextStyle(color: AppColors.error, fontSize: 13),
                    ),
                  ),
                  TextButton(
                    onPressed: () => ref.invalidate(opcionesCambioProvider(_venta.id)),
                    child: const Text('Reintentar'),
                  ),
                ],
              ),
              data: (porLinea) => _lineas(porLinea, bloqueadas, enLinea),
            ),
          ],
        ),
      ),
    );
  }

  Widget _lineas(Map<int, List<OpcionCambio>> porLinea, Set<int> bloqueadas, bool enLinea) {
    final lineas = [
      for (final l in _venta.lineasCambiables)
        if ((porLinea[l.id] ?? const <OpcionCambio>[]).isNotEmpty) l,
    ];
    if (lineas.isEmpty) {
      return const Text(
        'No hay otra talla o color con stock para esta compra.',
        style: TextStyle(color: AppColors.textoTenue, fontSize: 13),
      );
    }
    final puedeEnviar = enLinea && !_enviando && _cantidades.values.any((c) => c > 0);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final l in lineas) _fila(l, porLinea[l.id]!, bloqueadas.contains(l.id)),
        TextField(
          key: const Key('motivo-cambio'),
          controller: _motivo,
          maxLength: 300,
          textCapitalization: TextCapitalization.sentences,
          decoration: const InputDecoration(labelText: 'Motivo (opcional)'),
        ),
        if (_error != null) ...[
          Text(_error!, key: const Key('error-solicitud-cambio'), style: const TextStyle(color: AppColors.error)),
          const SizedBox(height: AppSpacing.sm),
        ],
        ElevatedButton(
          key: const Key('enviar-solicitud-cambio'),
          onPressed: puedeEnviar ? () => _enviar(porLinea) : null,
          child: _enviando ? const BotonCargando() : const Text('Solicitar cambio'),
        ),
        if (!enLinea)
          const Padding(
            padding: EdgeInsets.only(top: AppSpacing.xs),
            child: Text(
              'Requiere conexión',
              textAlign: TextAlign.center,
              style: TextStyle(color: AppColors.textoTenue, fontSize: 13),
            ),
          ),
      ],
    );
  }

  Widget _fila(VentaLinea linea, List<OpcionCambio> opciones, bool bloqueada) {
    final cantidad = _cantidades[linea.id] ?? 0;
    final detalle = [
      if (linea.tallaCodigo != null) linea.tallaCodigo!,
      if (linea.colorNombre != null) linea.colorNombre!,
      'compraste ${linea.cantidad}',
      if (linea.cantidadDevuelta > 0) 'devolviste ${linea.cantidadDevuelta}',
    ].join(' · ');
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(linea.productoNombre ?? 'Prenda', style: const TextStyle(fontWeight: FontWeight.w600)),
          Text(detalle, style: const TextStyle(color: AppColors.textoTenue, fontSize: 13)),
          if (bloqueada)
            const Padding(
              padding: EdgeInsets.only(top: AppSpacing.xs),
              child: Text(
                'Ya tienes una solicitud pendiente para esta prenda.',
                style: TextStyle(color: AppColors.advertencia, fontSize: 13),
              ),
            )
          else ...[
            Row(
              children: [
                const Text('Unidades a cambiar'),
                const Spacer(),
                IconButton(
                  key: Key('menos-${linea.id}'),
                  tooltip: 'Quitar una unidad',
                  icon: const Icon(Icons.remove_circle_outline),
                  onPressed: cantidad > 0 ? () => setState(() => _cantidades[linea.id] = cantidad - 1) : null,
                ),
                SizedBox(
                  width: 28,
                  child: Text('$cantidad', textAlign: TextAlign.center, style: const TextStyle(fontSize: 16)),
                ),
                IconButton(
                  key: Key('mas-${linea.id}'),
                  tooltip: 'Agregar una unidad',
                  icon: const Icon(Icons.add_circle_outline),
                  onPressed: cantidad < linea.cantidadRestante
                      ? () => setState(() => _cantidades[linea.id] = cantidad + 1)
                      : null,
                ),
              ],
            ),
            DropdownButtonFormField<int>(
              key: Key('cambiar-por-${linea.id}'),
              initialValue: _elegidas[linea.id],
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Cambiar por'),
              items: [
                for (final o in opciones)
                  DropdownMenuItem(value: o.varianteId, child: Text('${o.etiqueta} · quedan ${o.disponible}')),
              ],
              onChanged: (valor) => setState(() {
                if (valor == null) return;
                _elegidas[linea.id] = valor;
                // Elegir la talla ya implica cambiar una unidad.
                if ((_cantidades[linea.id] ?? 0) == 0) _cantidades[linea.id] = 1;
              }),
            ),
          ],
        ],
      ),
    );
  }
}

class _MensajeExito extends StatelessWidget {
  const _MensajeExito({required this.texto});

  final String texto;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.check_circle_outline, color: AppColors.exito, size: 28),
            const SizedBox(width: AppSpacing.md),
            Expanded(child: Text(texto, key: const Key('solicitud-enviada'))),
          ],
        ),
      ),
    );
  }
}

class _TituloLista extends StatelessWidget {
  const _TituloLista();

  @override
  Widget build(BuildContext context) {
    return const Text('Tus solicitudes', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 15));
  }
}

class _ErrorLista extends StatelessWidget {
  const _ErrorLista({required this.alReintentar});

  final VoidCallback alReintentar;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        const Expanded(
          child: Text(
            'No se pudieron cargar tus solicitudes.',
            style: TextStyle(color: AppColors.textoTenue, fontSize: 13),
          ),
        ),
        TextButton(onPressed: alReintentar, child: const Text('Reintentar')),
      ],
    );
  }
}

class _TarjetaSolicitud extends StatelessWidget {
  const _TarjetaSolicitud({required this.solicitud, required this.cancelando, required this.alCancelar});

  final SolicitudCambio solicitud;
  final bool cancelando;
  final VoidCallback alCancelar;

  @override
  Widget build(BuildContext context) {
    final color = _colorEstadoSolicitud[solicitud.estado] ?? AppColors.textoTenue;
    return Card(
      key: Key('solicitud-${solicitud.id}'),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(solicitud.codigo, style: const TextStyle(fontWeight: FontWeight.w700)),
                Chip(
                  label: Text(solicitud.etiquetaEstado, style: TextStyle(fontSize: 12, color: color)),
                  backgroundColor: AppColors.fondoAlterno,
                ),
              ],
            ),
            for (final l in solicitud.detalle)
              Padding(
                padding: const EdgeInsets.only(top: AppSpacing.xs),
                child: Text(
                  '${l.prendaDevuelta} → ${l.prendaNueva ?? 'otra talla'} (x${l.cantidad})',
                  style: const TextStyle(fontSize: 13),
                ),
              ),
            if (solicitud.motivo != null && solicitud.motivo!.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: AppSpacing.xs),
                child: Text(
                  'Tu motivo: ${solicitud.motivo}',
                  style: const TextStyle(color: AppColors.textoTenue, fontSize: 13),
                ),
              ),
            if (solicitud.estado == 'rechazada' && solicitud.motivoRechazo != null)
              Padding(
                padding: const EdgeInsets.only(top: AppSpacing.xs),
                child: Text(
                  'Motivo del rechazo: ${solicitud.motivoRechazo}',
                  style: const TextStyle(color: AppColors.error, fontSize: 13),
                ),
              ),
            if (solicitud.estaPendiente) ...[
              const SizedBox(height: AppSpacing.xs),
              Text(
                'Llévala a la tienda antes del ${formatearFechaHora(solicitud.atenderHasta)}.',
                style: const TextStyle(color: AppColors.textoTenue, fontSize: 13),
              ),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  key: Key('cancelar-solicitud-${solicitud.id}'),
                  onPressed: cancelando ? null : alCancelar,
                  child: cancelando ? const BotonCargando() : const Text('Cancelar solicitud'),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
