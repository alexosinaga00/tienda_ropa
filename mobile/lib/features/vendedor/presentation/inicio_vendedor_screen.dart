import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/conectividad/conectividad_service.dart';
import '../../../core/sesion/dialogos_sesion.dart';
import '../../../core/sync/operacion_pendiente.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/indicador_conexion.dart';
import '../../auth/models/usuario.dart';
import '../../auth/state/auth_controller.dart';
import '../../tienda/presentation/marca_tienda.dart';
import '../../tienda/state/tienda_controller.dart';
import '../state/catalogo_local_providers.dart';
import '../state/descarga_controller.dart';
import '../state/sincronizacion_providers.dart';
import 'aviso_bloqueo_sync.dart';
import 'aviso_pendientes_ajenos.dart';
import 'aviso_vigencia.dart';

/// El nombre legible del primer rol de la cuenta; un rol desconocido se muestra tal cual.
String rolLegible(List<String> roles) {
  if (roles.isEmpty) return 'Personal';
  return switch (roles.first) {
    'administrador' => 'Administrador',
    'encargado_sucursal' => 'Encargado de sucursal',
    'cajero' => 'Cajero',
    final otro => otro,
  };
}

/// Inicio del personal. PROVISIONAL: las siguientes etapas reemplazan el cuerpo (caja, reservas...); el nombre del
/// archivo, la clase y la ruta `/vendedor` se mantienen.
class InicioVendedorScreen extends ConsumerStatefulWidget {
  const InicioVendedorScreen({super.key});

  @override
  ConsumerState<InicioVendedorScreen> createState() => _InicioVendedorScreenState();
}

class _InicioVendedorScreenState extends ConsumerState<InicioVendedorScreen> {
  @override
  void initState() {
    super.initState();
    // Una sesión restaurada sin red se confirma con el servidor apenas se pueda (después del primer frame).
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (!ref.read(authControllerProvider).verificada) {
        ref.read(authControllerProvider.notifier).verificarSesion();
      }
      // Al entrar con conexión se actualizan los datos para trabajar sin red (no hace nada sin conexión).
      unawaited(ref.read(descargaControllerProvider.notifier).alEntrar());
    });
  }

  @override
  Widget build(BuildContext context) {
    // Al volver la conexión se reintenta la verificación (`verificarSesion` no hace nada si ya está verificada) y se
    // actualizan los datos si los últimos tienen más de 15 minutos.
    ref.listen<AsyncValue<bool>>(enLineaProvider, (anterior, actual) {
      if (actual.valueOrNull != true || anterior?.valueOrNull != false) return;
      if (!ref.read(authControllerProvider).verificada) {
        ref.read(authControllerProvider.notifier).verificarSesion();
      }
      unawaited(ref.read(descargaControllerProvider.notifier).alRecuperarConexion());
    });

    final auth = ref.watch(authControllerProvider);
    final tienda = ref.watch(tiendaActualProvider);
    final usuario = auth.usuario;

    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: false,
        title: MarcaTienda(tienda: tienda),
      ),
      body: usuario == null
          ? const Center(child: CircularProgressIndicator())
          : Column(
              children: [
                const IndicadorConexion.banner(),
                Expanded(
                  child: ListView(
                    padding: const EdgeInsets.all(AppSpacing.lg),
                    children: [
                      _TarjetaSaludo(
                        usuario: usuario,
                        nombreTienda: tienda?.nombre ?? usuario.empresaNombre ?? '',
                        verificada: auth.verificada,
                      ),
                      const AvisoPendientesAjenos(),
                      const SizedBox(height: AppSpacing.lg),
                      const AvisoBloqueoSync(),
                      const _TarjetaNuevaVenta(),
                      const SizedBox(height: AppSpacing.sm),
                      const _TarjetaNuevaReserva(),
                      const SizedBox(height: AppSpacing.sm),
                      const _TarjetaOperaciones(),
                      const SizedBox(height: AppSpacing.sm),
                      const _TarjetaCatalogo(),
                      const SizedBox(height: AppSpacing.sm),
                      const _TarjetaActualizar(),
                      const SizedBox(height: AppSpacing.xl),
                      OutlinedButton(
                        style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(48)),
                        onPressed: () => cambiarDeTiendaConAviso(context, ref),
                        child: const Text('Cambiar de tienda'),
                      ),
                      const SizedBox(height: AppSpacing.md),
                      ElevatedButton(
                        style: ElevatedButton.styleFrom(minimumSize: const Size.fromHeight(48)),
                        onPressed: () => cerrarSesionConAviso(context, ref),
                        child: const Text('Cerrar sesión'),
                      ),
                    ],
                  ),
                ),
              ],
            ),
    );
  }
}

