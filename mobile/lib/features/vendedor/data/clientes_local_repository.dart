import 'package:sqflite/sqflite.dart';

import '../../../core/utils/texto.dart';
import '../models/cliente_local.dart';

/// Lectura de los clientes de la copia local, para elegirlos al vender o reservar sin conexión.
abstract interface class ClientesLocalRepository {
  /// Clientes de la empresa que el servidor conoce (con `servidor_id`), ordenados por nombre. [texto] busca por nombre,
  /// apellido o CI/NIT sin distinguir mayúsculas ni tildes; con varias palabras deben aparecer todas.
  Future<List<ClienteLocal>> buscar({String? texto, int limite = 20, int desplazamiento = 0});

  /// `null` si no existe, es de otra empresa o todavía no tiene `servidor_id`.
  Future<ClienteLocal?> porId(int id);
}

/// Implementación sobre SQLite. TODA consulta filtra por [empresaId] y por `servidor_id IS NOT NULL`: un cliente creado solo en
/// el teléfono no sirve para una operación sin conexión (el backend no lo conoce).
class ClientesLocalSqlite implements ClientesLocalRepository {
  ClientesLocalSqlite(this._db, {required this.empresaId});

  final Database _db;
  final int empresaId;

  @override
  Future<List<ClienteLocal>> buscar({String? texto, int limite = 20, int desplazamiento = 0}) async {
    if (limite <= 0) return const [];
    final filtros = ['empresa_id = ?', 'servidor_id IS NOT NULL'];
    final args = <Object?>[empresaId];

    // `nombre` y `apellido` no tienen columna normalizada: se normalizan en la propia consulta con la misma tabla de
    // `normalizarBusqueda`, de modo que "jose", "JOSÉ" y "José" encuentran lo mismo, y "nunez" encuentra "Núñez".
    final palabras = _palabras(texto);
    final buscable = _normalizadoSql("nombre || ' ' || COALESCE(apellido, '') || ' ' || COALESCE(ci_nit, '')");
    for (final palabra in palabras) {
      filtros.add("$buscable LIKE ? ESCAPE '\\'");
      args.add('%${_escaparLike(palabra)}%');
    }

    final filas = await _db.rawQuery(
      'SELECT id, servidor_id, nombre, apellido, ci_nit FROM cliente_minimo '
      'WHERE ${filtros.join(' AND ')} '
      "ORDER BY ${_normalizadoSql('nombre')}, ${_normalizadoSql("COALESCE(apellido, '')")}, id "
      'LIMIT ? OFFSET ?',
      [...args, limite, desplazamiento < 0 ? 0 : desplazamiento],
    );
    return filas.map(_aCliente).toList();
  }

  @override
  Future<ClienteLocal?> porId(int id) async {
    final filas = await _db.query(
      'cliente_minimo',
      columns: ['id', 'servidor_id', 'nombre', 'apellido', 'ci_nit'],
      where: 'id = ? AND empresa_id = ? AND servidor_id IS NOT NULL',
      whereArgs: [id, empresaId],
    );
    return filas.isEmpty ? null : _aCliente(filas.first);
  }
}

ClienteLocal _aCliente(Map<String, Object?> f) => ClienteLocal(
  id: f['id']! as int,
  servidorId: f['servidor_id']! as int,
  nombre: f['nombre']! as String,
  apellido: f['apellido'] as String?,
  ciNit: f['ci_nit'] as String?,
);

// Letras con tilde (en minúscula y MAYÚSCULA) y su equivalente. `LOWER` de SQLite solo conoce ASCII, así que las mayúsculas
// acentuadas se reemplazan una por una. Es la misma tabla de `normalizarBusqueda` (texto.dart).
const _conTilde = 'áàäâãéèëêíìïîóòöôõúùüûñç';
const _sinTilde = 'aaaaaeeeeiiiiooooouuuunc';

/// La expresión SQL que deja [columna] en minúsculas y sin tildes: primero se reemplaza cada letra acentuada (en sus dos
/// formas) y al final `LOWER` baja el resto, que ya es ASCII.
String _normalizadoSql(String columna) {
  var expresion = columna;
  for (var i = 0; i < _conTilde.length; i++) {
    final minuscula = _conTilde[i];
    final mayuscula = minuscula.toUpperCase();
    final destino = _sinTilde[i];
    expresion = "REPLACE($expresion, '$minuscula', '$destino')";
    if (mayuscula != minuscula) expresion = "REPLACE($expresion, '$mayuscula', '$destino')";
  }
  return 'LOWER($expresion)';
}

List<String> _palabras(String? texto) {
  if (texto == null) return const [];
  final normal = normalizarBusqueda(texto);
  if (normal.isEmpty) return const [];
  return normal.split(' ').where((p) => p.isNotEmpty).toList();
}

/// Escapa los comodines de LIKE (`\`, `%`, `_`) para buscarlos como texto literal con `ESCAPE '\'`.
String _escaparLike(String s) => s.replaceAll(r'\', r'\\').replaceAll('%', r'\%').replaceAll('_', r'\_');
