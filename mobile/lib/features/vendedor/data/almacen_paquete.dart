import 'package:sqflite/sqflite.dart';

import '../../../core/local/esquema_local.dart';
import '../../../core/network/error_app.dart';
import '../../../core/utils/reloj.dart';
import '../../../core/utils/texto.dart';
import '../models/paquete_sincronizacion.dart';

/// Lo que se bajó del servidor en una descarga, listo para guardarse de una vez.
class PaqueteDescargado {
  const PaqueteDescargado({
    required this.manifiesto,
    required this.productos,
    required this.stock,
    required this.sucursalId,
    required this.completoStock,
    required this.generadoEnStock,
    this.clientes,
    this.generadoEnCatalogo,
  });

  final ManifiestoPaquete manifiesto;

  /// El catálogo COMPLETO de la empresa (el servidor no manda deltas de catálogo).
  final List<ProductoPaquete> productos;
  final DateTime? generadoEnCatalogo;

  /// El stock de [sucursalId]: completo si [completoStock], o solo lo modificado (delta).
  final List<ItemStockPaquete> stock;
  final int sucursalId;
  final bool completoStock;

  /// El `generado_en` del stock (primera página): de aquí sale el `desde` de la próxima descarga incremental.
  final DateTime generadoEnStock;

  /// `null` = esta descarga no trae clientes (las incrementales); no se toca la lista local.
  final List<ClientePaquete>? clientes;
}

/// Guarda un paquete descargado en la base local. Todo o nada.
abstract interface class AlmacenPaquete {
  Future<void> aplicar(PaqueteDescargado paquete, {required int usuarioId});
}

String claveMetaCatalogo(int empresaId) => 'catalogo_generado_en:$empresaId';
String claveMetaAvisoHoras(int empresaId) => 'aviso_horas:$empresaId';

/// Con qué contrato y esquema se hizo la última descarga de esa sucursal: si cambia, la siguiente es completa.
String claveMetaFormato(int empresaId, int sucursalId) => 'formato_descarga:$empresaId:$sucursalId';

class AlmacenPaqueteSqlite implements AlmacenPaquete {
  AlmacenPaqueteSqlite(this._db, this._reloj);

  final Database _db;
  final Reloj _reloj;

  // Nunca `INSERT OR REPLACE` sobre tablas con hijos: borraría la fila vieja (y con RESTRICT fallaría, o con CASCADE se
  // llevaría las filas hijas). `ON CONFLICT ... DO UPDATE` modifica en el lugar. El `WHERE` impide que un id de otra
  // empresa se pise.
  static const _sqlEmpresa =
      'INSERT INTO empresa (id, codigo, nombre) VALUES (?, ?, ?) '
      'ON CONFLICT(id) DO UPDATE SET codigo = excluded.codigo, nombre = excluded.nombre';
  static const _sqlSucursal =
      'INSERT INTO sucursal (id, empresa_id, codigo, nombre, direccion, es_deposito, activo) VALUES (?, ?, ?, ?, ?, ?, 1) '
      'ON CONFLICT(id) DO UPDATE SET codigo = excluded.codigo, nombre = excluded.nombre, direccion = excluded.direccion, '
      'es_deposito = excluded.es_deposito, activo = 1 WHERE sucursal.empresa_id = excluded.empresa_id';
  static const _sqlCategoria =
      'INSERT INTO categoria (id, empresa_id, nombre, categoria_padre_id) VALUES (?, ?, ?, ?) '
      'ON CONFLICT(id) DO UPDATE SET nombre = excluded.nombre, categoria_padre_id = excluded.categoria_padre_id '
      'WHERE categoria.empresa_id = excluded.empresa_id';
  static const _sqlTalla =
      'INSERT INTO talla (id, empresa_id, codigo, orden) VALUES (?, ?, ?, ?) '
      'ON CONFLICT(id) DO UPDATE SET codigo = excluded.codigo, orden = excluded.orden WHERE talla.empresa_id = excluded.empresa_id';
  static const _sqlColor =
      'INSERT INTO color (id, empresa_id, nombre, codigo_hex) VALUES (?, ?, ?, ?) '
      'ON CONFLICT(id) DO UPDATE SET nombre = excluded.nombre, codigo_hex = excluded.codigo_hex '
      'WHERE color.empresa_id = excluded.empresa_id';
  static const _sqlProducto =
      'INSERT INTO producto (id, empresa_id, codigo, nombre, nombre_busqueda, categoria_id, genero, imagen_principal_url, activo) '
      'VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1) '
      'ON CONFLICT(id) DO UPDATE SET codigo = excluded.codigo, nombre = excluded.nombre, '
      'nombre_busqueda = excluded.nombre_busqueda, categoria_id = excluded.categoria_id, genero = excluded.genero, '
      'imagen_principal_url = excluded.imagen_principal_url, activo = 1 WHERE producto.empresa_id = excluded.empresa_id';
  static const _sqlVariante =
      'INSERT INTO variante (id, producto_id, talla_id, color_id, sku, codigo_barras, precio_centavos, descuento_centavos, activo) '
      'VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1) '
      'ON CONFLICT(id) DO UPDATE SET producto_id = excluded.producto_id, talla_id = excluded.talla_id, '
      'color_id = excluded.color_id, sku = excluded.sku, codigo_barras = excluded.codigo_barras, '
      'precio_centavos = excluded.precio_centavos, descuento_centavos = excluded.descuento_centavos, activo = 1';
  static const _sqlCliente =
      'INSERT INTO cliente_minimo (empresa_id, servidor_id, nombre, apellido, ci_nit, creado_en) VALUES (?, ?, ?, ?, ?, ?) '
      'ON CONFLICT(empresa_id, servidor_id) WHERE servidor_id IS NOT NULL DO UPDATE SET '
      'nombre = excluded.nombre, apellido = excluded.apellido, ci_nit = excluded.ci_nit';

