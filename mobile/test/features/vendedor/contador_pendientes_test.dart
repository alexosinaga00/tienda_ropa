import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/sesion/contador_pendientes.dart';
import 'package:mobile/features/vendedor/data/contador_pendientes_sqlite.dart';
import 'package:mobile/features/vendedor/state/catalogo_local_providers.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';
import 'apoyo_operaciones.dart';

void main() {
  late Database db;
  late ContadorPendientesSqlite contador;

  setUp(() async {
    db = await abrirBaseDePrueba();
    addTearDown(db.close);
    await sembrarDosEmpresas(db);
    contador = ContadorPendientesSqlite(() async => db);
  });

  group('pendientesDe', () {
    test('sin operaciones es 0', () async {
      expect(await contador.pendientesDe(empresaId: 1, usuarioId: 7), 0);
    });

    test('cuenta solo registrada, enviada y en_conflicto', () async {
      var n = 0;
      for (final estado in ['registrada', 'enviada', 'confirmada', 'rechazada', 'en_conflicto']) {
        await sembrarOperacion(db, id: 'op-${n++}', estado: estado);
      }

      expect(await contador.pendientesDe(empresaId: 1, usuarioId: 7), 3);
    });

    test('las confirmadas y rechazadas no cuentan', () async {
      await sembrarOperacion(db, id: 'a', estado: 'confirmada');
      await sembrarOperacion(db, id: 'b', estado: 'rechazada');

      expect(await contador.pendientesDe(empresaId: 1, usuarioId: 7), 0);
    });

    test('cuenta ventas y reservas', () async {
      final cliente = await sembrarCliente(db);
      await sembrarOperacion(db, id: 'v', estado: 'registrada');
      await sembrarOperacion(db, id: 'r', tipo: 'reserva', estado: 'registrada', clienteId: cliente);

      expect(await contador.pendientesDe(empresaId: 1, usuarioId: 7), 2);
    });

    test('solo cuenta las de ESE usuario', () async {
      await sembrarOperacion(db, id: 'mia', estado: 'registrada');
      await sembrarOperacion(db, id: 'ajena', usuarioId: 8, estado: 'registrada');

      expect(await contador.pendientesDe(empresaId: 1, usuarioId: 7), 1);
      expect(await contador.pendientesDe(empresaId: 1, usuarioId: 8), 1);
      expect(await contador.pendientesDe(empresaId: 1, usuarioId: 99), 0);
    });

    test('solo cuenta las de ESA empresa', () async {
      await sembrarOperacion(db, id: 'e1', estado: 'registrada');
      await sembrarOperacion(db, id: 'e2', empresaId: 2, sucursalId: 11, varianteId: 200, estado: 'enviada');

      expect(await contador.pendientesDe(empresaId: 1, usuarioId: 7), 1);
      expect(await contador.pendientesDe(empresaId: 2, usuarioId: 7), 1);
      expect(await contador.pendientesDe(empresaId: 3, usuarioId: 7), 0);
    });

    test('sin empresa o sin usuario responde 0', () async {
      await sembrarOperacion(db, id: 'mia', estado: 'registrada');

      expect(await contador.pendientesDe(), 0);
      expect(await contador.pendientesDe(empresaId: 1), 0);
      expect(await contador.pendientesDe(usuarioId: 7), 0);
    });
  });

  group('pendientesDeOtros', () {
    test('cuenta las de otros usuarios de la misma empresa y no las propias', () async {
      await sembrarOperacion(db, id: 'mia', estado: 'registrada');
      await sembrarOperacion(db, id: 'o8', usuarioId: 8, estado: 'registrada');
      await sembrarOperacion(db, id: 'o9', usuarioId: 9, estado: 'en_conflicto');

      expect(await contador.pendientesDeOtros(empresaId: 1, usuarioId: 7), 2);
      expect(await contador.pendientesDeOtros(empresaId: 1, usuarioId: 8), 2);
    });

    test('solo cuenta los tres estados pendientes', () async {
      var n = 0;
      for (final estado in ['registrada', 'enviada', 'confirmada', 'rechazada', 'en_conflicto']) {
        await sembrarOperacion(db, id: 'op-${n++}', usuarioId: 8, estado: estado);
      }

      expect(await contador.pendientesDeOtros(empresaId: 1, usuarioId: 7), 3);
    });

    test('no cuenta las de otra empresa', () async {
      await sembrarOperacion(db, id: 'e2', empresaId: 2, sucursalId: 11, varianteId: 200, usuarioId: 8, estado: 'registrada');

      expect(await contador.pendientesDeOtros(empresaId: 1, usuarioId: 7), 0);
      expect(await contador.pendientesDeOtros(empresaId: 2, usuarioId: 7), 1);
    });

    test('sin operaciones de otros es 0', () async {
      await sembrarOperacion(db, id: 'mia', estado: 'registrada');

      expect(await contador.pendientesDeOtros(empresaId: 1, usuarioId: 7), 0);
    });
  });

  group('ante un error responde 0 y nunca lanza', () {
    test('si la base no abre', () async {
      final roto = ContadorPendientesSqlite(() async => throw StateError('no abre'));

      expect(await roto.pendientesDe(empresaId: 1, usuarioId: 7), 0);
      expect(await roto.pendientesDeOtros(empresaId: 1, usuarioId: 7), 0);
    });

    test('si no hay plugin (MissingPluginException al abrir)', () async {
      final sinPlugin = ContadorPendientesSqlite(() => throw UnsupportedError('sin plugin'));

      expect(await sinPlugin.pendientesDe(empresaId: 1, usuarioId: 7), 0);
    });

    test('si la base ya está cerrada', () async {
      await sembrarOperacion(db, id: 'mia', estado: 'registrada');
      final cerrada = await abrirBaseDePrueba();
      await cerrada.close();
      final c = ContadorPendientesSqlite(() async => cerrada);

      expect(await c.pendientesDe(empresaId: 1, usuarioId: 7), 0);
      expect(await c.pendientesDeOtros(empresaId: 1, usuarioId: 7), 0);
    });

    test('si falta la tabla (base de otra versión)', () async {
      final vacia = await databaseFactoryFfi.openDatabase(inMemoryDatabasePath);
      addTearDown(vacia.close);
      final c = ContadorPendientesSqlite(() async => vacia);

      expect(await c.pendientesDe(empresaId: 1, usuarioId: 7), 0);
    });

    test('un fallo pasajero no queda pegado: la siguiente consulta vuelve a intentar', () async {
      await sembrarOperacion(db, id: 'mia', estado: 'registrada');
      var intentos = 0;
      final c = ContadorPendientesSqlite(() async {
        if (intentos++ == 0) throw StateError('fallo pasajero');
        return db;
      });

      expect(await c.pendientesDe(empresaId: 1, usuarioId: 7), 0);
      expect(await c.pendientesDe(empresaId: 1, usuarioId: 7), 1);
    });
  });

  group('contadorPendientesProvider', () {
    test('es el real: cuenta en la base local de la sesión', () async {
      await sembrarOperacion(db, id: 'a', estado: 'registrada');
      await sembrarOperacion(db, id: 'b', estado: 'enviada');
      final contenedor = contenedorLocal(db);

      final real = contenedor.read(contadorPendientesProvider);

      expect(real, isA<ContadorPendientesSqlite>());
      expect(await real.pendientesDe(empresaId: 1, usuarioId: 7), 2);
    });

    test('sin base disponible (por ejemplo, sin el plugin) responde 0 sin lanzar', () async {
      final contenedor = ProviderContainer(
        overrides: [baseLocalProvider.overrideWith((ref) async => throw StateError('no abre'))],
      );
      addTearDown(contenedor.dispose);

      expect(await contenedor.read(contadorPendientesProvider).pendientesDe(empresaId: 1, usuarioId: 7), 0);
    });

    test('se puede reemplazar con overrideWithValue', () async {
      final contenedor = ProviderContainer(
        overrides: [contadorPendientesProvider.overrideWithValue(const ContadorPendientesVacio())],
      );
      addTearDown(contenedor.dispose);

      expect(await contenedor.read(contadorPendientesProvider).pendientesDe(empresaId: 1, usuarioId: 7), 0);
    });

    test('ContadorPendientesVacio siempre responde 0', () async {
      expect(await const ContadorPendientesVacio().pendientesDe(empresaId: 1, usuarioId: 7), 0);
    });
  });
}
