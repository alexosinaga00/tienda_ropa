import 'package:mobile/core/utils/reloj.dart';
import 'package:mobile/features/vendedor/data/almacen_paquete.dart';
import 'package:mobile/features/vendedor/models/paquete_sincronizacion.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/api_client_falso.dart';

/// Un reloj que se mueve a mano.
class RelojManual implements Reloj {
  RelojManual([DateTime? inicio]) : actual = inicio ?? DateTime.utc(2026, 10, 31, 12);

  DateTime actual;

  @override
  DateTime ahora() => actual;
}

typedef Json = Map<String, dynamic>;

// ---- JSON con la forma real del contrato (backend/app/sincronizacion/schemas.py, "Paquete de descarga") ----

Json jsonSucursal(int id, {bool deposito = false, List<Json>? horarios}) => {
  'id': id,
  'codigo': 'S$id',
  'nombre': 'Sucursal $id',
  'direccion': 'Calle $id',
  'es_deposito': deposito,
  'horarios': horarios ?? [jsonHorario(1), jsonHorario(2)],
};

Json jsonHorario(int dia, {String apertura = '09:00', String cierre = '18:00'}) => {
  'dia_semana': dia,
  'hora_apertura': apertura,
  'hora_cierre': cierre,
};

Json jsonManifiesto({
  int empresaId = 1,
  String codigo = 'chaski',
  String nombre = 'Chaski Sport',
  List<Json>? sucursales,
  List<Json>? categorias,
  List<Json>? tallas,
  List<Json>? colores,
  String generadoEn = '2026-10-31T10:00:00Z',
  Object? version = '1.0',
  int? aviso = 12,
}) {
  // Los ids de referencia de otra empresa se desplazan para no chocar (en el servidor son únicos en toda la base).
  final base = empresaId == 1 ? 0 : empresaId * 100;
  return {
    'version_contrato': ?version,
    'generado_en': generadoEn,
    'aviso_desactualizado_horas': ?aviso,
    'empresa': {'id': empresaId, 'codigo': codigo, 'nombre': nombre},
    'sucursales': sucursales ?? [jsonSucursal(base + 1), jsonSucursal(base + 2)],
    'referencia': {
      'categorias': categorias ?? [{'id': base + 1, 'nombre': 'Poleras', 'categoria_padre_id': null}],
      'tallas': tallas ?? [
        for (var i = 0; i < 4; i++) {'id': base + i + 1, 'codigo': const ['S', 'M', 'L', 'XL'][i], 'orden': i},
      ],
      'colores': colores ?? [{'id': base + 1, 'nombre': 'Negro', 'codigo_hex': '#000000'}],
    },
    'promociones_vigentes': <Json>[],
    'reglas': {
      'metodos_pago_offline': ['efectivo'],
      'max_operaciones_por_lote': 50,
      'plazo_cambio_horas': 24,
      'cambios_y_devoluciones': 'solo_en_linea',
      'reservas_offline': 'las registra el personal',
    },
  };
}

Json jsonVariante(int id, {int talla = 1, int color = 1, Object? precio = '75.00', Object? descuento = '0.00', String? sku, String? barras}) => {
  'id': id,
  'talla_id': talla,
  'color_id': color,
  'sku': sku ?? 'SKU-$id',
  'codigo_barras': barras,
  'precio': ?precio,
  'descuento_unitario': ?descuento,
};

Json jsonProducto(int id, String nombre, {List<Json>? variantes, int categoria = 1, String? codigo, String? imagen}) => {
  'id': id,
  'codigo': codigo ?? 'P$id',
  'nombre': nombre,
  'categoria_id': categoria,
  'genero': 'unisex',
  'temporada_id': null,
  'imagen_principal': imagen,
  'variantes': variantes ?? [jsonVariante(id * 10), jsonVariante(id * 10 + 1, talla: 2)],
};

Json jsonPaginaCatalogo(List<Json> productos, {int? total, int? siguiente, String generadoEn = '2026-10-31T10:00:01Z', Object? version = '1.0'}) => {
  'version_contrato': ?version,
  'generado_en': generadoEn,
  'total': total ?? productos.length,
  'siguiente_desde_id': siguiente,
  'items': productos,
};

Json jsonItemStock(int variante, int cantidad, {String actualizadoEn = '2026-10-31T09:30:00Z'}) => {
  'variante_id': variante,
  'cantidad_disponible': cantidad,
  'actualizado_en': actualizadoEn,
};

Json jsonPaginaStock(
  int sucursalId,
  List<Json> items, {
  bool incremental = false,
  int? siguiente,
  String generadoEn = '2026-10-31T10:00:02Z',
  Object? version = '1.0',
}) => {
  'version_contrato': ?version,
  'generado_en': generadoEn,
  'sucursal_id': sucursalId,
  'incremental': incremental,
  'siguiente_desde_variante_id': siguiente,
  'items': items,
};

Json jsonCliente(int id, String nombre, {String? ci, String? apellido = 'Perez'}) => {
  'id': id,
  'nombre': nombre,
  'apellido': apellido,
  'ci_nit': ci,
};

