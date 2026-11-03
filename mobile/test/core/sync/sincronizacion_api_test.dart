import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/sync/contrato_sync.dart';
import 'package:mobile/core/sync/operacion_pendiente.dart';
import 'package:mobile/core/sync/sincronizacion_api.dart';

import '../../helpers/api_client_falso.dart';

const _id = '3f2b8c1e-5d4a-4b7c-9e01-2a6f8d3c4b5a';

LoteEnvio _lote({String? dispositivo = 'disp-1'}) => LoteEnvio(
  dispositivo: dispositivo,
  operaciones: [
    OperacionEnvio(
      operacionId: _id,
      tipo: TipoOperacion.ventaContado,
      sucursalId: 3,
      fechaOperacion: DateTime.utc(2026, 10, 31, 9, 30),
      payload: {
        'lineas': [
          {'variante_id': 5, 'cantidad': 2, 'precio_unitario': '75.00', 'descuento_unitario': '0.00'},
        ],
        'total': '150.00',
        'pago': {'metodo': 'efectivo', 'monto_recibido': '150.00'},
      },
    ),
  ],
);

Map<String, dynamic> _respuestaServidor() => {
  'version_contrato': '1.0',
  'procesado_en': '2026-10-31T12:00:05Z',
  'resumen': {'total': 1, 'confirmadas': 1, 'rechazadas': 0, 'en_conflicto': 0, 'errores_temporales': 0, 'duplicadas': 0},
  'resultados': [
    {
      'operacion_id': _id.toUpperCase(),
      'estado': 'confirmada',
      'motivo': null,
      'mensaje': null,
      'duplicada': true,
      'procesada_en': '2026-10-31T12:00:04',
      'recurso': {'tipo': 'venta', 'id': 41, 'codigo': 'V-000041', 'total': '150.00'},
      'cambio': '0.00',
      'avisos': [
        {'codigo': 'precio_distinto', 'variante_id': 5, 'precio_operacion': '75.00', 'precio_actual': '80.50'},
      ],
      'faltantes': [
        {'variante_id': 6, 'solicitado': 3, 'disponible': 1},
      ],
    },
  ],
};

