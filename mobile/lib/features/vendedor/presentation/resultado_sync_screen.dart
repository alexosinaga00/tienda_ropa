import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/sync/cola_operaciones.dart';
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
import 'aviso_vigencia.dart' show fechaCortaLocal;
import 'textos_sync.dart';

/// Qué pasó con UNA operación hecha sin conexión y qué hacer. [esNueva] es verdadero justo después de registrarla: se muestra la
/// confirmación y los atajos para seguir trabajando. Se actualiza sola con cada cambio de la cola.
class ResultadoSyncScreen extends ConsumerStatefulWidget {
  const ResultadoSyncScreen({super.key, required this.operacionId, this.esNueva = false});

  final String operacionId;
  final bool esNueva;

  @override
  ConsumerState<ResultadoSyncScreen> createState() => _ResultadoSyncScreenState();
}

class _ResultadoSyncScreenState extends ConsumerState<ResultadoSyncScreen> {
  bool _reintentando = false;

  Future<void> _reintentar() async {
    setState(() => _reintentando = true);
    try {
      await sincronizarYAvisar(context, ref);
    } finally {
      if (mounted) setState(() => _reintentando = false);
    }
  }

  Future<void> _copiar(String codigo) async {
    final mensajero = ScaffoldMessenger.of(context);
    await Clipboard.setData(ClipboardData(text: codigo));
    mensajero
      ..hideCurrentSnackBar()
      ..showSnackBar(const SnackBar(content: Text('Código copiado')));
  }

  @override
  Widget build(BuildContext context) {
    final datos = ref.watch(datosResultadoProvider(widget.operacionId));

    final Widget cuerpo;
    if (datos.hasValue) {
      final d = datos.value;
      cuerpo = d == null ? const _NoEncontrada() : _contenido(context, d);
    } else if (datos.hasError) {
      cuerpo = _Mensaje(
        icono: Icons.error_outline,
        texto: 'No pudimos leer esta operación.',
        accion: TextButton(
          style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
          onPressed: () => ref.invalidate(datosResultadoProvider(widget.operacionId)),
          child: const Text('Reintentar'),
        ),
      );
    } else {
      cuerpo = const Center(child: CircularProgressIndicator());
    }

    return Scaffold(
      appBar: AppBar(title: const Text('Operación')),
      body: Column(
        children: [
          const IndicadorConexion.banner(),
          Expanded(child: cuerpo),
        ],
      ),
    );
  }

  Widget _contenido(BuildContext context, DatosResultado d) {
    final op = d.operacion;
    final estadoSync = ref.watch(estadoSyncProvider).valueOrNull;
    final ocupado = _reintentando || (estadoSync?.enCurso ?? false);
    final sucursales = ref.watch(sucursalesAutorizadasProvider).valueOrNull ?? const <SucursalLocal>[];
    final sucursal = sucursales.where((s) => s.id == op.sucursalId).firstOrNull?.nombre;
    final ahora = ref.watch(relojProvider).ahora();

    return ListView(
      padding: const EdgeInsets.all(AppSpacing.md),
      children: [
        if (widget.esNueva) ...[
          _FranjaNueva(operacion: op),
          const SizedBox(height: AppSpacing.md),
        ],
        _CabeceraResultado(operacion: op, ahora: ahora, alCopiar: () => unawaited(_copiar(op.codigoCorto))),
        const SizedBox(height: AppSpacing.md),
        if (op.estado.seEnvia) const AvisoBloqueoSync(),
        _SeccionEstado(datos: d),
        if (op.estado.seEnvia) ...[
          const SizedBox(height: AppSpacing.md),
          ElevatedButton(
            style: ElevatedButton.styleFrom(minimumSize: const Size.fromHeight(48)),
            onPressed: ocupado ? null : _reintentar,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              mainAxisSize: MainAxisSize.min,
              children: [
                if (ocupado) ...[
                  const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)),
                  const SizedBox(width: AppSpacing.sm),
                  const Text('Enviando…'),
                ] else
                  const Text('Reintentar ahora'),
              ],
            ),
          ),
        ],
        const SizedBox(height: AppSpacing.md),
        _Resumen(detalle: d.detalle, sucursal: sucursal),
        const SizedBox(height: AppSpacing.md),
        _Historial(datos: d),
      ],
    );
  }
}

