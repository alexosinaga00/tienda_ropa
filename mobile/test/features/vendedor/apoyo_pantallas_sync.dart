import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/core/conectividad/conectividad_service.dart';
import 'package:mobile/core/sync/cola_operaciones.dart';
import 'package:mobile/core/sync/contrato_sync.dart';
import 'package:mobile/core/sync/lineas_operacion.dart';
import 'package:mobile/core/sync/motor_sincronizacion.dart';
import 'package:mobile/core/sync/operacion_pendiente.dart';
import 'package:mobile/core/utils/reloj.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/vendedor/models/sucursal_local.dart';
import 'package:mobile/features/vendedor/presentation/operaciones_pendientes_screen.dart';
import 'package:mobile/features/vendedor/presentation/resultado_sync_screen.dart';
import 'package:mobile/features/vendedor/state/catalogo_local_providers.dart';
import 'package:mobile/features/vendedor/state/sincronizacion_providers.dart';

import '../../helpers/cola_falsa.dart';
import '../../helpers/conectividad_falsa.dart';
import '../../helpers/siembra_operaciones.dart';
import '../../helpers/sincronizacion_api_falsa.dart';
import 'apoyo_vendedor.dart';

/// El "ahora" de estas pruebas: 31/10/2026 12:00 UTC.
final ahoraDePrueba = DateTime.utc(2026, 10, 31, 12);

/// La empresa y el usuario de [usuarioDePrueba]: 3 y 7.
const empresaPrueba = 3;
const usuarioPrueba = 7;

/// Un id de operación de 36 caracteres cuyo código corto (8) es el número con ceros: `idOp(1)` empieza con "00000001".
String idOp(int n) => '${n.toString().padLeft(8, '0')}-0000-4000-8000-000000000000';

/// Una operación del usuario de la prueba (empresa 3, usuario 7). Sin [fecha], ocurrió a las 09:00 UTC de hoy.
OperacionPendiente opDe(
  int n, {
  EstadoOperacion estado = EstadoOperacion.registrada,
  TipoOperacion tipo = TipoOperacion.ventaContado,
  DateTime? fecha,
  int sucursalId = 1,
  int totalCentavos = 7500,
  String? ultimoError,
  int intentos = 0,
}) {
  return operacionDePrueba(
    idOp(n),
    empresaId: empresaPrueba,
    usuarioId: usuarioPrueba,
    sucursalId: sucursalId,
    tipo: tipo,
    estado: estado,
    fechaOperacion: fecha,
    ultimoError: ultimoError,
    intentos: intentos,
    payload: tipo == TipoOperacion.ventaContado
        ? jsonEncode(
            payloadVentaContado(
              lineas: [LineaVenta(varianteId: 5, cantidad: 1, precioUnitarioCentavos: totalCentavos)],
              totalCentavos: totalCentavos,
            ),
          )
        : null,
  );
}

/// La [ColaFalsa] con lo que a la pantalla le falta: nombres, fotos, clientes y los `detalle_json` de las respuestas.
class ColaDePantalla extends ColaFalsa {
  ColaDePantalla([super.iniciales]);

  final Map<String, DetalleOperacion Function(DetalleOperacion base)> _retoques = {};
  final Map<String, List<ResultadoLocal>> _respuestas = {};

  /// Cambia el detalle que se devuelve de una operación (líneas con nombre, cliente, visita...).
  void retocarDetalle(String operacionId, DetalleOperacion Function(DetalleOperacion base) retoque) {
    _retoques[operacionId] = retoque;
  }

  /// Agrega una respuesta del servidor tal cual (con su `detalle_json`), sin pasar por las reglas de la cola.
  void sembrarRespuesta(
    String operacionId, {
    required String estado,
    String? codigoMotivo,
    String? motivo,
    Map<String, Object?>? detalle,
    DateTime? recibidoEn,
  }) {
    _respuestas.putIfAbsent(operacionId, () => []).add(
      ResultadoLocal(
        operacionId: operacionId,
        recibidoEn: recibidoEn ?? DateTime.utc(2026, 10, 31, 11),
        estadoResultado: estado,
        codigoMotivo: codigoMotivo,
        motivo: motivo,
        detalleJson: detalle == null ? null : jsonEncode(detalle),
      ),
    );
  }

  /// Cambia la fila (estado y error) como lo haría la cola real, y avisa a la interfaz.
  Future<void> cambiarEstado(String operacionId, EstadoOperacion estado, {String? ultimoError}) {
    final o = fila(operacionId);
    sembrar(
      OperacionPendiente(
        operacionId: o.operacionId,
        empresaId: o.empresaId,
        sucursalId: o.sucursalId,
        usuarioId: o.usuarioId,
        tipo: o.tipo,
        estado: estado,
        payload: o.payload,
        versionContrato: o.versionContrato,
        intentos: o.intentos,
        fechaOperacion: o.fechaOperacion,
        creadaEn: o.creadaEn,
        ultimoError: ultimoError ?? o.ultimoError,
        resueltaEn: o.resueltaEn,
      ),
    );
    return avisarCambio();
  }