Json jsonPaginaClientes(List<Json> clientes, {int? total, int? siguiente, String generadoEn = '2026-10-31T10:00:03Z', Object? version = '1.0'}) => {
  'version_contrato': ?version,
  'generado_en': generadoEn,
  'total': total ?? clientes.length,
  'siguiente_desde_id': siguiente,
  'items': clientes,
};

// ---- Rutas ----

const rutaManifiesto = '/sincronizacion/paquete';
const rutaCatalogo = '/sincronizacion/paquete/catalogo';
const rutaStock = '/sincronizacion/paquete/stock';
const rutaClientes = '/sincronizacion/paquete/clientes';

/// Prepara en el [ApiClientFalso] las respuestas de una descarga completa (una página de cada una por defecto). Si ya había
/// respuestas preparadas, las nuevas se entregan DESPUÉS (la segunda descarga recibe las segundas).
void prepararServidor(
  ApiClientFalso api, {
  Json? manifiesto,
  List<Json>? paginasCatalogo,
  List<Json>? paginasStock,
  List<Json>? paginasClientes,
  int sucursalId = 1,
}) {
  api.responder('GET', rutaManifiesto, manifiesto ?? jsonManifiesto());
  for (final p in paginasCatalogo ?? [jsonPaginaCatalogo([jsonProducto(10, 'Polera Básica'), jsonProducto(11, 'Camisa Lino')])]) {
    api.responder('GET', rutaCatalogo, p);
  }
  for (final p in paginasStock ?? [
    jsonPaginaStock(sucursalId, [jsonItemStock(100, 5), jsonItemStock(101, 3), jsonItemStock(110, 2), jsonItemStock(111, 0)]),
  ]) {
    api.responder('GET', rutaStock, p);
  }
  for (final p in paginasClientes ?? [jsonPaginaClientes([jsonCliente(1, 'Ana', ci: '111'), jsonCliente(2, 'Luis', ci: '222')])]) {
    api.responder('GET', rutaClientes, p);
  }
}

/// Un [PaqueteDescargado] armado desde JSON (así también se ejercitan los modelos).
PaqueteDescargado armarPaquete({
  Json? manifiesto,
  List<Json>? productos,
  List<Json>? stock,
  List<Json>? clientes,
  int sucursalId = 1,
  bool completoStock = true,
  String generadoStock = '2026-10-31T10:00:02Z',
}) {
  return PaqueteDescargado(
    manifiesto: ManifiestoPaquete.fromJson(manifiesto ?? jsonManifiesto()),
    productos: [
      for (final p in productos ?? [jsonProducto(10, 'Polera Básica'), jsonProducto(11, 'Camisa Lino')]) ProductoPaquete.fromJson(p),
    ],
    stock: [
      for (final i in stock ?? [jsonItemStock(100, 5), jsonItemStock(101, 3), jsonItemStock(110, 2), jsonItemStock(111, 0)])
        ItemStockPaquete.fromJson(i),
    ],
    sucursalId: sucursalId,
    completoStock: completoStock,
    generadoEnStock: DateTime.parse(generadoStock),
    clientes: clientes == null ? null : [for (final c in clientes) ClientePaquete.fromJson(c)],
  );
}

// ---- Lecturas rápidas de la base ----

Future<int> contar(Database db, String tabla, {String? donde, List<Object?>? args}) async {
  final r = await db.rawQuery('SELECT COUNT(*) AS n FROM $tabla${donde == null ? '' : ' WHERE $donde'}', args);
  return r.first['n']! as int;
}

Future<Map<int, int>> stockDe(Database db, int sucursalId) async {
  final filas = await db.query('stock_conocido', where: 'sucursal_id = ?', whereArgs: [sucursalId]);
  return {for (final f in filas) f['variante_id']! as int: f['cantidad']! as int};
}

/// Inserta una operación pendiente con una venta de la variante dada (para probar que sigue válida tras una descarga).
Future<void> sembrarVentaPendiente(
  Database db, {
  required String operacionId,
  required int varianteId,
  int empresaId = 1,
  int sucursalId = 1,
  String estado = 'registrada',
}) async {
  await db.insert('operacion_pendiente', {
    'operacion_id': operacionId,
    'empresa_id': empresaId,
    'sucursal_id': sucursalId,
    'usuario_id': 7,
    'tipo': 'venta_contado',
    'estado': estado,
    'payload': '{}',
    'version_contrato': 1,
    'fecha_operacion': '2026-10-31T09:00:00Z',
    'creada_en': '2026-10-31T09:00:00Z',
  });
  final ventaId = await db.insert('venta', {
    'operacion_id': operacionId,
    'empresa_id': empresaId,
    'sucursal_id': sucursalId,
    'usuario_id': 7,
    'fecha_operacion': '2026-10-31T09:00:00Z',
    'forma_pago': 'efectivo',
    'total_centavos': 7500,
  });
  await db.insert('venta_detalle', {'venta_id': ventaId, 'variante_id': varianteId, 'cantidad': 1, 'precio_unitario_centavos': 7500});
}