// ---- Piezas -------------------------------------------------------------------------------

class _NoEncontrada extends StatelessWidget {
  const _NoEncontrada();

  @override
  Widget build(BuildContext context) {
    return _Mensaje(
      icono: Icons.search_off,
      texto: 'No encontramos esta operación.',
      accion: OutlinedButton(
        style: OutlinedButton.styleFrom(minimumSize: const Size(120, 48)),
        onPressed: () {
          if (context.canPop()) {
            context.pop();
          } else {
            context.go('/vendedor/operaciones');
          }
        },
        child: const Text('Volver'),
      ),
    );
  }
}

class _Mensaje extends StatelessWidget {
  const _Mensaje({required this.icono, required this.texto, this.accion});

  final IconData icono;
  final String texto;
  final Widget? accion;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icono, size: 36, color: AppColors.textoTenue),
            const SizedBox(height: AppSpacing.md),
            Text(texto, textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodyLarge),
            if (accion != null) ...[const SizedBox(height: AppSpacing.md), accion!],
          ],
        ),
      ),
    );
  }
}

/// "Venta registrada en tu teléfono. Pendiente de envío." con los atajos para seguir.
class _FranjaNueva extends StatelessWidget {
  const _FranjaNueva({required this.operacion});

  final OperacionPendiente operacion;

