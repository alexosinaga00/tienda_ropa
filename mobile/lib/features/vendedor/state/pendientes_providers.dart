import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/utils/reloj.dart';
import '../data/contador_pendientes_sqlite.dart';
import '../data/politica_limpieza_local.dart';
import 'catalogo_local_providers.dart';

/// Cuántas operaciones pendientes tienen OTROS usuarios de la empresa de la sesión en este teléfono (quien las registró
/// debe ingresar con su cuenta para enviarlas). 0 sin sesión o ante cualquier error. Se recalcula al terminar una descarga.
final pendientesAjenosProvider = FutureProvider<int>((ref) async {
  ref.watch(descargaTerminadaProvider);
  final empresaId = ref.watch(empresaLocalIdProvider);
  final usuarioId = ref.watch(usuarioLocalIdProvider);
  if (empresaId == null || usuarioId == null) return 0;
  try {
    final contador = ContadorPendientesSqlite(() => ref.read(baseLocalProvider.future));
    return await contador.pendientesDeOtros(empresaId: empresaId, usuarioId: usuarioId);
  } catch (_) {
    return 0;
  }
});

/// La limpieza de la base local al cerrar sesión. En las pruebas se reemplaza con `overrideWith`.
final politicaLimpiezaLocalProvider = FutureProvider<PoliticaLimpiezaLocal>((ref) async {
  final db = await ref.watch(baseLocalProvider.future);
  return PoliticaLimpiezaLocalSqlite(db, ref.watch(relojProvider));
});
