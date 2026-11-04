import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/utils/fecha_servidor.dart';
import 'package:mobile/features/compras/data/solicitudes_cambio_repository.dart';
import 'package:mobile/features/compras/models/plazo_cambio.dart';
import 'package:mobile/features/compras/models/solicitud_cambio.dart';
import 'package:mobile/features/compras/models/venta.dart';
import 'package:mobile/features/compras/presentation/compra_detalle_screen.dart';
import 'package:mobile/features/compras/presentation/mis_compras_screen.dart';
import 'package:mobile/features/compras/state/compras_providers.dart';
import 'package:mobile/features/compras/state/mis_compras_controller.dart';

import '../../helpers/solicitudes_cambio_falsas.dart';

Map<String, dynamic> _json({
  int id = 11,
  String estado = 'pendiente',
  int ventaDetalleId = 1,
  String? motivoRechazo,
  String? motivo = 'Me queda grande',
}) => {
  'id': id,
  'codigo': 'SOL-00$id',
  'venta_id': 7,
  'venta_codigo': 'V-0007',
  'sucursal_id': 2,
  'cliente_nombre': 'Ana Pérez',
  'fecha': '2026-11-04T15:00:00Z',
  'estado': estado,
  'motivo': motivo,
  'motivo_rechazo': motivoRechazo,
  'resuelta_en': null,
  'atender_hasta': '2026-11-07T15:00:00Z',
  'detalle': [
    {
      'venta_detalle_id': ventaDetalleId,
      'cantidad': 1,
      'variante_devuelta_id': 3,
      'prenda_devuelta': 'Polera Nike · talla M · Blanco',
      'variante_nueva_id': 4,
      'prenda_nueva': 'Polera Nike · talla L · Blanco',
      'disponible_nueva': 5,
    },
  ],
};

SolicitudCambio _solicitud({
  int id = 11,
  String estado = 'pendiente',
  int ventaDetalleId = 1,
  String? motivoRechazo,
  String? motivo = 'Me queda grande',
}) => SolicitudCambio.fromJson(
  _json(id: id, estado: estado, ventaDetalleId: ventaDetalleId, motivoRechazo: motivoRechazo, motivo: motivo),
);

/// Una compra de dos prendas distintas (la polera, que se compró 3 veces, y un pantalón).
Venta _venta({String estado = 'pagada', int devueltas = 0}) => Venta(
  id: 7,
  codigo: 'V-0007',
  estado: estado,
  fecha: DateTime(2026, 11, 4, 10),
  subtotal: 400,
  descuento: 0,
  costoEnvio: 0,
  total: 400,
  sucursalId: 2,
  unidadesDevueltas: devueltas,
  detalle: const [
    VentaLinea(
      id: 1,
      varianteId: 3,
      cantidad: 3,
      precioUnitario: 100,
      subtotal: 300,
      productoNombre: 'Polera Nike',
      tallaCodigo: 'M',
      colorNombre: 'Blanco',
    ),
    VentaLinea(
      id: 2,
      varianteId: 8,
      cantidad: 1,
      precioUnitario: 100,
      subtotal: 100,
      productoNombre: 'Pantalón Adidas',
      tallaCodigo: '32',
      colorNombre: 'Negro',
    ),
  ],
);

const _opciones = {
  1: [
    OpcionCambio(varianteId: 4, etiqueta: 'L · Blanco', disponible: 5),
    OpcionCambio(varianteId: 5, etiqueta: 'XL · Blanco', disponible: 1),
  ],
  2: [OpcionCambio(varianteId: 9, etiqueta: '34 · Negro', disponible: 2)],
};

PlazoCambio _plazo({required bool vigente}) =>
    PlazoCambio.fromJson({'vigente': vigente, 'vence_en': '2026-11-05T14:30:00Z', 'plazo_horas': 24});