  @override
  Widget build(BuildContext context) {
    final esVenta = operacion.tipo == TipoOperacion.ventaContado;
    final que = esVenta ? 'Venta' : 'Reserva';
    final texto = operacion.estado.seEnvia
        ? '$que registrada en tu teléfono. Pendiente de envío.'
        : '$que registrada en tu teléfono.';
    const color = AppColors.exito;
    final estiloBoton = ElevatedButton.styleFrom(minimumSize: const Size(0, 48));

    return Semantics(
      container: true,
      liveRegion: true,
      child: Container(
        key: const Key('franja_nueva'),
        width: double.infinity,
        padding: const EdgeInsets.all(AppSpacing.md),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(AppRadius.base),
          border: Border.all(color: color.withValues(alpha: 0.4)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Padding(
                  padding: EdgeInsets.only(top: 2),
                  child: Icon(Icons.check_circle_outline, size: 24, color: color),
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(texto, style: const TextStyle(color: color, fontSize: 16, fontWeight: FontWeight.w600)),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.md),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                ElevatedButton(
                  style: estiloBoton,
                  onPressed: () => context.pushReplacement('/vendedor/venta/nueva'),
                  child: const Text('Nueva venta'),
                ),
                ElevatedButton(
                  style: estiloBoton,
                  onPressed: () => context.pushReplacement('/vendedor/reserva/nueva'),
                  child: const Text('Nueva reserva'),
                ),
                OutlinedButton(
                  style: OutlinedButton.styleFrom(minimumSize: const Size(0, 48)),
                  onPressed: () => context.pushReplacement('/vendedor/operaciones'),
                  child: const Text('Ver pendientes'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// El estado en grande y el código corto con su botón de copiar.
class _CabeceraResultado extends StatelessWidget {
  const _CabeceraResultado({required this.operacion, required this.ahora, required this.alCopiar});

  final OperacionPendiente operacion;
  final DateTime ahora;
  final VoidCallback alCopiar;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return _Tarjeta(
      hijos: [
        Align(alignment: Alignment.centerLeft, child: EtiquetaEstadoSync(estado: operacion.estado, grande: true)),
        const SizedBox(height: AppSpacing.md),
        Text(
          '${tituloDeTipo(operacion.tipo)} · ${textoFechaOperacion(operacion.fechaOperacion, ahora)}',
          style: tema.textTheme.bodyLarge,
        ),
        const SizedBox(height: AppSpacing.xs),
        Row(
          children: [
            Text('Código: ', style: tema.textTheme.bodyMedium),
            Text(
              operacion.codigoCorto,
              key: const Key('codigo_operacion'),
              style: tema.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w700, letterSpacing: 1),
            ),
            const Spacer(),
            IconButton(
              tooltip: 'Copiar código',
              constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
              icon: const Icon(Icons.copy, size: 24),
              onPressed: alCopiar,
            ),
          ],
        ),
      ],
    );
  }
}

/// Qué pasó y qué hacer, según el estado.
class _SeccionEstado extends ConsumerWidget {
  const _SeccionEstado({required this.datos});

  final DatosResultado datos;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final op = datos.operacion;
    final extra = datos.extra;
    final tema = Theme.of(context);
    final nombres = {for (final l in datos.detalle.lineas) l.varianteId: l.nombre};
    String prenda(int varianteId) => nombres[varianteId] ?? 'la prenda';

    final avisos = <Widget>[
      for (final a in extra.avisos)
        if (a.precioActualCentavos != null && a.precioOperacionCentavos != null)
          Padding(
            padding: const EdgeInsets.only(top: AppSpacing.xs),
            child: Text(
              'El precio actual de ${prenda(a.varianteId)} es ${formatearBs(a.precioActualCentavos!)}; '
              'se respetó el que cobraste (${formatearBs(a.precioOperacionCentavos!)})',
              style: tema.textTheme.bodyMedium,
            ),
          ),
    ];

    switch (op.estado) {
      case EstadoOperacion.registrada || EstadoOperacion.enviada:
        final error = op.ultimoError?.trim();
        return _Tarjeta(
          titulo: 'Estado del envío',
          hijos: [
            Text(
              'Todavía no llegó al servidor. Se enviará cuando haya conexión.',
              style: tema.textTheme.bodyLarge,
            ),
            if (error != null && error.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: AppSpacing.sm),
                child: Text('Último intento: $error', style: tema.textTheme.bodyMedium),
              ),
          ],
        );

      case EstadoOperacion.confirmada:
        final codigo = extra.recursoCodigo;
        final cambio = extra.cambioCentavos;
        final que = op.tipo == TipoOperacion.ventaContado ? 'Venta' : 'Reserva';
        return _Tarjeta(
          titulo: 'Confirmada por el servidor',
          hijos: [
            Text(
              codigo == null ? 'Tu operación ya está en el servidor.' : '$que $codigo',
              key: const Key('codigo_recurso'),
              style: tema.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600),
            ),
            if (cambio != null && cambio > 0)
              Padding(
                padding: const EdgeInsets.only(top: AppSpacing.xs),
                child: Text('Cambio: ${formatearBs(cambio)}', style: tema.textTheme.bodyLarge),
              ),
            ...avisos,
          ],
        );

      case EstadoOperacion.rechazada || EstadoOperacion.enConflicto:
        final enConflicto = op.estado == EstadoOperacion.enConflicto;
        final motivo = motivoDeOperacion(op, datos.resultados);
        final mensajeServidor = datos.ultimo?.motivo?.trim();
        final detalleServidor = mensajeServidor != null && mensajeServidor.isNotEmpty && mensajeServidor != motivo.quePaso
            ? mensajeServidor
            : null;
        final motivoEncargado = extra.resolucionMotivo;
        return _Tarjeta(
          titulo: motivo.titulo,
          hijos: [
            _Parrafo(titulo: 'Qué pasó', texto: motivo.quePaso),
            if (detalleServidor != null) _Parrafo(titulo: 'Detalle del servidor', texto: detalleServidor),
            if (motivoEncargado != null) _Parrafo(titulo: 'Motivo del encargado', texto: motivoEncargado),
            _Parrafo(titulo: 'Qué hacer', texto: motivo.queHacer),
            if (enConflicto)
              Padding(
                padding: const EdgeInsets.only(top: AppSpacing.md),
                child: Text(
                  'Un encargado debe resolverla; aquí se actualizará sola.',
                  style: tema.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600),
                ),
              ),
            if (extra.faltantes.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.md),
              Text('Stock insuficiente', style: tema.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600)),
              for (final f in extra.faltantes)
                Padding(
                  padding: const EdgeInsets.only(top: AppSpacing.xs),
                  child: Text(
                    'De ${prenda(f.varianteId)} pediste ${f.solicitado} y el servidor tiene ${f.disponible}',
                    style: tema.textTheme.bodyMedium,
                  ),
                ),
            ],
            ...avisos,
          ],
        );
    }
  }
}