  /// La [ColaFalsa] solo avisa cuando una de sus operaciones se ejecuta: una llamada sin ids emite sin tocar nada.
  Future<void> avisarCambio() =>
      registrarFalloDeRed(const [], error: 'sin cambios', proximoReintento: DateTime.utc(2026, 10, 31));

  @override
  Future<DetalleOperacion?> detalle(String operacionId) async {
    final base = await super.detalle(operacionId);
    final retoque = _retoques[operacionId];
    if (base == null || retoque == null) return base;
    return retoque(base);
  }

  @override
  Future<List<ResultadoLocal>> resultados(String operacionId) async {
    final propias = _respuestas[operacionId];
    final reales = await super.resultados(operacionId);
    return [...reales, ...?propias];
  }
}

/// Un detalle como el de la cola real: con nombres de prenda, talla, color y, si se da, cliente y visita.
DetalleOperacion detalleCon(
  DetalleOperacion base, {
  List<LineaDetalle>? lineas,
  String? clienteNombre,
  bool? efectivoConfirmado,
  DateTime? fechaVisita,
  String? horaDesde,
  String? horaHasta,
  String? observacion,
}) {
  return DetalleOperacion(
    operacion: base.operacion,
    lineas: lineas ?? base.lineas,
    clienteNombre: clienteNombre ?? base.clienteNombre,
    clienteServidorId: base.clienteServidorId,
    totalCentavos: base.totalCentavos,
    efectivoConfirmado: efectivoConfirmado ?? base.efectivoConfirmado,
    fechaVisita: fechaVisita ?? base.fechaVisita,
    horaDesde: horaDesde ?? base.horaDesde,
    horaHasta: horaHasta ?? base.horaHasta,
    observacion: observacion ?? base.observacion,
  );
}

const sucursalCentro = SucursalLocal(id: 1, codigo: 'CEN', nombre: 'Centro', direccion: 'Av. 1', esDeposito: false, activo: true);
const sucursalNorte = SucursalLocal(id: 2, codigo: 'NOR', nombre: 'Norte', direccion: 'Av. 2', esDeposito: false, activo: true);

class EscenarioSync {
  EscenarioSync({
    required this.cola,
    required this.api,
    required this.motor,
    required this.reloj,
    required this.conectividad,
    required this.router,
    required this.contenedor,
  });

  final ColaDePantalla cola;
  final SincronizacionApiFalsa api;
  final MotorSincronizacion motor;
  final RelojDePrueba reloj;
  final ConectividadFalsa conectividad;
  final GoRouter router;
  final ProviderContainer contenedor;

  /// La ruta de la pantalla de arriba.
  String get ruta => router.routerDelegate.currentConfiguration.last.matchedLocation;

  /// Corre el motor a mano, fuera del reloj falso (la cola de prueba solo usa microtareas).
  Future<ResumenSync> sincronizar(WidgetTester tester, {Disparador disparador = Disparador.manual}) async {
    final resumen = await tester.runAsync(
      () => motor.sincronizar(empresaId: empresaPrueba, usuarioId: usuarioPrueba, disparador: disparador),
    );
    await tester.pump();
    return resumen!;
  }
}

