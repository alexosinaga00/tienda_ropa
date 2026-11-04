import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/features/catalogo/state/catalogo_providers.dart';
import 'package:mobile/features/catalogo/data/catalogo_repository.dart';
import 'package:mobile/features/compras/data/solicitudes_cambio_repository.dart';
import 'package:mobile/features/compras/models/solicitud_cambio.dart';
import 'package:mobile/features/compras/models/venta.dart';
import 'package:mobile/features/compras/state/compras_providers.dart';

import '../../helpers/api_client_falso.dart';

Map<String, dynamic> _json({String estado = 'pendiente', String? motivoRechazo, String? resueltaEn}) => {
  'id': 11,
  'codigo': 'SOL-0011',
  'venta_id': 7,
  'venta_codigo': 'V-0007',
  'sucursal_id': 2,
  'cliente_nombre': 'Ana Pérez',
  'fecha': '2026-11-04T15:00:00Z',
  'estado': estado,
  'motivo': 'Me queda grande',
  'motivo_rechazo': motivoRechazo,
  'resuelta_en': resueltaEn,
  'atender_hasta': '2026-11-07T15:00:00Z',
  'detalle': [
    {
      'venta_detalle_id': 1,
      'cantidad': 2,
      'variante_devuelta_id': 3,
      'prenda_devuelta': 'Polera Nike · talla M · Blanco',
      'variante_nueva_id': 4,
      'prenda_nueva': 'Polera Nike · talla L · Blanco',
      'disponible_nueva': 5,
    },
  ],
  'correo_programado': true,
};

