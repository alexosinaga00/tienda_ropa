import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/conectividad/conectividad_service.dart';
import '../../../core/network/providers.dart';
import '../../../core/sync/cola_operaciones.dart';
import '../../../core/sync/cola_operaciones_sqlite.dart';
import '../../../core/sync/dispositivo_id.dart';
import '../../../core/sync/generador_uuid.dart';
import '../../../core/sync/motor_sincronizacion.dart';
import '../../../core/sync/operacion_pendiente.dart';
import '../../../core/sync/sincronizacion_api.dart';
import '../../../core/utils/reloj.dart';
import '../data/clientes_local_repository.dart';
import 'catalogo_local_providers.dart';

/// Genera el id de cada operación. Las pantallas lo piden AL ABRIRSE (no al pulsar el botón) para que un doble toque no duplique.
final generadorUuidProvider = Provider<GeneradorUuid>((ref) => const GeneradorUuidV4());

/// La cola de operaciones sobre la base local. Se cierra sola al descartarse.
final colaOperacionesProvider = FutureProvider<ColaOperaciones>((ref) async {
  final db = await ref.watch(baseLocalProvider.future);
  final cola = ColaOperacionesSqlite(db, ref.watch(relojProvider));
  ref.onDispose(cola.dispose);
  return cola;
});

final sincronizacionApiProvider = Provider<SincronizacionApi>(
  (ref) => SincronizacionApiHttp(ref.watch(apiClientProvider)),
);

/// UNA sola instancia mientras no cambie la tienda ni la base: guarda el candado de "una sincronización a la vez".
final motorSincronizacionProvider = FutureProvider<MotorSincronizacion>((ref) async {
  final db = await ref.watch(baseLocalProvider.future);
  final cola = await ref.watch(colaOperacionesProvider.future);
  final generador = ref.watch(generadorUuidProvider);
  final motor = MotorSincronizacion(
    cola: cola,
    api: ref.watch(sincronizacionApiProvider),
    reloj: ref.watch(relojProvider),
    conectividad: ref.watch(conectividadServiceProvider),
    dispositivoId: () => obtenerDispositivoId(db, generador),
  );
  ref.onDispose(motor.dispose);
  return motor;
});

/// El estado del motor (en curso, última sincronización, bloqueo de plan, sesión vencida). Emite primero el actual.
final estadoSyncProvider = StreamProvider<EstadoSync>((ref) async* {
  final motor = await ref.watch(motorSincronizacionProvider.future);
  yield motor.estado;
  yield* motor.cambiosDeEstado;
});

/// Cuántas operaciones hay en cada estado para el usuario de la sesión; se refresca solo con cada cambio de la cola.
final conteoOperacionesProvider = StreamProvider<Map<EstadoOperacion, int>>((ref) async* {
  final empresaId = ref.watch(empresaLocalIdProvider);
  final usuarioId = ref.watch(usuarioLocalIdProvider);
  final cola = await ref.watch(colaOperacionesProvider.future);
  final vacio = {for (final e in EstadoOperacion.values) e: 0};
  if (empresaId == null || usuarioId == null) {
    yield vacio;
    return;
  }
  Future<Map<EstadoOperacion, int>> leer() => cola.conteoPorEstado(empresaId: empresaId, usuarioId: usuarioId);
  yield await leer();
  await for (final _ in cola.cambios) {
    yield await leer();
  }
});

/// Las operaciones por atender: registradas, enviadas, rechazadas y en conflicto (las que la persona debe mirar).
int porAtender(Map<EstadoOperacion, int> conteo) =>
    (conteo[EstadoOperacion.registrada] ?? 0) +
    (conteo[EstadoOperacion.enviada] ?? 0) +
    (conteo[EstadoOperacion.rechazada] ?? 0) +
    (conteo[EstadoOperacion.enConflicto] ?? 0);

/// Las que todavía no llegaron al servidor (lo que espera conexión).
int porEnviar(Map<EstadoOperacion, int> conteo) =>
    (conteo[EstadoOperacion.registrada] ?? 0) + (conteo[EstadoOperacion.enviada] ?? 0);

/// Los clientes del servidor guardados en el teléfono (los únicos que se pueden poner en una venta o reserva).
final clientesLocalProvider = FutureProvider<ClientesLocalRepository?>((ref) async {
  final empresaId = ref.watch(empresaLocalIdProvider);
  if (empresaId == null) return null;
  final db = await ref.watch(baseLocalProvider.future);
  return ClientesLocalSqlite(db, empresaId: empresaId);
});

/// Lee un provider tanto desde un `Ref` (providers) como desde un `WidgetRef` (pantallas).
T _leer<T>(Object ref, ProviderListenable<T> proveedor) =>
    ref is WidgetRef ? ref.read(proveedor) : (ref as Ref).read(proveedor);

/// Sincroniza ahora con la empresa y el usuario de la sesión. [ref] puede ser un `Ref` o un `WidgetRef`. Devuelve null si no
/// hay sesión. El motor tiene un candado: si ya hay una sincronización en curso, devuelve la misma.
Future<ResumenSync?> sincronizarAhora(Object ref, {Disparador disparador = Disparador.manual}) async {
  final empresaId = _leer(ref, empresaLocalIdProvider);
  final usuarioId = _leer(ref, usuarioLocalIdProvider);
  if (empresaId == null || usuarioId == null) return null;
  final motor = await _leer(ref, motorSincronizacionProvider.future);
  return motor.sincronizar(empresaId: empresaId, usuarioId: usuarioId, disparador: disparador);
}