/// Deja correr los futuros de la cola falsa (solo microtareas) y los frames que dependen de ellos.
Future<void> asentarSync(WidgetTester tester, {int rondas = 6}) async {
  for (var i = 0; i < rondas; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

/// Monta la lista de operaciones, la pantalla de resultado y unas pantallas mudas en un router mínimo, con la cola y el motor
/// de prueba (sin SQLite ni red). [inicial] es la ruta de arranque.
Future<EscenarioSync> abrirPantallasSync(
  WidgetTester tester, {
  String inicial = '/vendedor/operaciones',
  Iterable<OperacionPendiente> operaciones = const [],
  ColaDePantalla? cola,
  bool enLinea = true,
  List<SucursalLocal> sucursales = const [sucursalCentro],
  SincronizacionApiFalsa? api,
  List<Override> overrides = const [],
  Size tamano = const Size(800, 1800),
  Widget? inicio,
}) async {
  tester.view.physicalSize = tamano;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);

  final colaFalsa = cola ?? ColaDePantalla();
  for (final o in operaciones) {
    colaFalsa.sembrar(o);
  }
  final apiFalsa = api ?? SincronizacionApiFalsa();
  final reloj = RelojDePrueba(ahoraDePrueba);
  final conectividad = ConectividadFalsa(enLinea: enLinea);
  addTearDown(conectividad.cerrar);
  final motor = MotorSincronizacion(
    cola: colaFalsa,
    api: apiFalsa,
    reloj: reloj,
    conectividad: conectividad,
    dispositivoId: () async => 'telefono-de-prueba',
  );
  addTearDown(motor.dispose);

  final router = GoRouter(
    initialLocation: inicial,
    routes: [
      GoRoute(path: '/vendedor', builder: (context, state) => inicio ?? const Scaffold(body: Text('PANTALLA INICIO'))),
      GoRoute(path: '/vendedor/venta/nueva', builder: (context, state) => const Scaffold(body: Text('PANTALLA NUEVA VENTA'))),
      GoRoute(
        path: '/vendedor/reserva/nueva',
        builder: (context, state) => const Scaffold(body: Text('PANTALLA NUEVA RESERVA')),
      ),
      GoRoute(path: '/vendedor/operaciones', builder: (context, state) => const OperacionesPendientesScreen()),
      GoRoute(
        path: '/vendedor/operaciones/:operacionId',
        builder: (context, state) => ResultadoSyncScreen(
          operacionId: (state.pathParameters['operacionId'] ?? '').toLowerCase(),
          esNueva: state.uri.queryParameters['nuevo'] == '1',
        ),
      ),
    ],
  );
  addTearDown(router.dispose);

  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        authControllerProvider.overrideWith((ref) => AuthControllerFalso(ref, sesionDePersonal())),
        colaOperacionesProvider.overrideWith((ref) async => colaFalsa),
        motorSincronizacionProvider.overrideWith((ref) async => motor),
        relojProvider.overrideWithValue(reloj),
        conectividadServiceProvider.overrideWithValue(conectividad),
        sucursalesAutorizadasProvider.overrideWith((ref) async => sucursales),
        ...overrides,
      ],
      child: MaterialApp.router(routerConfig: router),
    ),
  );
  final contenedor = ProviderScope.containerOf(tester.element(find.byType(MaterialApp)));
  await asentarSync(tester);
  return EscenarioSync(
    cola: colaFalsa,
    api: apiFalsa,
    motor: motor,
    reloj: reloj,
    conectividad: conectividad,
    router: router,
    contenedor: contenedor,
  );
}

/// Captura lo que la app copia al portapapeles.
List<String> capturarPortapapeles(WidgetTester tester) {
  final copiado = <String>[];
  tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (llamada) async {
    if (llamada.method == 'Clipboard.setData') {
      copiado.add((llamada.arguments as Map)['text'] as String);
    }
    return null;
  });
  addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, null));
  return copiado;
}

/// Todos los textos de pantalla (también los de widgets `Text.rich`).
List<String> todosLosTextos(WidgetTester tester) => [
  for (final t in tester.widgetList<Text>(find.byType(Text))) t.data ?? t.textSpan?.toPlainText() ?? '',
];

/// Palabras del voseo rioplatense que NO deben aparecer: los textos van en tuteo.
final _voseo = RegExp(
  r'\b(tenés|podés|querés|sabés|hacé|elegí|pulsá|tocá|avisá|intentá|volvé|revisá|contactá|registrá|cobrá|actualizá|mirá|esperá|vos|sos|usá|ingresá)\b',
  caseSensitive: false,
);

/// Los textos que usan voseo (debe quedar vacío).
List<String> textosConVoseo(WidgetTester tester) => [
  for (final t in todosLosTextos(tester))
    if (_voseo.hasMatch(t)) t,
];

/// "hoy 11:00" para una fecha UTC, escrito aparte del código que se prueba (hora local).
String textoHoyEsperado(DateTime utc) {
  final l = utc.toLocal();
  String dos(int n) => n.toString().padLeft(2, '0');
  return 'hoy ${dos(l.hour)}:${dos(l.minute)}';
}

/// "29/10 09:30" para una fecha UTC (hora local), escrito aparte del código que se prueba.
String fechaCortaEsperada(DateTime utc) {
  final l = utc.toLocal();
  String dos(int n) => n.toString().padLeft(2, '0');
  return '${dos(l.day)}/${dos(l.month)} ${dos(l.hour)}:${dos(l.minute)}';
}

/// ¿La fecha y "ahora" caen el mismo día LOCAL? (Las pruebas de "hoy" solo valen en ese caso.)
bool mismoDiaLocal(DateTime a, DateTime b) {
  final la = a.toLocal();
  final lb = b.toLocal();
  return la.year == lb.year && la.month == lb.month && la.day == lb.day;
}
