import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/sync/contrato_sync.dart';
import 'package:mobile/core/sync/lineas_operacion.dart';
import 'package:mobile/core/sync/operacion_pendiente.dart';

OperacionPendiente _fila({String? payload, TipoOperacion tipo = TipoOperacion.ventaContado, DateTime? fecha}) {
  return OperacionPendiente(
    operacionId: 'aaaaaaaa-1111-4222-8333-bbbbbbbbbbbb',
    empresaId: 1,
    sucursalId: 3,
    usuarioId: 7,
    tipo: tipo,
    estado: EstadoOperacion.registrada,
    payload: payload ?? jsonEncode({'cliente_id': 5, 'total': '75.00'}),
    versionContrato: 1,
    intentos: 0,
    fechaOperacion: fecha ?? DateTime.utc(2026, 10, 31, 14, 5),
    creadaEn: DateTime.utc(2026, 10, 31, 14, 6),
  );
}

void main() {
  group('constantes', () {
    test('la versión del contrato es 1.0 y el lote del teléfono cabe en el del servidor (50)', () {
      expect(versionContratoSync, '1.0');
      expect(tamanioLoteSync, 20);
      expect(tamanioLoteSync, lessThanOrEqualTo(50));
    });
  });

  group('OperacionEnvio', () {
    test('desde(fila) toma el payload tal cual, sin recalcular nada', () {
      final envio = OperacionEnvio.desde(_fila());
      expect(envio.operacionId, 'aaaaaaaa-1111-4222-8333-bbbbbbbbbbbb');
      expect(envio.tipo, TipoOperacion.ventaContado);
      expect(envio.sucursalId, 3);
      expect(envio.fechaOperacion, DateTime.utc(2026, 10, 31, 14, 5));
      expect(envio.payload, {'cliente_id': 5, 'total': '75.00'});
    });

    test('toJson usa los nombres de cable y la fecha con Z', () {
      final json = OperacionEnvio.desde(_fila()).toJson();
      expect(json, {
        'operacion_id': 'aaaaaaaa-1111-4222-8333-bbbbbbbbbbbb',
        'tipo': 'venta_contado',
        'sucursal_id': 3,
        'fecha_operacion': '2026-10-31T14:05:00Z',
        'payload': {'cliente_id': 5, 'total': '75.00'},
      });
    });

    test('una reserva viaja con el tipo "reserva"', () {
      final json = OperacionEnvio.desde(_fila(tipo: TipoOperacion.reserva)).toJson();
      expect(json['tipo'], 'reserva');
    });

    test('la fecha local se convierte a UTC con Z', () {
      final local = DateTime(2026, 10, 31, 10, 0);
      final texto = OperacionEnvio.desde(_fila(fecha: local)).toJson()['fecha_operacion']! as String;
      expect(texto, endsWith('Z'));
      expect(DateTime.parse(texto), local.toUtc());
    });

    test('las fracciones de segundo se conservan', () {
      final texto = OperacionEnvio.desde(_fila(fecha: DateTime.utc(2026, 10, 31, 14, 5, 7, 250))).toJson()['fecha_operacion'];
      expect(texto, '2026-10-31T14:05:07.250Z');
    });

    test('un payload que no es JSON lanza un error en vez de enviar basura', () {
      expect(() => OperacionEnvio.desde(_fila(payload: 'no es json')), throwsFormatException);
    });
  });

  group('LoteEnvio.toJson', () {
    test('lleva la versión "1.0", el dispositivo y las operaciones', () {
      final lote = LoteEnvio(dispositivo: 'tel-abc', operaciones: [OperacionEnvio.desde(_fila())]);
      final json = lote.toJson();
      expect(json['version_contrato'], '1.0');
      expect(json['dispositivo'], 'tel-abc');
      expect((json['operaciones'] as List), hasLength(1));
    });

    test('sin dispositivo no manda la clave', () {
      final json = LoteEnvio(operaciones: [OperacionEnvio.desde(_fila())]).toJson();
      expect(json.containsKey('dispositivo'), isFalse);
    });

    test('NO manda empresa ni usuario (el servidor los toma del token)', () {
      final json = LoteEnvio(dispositivo: 'x', operaciones: [OperacionEnvio.desde(_fila())]).toJson();
      expect(json.keys, unorderedEquals(['version_contrato', 'dispositivo', 'operaciones']));
      final operacion = (json['operaciones'] as List).first as Map;
      expect(operacion.keys, unorderedEquals(['operacion_id', 'tipo', 'sucursal_id', 'fecha_operacion', 'payload']));
    });

    test('mantiene el orden de las operaciones', () {
      final a = OperacionEnvio(
        operacionId: 'a',
        tipo: TipoOperacion.reserva,
        sucursalId: 1,
        fechaOperacion: DateTime.utc(2026, 1, 1),
        payload: const {},
      );
      final b = OperacionEnvio(
        operacionId: 'b',
        tipo: TipoOperacion.reserva,
        sucursalId: 1,
        fechaOperacion: DateTime.utc(2026, 1, 2),
        payload: const {},
      );
      final ids = [for (final o in LoteEnvio(operaciones: [a, b]).toJson()['operaciones'] as List) (o as Map)['operacion_id']];
      expect(ids, ['a', 'b']);
    });

    test('se puede serializar a texto JSON', () {
      final texto = jsonEncode(LoteEnvio(dispositivo: 'd', operaciones: [OperacionEnvio.desde(_fila())]).toJson());
      expect(jsonDecode(texto), isA<Map>());
    });
  });

  group('totalCentavosDe y LineaVenta', () {
    test('suma (precio − descuento) × cantidad de cada línea', () {
      const lineas = [
        LineaVenta(varianteId: 1, cantidad: 2, precioUnitarioCentavos: 7500),
        LineaVenta(varianteId: 2, cantidad: 3, precioUnitarioCentavos: 5000, descuentoUnitarioCentavos: 500),
      ];
      expect(totalCentavosDe(lineas), 15000 + 13500);
    });

    test('sin líneas el total es 0', () {
      expect(totalCentavosDe(const []), 0);
    });

    test('el subtotal de una línea con descuento', () {
      const l = LineaVenta(varianteId: 1, cantidad: 4, precioUnitarioCentavos: 1000, descuentoUnitarioCentavos: 250);
      expect(l.subtotalCentavos, 3000);
    });

    test('un descuento igual al precio deja la línea en 0', () {
      const l = LineaVenta(varianteId: 1, cantidad: 4, precioUnitarioCentavos: 1000, descuentoUnitarioCentavos: 1000);
      expect(l.subtotalCentavos, 0);
    });

    test('con centavos sueltos no hay error de redondeo (0,10 + 0,20 = 0,30)', () {
      const lineas = [
        LineaVenta(varianteId: 1, cantidad: 1, precioUnitarioCentavos: 10),
        LineaVenta(varianteId: 2, cantidad: 1, precioUnitarioCentavos: 20),
      ];
      expect(totalCentavosDe(lineas), 30);
    });
  });

  group('payloadVentaContado', () {
    const lineas = [
      LineaVenta(varianteId: 100, cantidad: 2, precioUnitarioCentavos: 7500),
      LineaVenta(varianteId: 101, cantidad: 1, precioUnitarioCentavos: 5000, descuentoUnitarioCentavos: 500),
    ];
    final total = totalCentavosDe(lineas); // 15000 + 4500 = 19500

    test('con cliente: el payload exacto', () {
      expect(payloadVentaContado(clienteServidorId: 501, lineas: lineas, totalCentavos: total), {
        'cliente_id': 501,
        'lineas': [
          {'variante_id': 100, 'cantidad': 2, 'precio_unitario': '75.00', 'descuento_unitario': '0.00'},
          {'variante_id': 101, 'cantidad': 1, 'precio_unitario': '50.00', 'descuento_unitario': '5.00'},
        ],
        'total': '195.00',
        'pago': {'metodo': 'efectivo', 'monto_recibido': '195.00'},
      });
    });

    test('sin cliente: no manda la clave cliente_id', () {
      final payload = payloadVentaContado(lineas: lineas, totalCentavos: total);
      expect(payload.containsKey('cliente_id'), isFalse);
      expect(payload.keys, unorderedEquals(['lineas', 'total', 'pago']));
    });

    test('el monto recibido es igual al total (el efectivo cubre la cuenta)', () {
      final payload = payloadVentaContado(lineas: lineas, totalCentavos: total);
      expect((payload['pago']! as Map)['monto_recibido'], payload['total']);
      expect((payload['pago']! as Map)['metodo'], 'efectivo');
    });

    test('los montos son TEXTO con dos decimales, nunca números', () {
      final payload = payloadVentaContado(lineas: lineas, totalCentavos: total);
      expect(payload['total'], isA<String>());
      for (final l in payload['lineas']! as List) {
        expect((l as Map)['precio_unitario'], isA<String>());
        expect(l['descuento_unitario'], isA<String>());
      }
    });

    test('el descuento viaja por línea y el total ya lo descuenta', () {
      final payload = payloadVentaContado(
        lineas: const [LineaVenta(varianteId: 1, cantidad: 3, precioUnitarioCentavos: 1000, descuentoUnitarioCentavos: 100)],
        totalCentavos: 2700,
      );
      expect(((payload['lineas']! as List).first as Map)['descuento_unitario'], '1.00');
      expect(payload['total'], '27.00');
    });

    test('centavos sueltos: 5 centavos se escriben "0.05"', () {
      final payload = payloadVentaContado(
        lineas: const [LineaVenta(varianteId: 1, cantidad: 1, precioUnitarioCentavos: 5)],
        totalCentavos: 5,
      );
      expect(payload['total'], '0.05');
    });

    test('el JSON resultante se puede codificar y volver a leer igual', () {
      final payload = payloadVentaContado(clienteServidorId: 9, lineas: lineas, totalCentavos: total);
      expect(jsonDecode(jsonEncode(payload)), payload);
    });
  });

  group('payloadReserva', () {
    const lineas = [LineaReserva(varianteId: 100, cantidad: 2), LineaReserva(varianteId: 101, cantidad: 1)];

    test('el payload exacto con observación', () {
      expect(
        payloadReserva(
          clienteServidorId: 501,
          fechaVisita: DateTime(2026, 11, 2),
          horaDesde: '10:00',
          horaHasta: '11:30',
          observacion: '  Viene con su hijo  ',
          lineas: lineas,
        ),
        {
          'cliente_id': 501,
          'fecha_visita': '2026-11-02',
          'hora_visita_desde': '10:00',
          'hora_visita_hasta': '11:30',
          'observacion': 'Viene con su hijo',
          'lineas': [
            {'variante_id': 100, 'cantidad': 2},
            {'variante_id': 101, 'cantidad': 1},
          ],
        },
      );
    });

    test('sin observación (null, vacía o solo espacios) no manda la clave', () {
      for (final obs in [null, '', '   ']) {
        final p = payloadReserva(
          clienteServidorId: 1,
          fechaVisita: DateTime(2026, 11, 2),
          horaDesde: '10:00',
          horaHasta: '11:00',
          observacion: obs,
          lineas: lineas,
        );
        expect(p.containsKey('observacion'), isFalse, reason: 'obs=$obs');
      }
    });

    test('la fecha lleva ceros: "2026-01-05"', () {
      final p = payloadReserva(
        clienteServidorId: 1,
        fechaVisita: DateTime(2026, 1, 5),
        horaDesde: '09:00',
        horaHasta: '10:00',
        lineas: lineas,
      );
      expect(p['fecha_visita'], '2026-01-05');
    });

    test('las líneas solo llevan variante y cantidad (sin precios)', () {
      final p = payloadReserva(
        clienteServidorId: 1,
        fechaVisita: DateTime(2026, 11, 2),
        horaDesde: '09:00',
        horaHasta: '10:00',
        lineas: lineas,
      );
      for (final l in p['lineas']! as List) {
        expect((l as Map).keys, unorderedEquals(['variante_id', 'cantidad']));
      }
    });
  });

  group('EstadoResultadoSync', () {
    test('desdeNombre reconoce los estados del servidor', () {
      expect(EstadoResultadoSync.desdeNombre('confirmada'), EstadoResultadoSync.confirmada);
      expect(EstadoResultadoSync.desdeNombre('rechazada'), EstadoResultadoSync.rechazada);
      expect(EstadoResultadoSync.desdeNombre('en_conflicto'), EstadoResultadoSync.enConflicto);
      expect(EstadoResultadoSync.desdeNombre('error_temporal'), EstadoResultadoSync.errorTemporal);
    });

    test('un estado desconocido, vacío o nulo es "desconocido"', () {
      expect(EstadoResultadoSync.desdeNombre('algo_nuevo'), EstadoResultadoSync.desconocido);
      expect(EstadoResultadoSync.desdeNombre(''), EstadoResultadoSync.desconocido);
      expect(EstadoResultadoSync.desdeNombre(null), EstadoResultadoSync.desconocido);
    });

    test('aEstadoLocal', () {
      expect(EstadoResultadoSync.confirmada.aEstadoLocal, EstadoOperacion.confirmada);
      expect(EstadoResultadoSync.rechazada.aEstadoLocal, EstadoOperacion.rechazada);
      expect(EstadoResultadoSync.enConflicto.aEstadoLocal, EstadoOperacion.enConflicto);
      expect(EstadoResultadoSync.errorTemporal.aEstadoLocal, isNull);
      expect(EstadoResultadoSync.desconocido.aEstadoLocal, isNull);
    });
  });

  group('ResultadoOperacionSync.fromJson', () {
    // Un resultado con TODOS los campos reales del backend (backend/app/sincronizacion/schemas.py).
    final completo = <String, dynamic>{
      'operacion_id': 'AAAAAAAA-1111-4222-8333-BBBBBBBBBBBB',
      'estado': 'en_conflicto',
      'motivo': 'stock_insuficiente',
      'mensaje': 'No hay stock suficiente',
      'duplicada': true,
      'procesada_en': '2026-10-31T15:00:00Z',
      'recurso': {'tipo': 'venta', 'id': 77, 'codigo': 'V-000077', 'total': '195.00'},
      'cambio': '5.50',
      'avisos': [
        {'codigo': 'precio_distinto', 'variante_id': 100, 'precio_operacion': '75.00', 'precio_actual': '80.00'},
      ],
      'faltantes': [
        {'variante_id': 101, 'solicitado': 3, 'disponible': 1},
      ],
      'resolucion': {
        'accion': 'rechazar',
        'por_usuario_id': 4,
        'en': '2026-10-31T16:00:00Z',
        'motivo': 'Sin stock',
        'ajustes': [
          {'variante_id': 101, 'cantidad': 2, 'movimiento_id': 9},
        ],
      },
    };

    test('lee todos los campos', () {
      final r = ResultadoOperacionSync.fromJson(completo);
      expect(r.operacionId, 'aaaaaaaa-1111-4222-8333-bbbbbbbbbbbb', reason: 'siempre en minúscula');
      expect(r.estado, EstadoResultadoSync.enConflicto);
      expect(r.motivo, 'stock_insuficiente');
      expect(r.mensaje, 'No hay stock suficiente');
      expect(r.duplicada, isTrue);
      expect(r.procesadaEn, DateTime.utc(2026, 10, 31, 15));
      expect(r.recurso!.tipo, 'venta');
      expect(r.recurso!.id, 77);
      expect(r.recurso!.codigo, 'V-000077');
      expect(r.recurso!.totalCentavos, 19500);
      expect(r.cambioCentavos, 550);
      expect(r.avisos, hasLength(1));
      expect(r.avisos.single.varianteId, 100);
      expect(r.avisos.single.precioOperacionCentavos, 7500);
      expect(r.avisos.single.precioActualCentavos, 8000);
      expect(r.faltantes.single.varianteId, 101);
      expect(r.faltantes.single.solicitado, 3);
      expect(r.faltantes.single.disponible, 1);
      expect(r.resolucion!.accion, 'rechazar');
      expect(r.resolucion!.motivo, 'Sin stock');
    });

    test('un resultado mínimo (solo id y estado) no rompe y deja lo demás vacío', () {
      final r = ResultadoOperacionSync.fromJson({'operacion_id': 'abc', 'estado': 'confirmada'});
      expect(r.estado, EstadoResultadoSync.confirmada);
      expect(r.motivo, isNull);
      expect(r.mensaje, isNull);
      expect(r.duplicada, isFalse);
      expect(r.procesadaEn, isNull);
      expect(r.recurso, isNull);
      expect(r.cambioCentavos, isNull);
      expect(r.avisos, isEmpty);
      expect(r.faltantes, isEmpty);
      expect(r.resolucion, isNull);
    });

    test('un JSON vacío da una operación sin id y estado desconocido', () {
      final r = ResultadoOperacionSync.fromJson(const {});
      expect(r.operacionId, '');
      expect(r.estado, EstadoResultadoSync.desconocido);
    });

    test('ignora los campos nuevos que la app no conoce', () {
      final r = ResultadoOperacionSync.fromJson({
        'operacion_id': 'abc',
        'estado': 'rechazada',
        'campo_del_futuro': {'x': 1},
        'recurso': {'tipo': 'venta', 'id': 1, 'codigo': 'V1', 'otro': 'dato'},
        'avisos': [
          {'variante_id': 1, 'precio_operacion': '1.00', 'precio_actual': '2.00', 'extra': true},
        ],
      });
      expect(r.estado, EstadoResultadoSync.rechazada);
      expect(r.recurso!.id, 1);
      expect(r.avisos, hasLength(1));
    });

    test('estados desconocidos no rompen', () {
      final r = ResultadoOperacionSync.fromJson({'operacion_id': 'abc', 'estado': 'en_revision'});
      expect(r.estado, EstadoResultadoSync.desconocido);
      expect(r.estado.aEstadoLocal, isNull);
    });

    test('campos con la forma equivocada se toleran: cambio basura, avisos que no son lista, recurso que no es mapa', () {
      final r = ResultadoOperacionSync.fromJson({
        'operacion_id': 'abc',
        'estado': 'confirmada',
        'cambio': 'no-es-un-monto',
        'avisos': 'nada',
        'faltantes': 5,
        'recurso': 'x',
        'resolucion': [],
        'procesada_en': 'ayer',
      });
      expect(r.cambioCentavos, isNull);
      expect(r.avisos, isEmpty);
      expect(r.faltantes, isEmpty);
      expect(r.recurso, isNull);
      expect(r.resolucion, isNull);
      expect(r.procesadaEn, isNull);
    });

    test('elementos de las listas que no son mapas se saltan', () {
      final r = ResultadoOperacionSync.fromJson({
        'operacion_id': 'abc',
        'estado': 'en_conflicto',
        'faltantes': [
          'basura',
          {'variante_id': 2, 'solicitado': 5, 'disponible': 0},
        ],
      });
      expect(r.faltantes, hasLength(1));
      expect(r.faltantes.single.varianteId, 2);
    });

    test('procesada_en sin zona se toma como UTC', () {
      final r = ResultadoOperacionSync.fromJson({'operacion_id': 'a', 'estado': 'confirmada', 'procesada_en': '2026-10-31T15:00:00'});
      expect(r.procesadaEn, DateTime.utc(2026, 10, 31, 15));
      expect(r.procesadaEn!.isUtc, isTrue);
    });

    test('procesada_en con otra zona se pasa a UTC', () {
      final r = ResultadoOperacionSync.fromJson({
        'operacion_id': 'a',
        'estado': 'confirmada',
        'procesada_en': '2026-10-31T11:00:00-04:00',
      });
      expect(r.procesadaEn, DateTime.utc(2026, 10, 31, 15));
    });

    test('recurso sin total deja totalCentavos en null (una reserva)', () {
      final r = ResultadoOperacionSync.fromJson({
        'operacion_id': 'a',
        'estado': 'confirmada',
        'recurso': {'tipo': 'reserva', 'id': 3, 'codigo': 'R-3', 'fecha_expiracion': '2026-11-01T00:00:00Z'},
      });
      expect(r.recurso!.tipo, 'reserva');
      expect(r.recurso!.totalCentavos, isNull);
    });

    test('un monto numérico (no texto) también se entiende', () {
      final r = ResultadoOperacionSync.fromJson({'operacion_id': 'a', 'estado': 'confirmada', 'cambio': 2.5});
      expect(r.cambioCentavos, 250);
    });

    test('un monto negativo se toma como ausente', () {
      final r = ResultadoOperacionSync.fromJson({'operacion_id': 'a', 'estado': 'confirmada', 'cambio': '-1.00'});
      expect(r.cambioCentavos, isNull);
    });

    test('resolución sin motivo', () {
      final r = ResultadoOperacionSync.fromJson({
        'operacion_id': 'a',
        'estado': 'confirmada',
        'resolucion': {'accion': 'forzar'},
      });
      expect(r.resolucion!.accion, 'forzar');
      expect(r.resolucion!.motivo, isNull);
    });
  });

  group('RespuestaLote.fromJson', () {
    Map<String, dynamic> lote({Object? version = '1.0', Object? resultados}) => {
      'version_contrato': version,
      'procesado_en': '2026-10-31T15:00:00Z',
      'resumen': {'total': 2},
      'resultados':
          resultados ??
          [
            {'operacion_id': 'a', 'estado': 'confirmada'},
            {'operacion_id': 'b', 'estado': 'rechazada', 'motivo': 'fecha_futura'},
          ],
    };

    test('lee la versión, la hora del servidor y los resultados', () {
      final r = RespuestaLote.fromJson(lote());
      expect(r.versionContrato, '1.0');
      expect(r.procesadoEn, DateTime.utc(2026, 10, 31, 15));
      expect(r.resultados, hasLength(2));
      expect(r.resultados[1].motivo, 'fecha_futura');
    });

    test('una versión mayor lanza ErrorApp "Actualiza la app para sincronizar."', () {
      expect(
        () => RespuestaLote.fromJson(lote(version: '2.0')),
        throwsA(
          isA<ErrorApp>()
              .having((e) => e.mensaje, 'mensaje', 'Actualiza la app para sincronizar.')
              .having((e) => e.tipo, 'tipo', TipoErrorApp.desconocido),
        ),
      );
    });

    test('versión "2", 2 (número) y "10.1" también son mayores', () {
      for (final v in ['2', 2, '10.1', 3.0]) {
        expect(() => RespuestaLote.fromJson(lote(version: v)), throwsA(isA<ErrorApp>()), reason: 'version=$v');
      }
    });

    test('la misma versión mayor con otro menor ("1.7") sigue valiendo', () {
      expect(RespuestaLote.fromJson(lote(version: '1.7')).resultados, hasLength(2));
    });

    test('sin versión se acepta (lector tolerante) y queda la actual', () {
      final r = RespuestaLote.fromJson({
        'resultados': [
          {'operacion_id': 'a', 'estado': 'confirmada'},
        ],
      });
      expect(r.versionContrato, '1.0');
      expect(r.resultados, hasLength(1));
    });

    test('sin resultados o con resultados que no son lista queda vacío', () {
      expect(RespuestaLote.fromJson({'version_contrato': '1.0'}).resultados, isEmpty);
      expect(RespuestaLote.fromJson(lote(resultados: 'x')).resultados, isEmpty);
    });

    test('elementos que no son mapas se saltan', () {
      final r = RespuestaLote.fromJson(
        lote(
          resultados: [
            3,
            {'operacion_id': 'a', 'estado': 'confirmada'},
          ],
        ),
      );
      expect(r.resultados, hasLength(1));
    });

    test('procesado_en ausente queda en null', () {
      expect(RespuestaLote.fromJson({'version_contrato': '1.0', 'resultados': []}).procesadoEn, isNull);
    });
  });
}
