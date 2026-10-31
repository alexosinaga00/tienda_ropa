import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/vendedor/data/catalogo_local_repository.dart';
import 'package:mobile/features/vendedor/models/variante_local.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';

void main() {
  late Database db;
  late CatalogoLocalSqlite repo;

  setUp(() async {
    db = await abrirBaseDePrueba();
    await sembrarEmpresa(db);
    await sembrarSucursal(db, id: 1);
    await sembrarReferencias(db); // categoría 1 "Poleras", tallas 1..4, color 1.
    repo = CatalogoLocalSqlite(db, empresaId: 1);
  });

  tearDown(() async {
    await db.close();
  });

  Future<List<int>> ids(String? texto, {int? categoriaId, int limite = 50}) async =>
      (await repo.buscarProductos(texto: texto, categoriaId: categoriaId, limite: limite)).map((p) => p.id).toList();

  group('búsqueda por texto', () {
    setUp(() async {
      await sembrarProducto(db, id: 1, nombre: 'Camisa Básica', codigo: 'CAM-001', variantes: [variante(1, sku: 'ZZ-CAM-M-NEG')]);
      await sembrarProducto(db, id: 2, nombre: 'CAMISA Oxford', codigo: 'CAM-002', variantes: [variante(2, sku: 'ZZ-OXF-L-NEG')]);
      await sembrarProducto(db, id: 3, nombre: 'Pantalón Jean', codigo: 'PAN-001', variantes: [variante(3, sku: 'ZZ-JEA-30')]);
    });

    test('sin tildes ni mayúsculas: "camisa" encuentra "Camisa Básica" y "CAMISA"', () async {
      expect(await ids('camisa'), [1, 2]);
      expect(await ids('CAMISA'), [1, 2]);
      expect(await ids('CamIsÁ'), [1, 2]);
    });

    test('"basica" encuentra "Básica" y "básica" también', () async {
      expect(await ids('basica'), [1]);
      expect(await ids('básica'), [1]);
    });

    test('"pantalon" encuentra "Pantalón"', () async {
      expect(await ids('pantalon'), [3]);
    });

    test('coincidencia parcial en cualquier parte del nombre', () async {
      expect(await ids('xfor'), [2]);
      expect(await ids('jea'), [3]);
    });

    test('por código sin distinguir mayúsculas', () async {
      expect(await ids('CAM-001'), [1]);
      expect(await ids('cam-001'), [1]);
      expect(await ids('pan-0'), [3]);
    });

    test('por SKU de alguna variante sin distinguir mayúsculas', () async {
      expect(await ids('zz-oxf-l-neg'), [2]);
      expect(await ids('ZZ-JEA'), [3]);
    });

    test('un producto con varias variantes que coinciden sale UNA sola vez', () async {
      await sembrarProducto(
        db,
        id: 4,
        nombre: 'Short',
        variantes: [variante(10, tallaId: 1, sku: 'MULTI-S'), variante(11, tallaId: 2, sku: 'MULTI-M'), variante(12, tallaId: 3, sku: 'MULTI-L')],
      );
      final res = await repo.buscarProductos(texto: 'multi');
      expect(res.map((p) => p.id), [4]);
    });

    test('un SKU compartido por varios productos los devuelve a todos, una vez cada uno', () async {
      await sembrarProducto(db, id: 5, nombre: 'Otra', variantes: [variante(20, sku: 'ZZ-COMUN')]);
      await sembrarProducto(db, id: 6, nombre: 'Otra más', variantes: [variante(21, sku: 'ZZ-COMUN')]);
      expect(await ids('zz-comun'), [5, 6]);
    });

    test('varias palabras: todas deben aparecer', () async {
      expect(await ids('camisa oxford'), [2]);
      expect(await ids('oxford camisa'), [2]);
      expect(await ids('camisa jean'), isEmpty);
    });

    test('las palabras pueden estar repartidas entre nombre, código y SKU', () async {
      expect(await ids('camisa cam-002'), [2]);
      expect(await ids('basica zz-cam-m'), [1]);
      expect(await ids('camisa zz-jea'), isEmpty);
    });

    test('espacios de más no cambian el resultado', () async {
      expect(await ids('   camisa     oxford  '), [2]);
    });

    test('sin coincidencias devuelve una lista vacía', () async {
      expect(await ids('zapatilla'), isEmpty);
    });

    test('texto nulo, vacío o solo espacios no filtra', () async {
      expect(await ids(null), [1, 2, 3]);
      expect(await ids(''), [1, 2, 3]);
      expect(await ids('   '), [1, 2, 3]);
    });

    test('ordena por nombre sin tildes y, a igual nombre, por id', () async {
      await sembrarProducto(db, id: 7, nombre: 'camisa básica');
      await sembrarProducto(db, id: 8, nombre: 'Ábaco');
      // "abaco" < "camisa basica"(1, 7) < "camisa oxford" < "pantalon jean".
      expect(await ids(null), [8, 1, 7, 2, 3]);
    });
  });

  group('comodines y entradas raras', () {
    setUp(() async {
      await sembrarProducto(db, id: 1, nombre: 'Oferta 50% off');
      await sembrarProducto(db, id: 2, nombre: 'Oferta 50 off');
      await sembrarProducto(db, id: 3, nombre: 'a_b');
      await sembrarProducto(db, id: 4, nombre: 'axb');
      await sembrarProducto(db, id: 5, nombre: r'Ruta c:\tmp');
    });

    test('el % se busca como texto, no como comodín', () async {
      expect(await ids('50%'), [1]);
      expect(await ids('%'), [1]);
    });

    test('el _ se busca como texto, no como comodín', () async {
      expect(await ids('a_b'), [3]);
      expect(await ids('_'), [3]);
    });

    test(r'la barra invertida no rompe la consulta', () async {
      expect(await ids(r'c:\tmp'), [5]);
      expect(await ids(r'\'), [5]);
      expect(await ids(r'\%'), isEmpty);
    });

    test('las comillas y el SQL en el texto se tratan como texto', () async {
      expect(await ids("'; DROP TABLE producto; --"), isEmpty);
      expect(await ids("o'neil"), isEmpty);
      expect(await repo.contarProductos(), 5);
    });
  });

  group('categorías', () {
    setUp(() async {
      await db.insert('categoria', {'id': 2, 'empresa_id': 1, 'nombre': 'Pantalones'});
      await db.insert('categoria', {'id': 3, 'empresa_id': 1, 'nombre': 'Polos', 'categoria_padre_id': 1});
      await db.insert('categoria', {'id': 4, 'empresa_id': 1, 'nombre': 'Polos deportivos', 'categoria_padre_id': 3});
      await sembrarProducto(db, id: 1, nombre: 'Polera lisa', categoriaId: 1);
      await sembrarProducto(db, id: 2, nombre: 'Jean', categoriaId: 2);
      await sembrarProducto(db, id: 3, nombre: 'Polo rojo', categoriaId: 3);
      await sembrarProducto(db, id: 4, nombre: 'Polo running', categoriaId: 4);
    });

    test('filtra por categoría exacta', () async {
      expect(await ids(null, categoriaId: 2), [2]);
    });

    test('una categoría incluye sus subcategorías y las de más abajo', () async {
      expect(await ids(null, categoriaId: 1), [1, 3, 4]);
      expect(await ids(null, categoriaId: 3), [3, 4]);
      expect(await ids(null, categoriaId: 4), [4]);
    });

    test('se combina con el texto', () async {
      expect(await ids('polo', categoriaId: 1), [3, 4]);
      expect(await ids('polo', categoriaId: 2), isEmpty);
      expect(await ids('running', categoriaId: 3), [4]);
    });

    test('una categoría inexistente no devuelve nada', () async {
      expect(await ids(null, categoriaId: 999), isEmpty);
    });

    test('un ciclo de datos malos no cuelga la consulta', () async {
      await db.execute('UPDATE categoria SET categoria_padre_id = 4 WHERE id = 1');
      expect(await ids(null, categoriaId: 1), [1, 3, 4]);
    });

    test('categorias() devuelve las de la empresa ordenadas por nombre, con su padre', () async {
      final cats = await repo.categorias();
      expect(cats.map((c) => c.nombre), ['Pantalones', 'Poleras', 'Polos', 'Polos deportivos']);
      expect(cats.firstWhere((c) => c.id == 3).padreId, 1);
      expect(cats.firstWhere((c) => c.id == 1).padreId, isNull);
    });

    test('el producto trae el nombre de su categoría', () async {
      final p = await repo.productoPorId(3);
      expect(p!.categoriaId, 3);
      expect(p.categoriaNombre, 'Polos');
    });
  });

  group('paginación', () {
    setUp(() async {
      for (var i = 1; i <= 25; i++) {
        await sembrarProducto(db, id: i, nombre: 'Producto ${i.toString().padLeft(2, '0')}');
      }
    });

    test('páginas de 10 sin repetir ni saltar', () async {
      final vistos = <int>[];
      for (var pagina = 0; pagina < 3; pagina++) {
        final res = await repo.buscarProductos(limite: 10, desplazamiento: pagina * 10);
        vistos.addAll(res.map((p) => p.id));
        expect(res.length, pagina < 2 ? 10 : 5);
      }
      expect(vistos, List.generate(25, (i) => i + 1));
    });

    test('un desplazamiento más allá del final devuelve vacío', () async {
      expect(await repo.buscarProductos(limite: 10, desplazamiento: 25), isEmpty);
      expect(await repo.buscarProductos(limite: 10, desplazamiento: 500), isEmpty);
    });

    test('el límite por defecto es 20', () async {
      expect(await repo.buscarProductos(), hasLength(20));
    });

    test('límite 0 o negativo devuelve vacío y desplazamiento negativo se toma como 0', () async {
      expect(await repo.buscarProductos(limite: 0), isEmpty);
      expect(await repo.buscarProductos(limite: -3), isEmpty);
      final res = await repo.buscarProductos(limite: 2, desplazamiento: -5);
      expect(res.map((p) => p.id), [1, 2]);
    });

    test('la paginación respeta el filtro de texto', () async {
      // "producto" y "2" (ambas palabras): 02, 12, 20, 21, 22, 23, 24 y 25, en ese orden de nombre.
      final p1 = await repo.buscarProductos(texto: 'producto 2', limite: 3, desplazamiento: 0);
      final p2 = await repo.buscarProductos(texto: 'producto 2', limite: 3, desplazamiento: 3);
      final p3 = await repo.buscarProductos(texto: 'producto 2', limite: 3, desplazamiento: 6);
      expect(p1.map((p) => p.id), [2, 12, 20]);
      expect(p2.map((p) => p.id), [21, 22, 23]);
      expect(p3.map((p) => p.id), [24, 25]);
    });

    test('con nombres iguales la paginación sigue siendo estable (desempata por id)', () async {
      await db.delete('producto');
      for (var i = 1; i <= 6; i++) {
        await sembrarProducto(db, id: i, nombre: 'Igual', codigo: 'IG$i');
      }
      final a = await repo.buscarProductos(limite: 3, desplazamiento: 0);
      final b = await repo.buscarProductos(limite: 3, desplazamiento: 3);
      expect([...a, ...b].map((p) => p.id), [1, 2, 3, 4, 5, 6]);
    });
  });

  group('activos e inactivos', () {
    test('un producto inactivo no aparece en búsqueda, por id ni en el conteo', () async {
      await sembrarProducto(db, id: 1, nombre: 'Visible', variantes: [variante(1)]);
      await sembrarProducto(db, id: 2, nombre: 'Oculto', activo: false, variantes: [variante(2)]);
      expect(await ids(null), [1]);
      expect(await ids('oculto'), isEmpty);
      expect(await repo.productoPorId(2), isNull);
      expect(await repo.productoPorId(1), isNotNull);
      expect(await repo.contarProductos(), 1);
    });

    test('un producto inactivo tampoco se encuentra por código ni por SKU', () async {
      await sembrarProducto(db, id: 2, nombre: 'Oculto', codigo: 'OCU-1', activo: false, variantes: [variante(2, sku: 'OCU-SKU')]);
      expect(await ids('ocu-1'), isEmpty);
      expect(await ids('ocu-sku'), isEmpty);
    });

    test('las variantes del producto inactivo no se listan', () async {
      await sembrarProducto(db, id: 2, nombre: 'Oculto', activo: false, variantes: [variante(2)]);
      expect(await repo.variantesDeProducto(2, sucursalId: 1), isEmpty);
    });

    test('una variante inactiva no se lista ni se busca por su SKU', () async {
      await sembrarProducto(
        db,
        id: 1,
        nombre: 'Polera',
        variantes: [variante(1, tallaId: 1, sku: 'ACT-1'), variante(2, tallaId: 2, sku: 'INACT-2', activa: false)],
      );
      final vars = await repo.variantesDeProducto(1, sucursalId: 1);
      expect(vars.map((v) => v.sku), ['ACT-1']);
      expect(await ids('act-1'), [1]);
      expect(await ids('inact-2'), isEmpty);
    });

    test('una variante inactiva no cuenta en el precio ni en la existencia', () async {
      await sembrarProducto(
        db,
        id: 1,
        nombre: 'Polera',
        variantes: [variante(1, tallaId: 1, precio: 5000), variante(2, tallaId: 2, precio: 1000, activa: false)],
      );
      await sembrarStock(db, varianteId: 1, sucursalId: 1, cantidad: 4);
      await sembrarStock(db, varianteId: 2, sucursalId: 1, cantidad: 100);
      final p = await repo.productoPorId(1, sucursalId: 1);
      expect(p!.precioDesdeCentavos, 5000);
      expect(p.precioMaxCentavos, 5000);
      expect(p.existenciaEstimada, 4);
    });

    test('un producto sin variantes activas se lista con precio 0 y existencia 0', () async {
      await sembrarProducto(db, id: 1, nombre: 'Sin variantes');
      final p = (await repo.buscarProductos(sucursalId: 1)).single;
      expect(p.precioDesdeCentavos, 0);
      expect(p.precioMaxCentavos, 0);
      expect(p.existenciaEstimada, 0);
    });

    test('contarProductos cuenta solo los activos', () async {
      expect(await repo.contarProductos(), 0);
      await sembrarProducto(db, id: 1, nombre: 'A');
      await sembrarProducto(db, id: 2, nombre: 'B');
      await sembrarProducto(db, id: 3, nombre: 'C', activo: false);
      expect(await repo.contarProductos(), 2);
    });
  });

  group('precios', () {
    test('precioDesde es el menor (precio - descuento) y precioMax el mayor', () async {
      await sembrarProducto(
        db,
        id: 1,
        nombre: 'Polera',
        variantes: [
          variante(1, tallaId: 1, precio: 10000),
          variante(2, tallaId: 2, precio: 9000, descuento: 2500), // 6500
          variante(3, tallaId: 3, precio: 8000), // 8000
        ],
      );
      final p = await repo.productoPorId(1);
      expect(p!.precioDesdeCentavos, 6500);
      expect(p.precioMaxCentavos, 10000);
      expect(p.tieneRangoDePrecio, isTrue);
    });

    test('un descuento mayor que el precio no da precios negativos', () async {
      await sembrarProducto(db, id: 1, nombre: 'Liquidación', variantes: [variante(1, precio: 1000, descuento: 1500)]);
      final p = await repo.productoPorId(1);
      expect(p!.precioDesdeCentavos, 0);
      expect(p.precioMaxCentavos, 0);
    });

    test('con un solo precio no hay rango', () async {
      await sembrarProducto(db, id: 1, nombre: 'Polera', variantes: [variante(1, tallaId: 1, precio: 7500), variante(2, tallaId: 2, precio: 7500)]);
      final p = await repo.productoPorId(1);
      expect(p!.precioDesdeCentavos, 7500);
      expect(p.tieneRangoDePrecio, isFalse);
    });

    test('precioFinalCentavos de la variante resta el descuento y no baja de 0', () {
      VarianteLocal con(int precio, int descuento) => VarianteLocal(
            id: 1,
            productoId: 1,
            tallaId: 1,
            tallaCodigo: 'S',
            tallaOrden: 0,
            colorId: 1,
            colorNombre: 'Negro',
            sku: 'X',
            precioCentavos: precio,
            descuentoCentavos: descuento,
            cantidadConocida: 0,
            cantidadEstimada: 0,
          );
      expect(con(9000, 2500).precioFinalCentavos, 6500);
      expect(con(1000, 1500).precioFinalCentavos, 0);
      expect(con(1000, 0).precioFinalCentavos, 1000);
    });
  });

  group('existencia por sucursal', () {
    setUp(() async {
      await sembrarSucursal(db, id: 2);
      await sembrarProducto(db, id: 1, nombre: 'Polera', variantes: [variante(1, tallaId: 1), variante(2, tallaId: 2)]);
      await sembrarProducto(db, id: 2, nombre: 'Sin stock', variantes: [variante(3, tallaId: 1)]);
      await sembrarStock(db, varianteId: 1, sucursalId: 1, cantidad: 5);
      await sembrarStock(db, varianteId: 2, sucursalId: 1, cantidad: 2);
      await sembrarStock(db, varianteId: 1, sucursalId: 2, cantidad: 3);
    });

    test('la suma de sus variantes en la sucursal pedida', () async {
      final s1 = await repo.buscarProductos(sucursalId: 1);
      expect(s1.map((p) => p.existenciaEstimada), [7, 0]);
      final s2 = await repo.buscarProductos(sucursalId: 2);
      expect(s2.map((p) => p.existenciaEstimada), [3, 0]);
    });

    test('sin sucursal la existencia es null', () async {
      final res = await repo.buscarProductos();
      expect(res.map((p) => p.existenciaEstimada), [null, null]);
      expect((await repo.productoPorId(1))!.existenciaEstimada, isNull);
    });

    test('una sucursal sin datos da 0, no null', () async {
      expect((await repo.productoPorId(1, sucursalId: 999))!.existenciaEstimada, 0);
    });

    test('productoPorId con sucursal trae la existencia', () async {
      expect((await repo.productoPorId(1, sucursalId: 1))!.existenciaEstimada, 7);
      expect((await repo.productoPorId(1, sucursalId: 2))!.existenciaEstimada, 3);
    });

    test('la existencia estimada descuenta lo vendido sin conexión', () async {
      await db.insert('operacion_pendiente', {
        'operacion_id': 'op-1',
        'empresa_id': 1,
        'sucursal_id': 1,
        'usuario_id': 10,
        'tipo': 'venta_contado',
        'payload': '{}',
        'version_contrato': 1,
        'fecha_operacion': '2026-10-31T11:00:00Z',
        'creada_en': '2026-10-31T11:00:00Z',
      });
      final ventaId = await db.insert('venta', {
        'operacion_id': 'op-1',
        'empresa_id': 1,
        'sucursal_id': 1,
        'usuario_id': 10,
        'fecha_operacion': '2026-10-31T11:00:00Z',
        'forma_pago': 'efectivo',
        'total_centavos': 15000,
      });
      await db.insert('venta_detalle', {'venta_id': ventaId, 'variante_id': 1, 'cantidad': 2, 'precio_unitario_centavos': 7500});
      expect((await repo.productoPorId(1, sucursalId: 1))!.existenciaEstimada, 5);
      expect((await repo.productoPorId(1, sucursalId: 2))!.existenciaEstimada, 3);
    });
  });

  group('productoPorId y variantes', () {
    test('productoPorId devuelve todos los datos del producto', () async {
      await sembrarProducto(
        db,
        id: 9,
        nombre: 'Chamarra Térmica',
        codigo: 'CHA-9',
        genero: 'hombre',
        imagen: 'https://img.example/c.jpg',
        variantes: [variante(1, precio: 25000)],
      );
      final p = (await repo.productoPorId(9))!;
      expect(p.codigo, 'CHA-9');
      expect(p.nombre, 'Chamarra Térmica');
      expect(p.genero, 'hombre');
      expect(p.imagenUrl, 'https://img.example/c.jpg');
      expect(p.categoriaNombre, 'Poleras');
      expect(p.precioDesdeCentavos, 25000);
    });

    test('productoPorId de un id que no existe devuelve null', () async {
      expect(await repo.productoPorId(12345), isNull);
    });

    test('un producto sin imagen trae imagenUrl null', () async {
      await sembrarProducto(db, id: 1, nombre: 'Sin foto');
      expect((await repo.productoPorId(1))!.imagenUrl, isNull);
    });

    test('variantesDeProducto ordena por talla (su orden) y trae talla, color y stock', () async {
      await sembrarSucursal(db, id: 2);
      await sembrarProducto(
        db,
        id: 1,
        nombre: 'Polera',
        variantes: [
          variante(1, tallaId: 3, sku: 'P-L', precio: 8000, descuento: 500), // L
          variante(2, tallaId: 1, sku: 'P-S'), // S
          variante(3, tallaId: 2, sku: 'P-M'), // M
        ],
      );
      await sembrarStock(db, varianteId: 1, sucursalId: 1, cantidad: 6, generadoEn: '2026-10-31T09:30:00Z');
      await sembrarStock(db, varianteId: 2, sucursalId: 1, cantidad: 1);
      await sembrarStock(db, varianteId: 1, sucursalId: 2, cantidad: 40);

      final vars = await repo.variantesDeProducto(1, sucursalId: 1);
      expect(vars.map((v) => v.tallaCodigo), ['S', 'M', 'L']);
      expect(vars.map((v) => v.sku), ['P-S', 'P-M', 'P-L']);

      final l = vars.last;
      expect(l.productoId, 1);
      expect(l.tallaOrden, 2);
      expect(l.colorNombre, 'Negro');
      expect(l.colorHex, '#000000');
      expect(l.precioCentavos, 8000);
      expect(l.descuentoCentavos, 500);
      expect(l.precioFinalCentavos, 7500);
      expect(l.cantidadConocida, 6);
      expect(l.cantidadEstimada, 6);
      expect(l.generadoEn, DateTime.utc(2026, 10, 31, 9, 30));
      expect(l.generadoEn!.isUtc, isTrue);
    });

    test('una variante sin stock descargado tiene cantidades 0 y generadoEn null', () async {
      await sembrarProducto(db, id: 1, nombre: 'Polera', variantes: [variante(1)]);
      final v = (await repo.variantesDeProducto(1, sucursalId: 1)).single;
      expect(v.cantidadConocida, 0);
      expect(v.cantidadEstimada, 0);
      expect(v.generadoEn, isNull);
    });

    test('el stock de otra sucursal no se mezcla', () async {
      await sembrarSucursal(db, id: 2);
      await sembrarProducto(db, id: 1, nombre: 'Polera', variantes: [variante(1)]);
      await sembrarStock(db, varianteId: 1, sucursalId: 2, cantidad: 40);
      expect((await repo.variantesDeProducto(1, sucursalId: 1)).single.cantidadConocida, 0);
      expect((await repo.variantesDeProducto(1, sucursalId: 2)).single.cantidadConocida, 40);
    });

    test('variantesDeProducto de un producto inexistente devuelve vacío', () async {
      expect(await repo.variantesDeProducto(404, sucursalId: 1), isEmpty);
    });
  });

  group('sucursalesAutorizadas', () {
    setUp(() async {
      await sembrarSucursal(db, id: 2, nombre: 'Inactiva', activo: false);
      await sembrarSucursal(db, id: 3, nombre: 'No autorizada');
      await sembrarSucursal(db, id: 4, nombre: 'Depósito central', esDeposito: true);
      await sembrarSucursal(db, id: 5, nombre: 'Aaa tienda');
      for (final s in [1, 2, 4, 5]) {
        await db.insert('sucursal_autorizada', {'usuario_id': 10, 'sucursal_id': s});
      }
      await db.insert('sucursal_autorizada', {'usuario_id': 11, 'sucursal_id': 3});
    });

    test('solo las autorizadas y activas, con los depósitos al final', () async {
      final res = await repo.sucursalesAutorizadas(10);
      expect(res.map((s) => s.id), [5, 1, 4]);
      expect(res.last.esDeposito, isTrue);
      expect(res.first.esDeposito, isFalse);
      expect(res.every((s) => s.activo), isTrue);
    });

    test('trae código, nombre y dirección', () async {
      final s = (await repo.sucursalesAutorizadas(10)).firstWhere((s) => s.id == 1);
      expect(s.codigo, 'S1');
      expect(s.nombre, 'Sucursal 1');
      expect(s.direccion, 'Calle 1');
    });

    test('cada usuario ve las suyas', () async {
      expect((await repo.sucursalesAutorizadas(11)).map((s) => s.id), [3]);
    });

    test('un usuario sin autorizaciones no ve ninguna', () async {
      expect(await repo.sucursalesAutorizadas(99), isEmpty);
    });
  });

  group('rendimiento', () {
    test('5.000 productos con 4 variantes buscan en menos de 200 ms', () async {
      const total = 5000;
      await sembrarSucursal(db, id: 2);
      await db.transaction((txn) async {
        final batch = txn.batch();
        const prefijos = ['Camisa', 'Polera', 'Pantalon', 'Chamarra', 'Short'];
        for (var i = 1; i <= total; i++) {
          batch.insert('producto', {
            'id': i,
            'empresa_id': 1,
            'codigo': 'COD-${i.toString().padLeft(5, '0')}',
            'nombre': '${prefijos[i % prefijos.length]} Modelo $i',
            'nombre_busqueda': '${prefijos[i % prefijos.length].toLowerCase()} modelo $i',
            'categoria_id': 1,
            'genero': 'unisex',
          });
          for (var t = 1; t <= 4; t++) {
            final vid = i * 10 + t;
            batch.insert('variante', {
              'id': vid,
              'producto_id': i,
              'talla_id': t,
              'color_id': 1,
              'sku': 'SKU-$i-$t',
              'precio_centavos': 5000 + t * 100,
              'descuento_centavos': t == 2 ? 300 : 0,
            });
            batch.insert('stock_conocido', {
              'variante_id': vid,
              'sucursal_id': 1,
              'cantidad': t,
              'generado_en': '2026-10-31T10:00:00Z',
            });
          }
        }
        await batch.commit(noResult: true);
      });
      expect(await repo.contarProductos(), total);

      Future<void> medir(String nombre, Future<List<Object?>> Function() consulta, {required int esperados}) async {
        await consulta(); // calienta (plan de la consulta, caché de páginas).
        final reloj = Stopwatch()..start();
        final res = await consulta();
        reloj.stop();
        // ignore: avoid_print
        print('  [rendimiento] $nombre: ${reloj.elapsedMilliseconds} ms (${reloj.elapsedMicroseconds} us)');
        expect(res.length, esperados, reason: nombre);
        // Medido en la máquina de desarrollo (equipo de escritorio); el tope de 200 ms deja margen a equipos más lentos.
        expect(reloj.elapsedMilliseconds, lessThan(200), reason: '$nombre tardó ${reloj.elapsedMilliseconds} ms');
      }

      await medir('primera página sin filtro', () => repo.buscarProductos(), esperados: 20);
      await medir('primera página con existencia', () => repo.buscarProductos(sucursalId: 1), esperados: 20);
      await medir('texto "camisa" con existencia', () => repo.buscarProductos(texto: 'camisa', sucursalId: 1), esperados: 20);
      await medir('dos palabras', () => repo.buscarProductos(texto: 'polera modelo 4', limite: 50), esperados: 50);
      await medir('por SKU', () => repo.buscarProductos(texto: 'sku-2500-3'), esperados: 1);
      await medir('por código', () => repo.buscarProductos(texto: 'cod-04999', sucursalId: 1), esperados: 1);
      await medir('página lejana', () => repo.buscarProductos(desplazamiento: 4900, limite: 20, sucursalId: 1), esperados: 20);
      await medir('sin coincidencias', () => repo.buscarProductos(texto: 'zapatilla'), esperados: 0);
      await medir('con categoría', () => repo.buscarProductos(categoriaId: 1, texto: 'short'), esperados: 20);
    });
  });
}
