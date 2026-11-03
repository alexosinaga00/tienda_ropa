import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../features/vendedor/models/paquete_sincronizacion.dart' show mensajeActualizarApp;
import '../conectividad/conectividad_service.dart';
import '../network/error_app.dart';
import '../utils/reloj.dart';
import 'backoff.dart';
import 'cola_operaciones.dart';
import 'contrato_sync.dart';
import 'operacion_pendiente.dart';
import 'sincronizacion_api.dart';

/// Qué despertó al motor. Todos los automáticos respetan la conexión, las esperas, el bloqueo y la sesión vencida; solo
/// [manual] (el botón "Sincronizar ahora") los ignora.
enum Disparador { conexionRecuperada, primerPlano, registro, temporizador, manual }

/// Por qué el servidor no deja sincronizar. Mientras haya un bloqueo, los disparos automáticos no insisten.
enum TipoBloqueo { planNoIncluye, suscripcionNoActiva, actualizarApp }

class BloqueoSync {
  const BloqueoSync({required this.tipo, required this.mensaje});

  final TipoBloqueo tipo;

  /// Texto para la persona (viene del `ErrorApp`).
  final String mensaje;

  @override
  bool operator ==(Object other) => other is BloqueoSync && other.tipo == tipo && other.mensaje == mensaje;

  @override
  int get hashCode => Object.hash(tipo, mensaje);

  @override
  String toString() => 'BloqueoSync($tipo)';
}

/// El resultado de UNA corrida del motor. Los conteos son de lo que CAMBIÓ en esta corrida.
class ResumenSync {
  const ResumenSync({
    this.confirmadas = 0,
    this.rechazadas = 0,
    this.enConflicto = 0,
    this.pendientes = 0,
    this.fallidasPorRed = 0,
    this.omitidasPorEspera = 0,
    this.enviadas = 0,
    this.intentado = false,
    this.bloqueo,
    this.sesionVencida = false,
  });

  final int confirmadas;

  /// Incluye las que el servidor rechazó y las que se rechazaron localmente por un 4xx.
  final int rechazadas;
  final int enConflicto;

  /// Las que siguen sin resolver al terminar (`registrada` o `enviada`, también las que esperan su turno).
  final int pendientes;

  /// Operaciones cuyo envío falló por la red, por el servidor (5xx, 429, 408) o porque no volvieron en la respuesta.
  final int fallidasPorRed;

  /// Las que se dejaron para después porque aún no cumplen su espera (solo en los disparos automáticos).
  final int omitidasPorEspera;

  /// Cuántas operaciones se mandaron en lotes en esta corrida.
  final int enviadas;

  /// `false` si no se intentó nada: sin conexión, bloqueo, sesión vencida o sin candidatas.
  final bool intentado;
  final BloqueoSync? bloqueo;
  final bool sesionVencida;

  /// Algo cambió de estado: la interfaz debe refrescarse.
  bool get huboCambios => confirmadas + rechazadas + enConflicto > 0;

  @override
  String toString() =>
      'ResumenSync(confirmadas: $confirmadas, rechazadas: $rechazadas, enConflicto: $enConflicto, pendientes: $pendientes, '
      'fallidasPorRed: $fallidasPorRed, omitidasPorEspera: $omitidasPorEspera, enviadas: $enviadas, intentado: $intentado)';
}

class EstadoSync {
  const EstadoSync({
    this.enCurso = false,
    this.ultimaSincronizacion,
    this.ultimoResumen,
    this.bloqueo,
    this.sesionVencida = false,
  });

  final bool enCurso;

  /// Cuándo se intentó por última vez (hora del teléfono, UTC). Null si nunca.
  final DateTime? ultimaSincronizacion;
  final ResumenSync? ultimoResumen;
  final BloqueoSync? bloqueo;

  /// El servidor respondió 401 aun después de renovar: hay que volver a iniciar sesión. La cola se conserva.
  final bool sesionVencida;

  EstadoSync copiar({
    bool? enCurso,
    DateTime? ultimaSincronizacion,
    ResumenSync? ultimoResumen,
    BloqueoSync? Function()? bloqueo,
    bool? sesionVencida,
  }) => EstadoSync(
    enCurso: enCurso ?? this.enCurso,
    ultimaSincronizacion: ultimaSincronizacion ?? this.ultimaSincronizacion,
    ultimoResumen: ultimoResumen ?? this.ultimoResumen,
    bloqueo: bloqueo != null ? bloqueo() : this.bloqueo,
    sesionVencida: sesionVencida ?? this.sesionVencida,
  );
}