/// Lo que el repositorio falso recibió y lo que debe fallar.
class _RepoFalso implements SolicitudesCambioRepository {
  final pedidos = <({int ventaId, List<LineaSolicitudCambio> lineas, String? motivo})>[];
  final cancelaciones = <int>[];
  Object? errorAlSolicitar;
  Object? errorAlCancelar;

  @override
  Future<SolicitudCambio> solicitar({
    required int ventaId,
    required List<LineaSolicitudCambio> lineas,
    String? motivo,
  }) async {
    if (errorAlSolicitar != null) throw errorAlSolicitar!;
    pedidos.add((ventaId: ventaId, lineas: lineas, motivo: motivo));
    return _solicitud(id: 21);
  }

  @override
  Future<List<SolicitudCambio>> misSolicitudes({int? ventaId}) async => const [];

  @override
  Future<SolicitudCambio> cancelar(int solicitudId) async {
    if (errorAlCancelar != null) throw errorAlCancelar!;
    cancelaciones.add(solicitudId);
    return _solicitud(id: solicitudId, estado: 'cancelada');
  }
}

Future<void> _abrir(
  WidgetTester tester, {
  required _RepoFalso repo,
  Venta? venta,
  PlazoCambio? plazo,
  Map<int, List<OpcionCambio>> opciones = _opciones,
  List<SolicitudCambio> solicitudes = const [],
  bool enLinea = true,
}) async {
  tester.view.physicalSize = const Size(800, 3200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final compra = venta ?? _venta();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        compraDetalleProvider(7).overrideWith((ref) async => compra),
        plazoCambioProvider(7).overrideWith((ref) async => plazo ?? _plazo(vigente: true)),
        envioDeCompraProvider(7).overrideWith((ref) async => null),
        nombreSucursalProvider(2).overrideWith((ref) async => 'Centro'),
        ...solicitudesCambioFalsas(7, solicitudes: solicitudes, opciones: opciones, enLinea: enLinea),
        solicitudesCambioRepositoryProvider.overrideWithValue(repo),
      ],
      child: const MaterialApp(home: CompraDetalleScreen(ventaId: 7)),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _elegir(WidgetTester tester, int lineaId, String opcion) async {
  await tester.tap(find.byKey(Key('cambiar-por-$lineaId')));
  await tester.pumpAndSettle();
  await tester.tap(find.text(opcion).last);
  await tester.pumpAndSettle();
}

Future<void> _enviar(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('enviar-solicitud-cambio')));
  await tester.pumpAndSettle();
}

String _error(WidgetTester tester) => tester.widget<Text>(find.byKey(const Key('error-solicitud-cambio'))).data!;

