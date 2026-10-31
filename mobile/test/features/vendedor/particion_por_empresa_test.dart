import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/vendedor/data/catalogo_local_repository.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';

/// Dos empresas en la MISMA base (un teléfono compartido): cada repositorio solo ve lo suyo, aunque coincidan el código
/// de producto y el SKU.
void main() {
  late Database db;
  late CatalogoLocalSqlite a;
  late CatalogoLocalSqlite b;

  setUp(() async {
    db = await abrirBaseDePrueba();
    await sembrarEmpresa(db);
    await sembrarEmpresa(db, id: 2, codigo: 'andes', nombre: 'Andes');
    await sembrarSucursal(db, id: 1, empresaId: 1, nombre: 'Centro A');
    await sembrarSucursal(db, id: 2, empresaId: 2, nombre: 'Centro B');
    await sembrarSucursal(db, id: 3, empresaId: 2, nombre: 'Norte B');
    await sembrarReferencias(db, empresaId: 1, categoriaId: 1, categoria: 'Poleras');
    await sembrarReferencias(db, empresaId: 2, categoriaId: 2, categoria: 'Pantalones');
    // MISMO código de producto y MISMO sku en las dos empresas.
    await sembrarProducto(db, id: 1, empresaId: 1, nombre: 'Polera Roja', codigo: 'P-001', variantes: [variante(1, sku: 'SKU-X', precio: 5000)]);
    await sembrarProducto(
      db,
      id: 2,
      empresaId: 2,
      categoriaId: 2,
      nombre: 'Polera Roja',
      codigo: 'P-001',
      variantes: [variante(2, tallaId: 201, colorId: 201, sku: 'SKU-X', precio: 9000)],
    );
    // El mismo usuario (id 10) está autorizado en sucursales de las dos empresas.
    await db.insert('sucursal_autorizada', {'usuario_id': 10, 'sucursal_id': 1});
    await db.insert('sucursal_autorizada', {'usuario_id': 10, 'sucursal_id': 2});
    await db.insert('sucursal_autorizada', {'usuario_id': 10, 'sucursal_id': 3});
    // Stock "cruzado": la variante 1 (empresa 1) con stock en la sucursal 2 (empresa 2). La FK de la base lo permitiría.
    await sembrarStock(db, varianteId: 1, sucursalId: 1, cantidad: 5);
    await sembrarStock(db, varianteId: 1, sucursalId: 2, cantidad: 9);
    await sembrarStock(db, varianteId: 2, sucursalId: 2, cantidad: 4);
    a = CatalogoLocalSqlite(db, empresaId: 1);
    b = CatalogoLocalSqlite(db, empresaId: 2);
  });

  tearDown(() async {
    await db.close();
  });

  test('la búsqueda por nombre solo devuelve productos de la propia empresa', () async {
    expect((await a.buscarProductos(texto: 'polera')).map((p) => p.id), [1]);
    expect((await b.buscarProductos(texto: 'polera')).map((p) => p.id), [2]);
  });

  test('con el mismo código en las dos empresas, cada una ve el suyo', () async {
    expect((await a.buscarProductos(texto: 'p-001')).map((p) => p.id), [1]);
    expect((await b.buscarProductos(texto: 'p-001')).map((p) => p.id), [2]);
  });

  test('con el mismo SKU en las dos empresas, cada una ve el suyo', () async {
    expect((await a.buscarProductos(texto: 'sku-x')).map((p) => p.id), [1]);
    expect((await b.buscarProductos(texto: 'sku-x')).map((p) => p.id), [2]);
  });

  test('el listado sin filtro tampoco mezcla', () async {
    await sembrarProducto(db, id: 3, empresaId: 2, categoriaId: 2, nombre: 'Jean', codigo: 'P-002');
    expect((await a.buscarProductos()).map((p) => p.id), [1]);
    expect((await b.buscarProductos()).map((p) => p.id), [3, 2]);
  });

  test('los precios son los de la propia empresa', () async {
    expect((await a.productoPorId(1))!.precioDesdeCentavos, 5000);
    expect((await b.productoPorId(2))!.precioDesdeCentavos, 9000);
  });

  test('categorías de cada empresa', () async {
    expect((await a.categorias()).map((c) => c.nombre), ['Poleras']);
    expect((await b.categorias()).map((c) => c.nombre), ['Pantalones']);
  });

  test('filtrar por una categoría de la otra empresa no devuelve nada', () async {
    expect(await a.buscarProductos(categoriaId: 2), isEmpty);
    expect(await b.buscarProductos(categoriaId: 1), isEmpty);
    expect((await a.buscarProductos(categoriaId: 1)).map((p) => p.id), [1]);
  });

  test('sucursales autorizadas: un mismo usuario solo ve las de la empresa del repositorio', () async {
    expect((await a.sucursalesAutorizadas(10)).map((s) => s.id), [1]);
    expect((await b.sucursalesAutorizadas(10)).map((s) => s.id), [2, 3]);
  });

  test('contarProductos cuenta solo los de la empresa', () async {
    await sembrarProducto(db, id: 3, empresaId: 2, categoriaId: 2, nombre: 'Jean', codigo: 'P-002');
    await sembrarProducto(db, id: 4, empresaId: 2, categoriaId: 2, nombre: 'Short', codigo: 'P-003');
    expect(await a.contarProductos(), 1);
    expect(await b.contarProductos(), 3);
  });

  test('productoPorId de un id de la otra empresa devuelve null', () async {
    expect(await a.productoPorId(2), isNull);
    expect(await b.productoPorId(1), isNull);
    expect(await a.productoPorId(1), isNotNull);
    expect(await b.productoPorId(2), isNotNull);
  });

  test('variantesDeProducto de un producto de la otra empresa devuelve vacío', () async {
    expect(await a.variantesDeProducto(2, sucursalId: 1), isEmpty);
    expect(await b.variantesDeProducto(1, sucursalId: 2), isEmpty);
    expect(await a.variantesDeProducto(1, sucursalId: 1), hasLength(1));
  });

  test('la existencia solo cuenta stock de sucursales de la propia empresa', () async {
    // La empresa 1 pide la sucursal 2 (de la empresa 2): aunque haya una fila de stock, no se le muestra.
    expect((await a.productoPorId(1, sucursalId: 2))!.existenciaEstimada, 0);
    expect((await a.productoPorId(1, sucursalId: 1))!.existenciaEstimada, 5);
    expect((await a.variantesDeProducto(1, sucursalId: 2)).single.cantidadConocida, 0);
    expect((await b.productoPorId(2, sucursalId: 2))!.existenciaEstimada, 4);
  });

  test('una empresa sin datos en la base no ve nada', () async {
    final c = CatalogoLocalSqlite(db, empresaId: 3);
    expect(await c.buscarProductos(), isEmpty);
    expect(await c.buscarProductos(texto: 'polera'), isEmpty);
    expect(await c.categorias(), isEmpty);
    expect(await c.sucursalesAutorizadas(10), isEmpty);
    expect(await c.contarProductos(), 0);
    expect(await c.productoPorId(1), isNull);
  });

  test('los productos inactivos de una empresa no afectan a la otra', () async {
    await sembrarProducto(db, id: 5, empresaId: 2, categoriaId: 2, nombre: 'Polera Azul', codigo: 'P-005', activo: false);
    expect(await b.contarProductos(), 1);
    expect(await a.contarProductos(), 1);
  });
}
