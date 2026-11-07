import 'package:sqflite/sqflite.dart';

import '../../../core/utils/fecha_servidor.dart';
import '../../../core/utils/texto.dart';
import '../models/categoria_local.dart';
import '../models/producto_local.dart';
import '../models/sucursal_local.dart';
import '../models/variante_local.dart';

/// Lectura del catálogo en la base local, para consultar sin conexión.
abstract interface class CatalogoLocalRepository {
  /// Productos activos de la empresa, ordenados por nombre. [texto] busca por nombre (sin tildes ni mayúsculas), código o SKU
  /// de alguna variante; con varias palabras deben aparecer todas. [categoriaId] incluye también las subcategorías.
  /// Con [sucursalId] cada producto trae su existencia estimada en esa sucursal.
  Future<List<ProductoLocal>> buscarProductos({
    String? texto,
    int? categoriaId,
    int? sucursalId,
    int limite = 20,
    int desplazamiento = 0,
  });

  /// `null` si el producto no existe, está dado de baja o es de otra empresa.
  Future<ProductoLocal?> productoPorId(int id, {int? sucursalId});

  /// Variantes activas de un producto con su existencia en [sucursalId]; vacío si el producto no es visible.
  Future<List<VarianteLocal>> variantesDeProducto(int productoId, {required int sucursalId});

  Future<List<CategoriaLocal>> categorias();

  /// Sucursales activas que [usuarioId] puede usar (incluye los depósitos: la pantalla decide si los ofrece).
  Future<List<SucursalLocal>> sucursalesAutorizadas(int usuarioId);

  /// Cantidad de productos activos de la empresa (0 = todavía no se descargó el catálogo).
  Future<int> contarProductos();
}

/// Implementación sobre SQLite. TODA consulta filtra por [empresaId]: en un mismo teléfono pueden convivir varias empresas.
class CatalogoLocalSqlite implements CatalogoLocalRepository {
  CatalogoLocalSqlite(this._db, {required this.empresaId});

  final Database _db;
  final int empresaId;

  @override
  Future<List<ProductoLocal>> buscarProductos({
    String? texto,
    int? categoriaId,
    int? sucursalId,
    int limite = 20,
    int desplazamiento = 0,
  }) async {
    if (limite <= 0) return const [];
    final filtros = <String>[];
    final args = <Object?>[];

    for (final palabra in _palabras(texto)) {
      final patron = '%${_escaparLike(palabra)}%';
      filtros.add(
        "(p.nombre_busqueda LIKE ? ESCAPE '\\' "
        "OR LOWER(p.codigo) LIKE ? ESCAPE '\\' "
        'OR EXISTS (SELECT 1 FROM variante vs WHERE vs.producto_id = p.id AND vs.activo = 1 '
        "AND LOWER(vs.sku) LIKE ? ESCAPE '\\'))",
      );
      args.addAll([patron, patron, patron]);
    }

    if (categoriaId != null) {
      // La categoría pedida y todas sus descendientes (UNION, no UNION ALL: un ciclo de datos malos no cuelga la consulta).
      filtros.add(
        'p.categoria_id IN (WITH RECURSIVE arbol(id) AS ('
        'SELECT id FROM categoria WHERE id = ? AND empresa_id = ? '
        'UNION SELECT c.id FROM categoria c JOIN arbol a ON c.categoria_padre_id = a.id WHERE c.empresa_id = ?'
        ') SELECT id FROM arbol)',
      );
      args.addAll([categoriaId, empresaId, empresaId]);
    }

    return _consultarProductos(
      filtros: filtros,
      filtrosArgs: args,
      sucursalId: sucursalId,
      limite: limite,
      desplazamiento: desplazamiento < 0 ? 0 : desplazamiento,
    );
  }

  @override
  Future<ProductoLocal?> productoPorId(int id, {int? sucursalId}) async {
    final filas = await _consultarProductos(
      filtros: ['p.id = ?'],
      filtrosArgs: [id],
      sucursalId: sucursalId,
      limite: 1,
      desplazamiento: 0,
    );
    return filas.isEmpty ? null : filas.first;
  }

  /// Una sola consulta: primero se elige la PÁGINA de productos (filtro, orden, LIMIT/OFFSET) y solo para esos se agregan
  /// precios y existencias. Así el costo de las variantes y de la vista de stock depende del tamaño de la página, no del
  /// catálogo.
  Future<List<ProductoLocal>> _consultarProductos({
    required List<String> filtros,
    required List<Object?> filtrosArgs,
    required int? sucursalId,
    required int limite,
    required int desplazamiento,
  }) async {
    final where = ['p.empresa_id = ?', 'p.activo = 1', ...filtros].join(' AND ');
    final conExistencia = sucursalId != null;

    final sql = '''
SELECT p.id AS id, p.codigo AS codigo, p.nombre AS nombre, p.categoria_id AS categoria_id,
       c.nombre AS categoria_nombre, p.genero AS genero, p.imagen_principal_url AS imagen_url,
       COALESCE(MIN(MAX(0, v.precio_centavos - v.descuento_centavos)), 0) AS precio_desde,
       COALESCE(MAX(MAX(0, v.precio_centavos - v.descuento_centavos)), 0) AS precio_max,
       ${conExistencia ? 'COALESCE(SUM(st.cantidad_estimada), 0)' : 'NULL'} AS existencia
FROM (
  SELECT p.* FROM producto p
  WHERE $where
  ORDER BY p.nombre_busqueda, p.id
  LIMIT ? OFFSET ?
) p
JOIN categoria c ON c.id = p.categoria_id AND c.empresa_id = ?
LEFT JOIN variante v ON v.producto_id = p.id AND v.activo = 1
${conExistencia ? 'LEFT JOIN v_stock_local st ON st.variante_id = v.id AND st.sucursal_id = (SELECT id FROM sucursal WHERE id = ? AND empresa_id = ?)' : ''}
GROUP BY p.id
ORDER BY p.nombre_busqueda, p.id''';

    final args = <Object?>[empresaId, ...filtrosArgs, limite, desplazamiento, empresaId, if (conExistencia) ...[sucursalId, empresaId]];
    final filas = await _db.rawQuery(sql, args);
    return [
      for (final f in filas)
        ProductoLocal(
          id: f['id']! as int,
          codigo: f['codigo']! as String,
          nombre: f['nombre']! as String,
          categoriaId: f['categoria_id']! as int,
          categoriaNombre: f['categoria_nombre']! as String,
          genero: f['genero']! as String,
          imagenUrl: f['imagen_url'] as String?,
          precioDesdeCentavos: f['precio_desde']! as int,
          precioMaxCentavos: f['precio_max']! as int,
          existenciaEstimada: f['existencia'] as int?,
        ),
    ];
  }

