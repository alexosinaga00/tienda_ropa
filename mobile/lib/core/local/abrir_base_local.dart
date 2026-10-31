import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';
import 'esquema_local.dart';
import 'migraciones_locales.dart';

const nombreArchivoBaseLocal = 'fashionstore_local.db';

/// Abre (y crea o migra) la base local.
///
/// - [fabrica] y [ruta] se inyectan en las pruebas (`databaseFactoryFfi` con una base en memoria o en un archivo temporal);
///   en la app se usan `databaseFactory` de sqflite y el directorio privado de bases de datos.
/// - [migraciones] y [version] también son inyectables, para probar una migración con una versión de prueba.
/// - `PRAGMA foreign_keys = ON` se aplica en CADA conexión: sin esto SQLite no valida las llaves foráneas.
/// - Bajar de versión lanza un error. NUNCA se usa `onDatabaseDowngradeDelete`: borraría las operaciones pendientes.
Future<Database> abrirBaseLocal({
  DatabaseFactory? fabrica,
  String? ruta,
  int version = versionEsquemaLocal,
  Map<int, List<String>> migraciones = migracionesLocales,
}) async {
  final f = fabrica ?? databaseFactory;
  final destino = ruta ?? p.join(await f.getDatabasesPath(), nombreArchivoBaseLocal);

  return f.openDatabase(
    destino,
    options: OpenDatabaseOptions(
      version: version,
      onConfigure: (db) => db.execute('PRAGMA foreign_keys = ON'),
      onCreate: (db, v) async {
        for (final sentencia in sentenciasEsquemaV1) {
          await db.execute(sentencia);
        }
        await db.insert('meta', {'clave': 'version_esquema', 'valor': '1'});
        // Si se crea directamente en una versión posterior a la 1, se aplican también sus migraciones.
        await _migrar(db, 1, v, migraciones);
      },
      onUpgrade: (db, desde, hasta) => _migrar(db, desde, hasta, migraciones),
      onDowngrade: (db, desde, hasta) {
        throw StateError('La base local es de una versión más nueva ($desde) que la de esta app ($hasta).');
      },
    ),
  );
}

Future<void> _migrar(Database db, int desde, int hasta, Map<int, List<String>> migraciones) async {
  for (var v = desde + 1; v <= hasta; v++) {
    final sentencias = migraciones[v];
    if (sentencias == null) throw StateError('Falta la migración de la base local a la versión $v.');
    for (final sentencia in sentencias) {
      await db.execute(sentencia);
    }
    await db.insert('meta', {'clave': 'version_esquema', 'valor': '$v'}, conflictAlgorithm: ConflictAlgorithm.replace);
  }
}
