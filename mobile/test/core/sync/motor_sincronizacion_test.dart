import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/sync/contrato_sync.dart';
import 'package:mobile/core/sync/motor_sincronizacion.dart';
import 'package:mobile/core/sync/operacion_pendiente.dart';
import 'package:mobile/core/utils/reloj.dart';
import 'package:mobile/features/vendedor/models/paquete_sincronizacion.dart' show mensajeActualizarApp;

import '../../helpers/cola_falsa.dart';
import '../../helpers/conectividad_falsa.dart';
import '../../helpers/sincronizacion_api_falsa.dart';

class _Reloj implements Reloj {
  DateTime actual = DateTime.utc(2026, 10, 31, 12);

  @override
  DateTime ahora() => actual;

  void avanzar(Duration d) => actual = actual.add(d);
}

/// Ids con 8 caracteres distintos al inicio (el código corto que sale en los logs).
String id(int n) => '${n.toString().padLeft(8, '0')}-0000-4000-8000-000000000000';

DateTime hora(int minutos) => DateTime.utc(2026, 10, 31, 9).add(Duration(minutes: minutos));

const _empresa = 1;
const _usuario = 10;

ErrorApp _sinConexion({bool recibido = false}) =>
    ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: 'Sin conexión. Revisa tu internet e intenta de nuevo.', posiblementeRecibido: recibido);
const _servidor503 = ErrorApp(tipo: TipoErrorApp.servidor, mensaje: 'El servidor no pudo responder.', estado: 503);
const _validacion422 = ErrorApp(tipo: TipoErrorApp.validacion, mensaje: 'Revisa los datos e intenta de nuevo.', estado: 422);
const _http400 = ErrorApp(tipo: TipoErrorApp.desconocido, mensaje: 'Solicitud no válida.', estado: 400);

class _Entorno {
  _Entorno({
    this.tamanioLote = 20,
    this.revision = const Duration(minutes: 15),
    bool enLinea = true,
    Duration Function(int)? espera,
    Future<String> Function()? dispositivo,
  }) : conectividad = ConectividadFalsa(enLinea: enLinea),
       espera = espera ?? ((n) => Duration(seconds: 10 * n)),
       dispositivo = dispositivo ?? (() async => 'dispositivo-1') {
    motor = crearMotor();
  }

  final ColaFalsa cola = ColaFalsa();
  final SincronizacionApiFalsa api = SincronizacionApiFalsa();
  final _Reloj reloj = _Reloj();
  final ConectividadFalsa conectividad;
  final Duration Function(int) espera;
  final int tamanioLote;
  final Duration revision;
  final Future<String> Function() dispositivo;
  late final MotorSincronizacion motor;

  MotorSincronizacion crearMotor() => MotorSincronizacion(
    cola: cola,
    api: api,
    reloj: reloj,
    conectividad: conectividad,
    dispositivoId: dispositivo,
    espera: espera,
    tamanioLote: tamanioLote,
    revisionConflictos: revision,
  );

  Future<ResumenSync> sincronizar([Disparador d = Disparador.manual]) =>
      motor.sincronizar(empresaId: _empresa, usuarioId: _usuario, disparador: d);

  /// Siembra [n] ventas registradas con ids 1..n y fechas crecientes.
  void sembrar(int n, {int desde = 1, EstadoOperacion estado = EstadoOperacion.registrada, int intentos = 0}) {
    for (var i = 0; i < n; i++) {
      cola.sembrar(operacionDePrueba(id(desde + i), estado: estado, intentos: intentos, fechaOperacion: hora(desde + i)));
    }
  }

  OperacionPendiente op(int n) => cola.fila(id(n));
}

List<String> _capturarLogs() {
  final logs = <String>[];
  final previo = debugPrint;
  debugPrint = (String? mensaje, {int? wrapWidth}) {
    if (mensaje != null) logs.add(mensaje);
  };
  addTearDown(() => debugPrint = previo);
  return logs;
}