/// "Nueva venta de contado": registra una venta en efectivo, con o sin conexión.
class _TarjetaNuevaVenta extends StatelessWidget {
  const _TarjetaNuevaVenta();

  @override
  Widget build(BuildContext context) {
    return _TarjetaAccion(
      icono: Icons.point_of_sale,
      titulo: 'Nueva venta de contado',
      subtitulo: 'Cobra en efectivo, con o sin conexión',
      alPulsar: () => context.push('/vendedor/venta/nueva'),
    );
  }
}

/// "Nueva reserva": aparta prendas para que un cliente las pruebe en la tienda.
class _TarjetaNuevaReserva extends StatelessWidget {
  const _TarjetaNuevaReserva();

  @override
  Widget build(BuildContext context) {
    return _TarjetaAccion(
      icono: Icons.event_available_outlined,
      titulo: 'Nueva reserva',
      subtitulo: 'Aparta prendas para la visita de un cliente',
      alPulsar: () => context.push('/vendedor/reserva/nueva'),
    );
  }
}

/// "Operaciones": lo registrado en este teléfono, con una insignia de lo que pide atención.
class _TarjetaOperaciones extends ConsumerWidget {
  const _TarjetaOperaciones();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final conteo = ref.watch(conteoOperacionesProvider).valueOrNull;
    final pendientes = conteo == null ? 0 : porAtender(conteo);
    return _TarjetaAccion(
      icono: Icons.receipt_long_outlined,
      titulo: 'Operaciones',
      subtitulo: conteo == null ? 'Ventas y reservas de este teléfono' : _subtituloOperaciones(conteo),
      insignia: pendientes,
      alPulsar: () => context.push('/vendedor/operaciones'),
    );
  }
}

/// "3 por enviar · 1 en conflicto · 2 rechazadas", o "Todo al día" si nada espera.
String _subtituloOperaciones(Map<EstadoOperacion, int> conteo) {
  final porEnviarN = porEnviar(conteo);
  final enConflicto = conteo[EstadoOperacion.enConflicto] ?? 0;
  final rechazadas = conteo[EstadoOperacion.rechazada] ?? 0;
  final partes = [
    if (porEnviarN > 0) '$porEnviarN por enviar',
    if (enConflicto > 0) '$enConflicto en conflicto',
    if (rechazadas > 0) rechazadas == 1 ? '1 rechazada' : '$rechazadas rechazadas',
  ];
  return partes.isEmpty ? 'Todo al día' : partes.join(' · ');
}

/// "Catálogo sin conexión": entra a la consulta del catálogo descargado.
class _TarjetaCatalogo extends ConsumerWidget {
  const _TarjetaCatalogo();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final vigencia = ref.watch(vigenciaProvider).valueOrNull;
    final descargadoEn = vigencia?.descargadoEn;
    final subtitulo = descargadoEn == null ? 'Aún sin datos' : 'Datos del ${fechaCortaLocal(descargadoEn)}';
    return _TarjetaAccion(
      icono: Icons.inventory_2_outlined,
      titulo: 'Catálogo sin conexión',
      subtitulo: subtitulo,
      alPulsar: () => context.push('/vendedor/catalogo'),
    );
  }
}

/// "Actualizar datos": baja otra vez el catálogo, el stock y los clientes de la sucursal activa.
class _TarjetaActualizar extends ConsumerWidget {
  const _TarjetaActualizar();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final vigencia = ref.watch(vigenciaProvider).valueOrNull;
    final enLinea = ref.watch(enLineaProvider).valueOrNull ?? true;
    final descarga = ref.watch(descargaControllerProvider);
    final descargadoEn = vigencia?.descargadoEn;
    final subtitulo = descargadoEn == null
        ? 'Aún no hay datos descargados'
        : 'Última actualización: ${fechaCortaLocal(descargadoEn)}';
    final puede = enLinea && !descarga.descargando;