/// Lo que la corrida va acumulando.
class _Corrida {
  _Corrida({required this.empresaId, required this.usuarioId, required this.disparador});

  final int empresaId;
  final int usuarioId;
  final Disparador disparador;

  bool get manual => disparador == Disparador.manual;

  int confirmadas = 0;
  int rechazadas = 0;
  int enConflicto = 0;
  int fallidasPorRed = 0;
  int omitidas = 0;
  int enviadas = 0;
  bool intentado = false;

  /// Un error de red, de sesión o de bloqueo: no tiene sentido seguir con más lotes.
  bool detenido = false;

  bool dispositivoLeido = false;
  String? dispositivo;
}

const _errorSinRespuesta = 'Sin respuesta del servidor';
const _errorTemporal = 'El servidor tuvo un problema temporal. Se reintentará.';

/// El motor de sincronización (D12, D14): manda a `POST /sincronizacion/lote` lo que la cola tiene por enviar y aplica lo que
/// responde el servidor.
///
/// Garantías:
/// - Una operación NUNCA se borra de la cola por un fallo: queda 'registrada' o 'enviada' para reintentar. El reenvío es
///   seguro porque el servidor es idempotente por `operacion_id` (devuelve el estado actual con `duplicada=true`).
/// - Una sola corrida a la vez: un disparo durante otro recibe el MISMO `Future`.
/// - Un fallo en una operación no tumba a las demás (el servidor las procesa cada una en su SAVEPOINT; aquí, un 422 se aísla
///   enviándolas de una en una).
/// - Los registros de diagnóstico (RNF10) llevan el id corto, el tipo, el estado, los intentos y el código del motivo; nunca
///   nombres, documentos, teléfonos ni montos.
class MotorSincronizacion {
  MotorSincronizacion({
    required this._cola,
    required this._api,
    required this._reloj,
    required this._conectividad,
    required this._dispositivoId,
    Duration Function(int intentos)? espera,
    int tamanioLote = tamanioLoteSync,
    this._revisionConflictos = const Duration(minutes: 15),
  }) : _espera = espera ?? calcularEspera,
       _tamanioLote = tamanioLote < 1 ? 1 : tamanioLote;

  final ColaOperaciones _cola;
  final SincronizacionApi _api;
  final Reloj _reloj;
  final ConectividadService _conectividad;
  final Future<String> Function() _dispositivoId;
  final Duration Function(int intentos) _espera;
  final int _tamanioLote;
  final Duration _revisionConflictos;

  final StreamController<EstadoSync> _controlador = StreamController<EstadoSync>.broadcast();
  EstadoSync _estado = const EstadoSync();
  Future<ResumenSync>? _enCurso;
  DateTime? _ultimaRevision;
  bool _cerrado = false;

  EstadoSync get estado => _estado;

  /// Emite cada vez que cambia el estado (empieza, termina, bloqueo, sesión).
  Stream<EstadoSync> get cambiosDeEstado => _controlador.stream;

  /// Quita el bloqueo (p. ej. cuando el administrador arregló el plan y la persona pulsa "Reintentar").
  void limpiarBloqueo() => _fijar(_estado.copiar(bloqueo: () => null));

  /// Borra la marca de sesión vencida (después de volver a iniciar sesión).
  void reiniciarSesion() => _fijar(_estado.copiar(sesionVencida: false));

  void dispose() {
    if (_cerrado) return;
    _cerrado = true;
    unawaited(_controlador.close());
  }

  /// Sincroniza la cola de [usuarioId] en [empresaId]. Si ya hay una corrida, devuelve ESA (no hace otra petición).
  Future<ResumenSync> sincronizar({
    required int empresaId,
    required int usuarioId,
    Disparador disparador = Disparador.manual,
  }) {
    final enCurso = _enCurso;
    if (enCurso != null) return enCurso;

    _fijar(_estado.copiar(enCurso: true));
    final corrida = _Corrida(empresaId: empresaId, usuarioId: usuarioId, disparador: disparador);
    final futuro = _ejecutar(corrida).whenComplete(() {
      _enCurso = null;
      _fijar(_estado.copiar(enCurso: false));
    });
    _enCurso = futuro;
    return futuro;
  }

  // ---- La corrida ------------------------------------------------------------------------

