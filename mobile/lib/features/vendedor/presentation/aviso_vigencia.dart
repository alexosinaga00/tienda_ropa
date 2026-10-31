import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/conectividad/conectividad_service.dart';
import '../../../core/theme/app_theme.dart';
import '../data/politica_vigencia.dart';
import '../state/catalogo_local_providers.dart';
import '../state/descarga_controller.dart';

/// "hace 5 min", "hace 3 h", "hace 2 días": qué tan viejo es algo, legible para una persona.
String textoHace(Duration edad) {
  if (edad.isNegative || edad.inMinutes < 1) return 'hace un momento';
  if (edad.inMinutes < 60) return 'hace ${edad.inMinutes} min';
  if (edad.inHours < 24) return 'hace ${edad.inHours} h';
  final dias = edad.inDays;
  return dias == 1 ? 'hace 1 día' : 'hace $dias días';
}

/// "20/10 14:35" en la hora LOCAL del teléfono (la fecha puede venir en UTC).
String fechaCortaLocal(DateTime fecha) {
  final local = fecha.toLocal();
  String dos(int n) => n.toString().padLeft(2, '0');
  return '${dos(local.day)}/${dos(local.month)} ${dos(local.hour)}:${dos(local.minute)}';
}

/// Franja que dice qué tan viejos son los datos de la sucursal activa. NUNCA bloquea nada: solo informa y ofrece actualizar.
///
/// Se muestra si los datos no están frescos O no hay conexión (o mientras se actualiza / hay un mensaje de la descarga).
/// Se reutiliza en el detalle y, más adelante, en la caja.
class AvisoVigencia extends ConsumerWidget {
  const AvisoVigencia({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final vigencia = ref.watch(vigenciaProvider);
    final enLinea = ref.watch(enLineaProvider).valueOrNull ?? true;
    final descarga = ref.watch(descargaControllerProvider);

    // Mientras se calcula por primera vez no se muestra nada; si falla la lectura local, se trata como "nunca descargado".
    final resumen = vigencia.valueOrNull ?? (vigencia.hasError ? const ResumenVigencia(estado: EstadoVigencia.nunca) : null);
    if (resumen == null) return const SizedBox.shrink();

    final avisar = const PoliticaVigencia().debeAvisar(resumen.estado, enLinea: enLinea);
    if (!avisar && !descarga.descargando && descarga.mensaje == null) return const SizedBox.shrink();

    final autorizadas = ref.watch(sucursalesAutorizadasProvider).valueOrNull ?? const [];
    final activaId = ref.watch(sucursalActivaProvider).valueOrNull;
    final sucursal = autorizadas.where((s) => s.id == activaId).firstOrNull?.nombre ?? 'esta sucursal';

    final Color color = switch (resumen.estado) {
      EstadoVigencia.critica => AppColors.error,
      EstadoVigencia.antigua || EstadoVigencia.nunca => AppColors.advertencia,
      EstadoVigencia.fresca => AppColors.textoTenue,
    };

    final String? texto = !avisar ? null : _texto(resumen, sucursal);
    final puedeActualizar = enLinea && !descarga.descargando;

    return Semantics(
      container: true,
      liveRegion: true,
      child: Container(
        key: const Key('aviso_vigencia'),
        width: double.infinity,
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.08),
          border: Border(left: BorderSide(color: color, width: 4)),
        ),
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.sm),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (texto != null)
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Icon(
                      resumen.estado == EstadoVigencia.fresca ? Icons.cloud_off : Icons.history,
                      size: 20,
                      color: color,
                    ),
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(
                    child: Text(texto, style: TextStyle(color: color, fontSize: 14, fontWeight: FontWeight.w500)),
                  ),
                ],
              ),
            if (descarga.descargando)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: AppSpacing.sm),
                child: Row(
                  children: [
                    SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
                    SizedBox(width: AppSpacing.sm),
                    Text('Actualizando datos…', style: TextStyle(color: AppColors.texto, fontSize: 14)),
                  ],
                ),
              )
            else if (puedeActualizar && avisar)
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton(
                  style: TextButton.styleFrom(minimumSize: const Size(48, 48), foregroundColor: color),
                  onPressed: () => ref.read(descargaControllerProvider.notifier).actualizar(),
                  child: const Text('Actualizar'),
                ),
              ),
            if (descarga.mensaje != null)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.xs),
                child: Text(
                  descarga.mensaje!,
                  style: TextStyle(color: descarga.esError ? AppColors.error : AppColors.advertencia, fontSize: 14),
                ),
              ),
          ],
        ),
      ),
    );
  }

  String _texto(ResumenVigencia resumen, String sucursal) {
    final descargadoEn = resumen.descargadoEn;
    if (resumen.estado == EstadoVigencia.nunca || descargadoEn == null) {
      return 'Aún no descargaste el catálogo de esta sucursal.';
    }
    final cuando = '${fechaCortaLocal(descargadoEn)} (${textoHace(resumen.edad ?? Duration.zero)})';
    if (resumen.estado == EstadoVigencia.fresca) return 'Sin conexión. Los datos se actualizaron el $cuando.';
    return 'Datos de $sucursal actualizados el $cuando. Pueden estar desactualizados.';
  }
}
