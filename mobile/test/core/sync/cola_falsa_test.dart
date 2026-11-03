import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/sync/cola_operaciones.dart';
import 'package:mobile/core/sync/lineas_operacion.dart';
import 'package:mobile/core/sync/operacion_pendiente.dart';

import '../../helpers/cola_falsa.dart';
import '../../helpers/sincronizacion_api_falsa.dart';

/// La [ColaFalsa] la usan las pruebas de motor y de pantallas: aquí se comprueba que respeta las reglas de la interfaz.
void main() {
  final ahora = DateTime.utc(2026, 10, 31, 12);

  NuevaVenta venta(String id, {bool efectivo = true, List<LineaVenta>? lineas}) => NuevaVenta(
    operacionId: id,
    empresaId: 1,
    sucursalId: 1,
    usuarioId: 10,
    fechaOperacion: DateTime.utc(2026, 10, 31, 9),
    lineas: lineas ?? const [LineaVenta(varianteId: 5, cantidad: 2, precioUnitarioCentavos: 7500)],
    efectivoConfirmado: efectivo,
  );

  test('registrarVenta guarda una operación registrada con el payload del contrato y avisa del cambio', () async {
    final cola = ColaFalsa();
    var avisos = 0;
    cola.cambios.listen((_) => avisos++);

    await cola.registrarVenta(venta('a'));
    await pumpEventQueue();

    final o = cola.fila('a');
    expect(o.estado, EstadoOperacion.registrada);
    expect(o.intentos, 0);
    expect(o.payload, contains('"total":"150.00"'));
    expect(avisos, 1);
  });

  test('un id repetido, una venta sin efectivo o sin líneas lanzan ColaError y no guardan nada', () async {
    final cola = ColaFalsa();
    await cola.registrarVenta(venta('a'));

    await expectLater(cola.registrarVenta(venta('a')), throwsA(isA<ColaError>()));
    await expectLater(cola.registrarVenta(venta('b', efectivo: false)), throwsA(isA<ColaError>()));
    await expectLater(cola.registrarVenta(venta('c', lineas: const [])), throwsA(isA<ColaError>()));

    expect(cola.todas, hasLength(1));
  });

  test('paraEnviar respeta la espera, ordena por fecha_operacion y solo trae registrada o enviada', () async {
    final cola = ColaFalsa([
      operacionDePrueba('tarde', fechaOperacion: DateTime.utc(2026, 10, 31, 11)),
      operacionDePrueba('temprano', fechaOperacion: DateTime.utc(2026, 10, 31, 8), estado: EstadoOperacion.enviada),
      operacionDePrueba('espera', proximoReintentoEn: ahora.add(const Duration(minutes: 1))),
      operacionDePrueba('final', estado: EstadoOperacion.confirmada),
    ]);

    final conEspera = await cola.paraEnviar(empresaId: 1, usuarioId: 10, ahora: ahora);
    final sinEspera = await cola.paraEnviar(empresaId: 1, usuarioId: 10, ahora: ahora, ignorarEspera: true);

    expect(conEspera.map((o) => o.operacionId), ['temprano', 'tarde']);
    expect(sinEspera.map((o) => o.operacionId), containsAll(['temprano', 'tarde', 'espera']));
    expect(sinEspera.map((o) => o.operacionId), isNot(contains('final')));
  });

  test('marcarEnviadas suma un intento; volverARegistrada puede devolverlo', () async {
    final cola = ColaFalsa([operacionDePrueba('a'), operacionDePrueba('b')]);

    await cola.marcarEnviadas(['a', 'b']);
    expect(cola.fila('a').estado, EstadoOperacion.enviada);
    expect(cola.fila('a').intentos, 1);

    await cola.volverARegistrada(['a'], error: 'sin red', proximoReintento: ahora);
    await cola.volverARegistrada(['b'], devolverIntento: true);

    expect(cola.fila('a').estado, EstadoOperacion.registrada);
    expect(cola.fila('a').intentos, 1);
    expect(cola.fila('a').ultimoError, 'sin red');
    expect(cola.fila('b').intentos, 0);
    expect(cola.fila('b').proximoReintentoEn, isNull);
  });

  test('registrarFalloDeRed no cambia el estado', () async {
    final cola = ColaFalsa([operacionDePrueba('a', estado: EstadoOperacion.enviada, intentos: 1)]);

    await cola.registrarFalloDeRed(['a'], error: 'corte', proximoReintento: ahora);

    expect(cola.fila('a').estado, EstadoOperacion.enviada);
    expect(cola.fila('a').ultimoError, 'corte');
    expect(cola.fila('a').proximoReintentoEn, ahora);
  });

  test('aplicarResultados cambia el estado, guarda la fila de resultado y devuelve solo lo que cambió', () async {
    final cola = ColaFalsa([
      operacionDePrueba('a', estado: EstadoOperacion.enviada),
      operacionDePrueba('b', estado: EstadoOperacion.enviada),
    ]);

    final primera = await cola.aplicarResultados([resultadoConfirmada('a'), resultadoEnConflicto('b')], recibidoEn: ahora);
    final repetida = await cola.aplicarResultados([resultadoConfirmada('a'), resultadoEnConflicto('b')], recibidoEn: ahora);

    expect(primera, ['a', 'b']);
    expect(repetida, isEmpty);
    expect(cola.fila('a').estado, EstadoOperacion.confirmada);
    expect(cola.fila('a').resueltaEn, DateTime.utc(2026, 10, 31, 12));
    expect(cola.fila('b').estado, EstadoOperacion.enConflicto);
    expect(cola.fila('b').resueltaEn, isNull);
    expect(await cola.resultados('a'), hasLength(1));
  });

  test('una operación final no retrocede y un error_temporal no cambia el estado', () async {
    final cola = ColaFalsa([
      operacionDePrueba('a', estado: EstadoOperacion.confirmada),
      operacionDePrueba('b', estado: EstadoOperacion.enviada),
    ]);

    final cambiadas = await cola.aplicarResultados([resultadoRechazada('a'), resultadoTemporal('b')], recibidoEn: ahora);

    expect(cambiadas, isEmpty);
    expect(cola.fila('a').estado, EstadoOperacion.confirmada);
    expect(cola.fila('b').estado, EstadoOperacion.enviada);
    expect(cola.fila('b').ultimoError, isNotEmpty);
  });

  test('marcarRechazadaLocal solo actúa sobre registrada o enviada y deja su fila de resultado', () async {
    final cola = ColaFalsa([
      operacionDePrueba('a', estado: EstadoOperacion.enviada),
      operacionDePrueba('b', estado: EstadoOperacion.enConflicto),
    ]);

    await cola.marcarRechazadaLocal('a', motivo: 'Datos no válidos', recibidoEn: ahora);
    await cola.marcarRechazadaLocal('b', motivo: 'Datos no válidos', recibidoEn: ahora);

    expect(cola.fila('a').estado, EstadoOperacion.rechazada);
    expect(cola.fila('a').ultimoError, 'Datos no válidos');
    expect(cola.fila('b').estado, EstadoOperacion.enConflicto);
    expect((await cola.resultados('a')).single.codigoMotivo, 'rechazo_local');
  });

  test('conteoPorEstado incluye todos los estados y solo cuenta al usuario pedido', () async {
    final cola = ColaFalsa([
      operacionDePrueba('a'),
      operacionDePrueba('b', estado: EstadoOperacion.confirmada),
      operacionDePrueba('c', usuarioId: 99),
    ]);

    final conteo = await cola.conteoPorEstado(empresaId: 1, usuarioId: 10);

    expect(conteo.keys, containsAll(EstadoOperacion.values));
    expect(conteo[EstadoOperacion.registrada], 1);
    expect(conteo[EstadoOperacion.confirmada], 1);
    expect(conteo[EstadoOperacion.enviada], 0);
  });

  test('registra las llamadas y puede simular un fallo de escritura una sola vez', () async {
    final cola = ColaFalsa([operacionDePrueba('a')]);
    cola.fallarProximaEscritura = StateError('disco');

    await expectLater(cola.marcarEnviadas(['a']), throwsStateError);
    await cola.marcarEnviadas(['a']);

    expect(cola.de('marcarEnviadas'), hasLength(2));
    expect(cola.de('marcarEnviadas').last.ids, ['a']);
    expect(cola.fila('a').estado, EstadoOperacion.enviada);
  });
}