    return _TarjetaAccion(
      icono: Icons.sync,
      titulo: 'Actualizar datos',
      subtitulo: enLinea ? subtitulo : '$subtitulo\nSin conexión: no se puede actualizar ahora.',
      progreso: descarga.descargando,
      mensaje: descarga.mensaje,
      mensajeEsError: descarga.esError,
      alPulsar: puede ? () => unawaited(ref.read(descargaControllerProvider.notifier).actualizar()) : null,
    );
  }
}

class _TarjetaAccion extends StatelessWidget {
  const _TarjetaAccion({
    required this.icono,
    required this.titulo,
    required this.subtitulo,
    required this.alPulsar,
    this.progreso = false,
    this.mensaje,
    this.mensajeEsError = false,
    this.insignia = 0,
  });

  final IconData icono;
  final String titulo;
  final String subtitulo;
  final VoidCallback? alPulsar;

  /// Cuántas cosas piden atención; no se dibuja si es cero.
  final int insignia;
  final bool progreso;
  final String? mensaje;
  final bool mensajeEsError;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Card(
      elevation: 0,
      margin: EdgeInsets.zero,
      color: AppColors.fondo,
      clipBehavior: Clip.antiAlias,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.base),
        side: const BorderSide(color: AppColors.borde),
      ),
      child: InkWell(
        onTap: alPulsar,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 64),
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.md),
            child: Row(
              children: [
                Icon(icono, size: 24, color: alPulsar == null ? AppColors.textoTenue : AppColors.acento),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(titulo, style: tema.textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600)),
                      const SizedBox(height: AppSpacing.xs),
                      Text(subtitulo, style: tema.textTheme.bodyMedium),
                      if (progreso)
                        const Padding(
                          padding: EdgeInsets.only(top: AppSpacing.xs),
                          child: Text('Actualizando datos…', style: TextStyle(color: AppColors.texto, fontSize: 14)),
                        ),
                      if (mensaje != null)
                        Padding(
                          padding: const EdgeInsets.only(top: AppSpacing.xs),
                          child: Text(
                            mensaje!,
                            style: TextStyle(color: mensajeEsError ? AppColors.error : AppColors.advertencia, fontSize: 14),
                          ),
                        ),
                    ],
                  ),
                ),
                if (insignia > 0) ...[
                  Semantics(
                    label: '$insignia por atender',
                    excludeSemantics: true,
                    child: Container(
                      key: const Key('insignia_operaciones'),
                      constraints: const BoxConstraints(minWidth: 24, minHeight: 24),
                      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm),
                      alignment: Alignment.center,
                      decoration: BoxDecoration(color: AppColors.advertencia, borderRadius: BorderRadius.circular(12)),
                      child: Text(
                        insignia > 99 ? '99+' : '$insignia',
                        style: const TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w700),
                      ),
                    ),
                  ),
                  const SizedBox(width: AppSpacing.sm),
                ],
                if (progreso)
                  const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2))
                else if (alPulsar != null)
                  const Icon(Icons.chevron_right, size: 24, color: AppColors.textoTenue),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _TarjetaSaludo extends StatelessWidget {
  const _TarjetaSaludo({required this.usuario, required this.nombreTienda, required this.verificada});

  final Usuario usuario;
  final String nombreTienda;
  final bool verificada;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Card(
      elevation: 0,
      color: AppColors.fondoAlterno,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.base),
        side: const BorderSide(color: AppColors.borde),
      ),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Hola, ${usuario.nombre}', style: tema.textTheme.headlineMedium),
            const SizedBox(height: AppSpacing.sm),
            Text(rolLegible(usuario.roles), style: tema.textTheme.bodyLarge),
            if (nombreTienda.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.xs),
              Text(nombreTienda, style: tema.textTheme.bodyMedium),
            ],
            const SizedBox(height: AppSpacing.md),
            Row(
              children: [
                Icon(
                  verificada ? Icons.verified_user_outlined : Icons.warning_amber_rounded,
                  size: 20,
                  color: verificada ? AppColors.exito : AppColors.advertencia,
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(
                    verificada ? 'Sesión verificada' : 'Sesión sin verificar: sin conexión',
                    style: TextStyle(
                      color: verificada ? AppColors.exito : AppColors.advertencia,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
