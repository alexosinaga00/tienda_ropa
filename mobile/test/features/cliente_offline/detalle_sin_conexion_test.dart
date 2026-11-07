import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/core/conectividad/conectividad_service.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/network/providers.dart';
import 'package:mobile/core/utils/reloj.dart';
import 'package:mobile/features/auth/models/usuario.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/auth/state/auth_state.dart';
import 'package:mobile/features/catalogo/data/catalogo_repository.dart';
import 'package:mobile/features/catalogo/models/catalogo_detalle.dart';
import 'package:mobile/features/catalogo/models/referencia.dart';
import 'package:mobile/features/catalogo/presentation/detalle_screen.dart';
import 'package:mobile/features/catalogo/state/catalogo_providers.dart';
import 'package:mobile/features/cliente_offline/state/carrito_local_controller.dart';
import 'package:mobile/features/cliente_offline/state/cliente_offline_providers.dart';
import 'package:mobile/features/favoritos/state/favoritos_controller.dart';
import 'package:mobile/features/recomendador/state/recomendador_providers.dart';
import 'package:mobile/features/reservas/state/reservas_providers.dart';
import 'package:mobile/features/tracking/models/evento.dart';
import 'package:mobile/features/tracking/state/tracking_service.dart';

import '../../helpers/cliente_offline_apoyo.dart';
import '../../helpers/sesion_storage_falso.dart';
import '../../helpers/token_storage_falso.dart';

class _AuthCliente extends AuthController {
  _AuthCliente(super.ref) {
    state = const AuthState(
      estado: EstadoSesion.autenticado,
      usuario: Usuario(
        id: 9,
        nombre: 'Luis',
        apellido: 'Mamani',
        email: 'luis@example.com',
        telefono: null,
        activo: true,
        roles: ['cliente'],
        permisos: [],
        empresaId: 7,
        empresaCodigo: 'chaski',
      ),
    );
  }
}

class _TrackingMudo extends TrackingService {
  _TrackingMudo() : super(Dio());

  @override
  void track({required TipoEvento tipo, int? productoId, int? varianteId, String? texto}) {}
}

class _CarritoLocalRegistrador extends CarritoLocalController {
  _CarritoLocalRegistrador() : super(() async => null, const RelojSistema(), activo: false);

  final agregadas =
      <({int varianteId, int productoId, String nombre, int precio, String? talla, String? color, String? imagen})>[];

  @override
  Future<bool> agregar({
    required int varianteId,
    required int productoId,
    required String productoNombre,
    required int precioUnitarioCentavos,
    String? talla,
    String? color,
    String? imagen,
    int? sucursalId,
    String? sucursalNombre,
    int cantidad = 1,
  }) async {
    agregadas.add((
      varianteId: varianteId,
      productoId: productoId,
      nombre: productoNombre,
      precio: precioUnitarioCentavos,
      talla: talla,
      color: color,
      imagen: imagen,
    ));
    return true;
  }
}

CatalogoDetalle _detalle() => CatalogoDetalle.fromJson({
  'id': 1,
  'codigo': 'P1',
  'nombre': 'Polera Nike',
  'descripcion': 'Algodón',
  'categoria_id': 1,
  'material_id': null,
  'temporada_id': null,
  'coleccion_id': null,
  'genero': 'unisex',
  'precio_base': '199.00',
  'admite_probador': false,
  'variantes': [
    {'id': 101, 'talla_id': 2, 'color_id': 3, 'sku': 'SKU-1', 'precio_efectivo': '199.50', 'cantidad_disponible': null},
  ],
  'imagenes': [
    {'id': 1, 'url': 'https://x/otra.jpg', 'color_id': null, 'es_principal': true, 'orden': 0},
    {'id': 2, 'url': 'https://x/azul.jpg', 'color_id': 3, 'es_principal': false, 'orden': 1},
  ],
});

