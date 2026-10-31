import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/core/network/api_client.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/network/providers.dart';
import 'package:mobile/core/sesion/sesion_storage.dart';
import 'package:mobile/features/tienda/data/tienda_repository.dart';
import 'package:mobile/features/tienda/models/tienda.dart';
import 'package:mobile/features/tienda/presentation/elige_tienda_screen.dart';
import 'package:mobile/features/tienda/presentation/entrar_a_tienda_screen.dart';
import 'package:mobile/features/tienda/state/tienda_controller.dart';

import '../../helpers/api_client_falso.dart';
import '../../helpers/sesion_storage_falso.dart';
import '../../helpers/token_storage_falso.dart';

const rutaListaTiendas = '/public/tiendas';
String rutaTienda(String codigo) => '/public/$codigo/tienda';

Map<String, dynamic> jsonTienda(String codigo, String nombre, {String? color, String? logo, bool? disponible}) => {
  'codigo': codigo,
  'nombre': nombre,
  'logo_url': logo,
  'color_acento': color,
  'disponible': ?disponible,
};

const errorSinConexion = ErrorApp(
  tipo: TipoErrorApp.sinConexion,
  mensaje: 'Sin conexión. Revisa tu internet e intenta de nuevo.',
);
const errorNoEncontrado = ErrorApp(tipo: TipoErrorApp.noEncontrado, mensaje: 'No encontramos lo que buscabas.', estado: 404);

/// Un [ApiClientFalso] que no responde hasta que se abre la puerta: sirve para ver el estado "cargando".
class ApiLento extends ApiClientFalso {
  final puerta = Completer<void>();

  @override
  Future<List<T>> getLista<T>(
    String ruta, {
    Map<String, dynamic>? query,
    required DesdeJson<T> desde,
    bool publica = false,
  }) async {
    await puerta.future;
    return super.getLista(ruta, query: query, desde: desde, publica: publica);
  }

  @override
  Future<T> getObjeto<T>(
    String ruta, {
    Map<String, dynamic>? query,
    required DesdeJson<T> desde,
    bool publica = false,
  }) async {
    await puerta.future;
    return super.getObjeto(ruta, query: query, desde: desde, publica: publica);
  }
}

/// Un controlador cuyo estado trae un aviso (la tienda guardada ya no existe) sin tocar la sesión ni la red.
class ControladorConAviso extends TiendaController {
  ControladorConAviso(String aviso, SesionStorage storage)
    : super(storage: storage, repositorio: () => throw UnimplementedError(), alTiendaDesaparecida: () async {}) {
    cargadaFuture.then((_) {
      if (mounted) state = TiendaState(cargada: true, tienda: state.tienda, aviso: aviso);
    });
  }
}

class Escenario {
  Escenario(this.api, this.storage, this.router, this.contenedor);

  final ApiClientFalso api;
  final SesionStorageFalso storage;
  final GoRouter router;
  final ProviderContainer contenedor;
}

/// Monta las pantallas de tienda en un router mínimo con `/tienda`, `/home` y `/t/:codigo`.
Future<Escenario> abrirEscenario(
  WidgetTester tester,
  ApiClientFalso api, {
  String inicial = '/tienda',
  Tienda? guardada,
  String? aviso,
  bool empujarTienda = false,
}) async {
  final storage = SesionStorageFalso(tienda: guardada);
  final router = GoRouter(
    initialLocation: inicial,
    routes: [
      GoRoute(path: '/tienda', builder: (context, state) => const EligeTiendaScreen()),
      GoRoute(path: '/home', builder: (context, state) => const Scaffold(body: Text('HOME'))),
      GoRoute(
        path: '/t/:codigo',
        builder: (context, state) => EntrarATiendaScreen(codigo: state.pathParameters['codigo']!),
      ),
    ],
  );
  addTearDown(router.dispose);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        tiendaRepositoryProvider.overrideWithValue(TiendaRepository(api)),
        sesionStorageProvider.overrideWithValue(storage),
        tokenStorageProvider.overrideWithValue(TokenStorageFalso()),
        if (aviso != null) tiendaControllerProvider.overrideWith((ref) => ControladorConAviso(aviso, storage)),
      ],
      child: MaterialApp.router(routerConfig: router),
    ),
  );
  await tester.pump();
  if (empujarTienda) {
    router.push('/tienda');
    await tester.pump();
  }
  await tester.pump();
  final contenedor = ProviderScope.containerOf(tester.element(find.byType(MaterialApp)));
  return Escenario(api, storage, router, contenedor);
}
