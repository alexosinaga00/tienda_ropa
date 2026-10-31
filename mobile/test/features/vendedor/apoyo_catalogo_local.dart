import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/core/conectividad/conectividad_service.dart';
import 'package:mobile/core/utils/reloj.dart';
import 'package:mobile/features/auth/models/usuario.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/vendedor/models/paquete_sincronizacion.dart';
import 'package:mobile/features/vendedor/presentation/catalogo_local_screen.dart';
import 'package:mobile/features/vendedor/presentation/detalle_local_screen.dart';
import 'package:mobile/features/vendedor/state/catalogo_local_providers.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';
import '../../helpers/conectividad_falsa.dart';
import '../../helpers/servicio_descarga_falso.dart';
import 'apoyo_paquete.dart';
import 'apoyo_vendedor.dart';

export '../../helpers/servicio_descarga_falso.dart';

/// El usuario de las pruebas de la consulta sin conexión: id 7, de la empresa 1 (la que siembran los apoyos de la base).
const usuarioEmpresa1 = Usuario(
  id: 7,
  nombre: 'Marta',
  apellido: 'Quispe',
  email: 'marta@chaski.bo',
  telefono: null,
  activo: true,
  roles: ['cajero'],
  permisos: ['ventas.presencial'],
  empresaId: 1,
  empresaCodigo: 'chaski',
  empresaNombre: 'Chaski Sport',
);

/// Lo que dura la tarea de esperar a que SQLite (un hilo aparte) conteste: el reloj falso de las pruebas no lo adelanta.
Future<void> asentar(WidgetTester tester, {int rondas = 12}) async {
  for (var i = 0; i < rondas; i++) {
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 10)));
    await tester.pump();
  }
}

/// Ejecuta algo contra la base real (hilo aparte) desde el cuerpo de una prueba de widgets.
Future<T> enBase<T>(WidgetTester tester, Database db, Future<T> Function(Database db) accion) async {
  final resultado = await tester.runAsync(() => accion(db));
  return resultado as T;
}

/// "20/10 14:35" en la hora local, escrito aparte del código que se prueba.
String fechaLocalEsperada(DateTime utc) {
  final l = utc.toLocal();
  String dos(int n) => n.toString().padLeft(2, '0');
  return '${dos(l.day)}/${dos(l.month)} ${dos(l.hour)}:${dos(l.minute)}';
}

/// Abre la base real en memoria desde una prueba de widgets y la siembra. Se cierra sola al terminar.
Future<Database> abrirBaseSembrada(WidgetTester tester, {Future<void> Function(Database db)? siembra}) async {
  final db = await tester.runAsync(() async {
    final base = await abrirBaseDePrueba();
    if (siembra != null) await siembra(base);
    return base;
  });
  addTearDown(() async {
    try {
      await db!.close();
    } catch (_) {}
  });
  return db!;
}

Future<void> sembrarCategoriasYTallas(Database db) async {
  await sembrarReferencias(db); // categoría 1 "Poleras", tallas S/M/L/XL (1..4) y el color 1 "Negro"
  await db.insert('categoria', {'id': 2, 'empresa_id': 1, 'nombre': 'Camisas'});
  await db.insert('categoria', {'id': 3, 'empresa_id': 1, 'nombre': 'Camisas manga larga', 'categoria_padre_id': 2});
  await db.insert('categoria', {'id': 4, 'empresa_id': 1, 'nombre': 'Pantalones'});
}

Future<void> sembrarDescarga(Database db, {required int sucursalId, required DateTime descargadoEn, int empresaId = 1}) async {
  await db.insert('descarga', {
    'empresa_id': empresaId,
    'sucursal_id': sucursalId,
    'descargado_en': aIsoUtc(descargadoEn),
    'generado_en': aIsoUtc(descargadoEn),
    'completo': 1,
  });
}