  @override
  Future<List<VarianteLocal>> variantesDeProducto(int productoId, {required int sucursalId}) async {
    final filas = await _db.rawQuery(
      '''
SELECT v.id AS id, v.producto_id AS producto_id, v.talla_id AS talla_id, t.codigo AS talla_codigo, t.orden AS talla_orden,
       v.color_id AS color_id, co.nombre AS color_nombre, co.codigo_hex AS color_hex, v.sku AS sku,
       v.precio_centavos AS precio_centavos, v.descuento_centavos AS descuento_centavos,
       COALESCE(st.cantidad_conocida, 0) AS cantidad_conocida, COALESCE(st.cantidad_estimada, 0) AS cantidad_estimada,
       st.generado_en AS generado_en
FROM producto p
JOIN variante v ON v.producto_id = p.id AND v.activo = 1
JOIN talla t ON t.id = v.talla_id
JOIN color co ON co.id = v.color_id
LEFT JOIN v_stock_local st ON st.variante_id = v.id
  AND st.sucursal_id = (SELECT id FROM sucursal WHERE id = ? AND empresa_id = ?)
WHERE p.id = ? AND p.empresa_id = ? AND p.activo = 1
ORDER BY t.orden, t.id, co.nombre, v.id''',
      [sucursalId, empresaId, productoId, empresaId],
    );
    return [
      for (final f in filas)
        VarianteLocal(
          id: f['id']! as int,
          productoId: f['producto_id']! as int,
          tallaId: f['talla_id']! as int,
          tallaCodigo: f['talla_codigo']! as String,
          tallaOrden: f['talla_orden']! as int,
          colorId: f['color_id']! as int,
          colorNombre: f['color_nombre']! as String,
          colorHex: f['color_hex'] as String?,
          sku: f['sku']! as String,
          precioCentavos: f['precio_centavos']! as int,
          descuentoCentavos: f['descuento_centavos']! as int,
          cantidadConocida: f['cantidad_conocida']! as int,
          cantidadEstimada: f['cantidad_estimada']! as int,
          generadoEn: _fecha(f['generado_en'] as String?),
        ),
    ];
  }

  @override
  Future<List<CategoriaLocal>> categorias() async {
    final filas = await _db.query(
      'categoria',
      columns: ['id', 'nombre', 'categoria_padre_id'],
      where: 'empresa_id = ?',
      whereArgs: [empresaId],
      orderBy: 'nombre, id',
    );
    return [
      for (final f in filas)
        CategoriaLocal(id: f['id']! as int, nombre: f['nombre']! as String, padreId: f['categoria_padre_id'] as int?),
    ];
  }

  @override
  Future<List<SucursalLocal>> sucursalesAutorizadas(int usuarioId) async {
    final filas = await _db.rawQuery(
      '''
SELECT s.id, s.codigo, s.nombre, s.direccion, s.es_deposito, s.activo
FROM sucursal s
JOIN sucursal_autorizada a ON a.sucursal_id = s.id AND a.usuario_id = ?
WHERE s.empresa_id = ? AND s.activo = 1
ORDER BY s.es_deposito, s.nombre, s.id''',
      [usuarioId, empresaId],
    );
    return [
      for (final f in filas)
        SucursalLocal(
          id: f['id']! as int,
          codigo: f['codigo']! as String,
          nombre: f['nombre']! as String,
          direccion: f['direccion']! as String,
          esDeposito: (f['es_deposito']! as int) == 1,
          activo: (f['activo']! as int) == 1,
        ),
    ];
  }

  @override
  Future<int> contarProductos() async {
    final filas = await _db.rawQuery('SELECT COUNT(*) AS n FROM producto WHERE empresa_id = ? AND activo = 1', [empresaId]);
    return filas.first['n']! as int;
  }
}

/// Las palabras de la búsqueda, normalizadas (sin tildes, en minúsculas). Vacío si no hay texto.
List<String> _palabras(String? texto) {
  if (texto == null) return const [];
  final normal = normalizarBusqueda(texto);
  if (normal.isEmpty) return const [];
  return normal.split(' ').where((p) => p.isNotEmpty).toList();
}

/// Escapa los comodines de LIKE (`\`, `%`, `_`) para buscarlos como texto literal con `ESCAPE '\'`.
String _escaparLike(String s) => s.replaceAll(r'\', r'\\').replaceAll('%', r'\%').replaceAll('_', r'\_');

DateTime? _fecha(String? iso) => leerInstanteUtc(iso);