void main() {
  group('cuándo se ofrece pedir el cambio', () {
    testWidgets('una compra pagada dentro del plazo ofrece cambiar talla o color, prenda por prenda', (tester) async {
      await _abrir(tester, repo: _RepoFalso());

      expect(find.text('Cambiar talla o color'), findsOneWidget);
      // Cada prenda sale dos veces: en el comprobante y en el formulario.
      expect(find.text('Polera Nike'), findsNWidgets(2));
      expect(find.text('Pantalón Adidas'), findsNWidgets(2));
      expect(find.byKey(const Key('cambiar-por-1')), findsOneWidget);
      expect(find.byKey(const Key('cambiar-por-2')), findsOneWidget);
      expect(find.text('Solicitar cambio'), findsOneWidget);
    });

    testWidgets('pasado el plazo no se ofrece pedir el cambio', (tester) async {
      await _abrir(tester, repo: _RepoFalso(), plazo: _plazo(vigente: false));

      expect(find.text('Cambiar talla o color'), findsNothing);
      expect(find.byKey(const Key('enviar-solicitud-cambio')), findsNothing);
    });

    testWidgets('una compra pendiente de pago no se puede cambiar', (tester) async {
      await _abrir(tester, repo: _RepoFalso(), venta: _venta(estado: 'pendiente_pago'));

      expect(find.text('Cambiar talla o color'), findsNothing);
    });

    testWidgets('si ya se devolvió toda la compra no queda nada que cambiar', (tester) async {
      await _abrir(tester, repo: _RepoFalso(), venta: _venta(devueltas: 4));

      expect(find.text('Cambiar talla o color'), findsNothing);
    });

    testWidgets('sin otra talla o color con stock lo dice y no deja enviar', (tester) async {
      await _abrir(tester, repo: _RepoFalso(), opciones: const {});

      expect(find.text('No hay otra talla o color con stock para esta compra.'), findsOneWidget);
      expect(find.byKey(const Key('enviar-solicitud-cambio')), findsNothing);
    });

    testWidgets('solo ofrece las prendas que tienen otra talla disponible', (tester) async {
      await _abrir(tester, repo: _RepoFalso(), opciones: {1: _opciones[1]!});

      expect(find.byKey(const Key('cambiar-por-1')), findsOneWidget);
      expect(find.byKey(const Key('cambiar-por-2')), findsNothing);
    });

    testWidgets('sin conexión el botón queda deshabilitado y dice "Requiere conexión"', (tester) async {
      await _abrir(tester, repo: _RepoFalso(), enLinea: false);

      expect(find.text('Requiere conexión'), findsOneWidget);
      final boton = tester.widget<ElevatedButton>(find.byKey(const Key('enviar-solicitud-cambio')));
      expect(boton.onPressed, isNull);
    });

    testWidgets('con conexión no aparece el aviso de conexión', (tester) async {
      await _abrir(tester, repo: _RepoFalso());

      expect(find.text('Requiere conexión'), findsNothing);
    });

    testWidgets('el botón espera a que haya al menos una prenda elegida', (tester) async {
      await _abrir(tester, repo: _RepoFalso());
      ElevatedButton boton() => tester.widget<ElevatedButton>(find.byKey(const Key('enviar-solicitud-cambio')));

      expect(boton().onPressed, isNull);
      await _elegir(tester, 1, 'L · Blanco · quedan 5');
      expect(boton().onPressed, isNotNull);
    });
  });

  group('pedir el cambio', () {
    testWidgets('varias prendas en una sola solicitud, con el motivo, y avisa adónde llevarlas', (tester) async {
      final repo = _RepoFalso();
      await _abrir(tester, repo: repo);

      await _elegir(tester, 1, 'L · Blanco · quedan 5'); // elegir ya cuenta una unidad
      await tester.tap(find.byKey(const Key('mas-1')));
      await tester.pump();
      await _elegir(tester, 2, '34 · Negro · quedan 2');
      await tester.enterText(find.byKey(const Key('motivo-cambio')), '  Me quedan grandes ');
      await _enviar(tester);

      expect(repo.pedidos, hasLength(1));
      final pedido = repo.pedidos.single;
      expect(pedido.ventaId, 7);
      expect(pedido.motivo, '  Me quedan grandes ');
      expect(pedido.lineas.map((l) => l.toJson()), [
        {'venta_detalle_id': 1, 'cantidad': 2, 'variante_nueva_id': 4},
        {'venta_detalle_id': 2, 'cantidad': 1, 'variante_nueva_id': 9},
      ]);
      final hasta = formatearFechaHora(fechaDelServidor('2026-11-07T15:00:00Z'));
      expect(
        tester.widget<Text>(find.byKey(const Key('solicitud-enviada'))).data,
        'Solicitud SOL-0021 enviada. Lleva la prenda a la sucursal Centro antes del $hasta.',
      );
      // El formulario queda limpio para otro pedido.
      expect(tester.widget<ElevatedButton>(find.byKey(const Key('enviar-solicitud-cambio'))).onPressed, isNull);
      expect(tester.widget<TextField>(find.byKey(const Key('motivo-cambio'))).controller!.text, isEmpty);
    });

    testWidgets('las unidades se mueven entre 0 y lo que se compró', (tester) async {
      await _abrir(tester, repo: _RepoFalso());
      await _elegir(tester, 1, 'L · Blanco · quedan 5');

      for (var i = 0; i < 5; i++) {
        await tester.tap(find.byKey(const Key('mas-1')));
        await tester.pump();
      }
      expect(find.text('3'), findsWidgets); // se compraron 3: no pasa de ahí
      expect(tester.widget<IconButton>(find.byKey(const Key('mas-1'))).onPressed, isNull);

      for (var i = 0; i < 5; i++) {
        await tester.tap(find.byKey(const Key('menos-1')));
        await tester.pump();
      }
      expect(tester.widget<IconButton>(find.byKey(const Key('menos-1'))).onPressed, isNull);
    });

    testWidgets('pedir más unidades de las que quedan de esa talla se frena antes de enviar', (tester) async {
      final repo = _RepoFalso();
      await _abrir(tester, repo: repo);

      await _elegir(tester, 1, 'XL · Blanco · quedan 1');
      await tester.tap(find.byKey(const Key('mas-1')));
      await tester.pump();
      await _enviar(tester);

      expect(_error(tester), 'Solo quedan 1 de XL · Blanco. Pide menos unidades.');
      expect(repo.pedidos, isEmpty);
    });

    testWidgets('unidades sin talla elegida piden elegirla', (tester) async {
      final repo = _RepoFalso();
      await _abrir(tester, repo: repo);

      await tester.tap(find.byKey(const Key('mas-1')));
      await tester.pump();
      await _enviar(tester);

      expect(_error(tester), 'Elige la talla o el color nuevo de Polera Nike.');
      expect(repo.pedidos, isEmpty);
    });

    testWidgets('una prenda con una solicitud pendiente no se puede pedir otra vez', (tester) async {
      await _abrir(tester, repo: _RepoFalso(), solicitudes: [_solicitud(ventaDetalleId: 1)]);

      expect(find.text('Ya tienes una solicitud pendiente para esta prenda.'), findsOneWidget);
      expect(find.byKey(const Key('cambiar-por-1')), findsNothing);
      expect(find.byKey(const Key('cambiar-por-2')), findsOneWidget); // la otra prenda sí
    });
  });

  group('los errores del servidor se ven en la misma pantalla', () {
    const casos = {
      'ya hay una pendiente (409)': (
        ErrorApp(
          tipo: TipoErrorApp.conflicto,
          estado: 409,
          mensaje: 'Ya tienes una solicitud de cambio pendiente para esa prenda',
          detalle: 'Ya tienes una solicitud de cambio pendiente para esa prenda',
        ),
        'Ya tienes una solicitud de cambio pendiente para esa prenda',
      ),
      'demasiadas solicitudes (429)': (
        ErrorApp(
          tipo: TipoErrorApp.desconocido,
          estado: 429,
          mensaje: 'Hiciste muchas solicitudes de cambio. Intenta de nuevo más tarde.',
          detalle: 'Hiciste muchas solicitudes de cambio. Intenta de nuevo más tarde.',
        ),
        'Hiciste muchas solicitudes de cambio. Intenta de nuevo más tarde.',
      ),
      'cambio inválido (400)': (
        ErrorApp(
          tipo: TipoErrorApp.desconocido,
          estado: 400,
          mensaje: 'El cambio tiene diferencia de precio: todavía no se puede registrar',
          detalle: 'El cambio tiene diferencia de precio: todavía no se puede registrar',
        ),
        'El cambio tiene diferencia de precio: todavía no se puede registrar',
      ),
      'sin conexión': (
        ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: 'Sin conexión. Revisa tu internet e intenta de nuevo.'),
        'Requiere conexión. Revisa tu internet e intenta de nuevo.',
      ),
      'error inesperado': (
        ErrorApp(tipo: TipoErrorApp.servidor, estado: 500, mensaje: 'El servidor no pudo responder.'),
        'No se pudo enviar la solicitud. Intenta de nuevo.',
      ),
    };

    for (final entrada in casos.entries) {
      testWidgets(entrada.key, (tester) async {
        final repo = _RepoFalso()..errorAlSolicitar = entrada.value.$1;
        await _abrir(tester, repo: repo);

        await _elegir(tester, 1, 'L · Blanco · quedan 5');
        await _enviar(tester);

        expect(_error(tester), entrada.value.$2);
        expect(find.byKey(const Key('solicitud-enviada')), findsNothing);
        // Y se puede corregir y volver a intentar.
        expect(tester.widget<ElevatedButton>(find.byKey(const Key('enviar-solicitud-cambio'))).onPressed, isNotNull);
      });
    }
  });

  group('Tus solicitudes', () {
    testWidgets('cada una con su estado, sus prendas y el motivo del rechazo', (tester) async {
      await _abrir(
        tester,
        repo: _RepoFalso(),
        solicitudes: [
          _solicitud(id: 11, ventaDetalleId: 2),
          _solicitud(id: 12, estado: 'rechazada', motivoRechazo: 'La prenda llegó usada'),
          _solicitud(id: 13, estado: 'aprobada'),
          _solicitud(id: 14, estado: 'cancelada'),
          _solicitud(id: 15, estado: 'vencida'),
        ],
      );

      expect(find.text('Tus solicitudes'), findsOneWidget);
      for (final etiqueta in ['Pendiente', 'Rechazada', 'Aprobada', 'Cancelada', 'Vencida']) {
        expect(find.text(etiqueta), findsOneWidget, reason: etiqueta);
      }
      expect(find.text('Polera Nike · talla M · Blanco → Polera Nike · talla L · Blanco (x1)'), findsNWidgets(5));
      expect(find.text('Tu motivo: Me queda grande'), findsNWidgets(5));
      expect(find.text('Motivo del rechazo: La prenda llegó usada'), findsOneWidget);
      final hasta = formatearFechaHora(fechaDelServidor('2026-11-07T15:00:00Z'));
      expect(find.text('Llévala a la tienda antes del $hasta.'), findsOneWidget); // solo la pendiente
    });

    testWidgets('solo la pendiente se puede cancelar', (tester) async {
      await _abrir(
        tester,
        repo: _RepoFalso(),
        solicitudes: [_solicitud(id: 11, ventaDetalleId: 2), _solicitud(id: 13, estado: 'aprobada')],
      );

      expect(find.byKey(const Key('cancelar-solicitud-11')), findsOneWidget);
      expect(find.byKey(const Key('cancelar-solicitud-13')), findsNothing);
    });

    testWidgets('cancelar pide confirmar y manda la cancelación', (tester) async {
      final repo = _RepoFalso();
      await _abrir(tester, repo: repo, solicitudes: [_solicitud(id: 11, ventaDetalleId: 2)]);

      await tester.tap(find.byKey(const Key('cancelar-solicitud-11')));
      await tester.pumpAndSettle();
      expect(find.text('¿Cancelar la solicitud?'), findsOneWidget);
      await tester.tap(find.text('Sí, cancelar'));
      await tester.pumpAndSettle();

      expect(repo.cancelaciones, [11]);
      expect(find.text('Solicitud cancelada.'), findsOneWidget);
    });

    testWidgets('si se arrepiente en la confirmación no cancela nada', (tester) async {
      final repo = _RepoFalso();
      await _abrir(tester, repo: repo, solicitudes: [_solicitud(id: 11, ventaDetalleId: 2)]);

      await tester.tap(find.byKey(const Key('cancelar-solicitud-11')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('No'));
      await tester.pumpAndSettle();

      expect(repo.cancelaciones, isEmpty);
    });

    testWidgets('si el servidor no deja cancelar (ya la resolvieron) lo dice', (tester) async {
      final repo = _RepoFalso()
        ..errorAlCancelar = const ErrorApp(
          tipo: TipoErrorApp.conflicto,
          estado: 409,
          mensaje: 'La solicitud ya fue resuelta (estado: aprobada)',
          detalle: 'La solicitud ya fue resuelta (estado: aprobada)',
        );
      await _abrir(tester, repo: repo, solicitudes: [_solicitud(id: 11, ventaDetalleId: 2)]);

      await tester.tap(find.byKey(const Key('cancelar-solicitud-11')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Sí, cancelar'));
      await tester.pumpAndSettle();

      expect(find.text('La solicitud ya fue resuelta (estado: aprobada)'), findsOneWidget);
    });

    testWidgets('con el plazo vencido igual se ven las solicitudes que ya había', (tester) async {
      await _abrir(
        tester,
        repo: _RepoFalso(),
        plazo: _plazo(vigente: false),
        solicitudes: [_solicitud(id: 12, estado: 'rechazada', motivoRechazo: 'La prenda llegó usada')],
      );

      expect(find.text('Cambiar talla o color'), findsNothing);
      expect(find.text('Tus solicitudes'), findsOneWidget);
      expect(find.text('Motivo del rechazo: La prenda llegó usada'), findsOneWidget);
    });

    testWidgets('si no se pudieron cargar lo dice y deja reintentar, sin tapar el comprobante', (tester) async {
      tester.view.physicalSize = const Size(800, 3200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      var intentos = 0;
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            compraDetalleProvider(7).overrideWith((ref) async => _venta()),
            plazoCambioProvider(7).overrideWith((ref) async => _plazo(vigente: false)),
            envioDeCompraProvider(7).overrideWith((ref) async => null),
            nombreSucursalProvider(2).overrideWith((ref) async => 'Centro'),
            ...solicitudesCambioFalsas(7),
            misSolicitudesCambioProvider(7).overrideWith((ref) async {
              intentos++;
              if (intentos == 1) throw const ErrorApp(tipo: TipoErrorApp.servidor, mensaje: 'falló');
              return [_solicitud(ventaDetalleId: 2)];
            }),
          ],
          child: const MaterialApp(home: CompraDetalleScreen(ventaId: 7)),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('No se pudieron cargar tus solicitudes.'), findsOneWidget);
      expect(find.text('V-0007'), findsOneWidget);

      await tester.tap(find.text('Reintentar'));
      await tester.pumpAndSettle();

      expect(find.text('No se pudieron cargar tus solicitudes.'), findsNothing);
      expect(find.text('SOL-0011'), findsOneWidget);
    });
  });

  group('Mis compras: aviso de cambio pendiente', () {
    Widget lista({required Set<int> conPendiente}) => ProviderScope(
      overrides: [
        misComprasControllerProvider.overrideWith((ref) => _ComprasFalsas(ref, [_venta()])),
        comprasConCambioPendienteProvider.overrideWith((ref) async => conPendiente),
      ],
      child: const MaterialApp(home: MisComprasScreen()),
    );

    testWidgets('la compra con una solicitud pendiente lo dice', (tester) async {
      await tester.pumpWidget(lista(conPendiente: {7}));
      await tester.pumpAndSettle();

      expect(find.text('V-0007'), findsOneWidget);
      expect(find.byKey(const Key('chip-cambio-pendiente')), findsOneWidget);
      expect(find.text('Cambio pendiente'), findsOneWidget);
    });

    testWidgets('sin solicitud pendiente no dice nada', (tester) async {
      await tester.pumpWidget(lista(conPendiente: {99}));
      await tester.pumpAndSettle();

      expect(find.text('V-0007'), findsOneWidget);
      expect(find.byKey(const Key('chip-cambio-pendiente')), findsNothing);
    });
  });
}

class _ComprasFalsas extends MisComprasController {
  _ComprasFalsas(super.ref, List<Venta> ventas) : super(activo: false) {
    state = AsyncValue.data(ventas);
  }
}