  @override
  Future<void> aplicar(PaqueteDescargado paquete, {required int usuarioId}) async {
    final manifiesto = paquete.manifiesto;
    final empresaId = manifiesto.empresa.id;
    final sucursalId = paquete.sucursalId;
    if (!manifiesto.sucursales.any((s) => s.id == sucursalId)) {
      throw const ErrorApp(tipo: TipoErrorApp.prohibido, mensaje: 'Esa sucursal no está autorizada para tu cuenta.');
    }
    final ahora = aIsoUtc(_reloj.ahora());
    final generadoStock = aIsoUtc(paquete.generadoEnStock);
    final generadoCatalogo = aIsoUtc(paquete.generadoEnCatalogo ?? manifiesto.generadoEn ?? paquete.generadoEnStock);

    await _db.transaction((txn) async {
      // ---- Lecturas previas (dentro de la misma transacción) ----
      final categoriasLocales = {
        for (final f in await txn.rawQuery('SELECT id FROM categoria WHERE empresa_id = ?', [empresaId])) f['id']! as int,
      };
      final clientesSinServidor = <String, int>{};
      if (paquete.clientes != null) {
        final filas = await txn.rawQuery(
          'SELECT id, ci_nit FROM cliente_minimo WHERE empresa_id = ? AND servidor_id IS NULL AND ci_nit IS NOT NULL',
          [empresaId],
        );
        for (final f in filas) {
          clientesSinServidor[f['ci_nit']! as String] = f['id']! as int;
        }
      }

      final lote = txn.batch();

      // ---- Empresa, sucursales, horarios y autorización ----
      lote.execute(_sqlEmpresa, [empresaId, manifiesto.empresa.codigo, manifiesto.empresa.nombre]);
      for (final s in manifiesto.sucursales) {
        lote.execute(_sqlSucursal, [s.id, empresaId, s.codigo, s.nombre, s.direccion, s.esDeposito ? 1 : 0]);
      }
      for (final s in manifiesto.sucursales) {
        lote.delete('sucursal_horario', where: 'sucursal_id = ?', whereArgs: [s.id]);
        for (final h in s.horarios) {
          lote.insert(
            'sucursal_horario',
            {'sucursal_id': s.id, 'dia_semana': h.diaSemana, 'hora_apertura': h.horaApertura, 'hora_cierre': h.horaCierre},
            conflictAlgorithm: ConflictAlgorithm.replace, // nada depende de esta tabla
          );
        }
      }
      lote.execute(
        'DELETE FROM sucursal_autorizada WHERE usuario_id = ? AND sucursal_id IN (SELECT id FROM sucursal WHERE empresa_id = ?)',
        [usuarioId, empresaId],
      );
      for (final s in manifiesto.sucursales) {
        lote.insert(
          'sucursal_autorizada',
          {'usuario_id': usuarioId, 'sucursal_id': s.id},
          conflictAlgorithm: ConflictAlgorithm.ignore,
        );
      }

      // ---- Referencias ----
      // Un padre que no existe ni llega (categoría inactiva) se deja en NULL: la llave se valida al terminar la transacción
      // y una sola fila mala bloquearía todas las descargas futuras.
      final categoriasConocidas = {...categoriasLocales, for (final c in manifiesto.categorias) c.id};
      for (final c in manifiesto.categorias) {
        final padre = c.categoriaPadreId != null && categoriasConocidas.contains(c.categoriaPadreId) ? c.categoriaPadreId : null;
        lote.execute(_sqlCategoria, [c.id, empresaId, c.nombre, padre]);
      }
      // Un producto activo cuya categoría está inactiva: se crea una categoría genérica con ese id (no pisa una real).
      final faltantes = {
        for (final p in paquete.productos)
          if (!categoriasConocidas.contains(p.categoriaId)) p.categoriaId,
      };
      for (final id in faltantes) {
        lote.insert(
          'categoria',
          {'id': id, 'empresa_id': empresaId, 'nombre': 'Sin categoría'},
          conflictAlgorithm: ConflictAlgorithm.ignore,
        );
      }
      for (final t in manifiesto.tallas) {
        lote.execute(_sqlTalla, [t.id, empresaId, t.codigo, t.orden]);
      }
      for (final c in manifiesto.colores) {
        lote.execute(_sqlColor, [c.id, empresaId, c.nombre, c.codigoHex]);
      }

      // ---- Catálogo: lo que no llegue queda inactivo (nunca se borra: las ventas pendientes lo referencian) ----
      lote.execute('UPDATE producto SET activo = 0 WHERE empresa_id = ?', [empresaId]);
      lote.execute(
        'UPDATE variante SET activo = 0 WHERE producto_id IN (SELECT id FROM producto WHERE empresa_id = ?)',
        [empresaId],
      );
      final variantesDelCatalogo = <int>{};
      for (final p in paquete.productos) {
        lote.execute(_sqlProducto, [
          p.id,
          empresaId,
          p.codigo,
          p.nombre,
          normalizarBusqueda(p.nombre),
          p.categoriaId,
          p.genero,
          p.imagenPrincipal,
        ]);
        for (final v in p.variantes) {
          variantesDelCatalogo.add(v.id);
          lote.execute(_sqlVariante, [
            v.id,
            p.id,
            v.tallaId,
            v.colorId,
            v.sku,
            v.codigoBarras,
            v.precioCentavos,
            v.descuentoCentavos,
          ]);
        }
      }

      // ---- Stock de ESTA sucursal (las demás no se tocan) ----
      if (paquete.completoStock) {
        lote.delete('stock_conocido', where: 'sucursal_id = ?', whereArgs: [sucursalId]);
      }
      for (final item in paquete.stock) {
        // Stock de una variante que no está en el catálogo (la llave foránea fallaría): no sirve para vender.
        if (!variantesDelCatalogo.contains(item.varianteId)) continue;
        lote.insert(
          'stock_conocido',
          {
            'variante_id': item.varianteId,
            'sucursal_id': sucursalId,
            // El CHECK no admite negativos: más reservas que existencias se ve como 0.
            'cantidad': item.cantidadDisponible < 0 ? 0 : item.cantidadDisponible,
            'generado_en': generadoStock,
          },
          conflictAlgorithm: ConflictAlgorithm.replace, // nada depende de esta tabla
        );
      }

      // ---- Clientes (solo en descargas completas) ----
      for (final c in paquete.clientes ?? const <ClientePaquete>[]) {
        final localId = c.ciNit == null ? null : clientesSinServidor.remove(c.ciNit);
        if (localId != null) {
          // Es el mismo cliente que se registró en el teléfono: se enlaza, sin cambiarle los datos.
          lote.update('cliente_minimo', {'servidor_id': c.id}, where: 'id = ?', whereArgs: [localId]);
        } else {
          lote.execute(_sqlCliente, [empresaId, c.id, c.nombre, c.apellido, c.ciNit, ahora]);
        }
      }

      // ---- Constancia de la descarga ----
      lote.insert('descarga', {
        'empresa_id': empresaId,
        'sucursal_id': sucursalId,
        'descargado_en': ahora,
        'generado_en': generadoStock,
        'completo': paquete.completoStock ? 1 : 0,
      }, conflictAlgorithm: ConflictAlgorithm.replace);
      lote.insert('meta', {'clave': claveMetaCatalogo(empresaId), 'valor': generadoCatalogo}, conflictAlgorithm: ConflictAlgorithm.replace);
      lote.insert(
        'meta',
        {'clave': claveMetaFormato(empresaId, sucursalId), 'valor': formatoDescargaActual},
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
      final aviso = manifiesto.avisoDesactualizadoHoras;
      if (aviso != null) {
        lote.insert('meta', {'clave': claveMetaAvisoHoras(empresaId), 'valor': '$aviso'}, conflictAlgorithm: ConflictAlgorithm.replace);
      }

      await lote.commit(noResult: true);
    });
  }
}

/// Identifica con qué contrato y esquema se guardó una descarga. Si la app cambia alguno de los dos, la próxima descarga de
/// cada sucursal es completa y no un delta sobre datos con otra forma.
const formatoDescargaActual = 'contrato$versionContratoSoportada-esquema$versionEsquemaLocal';