void main() {
  group('SolicitudCambio', () {
    test('lee el contrato del servidor y pasa las fechas de UTC a hora local', () {
      final s = SolicitudCambio.fromJson(_json());

      expect(s.id, 11);
      expect(s.codigo, 'SOL-0011');
      expect(s.ventaId, 7);
      expect(s.ventaCodigo, 'V-0007');
      expect(s.sucursalId, 2);
      expect(s.clienteNombre, 'Ana Pérez');
      expect(s.motivo, 'Me queda grande');
      expect(s.fecha.toUtc(), DateTime.utc(2026, 11, 4, 15));
      expect(s.atenderHasta.toUtc(), DateTime.utc(2026, 11, 7, 15));
      expect(s.resueltaEn, isNull);
      expect(s.correoProgramado, isTrue);
      expect(s.detalle.single.cantidad, 2);
      expect(s.detalle.single.prendaDevuelta, 'Polera Nike · talla M · Blanco');
      expect(s.detalle.single.prendaNueva, 'Polera Nike · talla L · Blanco');
      expect(s.detalle.single.varianteNuevaId, 4);
      expect(s.detalle.single.disponibleNueva, 5);
    });

    test('solo la pendiente está pendiente y cada estado tiene su etiqueta', () {
      expect(SolicitudCambio.fromJson(_json()).estaPendiente, isTrue);
      const etiquetas = {
        'pendiente': 'Pendiente',
        'aprobada': 'Aprobada',
        'rechazada': 'Rechazada',
        'cancelada': 'Cancelada',
        'vencida': 'Vencida',
      };
      etiquetas.forEach((estado, etiqueta) {
        final s = SolicitudCambio.fromJson(_json(estado: estado));
        expect(s.etiquetaEstado, etiqueta);
        expect(s.estaPendiente, estado == 'pendiente');
      });
    });

    test('una resuelta trae su fecha y el motivo del rechazo', () {
      final s = SolicitudCambio.fromJson(
        _json(estado: 'rechazada', motivoRechazo: 'La prenda llegó usada', resueltaEn: '2026-11-04T16:00:00Z'),
      );

      expect(s.motivoRechazo, 'La prenda llegó usada');
      expect(s.resueltaEn!.toUtc(), DateTime.utc(2026, 11, 4, 16));
    });

    test('LineaSolicitudCambio arma el cuerpo que espera el servidor', () {
      const linea = LineaSolicitudCambio(ventaDetalleId: 1, cantidad: 2, varianteNuevaId: 4);

      expect(linea.toJson(), {'venta_detalle_id': 1, 'cantidad': 2, 'variante_nueva_id': 4});
    });
  });

  group('SolicitudesCambioRepository', () {
    late ApiClientFalso api;
    late SolicitudesCambioRepository repositorio;

    setUp(() {
      api = ApiClientFalso();
      repositorio = SolicitudesCambioRepository(api);
    });

    test('solicitar manda la compra, el motivo y todas las prendas en una sola petición', () async {
      api.responder('POST', '/solicitudes-cambio', _json());

      final s = await repositorio.solicitar(
        ventaId: 7,
        motivo: '  Me queda grande ',
        lineas: const [
          LineaSolicitudCambio(ventaDetalleId: 1, cantidad: 2, varianteNuevaId: 4),
          LineaSolicitudCambio(ventaDetalleId: 2, cantidad: 1, varianteNuevaId: 9),
        ],
      );

      expect(s.codigo, 'SOL-0011');
      final llamada = api.de('POST', '/solicitudes-cambio').single;
      expect(llamada.publica, isFalse); // exige sesión: la empresa sale del token
      expect(llamada.cuerpo, {
        'venta_id': 7,
        'motivo': 'Me queda grande',
        'detalle': [
          {'venta_detalle_id': 1, 'cantidad': 2, 'variante_nueva_id': 4},
          {'venta_detalle_id': 2, 'cantidad': 1, 'variante_nueva_id': 9},
        ],
      });
    });

    test('sin motivo no manda el campo', () async {
      api.responder('POST', '/solicitudes-cambio', _json());

      await repositorio.solicitar(
        ventaId: 7,
        motivo: '   ',
        lineas: const [LineaSolicitudCambio(ventaDetalleId: 1, cantidad: 1, varianteNuevaId: 4)],
      );

      expect((api.de('POST', '/solicitudes-cambio').single.cuerpo! as Map).containsKey('motivo'), isFalse);
    });

    test('misSolicitudes filtra por compra, o trae todas', () async {
      api.responder('GET', '/solicitudes-cambio/mias', [_json()]);

      final deLaCompra = await repositorio.misSolicitudes(ventaId: 7);
      final todas = await repositorio.misSolicitudes();

      expect(deLaCompra.single.ventaId, 7);
      expect(todas, hasLength(1));
      final llamadas = api.de('GET', '/solicitudes-cambio/mias');
      expect(llamadas[0].query, {'venta_id': 7});
      expect(llamadas[1].query, isEmpty);
    });

    test('cancelar usa la ruta de la solicitud', () async {
      api.responder('POST', '/solicitudes-cambio/11/cancelar', _json(estado: 'cancelada'));

      final s = await repositorio.cancelar(11);

      expect(s.estado, 'cancelada');
      expect(api.de('POST', '/solicitudes-cambio/11/cancelar'), hasLength(1));
    });

    test('los errores del servidor llegan tal cual (409, 429, 400)', () async {
      const conflicto = ErrorApp(
        tipo: TipoErrorApp.conflicto,
        mensaje: 'Ya tienes una solicitud de cambio pendiente para esa prenda',
        estado: 409,
      );
      api.responder('POST', '/solicitudes-cambio', conflicto);

      await expectLater(
        repositorio.solicitar(
          ventaId: 7,
          lineas: const [LineaSolicitudCambio(ventaDetalleId: 1, cantidad: 1, varianteNuevaId: 4)],
        ),
        throwsA(isA<ErrorApp>().having((e) => e.estado, 'estado', 409)),
      );
    });
  });

  group('opcionesCambioProvider: las otras tallas del mismo producto y precio, con stock', () {
    Map<String, dynamic> variante(int id, {double precio = 100, int? disponible = 5}) => {
      'id': id,
      'talla_id': id,
      'color_id': 1,
      'sku': 'SKU-$id',
      'precio_efectivo': precio.toStringAsFixed(2),
      'cantidad_disponible': disponible,
    };

    Venta venta({int? sucursalId = 2}) => Venta(
      id: 7,
      codigo: 'V-0007',
      estado: 'pagada',
      fecha: DateTime(2026, 11, 4),
      subtotal: 200,
      descuento: 0,
      costoEnvio: 0,
      total: 200,
      sucursalId: sucursalId,
      detalle: const [VentaLinea(id: 1, varianteId: 3, cantidad: 2, precioUnitario: 100, subtotal: 200)],
    );

    ProviderContainer contenedor(ApiClientFalso api, Venta compra) {
      final c = ProviderContainer(
        overrides: [
          compraDetalleProvider(7).overrideWith((ref) async => compra),
          catalogoRepositoryProvider.overrideWithValue(CatalogoRepository(api)),
        ],
      );
      addTearDown(c.dispose);
      return c;
    }

    // La variante comprada tal como la devuelve el catálogo (para saber su producto).
    const compradaEnCatalogo = {
      'variante_id': 3,
      'producto_id': 50,
      'producto_nombre': 'Polera Nike',
      'talla_codigo': 'M',
      'color_nombre': 'Blanco',
    };

    void prepararCatalogo(ApiClientFalso api, List<Map<String, dynamic>> variantes) {
      // La primera consulta resuelve la variante comprada; la segunda, los nombres de todas las del producto.
      api.responder('GET', '/catalogo/variantes/detalle', [compradaEnCatalogo]);
      api.responder('GET', '/catalogo/variantes/detalle', [
        for (final v in variantes)
          {
            'variante_id': v['id'],
            'producto_id': 50,
            'producto_nombre': 'Polera Nike',
            'talla_codigo': 'T${v['id']}',
            'color_nombre': 'Blanco',
          },
      ]);
      api.responder('GET', '/catalogo/50', {
        'id': 50,
        'codigo': 'POL-1',
        'nombre': 'Polera Nike',
        'descripcion': null,
        'categoria_id': 1,
        'material_id': null,
        'temporada_id': null,
        'coleccion_id': null,
        'genero': 'unisex',
        'precio_base': '100.00',
        'admite_probador': false,
        'variantes': variantes,
        'imagenes': <Map<String, dynamic>>[],
      });
    }

    test('ofrece solo lo del mismo precio con stock, nunca la misma, y pide el stock de la sucursal', () async {
      final api = ApiClientFalso();
      prepararCatalogo(api, [
        variante(3), // la que compró
        variante(4, disponible: 3), // sirve
        variante(5, precio: 120), // otro precio
        variante(6, disponible: 0), // sin stock
        variante(7, disponible: null), // no se sabe el stock
      ]);

      final opciones = await contenedor(api, venta()).read(opcionesCambioProvider(7).future);

      expect(opciones.keys, [1]);
      expect(opciones[1]!.map((o) => o.varianteId), [4]);
      expect(opciones[1]!.single.etiqueta, 'T4 · Blanco');
      expect(opciones[1]!.single.disponible, 3);
      final detalle = api.de('GET', '/catalogo/50').single;
      expect(detalle.publica, isTrue);
      expect(detalle.query, {'sucursal_id': 2});
    });

    test('una compra sin sucursal no ofrece nada (no se sabe el stock)', () async {
      final api = ApiClientFalso();
      api.responder('GET', '/catalogo/variantes/detalle', [compradaEnCatalogo]);

      final opciones = await contenedor(api, venta(sucursalId: null)).read(opcionesCambioProvider(7).future);

      expect(opciones, isEmpty);
      expect(api.de('GET', '/catalogo/50'), isEmpty);
    });
  });
}
