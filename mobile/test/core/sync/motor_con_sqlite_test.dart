import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/sync/cola_operaciones.dart';
import 'package:mobile/core/sync/cola_operaciones_sqlite.dart';
import 'package:mobile/core/sync/contrato_sync.dart';
import 'package:mobile/core/sync/dispositivo_id.dart';
import 'package:mobile/core/sync/generador_uuid.dart';
import 'package:mobile/core/sync/lineas_operacion.dart';
import 'package:mobile/core/sync/motor_sincronizacion.dart';
import 'package:mobile/core/sync/operacion_pendiente.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';
import '../../helpers/conectividad_falsa.dart';
import '../../helpers/siembra_operaciones.dart';
import '../../helpers/sincronizacion_api_falsa.dart';

String id(int n) => '${n.toString().padLeft(8, '0')}-0000-4000-8000-000000000000';

DateTime hora(int minutos) => DateTime.utc(2026, 10, 31, 9).add(Duration(minutes: minutos));

const _empresa = 1;
const _usuario = 10;

/// Una confirmación con el recurso creado (id 7) para comprobar lo que se guarda.
ResultadoOperacionSync _confirmada(String id, {String codigo = 'V-1', String tipo = 'venta', int? total, int? cambio}) =>
    ResultadoOperacionSync(
      operacionId: id,
      estado: EstadoResultadoSync.confirmada,
      procesadaEn: DateTime.utc(2026, 10, 31, 12),
      recurso: RecursoSync(tipo: tipo, id: 7, codigo: codigo, totalCentavos: total),
      cambioCentavos: cambio,
    );

class _Gen implements GeneradorUuid {
  @override
  String nuevo() => 'aaaaaaaa-0000-4000-8000-bbbbbbbbbbbb';
}

NuevaVenta _venta(int n, {int? cliente, int cantidad = 2, int variante = 100, int precio = 7500}) => NuevaVenta(
  operacionId: id(n),
  empresaId: _empresa,
  sucursalId: 1,
  usuarioId: _usuario,
  fechaOperacion: hora(n),
  lineas: [LineaVenta(varianteId: variante, cantidad: cantidad, precioUnitarioCentavos: precio)],
  clienteMinimoId: cliente,
  efectivoConfirmado: true,
);

NuevaReserva _reserva(int n, {int cliente = 1}) => NuevaReserva(
  operacionId: id(n),
  empresaId: _empresa,
  sucursalId: 1,
  usuarioId: _usuario,
  fechaOperacion: hora(n),
  clienteMinimoId: cliente,
  fechaVisita: DateTime(2026, 11, 2),
  horaDesde: '10:00',
  horaHasta: '11:00',
  lineas: const [LineaReserva(varianteId: 101, cantidad: 1)],
);

/// Todo el sistema real salvo la red: base SQLite, cola SQLite y motor.
class _Mundo {
  _Mundo._(this.db, this.reloj, this.cola, this.api, this.conectividad, {required this.espera});

  static Future<_Mundo> crear({Database? db, int tamanioLote = 20}) async {
    final base = db ?? await abrirBaseDePrueba();
    if (db == null) await sembrarMundoDeOperaciones(base);
    final reloj = RelojDePrueba(DateTime.utc(2026, 10, 31, 12));
    final cola = ColaOperacionesSqlite(base, reloj);
    final mundo = _Mundo._(base, reloj, cola, SincronizacionApiFalsa(), ConectividadFalsa(), espera: (n) => Duration(seconds: 10 * n));
    mundo.motor = mundo.nuevoMotor(tamanioLote: tamanioLote);
    return mundo;
  }

  final Database db;
  final RelojDePrueba reloj;
  final ColaOperacionesSqlite cola;
  final SincronizacionApiFalsa api;
  final ConectividadFalsa conectividad;
  final Duration Function(int) espera;
  late MotorSincronizacion motor;

