import 'dart:async';

import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/sync/contrato_sync.dart';
import 'package:mobile/core/sync/sincronizacion_api.dart';

// ---- Constructores de resultados del servidor ----

ResultadoOperacionSync resultadoConfirmada(String id, {bool duplicada = false, int recursoId = 1, String? codigo, DateTime? procesadaEn}) =>
    ResultadoOperacionSync(
      operacionId: id,
      estado: EstadoResultadoSync.confirmada,
      duplicada: duplicada,
      procesadaEn: procesadaEn ?? DateTime.utc(2026, 10, 31, 12),
      recurso: RecursoSync(tipo: 'venta', id: recursoId, codigo: codigo ?? 'V-$recursoId', totalCentavos: 7500),
    );

ResultadoOperacionSync resultadoRechazada(String id, {String motivo = 'variante_inactiva', bool duplicada = false}) =>
    ResultadoOperacionSync(
      operacionId: id,
      estado: EstadoResultadoSync.rechazada,
      motivo: motivo,
      mensaje: 'Texto del servidor',
      duplicada: duplicada,
      procesadaEn: DateTime.utc(2026, 10, 31, 12),
    );

ResultadoOperacionSync resultadoEnConflicto(String id, {String motivo = 'stock_insuficiente', bool duplicada = false}) =>
    ResultadoOperacionSync(
      operacionId: id,
      estado: EstadoResultadoSync.enConflicto,
      motivo: motivo,
      duplicada: duplicada,
      procesadaEn: DateTime.utc(2026, 10, 31, 12),
      faltantes: const [FaltanteSync(varianteId: 5, solicitado: 2, disponible: 0)],
    );

ResultadoOperacionSync resultadoTemporal(String id) =>
    ResultadoOperacionSync(operacionId: id, estado: EstadoResultadoSync.errorTemporal, mensaje: 'Intenta de nuevo');

RespuestaLote respuestaDeLote(List<ResultadoOperacionSync> resultados) =>
    RespuestaLote(versionContrato: '1.0', procesadoEn: DateTime.utc(2026, 10, 31, 12), resultados: resultados);

/// Lo que el servidor haría por defecto: confirmar todas las operaciones del lote.
RespuestaLote confirmarTodas(LoteEnvio lote) =>
    respuestaDeLote([for (final o in lote.operaciones) resultadoConfirmada(o.operacionId)]);

/// Doble de [SincronizacionApi].
///
/// `enviarLote` toma la siguiente respuesta PROGRAMADA con [programar] (se consume una por llamada; al agotarse se usa
/// [porDefecto], que confirma todo). Cada respuesta es un [RespuestaLote], un [ErrorApp] (se lanza) o una función
/// `RespuestaLote Function(LoteEnvio)`.
class SincronizacionApiFalsa implements SincronizacionApi {
  SincronizacionApiFalsa({this.porDefecto = confirmarTodas});

  /// Qué responde cuando ya no quedan respuestas programadas.
  RespuestaLote Function(LoteEnvio lote) porDefecto;

  /// Cada lote recibido, en orden.
  final List<LoteEnvio> lotes = [];

  /// Cada id consultado con [consultar], en orden.
  final List<String> consultas = [];

  /// Se llama con cada lote ANTES de responder (para simular algo que ocurre mientras viaja: un encargado resuelve, etc.).
  FutureOr<void> Function(LoteEnvio lote)? alRecibir;

  final List<Object> _respuestas = [];
  final Map<String, List<Object?>> _consultasProgramadas = {};
  Completer<void>? _compuerta;

  /// Cuántas peticiones de lote se hicieron.
  int get peticiones => lotes.length;

  /// Los ids de operación de cada lote, en el orden en que se enviaron.
  List<List<String>> get idsPorLote => [
    for (final l in lotes) [for (final o in l.operaciones) o.operacionId],
  ];

  /// Todos los ids enviados, en orden.
  List<String> get idsEnviados => [for (final ids in idsPorLote) ...ids];

  /// Programa la siguiente respuesta del lote (en orden).
  void programar(Object respuesta) {
    assert(
      respuesta is RespuestaLote || respuesta is ErrorApp || respuesta is Function,
      'Una respuesta es RespuestaLote, ErrorApp o una función de LoteEnvio.',
    );
    _respuestas.add(respuesta);
  }

  /// Programa lo que responde `consultar(id)`: un [ResultadoOperacionSync], `null` (el servidor no la conoce), un [ErrorApp] o
  /// cualquier otro objeto lanzable. Se entregan en orden y la última se repite. Sin programar devuelve `null`.
  void programarConsulta(String operacionId, Object? respuesta) {
    _consultasProgramadas.putIfAbsent(operacionId, () => []).add(respuesta);
  }

  /// Hace que `enviarLote` espere (simula lentitud) hasta que se complete lo que devuelve esta función.
  Completer<void> retener() {
    final c = Completer<void>();
    _compuerta = c;
    return c;
  }

  @override
  Future<RespuestaLote> enviarLote(LoteEnvio lote) async {
    lotes.add(lote);
    final compuerta = _compuerta;
    if (compuerta != null) await compuerta.future;
    final gancho = alRecibir;
    if (gancho != null) await gancho(lote);

    if (_respuestas.isEmpty) return porDefecto(lote);
    final siguiente = _respuestas.removeAt(0);
    if (siguiente is ErrorApp) throw siguiente;
    if (siguiente is RespuestaLote) return siguiente;
    // Una función de LoteEnvio que devuelve un RespuestaLote o lanza.
    return (siguiente as dynamic)(lote) as RespuestaLote;
  }

  @override
  Future<ResultadoOperacionSync?> consultar(String operacionId) async {
    consultas.add(operacionId);
    final cola = _consultasProgramadas[operacionId];
    if (cola == null || cola.isEmpty) return null;
    final respuesta = cola.length > 1 ? cola.removeAt(0) : cola.first;
    if (respuesta is Object && respuesta is! ResultadoOperacionSync) throw respuesta;
    return respuesta as ResultadoOperacionSync?;
  }
}