  Future<ResumenSync> _ejecutar(_Corrida c) async {
    final cronometro = Stopwatch()..start();
    String? razonNoIntento;
    if (!c.manual) {
      if (!_conectividad.actual) {
        razonNoIntento = 'sin_conexion';
      } else if (_estado.bloqueo != null) {
        razonNoIntento = 'bloqueo';
      } else if (_estado.sesionVencida) {
        razonNoIntento = 'sesion_vencida';
      }
    }

    if (razonNoIntento == null) {
      await _enviarPendientes(c);
      if (!c.detenido) await _revisarConflictos(c);
    }

    final conteo = await _cola.conteoPorEstado(empresaId: c.empresaId, usuarioId: c.usuarioId);
    final pendientes = (conteo[EstadoOperacion.registrada] ?? 0) + (conteo[EstadoOperacion.enviada] ?? 0);

    final resumen = ResumenSync(
      confirmadas: c.confirmadas,
      rechazadas: c.rechazadas,
      enConflicto: c.enConflicto,
      pendientes: pendientes,
      fallidasPorRed: c.fallidasPorRed,
      omitidasPorEspera: c.omitidas,
      enviadas: c.enviadas,
      intentado: c.intentado,
      bloqueo: _estado.bloqueo,
      sesionVencida: _estado.sesionVencida,
    );
    _fijar(
      _estado.copiar(
        ultimoResumen: resumen,
        ultimaSincronizacion: c.intentado ? _reloj.ahora() : null,
      ),
    );
    _registrar(
      'sync fin disparador=${c.disparador.name} intentado=${c.intentado} ${razonNoIntento == null ? '' : 'omitida=$razonNoIntento '}'
      'enviadas=${c.enviadas} confirmadas=${c.confirmadas} rechazadas=${c.rechazadas} en_conflicto=${c.enConflicto} '
      'pendientes=$pendientes fallidas_red=${c.fallidasPorRed} omitidas_espera=${c.omitidas} ms=${cronometro.elapsedMilliseconds}',
    );
    return resumen;
  }

  Future<void> _enviarPendientes(_Corrida c) async {
    final ahora = _reloj.ahora();
    final candidatas = await _cola.paraEnviar(
      empresaId: c.empresaId,
      usuarioId: c.usuarioId,
      ahora: ahora,
      ignorarEspera: c.manual,
    );
    if (!c.manual) {
      final todas = await _cola.paraEnviar(
        empresaId: c.empresaId,
        usuarioId: c.usuarioId,
        ahora: ahora,
        ignorarEspera: true,
      );
      c.omitidas = todas.length > candidatas.length ? todas.length - candidatas.length : 0;
    }
    if (candidatas.isEmpty) return;

    // Por fecha en que OCURRIERON (D14). La cola ya las entrega así; se reordena por si acaso, sin perder el orden entre iguales.
    final indexadas = [for (var i = 0; i < candidatas.length; i++) (i, candidatas[i])];
    indexadas.sort((a, b) {
      final porFecha = a.$2.fechaOperacion.compareTo(b.$2.fechaOperacion);
      return porFecha != 0 ? porFecha : a.$1.compareTo(b.$1);
    });
    final ordenadas = [for (final e in indexadas) e.$2];

    for (var i = 0; i < ordenadas.length && !c.detenido; i += _tamanioLote) {
      final fin = i + _tamanioLote > ordenadas.length ? ordenadas.length : i + _tamanioLote;
      await _enviarLote(c, ordenadas.sublist(i, fin));
    }
  }

  Future<void> _enviarLote(_Corrida c, List<OperacionPendiente> candidatas) async {
    // Se arma el envío ANTES de marcar nada. Una fila con el payload dañado jamás podría enviarse: se rechaza localmente.
    final operaciones = <OperacionPendiente>[];
    final envios = <OperacionEnvio>[];
    for (final op in candidatas) {
      try {
        envios.add(OperacionEnvio.desde(op));
        operaciones.add(op);
      } catch (_) {
        await _cola.marcarRechazadaLocal(
          op.operacionId,
          motivo: 'Los datos guardados de esta operación están dañados.',
          recibidoEn: _reloj.ahora(),
        );
        c.rechazadas++;
        _registrarOperacion(op, estado: 'rechazada', intentos: op.intentos, motivo: 'datos_danados');
      }
    }
    if (operaciones.isEmpty) return;

    await _leerDispositivo(c);
    await _cola.marcarEnviadas([for (final op in operaciones) op.operacionId]);
    c.intentado = true;
    c.enviadas += operaciones.length;

    final RespuestaLote respuesta;
    try {
      respuesta = await _api.enviarLote(LoteEnvio(dispositivo: c.dispositivo, operaciones: envios));
    } catch (error) {
      await _alFallarEnvio(c, operaciones, error);
      return;
    }
    await _procesarRespuesta(c, operaciones, respuesta);
  }