/// La empresa 1 con dos sucursales autorizadas para el usuario 7 (Centro y Norte) y cuatro prendas:
/// - 10 "Polera Básica" (Poleras): variantes 100 (S, 5 en Centro y 1 en Norte) y 101 (M, 3 en Centro) a Bs 75.00.
/// - 11 "Camisa Lino" (Camisas): variantes 110 (S, 2 en Centro, Bs 50.00) y 111 (M, 0, Bs 90.00).
/// - 12 "Pantalón Jean" (Pantalones): variante 120 (S, sin existencias).
/// - 13 "Camisa Oxford" (Camisas manga larga, hija de Camisas): variante 130 (S, 4 en Centro, Bs 120.00).
/// Centro se descargó a la hora indicada ([descargadoEn]; por defecto 30 minutos antes de [instanteBase]); Norte, solo si
/// [descargaNorte].
Future<void> sembrarEscenarioBasico(
  Database db, {
  DateTime? descargadoEn,
  bool descargaCentro = true,
  bool descargaNorte = false,
  bool depositoNorte = false,
}) async {
  await sembrarEmpresa(db);
  await sembrarSucursal(db, id: 1, nombre: 'Centro');
  await sembrarSucursal(db, id: 2, nombre: 'Norte', esDeposito: depositoNorte);
  await db.insert('sucursal_autorizada', {'usuario_id': 7, 'sucursal_id': 1});
  await db.insert('sucursal_autorizada', {'usuario_id': 7, 'sucursal_id': 2});
  await sembrarCategoriasYTallas(db);

  await sembrarProducto(db, id: 10, nombre: 'Polera Básica', codigo: 'P10', variantes: [
    variante(100, sku: 'SKU-100'),
    variante(101, tallaId: 2, sku: 'SKU-101'),
  ]);
  await sembrarProducto(db, id: 11, nombre: 'Camisa Lino', codigo: 'C11', categoriaId: 2, variantes: [
    variante(110, sku: 'SKU-110', precio: 5000),
    variante(111, tallaId: 2, sku: 'SKU-111', precio: 9000),
  ]);
  await sembrarProducto(db, id: 12, nombre: 'Pantalón Jean', codigo: 'J12', categoriaId: 4, variantes: [
    variante(120, sku: 'SKU-120', precio: 15000),
  ]);
  await sembrarProducto(db, id: 13, nombre: 'Camisa Oxford', codigo: 'O13', categoriaId: 3, variantes: [
    variante(130, sku: 'SKU-130', precio: 12000),
  ]);

  await sembrarStock(db, varianteId: 100, sucursalId: 1, cantidad: 5);
  await sembrarStock(db, varianteId: 101, sucursalId: 1, cantidad: 3);
  await sembrarStock(db, varianteId: 110, sucursalId: 1, cantidad: 2);
  await sembrarStock(db, varianteId: 111, sucursalId: 1, cantidad: 0);
  await sembrarStock(db, varianteId: 130, sucursalId: 1, cantidad: 4);
  await sembrarStock(db, varianteId: 100, sucursalId: 2, cantidad: 1);

  final base = descargadoEn ?? instanteBase.subtract(const Duration(minutes: 30));
  if (descargaCentro) await sembrarDescarga(db, sucursalId: 1, descargadoEn: base);
  if (descargaNorte) await sembrarDescarga(db, sucursalId: 2, descargadoEn: base);
}

/// El "ahora" de las pruebas: 31/10/2026 12:00 UTC.
final instanteBase = DateTime.utc(2026, 10, 31, 12);

class EscenarioCatalogoLocal {
  EscenarioCatalogoLocal({
    required this.contenedor,
    required this.conectividad,
    required this.reloj,
    required this.servicio,
    required this.db,
    this.router,
  });

  final ProviderContainer contenedor;
  final ConectividadFalsa conectividad;
  final RelojManual reloj;
  final ServicioDescargaFalso servicio;
  final Database db;
  final GoRouter? router;

  String get ruta => router!.routerDelegate.currentConfiguration.last.matchedLocation;
}

List<Override> _overrides({
  required Database db,
  required ConectividadFalsa conectividad,
  required RelojManual reloj,
  required ServicioDescargaFalso servicio,
  required Usuario usuario,
}) {
  return [
    baseLocalProvider.overrideWith((ref) => db),
    descargaServiceProvider.overrideWith((ref) => servicio),
    relojProvider.overrideWithValue(reloj),
    conectividadServiceProvider.overrideWithValue(conectividad),
    authControllerProvider.overrideWith((ref) => AuthControllerFalso(ref, sesionDePersonal(usuario: usuario))),
  ];
}