  MotorSincronizacion nuevoMotor({int tamanioLote = 20}) => MotorSincronizacion(
    cola: cola,
    api: api,
    reloj: reloj,
    conectividad: conectividad,
    dispositivoId: () => obtenerDispositivoId(db, _Gen()),
    espera: espera,
    tamanioLote: tamanioLote,
  );

  Future<ResumenSync> sincronizar([Disparador d = Disparador.manual]) =>
      motor.sincronizar(empresaId: _empresa, usuarioId: _usuario, disparador: d);

  Future<OperacionPendiente> op(int n) async => (await cola.obtener(id(n)))!;
}

void main() {
  late List<String> logs;
  late _Mundo m;

  setUp(() async {
    logs = [];
    final previo = debugPrint;
    debugPrint = (String? mensaje, {int? wrapWidth}) {
      if (mensaje != null) logs.add(mensaje);
    };
    addTearDown(() => debugPrint = previo);
    m = await _Mundo.crear();
  });

  tearDown(() async {
    m.motor.dispose();
    await m.cola.dispose();
    await m.db.close();
  });

  group('registro -> sincronizar sobre SQLite real', () {
    test('una venta registrada se confirma y guarda su resultado con el detalle', () async {
      await m.cola.registrarVenta(_venta(1, cliente: 1));
      m.api.programar(respuestaDeLote([_confirmada(id(1), codigo: 'V-000123', total: 15000, cambio: 0)]));

      final r = await m.sincronizar();

      expect(r.confirmadas, 1);
      expect(r.pendientes, 0);
      final o = await m.op(1);
      expect(o.estado, EstadoOperacion.confirmada);
      expect(o.intentos, 1);
      expect(o.ultimoError, isNull);
      expect(o.resueltaEn, DateTime.utc(2026, 10, 31, 12));
      final resultados = await m.cola.resultados(id(1));
      expect(resultados.single.estadoResultado, 'confirmada');
      expect(resultados.single.entidadServidorId, 7);
      final detalle = jsonDecode(resultados.single.detalleJson!) as Map<String, dynamic>;
      expect((detalle['recurso'] as Map)['codigo'], 'V-000123');
      expect((detalle['recurso'] as Map)['total_centavos'], 15000);
    });

    test('lo que viaja es el payload guardado, con el cliente del servidor, el sucursal y la fecha', () async {
      await m.cola.registrarVenta(_venta(1, cliente: 1));
      final guardado = await m.op(1);

      await m.sincronizar();

      final enviado = m.api.lotes.single.operaciones.single;
      expect(enviado.operacionId, id(1));
      expect(enviado.sucursalId, 1);
      expect(enviado.fechaOperacion, hora(1));
      expect(enviado.payload, jsonDecode(guardado.payload));
      expect(enviado.payload['cliente_id'], 501);
      expect(enviado.payload['total'], '150.00');
    });

    test('una reserva viaja con el cliente del servidor y se confirma', () async {
      await m.cola.registrarReserva(_reserva(1));
      m.api.programar(respuestaDeLote([_confirmada(id(1), codigo: 'R-000009', tipo: 'reserva')]));

      final r = await m.sincronizar();

      expect(r.confirmadas, 1);
      final enviado = m.api.lotes.single.operaciones.single;
      expect(enviado.tipo, TipoOperacion.reserva);
      expect(enviado.payload['cliente_id'], 501);
      expect(enviado.payload['fecha_visita'], '2026-11-02');
      expect((await m.op(1)).estado, EstadoOperacion.confirmada);
    });

    test('venta y reserva salen por fecha_operacion (la más antigua primero)', () async {
      await m.cola.registrarVenta(_venta(3));
      await m.cola.registrarReserva(_reserva(1));
      await m.cola.registrarVenta(_venta(2, variante: 101, precio: 5000));

      await m.sincronizar();

      expect(m.api.idsEnviados, [id(1), id(2), id(3)]);
    });

    test('el identificador del dispositivo se guarda en meta y viaja en el lote', () async {
      await m.cola.registrarVenta(_venta(1));

      await m.sincronizar();

      expect(m.api.lotes.single.dispositivo, 'aaaaaaaa-0000-4000-8000-bbbbbbbbbbbb');
      final filas = await m.db.query('meta', where: 'clave = ?', whereArgs: [claveDispositivoId]);
      expect(filas.single['valor'], 'aaaaaaaa-0000-4000-8000-bbbbbbbbbbbb');
    });

    test('25 operaciones con lotes de 10 hacen 3 lotes y todas quedan confirmadas', () async {
      m.motor.dispose();
      m.motor = m.nuevoMotor(tamanioLote: 10);
      for (var i = 1; i <= 25; i++) {
        await m.cola.registrarVenta(_venta(i));
      }

      final r = await m.sincronizar();

      expect(m.api.idsPorLote.map((l) => l.length), [10, 10, 5]);
      expect(r.confirmadas, 25);
      final conteo = await m.cola.conteoPorEstado(empresaId: _empresa, usuarioId: _usuario);
      expect(conteo[EstadoOperacion.confirmada], 25);
      expect(conteo[EstadoOperacion.registrada], 0);
    });

    test('un rechazo del servidor y un conflicto con faltantes quedan guardados', () async {
      await m.cola.registrarVenta(_venta(1));
      await m.cola.registrarVenta(_venta(2));
      m.api.programar(respuestaDeLote([
        resultadoRechazada(id(1), motivo: 'variante_inactiva'),
        resultadoEnConflicto(id(2)),
      ]));

      final r = await m.sincronizar();

      expect((r.rechazadas, r.enConflicto), (1, 1));
      final rechazada = await m.op(1);
      expect(rechazada.estado, EstadoOperacion.rechazada);
      expect(rechazada.ultimoError, 'Texto del servidor');
      final conflicto = await m.op(2);
      expect(conflicto.estado, EstadoOperacion.enConflicto);
      expect(conflicto.resueltaEn, isNull);
      final resultado = (await m.cola.resultados(id(2))).single;
      expect(resultado.codigoMotivo, 'stock_insuficiente');
      final faltantes = (jsonDecode(resultado.detalleJson!) as Map)['faltantes'] as List;
      expect(faltantes.single, {'variante_id': 5, 'solicitado': 2, 'disponible': 0});
    });
  });

  group('cortes de red con la cola real', () {
    test('corte a mitad con respuesta incierta: sigue enviada y el reenvío no duplica nada', () async {
      await m.cola.registrarVenta(_venta(1));
      await m.cola.registrarVenta(_venta(2));
      final procesadas = <String>{};
      m.api.porDefecto = (lote) => respuestaDeLote([
        for (final o in lote.operaciones)
          resultadoConfirmada(o.operacionId, duplicada: !procesadas.add(o.operacionId)),
      ]);
      // El servidor SÍ procesó el lote, pero la respuesta no llegó.
      m.api.programar((lote) {
        procesadas.addAll(lote.operaciones.map((o) => o.operacionId));
        throw const ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: 'Sin conexión', posiblementeRecibido: true);
      });

      final primera = await m.sincronizar();
      expect(primera.fallidasPorRed, 2);
      final tras = await m.op(1);
      expect(tras.estado, EstadoOperacion.enviada);
      expect(tras.intentos, 1);
      expect(tras.proximoReintentoEn, DateTime.utc(2026, 10, 31, 12, 0, 10));
      expect(tras.ultimoError, isNotEmpty);

      m.reloj.avanzar(const Duration(seconds: 11));
      final segunda = await m.sincronizar(Disparador.conexionRecuperada);

      expect(segunda.confirmadas, 2);
      expect(procesadas, hasLength(2));
      expect((await m.op(1)).intentos, 2, reason: 'cada envío cuenta un intento, también el reenvío de una enviada');
      final filas = await m.db.rawQuery('SELECT COUNT(*) AS n FROM operacion_pendiente');
      expect(filas.single['n'], 2);
      final respuestas = await m.db.rawQuery("SELECT COUNT(*) AS n FROM resultado_sync WHERE estado_resultado = 'confirmada'");
      expect(respuestas.single['n'], 2);
    });

    test('corte antes de conectar: vuelve a registrada con su espera y se manda luego', () async {
      await m.cola.registrarVenta(_venta(1));
      m.api.programar(const ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: 'Sin conexión'));

      await m.sincronizar();

      final o = await m.op(1);
      expect(o.estado, EstadoOperacion.registrada);
      expect(o.intentos, 1);
      expect(o.proximoReintentoEn, DateTime.utc(2026, 10, 31, 12, 0, 10));

      // Aún en espera: el automático no la manda; el manual sí.
      final automatico = await m.sincronizar(Disparador.temporizador);
      expect(automatico.intentado, isFalse);
      expect(automatico.omitidasPorEspera, 1);
      final manual = await m.sincronizar();
      expect(manual.confirmadas, 1);
    });

    test('401: la cola se conserva intacta y sin gastar intentos', () async {
      await m.cola.registrarVenta(_venta(1));
      await m.cola.registrarVenta(_venta(2));
      m.api.programar(const ErrorApp(tipo: TipoErrorApp.noAutorizado, mensaje: 'Tu sesión venció.', estado: 401));

      final r = await m.sincronizar();

      expect(r.sesionVencida, isTrue);
      for (final n in [1, 2]) {
        final o = await m.op(n);
        expect(o.estado, EstadoOperacion.registrada);
        expect(o.intentos, 0);
        expect(o.proximoReintentoEn, isNull);
      }
      m.motor.reiniciarSesion();
      expect((await m.sincronizar(Disparador.primerPlano)).confirmadas, 2);
    });

    test('plan sin la función: bloqueo, intento devuelto y la cola intacta', () async {
      await m.cola.registrarVenta(_venta(1));
      m.api.programar(const ErrorApp(tipo: TipoErrorApp.planNoIncluyeFuncionalidad, mensaje: 'Tu plan no incluye esta función.', estado: 403));

      final r = await m.sincronizar();

      expect(r.bloqueo?.tipo, TipoBloqueo.planNoIncluye);
      final o = await m.op(1);
      expect(o.estado, EstadoOperacion.registrada);
      expect(o.intentos, 0);
    });

    test('422 del lote: la mala queda rechazada con código rechazo_local y las demás se confirman', () async {
      for (var i = 1; i <= 3; i++) {
        await m.cola.registrarVenta(_venta(i));
      }
      const validacion = ErrorApp(tipo: TipoErrorApp.validacion, mensaje: 'Revisa los datos.', estado: 422);
      m.api.porDefecto = (lote) {
        if (lote.operaciones.any((o) => o.operacionId == id(2))) throw validacion;
        return confirmarTodas(lote);
      };
      m.api.programar(validacion);

      final r = await m.sincronizar();

      expect((r.confirmadas, r.rechazadas), (2, 1));
      final mala = await m.op(2);
      expect(mala.estado, EstadoOperacion.rechazada);
      expect(mala.ultimoError, 'El servidor no aceptó los datos (código 422).');
      expect(mala.resueltaEn, isNotNull);
      final resultado = (await m.cola.resultados(id(2))).single;
      expect(resultado.codigoMotivo, codigoRechazoLocal);
      expect((await m.op(1)).estado, EstadoOperacion.confirmada);
      expect((await m.op(3)).estado, EstadoOperacion.confirmada);
    });

    test('una operación que el servidor no devuelve queda enviada y se reenvía después', () async {
      await m.cola.registrarVenta(_venta(1));
      await m.cola.registrarVenta(_venta(2));
      m.api.programar(respuestaDeLote([resultadoConfirmada(id(1))]));

      final r = await m.sincronizar();

      expect(r.fallidasPorRed, 1);
      final o = await m.op(2);
      expect(o.estado, EstadoOperacion.enviada);
      expect(o.ultimoError, 'Sin respuesta del servidor');

      final siguiente = await m.sincronizar();
      expect(siguiente.confirmadas, 1);
      expect(m.api.idsPorLote.last, [id(2)]);
    });

    test('error_temporal queda enviada con el aviso y no deja fila de resultado', () async {
      await m.cola.registrarVenta(_venta(1));
      m.api.programar(respuestaDeLote([resultadoTemporal(id(1))]));

      await m.sincronizar();

      final o = await m.op(1);
      expect(o.estado, EstadoOperacion.enviada);
      expect(o.proximoReintentoEn, isNotNull);
      expect(await m.cola.resultados(id(1)), isEmpty);
    });
  });

  group('revisión de conflictos con la cola real', () {
    test('un encargado la confirmó desde la web: se aplica con la hora del servidor', () async {
      await m.cola.registrarVenta(_venta(1));
      m.api.programar(respuestaDeLote([resultadoEnConflicto(id(1))]));
      await m.sincronizar();
      expect((await m.op(1)).estado, EstadoOperacion.enConflicto);

      m.api.programarConsulta(id(1), resultadoConfirmada(id(1), procesadaEn: DateTime.utc(2026, 10, 31, 15, 30)));
      final r = await m.sincronizar();

      expect(r.confirmadas, 1);
      final o = await m.op(1);
      expect(o.estado, EstadoOperacion.confirmada);
      expect(o.resueltaEn, DateTime.utc(2026, 10, 31, 15, 30));
      expect(o.ultimoError, isNull);
      final estados = (await m.cola.resultados(id(1))).map((x) => x.estadoResultado);
      expect(estados, ['en_conflicto', 'confirmada']);
    });

    test('la rechazó: queda rechazada; sigue en conflicto: no cambia nada', () async {
      await m.cola.registrarVenta(_venta(1));
      await m.cola.registrarVenta(_venta(2));
      m.api.programar(respuestaDeLote([resultadoEnConflicto(id(1)), resultadoEnConflicto(id(2))]));
      await m.sincronizar();
      m.api.programarConsulta(id(1), resultadoRechazada(id(1), motivo: 'stock_insuficiente'));
      m.api.programarConsulta(id(2), resultadoEnConflicto(id(2)));

      final r = await m.sincronizar();

      expect((r.rechazadas, r.enConflicto), (1, 0));
      expect((await m.op(1)).estado, EstadoOperacion.rechazada);
      expect((await m.op(2)).estado, EstadoOperacion.enConflicto);
      expect(await m.cola.resultados(id(2)), hasLength(1));
    });

    test('una confirmada desde la web no vuelve a consultarse', () async {
      await m.cola.registrarVenta(_venta(1));
      m.api.programar(respuestaDeLote([resultadoEnConflicto(id(1))]));
      await m.sincronizar();
      m.api.programarConsulta(id(1), resultadoConfirmada(id(1)));
      await m.sincronizar();
      m.api.consultas.clear();

      await m.sincronizar();

      expect(m.api.consultas, isEmpty);
    });
  });

  group('observabilidad con datos reales', () {
    test('los registros no llevan nombres, documentos, teléfonos ni montos', () async {
      await sembrarClienteMinimo(m.db, servidorId: 777, nombre: 'Marcela', apellido: 'Quispe', ciNit: '9988776');
      await m.cola.registrarVenta(_venta(1, cliente: 1, precio: 12345));
      await m.cola.registrarVenta(_venta(2, cliente: 4, precio: 12345));
      m.api.programar(respuestaDeLote([resultadoConfirmada(id(1)), resultadoEnConflicto(id(2))]));

      await m.sincronizar();

      final todo = logs.join('\n');
      for (final prohibido in ['Ana', 'Pérez', '1234567', 'Marcela', 'Quispe', '9988776', '123.45', '12345', id(1), id(2)]) {
        expect(todo.contains(prohibido), isFalse, reason: 'el log contiene "$prohibido"');
      }
      expect(logs.where((l) => l.startsWith('sync op=00000001')), hasLength(1));
      expect(logs.where((l) => l.startsWith('sync fin')), hasLength(1));
    });
  });

  group('reinicio de la app (base en archivo)', () {
    late Directory carpeta;

    setUp(() async {
      carpeta = await Directory.systemTemp.createTemp('motor_sqlite_test');
    });

    tearDown(() async {
      try {
        await carpeta.delete(recursive: true);
      } catch (_) {
        // En Windows el archivo puede tardar en soltarse: no importa para la prueba.
      }
    });

    test('tras un corte con respuesta incierta y un reinicio, la operación se reenvía y se confirma una sola vez', () async {
      final ruta = p.join(carpeta.path, 'local.db');
      final base1 = await abrirBaseDePrueba(ruta: ruta);
      await sembrarMundoDeOperaciones(base1);
      final mundo1 = await _Mundo.crear(db: base1);
      await mundo1.cola.registrarVenta(_venta(1, cliente: 1));
      await mundo1.cola.registrarReserva(_reserva(2));
      mundo1.api.programar(const ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: 'Sin conexión', posiblementeRecibido: true));
      await mundo1.sincronizar();
      final dispositivo1 = mundo1.api.lotes.single.dispositivo;
      mundo1.motor.dispose();
      await mundo1.cola.dispose();
      await base1.close();

      // La app se reinicia: base, cola y motor NUEVOS sobre el mismo archivo.
      final base2 = await abrirBaseDePrueba(ruta: ruta);
      addTearDown(base2.close);
      final mundo2 = await _Mundo.crear(db: base2);
      mundo2.reloj.actual = DateTime.utc(2026, 10, 31, 13);
      expect((await mundo2.op(1)).estado, EstadoOperacion.enviada);
      expect((await mundo2.op(2)).estado, EstadoOperacion.enviada);

      final r = await mundo2.sincronizar(Disparador.primerPlano);

      expect(r.confirmadas, 2);
      expect(mundo2.api.idsEnviados, [id(1), id(2)]);
      expect(mundo2.api.lotes.single.dispositivo, dispositivo1, reason: 'el dispositivo sobrevive al reinicio');
      expect((await mundo2.op(1)).intentos, 2);
      final filas = await base2.rawQuery('SELECT COUNT(*) AS n FROM operacion_pendiente');
      expect(filas.single['n'], 2);
    });

    test('una operación registrada sin conexión sobrevive al reinicio y se envía al volver la red', () async {
      final ruta = p.join(carpeta.path, 'local.db');
      final base1 = await abrirBaseDePrueba(ruta: ruta);
      await sembrarMundoDeOperaciones(base1);
      final mundo1 = await _Mundo.crear(db: base1);
      mundo1.conectividad.emitir(false);
      await mundo1.cola.registrarVenta(_venta(1));
      final sinRed = await mundo1.sincronizar(Disparador.registro);
      expect(sinRed.intentado, isFalse);
      mundo1.motor.dispose();
      await mundo1.cola.dispose();
      await base1.close();

      final base2 = await abrirBaseDePrueba(ruta: ruta);
      addTearDown(base2.close);
      final mundo2 = await _Mundo.crear(db: base2);
      final r = await mundo2.sincronizar(Disparador.conexionRecuperada);

      expect(r.confirmadas, 1);
      expect((await mundo2.op(1)).estado, EstadoOperacion.confirmada);
    });
  });
}
