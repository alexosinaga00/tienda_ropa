import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/vendedor/data/almacen_paquete.dart';
import 'package:mobile/features/vendedor/data/descarga_repository.dart';
import 'package:mobile/features/vendedor/data/politica_vigencia.dart';
import 'package:mobile/features/vendedor/state/catalogo_local_providers.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';
import 'apoyo_operaciones.dart';
import 'apoyo_paquete.dart';

final _ahora = DateTime.utc(2026, 10, 31, 12);

Future<void> _autorizar(Database db, int usuarioId, List<int> sucursales) async {
  for (final s in sucursales) {
    await db.insert('sucursal_autorizada', {'usuario_id': usuarioId, 'sucursal_id': s});
  }
}

Future<void> _descargadoHace(Database db, Duration edad, {int empresaId = 1, int sucursalId = 1}) async {
  await db.insert('descarga', {
    'empresa_id': empresaId,
    'sucursal_id': sucursalId,
    'descargado_en': _ahora.subtract(edad).toIso8601String(),
    'generado_en': _ahora.subtract(edad).toIso8601String(),
    'completo': 1,
  });
}

void main() {
  late Database db;
  late RelojManual reloj;

  setUp(() async {
    db = await abrirBaseDePrueba();
    addTearDown(db.close);
    await sembrarDosEmpresas(db);
    reloj = RelojManual(_ahora);
  });

  group('empresa y usuario de la sesión', () {
    test('sin sesión ambos son null', () {
      final c = contenedorLocal(db);

      expect(c.read(empresaLocalIdProvider), isNull);
      expect(c.read(usuarioLocalIdProvider), isNull);
    });

    test('con sesión salen del usuario autenticado', () {
      final c = contenedorLocal(db, auth: sesionDe(personalDe(id: 9, empresaId: 2, codigo: 'andina')));

      expect(c.read(empresaLocalIdProvider), 2);
      expect(c.read(usuarioLocalIdProvider), 9);
    });
  });

  group('catalogoLocalProvider', () {
    test('sin sesión es null', () async {
      final c = contenedorLocal(db);

      expect(await c.read(catalogoLocalProvider.future), isNull);
    });

    test('con sesión da el catálogo de la empresa de la sesión, sin mezclar la otra', () async {
      final c = contenedorLocal(db, auth: sesionDe(personalDe()));

      final catalogo = (await c.read(catalogoLocalProvider.future))!;
      final productos = await catalogo.buscarProductos();

      expect([for (final p in productos) p.nombre], ['Polera Básica']);
      expect(await catalogo.contarProductos(), 1);
      expect(await catalogo.productoPorId(20), isNull, reason: 'el producto 20 es de la otra empresa');
    });

    test('cambiar de empresa cambia la partición que se ve', () async {
      final c = contenedorLocal(db, auth: sesionDe(personalDe()));
      final primero = (await c.read(catalogoLocalProvider.future))!;
      expect([for (final p in await primero.buscarProductos()) p.nombre], ['Polera Básica']);

      (c.read(authControllerProvider.notifier) as AuthControllerFijo).fijar(
        sesionDe(personalDe(empresaId: 2, codigo: 'andina')),
      );
      final segundo = (await c.read(catalogoLocalProvider.future))!;

      expect([for (final p in await segundo.buscarProductos()) p.nombre], ['Chompa Andina']);
      expect(await segundo.productoPorId(10), isNull);
    });

    test('al cerrar la sesión vuelve a null', () async {
      final c = contenedorLocal(db, auth: sesionDe(personalDe()));
      expect(await c.read(catalogoLocalProvider.future), isNotNull);

      (c.read(authControllerProvider.notifier) as AuthControllerFijo).fijar(sinSesion);

      expect(await c.read(catalogoLocalProvider.future), isNull);
    });
  });

  group('sucursalesAutorizadasProvider', () {
    test('sin sesión es una lista vacía', () async {
      final c = contenedorLocal(db);

      expect(await c.read(sucursalesAutorizadasProvider.future), isEmpty);
    });

    test('solo trae las autorizadas al usuario y activas', () async {
      await sembrarSucursal(db, id: 2);
      await sembrarSucursal(db, id: 3, activo: false);
      await sembrarSucursal(db, id: 4);
      await _autorizar(db, 7, [1, 2, 3]);
      await _autorizar(db, 8, [4]);
      final c = contenedorLocal(db, auth: sesionDe(personalDe()));

      final ids = [for (final s in await c.read(sucursalesAutorizadasProvider.future)) s.id]..sort();

      expect(ids, [1, 2]);
    });
  });

  group('sucursalActivaProvider', () {
    test('sin sesión es null', () async {
      final c = contenedorLocal(db);

      expect(await c.read(sucursalActivaProvider.future), isNull);
    });

    test('sin sucursales descargadas ni autorizadas es null', () async {
      final c = contenedorLocal(db, auth: sesionDe(personalDe()));

      expect(await c.read(sucursalActivaProvider.future), isNull);
    });

    test('la guardada, si sigue autorizada', () async {
      await sembrarSucursal(db, id: 2);
      await sembrarSucursal(db, id: 3);
      await _autorizar(db, 7, [1, 2, 3]);
      await DescargaRepositorySqlite(db).fijarSucursalActiva(1, 7, 3);
      final c = contenedorLocal(db, auth: sesionDe(personalDe()));

      expect(await c.read(sucursalActivaProvider.future), 3);
    });

    test('si la guardada ya no está autorizada, la primera que no es depósito', () async {
      await sembrarSucursal(db, id: 2, esDeposito: true);
      await sembrarSucursal(db, id: 3);
      await _autorizar(db, 7, [2, 3]);
      await DescargaRepositorySqlite(db).fijarSucursalActiva(1, 7, 1); // la 1 existe, pero no es de este usuario
      final c = contenedorLocal(db, auth: sesionDe(personalDe()));

      expect(await c.read(sucursalActivaProvider.future), 3);
    });

    test('sin ninguna guardada, la primera que no es depósito', () async {
      await sembrarSucursal(db, id: 2, esDeposito: true);
      await _autorizar(db, 7, [1, 2]);
      final c = contenedorLocal(db, auth: sesionDe(personalDe()));

      expect(await c.read(sucursalActivaProvider.future), 1);
    });

    test('si solo hay depósitos, usa el primero', () async {
      await sembrarSucursal(db, id: 2, esDeposito: true);
      await _autorizar(db, 7, [2]);
      final c = contenedorLocal(db, auth: sesionDe(personalDe()));

      expect(await c.read(sucursalActivaProvider.future), 2);
    });

    test('la sucursal guardada por otro usuario no se usa', () async {
      await sembrarSucursal(db, id: 2);
      await _autorizar(db, 7, [1, 2]);
      await DescargaRepositorySqlite(db).fijarSucursalActiva(1, 8, 2);
      final c = contenedorLocal(db, auth: sesionDe(personalDe()));

      expect(await c.read(sucursalActivaProvider.future), 1);
    });

    test('se recalcula cuando termina una descarga', () async {
      final c = contenedorLocal(db, auth: sesionDe(personalDe()));
      expect(await c.read(sucursalActivaProvider.future), isNull);

      await _autorizar(db, 7, [1]);
      c.read(descargaTerminadaProvider.notifier).state++;

      expect(await c.read(sucursalActivaProvider.future), 1);
    });

    test('cambiar de empresa cambia la sucursal activa', () async {
      await _autorizar(db, 7, [1, 11]);
      final c = contenedorLocal(db, auth: sesionDe(personalDe()));
      expect(await c.read(sucursalActivaProvider.future), 1);

      (c.read(authControllerProvider.notifier) as AuthControllerFijo).fijar(
        sesionDe(personalDe(empresaId: 2, codigo: 'andina')),
      );

      expect(await c.read(sucursalActivaProvider.future), 11);
    });
  });

  group('vigenciaProvider', () {
    Future<ResumenVigencia> vigencia(Duration? edad, {int? avisoHoras, bool autorizada = true}) async {
      if (autorizada) await _autorizar(db, 7, [1]);
      if (edad != null) await _descargadoHace(db, edad);
      if (avisoHoras != null) {
        await db.insert('meta', {'clave': claveMetaAvisoHoras(1), 'valor': '$avisoHoras'});
      }
      final c = contenedorLocal(db, auth: sesionDe(personalDe()), reloj: reloj);
      return c.read(vigenciaProvider.future);
    }

    test('sin sesión es "nunca"', () async {
      final c = contenedorLocal(db, reloj: reloj);

      final v = await c.read(vigenciaProvider.future);

      expect(v.estado, EstadoVigencia.nunca);
      expect(v.descargadoEn, isNull);
      expect(v.edad, isNull);
    });

    test('con sucursal pero sin descarga es "nunca"', () async {
      final v = await vigencia(null);

      expect(v.estado, EstadoVigencia.nunca);
      expect(v.descargadoEn, isNull);
    });

    test('sin sucursal activa (nada autorizado) es "nunca"', () async {
      final v = await vigencia(const Duration(minutes: 5), autorizada: false);

      expect(v.estado, EstadoVigencia.nunca);
    });

    test('fresca: 30 minutos, con la edad y la hora de la descarga', () async {
      final v = await vigencia(const Duration(minutes: 30));

      expect(v.estado, EstadoVigencia.fresca);
      expect(v.edad, const Duration(minutes: 30));
      expect(v.descargadoEn, _ahora.subtract(const Duration(minutes: 30)));
    });

    test('antigua: 3 horas con el aviso por defecto de 2 h', () async {
      expect((await vigencia(const Duration(hours: 3))).estado, EstadoVigencia.antigua);
    });

    test('crítica: 25 horas', () async {
      expect((await vigencia(const Duration(hours: 25))).estado, EstadoVigencia.critica);
    });

    test('con aviso_horas = 1 del servidor, 90 minutos ya es antigua (con el de por defecto sería fresca)', () async {
      expect((await vigencia(const Duration(minutes: 90), avisoHoras: 1)).estado, EstadoVigencia.antigua);
    });

    test('con aviso_horas = 12 del servidor, 3 horas sigue fresca', () async {
      expect((await vigencia(const Duration(hours: 3), avisoHoras: 12)).estado, EstadoVigencia.fresca);
    });

    test('con aviso_horas = 30, lo crítico sube a 31 h: a 30 h es antigua', () async {
      expect((await vigencia(const Duration(hours: 30), avisoHoras: 30)).estado, EstadoVigencia.antigua);
    });

    test('con aviso_horas = 30, a 31 h es crítica', () async {
      expect((await vigencia(const Duration(hours: 31), avisoHoras: 30)).estado, EstadoVigencia.critica);
    });

    test('el aviso de la otra empresa no cuenta', () async {
      await db.insert('meta', {'clave': claveMetaAvisoHoras(2), 'valor': '1'});

      expect((await vigencia(const Duration(minutes: 90))).estado, EstadoVigencia.fresca);
    });

    test('la vigencia es de la sucursal activa: la descarga de otra sucursal no cuenta', () async {
      await sembrarSucursal(db, id: 2);
      await _autorizar(db, 7, [1, 2]);
      await _descargadoHace(db, const Duration(minutes: 5), sucursalId: 2);
      await DescargaRepositorySqlite(db).fijarSucursalActiva(1, 7, 1);
      final c = contenedorLocal(db, auth: sesionDe(personalDe()), reloj: reloj);

      expect((await c.read(vigenciaProvider.future)).estado, EstadoVigencia.nunca);
    });

    test('usa el reloj: al avanzar la hora y terminar otra descarga pasa de fresca a antigua', () async {
      await _autorizar(db, 7, [1]);
      await _descargadoHace(db, const Duration(minutes: 30));
      final c = contenedorLocal(db, auth: sesionDe(personalDe()), reloj: reloj);
      expect((await c.read(vigenciaProvider.future)).estado, EstadoVigencia.fresca);

      reloj.actual = reloj.actual.add(const Duration(hours: 2));
      c.read(descargaTerminadaProvider.notifier).state++;

      final v = await c.read(vigenciaProvider.future);
      expect(v.estado, EstadoVigencia.antigua);
      expect(v.edad, const Duration(hours: 2, minutes: 30));
    });

    test('cambiar de empresa cambia la partición: la otra empresa nunca descargó', () async {
      await _autorizar(db, 7, [1, 11]);
      await _descargadoHace(db, const Duration(minutes: 5));
      final c = contenedorLocal(db, auth: sesionDe(personalDe()), reloj: reloj);
      expect((await c.read(vigenciaProvider.future)).estado, EstadoVigencia.fresca);

      (c.read(authControllerProvider.notifier) as AuthControllerFijo).fijar(
        sesionDe(personalDe(empresaId: 2, codigo: 'andina')),
      );

      expect((await c.read(vigenciaProvider.future)).estado, EstadoVigencia.nunca);
    });
  });
}
