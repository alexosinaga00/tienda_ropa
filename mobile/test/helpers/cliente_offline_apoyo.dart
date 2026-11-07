import 'dart:async';

import 'package:mobile/core/local_cliente/abrir_base_cliente.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/sync/generador_uuid.dart';
import 'package:mobile/core/utils/reloj.dart';
import 'package:mobile/features/cliente_offline/data/pedidos_diferidos_api.dart';
import 'package:mobile/features/cliente_offline/data/repositorio_cliente.dart';
import 'package:mobile/features/cliente_offline/models/linea_carrito_local.dart';
import 'package:mobile/features/cliente_offline/models/pedido_diferido_api.dart';
import 'package:mobile/features/cliente_offline/models/pedido_sin_conexion.dart';
import 'package:mobile/features/cliente_offline/state/cola_pedidos.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'conectividad_falsa.dart';
import 'siembra_operaciones.dart';

/// La base local REAL del cliente (SQLite del paquete `sqflite_common_ffi`) en memoria.
Future<Database> abrirBaseClienteDePrueba({String? ruta}) {
  sqfliteFfiInit();
  return abrirBaseCliente(fabrica: databaseFactoryFfi, ruta: ruta ?? inMemoryDatabasePath);
}

const alcanceAna = AlcanceCliente(empresaId: 7, usuarioId: 4);
const alcanceLuis = AlcanceCliente(empresaId: 7, usuarioId: 9);
const alcanceOtraEmpresa = AlcanceCliente(empresaId: 8, usuarioId: 4);

String idOperacion(int n) => '${n.toString().padLeft(8, '0')}-0000-4000-8000-000000000000';

LineaCarritoLocal lineaCarrito({
  int varianteId = 10,
  int productoId = 1,
  int cantidad = 1,
  String nombre = 'Polera Nike',
  int precio = 19900,
  String? talla = 'M',
  String? color = 'Azul',
  String? imagen,
  int? sucursalId,
  DateTime? agregadoEn,
}) => LineaCarritoLocal(
  varianteId: varianteId,
  productoId: productoId,
  cantidad: cantidad,
  productoNombre: nombre,
  precioUnitarioCentavos: precio,
  talla: talla,
  color: color,
  imagen: imagen,
  sucursalId: sucursalId,
  agregadoEn: agregadoEn ?? DateTime.utc(2026, 11, 6, 12),
);

/// Un pedido en cola de ejemplo. Por defecto: 2 poleras de Bs 199.00 en la sucursal 3.
PedidoSinConexion pedidoDePrueba({
  int n = 1,
  AlcanceCliente alcance = alcanceAna,
  EstadoPedidoLocal estado = EstadoPedidoLocal.pendiente,
  DateTime? creadoEn,
  int cantidad = 2,
  int precio = 19900,
  int intentos = 0,
  DateTime? ultimoIntentoEn,
  DateTime? proximoIntentoEn,
}) {
  final creado = creadoEn ?? DateTime.utc(2026, 11, 6, 12);
  return PedidoSinConexion(
    empresaId: alcance.empresaId,
    usuarioId: alcance.usuarioId,
    operacionId: idOperacion(n),
    estado: estado,
    sucursalId: 3,
    sucursalNombre: 'Centro',
    costoEnvioCentavos: 0,
    lineas: [
      LineaPedidoLocal(
        varianteId: 10,
        cantidad: cantidad,
        productoNombre: 'Polera Nike',
        talla: 'M',
        color: 'Azul',
        precioUnitarioCentavos: precio,
      ),
    ],
    totalMaximoCentavos: precio * cantidad,
    fechaPedido: creado.toIso8601String(),
    creadoEn: creado,
    intentos: intentos,
    ultimoIntentoEn: ultimoIntentoEn,
    proximoIntentoEn: proximoIntentoEn,
  );
}

PedidoDiferidoRespuesta respuestaCobrada(
  String operacionId, {
  String codigo = 'V-0055',
  int ventaId = 55,
  int total = 39800,
}) => PedidoDiferidoRespuesta.fromJson({
  'operacion_id': operacionId,
  'estado': 'cobrado',
  'motivo': null,
  'mensaje': 'Cobramos tu pedido.',
  'venta_id': ventaId,
  'codigo_venta': codigo,
  'total': '${total ~/ 100}.${(total % 100).toString().padLeft(2, '0')}',
  'total_usd': '57.18',
  'duplicada': false,
});