  /// El identificador del teléfono es opcional en el contrato: si no se puede leer, el lote va sin él.
  Future<void> _leerDispositivo(_Corrida c) async {
    if (c.dispositivoLeido) return;
    c.dispositivoLeido = true;
    try {
      c.dispositivo = await _dispositivoId();
    } catch (_) {
      c.dispositivo = null;
    }
  }

  // ---- Respuesta correcta -----------------------------------------------------------------

  Future<void> _procesarRespuesta(_Corrida c, List<OperacionPendiente> operaciones, RespuestaLote respuesta) async {
    // El servidor respondió: la sesión y el plan sirven.
    if (_estado.bloqueo != null || _estado.sesionVencida) {
      _fijar(_estado.copiar(bloqueo: () => null, sesionVencida: false));
    }

    final porId = <String, ResultadoOperacionSync>{};
    for (final r in respuesta.resultados) {
      porId.putIfAbsent(r.operacionId.toLowerCase(), () => r);
    }

    final aplicables = <ResultadoOperacionSync>[];
    final opDe = <String, OperacionPendiente>{};
    final temporales = <OperacionPendiente>[];
    final sinRespuesta = <OperacionPendiente>[];
    for (final op in operaciones) {
      final r = porId[op.operacionId.toLowerCase()];
      if (r == null) {
        sinRespuesta.add(op);
      } else if (r.estado.aEstadoLocal == null) {
        temporales.add(op);
        _registrarOperacion(op, estado: r.estado.nombre.isEmpty ? 'desconocido' : r.estado.nombre, intentos: _intentosTrasEnvio(op), motivo: r.motivo);
      } else {
        aplicables.add(r);
        opDe[r.operacionId.toLowerCase()] = op;
      }
    }

    if (aplicables.isNotEmpty) {
      final cambiadas = (await _cola.aplicarResultados(aplicables, recibidoEn: _reloj.ahora())).map((i) => i.toLowerCase()).toSet();
      for (final r in aplicables) {
        final op = opDe[r.operacionId.toLowerCase()]!;
        final cambio = cambiadas.contains(r.operacionId.toLowerCase());
        if (cambio) _contar(c, r.estado);
        _registrarOperacion(op, estado: r.estado.nombre, intentos: _intentosTrasEnvio(op), motivo: r.motivo, duplicada: r.duplicada);
      }
    }

    if (temporales.isNotEmpty) {
      await _cola.registrarFalloDeRed(
        [for (final op in temporales) op.operacionId],
        error: _errorTemporal,
        proximoReintento: _reloj.ahora().add(_esperaPara(temporales)),
      );
      c.fallidasPorRed += temporales.length;
    }
    if (sinRespuesta.isNotEmpty) {
      await _cola.registrarFalloDeRed(
        [for (final op in sinRespuesta) op.operacionId],
        error: _errorSinRespuesta,
        proximoReintento: _reloj.ahora().add(_esperaPara(sinRespuesta)),
      );
      c.fallidasPorRed += sinRespuesta.length;
      for (final op in sinRespuesta) {
        _registrarOperacion(op, estado: 'enviada', intentos: _intentosTrasEnvio(op), motivo: 'sin_respuesta');
      }
    }
  }

  void _contar(_Corrida c, EstadoResultadoSync estado) {
    switch (estado) {
      case EstadoResultadoSync.confirmada:
        c.confirmadas++;
      case EstadoResultadoSync.rechazada:
        c.rechazadas++;
      case EstadoResultadoSync.enConflicto:
        c.enConflicto++;
      case EstadoResultadoSync.errorTemporal || EstadoResultadoSync.desconocido:
        break;
    }
  }

  // ---- Errores del lote -------------------------------------------------------------------

