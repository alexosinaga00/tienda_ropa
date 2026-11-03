import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/core/conectividad/conectividad_service.dart';
import 'package:mobile/core/sync/cola_operaciones.dart';
import 'package:mobile/core/sync/generador_uuid.dart';
import 'package:mobile/core/sync/motor_sincronizacion.dart';
import 'package:mobile/core/utils/reloj.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/vendedor/presentation/nueva_reserva_screen.dart';
import 'package:mobile/features/vendedor/presentation/nueva_venta_screen.dart';
import 'package:mobile/features/vendedor/state/catalogo_local_providers.dart';
import 'package:mobile/features/vendedor/state/sincronizacion_providers.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/cola_falsa.dart';
import '../../helpers/conectividad_falsa.dart';
import 'apoyo_catalogo_local.dart';
import 'apoyo_paquete.dart';
import 'apoyo_vendedor.dart';

/// Ids de operación fijos, en el orden en que se piden.
class GeneradorUuidFijo implements GeneradorUuid {
  GeneradorUuidFijo([List<String>? ids]) : ids = ids ?? [idUno, idDos, idTres];

  static const idUno = 'aaaaaaaa-0000-4000-8000-000000000001';
  static const idDos = 'aaaaaaaa-0000-4000-8000-000000000002';
  static const idTres = 'aaaaaaaa-0000-4000-8000-000000000003';

  final List<String> ids;
  int _siguiente = 0;

  /// Cuántos ids se han pedido.
  int get pedidos => _siguiente;

  @override
  String nuevo() => _siguiente < ids.length ? ids[_siguiente++] : 'aaaaaaaa-0000-4000-8000-0000000000${90 + _siguiente++}';
}

/// La [ColaFalsa] que además guarda cada [NuevaVenta] y [NuevaReserva] que recibe, y puede fallar a pedido.
class ColaEspia extends ColaFalsa {
  ColaEspia([super.iniciales]);

  /// Cada intento de registrar (también los que fallaron).
  final List<NuevaVenta> ventas = [];
  final List<NuevaReserva> reservas = [];

  /// Si se asigna, el próximo intento de registrar lanza esto (una vez).
  Object? errorAlRegistrar;

  /// Si se asigna, el registro espera a que se complete (para probar el doble toque).
  Completer<void>? puerta;

  Future<void> _antes() async {
    await puerta?.future;
    final e = errorAlRegistrar;
    if (e != null) {
      errorAlRegistrar = null;
      throw e;
    }
  }

  @override
  Future<void> registrarVenta(NuevaVenta venta) async {
    ventas.add(venta);
    await _antes();
    await super.registrarVenta(venta);
  }

  @override
  Future<void> registrarReserva(NuevaReserva reserva) async {
    reservas.add(reserva);
    await _antes();
    await super.registrarReserva(reserva);
  }
}

class EscenarioNuevaOperacion {
  EscenarioNuevaOperacion({
    required this.contenedor,
    required this.cola,
    required this.reloj,
    required this.conectividad,
    required this.servicio,
    required this.db,
    required this.generador,
    this.router,
    List<Object?>? resultados,
  }) : resultados = resultados ?? [];

  final ProviderContainer contenedor;
  final ColaEspia cola;
  final RelojManual reloj;
  final ConectividadFalsa conectividad;
  final ServicioDescargaFalso servicio;
  final Database db;
  final GeneradorUuidFijo generador;
  final GoRouter? router;

  /// Lo que devolvió cada vez que se abrió y se cerró el selector del anfitrión.
  final List<Object?> resultados;

  /// La ruta (sin parámetros) que muestra el router.
  String get ruta => router!.routerDelegate.currentConfiguration.last.matchedLocation;

  /// La dirección completa, con sus parámetros.
  String get ubicacion => router!.routeInformationProvider.value.uri.toString();
}

