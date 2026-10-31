import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/features/vendedor/data/almacen_paquete.dart';
import 'package:mobile/features/vendedor/data/descarga_repository.dart';
import 'package:mobile/features/vendedor/data/paquete_api.dart';
import 'package:mobile/features/vendedor/state/descarga_catalogo_service.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/api_client_falso.dart';
import '../../helpers/base_local_falsa.dart';
import 'apoyo_paquete.dart';

/// Todo lo guardado de una empresa, para comparar antes y después de reabrir la base.
Future<Map<String, List<Map<String, Object?>>>> instantanea(Database db) async {
  Future<List<Map<String, Object?>>> todo(String sql) async => [for (final f in await db.rawQuery(sql)) Map.of(f)];
  return {
    'empresa': await todo('SELECT * FROM empresa ORDER BY id'),
    'sucursal': await todo('SELECT * FROM sucursal ORDER BY id'),
    'horario': await todo('SELECT * FROM sucursal_horario ORDER BY sucursal_id, dia_semana'),
    'autorizada': await todo('SELECT * FROM sucursal_autorizada ORDER BY usuario_id, sucursal_id'),
    'producto': await todo('SELECT * FROM producto ORDER BY id'),
    'variante': await todo('SELECT * FROM variante ORDER BY id'),
    'stock': await todo('SELECT * FROM stock_conocido ORDER BY sucursal_id, variante_id'),
    'cliente': await todo('SELECT * FROM cliente_minimo ORDER BY id'),
    'descarga': await todo('SELECT * FROM descarga ORDER BY empresa_id, sucursal_id'),
    'meta': await todo('SELECT * FROM meta ORDER BY clave'),
  };
}