  /// Qué hacer con las [operaciones] (ya marcadas 'enviada') cuando el envío falló con [error]. Las operaciones conservan su
  /// registro SIEMPRE: nada se borra.
  Future<void> _alFallarEnvio(_Corrida c, List<OperacionPendiente> operaciones, Object error) async {
    final e = ErrorApp.desde(error);
    final ids = [for (final op in operaciones) op.operacionId];
    final proximo = _reloj.ahora().add(_esperaPara(operaciones));

    // El servidor habla un contrato más nuevo: pudo haber PROCESADAS las operaciones (la respuesta sí llegó), así que siguen
    // 'enviada' y se reenvían con seguridad cuando la app se actualice.
    if (e.tipo == TipoErrorApp.desconocido && e.mensaje == mensajeActualizarApp) {
      await _cola.registrarFalloDeRed(ids, error: e.mensaje, proximoReintento: proximo);
      _fijar(_estado.copiar(bloqueo: () => BloqueoSync(tipo: TipoBloqueo.actualizarApp, mensaje: e.mensaje)));
      c.detenido = true;
      _registrarFallo(operaciones, 'actualizar_app', estado: 'enviada');
      return;
    }

    switch (e.tipo) {
      case TipoErrorApp.sinConexion:
        if (e.posiblementeRecibido) {
          // Pudo llegar y procesarse: siguen 'enviada'. Reenviar es seguro (idempotencia).
          await _cola.registrarFalloDeRed(ids, error: e.mensaje, proximoReintento: proximo);
          _registrarFallo(operaciones, 'sin_conexion_incierta', estado: 'enviada');
        } else {
          await _cola.volverARegistrada(ids, error: e.mensaje, proximoReintento: proximo);
          _registrarFallo(operaciones, 'sin_conexion', estado: 'registrada');
        }
        c.fallidasPorRed += operaciones.length;
        c.detenido = true;
      case TipoErrorApp.noAutorizado:
        // La cola se CONSERVA; no es culpa de la operación (no gasta intento). Vuelve a salir tras iniciar sesión.
        await _cola.volverARegistrada(ids, error: e.mensaje, devolverIntento: true);
        _fijar(_estado.copiar(sesionVencida: true));
        c.detenido = true;
        _registrarFallo(operaciones, 'sesion_vencida', estado: 'registrada');
      case TipoErrorApp.planNoIncluyeFuncionalidad || TipoErrorApp.suscripcionNoActiva:
        await _cola.volverARegistrada(ids, error: e.mensaje, devolverIntento: true);
        final tipo = e.tipo == TipoErrorApp.planNoIncluyeFuncionalidad ? TipoBloqueo.planNoIncluye : TipoBloqueo.suscripcionNoActiva;
        _fijar(_estado.copiar(bloqueo: () => BloqueoSync(tipo: tipo, mensaje: e.mensaje)));
        c.detenido = true;
        _registrarFallo(operaciones, tipo == TipoBloqueo.planNoIncluye ? 'plan_no_incluye' : 'suscripcion_no_activa', estado: 'registrada');
      default:
        if (e.estado == 429 || e.estado == 408) {
          // El servidor pidió esperar: aún no se procesó nada.
          await _cola.volverARegistrada(ids, error: e.mensaje, proximoReintento: proximo);
          c.fallidasPorRed += operaciones.length;
          c.detenido = true;
          _registrarFallo(operaciones, 'http_${e.estado}', estado: 'registrada');
        } else if (e.tipo == TipoErrorApp.validacion || e.estado == 400) {
          await _aislar(c, operaciones, e);
        } else {
          // 5xx y cualquier otro error inesperado: pudo procesarse en parte; siguen 'enviada' y se reenvían.
          await _cola.registrarFalloDeRed(ids, error: e.mensaje, proximoReintento: proximo);
          c.fallidasPorRed += operaciones.length;
          c.detenido = true;
          _registrarFallo(operaciones, e.estado == null ? 'error_inesperado' : 'http_${e.estado}', estado: 'enviada');
        }
    }
  }

  /// El servidor rechazó el lote ENTERO por los datos (422 o 400): se reenvían de una en una para saber cuál es la mala. La que
  /// el servidor siga rechazando con 4xx se rechaza localmente; las demás siguen su curso.
  Future<void> _aislar(_Corrida c, List<OperacionPendiente> operaciones, ErrorApp error) async {
    if (operaciones.length == 1) {
      await _rechazarLocal(c, operaciones.single, error);
      return;
    }
    for (var i = 0; i < operaciones.length; i++) {
      final op = operaciones[i];
      final RespuestaLote respuesta;
      try {
        final envio = OperacionEnvio.desde(op);
        respuesta = await _api.enviarLote(LoteEnvio(dispositivo: c.dispositivo, operaciones: [envio]));
      } catch (e) {
        final ee = ErrorApp.desde(e);
        if (ee.tipo == TipoErrorApp.validacion || ee.estado == 400) {
          await _rechazarLocal(c, op, ee);
          continue;
        }
        // Otro tipo de fallo: se trata como cualquier error de lote, para ESTA operación y las que faltan.
        await _alFallarEnvio(c, operaciones.sublist(i), ee);
        return;
      }
      await _procesarRespuesta(c, [op], respuesta);
    }
  }