PedidoDiferidoRespuesta respuestaRechazada(
  String operacionId,
  String motivo, {
  String mensaje = 'No se pudo cobrar.',
}) => PedidoDiferidoRespuesta.fromJson({
  'operacion_id': operacionId,
  'estado': 'rechazado',
  'motivo': motivo,
  'mensaje': mensaje,
  'venta_id': null,
  'codigo_venta': null,
  'total': null,
  'total_usd': null,
  'duplicada': false,
});

ErrorApp errorHttp(int estado, {String? codigo, Duration? reintentar}) => ErrorApp(
  tipo: switch (estado) {
    401 => TipoErrorApp.noAutorizado,
    403 when codigo == 'suscripcion_no_activa' => TipoErrorApp.suscripcionNoActiva,
    403 => TipoErrorApp.prohibido,
    422 => TipoErrorApp.validacion,
    >= 500 => TipoErrorApp.servidor,
    _ => TipoErrorApp.desconocido,
  },
  mensaje: 'Error $estado',
  estado: estado,
  codigo: codigo,
  reintentarDespues: reintentar,
);

const errorSinRed = ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: 'Sin conexiÃ³n', posiblementeRecibido: true);

/// Doble de la API de pedidos. Cada respuesta se prepara con [responder]: una [PedidoDiferidoRespuesta] (se devuelve), un
/// error (se lanza) o un `Future Function(PedidoDiferidoCrear)` (para esperar a mano). Las respuestas se entregan en orden y la
/// ÃšLTIMA se repite. Sin ninguna preparada, falla con un [StateError]: una prueba mal armada no pasa inadvertida.
class ApiPedidosFalsa implements PedidosDiferidosApi {
  final List<PedidoDiferidoCrear> enviados = [];
  final List<Object> _respuestas = [];

  /// CuÃ¡ntos envÃ­os corrieron al mismo tiempo como mÃ¡ximo (debe ser 1: nunca en paralelo).
  int maximoSimultaneos = 0;
  int _simultaneos = 0;

  /// QuÃ© hacer con cada envÃ­o si no se prepararon respuestas: devolver cobrado.
  bool cobrarPorDefecto = true;

  void responder(Object respuesta) => _respuestas.add(respuesta);

  List<String> get idsEnviados => [for (final e in enviados) e.operacionId];

  @override
  Future<PedidoDiferidoRespuesta> enviar(PedidoDiferidoCrear pedido) async {
    enviados.add(pedido);
    _simultaneos++;
    if (_simultaneos > maximoSimultaneos) maximoSimultaneos = _simultaneos;
    try {
      if (_respuestas.isEmpty) {
        if (cobrarPorDefecto) return respuestaCobrada(pedido.operacionId);
        throw StateError('ApiPedidosFalsa sin respuesta preparada');
      }
      final respuesta = _respuestas.length > 1 ? _respuestas.removeAt(0) : _respuestas.first;
      if (respuesta is Function) {
        // Un cierre: puede esperar a mano, cambiar el reloj, o lanzar.
        final resultado = Function.apply(respuesta, [pedido]);
        return (resultado is Future ? await resultado : resultado) as PedidoDiferidoRespuesta;
      }
      if (respuesta is PedidoDiferidoRespuesta) return respuesta;
      throw respuesta;
    } finally {
      _simultaneos--;
    }
  }
}

/// Un temporizador que no corre solo: guarda lo programado para dispararlo a mano.
class TemporizadorFalso {
  final List<({Duration espera, void Function() accion, TimerFalso timer})> programados = [];

  Timer crear(Duration espera, void Function() accion) {
    final timer = TimerFalso();
    programados.add((espera: espera, accion: accion, timer: timer));
    return timer;
  }

  /// Los que siguen activos (no cancelados).
  int get activos => programados.where((p) => !p.timer.cancelado).length;

  Duration? get ultimaEspera => programados.isEmpty ? null : programados.last.espera;

  void dispararUltimo() {
    final ultimo = programados.last;
    if (!ultimo.timer.cancelado) ultimo.accion();
  }
}

class TimerFalso implements Timer {
  bool cancelado = false;

  @override
  void cancel() => cancelado = true;

  @override
  bool get isActive => !cancelado;

  @override
  int get tick => 0;
}

class GeneradorUuidSecuencial implements GeneradorUuid {
  int _n = 0;

