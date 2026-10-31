import 'package:sqflite/sqflite.dart';

import '../models/paquete_sincronizacion.dart';
import 'almacen_paquete.dart';

/// Cuándo se descargó por última vez el paquete de una sucursal.
class UltimaDescarga {
  const UltimaDescarga({required this.descargadoEn, required this.generadoEn, required this.completo});

  /// La hora del teléfono en que terminó la descarga (para mostrar "datos del ...").
  final DateTime descargadoEn;

  /// La hora del SERVIDOR en que se leyó el stock: el `desde` de la próxima descarga incremental.
  final DateTime generadoEn;
  final bool completo;
}

/// Lo que la descarga necesita saber del estado local, y la sucursal con la que trabaja cada persona.
abstract interface class DescargaRepository {
  Future<UltimaDescarga?> ultimaDescarga(int empresaId, int sucursalId);

  /// La sucursal elegida por [usuarioId] en [empresaId], o `null` si no eligió ninguna.
  Future<int?> sucursalActiva(int empresaId, int usuarioId);

  Future<void> fijarSucursalActiva(int empresaId, int usuarioId, int sucursalId);

  /// Hay una operación 'enviada' (el servidor puede haberla aplicado o no): el stock que se descargue ahora sería ambiguo.
  Future<bool> hayOperacionesEnviadas(int empresaId);

  /// Horas tras las cuales se avisa "información desactualizada" (la última que mandó el servidor).
  Future<int?> avisoHoras(int empresaId);

  /// La empresa a la que pertenece una sucursal ya conocida en este teléfono (`null` si todavía no se descargó).
  Future<int?> empresaDeSucursal(int sucursalId);

  /// Con qué contrato y esquema se hizo la última descarga de esa sucursal (`null` si nunca).
  Future<String?> formatoDescarga(int empresaId, int sucursalId);
}

String claveMetaSucursalActiva(int empresaId, int usuarioId) => 'sucursal_activa:$empresaId:$usuarioId';

class DescargaRepositorySqlite implements DescargaRepository {
  DescargaRepositorySqlite(this._db);

  final Database _db;

  Future<String?> _meta(String clave) async {
    final filas = await _db.query('meta', columns: ['valor'], where: 'clave = ?', whereArgs: [clave]);
    return filas.isEmpty ? null : filas.first['valor']! as String;
  }

  @override
  Future<UltimaDescarga?> ultimaDescarga(int empresaId, int sucursalId) async {
    final filas = await _db.query(
      'descarga',
      where: 'empresa_id = ? AND sucursal_id = ?',
      whereArgs: [empresaId, sucursalId],
    );
    if (filas.isEmpty) return null;
    final fila = filas.first;
    final descargadoEn = leerFechaUtc(fila['descargado_en']);
    final generadoEn = leerFechaUtc(fila['generado_en']);
    if (descargadoEn == null || generadoEn == null) return null; // fila ilegible: se trata como si no hubiera descarga
    return UltimaDescarga(descargadoEn: descargadoEn, generadoEn: generadoEn, completo: fila['completo'] == 1);
  }

  @override
  Future<int?> sucursalActiva(int empresaId, int usuarioId) async {
    final valor = await _meta(claveMetaSucursalActiva(empresaId, usuarioId));
    return valor == null ? null : int.tryParse(valor);
  }

  @override
  Future<void> fijarSucursalActiva(int empresaId, int usuarioId, int sucursalId) async {
    await _db.insert(
      'meta',
      {'clave': claveMetaSucursalActiva(empresaId, usuarioId), 'valor': '$sucursalId'},
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  @override
  Future<bool> hayOperacionesEnviadas(int empresaId) async {
    final filas = await _db.rawQuery(
      "SELECT 1 FROM operacion_pendiente WHERE empresa_id = ? AND estado = 'enviada' LIMIT 1",
      [empresaId],
    );
    return filas.isNotEmpty;
  }

  @override
  Future<int?> avisoHoras(int empresaId) async {
    final valor = await _meta(claveMetaAvisoHoras(empresaId));
    return valor == null ? null : int.tryParse(valor);
  }

  @override
  Future<int?> empresaDeSucursal(int sucursalId) async {
    final filas = await _db.query('sucursal', columns: ['empresa_id'], where: 'id = ?', whereArgs: [sucursalId]);
    return filas.isEmpty ? null : filas.first['empresa_id']! as int;
  }

  @override
  Future<String?> formatoDescarga(int empresaId, int sucursalId) => _meta(claveMetaFormato(empresaId, sucursalId));
}