void main() {
  late ApiClientFalso cliente;
  late SincronizacionApiHttp api;

  setUp(() {
    cliente = ApiClientFalso();
    api = SincronizacionApiHttp(cliente);
  });

  group('enviarLote', () {
    test('hace POST a /sincronizacion/lote, una sola vez y con sesión (no pública)', () async {
      cliente.responder('POST', '/sincronizacion/lote', _respuestaServidor());

      await api.enviarLote(_lote());

      final llamadas = cliente.de('POST', '/sincronizacion/lote');
      expect(llamadas, hasLength(1));
      expect(llamadas.single.publica, isFalse);
      expect(cliente.llamadas, hasLength(1));
    });

    test('el cuerpo es exactamente el contrato 1.0 (montos como texto, fechas con Z, sin empresa ni usuario)', () async {
      cliente.responder('POST', '/sincronizacion/lote', _respuestaServidor());

      await api.enviarLote(_lote());

      expect(cliente.llamadas.single.cuerpo, {
        'version_contrato': '1.0',
        'dispositivo': 'disp-1',
        'operaciones': [
          {
            'operacion_id': _id,
            'tipo': 'venta_contado',
            'sucursal_id': 3,
            'fecha_operacion': '2026-10-31T09:30:00Z',
            'payload': {
              'lineas': [
                {'variante_id': 5, 'cantidad': 2, 'precio_unitario': '75.00', 'descuento_unitario': '0.00'},
              ],
              'total': '150.00',
              'pago': {'metodo': 'efectivo', 'monto_recibido': '150.00'},
            },
          },
        ],
      });
    });

    test('sin dispositivo, la clave no viaja', () async {
      cliente.responder('POST', '/sincronizacion/lote', _respuestaServidor());

      await api.enviarLote(_lote(dispositivo: null));

      expect((cliente.llamadas.single.cuerpo! as Map).containsKey('dispositivo'), isFalse);
    });

    test('una reserva viaja con su tipo', () async {
      cliente.responder('POST', '/sincronizacion/lote', _respuestaServidor());
      final lote = LoteEnvio(
        operaciones: [
          OperacionEnvio(
            operacionId: _id,
            tipo: TipoOperacion.reserva,
            sucursalId: 1,
            fechaOperacion: DateTime.utc(2026, 10, 31),
            payload: const {'cliente_id': 3},
          ),
        ],
      );

      await api.enviarLote(lote);

      final operaciones = (cliente.llamadas.single.cuerpo! as Map)['operaciones'] as List;
      expect((operaciones.single as Map)['tipo'], 'reserva');
    });

    test('parsea la respuesta: estado, duplicada, hora del servidor, recurso, montos, avisos y faltantes', () async {
      cliente.responder('POST', '/sincronizacion/lote', _respuestaServidor());

      final respuesta = await api.enviarLote(_lote());

      expect(respuesta.versionContrato, '1.0');
      expect(respuesta.procesadoEn, DateTime.utc(2026, 10, 31, 12, 0, 5));
      final r = respuesta.resultados.single;
      expect(r.operacionId, _id, reason: 'el id se normaliza a minúscula');
      expect(r.estado, EstadoResultadoSync.confirmada);
      expect(r.duplicada, isTrue);
      expect(r.procesadaEn, DateTime.utc(2026, 10, 31, 12, 0, 4), reason: 'sin zona se toma como UTC');
      expect(r.recurso?.tipo, 'venta');
      expect(r.recurso?.id, 41);
      expect(r.recurso?.codigo, 'V-000041');
      expect(r.recurso?.totalCentavos, 15000);
      expect(r.cambioCentavos, 0);
      expect(r.avisos.single.precioOperacionCentavos, 7500);
      expect(r.avisos.single.precioActualCentavos, 8050);
      expect(r.faltantes.single.solicitado, 3);
      expect(r.faltantes.single.disponible, 1);
    });

    test('parsea los cuatro estados y uno desconocido', () async {
      cliente.responder('POST', '/sincronizacion/lote', {
        'version_contrato': '1.0',
        'resultados': [
          {'operacion_id': 'a', 'estado': 'confirmada'},
          {'operacion_id': 'b', 'estado': 'rechazada', 'motivo': 'variante_inactiva', 'mensaje': 'Inactiva'},
          {'operacion_id': 'c', 'estado': 'en_conflicto', 'motivo': 'stock_insuficiente'},
          {'operacion_id': 'd', 'estado': 'error_temporal'},
          {'operacion_id': 'e', 'estado': 'algo_nuevo'},
        ],
      });

      final r = (await api.enviarLote(_lote())).resultados;

      expect(r.map((x) => x.estado), [
        EstadoResultadoSync.confirmada,
        EstadoResultadoSync.rechazada,
        EstadoResultadoSync.enConflicto,
        EstadoResultadoSync.errorTemporal,
        EstadoResultadoSync.desconocido,
      ]);
      expect(r[1].motivo, 'variante_inactiva');
      expect(r[1].mensaje, 'Inactiva');
      expect(r[2].motivo, 'stock_insuficiente');
    });

    test('es tolerante: campos que faltan quedan en null y los nuevos se ignoran', () async {
      cliente.responder('POST', '/sincronizacion/lote', {
        'version_contrato': '1.0',
        'campo_nuevo': 123,
        'resultados': [
          {'operacion_id': _id, 'estado': 'confirmada', 'campo_futuro': true},
        ],
      });

      final respuesta = await api.enviarLote(_lote());

      expect(respuesta.procesadoEn, isNull);
      final r = respuesta.resultados.single;
      expect(r.recurso, isNull);
      expect(r.cambioCentavos, isNull);
      expect(r.avisos, isEmpty);
      expect(r.faltantes, isEmpty);
      expect(r.duplicada, isFalse);
    });

    test('un contrato más nuevo (2.0) lanza el error de actualizar la app', () async {
      cliente.responder('POST', '/sincronizacion/lote', {'version_contrato': '2.0', 'resultados': <Object>[]});

      await expectLater(
        api.enviarLote(_lote()),
        throwsA(isA<ErrorApp>().having((e) => e.mensaje, 'mensaje', 'Actualiza la app para sincronizar.')),
      );
    });

    test('los errores del cliente HTTP se propagan sin tocarlos', () async {
      const errores = [
        ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: 'Sin conexión', posiblementeRecibido: true),
        ErrorApp(tipo: TipoErrorApp.noAutorizado, mensaje: 'Sesión vencida', estado: 401),
        ErrorApp(tipo: TipoErrorApp.validacion, mensaje: 'Datos', estado: 422),
        ErrorApp(tipo: TipoErrorApp.servidor, mensaje: 'Servidor', estado: 503),
        ErrorApp(tipo: TipoErrorApp.suscripcionNoActiva, mensaje: 'Suscripción', estado: 403),
      ];
      for (final error in errores) {
        final c = ApiClientFalso()..responder('POST', '/sincronizacion/lote', error);

        await expectLater(
          SincronizacionApiHttp(c).enviarLote(_lote()),
          throwsA(same(error)),
          reason: '${error.tipo}',
        );
      }
    });
  });

  group('consultar', () {
    final ruta = '/sincronizacion/operaciones/$_id';

    test('hace GET a /sincronizacion/operaciones/{id}', () async {
      cliente.responder('GET', ruta, {'operacion_id': _id, 'estado': 'confirmada'});

      await api.consultar(_id);

      expect(cliente.de('GET', ruta), hasLength(1));
      expect(cliente.llamadas.single.publica, isFalse);
    });

    test('parsea el detalle con los mismos campos del resultado', () async {
      cliente.responder('GET', ruta, {
        'operacion_id': _id,
        'tipo': 'venta_contado',
        'estado': 'rechazada',
        'motivo': 'stock_insuficiente',
        'mensaje': 'Un encargado la rechazó',
        'usuario_id': 10,
        'fecha_operacion': '2026-10-31T09:30:00Z',
        'recibida_en': '2026-10-31T10:00:00Z',
        'procesada_en': '2026-10-31T11:15:00Z',
        'resolucion': {'accion': 'rechazar', 'motivo': 'Se devolvió el efectivo'},
      });

      final r = await api.consultar(_id);

      expect(r, isNotNull);
      expect(r!.estado, EstadoResultadoSync.rechazada);
      expect(r.motivo, 'stock_insuficiente');
      expect(r.procesadaEn, DateTime.utc(2026, 10, 31, 11, 15));
      expect(r.resolucion?.accion, 'rechazar');
      expect(r.resolucion?.motivo, 'Se devolvió el efectivo');
    });

    test('devuelve null si el servidor no la conoce (404)', () async {
      cliente.responder('GET', ruta, const ErrorApp(tipo: TipoErrorApp.noEncontrado, mensaje: 'No encontramos', estado: 404));

      expect(await api.consultar(_id), isNull);
    });

    test('propaga los demás errores', () async {
      const errores = [
        ErrorApp(tipo: TipoErrorApp.servidor, mensaje: 'Servidor', estado: 500),
        ErrorApp(tipo: TipoErrorApp.noAutorizado, mensaje: 'Sesión', estado: 401),
        ErrorApp(tipo: TipoErrorApp.prohibido, mensaje: 'Prohibido', estado: 403),
        ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: 'Sin conexión'),
        ErrorApp(tipo: TipoErrorApp.planNoIncluyeFuncionalidad, mensaje: 'Plan', estado: 403),
      ];
      for (final error in errores) {
        final c = ApiClientFalso()..responder('GET', ruta, error);

        await expectLater(SincronizacionApiHttp(c).consultar(_id), throwsA(same(error)), reason: '${error.tipo}');
      }
    });

    test('el id va codificado en la ruta', () async {
      cliente.responder('GET', '/sincronizacion/operaciones/a%2Fb%20c', {'operacion_id': 'a/b c', 'estado': 'confirmada'});

      final r = await api.consultar('a/b c');

      expect(r?.estado, EstadoResultadoSync.confirmada);
    });
  });
}
