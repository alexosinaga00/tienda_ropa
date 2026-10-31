import 'package:mobile/core/local/abrir_base_local.dart';
import 'package:mobile/core/utils/texto.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

/// Una variante de ejemplo para [sembrarProducto]. El precio y el descuento van en centavos.
typedef VarianteSemilla = ({int id, int tallaId, int colorId, String sku, int precio, int descuento, bool activa});

VarianteSemilla variante(int id, {int tallaId = 1, int colorId = 1, String? sku, int precio = 7500, int descuento = 0, bool activa = true}) =>
    (id: id, tallaId: tallaId, colorId: colorId, sku: sku ?? 'SKU-$id', precio: precio, descuento: descuento, activa: activa);

/// La base local REAL (SQLite del paquete `sqflite_common_ffi`) en memoria, con el esquema completo y las llaves
/// foráneas activadas. Con [ruta] se usa un archivo (para probar el reinicio).
Future<Database> abrirBaseDePrueba({String? ruta}) {
  sqfliteFfiInit();
  return abrirBaseLocal(fabrica: databaseFactoryFfi, ruta: ruta ?? inMemoryDatabasePath);
}

Future<void> sembrarEmpresa(Database db, {int id = 1, String codigo = 'chaski', String nombre = 'Chaski Sport'}) async {
  await db.insert('empresa', {'id': id, 'codigo': codigo, 'nombre': nombre});
}

Future<void> sembrarSucursal(
  Database db, {
  required int id,
  int empresaId = 1,
  String? nombre,
  bool esDeposito = false,
  bool activo = true,
}) async {
  await db.insert('sucursal', {
    'id': id,
    'empresa_id': empresaId,
    'codigo': 'S$id',
    'nombre': nombre ?? 'Sucursal $id',
    'direccion': 'Calle $id',
    'es_deposito': esDeposito ? 1 : 0,
    'activo': activo ? 1 : 0,
  });
}

/// Una categoría, las tallas S/M/L/XL (ids 1..4 si empresaId = 1; en otra empresa suman `empresaId * 100`) y un color.
Future<void> sembrarReferencias(Database db, {int empresaId = 1, int categoriaId = 1, String categoria = 'Poleras'}) async {
  final base = empresaId == 1 ? 0 : empresaId * 100;
  await db.insert('categoria', {'id': categoriaId, 'empresa_id': empresaId, 'nombre': categoria});
  const tallas = ['S', 'M', 'L', 'XL'];
  for (var i = 0; i < tallas.length; i++) {
    await db.insert('talla', {'id': base + i + 1, 'empresa_id': empresaId, 'codigo': tallas[i], 'orden': i});
  }
  await db.insert('color', {'id': base + 1, 'empresa_id': empresaId, 'nombre': 'Negro', 'codigo_hex': '#000000'});
}

Future<void> sembrarProducto(
  Database db, {
  required int id,
  int empresaId = 1,
  required String nombre,
  String? codigo,
  int categoriaId = 1,
  String genero = 'unisex',
  String? imagen,
  bool activo = true,
  List<VarianteSemilla> variantes = const [],
}) async {
  await db.insert('producto', {
    'id': id,
    'empresa_id': empresaId,
    'codigo': codigo ?? 'P$id',
    'nombre': nombre,
    'nombre_busqueda': normalizarBusqueda(nombre),
    'categoria_id': categoriaId,
    'genero': genero,
    'imagen_principal_url': imagen,
    'activo': activo ? 1 : 0,
  });
  for (final v in variantes) {
    await db.insert('variante', {
      'id': v.id,
      'producto_id': id,
      'talla_id': v.tallaId,
      'color_id': v.colorId,
      'sku': v.sku,
      'precio_centavos': v.precio,
      'descuento_centavos': v.descuento,
      'activo': v.activa ? 1 : 0,
    });
  }
}

Future<void> sembrarStock(
  Database db, {
  required int varianteId,
  required int sucursalId,
  required int cantidad,
  String generadoEn = '2026-10-31T10:00:00Z',
}) async {
  await db.insert('stock_conocido', {
    'variante_id': varianteId,
    'sucursal_id': sucursalId,
    'cantidad': cantidad,
    'generado_en': generadoEn,
  });
}