void _tamano(WidgetTester tester, Size tamano) {
  tester.view.physicalSize = tamano;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

List<Override> _overrides({
  required Database db,
  required ColaEspia cola,
  required RelojManual reloj,
  required ConectividadFalsa conectividad,
  required ServicioDescargaFalso servicio,
  required GeneradorUuidFijo generador,
  required BloqueoSync? bloqueo,
}) {
  return [
    baseLocalProvider.overrideWith((ref) => db),
    descargaServiceProvider.overrideWith((ref) => servicio),
    relojProvider.overrideWithValue(reloj),
    conectividadServiceProvider.overrideWithValue(conectividad),
    authControllerProvider.overrideWith((ref) => AuthControllerFalso(ref, sesionDePersonal(usuario: usuarioEmpresa1))),
    colaOperacionesProvider.overrideWith((ref) async => cola),
    generadorUuidProvider.overrideWithValue(generador),
    estadoSyncProvider.overrideWith((ref) => Stream.value(EstadoSync(bloqueo: bloqueo))),
  ];
}

/// Monta la pantalla de "Nueva venta" o "Nueva reserva" en un router mínimo (`/vendedor`, las dos pantallas y
/// `/vendedor/operaciones/:id`, que solo muestra su id) con la base real en memoria y la cola falsa. Ya espera a que cargue.
Future<EscenarioNuevaOperacion> abrirNuevaOperacion(
  WidgetTester tester, {
  required Database db,
  String ruta = '/vendedor/venta/nueva',
  bool enLinea = true,
  ColaEspia? cola,
  BloqueoSync? bloqueo,
  RelojManual? reloj,
  Size tamano = const Size(800, 1800),
}) async {
  _tamano(tester, tamano);
  final conectividad = ConectividadFalsa(enLinea: enLinea);
  addTearDown(conectividad.cerrar);
  final colaEspia = cola ?? ColaEspia();
  addTearDown(colaEspia.cerrar);
  final relojFijo = reloj ?? RelojManual(instanteBase);
  final servicio = ServicioDescargaFalso();
  final generador = GeneradorUuidFijo();

  final router = GoRouter(
    initialLocation: '/vendedor',
    routes: [
      GoRoute(path: '/vendedor', builder: (context, state) => const Scaffold(body: Text('PANTALLA INICIO'))),
      GoRoute(path: '/vendedor/venta/nueva', builder: (context, state) => const NuevaVentaScreen()),
      GoRoute(path: '/vendedor/reserva/nueva', builder: (context, state) => const NuevaReservaScreen()),
      GoRoute(
        path: '/vendedor/operaciones/:operacionId',
        builder: (context, state) => Scaffold(
          body: Text('RESULTADO ${state.pathParameters['operacionId']} nuevo=${state.uri.queryParameters['nuevo']}'),
        ),
      ),
    ],
  );
  addTearDown(router.dispose);

  await tester.pumpWidget(
    ProviderScope(
      overrides: _overrides(
        db: db,
        cola: colaEspia,
        reloj: relojFijo,
        conectividad: conectividad,
        servicio: servicio,
        generador: generador,
        bloqueo: bloqueo,
      ),
      child: MaterialApp.router(routerConfig: router),
    ),
  );
  final contenedor = ProviderScope.containerOf(tester.element(find.byType(MaterialApp)));
  unawaited(router.push(ruta));
  await tester.pump();
  await asentar(tester);
  await tester.pumpAndSettle();
  return EscenarioNuevaOperacion(
    contenedor: contenedor,
    cola: colaEspia,
    reloj: relojFijo,
    conectividad: conectividad,
    servicio: servicio,
    db: db,
    generador: generador,
    router: router,
  );
}

/// Una pantalla con un solo botón "Abrir" que ejecuta [abrir] (por ejemplo, un selector) y guarda lo que devuelve en
/// [EscenarioNuevaOperacion.resultados].
Future<EscenarioNuevaOperacion> abrirAnfitrion(
  WidgetTester tester, {
  required Database db,
  required Future<Object?> Function(BuildContext context, WidgetRef ref) abrir,
  Size tamano = const Size(800, 1800),
}) async {
  _tamano(tester, tamano);
  final conectividad = ConectividadFalsa();
  addTearDown(conectividad.cerrar);
  final cola = ColaEspia();
  addTearDown(cola.cerrar);
  final reloj = RelojManual(instanteBase);
  final servicio = ServicioDescargaFalso();
  final generador = GeneradorUuidFijo();
  final resultados = <Object?>[];

  await tester.pumpWidget(
    ProviderScope(
      overrides: _overrides(
        db: db,
        cola: cola,
        reloj: reloj,
        conectividad: conectividad,
        servicio: servicio,
        generador: generador,
        bloqueo: null,
      ),
      child: MaterialApp(
        home: Scaffold(
          body: Consumer(
            builder: (context, ref, _) => Center(
              child: ElevatedButton(
                onPressed: () async => resultados.add(await abrir(context, ref)),
                child: const Text('Abrir'),
              ),
            ),
          ),
        ),
      ),
    ),
  );
  final contenedor = ProviderScope.containerOf(tester.element(find.byType(MaterialApp)));
  await asentar(tester);
  return EscenarioNuevaOperacion(
    contenedor: contenedor,
    cola: cola,
    reloj: reloj,
    conectividad: conectividad,
    servicio: servicio,
    db: db,
    generador: generador,
    resultados: resultados,
  );
}

/// Pulsa "Abrir" y espera a que el selector cargue.
Future<void> abrirSelector(WidgetTester tester) async {
  await tester.tap(find.text('Abrir'));
  await tester.pump();
  await asentar(tester);
  await tester.pumpAndSettle();
}

/// Espera a que SQLite conteste y a que terminen las animaciones.
Future<void> esperar(WidgetTester tester) async {
  await tester.pump();
  await asentar(tester);
  await tester.pumpAndSettle();
}

/// Escribe en un campo y deja pasar la espera de la búsqueda (300 ms) y la lectura de la base.
Future<void> buscarEscribiendo(WidgetTester tester, Finder campo, String texto) async {
  await tester.enterText(campo, texto);
  await tester.pump(const Duration(milliseconds: 350));
  await asentar(tester);
  await tester.pumpAndSettle();
}

/// Un cliente que el servidor conoce, para sembrar. Devuelve su id local.
Future<int> sembrarClienteServidor(Database db, {int servidorId = 501, String nombre = 'Ana', String? apellido = 'Pérez', String? ciNit}) async {
  return db.insert('cliente_minimo', {
    'empresa_id': 1,
    'servidor_id': servidorId,
    'nombre': nombre,
    'apellido': apellido,
    'ci_nit': ciNit,
    'creado_en': '2026-10-31T09:00:00Z',
  });
}