class _Parrafo extends StatelessWidget {
  const _Parrafo({required this.titulo, required this.texto});

  final String titulo;
  final String texto;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(titulo, style: tema.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
          const SizedBox(height: AppSpacing.xs),
          Text(texto, style: tema.textTheme.bodyLarge),
        ],
      ),
    );
  }
}

/// Qué se vendió o reservó: prendas, cliente, total o visita.
class _Resumen extends StatelessWidget {
  const _Resumen({required this.detalle, required this.sucursal});

  final DetalleOperacion detalle;
  final String? sucursal;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final op = detalle.operacion;
    final esVenta = op.tipo == TipoOperacion.ventaContado;
    final visita = detalle.fechaVisita;
    final horas = (detalle.horaDesde != null && detalle.horaHasta != null)
        ? 'de ${detalle.horaDesde} a ${detalle.horaHasta}'
        : null;
    final observacion = detalle.observacion?.trim();

    return _Tarjeta(
      titulo: 'Resumen',
      hijos: [
        if (sucursal != null) _Dato('Sucursal', sucursal!),
        if (detalle.clienteNombre != null) _Dato('Cliente', detalle.clienteNombre!),
        if (!esVenta && visita != null) _Dato('Visita', _fechaVisita(visita) + (horas == null ? '' : ', $horas')),
        if (!esVenta && visita == null && horas != null) _Dato('Visita', horas),
        if (!esVenta && observacion != null && observacion.isNotEmpty) _Dato('Observación', observacion),
        const SizedBox(height: AppSpacing.sm),
        if (detalle.lineas.isEmpty)
          Text('Sin prendas registradas', style: tema.textTheme.bodyMedium)
        else
          for (final l in detalle.lineas) _LineaResumen(linea: l, esVenta: esVenta),
        if (esVenta && detalle.totalCentavos != null) ...[
          const Divider(height: AppSpacing.lg, color: AppColors.borde),
          Row(
            children: [
              Expanded(child: Text('Total', style: tema.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w700))),
              Text(
                formatearBs(detalle.totalCentavos!),
                style: tema.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w700),
              ),
            ],
          ),
          if (detalle.efectivoConfirmado == true)
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.xs),
              child: Row(
                children: [
                  Expanded(child: Text('Efectivo recibido', style: tema.textTheme.bodyMedium)),
                  Text(formatearBs(detalle.totalCentavos!), style: tema.textTheme.bodyMedium),
                ],
              ),
            ),
        ],
      ],
    );
  }

  /// La fecha de la visita viene sin hora ni zona: se escribe tal cual.
  String _fechaVisita(DateTime f) {
    String dos(int n) => n.toString().padLeft(2, '0');
    return '${dos(f.day)}/${dos(f.month)}/${f.year}';
  }
}

class _Dato extends StatelessWidget {
  const _Dato(this.etiqueta, this.valor);

  final String etiqueta;
  final String valor;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xs),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 96, child: Text(etiqueta, style: tema.textTheme.bodyMedium)),
          Expanded(child: Text(valor, style: tema.textTheme.bodyLarge)),
        ],
      ),
    );
  }
}

