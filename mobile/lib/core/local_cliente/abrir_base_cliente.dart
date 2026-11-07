import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

import 'esquema_cliente.dart';
import 'migraciones_cliente.dart';

/// Un archivo distinto del de la base del personal (`fashionstore_local.db`): jamás comparten tablas.
const nombreArchivoBaseCliente = 'fashionstore_cliente.db';

/// Abre (y crea o migra) la base local del cliente.
///
/// - [fabrica] y [ruta] se inyectan en las pruebas (`databaseFactoryFfi` con una base en memoria o en un archivo
///   temporal); en la app se usan `databaseFactory` de sqflite y el directorio privado de bases de datos.
/// - [migraciones] y [version] también son inyectables, para probar una migración con una versión de prueba.
/// - Bajar de versión lanza un error. NUNCA se usa `onDatabaseDowngradeDelete`: borraría los pedidos sin enviar.
Future<Database> abrirBaseCliente({
  DatabaseFactory? fabrica,
  String? ruta,
  int version = versionEsquemaCliente,
  Map<int, List<String>> migraciones = migracionesCliente,
}) async {
  final f = fabrica ?? databaseFactory;
  final destino = ruta ?? p.join(await f.getDatabasesPath(), nombreArchivoBaseCliente);

  return f.openDatabase(
    destino,
    options: OpenDatabaseOptions(
      version: version,
      onCreate: (db, v) async {
        for (final sentencia in sentenciasEsquemaClienteV1) {
          await db.execute(sentencia);
        }
        // Si se crea directamente en una versión posterior a la 1, se aplican también sus migraciones.
        await _migrar(db, 1, v, migraciones);
      },
      onUpgrade: (db, desde, hasta) => _migrar(db, desde, hasta, migraciones),
      onDowngrade: (db, desde, hasta) {
        throw StateError('La base local del cliente es de una versión más nueva ($desde) que la de esta app ($hasta).');
      },
    ),
  );
}

Future<void> _migrar(Database db, int desde, int hasta, Map<int, List<String>> migraciones) async {
  for (var v = desde + 1; v <= hasta; v++) {
    final sentencias = migraciones[v];
    if (sentencias == null) throw StateError('Falta la migración de la base local del cliente a la versión $v.');
    for (final sentencia in sentencias) {
      await db.execute(sentencia);
    }
  }
}
