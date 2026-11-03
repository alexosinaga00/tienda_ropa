import 'package:sqflite/sqflite.dart';

import 'generador_uuid.dart';

/// La clave de `meta` donde se guarda el identificador del teléfono.
const claveDispositivoId = 'dispositivo_id';

/// El identificador de ESTE teléfono (un UUID que se genera una vez y no cambia). Viaja en cada lote como `dispositivo`, solo
/// para auditoría: no es un dato personal. Si ya existe en `meta` se devuelve; si no, se genera, se guarda y se devuelve. Dos
/// llamadas simultáneas terminan con el mismo valor (gana la primera que escribe).
Future<String> obtenerDispositivoId(Database db, GeneradorUuid generador) async {
  final existente = await _leer(db);
  if (existente != null) return existente;

  await db.insert(
    'meta',
    {'clave': claveDispositivoId, 'valor': generador.nuevo()},
    conflictAlgorithm: ConflictAlgorithm.ignore,
  );
  // Se vuelve a leer: si otra llamada se adelantó, su valor es el que quedó.
  return (await _leer(db)) ?? (throw StateError('No se pudo guardar el identificador del dispositivo.'));
}

Future<String?> _leer(DatabaseExecutor db) async {
  final filas = await db.query('meta', columns: ['valor'], where: 'clave = ?', whereArgs: [claveDispositivoId], limit: 1);
  if (filas.isEmpty) return null;
  final valor = filas.first['valor'] as String?;
  return (valor == null || valor.isEmpty) ? null : valor;
}