class _LineaResumen extends StatelessWidget {
  const _LineaResumen({required this.linea, required this.esVenta});

  final LineaDetalle linea;
  final bool esVenta;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final variante = [
      if (linea.talla != null && linea.talla!.isNotEmpty) 'Talla ${linea.talla}',
      if (linea.color != null && linea.color!.isNotEmpty) linea.color!,
    ].join(' · ');
    final precio = linea.precioUnitarioCentavos;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _Miniatura(url: linea.imagenUrl, nombre: linea.nombre),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(linea.nombre, style: tema.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600)),
                if (variante.isNotEmpty) Text(variante, style: tema.textTheme.bodyMedium),
                Text(
                  esVenta && precio != null
                      ? 'Cantidad: ${linea.cantidad} · ${formatearBs(precio)} c/u'
                      : 'Cantidad: ${linea.cantidad}',
                  style: tema.textTheme.bodyMedium,
                ),
              ],
            ),
          ),
          if (esVenta && precio != null) ...[
            const SizedBox(width: AppSpacing.sm),
            Text(
              formatearBs(precio * linea.cantidad),
              style: tema.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600),
            ),
          ],
        ],
      ),
    );
  }
}

/// La foto de la prenda (48 px). Sin foto, o si no carga (sin conexión), un recuadro con la inicial del nombre.
class _Miniatura extends StatelessWidget {
  const _Miniatura({required this.url, required this.nombre});

  final String? url;
  final String nombre;

  @override
  Widget build(BuildContext context) {
    final alterno = Container(
      key: const Key('miniatura_alterna'),
      width: 48,
      height: 48,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: AppColors.fondoAlterno,
        borderRadius: BorderRadius.circular(AppRadius.base),
        border: Border.all(color: AppColors.borde),
      ),
      child: Text(
        nombre.isEmpty ? '?' : nombre.characters.first.toUpperCase(),
        style: const TextStyle(color: AppColors.textoTenue, fontSize: 20, fontWeight: FontWeight.w600),
      ),
    );
    final direccion = url;
    if (direccion == null || direccion.isEmpty) return alterno;
    return ClipRRect(
      borderRadius: BorderRadius.circular(AppRadius.base),
      child: Image.network(
        direccion,
        width: 48,
        height: 48,
        fit: BoxFit.cover,
        errorBuilder: (context, error, pila) => alterno,
        loadingBuilder: (context, hijo, progreso) => progreso == null ? hijo : alterno,
      ),
    );
  }
}

/// Cuándo se registró y cada respuesta que dio el servidor.
class _Historial extends StatelessWidget {
  const _Historial({required this.datos});

  final DatosResultado datos;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    String etiqueta(String estado) =>
        EstadoOperacion.desdeNombre(estado) == null ? estado : estiloDeEstado(EstadoOperacion.desdeNombre(estado)!).texto;
    final filas = <(DateTime, String)>[
      (datos.operacion.creadaEn, 'Registrada en tu teléfono'),
      for (final r in datos.resultados) (r.recibidoEn, etiqueta(r.estadoResultado)),
    ];
    return _Tarjeta(
      titulo: 'Historial',
      hijos: [
        for (final f in filas)
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.xs),
            child: Text('${fechaCortaLocal(f.$1)} · ${f.$2}', style: tema.textTheme.bodyMedium),
          ),
      ],
    );
  }
}

class _Tarjeta extends StatelessWidget {
  const _Tarjeta({this.titulo, required this.hijos});

  final String? titulo;
  final List<Widget> hijos;

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      margin: EdgeInsets.zero,
      color: AppColors.fondo,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.base),
        side: const BorderSide(color: AppColors.borde),
      ),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (titulo != null) ...[
              Text(titulo!, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
              const SizedBox(height: AppSpacing.sm),
            ],
            ...hijos,
          ],
        ),
      ),
    );
  }
}