  Future<void> _rechazarLocal(_Corrida c, OperacionPendiente op, ErrorApp error) async {
    await _cola.marcarRechazadaLocal(
      op.operacionId,
      motivo: 'El servidor no aceptó los datos (código ${error.estado ?? 422}).',
      recibidoEn: _reloj.ahora(),
    );
    c.rechazadas++;
    _registrarOperacion(op, estado: 'rechazada', intentos: _intentosTrasEnvio(op), motivo: 'http_${error.estado ?? 422}');
  }

  // ---- Revisión de conflictos --------------------------------------------------------------

  /// Un encargado pudo resolver desde la web una operación 'en_conflicto': se pregunta por ella. Un fallo aquí NUNCA afecta a lo
  /// demás.
  Future<void> _revisarConflictos(_Corrida c) async {
    final ahora = _reloj.ahora();
    final ultima = _ultimaRevision;
    final toca = c.manual || ultima == null || ahora.difference(ultima) >= _revisionConflictos;
    if (!toca) return;
    _ultimaRevision = ahora;

    final List<OperacionPendiente> enConflicto;
    try {
      enConflicto = await _cola.paraRevisarConflictos(empresaId: c.empresaId, usuarioId: c.usuarioId);
    } catch (_) {
      return;
    }
    for (final op in enConflicto) {
      try {
        final r = await _api.consultar(op.operacionId);
        if (r == null) continue;
        if (r.estado != EstadoResultadoSync.confirmada && r.estado != EstadoResultadoSync.rechazada) continue;
        // Se aplica con el id que se preguntó, aunque el detalle no lo repita.
        final resultado = r.operacionId.toLowerCase() == op.operacionId.toLowerCase()
            ? r
            : ResultadoOperacionSync(
                operacionId: op.operacionId,
                estado: r.estado,
                motivo: r.motivo,
                mensaje: r.mensaje,
                procesadaEn: r.procesadaEn,
                recurso: r.recurso,
              );
        final cambiadas = await _cola.aplicarResultados([resultado], recibidoEn: _reloj.ahora());
        if (cambiadas.isNotEmpty) {
          _contar(c, r.estado);
          _registrarOperacion(op, estado: r.estado.nombre, intentos: op.intentos, motivo: r.motivo, origen: 'revision');
        }
      } catch (_) {
        // Nunca afecta a lo demás: se volverá a preguntar en la próxima revisión.
      }
    }
  }

  // ---- Ayudas -----------------------------------------------------------------------------

  /// Los intentos que la operación lleva DESPUÉS de marcarla enviada: cada envío es un intento (`marcarEnviadas` suma uno tanto a
  /// una 'registrada' como a una 'enviada' huérfana que se reenvía).
  int _intentosTrasEnvio(OperacionPendiente op) => op.intentos + 1;

  /// La espera sale de la operación con MÁS intentos del grupo.
  Duration _esperaPara(List<OperacionPendiente> operaciones) {
    var mayor = 1;
    for (final op in operaciones) {
      final n = _intentosTrasEnvio(op);
      if (n > mayor) mayor = n;
    }
    return _espera(mayor);
  }

  void _fijar(EstadoSync nuevo) {
    _estado = nuevo;
    if (!_cerrado && !_controlador.isClosed) _controlador.add(nuevo);
  }

  void _registrarOperacion(
    OperacionPendiente op, {
    required String estado,
    required int intentos,
    String? motivo,
    bool duplicada = false,
    String? origen,
  }) {
    _registrar(
      'sync op=${op.codigoCorto} tipo=${op.tipo.nombre} estado=$estado intentos=$intentos'
      '${motivo == null || motivo.isEmpty ? '' : ' motivo=$motivo'}${duplicada ? ' duplicada=si' : ''}${origen == null ? '' : ' origen=$origen'}',
    );
  }

  void _registrarFallo(List<OperacionPendiente> operaciones, String motivo, {required String estado}) {
    for (final op in operaciones) {
      _registrarOperacion(op, estado: estado, intentos: _intentosTrasEnvio(op), motivo: motivo);
    }
  }

  void _registrar(String linea) => debugPrint(linea);
}