void main() {
  late List<String> logs;

  setUp(() {
    logs = _capturarLogs();
  });

  group('flujo feliz', () {
    test('una venta y una reserva se confirman y quedan con su resultado', () async {
      final e = _Entorno();
      e.cola.sembrar(operacionDePrueba(id(1), fechaOperacion: hora(1)));
      e.cola.sembrar(operacionDePrueba(id(2), tipo: TipoOperacion.reserva, fechaOperacion: hora(2)));

      final r = await e.sincronizar();

      expect(r.intentado, isTrue);
      expect(r.enviadas, 2);
      expect(r.confirmadas, 2);
      expect(r.rechazadas, 0);
      expect(r.enConflicto, 0);
      expect(r.pendientes, 0);
      expect(r.fallidasPorRed, 0);
      expect(r.huboCambios, isTrue);
      expect(e.op(1).estado, EstadoOperacion.confirmada);
      expect(e.op(2).estado, EstadoOperacion.confirmada);
      expect(e.op(1).intentos, 1);
      expect((await e.cola.resultados(id(1))).single.estadoResultado, 'confirmada');
      expect(e.api.peticiones, 1);
    });

    test('el lote lleva la versión del contrato, el dispositivo y cada operación con su payload', () async {
      final e = _Entorno();
      e.sembrar(1);

      await e.sincronizar();

      final json = e.api.lotes.single.toJson();
      expect(json['version_contrato'], '1.0');
      expect(json['dispositivo'], 'dispositivo-1');
      final operaciones = json['operaciones'] as List;
      expect(operaciones, hasLength(1));
      final o = operaciones.single as Map;
      expect(o['operacion_id'], id(1));
      expect(o['tipo'], 'venta_contado');
      expect(o['sucursal_id'], 1);
      expect(o['fecha_operacion'], '2026-10-31T09:01:00Z');
      expect(o['payload'], jsonDecode(e.op(1).payload));
    });

    test('registra la hora del intento y el último resumen en el estado', () async {
      final e = _Entorno();
      e.sembrar(2);

      final r = await e.sincronizar();

      expect(e.motor.estado.ultimaSincronizacion, e.reloj.actual);
      expect(identical(e.motor.estado.ultimoResumen, r), isTrue);
      expect(e.motor.estado.enCurso, isFalse);
    });

    test('las operaciones salen por fecha_operacion aunque la cola las tenga desordenadas', () async {
      final e = _Entorno();
      e.cola.sembrar(operacionDePrueba(id(3), fechaOperacion: hora(30)));
      e.cola.sembrar(operacionDePrueba(id(1), fechaOperacion: hora(10)));
      e.cola.sembrar(operacionDePrueba(id(2), fechaOperacion: hora(20)));

      await e.sincronizar();

      expect(e.api.idsEnviados, [id(1), id(2), id(3)]);
    });

    test('45 operaciones con lotes de 20 hacen 3 lotes (20, 20 y 5) en orden', () async {
      final e = _Entorno();
      e.sembrar(45);

      final r = await e.sincronizar();

      expect(e.api.idsPorLote.map((l) => l.length), [20, 20, 5]);
      expect(e.api.idsEnviados, [for (var i = 1; i <= 45; i++) id(i)]);
      expect(r.enviadas, 45);
      expect(r.confirmadas, 45);
      expect(e.cola.todas.every((o) => o.estado == EstadoOperacion.confirmada), isTrue);
    });

    test('el tamaño de lote por defecto es el del contrato (20)', () async {
      final cola = ColaFalsa([for (var i = 1; i <= 21; i++) operacionDePrueba(id(i), fechaOperacion: hora(i))]);
      final api = SincronizacionApiFalsa();
      final motor = MotorSincronizacion(
        cola: cola,
        api: api,
        reloj: _Reloj(),
        conectividad: ConectividadFalsa(),
        dispositivoId: () async => 'd',
      );

      await motor.sincronizar(empresaId: _empresa, usuarioId: _usuario);

      expect(api.idsPorLote.map((l) => l.length), [tamanioLoteSync, 1]);
    });

    test('marca las operaciones como enviadas ANTES de mandar el lote', () async {
      final e = _Entorno();
      e.sembrar(2);
      final estadosAlRecibir = <EstadoOperacion>[];
      e.api.alRecibir = (lote) {
        for (final o in lote.operaciones) {
          estadosAlRecibir.add(e.cola.fila(o.operacionId).estado);
        }
      };

      await e.sincronizar();

      expect(estadosAlRecibir, [EstadoOperacion.enviada, EstadoOperacion.enviada]);
    });

    test('sin candidatas no intenta nada', () async {
      final e = _Entorno();

      final r = await e.sincronizar();

      expect(r.intentado, isFalse);
      expect(r.enviadas, 0);
      expect(e.api.peticiones, 0);
      expect(e.motor.estado.ultimaSincronizacion, isNull);
      expect(r.huboCambios, isFalse);
    });

    test('solo envía las operaciones del usuario y la empresa pedidos', () async {
      final e = _Entorno();
      e.sembrar(1);
      e.cola.sembrar(operacionDePrueba(id(8), usuarioId: 99, fechaOperacion: hora(8)));
      e.cola.sembrar(operacionDePrueba(id(9), empresaId: 2, fechaOperacion: hora(9)));

      await e.sincronizar();

      expect(e.api.idsEnviados, [id(1)]);
      expect(e.op(8).estado, EstadoOperacion.registrada);
      expect(e.op(9).estado, EstadoOperacion.registrada);
    });

    test('las operaciones finales no se vuelven a enviar', () async {
      final e = _Entorno();
      e.sembrar(1);
      e.sembrar(1, desde: 2, estado: EstadoOperacion.confirmada);
      e.sembrar(1, desde: 3, estado: EstadoOperacion.rechazada);
      e.sembrar(1, desde: 4, estado: EstadoOperacion.enConflicto);

      await e.sincronizar();

      expect(e.api.idsEnviados, [id(1)]);
    });

    test('un rechazo y un conflicto del servidor se aplican y se cuentan', () async {
      final e = _Entorno();
      e.sembrar(3);
      e.api.programar(respuestaDeLote([
        resultadoConfirmada(id(1)),
        resultadoRechazada(id(2), motivo: 'variante_inactiva'),
        resultadoEnConflicto(id(3)),
      ]));

      final r = await e.sincronizar();

      expect((r.confirmadas, r.rechazadas, r.enConflicto), (1, 1, 1));
      expect(e.op(2).estado, EstadoOperacion.rechazada);
      expect(e.op(3).estado, EstadoOperacion.enConflicto);
      expect((await e.cola.resultados(id(2))).single.codigoMotivo, 'variante_inactiva');
      expect((await e.cola.resultados(id(3))).single.estadoResultado, 'en_conflicto');
      // El conflicto sigue sin resolverse, pero ya no es 'pendiente de enviar'.
      expect(r.pendientes, 0);
    });

    test('el dispositivo se lee una sola vez por corrida', () async {
      var lecturas = 0;
      final e = _Entorno(dispositivo: () async {
        lecturas++;
        return 'disp';
      });
      e.sembrar(45);

      await e.sincronizar();

      expect(lecturas, 1);
      expect(e.api.lotes.every((l) => l.dispositivo == 'disp'), isTrue);
    });

    test('si no se puede leer el dispositivo, el lote va sin él', () async {
      final e = _Entorno(dispositivo: () async => throw StateError('sin base'));
      e.sembrar(1);

      final r = await e.sincronizar();

      expect(r.confirmadas, 1);
      expect(e.api.lotes.single.dispositivo, isNull);
      expect(e.api.lotes.single.toJson().containsKey('dispositivo'), isFalse);
    });

    test('un resultado de una operación que no se envió se ignora', () async {
      final e = _Entorno();
      e.sembrar(1);
      e.api.programar(respuestaDeLote([resultadoConfirmada(id(1)), resultadoConfirmada(id(77))]));

      final r = await e.sincronizar();

      expect(r.confirmadas, 1);
      expect(e.cola.todas.map((o) => o.operacionId), [id(1)]);
    });
  });

  group('candado (una sola sincronización a la vez)', () {
    test('dos sincronizar() simultáneos devuelven el MISMO Future y hacen una sola petición', () async {
      final e = _Entorno();
      e.sembrar(2);
      final compuerta = e.api.retener();

      final f1 = e.sincronizar();
      final f2 = e.sincronizar(Disparador.registro);
      final f3 = e.sincronizar(Disparador.temporizador);
      await pumpEventQueue();

      expect(identical(f1, f2), isTrue);
      expect(identical(f1, f3), isTrue);
      expect(e.motor.estado.enCurso, isTrue);

      compuerta.complete();
      final r = await f1;

      expect(e.api.peticiones, 1);
      expect(r.confirmadas, 2);
      expect(e.motor.estado.enCurso, isFalse);
    });

    test('terminada la corrida, un nuevo disparo sí hace otra petición', () async {
      final e = _Entorno();
      e.sembrar(1);
      final primera = e.sincronizar();
      await primera;
      e.sembrar(1, desde: 2);

      final segunda = e.sincronizar();
      await segunda;

      expect(identical(primera, segunda), isFalse);
      expect(e.api.peticiones, 2);
    });

    test('si la corrida falla por un error de la cola, el candado se libera', () async {
      final e = _Entorno();
      e.sembrar(1);
      e.cola.fallarProximaEscritura = StateError('disco lleno');

      await expectLater(e.sincronizar(), throwsStateError);
      expect(e.motor.estado.enCurso, isFalse);

      final r = await e.sincronizar();
      expect(r.confirmadas, 1);
    });

    test('un disparo automático durante una corrida manual no crea otra petición', () async {
      final e = _Entorno();
      e.sembrar(1);
      final compuerta = e.api.retener();

      final manual = e.sincronizar();
      await pumpEventQueue();
      final automatico = e.sincronizar(Disparador.conexionRecuperada);
      compuerta.complete();
      await Future.wait([manual, automatico]);

      expect(e.api.peticiones, 1);
    });
  });

  group('estado y flujo de cambios', () {
    test('emite enCurso=true al empezar y enCurso=false (con resumen) al terminar', () async {
      final e = _Entorno();
      e.sembrar(1);
      final emitidos = <EstadoSync>[];
      final sub = e.motor.cambiosDeEstado.listen(emitidos.add);

      await e.sincronizar();
      await pumpEventQueue();

      expect(emitidos.first.enCurso, isTrue);
      expect(emitidos.last.enCurso, isFalse);
      expect(emitidos.last.ultimoResumen?.confirmadas, 1);
      await sub.cancel();
    });

    test('es un stream broadcast: varios oyentes reciben lo mismo', () async {
      final e = _Entorno();
      final a = <EstadoSync>[];
      final b = <EstadoSync>[];
      final s1 = e.motor.cambiosDeEstado.listen(a.add);
      final s2 = e.motor.cambiosDeEstado.listen(b.add);

      await e.sincronizar();
      await pumpEventQueue();

      expect(a, isNotEmpty);
      expect(a.length, b.length);
      await s1.cancel();
      await s2.cancel();
    });

    test('dispose cierra el flujo y seguir sincronizando no falla', () async {
      final e = _Entorno();
      e.sembrar(1);
      var cerrado = false;
      e.motor.cambiosDeEstado.listen((_) {}, onDone: () => cerrado = true);

      e.motor.dispose();
      e.motor.dispose();
      await pumpEventQueue();
      final r = await e.sincronizar();

      expect(cerrado, isTrue);
      expect(r.confirmadas, 1);
    });
  });

  group('disparadores, conexión, bloqueo y sesión', () {
    for (final d in [Disparador.conexionRecuperada, Disparador.primerPlano, Disparador.registro, Disparador.temporizador]) {
      test('el disparador automático ${d.name} sincroniza con conexión', () async {
        final e = _Entorno();
        e.sembrar(1);

        final r = await e.sincronizar(d);

        expect(r.intentado, isTrue);
        expect(r.confirmadas, 1);
      });
    }

    test('sin conexión un disparo automático no intenta ni toca la cola', () async {
      final e = _Entorno(enLinea: false);
      e.sembrar(2);

      final r = await e.sincronizar(Disparador.temporizador);

      expect(r.intentado, isFalse);
      expect(r.pendientes, 2);
      expect(e.api.peticiones, 0);
      expect(e.cola.de('marcarEnviadas'), isEmpty);
      expect(e.op(1).intentos, 0);
    });

    test('sin conexión un disparo manual SÍ intenta', () async {
      final e = _Entorno(enLinea: false);
      e.sembrar(2);

      final r = await e.sincronizar();

      expect(r.intentado, isTrue);
      expect(e.api.peticiones, 1);
      expect(r.confirmadas, 2);
    });

    test('con bloqueo los disparos automáticos no intentan', () async {
      final e = _Entorno();
      e.sembrar(2);
      e.api.programar(const ErrorApp(tipo: TipoErrorApp.suscripcionNoActiva, mensaje: 'La suscripción no está activa', estado: 403));
      await e.sincronizar(Disparador.registro);
      expect(e.motor.estado.bloqueo, isNotNull);

      final r = await e.sincronizar(Disparador.temporizador);

      expect(r.intentado, isFalse);
      expect(r.bloqueo?.tipo, TipoBloqueo.suscripcionNoActiva);
      expect(e.api.peticiones, 1);
    });

    test('un disparo manual con bloqueo intenta y, si el servidor lo vuelve a rechazar, el bloqueo se mantiene', () async {
      final e = _Entorno();
      e.sembrar(1);
      const plan = ErrorApp(tipo: TipoErrorApp.planNoIncluyeFuncionalidad, mensaje: 'Tu plan no incluye esta función.', estado: 403);
      e.api.programar(plan);
      e.api.programar(plan);
      await e.sincronizar(Disparador.registro);

      final r = await e.sincronizar();

      expect(e.api.peticiones, 2);
      expect(r.intentado, isTrue);
      expect(r.bloqueo?.tipo, TipoBloqueo.planNoIncluye);
      expect(e.motor.estado.bloqueo?.tipo, TipoBloqueo.planNoIncluye);
    });

    test('un disparo manual con bloqueo que ahora funciona lo levanta', () async {
      final e = _Entorno();
      e.sembrar(1);
      e.api.programar(const ErrorApp(tipo: TipoErrorApp.suscripcionNoActiva, mensaje: 'No activa', estado: 403));
      await e.sincronizar(Disparador.registro);

      final r = await e.sincronizar();

      expect(r.confirmadas, 1);
      expect(r.bloqueo, isNull);
      expect(e.motor.estado.bloqueo, isNull);
    });

    test('limpiarBloqueo permite que vuelvan los disparos automáticos', () async {
      final e = _Entorno();
      e.sembrar(1);
      e.api.programar(const ErrorApp(tipo: TipoErrorApp.suscripcionNoActiva, mensaje: 'No activa', estado: 403));
      await e.sincronizar(Disparador.registro);

      e.motor.limpiarBloqueo();
      final r = await e.sincronizar(Disparador.temporizador);

      expect(e.motor.estado.bloqueo, isNull);
      expect(r.confirmadas, 1);
    });

    test('con la sesión vencida los disparos automáticos no intentan; reiniciarSesion los habilita', () async {
      final e = _Entorno();
      e.sembrar(1);
      e.api.programar(const ErrorApp(tipo: TipoErrorApp.noAutorizado, mensaje: 'Tu sesión venció.', estado: 401));
      await e.sincronizar(Disparador.registro);
      expect(e.motor.estado.sesionVencida, isTrue);

      final bloqueada = await e.sincronizar(Disparador.temporizador);
      expect(bloqueada.intentado, isFalse);
      expect(bloqueada.sesionVencida, isTrue);
      expect(e.api.peticiones, 1);

      e.motor.reiniciarSesion();
      expect(e.motor.estado.sesionVencida, isFalse);
      final r = await e.sincronizar(Disparador.temporizador);
      expect(r.confirmadas, 1);
    });

    test('un disparo manual intenta aunque la sesión esté marcada como vencida', () async {
      final e = _Entorno();
      e.sembrar(1);
      e.api.programar(const ErrorApp(tipo: TipoErrorApp.noAutorizado, mensaje: 'Tu sesión venció.', estado: 401));
      await e.sincronizar(Disparador.registro);

      final r = await e.sincronizar();

      expect(e.api.peticiones, 2);
      expect(r.confirmadas, 1);
      expect(e.motor.estado.sesionVencida, isFalse);
    });
  });

  group('esperas (backoff)', () {
    test('el disparo automático respeta la espera y cuenta las omitidas', () async {
      final e = _Entorno();
      e.cola.sembrar(operacionDePrueba(id(1), proximoReintentoEn: e.reloj.actual.add(const Duration(minutes: 1)), fechaOperacion: hora(1)));
      e.cola.sembrar(operacionDePrueba(id(2), fechaOperacion: hora(2)));

      final r = await e.sincronizar(Disparador.temporizador);

      expect(r.omitidasPorEspera, 1);
      expect(r.enviadas, 1);
      expect(e.api.idsEnviados, [id(2)]);
      expect(r.pendientes, 1);
    });

    test('solo con esperas pendientes no intenta y reporta las omitidas', () async {
      final e = _Entorno();
      e.cola.sembrar(operacionDePrueba(id(1), proximoReintentoEn: e.reloj.actual.add(const Duration(minutes: 1))));

      final r = await e.sincronizar(Disparador.primerPlano);

      expect(r.intentado, isFalse);
      expect(r.omitidasPorEspera, 1);
      expect(r.pendientes, 1);
      expect(e.api.peticiones, 0);
    });

    test('cumplida la espera, el siguiente disparo automático la envía', () async {
      final e = _Entorno();
      e.cola.sembrar(operacionDePrueba(id(1), proximoReintentoEn: e.reloj.actual.add(const Duration(minutes: 1))));
      await e.sincronizar(Disparador.temporizador);

      e.reloj.avanzar(const Duration(minutes: 2));
      final r = await e.sincronizar(Disparador.temporizador);

      expect(r.confirmadas, 1);
      expect(r.omitidasPorEspera, 0);
    });

    test('el disparo manual ignora la espera', () async {
      final e = _Entorno();
      e.cola.sembrar(operacionDePrueba(id(1), proximoReintentoEn: e.reloj.actual.add(const Duration(hours: 1))));

      final r = await e.sincronizar();

      expect(r.confirmadas, 1);
      expect(r.omitidasPorEspera, 0);
      final consulta = e.cola.de('paraEnviar').single;
      expect(consulta.detalle['ignorarEspera'], isTrue);
    });

    test('con la espera calculada por defecto, el primer fallo espera cerca de 5 segundos', () async {
      final cola = ColaFalsa([operacionDePrueba(id(1))]);
      final api = SincronizacionApiFalsa()..programar(_servidor503);
      final reloj = _Reloj();
      final motor = MotorSincronizacion(
        cola: cola,
        api: api,
        reloj: reloj,
        conectividad: ConectividadFalsa(),
        dispositivoId: () async => 'd',
      );

      await motor.sincronizar(empresaId: _empresa, usuarioId: _usuario);

      final espera = cola.fila(id(1)).proximoReintentoEn!.difference(reloj.actual);
      expect(espera.inMilliseconds, inInclusiveRange(4000, 6000));
    });

    test('la espera usa el número de intentos de CADA operación (el mayor del lote)', () async {
      final e = _Entorno(espera: (n) => Duration(seconds: n));
      e.cola.sembrar(operacionDePrueba(id(1), intentos: 0, fechaOperacion: hora(1)));
      e.cola.sembrar(operacionDePrueba(id(2), intentos: 4, fechaOperacion: hora(2)));
      e.api.programar(_sinConexion());

      await e.sincronizar();

      // La segunda llevaba 4 intentos y con este envío son 5; el mayor manda para todo el lote.
      expect(e.op(1).proximoReintentoEn, e.reloj.actual.add(const Duration(seconds: 5)));
      expect(e.op(2).proximoReintentoEn, e.reloj.actual.add(const Duration(seconds: 5)));
    });

    test('el reenvío de una enviada huérfana también cuenta un intento en la espera', () async {
      final e = _Entorno(espera: (n) => Duration(seconds: n));
      e.cola.sembrar(operacionDePrueba(id(1), estado: EstadoOperacion.enviada, intentos: 3));
      e.api.programar(_servidor503);

      await e.sincronizar();

      expect(e.op(1).intentos, 4);
      expect(e.op(1).proximoReintentoEn, e.reloj.actual.add(const Duration(seconds: 4)));
    });

    test('la espera crece con cada fallo consecutivo', () async {
      final e = _Entorno(espera: (n) => Duration(seconds: 10 * n));
      e.sembrar(1);
      e.api.programar(_sinConexion());
      e.api.programar(_sinConexion());

      await e.sincronizar();
      final primera = e.op(1).proximoReintentoEn!.difference(e.reloj.actual);
      await e.sincronizar();
      final segunda = e.op(1).proximoReintentoEn!.difference(e.reloj.actual);

      expect(primera, const Duration(seconds: 10));
      expect(segunda, const Duration(seconds: 20));
      expect(e.op(1).intentos, 2);
    });
  });

  group('errores del lote (las operaciones se conservan siempre)', () {
    test('sin conexión y NO recibido: vuelven a registrada con espera y se detiene el resto', () async {
      final e = _Entorno();
      e.sembrar(45);
      e.api.programar(_sinConexion());

      final r = await e.sincronizar();

      expect(e.api.peticiones, 1);
      expect(r.intentado, isTrue);
      expect(r.fallidasPorRed, 20);
      expect(r.confirmadas, 0);
      expect(r.pendientes, 45);
      for (var i = 1; i <= 20; i++) {
        expect(e.op(i).estado, EstadoOperacion.registrada, reason: 'op $i');
        expect(e.op(i).intentos, 1);
        expect(e.op(i).ultimoError, contains('Sin conexión'));
        expect(e.op(i).proximoReintentoEn, e.reloj.actual.add(const Duration(seconds: 10)));
      }
      // Los lotes siguientes ni se tocaron.
      expect(e.op(21).intentos, 0);
      expect(e.op(21).estado, EstadoOperacion.registrada);
      expect(e.cola.de('marcarEnviadas'), hasLength(1));
    });

    test('sin conexión y posiblemente recibido: SIGUEN enviadas (reenviar es seguro) con espera', () async {
      final e = _Entorno();
      e.sembrar(25);
      e.api.programar(_sinConexion(recibido: true));

      final r = await e.sincronizar();

      expect(e.api.peticiones, 1);
      expect(r.fallidasPorRed, 20);
      for (var i = 1; i <= 20; i++) {
        expect(e.op(i).estado, EstadoOperacion.enviada);
        expect(e.op(i).intentos, 1);
        expect(e.op(i).proximoReintentoEn, e.reloj.actual.add(const Duration(seconds: 10)));
        expect(e.op(i).ultimoError, isNotEmpty);
      }
      expect(e.cola.de('volverARegistrada'), isEmpty);
      expect(e.cola.de('registrarFalloDeRed'), hasLength(1));
      expect(e.op(21).estado, EstadoOperacion.registrada);
    });

    test('error del servidor (5xx): siguen enviadas, con espera, y se detiene el resto', () async {
      final e = _Entorno();
      e.sembrar(30);
      e.api.programar(_servidor503);

      final r = await e.sincronizar();

      expect(e.api.peticiones, 1);
      expect(r.fallidasPorRed, 20);
      expect(e.op(1).estado, EstadoOperacion.enviada);
      expect(e.op(1).proximoReintentoEn, isNotNull);
      expect(e.op(1).intentos, 1);
      expect(e.op(25).estado, EstadoOperacion.registrada);
    });

    test('429: vuelven a registrada con espera y se detiene el resto', () async {
      final e = _Entorno();
      e.sembrar(30);
      e.api.programar(const ErrorApp(tipo: TipoErrorApp.desconocido, mensaje: 'Demasiadas solicitudes.', estado: 429));

      final r = await e.sincronizar();

      expect(e.api.peticiones, 1);
      expect(r.fallidasPorRed, 20);
      expect(e.op(1).estado, EstadoOperacion.registrada);
      expect(e.op(1).intentos, 1);
      expect(e.op(1).proximoReintentoEn, e.reloj.actual.add(const Duration(seconds: 10)));
    });

    test('408: vuelven a registrada con espera y se detiene el resto', () async {
      final e = _Entorno();
      e.sembrar(30);
      e.api.programar(const ErrorApp(tipo: TipoErrorApp.desconocido, mensaje: 'Tiempo agotado.', estado: 408));

      await e.sincronizar();

      expect(e.api.peticiones, 1);
      expect(e.op(1).estado, EstadoOperacion.registrada);
      expect(e.op(1).proximoReintentoEn, isNotNull);
    });

    test('401: conserva la cola, no gasta intentos, marca sesión vencida y se detiene', () async {
      final e = _Entorno();
      e.sembrar(30);
      e.api.programar(const ErrorApp(tipo: TipoErrorApp.noAutorizado, mensaje: 'Tu sesión venció. Inicia sesión de nuevo.', estado: 401));

      final r = await e.sincronizar();

      expect(e.api.peticiones, 1);
      expect(r.sesionVencida, isTrue);
      expect(e.motor.estado.sesionVencida, isTrue);
      expect(r.pendientes, 30);
      expect(r.fallidasPorRed, 0);
      expect(e.cola.todas, hasLength(30));
      expect(e.op(1).estado, EstadoOperacion.registrada);
      expect(e.op(1).intentos, 0);
      expect(e.op(1).proximoReintentoEn, isNull);
      final llamada = e.cola.de('volverARegistrada').single;
      expect(llamada.detalle['devolverIntento'], isTrue);
    });

    test('tras un 401, al volver a iniciar sesión las operaciones salen enseguida', () async {
      final e = _Entorno();
      e.sembrar(2);
      e.api.programar(const ErrorApp(tipo: TipoErrorApp.noAutorizado, mensaje: 'Sesión vencida', estado: 401));
      await e.sincronizar(Disparador.registro);

      e.motor.reiniciarSesion();
      final r = await e.sincronizar(Disparador.primerPlano);

      expect(r.confirmadas, 2);
      expect(r.omitidasPorEspera, 0);
    });

    test('plan sin la función: devuelve el intento, bloquea con el mensaje y se detiene', () async {
      final e = _Entorno();
      e.sembrar(30);
      e.api.programar(const ErrorApp(tipo: TipoErrorApp.planNoIncluyeFuncionalidad, mensaje: 'Tu plan no incluye esta función.', estado: 403));

      final r = await e.sincronizar();

      expect(e.api.peticiones, 1);
      expect(r.bloqueo?.tipo, TipoBloqueo.planNoIncluye);
      expect(r.bloqueo?.mensaje, 'Tu plan no incluye esta función.');
      expect(e.op(1).estado, EstadoOperacion.registrada);
      expect(e.op(1).intentos, 0);
      expect(e.cola.de('volverARegistrada').single.detalle['devolverIntento'], isTrue);
      expect(r.sesionVencida, isFalse);
    });

    test('suscripción no activa: devuelve el intento, bloquea con el mensaje y se detiene', () async {
      final e = _Entorno();
      e.sembrar(30);
      e.api.programar(const ErrorApp(tipo: TipoErrorApp.suscripcionNoActiva, mensaje: 'La suscripción de esta tienda no está activa.', estado: 403));

      final r = await e.sincronizar();

      expect(e.api.peticiones, 1);
      expect(r.bloqueo?.tipo, TipoBloqueo.suscripcionNoActiva);
      expect(r.bloqueo?.mensaje, contains('suscripción'));
      expect(e.op(1).estado, EstadoOperacion.registrada);
      expect(e.op(1).intentos, 0);
      expect(e.motor.estado.bloqueo?.tipo, TipoBloqueo.suscripcionNoActiva);
    });

    test('el servidor habla un contrato más nuevo: bloqueo actualizarApp y las operaciones se conservan', () async {
      final e = _Entorno();
      e.sembrar(2);
      e.api.programar(const ErrorApp(tipo: TipoErrorApp.desconocido, mensaje: mensajeActualizarApp));

      final r = await e.sincronizar();

      expect(r.bloqueo?.tipo, TipoBloqueo.actualizarApp);
      expect(r.bloqueo?.mensaje, mensajeActualizarApp);
      // La respuesta SÍ llegó: pudo procesarse, así que siguen 'enviada' y se reenviarán con seguridad.
      expect(e.op(1).estado, EstadoOperacion.enviada);
      expect(e.cola.todas, hasLength(2));
      expect((await e.sincronizar(Disparador.temporizador)).intentado, isFalse);
    });

    test('un error desconocido que no es el de actualizar la app se trata como 5xx', () async {
      final e = _Entorno();
      e.sembrar(25);
      e.api.programar(const ErrorApp(tipo: TipoErrorApp.desconocido, mensaje: 'Ocurrió un error inesperado.', estado: 418));

      final r = await e.sincronizar();

      expect(r.bloqueo, isNull);
      expect(e.api.peticiones, 1);
      expect(e.op(1).estado, EstadoOperacion.enviada);
      expect(e.op(1).proximoReintentoEn, isNotNull);
    });

    test('403 prohibido, 404 y 409 también se tratan como 5xx: se conservan y se reintentan', () async {
      for (final (tipo, estado) in [
        (TipoErrorApp.prohibido, 403),
        (TipoErrorApp.noEncontrado, 404),
        (TipoErrorApp.conflicto, 409),
        (TipoErrorApp.limitePlanExcedido, 409),
      ]) {
        final e = _Entorno();
        e.sembrar(1);
        e.api.programar(ErrorApp(tipo: tipo, mensaje: 'x', estado: estado));

        final r = await e.sincronizar();

        expect(e.op(1).estado, EstadoOperacion.enviada, reason: '$tipo');
        expect(e.op(1).proximoReintentoEn, isNotNull, reason: '$tipo');
        expect(r.fallidasPorRed, 1, reason: '$tipo');
      }
    });

    test('una excepción que no es ErrorApp también se trata como 5xx y no se pierde nada', () async {
      final e = _Entorno();
      e.sembrar(2);
      e.api.programar((LoteEnvio lote) => throw const FormatException('respuesta rota'));

      final r = await e.sincronizar();

      expect(r.fallidasPorRed, 2);
      expect(e.op(1).estado, EstadoOperacion.enviada);
      expect(e.cola.todas, hasLength(2));
    });

    test('tras un error de red, el siguiente intento envía lo mismo y se confirma', () async {
      final e = _Entorno();
      e.sembrar(3);
      e.api.programar(_sinConexion());
      await e.sincronizar();

      final r = await e.sincronizar();

      expect(r.confirmadas, 3);
      expect(e.api.idsPorLote.last, [id(1), id(2), id(3)]);
      expect(e.op(1).intentos, 2);
    });
  });

  group('422 y 400 del lote entero: se aísla la operación mala', () {
    void programarMala(_Entorno e, Set<String> malas, ErrorApp error) {
      e.api.porDefecto = (lote) {
        if (lote.operaciones.any((o) => malas.contains(o.operacionId))) throw error;
        return confirmarTodas(lote);
      };
    }

    test('422: reenvía una por una; la mala queda rechazada localmente y las demás se confirman', () async {
      final e = _Entorno();
      e.sembrar(3);
      programarMala(e, {id(2)}, _validacion422);
      e.api.programar(_validacion422);

      final r = await e.sincronizar();

      expect(e.api.peticiones, 4);
      expect(e.api.idsPorLote, [
        [id(1), id(2), id(3)],
        [id(1)],
        [id(2)],
        [id(3)],
      ]);
      expect(r.confirmadas, 2);
      expect(r.rechazadas, 1);
      expect(r.pendientes, 0);
      expect(e.op(1).estado, EstadoOperacion.confirmada);
      expect(e.op(2).estado, EstadoOperacion.rechazada);
      expect(e.op(2).ultimoError, 'El servidor no aceptó los datos (código 422).');
      expect(e.op(3).estado, EstadoOperacion.confirmada);
      expect(r.enviadas, 3);
    });

    test('400 del lote entero también aísla', () async {
      final e = _Entorno();
      e.sembrar(2);
      programarMala(e, {id(1)}, _http400);
      e.api.programar(_http400);

      final r = await e.sincronizar();

      expect(r.rechazadas, 1);
      expect(r.confirmadas, 1);
      expect(e.op(1).ultimoError, 'El servidor no aceptó los datos (código 400).');
      expect(e.op(1).estado, EstadoOperacion.rechazada);
    });

    test('una operación rechazada localmente deja su fila de resultado y no se reenvía', () async {
      final e = _Entorno();
      e.sembrar(2);
      programarMala(e, {id(1)}, _validacion422);
      e.api.programar(_validacion422);
      await e.sincronizar();

      final resultados = await e.cola.resultados(id(1));
      expect(resultados.single.estadoResultado, 'rechazada');
      expect(resultados.single.motivo, contains('422'));

      e.api.lotes.clear();
      await e.sincronizar();
      expect(e.api.peticiones, 0);
    });

    test('un lote de una sola operación con 422 se rechaza sin reenviar', () async {
      final e = _Entorno();
      e.sembrar(1);
      e.api.programar(_validacion422);

      final r = await e.sincronizar();

      expect(e.api.peticiones, 1);
      expect(r.rechazadas, 1);
      expect(e.op(1).estado, EstadoOperacion.rechazada);
    });

    test('si todas son malas, todas se rechazan localmente y el motor sigue con los demás lotes', () async {
      final e = _Entorno(tamanioLote: 2);
      e.sembrar(4);
      e.api.porDefecto = (lote) => throw _validacion422;
      e.api.programar(_validacion422);
      e.api.programar(_validacion422);

      final r = await e.sincronizar();

      expect(r.rechazadas, 4);
      expect(r.confirmadas, 0);
      expect(e.cola.todas.every((o) => o.estado == EstadoOperacion.rechazada), isTrue);
    });

    test('la 422 de un lote no impide que el siguiente lote se envíe', () async {
      final e = _Entorno(tamanioLote: 2);
      e.sembrar(4);
      e.api.programar(_validacion422);
      programarMala(e, {id(2)}, _validacion422);

      final r = await e.sincronizar();

      expect(r.rechazadas, 1);
      expect(r.confirmadas, 3);
    });

    test('un corte de red a mitad del aislamiento detiene el resto y deja las demás enviadas con espera', () async {
      final e = _Entorno();
      e.sembrar(4);
      e.api.programar(_validacion422);
      e.api.programar(respuestaDeLote([resultadoConfirmada(id(1))]));
      e.api.programar(_sinConexion());

      final r = await e.sincronizar();

      expect(e.op(1).estado, EstadoOperacion.confirmada);
      // La 2 y las que faltaban vuelven a registrada (el corte fue al conectar: nunca llegaron).
      for (var i = 2; i <= 4; i++) {
        expect(e.op(i).estado, EstadoOperacion.registrada, reason: 'op $i');
        expect(e.op(i).proximoReintentoEn, isNotNull);
      }
      expect(r.confirmadas, 1);
      expect(r.fallidasPorRed, 3);
      expect(e.cola.todas, hasLength(4));
    });

    test('la 422 de una operación no cuenta como fallo de red ni detiene el sistema', () async {
      final e = _Entorno();
      e.sembrar(2);
      programarMala(e, {id(1), id(2)}, _validacion422);
      e.api.programar(_validacion422);

      final r = await e.sincronizar();

      expect(r.fallidasPorRed, 0);
      expect(r.bloqueo, isNull);
      expect(r.sesionVencida, isFalse);
    });
  });

  group('respuestas parciales o con avisos', () {
    test('una operación que el servidor NO devuelve queda enviada con "Sin respuesta del servidor" y espera', () async {
      final e = _Entorno();
      e.sembrar(3);
      e.api.programar(respuestaDeLote([resultadoConfirmada(id(1)), resultadoConfirmada(id(3))]));

      final r = await e.sincronizar();

      expect(r.confirmadas, 2);
      expect(r.fallidasPorRed, 1);
      expect(e.op(2).estado, EstadoOperacion.enviada);
      expect(e.op(2).ultimoError, 'Sin respuesta del servidor');
      expect(e.op(2).proximoReintentoEn, e.reloj.actual.add(const Duration(seconds: 10)));
      expect(r.pendientes, 1);
    });

    test('un error_temporal queda enviada con espera y no cambia de estado', () async {
      final e = _Entorno();
      e.sembrar(2);
      e.api.programar(respuestaDeLote([resultadoConfirmada(id(1)), resultadoTemporal(id(2))]));

      final r = await e.sincronizar();

      expect(r.confirmadas, 1);
      expect(r.fallidasPorRed, 1);
      expect(e.op(2).estado, EstadoOperacion.enviada);
      expect(e.op(2).proximoReintentoEn, isNotNull);
      expect(e.op(2).ultimoError, isNotEmpty);
      expect(await e.cola.resultados(id(2)), isEmpty);
    });

    test('un error_temporal se reenvía en la siguiente corrida con la misma operacion_id', () async {
      final e = _Entorno();
      e.sembrar(1);
      e.api.programar(respuestaDeLote([resultadoTemporal(id(1))]));
      await e.sincronizar();

      final r = await e.sincronizar();

      expect(r.confirmadas, 1);
      expect(e.api.idsEnviados, [id(1), id(1)]);
    });

    test('duplicada=true se trata igual que un resultado nuevo', () async {
      final e = _Entorno();
      e.sembrar(2);
      e.api.programar(respuestaDeLote([
        resultadoConfirmada(id(1), duplicada: true),
        resultadoRechazada(id(2), duplicada: true),
      ]));

      final r = await e.sincronizar();

      expect(r.confirmadas, 1);
      expect(r.rechazadas, 1);
      expect(e.op(1).estado, EstadoOperacion.confirmada);
      expect(e.op(2).estado, EstadoOperacion.rechazada);
    });

    test('una operación en estado final no retrocede ni se cuenta como cambio', () async {
      final e = _Entorno();
      e.sembrar(1);
      // Mientras el lote viaja, otra vía (p. ej. la revisión) deja la operación confirmada.
      e.api.alRecibir = (lote) {
        e.cola.sembrar(operacionDePrueba(id(1), estado: EstadoOperacion.confirmada, intentos: 1, fechaOperacion: hora(1)));
      };
      e.api.programar(respuestaDeLote([resultadoRechazada(id(1))]));

      final r = await e.sincronizar();

      expect(e.op(1).estado, EstadoOperacion.confirmada);
      expect(r.rechazadas, 0);
      expect(r.confirmadas, 0);
      expect(r.huboCambios, isFalse);
    });

    test('un resultado repetido de en_conflicto no se cuenta dos veces', () async {
      final e = _Entorno();
      e.cola.sembrar(operacionDePrueba(id(1), estado: EstadoOperacion.enviada, intentos: 1));
      e.api.programar(respuestaDeLote([resultadoEnConflicto(id(1))]));
      final primera = await e.sincronizar();
      expect(primera.enConflicto, 1);

      // Ya está en conflicto: no vuelve a ser candidata.
      final segunda = await e.sincronizar();
      expect(segunda.enConflicto, 0);
      expect(e.api.peticiones, 1);
    });

    test('una fila con el payload dañado se rechaza localmente y las demás se envían', () async {
      final e = _Entorno();
      e.cola.sembrar(operacionDePrueba(id(1), payload: '{esto no es json', fechaOperacion: hora(1)));
      e.cola.sembrar(operacionDePrueba(id(2), fechaOperacion: hora(2)));

      final r = await e.sincronizar();

      expect(e.op(1).estado, EstadoOperacion.rechazada);
      expect(e.op(2).estado, EstadoOperacion.confirmada);
      expect(r.rechazadas, 1);
      expect(r.confirmadas, 1);
      expect(e.api.idsEnviados, [id(2)]);
    });
  });

  group('revisión de conflictos', () {
    ColaFalsa conConflictos(_Entorno e, [int n = 1]) {
      for (var i = 1; i <= n; i++) {
        e.cola.sembrar(operacionDePrueba(id(i), estado: EstadoOperacion.enConflicto, intentos: 1, fechaOperacion: hora(i)));
      }
      return e.cola;
    }

    test('manual: si un encargado la confirmó, se aplica y se cuenta', () async {
      final e = _Entorno();
      conConflictos(e);
      e.api.programarConsulta(id(1), resultadoConfirmada(id(1)));

      final r = await e.sincronizar();

      expect(e.api.consultas, [id(1)]);
      expect(e.op(1).estado, EstadoOperacion.confirmada);
      expect(r.confirmadas, 1);
      expect(r.huboCambios, isTrue);
      expect(r.intentado, isFalse);
      expect(e.api.peticiones, 0);
    });

    test('si la rechazó, se aplica como rechazada', () async {
      final e = _Entorno();
      conConflictos(e);
      e.api.programarConsulta(id(1), resultadoRechazada(id(1), motivo: 'stock_insuficiente'));

      final r = await e.sincronizar();

      expect(e.op(1).estado, EstadoOperacion.rechazada);
      expect(r.rechazadas, 1);
    });

    test('si sigue en conflicto, no pasa nada', () async {
      final e = _Entorno();
      conConflictos(e);
      e.api.programarConsulta(id(1), resultadoEnConflicto(id(1)));

      final r = await e.sincronizar();

      expect(e.op(1).estado, EstadoOperacion.enConflicto);
      expect(r.enConflicto, 0);
      expect(r.huboCambios, isFalse);
      expect(e.cola.de('aplicarResultados'), isEmpty);
    });

    test('si el servidor no la conoce (null), no pasa nada', () async {
      final e = _Entorno();
      conConflictos(e);

      final r = await e.sincronizar();

      expect(e.api.consultas, [id(1)]);
      expect(e.op(1).estado, EstadoOperacion.enConflicto);
      expect(r.huboCambios, isFalse);
    });

    test('si la consulta falla, no rompe y las demás se revisan', () async {
      final e = _Entorno();
      conConflictos(e, 2);
      e.api.programarConsulta(id(1), _servidor503);
      e.api.programarConsulta(id(2), resultadoConfirmada(id(2)));

      final r = await e.sincronizar();

      expect(e.api.consultas, [id(1), id(2)]);
      expect(e.op(1).estado, EstadoOperacion.enConflicto);
      expect(e.op(2).estado, EstadoOperacion.confirmada);
      expect(r.confirmadas, 1);
    });

    test('un error no esperado (no ErrorApp) en la consulta tampoco afecta a lo demás', () async {
      final e = _Entorno();
      conConflictos(e);
      e.sembrar(1, desde: 5);
      e.api.programarConsulta(id(1), StateError('boom'));

      final r = await e.sincronizar();

      expect(r.confirmadas, 1);
      expect(e.op(5).estado, EstadoOperacion.confirmada);
    });

    test('un error de la consulta no cambia el resultado del envío de lotes', () async {
      final e = _Entorno();
      conConflictos(e);
      e.sembrar(2, desde: 5);
      e.api.programarConsulta(id(1), const ErrorApp(tipo: TipoErrorApp.noAutorizado, mensaje: 'x', estado: 401));

      final r = await e.sincronizar();

      expect(r.confirmadas, 2);
      expect(r.sesionVencida, isFalse);
    });

    test('automático: revisa la primera vez, luego espera el intervalo configurado', () async {
      final e = _Entorno(revision: const Duration(minutes: 15));
      conConflictos(e);
      e.api.programarConsulta(id(1), resultadoEnConflicto(id(1)));

      await e.sincronizar(Disparador.temporizador);
      expect(e.api.consultas, hasLength(1));

      e.reloj.avanzar(const Duration(minutes: 14));
      await e.sincronizar(Disparador.temporizador);
      expect(e.api.consultas, hasLength(1));

      e.reloj.avanzar(const Duration(minutes: 2));
      await e.sincronizar(Disparador.temporizador);
      expect(e.api.consultas, hasLength(2));
    });

    test('el intervalo de revisión es configurable', () async {
      final e = _Entorno(revision: const Duration(seconds: 30));
      conConflictos(e);
      await e.sincronizar(Disparador.registro);
      e.reloj.avanzar(const Duration(seconds: 31));

      await e.sincronizar(Disparador.registro);

      expect(e.api.consultas, hasLength(2));
    });

    test('manual: revisa siempre, aunque no haya pasado el intervalo', () async {
      final e = _Entorno();
      conConflictos(e);
      await e.sincronizar(Disparador.temporizador);

      await e.sincronizar();
      await e.sincronizar();

      expect(e.api.consultas, hasLength(3));
    });

    test('no revisa sin conexión (disparo automático)', () async {
      final e = _Entorno(enLinea: false);
      conConflictos(e);

      await e.sincronizar(Disparador.temporizador);

      expect(e.api.consultas, isEmpty);
    });

    test('no revisa si el envío se detuvo por un error de red o de sesión', () async {
      final e = _Entorno();
      conConflictos(e);
      e.sembrar(1, desde: 5);
      e.api.programar(_sinConexion());

      await e.sincronizar();

      expect(e.api.consultas, isEmpty);
    });

    test('se aplica con el id consultado aunque el detalle traiga otro', () async {
      final e = _Entorno();
      conConflictos(e);
      e.api.programarConsulta(id(1), resultadoConfirmada(''));

      final r = await e.sincronizar();

      expect(e.op(1).estado, EstadoOperacion.confirmada);
      expect(r.confirmadas, 1);
    });

    test('las operaciones de otro usuario no se consultan', () async {
      final e = _Entorno();
      e.cola.sembrar(operacionDePrueba(id(1), estado: EstadoOperacion.enConflicto, usuarioId: 77));

      await e.sincronizar();

      expect(e.api.consultas, isEmpty);
    });

    test('una operación resuelta por la web desaparece de pendientes y no vuelve a consultarse', () async {
      final e = _Entorno();
      conConflictos(e);
      e.api.programarConsulta(id(1), resultadoConfirmada(id(1)));
      await e.sincronizar();

      await e.sincronizar();

      expect(e.api.consultas, [id(1)]);
    });
  });

  group('recuperación tras un reinicio', () {
    test('las enviadas huérfanas se reenvían sin código especial (cada reenvío cuenta un intento)', () async {
      final e = _Entorno();
      for (var i = 1; i <= 3; i++) {
        e.cola.sembrar(operacionDePrueba(id(i), estado: EstadoOperacion.enviada, intentos: 1, fechaOperacion: hora(i)));
      }
      e.api.porDefecto = (lote) => respuestaDeLote([
        for (final o in lote.operaciones) resultadoConfirmada(o.operacionId, duplicada: true),
      ]);

      // Un motor NUEVO sobre la misma cola, como tras reabrir la app.
      final nuevo = e.crearMotor();
      final r = await nuevo.sincronizar(empresaId: _empresa, usuarioId: _usuario, disparador: Disparador.primerPlano);

      expect(r.confirmadas, 3);
      expect(e.api.idsEnviados, [id(1), id(2), id(3)]);
      expect(e.op(1).intentos, 2);
    });

    test('un corte con respuesta incierta se reenvía luego sin duplicar en el servidor', () async {
      final e = _Entorno();
      e.sembrar(5);
      final procesadas = <String>{};
      e.api.porDefecto = (lote) => respuestaDeLote([
        // `add` devuelve false si el servidor ya la había procesado: entonces es un reenvío (duplicada).
        for (final o in lote.operaciones) resultadoConfirmada(o.operacionId, duplicada: !procesadas.add(o.operacionId)),
      ]);
      // El primer lote SÍ se procesó en el servidor, pero la respuesta nunca llegó.
      e.api.programar((LoteEnvio lote) {
        for (final o in lote.operaciones) {
          procesadas.add(o.operacionId);
        }
        throw _sinConexion(recibido: true);
      });
      await e.sincronizar();
      expect(e.op(1).estado, EstadoOperacion.enviada);

      final nuevo = e.crearMotor();
      e.reloj.avanzar(const Duration(minutes: 5));
      final r = await nuevo.sincronizar(empresaId: _empresa, usuarioId: _usuario, disparador: Disparador.conexionRecuperada);

      expect(r.confirmadas, 5);
      expect(procesadas, hasLength(5));
      expect(e.api.lotes.last.operaciones, hasLength(5));
      expect(e.cola.todas.every((o) => o.estado == EstadoOperacion.confirmada), isTrue);
      // Cada operación quedó con UNA sola confirmación.
      for (var i = 1; i <= 5; i++) {
        expect((await e.cola.resultados(id(i))).where((x) => x.estadoResultado == 'confirmada'), hasLength(1));
      }
    });

    test('un motor nuevo no hereda el bloqueo ni la sesión vencida del anterior', () async {
      final e = _Entorno();
      e.sembrar(1);
      e.api.programar(const ErrorApp(tipo: TipoErrorApp.noAutorizado, mensaje: 'x', estado: 401));
      await e.sincronizar();

      final nuevo = e.crearMotor();

      expect(nuevo.estado.sesionVencida, isFalse);
      expect(nuevo.estado.bloqueo, isNull);
      expect(nuevo.estado.enCurso, isFalse);
    });
  });

  group('observabilidad (RNF10)', () {
    test('cada operación deja un registro con id corto, tipo, estado, intentos y código de motivo', () async {
      final e = _Entorno();
      e.sembrar(2);
      e.api.programar(respuestaDeLote([resultadoConfirmada(id(1)), resultadoRechazada(id(2), motivo: 'variante_inactiva')]));

      await e.sincronizar();

      expect(
        logs.where((l) => l.startsWith('sync op=00000001')),
        [contains('tipo=venta_contado')],
      );
      final l1 = logs.singleWhere((l) => l.startsWith('sync op=00000001'));
      expect(l1, contains('estado=confirmada'));
      expect(l1, contains('intentos=1'));
      final l2 = logs.singleWhere((l) => l.startsWith('sync op=00000002'));
      expect(l2, contains('estado=rechazada'));
      expect(l2, contains('motivo=variante_inactiva'));
    });

    test('hay un registro por sincronización con los conteos y los milisegundos', () async {
      final e = _Entorno();
      e.sembrar(3);

      await e.sincronizar(Disparador.registro);

      final fin = logs.where((l) => l.startsWith('sync fin')).toList();
      expect(fin, hasLength(1));
      expect(fin.single, contains('disparador=registro'));
      expect(fin.single, contains('enviadas=3'));
      expect(fin.single, contains('confirmadas=3'));
      expect(fin.single, contains('pendientes=0'));
      expect(RegExp(r'ms=\d+').hasMatch(fin.single), isTrue);
    });

    test('NUNCA salen nombres, documentos, teléfonos, montos ni el id completo', () async {
      final e = _Entorno();
      final payload = jsonEncode({
        'cliente_id': 3,
        'cliente_nombre': 'Juan Pérez',
        'ci_nit': '1234567',
        'telefono': '70011223',
        'total': '75.00',
        'lineas': [
          {'variante_id': 5, 'cantidad': 1, 'precio_unitario': '75.00'},
        ],
      });
      e.cola.sembrar(operacionDePrueba(id(1), payload: payload, fechaOperacion: hora(1)));
      e.cola.sembrar(operacionDePrueba(id(2), payload: payload, fechaOperacion: hora(2)));
      e.cola.sembrar(operacionDePrueba(id(3), payload: payload, fechaOperacion: hora(3)));
      e.api.programar(respuestaDeLote([
        resultadoConfirmada(id(1)),
        resultadoRechazada(id(2)),
        resultadoEnConflicto(id(3)),
      ]));
      e.api.programar(const ErrorApp(tipo: TipoErrorApp.servidor, mensaje: 'Juan Pérez 1234567 Bs 75.00', estado: 500));
      await e.sincronizar();
      e.sembrar(1, desde: 4);
      await e.sincronizar();

      final todo = logs.join('\n');
      for (final prohibido in ['Juan', 'Pérez', '1234567', '70011223', '75.00', 'Bs ', id(1), id(2), id(3), 'Texto del servidor']) {
        expect(todo.contains(prohibido), isFalse, reason: 'el log contiene "$prohibido"');
      }
      expect(logs, isNotEmpty);
    });

    test('un fallo de red se registra por operación con su estado y sin el mensaje del error', () async {
      final e = _Entorno();
      e.sembrar(1);
      e.api.programar(const ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: 'Mensaje con Maria 555', posiblementeRecibido: true));

      await e.sincronizar();

      final linea = logs.singleWhere((l) => l.startsWith('sync op=00000001'));
      expect(linea, contains('estado=enviada'));
      expect(linea, contains('intentos=1'));
      expect(logs.join('\n').contains('Maria'), isFalse);
    });

    test('una corrida que no intenta nada también deja su registro final', () async {
      final e = _Entorno(enLinea: false);

      await e.sincronizar(Disparador.temporizador);

      final fin = logs.singleWhere((l) => l.startsWith('sync fin'));
      expect(fin, contains('intentado=false'));
      expect(fin, contains('omitida=sin_conexion'));
    });
  });

  group('modelos', () {
    test('ResumenSync por defecto está vacío y no hubo cambios', () {
      const r = ResumenSync();
      expect(r.huboCambios, isFalse);
      expect(r.intentado, isFalse);
      expect(r.bloqueo, isNull);
      expect(r.sesionVencida, isFalse);
    });

    test('huboCambios es verdadero con cualquiera de los tres conteos', () {
      expect(const ResumenSync(confirmadas: 1).huboCambios, isTrue);
      expect(const ResumenSync(rechazadas: 1).huboCambios, isTrue);
      expect(const ResumenSync(enConflicto: 1).huboCambios, isTrue);
      expect(const ResumenSync(fallidasPorRed: 3, pendientes: 3).huboCambios, isFalse);
    });

    test('BloqueoSync compara por tipo y mensaje', () {
      const a = BloqueoSync(tipo: TipoBloqueo.planNoIncluye, mensaje: 'x');
      const b = BloqueoSync(tipo: TipoBloqueo.planNoIncluye, mensaje: 'x');
      const c = BloqueoSync(tipo: TipoBloqueo.actualizarApp, mensaje: 'x');
      expect(a, b);
      expect(a.hashCode, b.hashCode);
      expect(a == c, isFalse);
    });

    test('EstadoSync inicial: sin sincronizar, sin bloqueo y sin sesión vencida', () {
      final e = _Entorno();
      expect(e.motor.estado.enCurso, isFalse);
      expect(e.motor.estado.ultimaSincronizacion, isNull);
      expect(e.motor.estado.ultimoResumen, isNull);
      expect(e.motor.estado.bloqueo, isNull);
      expect(e.motor.estado.sesionVencida, isFalse);
    });
  });
}