void main() {
  late Directory directorio;
  late String ruta;
  late RelojManual reloj;
  late ApiClientFalso api;

  setUp(() {
    directorio = Directory.systemTemp.createTempSync('fashionstore_reinicio_');
    ruta = p.join(directorio.path, 'local.db');
    reloj = RelojManual(DateTime.utc(2026, 10, 31, 12));
    api = ApiClientFalso();
  });

  tearDown(() {
    try {
      directorio.deleteSync(recursive: true);
    } on FileSystemException {
      // En Windows el archivo puede tardar en soltarse; no es un fallo de la prueba.
    }
  });

  DescargaCatalogoService crearServicio(Database db) =>
      DescargaCatalogoService(PaqueteApi(api), AlmacenPaqueteSqlite(db, reloj), DescargaRepositorySqlite(db), reloj);

  test('al cerrar y reabrir la base, los datos y la descarga siguen igual', () async {
    prepararServidor(api);
    var db = await abrirBaseDePrueba(ruta: ruta);
    final resultado = await crearServicio(db).descargar(sucursalId: 1, usuarioId: 7);
    expect(resultado, isA<DescargaExitosa>());
    await DescargaRepositorySqlite(db).fijarSucursalActiva(1, 7, 1);
    final antes = await instantanea(db);
    final ultimaAntes = (await DescargaRepositorySqlite(db).ultimaDescarga(1, 1))!;
    await db.close();

    db = await abrirBaseDePrueba(ruta: ruta);
    addTearDown(db.close);

    expect(await instantanea(db), antes);
    final repo = DescargaRepositorySqlite(db);
    final ultima = (await repo.ultimaDescarga(1, 1))!;
    expect(ultima.descargadoEn, ultimaAntes.descargadoEn);
    expect(ultima.generadoEn, ultimaAntes.generadoEn);
    expect(ultima.completo, ultimaAntes.completo);
    expect(await repo.sucursalActiva(1, 7), 1);
    expect(await repo.avisoHoras(1), 12);
    expect(await stockDe(db, 1), {100: 5, 101: 3, 110: 2, 111: 0});
    expect(await db.rawQuery('PRAGMA foreign_key_check'), isEmpty);
  });

  test('una operación pendiente insertada a mano sobrevive al reinicio y a una descarga posterior', () async {
    prepararServidor(api);
    prepararServidor(api, manifiesto: jsonManifiesto(generadoEn: '2026-10-31T11:00:00Z'), paginasStock: [jsonPaginaStock(1, [jsonItemStock(100, 9)], incremental: true)]);
    var db = await abrirBaseDePrueba(ruta: ruta);
    await crearServicio(db).descargar(sucursalId: 1, usuarioId: 7);
    await sembrarVentaPendiente(db, operacionId: 'op-viva', varianteId: 100);
    final operacionAntes = (await db.query('operacion_pendiente')).single;
    await db.close();

    db = await abrirBaseDePrueba(ruta: ruta);
    addTearDown(db.close);

    expect((await db.query('operacion_pendiente')).single, operacionAntes);
    expect(await contar(db, 'venta_detalle'), 1);

    // Y una descarga nueva, ya con la base reabierta, tampoco la toca.
    await crearServicio(db).descargar(sucursalId: 1, usuarioId: 7);
    expect((await db.query('operacion_pendiente')).single, operacionAntes);
    expect(await contar(db, 'venta_detalle'), 1);
  });

  test('tras reiniciar, la siguiente descarga es incremental con el generado_en que quedó guardado', () async {
    prepararServidor(api);
    prepararServidor(api, paginasStock: [jsonPaginaStock(1, [jsonItemStock(100, 9)], incremental: true, generadoEn: '2026-10-31T11:00:02Z')]);
    var db = await abrirBaseDePrueba(ruta: ruta);
    await crearServicio(db).descargar(sucursalId: 1, usuarioId: 7);
    await db.close();

    db = await abrirBaseDePrueba(ruta: ruta);
    addTearDown(db.close);
    final r = await crearServicio(db).descargar(sucursalId: 1, usuarioId: 7);

    expect((r as DescargaExitosa).completa, isFalse);
    expect(api.de('GET', rutaStock).last.query!['desde'], '2026-10-31T10:00:02Z');
    expect(await stockDe(db, 1), {100: 9, 101: 3, 110: 2, 111: 0});
  });

  test('una operación enviada que sobrevivió al reinicio pospone la descarga', () async {
    prepararServidor(api);
    var db = await abrirBaseDePrueba(ruta: ruta);
    await crearServicio(db).descargar(sucursalId: 1, usuarioId: 7);
    await sembrarVentaPendiente(db, operacionId: 'op-enviada', varianteId: 100, estado: 'enviada');
    await db.close();
    final llamadasAntes = api.llamadas.length;

    db = await abrirBaseDePrueba(ruta: ruta);
    addTearDown(db.close);
    final r = await crearServicio(db).descargar(sucursalId: 1, usuarioId: 7);

    expect(r, isA<DescargaPospuesta>());
    expect(api.llamadas.length, llamadasAntes);
  });

  test('una descarga que falla deja el archivo igual que estaba, también tras reabrir', () async {
    prepararServidor(api);
    api.responder('GET', rutaManifiesto, const ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: 'Sin conexión.'));
    var db = await abrirBaseDePrueba(ruta: ruta);
    final servicio = crearServicio(db);
    await servicio.descargar(sucursalId: 1, usuarioId: 7);
    final antes = await instantanea(db);

    final r = await servicio.descargar(sucursalId: 1, usuarioId: 7);
    expect(r, isA<DescargaFallida>());
    await db.close();

    db = await abrirBaseDePrueba(ruta: ruta);
    addTearDown(db.close);
    expect(await instantanea(db), antes);
  });

  group('dos empresas en la misma base', () {
    // Chaski (empresa 1, sucursal 1) y Andina (empresa 2, sucursales 201 y 202), en este orden de llamadas:
    // Chaski, Andina, Chaski otra vez.
    void prepararDosEmpresas() {
      prepararServidor(api);
      prepararServidor(
        api,
        manifiesto: jsonManifiesto(empresaId: 2, codigo: 'andina', nombre: 'Boutique Andina'),
        paginasCatalogo: [
          jsonPaginaCatalogo([
            jsonProducto(20, 'Falda Andina', categoria: 201, variantes: [jsonVariante(200, talla: 201, color: 201, sku: 'SKU-200')]),
          ]),
        ],
        paginasStock: [jsonPaginaStock(201, [jsonItemStock(200, 6)])],
        paginasClientes: [jsonPaginaClientes([jsonCliente(50, 'Rosa', ci: '555')])],
      );
      // Chaski otra vez: sin la Camisa, con otro precio y sin stock nuevo.
      prepararServidor(
        api,
        manifiesto: jsonManifiesto(generadoEn: '2026-10-31T13:00:00Z'),
        paginasCatalogo: [
          jsonPaginaCatalogo([jsonProducto(10, 'Polera Básica', variantes: [jsonVariante(100, precio: '10.00')])]),
        ],
        paginasStock: [jsonPaginaStock(1, [jsonItemStock(100, 1)], incremental: true, generadoEn: '2026-10-31T13:00:02Z')],
        paginasClientes: const [],
      );
    }

    test('bajar el paquete de una no toca a la otra (ni al reiniciar)', () async {
      prepararDosEmpresas();
      var db = await abrirBaseDePrueba(ruta: ruta);
      var servicio = crearServicio(db);
      await servicio.descargar(sucursalId: 1, usuarioId: 7);
      await servicio.descargar(sucursalId: 201, usuarioId: 9);

      Future<Map<String, Object?>> deAndina(Database d) async => {
        'productos': await d.query('producto', where: 'empresa_id = 2'),
        'variantes': await d.rawQuery('SELECT v.* FROM variante v JOIN producto p ON p.id = v.producto_id WHERE p.empresa_id = 2'),
        'stock': await d.query('stock_conocido', where: 'sucursal_id IN (201, 202)'),
        'descarga': await d.query('descarga', where: 'empresa_id = 2'),
        'clientes': await d.query('cliente_minimo', where: 'empresa_id = 2'),
        'autorizada': await d.query('sucursal_autorizada', where: 'usuario_id = 9'),
      };
      final andinaAntes = await deAndina(db);
      await db.close();

      db = await abrirBaseDePrueba(ruta: ruta);
      addTearDown(db.close);
      servicio = crearServicio(db);
      final r = await servicio.descargar(sucursalId: 1, usuarioId: 7);

      expect(r, isA<DescargaExitosa>());
      expect(await deAndina(db), andinaAntes);
      // Y lo de Chaski sí cambió.
      expect((await db.query('producto', where: 'id = 11')).single['activo'], 0);
      expect((await db.query('variante', where: 'id = 100')).single['precio_centavos'], 1000);
      expect((await db.query('producto', where: 'id = 20')).single['activo'], 1);
      expect(await contar(db, 'cliente_minimo', donde: 'empresa_id = 1'), 2);
      expect(await contar(db, 'cliente_minimo', donde: 'empresa_id = 2'), 1);
    });

    test('la vigencia de cada empresa es suya', () async {
      prepararDosEmpresas();
      final db = await abrirBaseDePrueba(ruta: ruta);
      addTearDown(db.close);
      final servicio = crearServicio(db);
      await servicio.descargar(sucursalId: 1, usuarioId: 7);
      await servicio.descargar(sucursalId: 201, usuarioId: 9);
      final repo = DescargaRepositorySqlite(db);

      expect((await repo.ultimaDescarga(1, 1))!.generadoEn, DateTime.utc(2026, 10, 31, 10, 0, 2));
      expect((await repo.ultimaDescarga(2, 201))!.generadoEn, DateTime.utc(2026, 10, 31, 10, 0, 2));
      expect(await repo.ultimaDescarga(1, 201), isNull);
      expect(await repo.ultimaDescarga(2, 1), isNull);
      expect(await repo.avisoHoras(2), 12);
    });

    test('una operación enviada de una empresa no frena la descarga de la otra', () async {
      prepararDosEmpresas();
      final db = await abrirBaseDePrueba(ruta: ruta);
      addTearDown(db.close);
      final servicio = crearServicio(db);
      await servicio.descargar(sucursalId: 1, usuarioId: 7);
      await sembrarVentaPendiente(db, operacionId: 'op-chaski', varianteId: 100, estado: 'enviada');

      final r = await servicio.descargar(sucursalId: 201, usuarioId: 9);

      expect(r, isA<DescargaExitosa>());
      expect(await contar(db, 'producto', donde: 'empresa_id = 2'), 1);
    });
  });
}