Future<_CarritoLocalRegistrador> _montar(
  WidgetTester tester, {
  required bool enLinea,
  Future<CatalogoDetalle> Function()? detalle,
}) async {
  final local = _CarritoLocalRegistrador();
  final router = GoRouter(
    routes: [
      GoRoute(path: '/', builder: (context, state) => const DetalleScreen(productoId: 1)),
      GoRoute(
        path: '/carrito',
        builder: (context, state) => const Scaffold(body: Text('PANTALLA CARRITO')),
      ),
    ],
  );
  addTearDown(router.dispose);
  tester.view.physicalSize = const Size(800, 3200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        tokenStorageProvider.overrideWithValue(TokenStorageFalso()),
        sesionStorageProvider.overrideWithValue(SesionStorageFalso()),
        authControllerProvider.overrideWith((ref) => _AuthCliente(ref)),
        enLineaProvider.overrideWith((ref) => Stream.value(enLinea)),
        detalleProductoProvider.overrideWith((ref, id) => detalle == null ? Future.value(_detalle()) : detalle()),
        tallasRefProvider.overrideWith((ref) async => const [TallaRef(id: 2, codigo: 'M', orden: 1)]),
        coloresRefProvider.overrideWith((ref) async => const [ColorRef(id: 3, nombre: 'Azul')]),
        sucursalesRefProvider.overrideWith((ref) async => const <SucursalRef>[]),
        disponibilidadPorVarianteProvider.overrideWith((ref, id) async => throw errorSinRed),
        recomendacionesDetalleProvider.overrideWith((ref, id) async => const []),
        trackingServiceProvider.overrideWithValue(_TrackingMudo()),
        favoritosControllerProvider.overrideWith((ref) => FavoritosController(ref, activo: false)),
        carritoLocalProvider.overrideWith((ref) => local),
      ],
      child: MaterialApp.router(routerConfig: router),
    ),
  );
  await tester.pumpAndSettle();
  return local;
}

Future<void> _elegirTallaYColor(WidgetTester tester) async {
  await tester.tap(find.widgetWithText(ChoiceChip, 'M'));
  await tester.pump();
  await tester.tap(find.widgetWithText(ChoiceChip, 'Azul'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
    'sin conexión: avisa "ves lo que ya tenías cargado" y la disponibilidad dice que se confirma al comprar',
    (tester) async {
      await _montar(tester, enLinea: false);
      await _elegirTallaYColor(tester);

      expect(find.text('Sin conexión: ves lo que ya tenías cargado'), findsOneWidget);
      expect(find.byKey(const Key('disponibilidad-sin-datos')), findsOneWidget);
      expect(find.text('Sin conexión: la disponibilidad se confirma al comprar.'), findsOneWidget);
      expect(find.text('Polera Nike'), findsOneWidget);
    },
  );

  testWidgets('sin conexión "Agregar al carrito" guarda la prenda en el carrito LOCAL con todo para mostrarla', (
    tester,
  ) async {
    final local = await _montar(tester, enLinea: false);
    await _elegirTallaYColor(tester);

    await tester.tap(find.text('Agregar al carrito'));
    await tester.pumpAndSettle();

    final a = local.agregadas.single;
    expect(a.varianteId, 101);
    expect(a.productoId, 1);
    expect(a.nombre, 'Polera Nike');
    expect(a.precio, 19950, reason: 'centavos enteros, sin coma flotante');
    expect(a.talla, 'M');
    expect(a.color, 'Azul');
    expect(a.imagen, 'https://x/azul.jpg', reason: 'la foto del color elegido');
    expect(find.text('Guardado en tu carrito sin conexión. Lo verás en tu carrito.'), findsOneWidget);
  });

  testWidgets('el aviso lleva al carrito', (tester) async {
    await _montar(tester, enLinea: false);
    await _elegirTallaYColor(tester);
    await tester.tap(find.text('Agregar al carrito'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Ver carrito'));
    await tester.pumpAndSettle();

    expect(find.text('PANTALLA CARRITO'), findsOneWidget);
  });

  testWidgets('sin conexión y sin la prenda guardada, el mensaje dice que no estaba guardada', (tester) async {
    await _montar(
      tester,
      enLinea: false,
      detalle: () => Future<CatalogoDetalle>.error(
        const ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: mensajePrendaNoGuardada),
      ),
    );

    expect(find.byKey(const Key('error-detalle')), findsOneWidget);
    expect(find.text(mensajePrendaNoGuardada), findsOneWidget);
  });

  testWidgets('con conexión NO toca el carrito local', (tester) async {
    final local = await _montar(tester, enLinea: true);

    expect(find.text('Sin conexión: ves lo que ya tenías cargado'), findsNothing);
    expect(local.agregadas, isEmpty);
  });
}
