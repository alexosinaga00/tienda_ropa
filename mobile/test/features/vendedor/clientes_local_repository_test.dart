import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/vendedor/data/clientes_local_repository.dart';
import 'package:mobile/features/vendedor/models/cliente_local.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';
import '../../helpers/siembra_operaciones.dart';

void main() {
  late Database db;
  late ClientesLocalSqlite repo;

  setUp(() async {
    db = await abrirBaseDePrueba();
    await sembrarEmpresa(db);
    await sembrarEmpresa(db, id: 2, codigo: 'andina', nombre: 'Boutique Andina');
    repo = ClientesLocalSqlite(db, empresaId: 1);
  });

  tearDown(() async {
    await db.close();
  });

  Future<List<String>> nombres(String? texto, {int limite = 50, int desplazamiento = 0}) async {
    final r = await repo.buscar(texto: texto, limite: limite, desplazamiento: desplazamiento);
    return r.map((c) => c.nombreCompleto).toList();
  }

  group('qué clientes se ven', () {
    test('solo los de la empresa y que ya están en el servidor', () async {
      await sembrarClienteMinimo(db, servidorId: 10, nombre: 'Ana', apellido: 'Pérez');
      await sembrarClienteMinimo(db, nombre: 'Solo', apellido: 'Teléfono'); // sin servidor_id
      await sembrarClienteMinimo(db, empresaId: 2, servidorId: 20, nombre: 'Ajena', apellido: 'Empresa');
      expect(await nombres(null), ['Ana Pérez']);
    });

    test('la otra empresa ve solo lo suyo', () async {
      await sembrarClienteMinimo(db, servidorId: 10, nombre: 'Ana');
      await sembrarClienteMinimo(db, empresaId: 2, servidorId: 20, nombre: 'Rosa');
      final otra = ClientesLocalSqlite(db, empresaId: 2);
      expect((await otra.buscar()).map((c) => c.nombre), ['Rosa']);
      expect(await ClientesLocalSqlite(db, empresaId: 3).buscar(), isEmpty);
    });

    test('sin clientes devuelve vacío', () async {
      expect(await repo.buscar(), isEmpty);
    });

    test('devuelve el id local y el del servidor', () async {
      final id = await sembrarClienteMinimo(db, servidorId: 501, nombre: 'Ana', apellido: 'Pérez', ciNit: '1234567');
      final c = (await repo.buscar()).single;
      expect(c.id, id);
      expect(c.servidorId, 501);
      expect(c.nombre, 'Ana');
      expect(c.apellido, 'Pérez');
      expect(c.ciNit, '1234567');
    });

    test('un cliente enlazado después (le llega el servidor_id) aparece', () async {
      final id = await sembrarClienteMinimo(db, nombre: 'Luis');
      expect(await repo.buscar(), isEmpty);
      await db.update('cliente_minimo', {'servidor_id': 99}, where: 'id = ?', whereArgs: [id]);
      expect((await repo.buscar()).single.servidorId, 99);
    });
  });

  group('porId', () {
    test('devuelve el cliente por su id LOCAL', () async {
      final id = await sembrarClienteMinimo(db, servidorId: 501, nombre: 'Ana', apellido: 'Pérez');
      final c = await repo.porId(id);
      expect(c, isNotNull);
      expect(c!.servidorId, 501);
      expect(c.nombreCompleto, 'Ana Pérez');
    });

    test('null si no existe', () async {
      expect(await repo.porId(999), isNull);
    });

    test('null si es de otra empresa', () async {
      final id = await sembrarClienteMinimo(db, empresaId: 2, servidorId: 20, nombre: 'Rosa');
      expect(await repo.porId(id), isNull);
      expect(await ClientesLocalSqlite(db, empresaId: 2).porId(id), isNotNull);
    });

    test('null si todavía no tiene servidor_id', () async {
      final id = await sembrarClienteMinimo(db, nombre: 'Luis');
      expect(await repo.porId(id), isNull);
    });

    test('el id del servidor NO sirve como id local', () async {
      await sembrarClienteMinimo(db, servidorId: 501, nombre: 'Ana');
      expect(await repo.porId(501), isNull);
    });
  });

  group('búsqueda', () {
    setUp(() async {
      await sembrarClienteMinimo(db, servidorId: 1, nombre: 'José', apellido: 'Núñez', ciNit: '1111111');
      await sembrarClienteMinimo(db, servidorId: 2, nombre: 'MARÍA', apellido: 'MUÑOZ', ciNit: '2222222-1A');
      await sembrarClienteMinimo(db, servidorId: 3, nombre: 'Ángel', apellido: 'Quispe', ciNit: '3333333');
      await sembrarClienteMinimo(db, servidorId: 4, nombre: 'Pedro', apellido: 'Pérez Gómez', ciNit: '4444444');
      await sembrarClienteMinimo(db, servidorId: 5, nombre: 'Ñusta', ciNit: '5555555');
    });

    test('por nombre sin tildes ni mayúsculas', () async {
      expect(await nombres('jose'), ['José Núñez']);
      expect(await nombres('JOSÉ'), ['José Núñez']);
      expect(await nombres('JoSe'), ['José Núñez']);
    });

    test('por apellido, con ñ y tildes', () async {
      expect(await nombres('nunez'), ['José Núñez']);
      expect(await nombres('núñez'), ['José Núñez']);
      expect(await nombres('NÚÑEZ'), ['José Núñez']);
    });

    test('un nombre guardado en MAYÚSCULAS con tilde se encuentra con minúsculas y sin tilde', () async {
      expect(await nombres('maria'), ['MARÍA MUÑOZ']);
      expect(await nombres('munoz'), ['MARÍA MUÑOZ']);
      expect(await nombres('muñoz'), ['MARÍA MUÑOZ']);
      expect(await nombres('María'), ['MARÍA MUÑOZ']);
    });

    test('una mayúscula acentuada inicial: "angel" y "ÁNGEL" encuentran "Ángel"', () async {
      expect(await nombres('angel'), ['Ángel Quispe']);
      expect(await nombres('ÁNGEL'), ['Ángel Quispe']);
    });

    test('la ñ al inicio: "nusta" encuentra "Ñusta"', () async {
      expect(await nombres('nusta'), ['Ñusta']);
      expect(await nombres('ÑUSTA'), ['Ñusta']);
    });

    test('por CI/NIT, completo o parcial', () async {
      expect(await nombres('4444444'), ['Pedro Pérez Gómez']);
      expect(await nombres('4444'), ['Pedro Pérez Gómez']);
      expect(await nombres('2222222-1a'), ['MARÍA MUÑOZ']);
      expect(await nombres('2222222-1A'), ['MARÍA MUÑOZ']);
    });

    test('coincidencia parcial en cualquier parte', () async {
      expect(await nombres('quis'), ['Ángel Quispe']);
      expect(await nombres('edr'), ['Pedro Pérez Gómez']);
    });

    test('varias palabras: todas deben aparecer, en cualquier orden', () async {
      expect(await nombres('pedro gomez'), ['Pedro Pérez Gómez']);
      expect(await nombres('gomez pedro'), ['Pedro Pérez Gómez']);
      expect(await nombres('perez gomez'), ['Pedro Pérez Gómez']);
      expect(await nombres('pedro quispe'), isEmpty);
    });

    test('nombre y apellido juntos', () async {
      expect(await nombres('jose nunez'), ['José Núñez']);
      expect(await nombres('Maria Muñoz'), ['MARÍA MUÑOZ']);
    });

    test('espacios de más no estorban', () async {
      expect(await nombres('   jose   nunez  '), ['José Núñez']);
    });

    test('texto vacío, nulo o solo espacios devuelve todos', () async {
      expect(await nombres(null), hasLength(5));
      expect(await nombres(''), hasLength(5));
      expect(await nombres('    '), hasLength(5));
    });

    test('sin coincidencias devuelve vacío', () async {
      expect(await nombres('zzzz'), isEmpty);
    });

    test('un cliente sin apellido ni CI también se busca por nombre', () async {
      await sembrarClienteMinimo(db, servidorId: 6, nombre: 'Sinapellido');
      expect(await nombres('sinapel'), ['Sinapellido']);
    });

    test('NO encuentra clientes sin servidor_id aunque coincidan', () async {
      await sembrarClienteMinimo(db, nombre: 'José', apellido: 'Solo');
      expect(await nombres('solo'), isEmpty);
      expect(await nombres('jose'), ['José Núñez']);
    });

    test('NO encuentra clientes de otra empresa aunque coincidan', () async {
      await sembrarClienteMinimo(db, empresaId: 2, servidorId: 70, nombre: 'José', apellido: 'Ajeno');
      expect(await nombres('ajeno'), isEmpty);
    });

    test('"ç" y las demás vocales con diéresis o acento grave se igualan', () async {
      await sembrarClienteMinimo(db, servidorId: 7, nombre: 'François', apellido: 'Müller');
      expect(await nombres('francois'), ['François Müller']);
      expect(await nombres('muller'), ['François Müller']);
      expect(await nombres('MÜLLER'), ['François Müller']);
    });
  });

  group('comodines de LIKE', () {
    setUp(() async {
      await sembrarClienteMinimo(db, servidorId: 1, nombre: 'Ana', apellido: '100%', ciNit: 'A_1');
      await sembrarClienteMinimo(db, servidorId: 2, nombre: 'Beto', apellido: 'Pérez', ciNit: 'AX1');
      await sembrarClienteMinimo(db, servidorId: 3, nombre: 'Carla', apellido: r'Ruiz\Díaz');
    });

    test('% se busca como texto, no como comodín', () async {
      expect(await nombres('%'), ['Ana 100%']);
      expect(await nombres('100%'), ['Ana 100%']);
    });

    test('_ se busca como texto: "a_1" no encuentra "AX1"', () async {
      expect(await nombres('a_1'), ['Ana 100%']);
      expect(await nombres('_'), ['Ana 100%']);
    });

    test(r'la barra invertida se busca como texto', () async {
      expect(await nombres(r'ruiz\diaz'), [r'Carla Ruiz\Díaz']);
      expect(await nombres(r'\'), [r'Carla Ruiz\Díaz']);
    });

    test('una comilla simple no rompe la consulta', () async {
      await sembrarClienteMinimo(db, servidorId: 4, nombre: "D'Angelo");
      expect(await nombres("d'ang"), ["D'Angelo"]);
      expect(await nombres("'; DROP TABLE cliente_minimo; --"), isEmpty);
      expect(await nombres(null), hasLength(4));
    });
  });

  group('orden y paginación', () {
    setUp(() async {
      // Orden esperado por nombre normalizado: Alberto, Álvaro, Ana, Bruno, Carla (Ángel va con la "a").
      await sembrarClienteMinimo(db, servidorId: 1, nombre: 'Carla', apellido: 'Z');
      await sembrarClienteMinimo(db, servidorId: 2, nombre: 'Álvaro', apellido: 'Y');
      await sembrarClienteMinimo(db, servidorId: 3, nombre: 'Bruno', apellido: 'X');
      await sembrarClienteMinimo(db, servidorId: 4, nombre: 'Alberto', apellido: 'W');
      await sembrarClienteMinimo(db, servidorId: 5, nombre: 'ana', apellido: 'V');
    });

    test('ordena por nombre sin importar mayúsculas ni tildes', () async {
      expect((await repo.buscar(limite: 50)).map((c) => c.nombre), ['Alberto', 'Álvaro', 'ana', 'Bruno', 'Carla']);
    });

    test('con el mismo nombre ordena por apellido y luego por id', () async {
      await sembrarClienteMinimo(db, servidorId: 6, nombre: 'Bruno', apellido: 'A');
      await sembrarClienteMinimo(db, servidorId: 7, nombre: 'Bruno', apellido: 'A');
      final r = (await repo.buscar(limite: 50)).where((c) => c.nombre == 'Bruno').toList();
      expect(r.map((c) => c.apellido), ['A', 'A', 'X']);
      expect(r[0].id < r[1].id, isTrue);
    });

    test('el límite por defecto es 20', () async {
      for (var i = 0; i < 30; i++) {
        await sembrarClienteMinimo(db, servidorId: 100 + i, nombre: 'Cliente ${i.toString().padLeft(2, '0')}');
      }
      expect(await repo.buscar(), hasLength(20));
    });

    test('limite y desplazamiento recorren todo sin repetir ni saltar', () async {
      final todos = (await repo.buscar(limite: 50)).map((c) => c.nombre).toList();
      final paginas = <String>[];
      for (var d = 0; d < todos.length; d += 2) {
        paginas.addAll((await repo.buscar(limite: 2, desplazamiento: d)).map((c) => c.nombre));
      }
      expect(paginas, todos);
    });

    test('una página más allá del final es vacía', () async {
      expect(await repo.buscar(limite: 10, desplazamiento: 5), isEmpty);
      expect(await repo.buscar(limite: 10, desplazamiento: 500), isEmpty);
    });

    test('límite cero o negativo devuelve vacío', () async {
      expect(await repo.buscar(limite: 0), isEmpty);
      expect(await repo.buscar(limite: -1), isEmpty);
    });

    test('un desplazamiento negativo cuenta como cero', () async {
      expect((await repo.buscar(limite: 2, desplazamiento: -5)).map((c) => c.nombre), ['Alberto', 'Álvaro']);
    });

    test('la paginación respeta el texto buscado', () async {
      expect((await repo.buscar(texto: 'a', limite: 2)).map((c) => c.nombre), ['Alberto', 'Álvaro']);
      expect((await repo.buscar(texto: 'a', limite: 2, desplazamiento: 2)).map((c) => c.nombre), ['ana', 'Carla']);
    });
  });

  group('ClienteLocal', () {
    test('nombreCompleto une nombre y apellido', () {
      expect(const ClienteLocal(id: 1, servidorId: 2, nombre: 'Ana', apellido: 'Pérez').nombreCompleto, 'Ana Pérez');
    });

    test('sin apellido (null, vacío o espacios) es solo el nombre', () {
      expect(const ClienteLocal(id: 1, servidorId: 2, nombre: 'Ana').nombreCompleto, 'Ana');
      expect(const ClienteLocal(id: 1, servidorId: 2, nombre: 'Ana', apellido: '').nombreCompleto, 'Ana');
      expect(const ClienteLocal(id: 1, servidorId: 2, nombre: 'Ana', apellido: '  ').nombreCompleto, 'Ana');
    });

    test('igualdad por valor', () {
      const a = ClienteLocal(id: 1, servidorId: 2, nombre: 'Ana', apellido: 'P', ciNit: '1');
      const b = ClienteLocal(id: 1, servidorId: 2, nombre: 'Ana', apellido: 'P', ciNit: '1');
      const c = ClienteLocal(id: 1, servidorId: 3, nombre: 'Ana', apellido: 'P', ciNit: '1');
      expect(a, b);
      expect(a.hashCode, b.hashCode);
      expect(a == c, isFalse);
    });
  });

  test('ClientesLocalSqlite cumple la interfaz ClientesLocalRepository', () {
    final ClientesLocalRepository r = repo;
    expect(r, isA<ClientesLocalRepository>());
  });
}