  @override
  String nuevo() => idOperacion(++_n);
}

/// Todo el sistema de la cola, real salvo la red y el reloj: base SQLite, repositorio y cola.
class MundoCola {
  MundoCola._(this.db, this.reloj, this.api, this.conectividad, this.temporizador, this.alcance);

  static Future<MundoCola> crear({
    AlcanceCliente alcance = alcanceAna,
    Duration Function(int)? espera,
    Duration tiempoLimite = const Duration(seconds: 30),
    bool enLinea = true,
    Database? db,
  }) async {
    final base = db ?? await abrirBaseClienteDePrueba();
    final mundo = MundoCola._(
      base,
      RelojDePrueba(DateTime.utc(2026, 11, 6, 12)),
      ApiPedidosFalsa(),
      ConectividadFalsa(enLinea: enLinea),
      TemporizadorFalso(),
      alcance,
    );
    mundo.cola = mundo.nuevaCola(espera: espera, tiempoLimite: tiempoLimite);
    return mundo;
  }

  final Database db;
  final RelojDePrueba reloj;
  final ApiPedidosFalsa api;
  final ConectividadFalsa conectividad;
  final TemporizadorFalso temporizador;
  AlcanceCliente? alcance;
  late ColaPedidos cola;
  final List<PedidoSinConexion> resueltos = [];
  int vecesSinMetodoPago = 0;

  RepositorioCliente repo([AlcanceCliente? a]) => RepositorioCliente(db, alcance: a ?? alcance!);

  ColaPedidos nuevaCola({Duration Function(int)? espera, Duration tiempoLimite = const Duration(seconds: 30)}) {
    final nueva = ColaPedidos(
      repositorio: () async => alcance == null ? null : repo(),
      alcanceActual: () => alcance,
      api: api,
      reloj: reloj,
      conectividad: conectividad,
      generador: GeneradorUuidSecuencial(),
      espera: espera ?? (n) => Duration(seconds: 10 * n),
      tiempoLimite: tiempoLimite,
      temporizador: temporizador.crear,
      alFaltarMetodoPago: () async => vecesSinMetodoPago++,
    );
    nueva.resueltos.listen(resueltos.add);
    return nueva;
  }

  /// Guarda un pedido directamente en la base (sin pasar por la cola).
  Future<PedidoSinConexion> sembrar(PedidoSinConexion pedido) =>
      repo(AlcanceCliente(empresaId: pedido.empresaId, usuarioId: pedido.usuarioId)).registrarPedido(pedido);

  Future<PedidoSinConexion> pedido(int n) async => (await repo().pedido(idOperacion(n)))!;
}

/// Una cola que no toca la red ni la base: anota lo que le piden las pantallas. Para las pruebas de widgets.
class ColaFalsa extends ColaPedidos {
  ColaFalsa({this.sinEnviar = 0})
    : super(
        repositorio: () async => null,
        alcanceActual: () => null,
        api: ApiPedidosFalsa(),
        reloj: const RelojSistema(),
        conectividad: ConectividadFalsa(),
      );

  int sinEnviar;

  /// Los pedidos que la pantalla verá.
  List<PedidoSinConexion> lista = [];
  final descartados = <String>[];

  @override
  Future<List<PedidoSinConexion>> pedidos() async => lista;
  final entradas = <EntradaPedido>[];
  final alcances = <AlcanceCliente?>[];
  int enviosManuales = 0;
  int borrados = 0;
  int vistos = 0;
  int volvioConexion = 0;
  int procesados = 0;

  @override
  Future<int> contarSinEnviar() async => sinEnviar;

  @override
  Future<bool> descartar(String operacionId) async {
    descartados.add(operacionId);
    return true;
  }

  @override
  Future<void> enviarAhora() async => enviosManuales++;

  @override
  Future<bool> borrarTodoDeEstaCuenta() async {
    borrados++;
    return true;
  }

  @override
  Future<void> marcarVistos() async => vistos++;

  @override
  Future<PedidoSinConexion?> encolar(EntradaPedido entrada) async {
    entradas.add(entrada);
    return pedidoDePrueba();
  }

  @override
  void alCambiarAlcance(AlcanceCliente? alcance) => alcances.add(alcance);

  @override
  void alVolverConexion() => volvioConexion++;

  @override
  Future<void> procesar({bool manual = false, bool reanudar = false}) async => procesados++;
}
