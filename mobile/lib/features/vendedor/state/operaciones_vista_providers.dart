import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/sync/cola_operaciones.dart';
import '../../../core/sync/motivos_sync.dart';
import '../../../core/sync/motor_sincronizacion.dart';
import '../../../core/sync/operacion_pendiente.dart';
import '../models/detalle_resultado_sync.dart';
import 'catalogo_local_providers.dart';
import 'sincronizacion_providers.dart';

/// Sincroniza ahora. `sincronizarAhora` pide un `Ref` (no un `WidgetRef`), así que las pantallas pasan por este proveedor;
/// en las pruebas se sustituye con un doble.
typedef Sincronizador = Future<ResumenSync?> Function({Disparador disparador});

final sincronizadorProvider = Provider<Sincronizador>(
  (ref) =>
      ({Disparador disparador = Disparador.manual}) => sincronizarAhora(ref, disparador: disparador),
);

/// Sube en uno cada vez que la cola cambia. Quien lo espera con `await ref.watch(versionColaProvider.future)` se reconstruye en
/// cada cambio (y espera la primera lectura una sola vez).
final versionColaProvider = StreamProvider.autoDispose<int>((ref) async* {
  final cola = await ref.watch(colaOperacionesProvider.future);
  var version = 0;
  yield version;
  await for (final _ in cola.cambios) {
    yield ++version;
  }
});

/// Por qué una operación rechazada o en conflicto no se aceptó, con la ÚLTIMA respuesta del servidor. Sin respuesta (p. ej. un
/// rechazo local sin fila) usa el último error guardado.
MotivoSync motivoDeOperacion(OperacionPendiente operacion, List<ResultadoLocal> resultados) {
  final ultimo = resultados.isEmpty ? null : resultados.last;
  final mensaje = (ultimo?.motivo?.trim().isNotEmpty ?? false) ? ultimo!.motivo : operacion.ultimoError;
  return motivoDe(ultimo?.codigoMotivo, mensajeServidor: mensaje);
}

/// Lo que una fila de la lista necesita de su operación: el detalle (total o cliente) y, si no se aceptó, el motivo.
class ResumenFila {
  const ResumenFila({this.detalle, this.motivo});

  final DetalleOperacion? detalle;
  final MotivoSync? motivo;
}

final resumenFilaProvider = FutureProvider.autoDispose.family<ResumenFila, String>((ref, operacionId) async {
  await ref.watch(versionColaProvider.future);
  final cola = await ref.watch(colaOperacionesProvider.future);
  final detalle = await cola.detalle(operacionId);
  if (detalle == null) return const ResumenFila();
  final estado = detalle.operacion.estado;
  if (estado != EstadoOperacion.rechazada && estado != EstadoOperacion.enConflicto) return ResumenFila(detalle: detalle);
  final resultados = await cola.resultados(operacionId);
  return ResumenFila(detalle: detalle, motivo: motivoDeOperacion(detalle.operacion, resultados));
});

/// Todo lo que la pantalla de resultado muestra de una operación.
class DatosResultado {
  const DatosResultado({required this.detalle, required this.resultados, required this.extra});

  final DetalleOperacion detalle;

  /// Las respuestas del servidor, de la más antigua a la más nueva.
  final List<ResultadoLocal> resultados;

  /// El `detalle_json` de la ÚLTIMA respuesta.
  final DetalleResultadoSync extra;

  OperacionPendiente get operacion => detalle.operacion;
  ResultadoLocal? get ultimo => resultados.isEmpty ? null : resultados.last;
}

/// Null si la operación no existe o es de otra empresa u otro usuario de este teléfono.
final datosResultadoProvider = FutureProvider.autoDispose.family<DatosResultado?, String>((ref, operacionId) async {
  await ref.watch(versionColaProvider.future);
  final empresaId = ref.watch(empresaLocalIdProvider);
  final usuarioId = ref.watch(usuarioLocalIdProvider);
  final cola = await ref.watch(colaOperacionesProvider.future);
  final detalle = await cola.detalle(operacionId);
  if (detalle == null) return null;
  if (detalle.operacion.empresaId != empresaId || detalle.operacion.usuarioId != usuarioId) return null;
  final resultados = await cola.resultados(operacionId);
  return DatosResultado(
    detalle: detalle,
    resultados: resultados,
    extra: DetalleResultadoSync.desde(resultados.isEmpty ? null : resultados.last.detalleJson),
  );
});
