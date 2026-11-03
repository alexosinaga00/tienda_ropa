import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/conectividad/conectividad_service.dart';
import '../../../core/sync/motor_sincronizacion.dart';
import '../../../core/sync/operacion_pendiente.dart';
import '../../../core/theme/app_theme.dart';
import '../state/operaciones_vista_providers.dart';
import 'aviso_vigencia.dart' show fechaCortaLocal;

const textoSesionVencida = 'Tu sesión venció: vuelve a ingresar para enviar';

/// Cómo se ve cada estado: SIEMPRE con texto (el color solo no basta) y un ícono.
class EstiloEstadoSync {
  const EstiloEstadoSync({required this.texto, required this.color, required this.icono});

  final String texto;
  final Color color;
  final IconData icono;
}

EstiloEstadoSync estiloDeEstado(EstadoOperacion estado) => switch (estado) {
  EstadoOperacion.registrada => const EstiloEstadoSync(
    texto: 'Pendiente de envío',
    color: AppColors.textoTenue,
    icono: Icons.schedule,
  ),
  EstadoOperacion.enviada => const EstiloEstadoSync(texto: 'Enviando…', color: AppColors.acento, icono: Icons.sync),
  EstadoOperacion.confirmada => const EstiloEstadoSync(
    texto: 'Sincronizada',
    color: AppColors.exito,
    icono: Icons.check_circle_outline,
  ),
  EstadoOperacion.rechazada => const EstiloEstadoSync(
    texto: 'Rechazada',
    color: AppColors.error,
    icono: Icons.cancel_outlined,
  ),
  EstadoOperacion.enConflicto => const EstiloEstadoSync(
    texto: 'En conflicto',
    color: AppColors.advertencia,
    icono: Icons.warning_amber_rounded,
  ),
};

/// Una etiqueta con ícono y texto del estado de una operación. [grande] es la de la cabecera de la pantalla de resultado.
class EtiquetaEstadoSync extends StatelessWidget {
  const EtiquetaEstadoSync({super.key, required this.estado, this.grande = false});

  final EstadoOperacion estado;
  final bool grande;

  @override
  Widget build(BuildContext context) {
    final estilo = estiloDeEstado(estado);
    return Container(
      padding: EdgeInsets.symmetric(horizontal: grande ? AppSpacing.md : AppSpacing.sm, vertical: grande ? AppSpacing.sm : AppSpacing.xs),
      decoration: BoxDecoration(
        color: estilo.color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(AppRadius.base),
        border: Border.all(color: estilo.color.withValues(alpha: 0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(estilo.icono, size: 20, color: estilo.color),
          const SizedBox(width: AppSpacing.xs),
          Flexible(
            child: Text(
              estilo.texto,
              style: TextStyle(color: estilo.color, fontSize: grande ? 16 : 14, fontWeight: FontWeight.w600),
            ),
          ),
        ],
      ),
    );
  }
}

String tituloDeTipo(TipoOperacion tipo) => switch (tipo) {
  TipoOperacion.ventaContado => 'Venta de contado',
  TipoOperacion.reserva => 'Reserva',
};

/// "hoy 14:35" si la operación fue hoy (en la hora local) y "30/10 14:35" si fue otro día.
String textoFechaOperacion(DateTime fecha, DateTime ahora) {
  final f = fecha.toLocal();
  final a = ahora.toLocal();
  if (f.year == a.year && f.month == a.month && f.day == a.day) {
    String dos(int n) => n.toString().padLeft(2, '0');
    return 'hoy ${dos(f.hour)}:${dos(f.minute)}';
  }
  return fechaCortaLocal(fecha);
}

/// Lo que se le dice a la persona al terminar "Sincronizar ahora". [enLinea] distingue "sin conexión" de un fallo del servidor.
String mensajeDeResumenSync(ResumenSync? resumen, {required bool enLinea}) {
  if (resumen == null) return 'Inicia sesión para sincronizar';
  if (resumen.sesionVencida) return textoSesionVencida;
  final bloqueo = resumen.bloqueo;
  if (bloqueo != null) return bloqueo.mensaje;

  final partes = <String>[];
  if (resumen.confirmadas > 0) {
    partes.add(resumen.confirmadas == 1 ? '1 operación sincronizada' : '${resumen.confirmadas} operaciones sincronizadas');
  }
  final atencion = resumen.rechazadas + resumen.enConflicto;
  if (atencion > 0) partes.add(atencion == 1 ? '1 necesita atención' : '$atencion necesitan atención');
  if (partes.isNotEmpty) return partes.join(' · ');

  if (resumen.fallidasPorRed > 0 || (!resumen.intentado && resumen.pendientes > 0 && !enLinea)) {
    return enLinea ? 'No se pudo enviar ahora. Se reintentará más tarde' : 'Sin conexión: se enviará cuando vuelva';
  }
  return 'No hay nada por enviar';
}

/// Sincroniza a mano y avisa el resultado con un SnackBar. Lo usan el botón "Sincronizar ahora" y "Reintentar ahora".
Future<void> sincronizarYAvisar(BuildContext context, WidgetRef ref) async {
  // Todo lo que depende del contexto o del ref se toma ANTES de esperar: la pantalla puede cerrarse mientras se sincroniza.
  final mensajero = ScaffoldMessenger.of(context);
  final sincronizar = ref.read(sincronizadorProvider);
  final conectividad = ref.read(conectividadServiceProvider);

  String texto;
  try {
    final resumen = await sincronizar(disparador: Disparador.manual);
    texto = mensajeDeResumenSync(resumen, enLinea: conectividad.actual);
  } catch (_) {
    texto = 'No se pudo sincronizar ahora. Inténtalo de nuevo';
  }
  mensajero
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(texto)));
}
