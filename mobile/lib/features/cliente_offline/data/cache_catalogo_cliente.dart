import 'dart:convert';

import 'package:sqflite/sqflite.dart';

import '../../../core/utils/reloj.dart';
import '../../../core/utils/texto.dart';
import '../../catalogo/models/catalogo_detalle.dart';
import '../../catalogo/models/catalogo_item.dart';
import '../config/cliente_offline_config.dart';

/// Lo público de la tienda que el cliente ya vio, guardado en el teléfono para mostrarlo sin conexión: las prendas del
/// catálogo, el detalle de cada una (con sus variantes) y las tallas, colores y sucursales. Es lo mismo que mandó el
/// servidor, en JSON; no incluye stock exacto garantizado (puede estar viejo) ni nada de la persona.
abstract interface class CacheCatalogoCliente {
  /// Guarda las prendas de una página. [primeraPosicion] es el lugar de la primera en el listado SIN filtros (null para
  /// una búsqueda: conserva el lugar que ya tuvieran).
  Future<void> guardarItems(List<Map<String, dynamic>> crudos, {int? primeraPosicion});

  /// Las prendas guardadas, en el orden del listado. Con [texto] solo las que lo contienen (sin mayúsculas ni tildes).
  Future<List<CatalogoItem>> leerItems({String? texto});

  Future<void> guardarDetalle(int productoId, Map<String, dynamic> crudo);

  Future<CatalogoDetalle?> leerDetalle(int productoId);

  /// Reemplaza TODAS las referencias de ese [tipo] (`cacheTalla`, `cacheColor` o `cacheSucursal`).
  Future<void> guardarReferencias(String tipo, List<Map<String, dynamic>> crudos);

  Future<List<Map<String, dynamic>>> leerReferencias(String tipo);
}

class CacheCatalogoClienteSqlite implements CacheCatalogoCliente {
  /// [base] y [tienda] se piden al usar (no al construir): la base puede tardar en abrirse y la tienda puede cambiar.
  CacheCatalogoClienteSqlite(this._base, this._tienda, this._reloj);

  final Future<Database> Function() _base;
  final String? Function() _tienda;
  final Reloj _reloj;

  String get _codigo {
    final codigo = _tienda();
    if (codigo == null || codigo.isEmpty) throw StateError('No hay una tienda elegida.');
    return codigo;
  }

  String get _ahora => _reloj.ahora().toUtc().toIso8601String();

  @override
  Future<void> guardarItems(List<Map<String, dynamic>> crudos, {int? primeraPosicion}) async {
    if (crudos.isEmpty) return;
    final db = await _base();
    final tienda = _codigo;
    await db.transaction((txn) async {
      for (var i = 0; i < crudos.length; i++) {
        final id = crudos[i]['id'] as int;
        int? orden = primeraPosicion == null ? null : primeraPosicion + i;
        if (orden == null) {
          // Una búsqueda no cambia el lugar que la prenda ya tenía en el listado.
          final previas = await txn.query(
            'cli_cache',
            columns: ['orden'],
            where: 'tienda = ? AND tipo = ? AND clave = ?',
            whereArgs: [tienda, cacheItem, '$id'],
          );
          if (previas.isNotEmpty) orden = previas.first['orden'] as int?;
        }
        await txn.insert('cli_cache', {
          'tienda': tienda,
          'tipo': cacheItem,
          'clave': '$id',
          'orden': orden,
          'json': jsonEncode(crudos[i]),
          'guardado_en': _ahora,
        }, conflictAlgorithm: ConflictAlgorithm.replace);
      }
      // Nunca crece sin límite: se quedan las primeras del listado y las vistas más recientemente.
      await txn.rawDelete(
        'DELETE FROM cli_cache WHERE tienda = ? AND tipo = ? AND clave NOT IN ('
        'SELECT clave FROM cli_cache WHERE tienda = ? AND tipo = ? '
        'ORDER BY (orden IS NULL), orden ASC, guardado_en DESC LIMIT ?)',
        [tienda, cacheItem, tienda, cacheItem, maxItemsEnCache],
      );
    });
  }

  @override
  Future<List<CatalogoItem>> leerItems({String? texto}) async {
    final db = await _base();
    final filas = await db.query(
      'cli_cache',
      columns: ['json'],
      where: 'tienda = ? AND tipo = ?',
      whereArgs: [_codigo, cacheItem],
      orderBy: '(orden IS NULL), orden ASC, guardado_en DESC',
    );
    final items = <CatalogoItem>[];
    for (final fila in filas) {
      try {
        items.add(CatalogoItem.fromJson(jsonDecode(fila['json']! as String) as Map<String, dynamic>));
      } catch (_) {
        // Una fila dañada no tumba el resto: simplemente no se muestra.
      }
    }
    final buscado = texto == null ? '' : normalizarBusqueda(texto);
    if (buscado.isEmpty) return items;
    return items.where((i) => normalizarBusqueda(i.nombre).contains(buscado)).toList();
  }

  @override
  Future<void> guardarDetalle(int productoId, Map<String, dynamic> crudo) async {
    final db = await _base();
    final tienda = _codigo;
    await db.transaction((txn) async {
      await txn.insert('cli_cache', {
        'tienda': tienda,
        'tipo': cacheDetalle,
        'clave': '$productoId',
        'orden': null,
        'json': jsonEncode(crudo),
        'guardado_en': _ahora,
      }, conflictAlgorithm: ConflictAlgorithm.replace);
      await txn.rawDelete(
        'DELETE FROM cli_cache WHERE tienda = ? AND tipo = ? AND clave NOT IN ('
        'SELECT clave FROM cli_cache WHERE tienda = ? AND tipo = ? ORDER BY guardado_en DESC LIMIT ?)',
        [tienda, cacheDetalle, tienda, cacheDetalle, maxDetallesEnCache],
      );
    });
  }

  @override
  Future<CatalogoDetalle?> leerDetalle(int productoId) async {
    final db = await _base();
    final filas = await db.query(
      'cli_cache',
      columns: ['json'],
      where: 'tienda = ? AND tipo = ? AND clave = ?',
      whereArgs: [_codigo, cacheDetalle, '$productoId'],
    );
    if (filas.isEmpty) return null;
    try {
      return CatalogoDetalle.fromJson(jsonDecode(filas.first['json']! as String) as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }

  @override
  Future<void> guardarReferencias(String tipo, List<Map<String, dynamic>> crudos) async {
    final db = await _base();
    final tienda = _codigo;
    await db.transaction((txn) async {
      await txn.delete('cli_cache', where: 'tienda = ? AND tipo = ?', whereArgs: [tienda, tipo]);
      for (final crudo in crudos) {
        await txn.insert('cli_cache', {
          'tienda': tienda,
          'tipo': tipo,
          'clave': '${crudo['id']}',
          'orden': null,
          'json': jsonEncode(crudo),
          'guardado_en': _ahora,
        }, conflictAlgorithm: ConflictAlgorithm.replace);
      }
    });
  }

  @override
  Future<List<Map<String, dynamic>>> leerReferencias(String tipo) async {
    final db = await _base();
    final filas = await db.query(
      'cli_cache',
      columns: ['json'],
      where: 'tienda = ? AND tipo = ?',
      whereArgs: [_codigo, tipo],
      orderBy: 'CAST(clave AS INTEGER) ASC',
    );
    final lista = <Map<String, dynamic>>[];
    for (final fila in filas) {
      try {
        lista.add(jsonDecode(fila['json']! as String) as Map<String, dynamic>);
      } catch (_) {
        // Una fila dañada no tumba el resto.
      }
    }
    return lista;
  }
}