void _tamano(WidgetTester tester, Size tamano) {
  tester.view.physicalSize = tamano;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

/// Monta las pantallas del catálogo sin conexión en un router mínimo (`/vendedor`, `/vendedor/catalogo` y
/// `/vendedor/producto/:id`) con la base, el reloj, la conectividad y la descarga de las pruebas. Ya espera a que carguen.
Future<EscenarioCatalogoLocal> abrirCatalogoLocal(
  WidgetTester tester, {
  required Database db,
  String inicial = '/vendedor/catalogo',
  bool enLinea = true,
  RelojManual? reloj,
  ServicioDescargaFalso? servicio,
  Usuario usuario = usuarioEmpresa1,
  Size tamano = const Size(800, 1800),
}) async {
  _tamano(tester, tamano);
  final conectividad = ConectividadFalsa(enLinea: enLinea);
  addTearDown(conectividad.cerrar);
  final relojFijo = reloj ?? RelojManual(instanteBase);
  final servicioFalso = servicio ?? ServicioDescargaFalso();

  final router = GoRouter(
    initialLocation: inicial,
    routes: [
      GoRoute(path: '/vendedor', builder: (context, state) => const Scaffold(body: Text('PANTALLA INICIO'))),
      GoRoute(path: '/vendedor/catalogo', builder: (context, state) => const CatalogoLocalScreen()),
      GoRoute(
        path: '/vendedor/producto/:id',
        builder: (context, state) => DetalleLocalScreen(productoId: int.parse(state.pathParameters['id']!)),
      ),
    ],
  );
  addTearDown(router.dispose);

  await tester.pumpWidget(
    ProviderScope(
      overrides: _overrides(db: db, conectividad: conectividad, reloj: relojFijo, servicio: servicioFalso, usuario: usuario),
      child: MaterialApp.router(routerConfig: router),
    ),
  );
  final contenedor = ProviderScope.containerOf(tester.element(find.byType(MaterialApp)));
  await asentar(tester);
  return EscenarioCatalogoLocal(
    contenedor: contenedor,
    conectividad: conectividad,
    reloj: relojFijo,
    servicio: servicioFalso,
    db: db,
    router: router,
  );
}

/// Monta un solo widget (el aviso, el selector...) dentro de un Scaffold, con los mismos dobles.
Future<EscenarioCatalogoLocal> abrirComponente(
  WidgetTester tester, {
  required Database db,
  required Widget hijo,
  bool enLinea = true,
  RelojManual? reloj,
  ServicioDescargaFalso? servicio,
  Usuario usuario = usuarioEmpresa1,
}) async {
  _tamano(tester, const Size(800, 1800));
  final conectividad = ConectividadFalsa(enLinea: enLinea);
  addTearDown(conectividad.cerrar);
  final relojFijo = reloj ?? RelojManual(instanteBase);
  final servicioFalso = servicio ?? ServicioDescargaFalso();

  await tester.pumpWidget(
    ProviderScope(
      overrides: _overrides(db: db, conectividad: conectividad, reloj: relojFijo, servicio: servicioFalso, usuario: usuario),
      child: MaterialApp(
        home: Scaffold(appBar: AppBar(actions: [hijo]), body: const SizedBox.shrink()),
      ),
    ),
  );
  final contenedor = ProviderScope.containerOf(tester.element(find.byType(MaterialApp)));
  await asentar(tester);
  return EscenarioCatalogoLocal(
    contenedor: contenedor,
    conectividad: conectividad,
    reloj: relojFijo,
    servicio: servicioFalso,
    db: db,
  );
}

/// Igual que [abrirComponente] pero el widget va en el cuerpo (el aviso es una franja de ancho completo).
Future<EscenarioCatalogoLocal> abrirFranja(
  WidgetTester tester, {
  required Database db,
  required Widget hijo,
  bool enLinea = true,
  RelojManual? reloj,
  ServicioDescargaFalso? servicio,
}) async {
  _tamano(tester, const Size(800, 1800));
  final conectividad = ConectividadFalsa(enLinea: enLinea);
  addTearDown(conectividad.cerrar);
  final relojFijo = reloj ?? RelojManual(instanteBase);
  final servicioFalso = servicio ?? ServicioDescargaFalso();

  await tester.pumpWidget(
    ProviderScope(
      overrides: _overrides(db: db, conectividad: conectividad, reloj: relojFijo, servicio: servicioFalso, usuario: usuarioEmpresa1),
      child: MaterialApp(home: Scaffold(body: hijo)),
    ),
  );
  final contenedor = ProviderScope.containerOf(tester.element(find.byType(MaterialApp)));
  await asentar(tester);
  return EscenarioCatalogoLocal(
    contenedor: contenedor,
    conectividad: conectividad,
    reloj: relojFijo,
    servicio: servicioFalso,
    db: db,
  );
}

/// Los textos de los widgets `Text` que hay en pantalla (para mensajes de depuración al fallar una prueba).
List<String> textosEnPantalla(WidgetTester tester) => [
  for (final t in tester.widgetList<Text>(find.byType(Text))) t.data ?? t.textSpan?.toPlainText() ?? '',
];
