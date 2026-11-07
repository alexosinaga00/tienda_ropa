import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../../core/conectividad/conectividad_service.dart';
import '../../../core/network/error_app.dart';
import '../../../core/sync/backoff.dart';
import '../../../core/sync/generador_uuid.dart';
import '../../../core/utils/reloj.dart';
import '../config/cliente_offline_config.dart';
import '../data/pedidos_diferidos_api.dart';
import '../data/repositorio_cliente.dart';
import '../models/linea_carrito_local.dart';
import '../models/pedido_diferido_api.dart';
import '../models/pedido_sin_conexion.dart';

/// En qué está la cola de pedidos hechos sin conexión.
enum FaseCola {
  inactiva,
  sincronizando,
  esperandoReintento,
  sinConexion,

  /// La sesión venció: no se envía nada hasta que la MISMA persona vuelva a iniciar sesión.
  pausadaSesion,

  /// La tienda no puede recibir pedidos ahora (suscripción, plan o permiso). No es un rechazo del pedido.
  pausada,

  /// Demasiados fallos seguidos: espera el botón "Reintentar".
  detenidaPorFallos,
}

class EstadoCola {
  const EstadoCola({this.fase = FaseCola.inactiva, this.motivoPausa, this.proximoIntentoEn});

  final FaseCola fase;

  /// Texto para la persona cuando la cola está pausada o detenida.
  final String? motivoPausa;

  /// Cuándo se reintentará sola; null si no hay un reintento programado.
  final DateTime? proximoIntentoEn;

  /// Detenida a la espera de que la persona haga algo (iniciar sesión, "Reintentar").
  bool get detenida => fase == FaseCola.pausadaSesion || fase == FaseCola.pausada || fase == FaseCola.detenidaPorFallos;
}

/// Lo que hace falta para poner un pedido en la cola.
class EntradaPedido {
  const EntradaPedido({
    required this.sucursalId,
    required this.sucursalNombre,
    required this.lineas,
    this.costoEnvioCentavos = 0,
  });

  final int sucursalId;
  final String sucursalNombre;

  /// Sin conexión solo se ofrece retiro en sucursal: normalmente 0.
  final int costoEnvioCentavos;
  final List<LineaCarritoLocal> lineas;
}

enum _Seguir { seguir, detener }

/// Cola de PEDIDOS hechos sin conexión que se pagan con el PayPal guardado.
///
/// Reglas que no se rompen:
///  - Un pedido NUNCA se borra por intentar enviarlo: solo cambia de estado. Cualquier fallo lo deja `pendiente` (con su
///    espera) y el reenvío usa la MISMA `operacion_id`: el servidor no cobra dos veces y devuelve lo ya decidido.
///  - Los pedidos salen UNO A UNO y en orden (el más antiguo primero). Si uno falla por algo temporal, los demás esperan.
///  - Un solo ciclo a la vez: un disparo durante un ciclo no envía en paralelo; hace que, al terminar, corra otro.
///  - Solo se envían los pedidos de la persona de la sesión (el repositorio lo garantiza).
///  - Un `pendiente` con más de [pedidoCaducaDias] días NO se envía: pasa a `vencido`. Se revisa al inicio de cada ciclo y
///    antes de cada envío. Un `enviando` no vence (el servidor pudo haberlo decidido).
///
/// Disparadores (los conecta `DisparadorColaPedidos`): volver la red, iniciar sesión o abrir la app con sesión, volver al
/// primer plano, un temporizador de 60 s, encolar un pedido y el botón "Enviar ahora".
class ColaPedidos {
  ColaPedidos({
    required this._repositorio,
    required this._alcanceActual,
    required this._api,
    required this._reloj,
    required this._conectividad,
    this._generador = const GeneradorUuidV4(),
    this._espera = calcularEspera,
    this._tiempoLimite = tiempoLimitePedido,
    this._temporizador = Timer.new,
    this.alFaltarMetodoPago,
  });

  /// El repositorio de la persona de la sesión (abre la base si hace falta), o null si no hay un cliente con sesión.
  final Future<RepositorioCliente?> Function() _repositorio;

  /// Con quién es la sesión AHORA (síncrono): permite saber, en medio de un envío, si la persona cambió.
  final AlcanceCliente? Function() _alcanceActual;
  final PedidosDiferidosApi _api;
  final Reloj _reloj;
  final ConectividadService _conectividad;
  final GeneradorUuid _generador;
  final Duration Function(int intentos) _espera;
  final Duration _tiempoLimite;
  final Timer Function(Duration espera, void Function() accion) _temporizador;

  /// Se llama cuando el servidor dice que no hay PayPal guardado: lo recordado ya no es cierto.
  final Future<void> Function()? alFaltarMetodoPago;

  final StreamController<PedidoSinConexion> _resueltos = StreamController<PedidoSinConexion>.broadcast();
  final StreamController<EstadoCola> _estados = StreamController<EstadoCola>.broadcast();
  final StreamController<void> _cambios = StreamController<void>.broadcast();
  EstadoCola _estado = const EstadoCola();

  Future<void>? _ciclo;
  bool _otroCiclo = false;
  bool _otroManual = false;
  bool _otroReanudar = false;
  int _fallosSeguidos = 0;
  Timer? _reintento;
  bool _alcanceObservado = false;
  String? _claveActual;
  String? _clavePausadaPorSesion;
  bool _cerrada = false;

  EstadoCola get estado => _estado;

  /// Emite cada vez que cambia el estado de la cola.
  Stream<EstadoCola> get estados => _estados.stream;

  /// Emite cada vez que cambia la lista de pedidos (nuevo, enviando, resuelto, descartado...).
  Stream<void> get cambios => _cambios.stream;

  /// Emite un pedido cuando el servidor lo cobró o lo rechazó (para avisar a la persona con un mensaje).
  Stream<PedidoSinConexion> get resueltos => _resueltos.stream;

  void dispose() {
    if (_cerrada) return;
    _cerrada = true;
    _cancelarReintento();
    unawaited(_resueltos.close());
    unawaited(_estados.close());
    unawaited(_cambios.close());
  }

  // ---- Interfaz pública ------------------------------------------------------------------------------------------

  /// Mis pedidos, del más nuevo al más viejo. Vacío sin sesión o si la base local falla.
  Future<List<PedidoSinConexion>> pedidos() async {
    final repo = await _repo();
    if (repo == null) return const [];
    try {
      return await repo.pedidos();
    } catch (e) {
      debugPrint('cola_pedidos no se pudo leer error=${e.runtimeType}');
      return const [];
    }
  }

  /// Cuántos pedidos míos siguen sin enviar (los vencidos y los resueltos no cuentan).
  Future<int> contarSinEnviar() async {
    final repo = await _repo();
    if (repo == null) return 0;
    try {
      return await repo.contarSinEnviar();
    } catch (_) {
      return 0;
    }
  }

  /// Pone el pedido en la cola y vacía el carrito local EN LA MISMA transacción. Devuelve el pedido, o null si no hay
  /// sesión, el carrito está vacío o es demasiado grande. Con red, la cola intenta enviarlo enseguida.
  Future<PedidoSinConexion?> encolar(EntradaPedido entrada) async {
    final repo = await _repo();
    if (repo == null || entrada.lineas.isEmpty || entrada.lineas.length > maxLineasPedido) return null;

    final ahora = _reloj.ahora().toUtc();
    final pedido = PedidoSinConexion(
      empresaId: repo.alcance.empresaId,
      usuarioId: repo.alcance.usuarioId,
      operacionId: _generador.nuevo(),
      estado: EstadoPedidoLocal.pendiente,
      sucursalId: entrada.sucursalId,
      sucursalNombre: entrada.sucursalNombre,
      costoEnvioCentavos: entrada.costoEnvioCentavos,
      lineas: [
        for (final l in entrada.lineas)
          LineaPedidoLocal(
            varianteId: l.varianteId,
            cantidad: l.cantidad,
            productoNombre: l.productoNombre,
            talla: l.talla,
            color: l.color,
            precioUnitarioCentavos: l.precioUnitarioCentavos,
            imagen: l.imagen,
          ),
      ],
      totalMaximoCentavos: totalDeLineasCentavos(entrada.lineas) + entrada.costoEnvioCentavos,
      fechaPedido: ahora.toIso8601String(),
      creadoEn: ahora,
    );
    final PedidoSinConexion guardado;
    try {
      guardado = await repo.registrarPedido(pedido, vaciarElCarrito: true);
    } catch (e) {
      debugPrint('cola_pedidos no se pudo guardar error=${e.runtimeType}');
      return null;
    }
    _notificarCambio();
    _notificarNuevoPedido();
    return guardado;
  }

  /// Quita un pedido que todavía no salió (o que venció). Devuelve false si no existe, ya se está enviando o está resuelto.
  Future<bool> descartar(String operacionId) async {
    final repo = await _repo();
    if (repo == null) return false;
    try {
      final quitado = await repo.descartarPedido(operacionId);
      _notificarCambio();
      return quitado;
    } catch (e) {
      debugPrint('cola_pedidos no se pudo descartar error=${e.runtimeType}');
      return false;
    }
  }

  /// "Borrarlos y salir": quita del teléfono todo lo de esta cuenta, también los pedidos sin enviar. Nunca lanza; devuelve
  /// false si no se pudo.
  Future<bool> borrarTodoDeEstaCuenta() async {
    final repo = await _repo();
    if (repo == null) return true;
    try {
      await repo.borrarTodo();
    } catch (e) {
      debugPrint('cola_pedidos no se pudo borrar error=${e.runtimeType}');
      return false;
    }
    _notificarCambio();
    return true;
  }

  /// La persona ya vio los resultados: dejan de contarse como nuevos.
  Future<void> marcarVistos() async {
    final repo = await _repo();
    if (repo == null) return;
    try {
      await repo.marcarVistos();
    } catch (e) {
      debugPrint('cola_pedidos no se pudo marcar vistos error=${e.runtimeType}');
    }
    _notificarCambio();
  }

  /// "Enviar ahora" / "Reintentar": ignora la espera de los reintentos y levanta una pausa o una detención (salvo la de
  /// sesión vencida, que solo se levanta al volver a entrar). Nunca lanza.
  Future<void> enviarAhora() => procesar(manual: true);

  /// Volvió la red: levanta una pausa o una detención, pero respeta la espera de cada pedido.
  void alVolverConexion() {
    _fallosSeguidos = 0;
    unawaited(procesar(reanudar: true));
  }

  /// Entra, sale o cambia la persona de la sesión: arranca o se reinicia la cola de esa persona (también al abrir la app
  /// con sesión). Lo guardado en el teléfono NO se toca.
  void alCambiarAlcance(AlcanceCliente? alcance) {
    final clave = alcance?.clave;
    if (_alcanceObservado && clave == _claveActual) return;
    _alcanceObservado = true;
    _claveActual = clave;

    if (clave == null) {
      _cancelarReintento();
      if (_estado.fase != FaseCola.pausadaSesion) {
        _reiniciarEstado();
      } else {
        _fijar(EstadoCola(fase: _estado.fase, motivoPausa: _estado.motivoPausa));
      }
      _notificarCambio();
      return;
    }

    if (_estado.fase == FaseCola.pausadaSesion && _clavePausadaPorSesion == clave) {
      // La misma persona volvió a iniciar sesión: sus pedidos siguen guardados y se reanuda.
      _limpiarPausa();
      _fallosSeguidos = 0;
    } else {
      _reiniciarEstado();
    }
    _notificarCambio();
    // Si todavía corre el ciclo de la persona anterior, el de esta empieza cuando aquel termine.
    if (_ciclo != null) {
      _otroCiclo = true;
    } else {
      unawaited(procesar());
    }
  }

  /// Un solo ciclo a la vez: un segundo disparo NO envía en paralelo; hace que, al terminar éste, corra otro con lo pedido.
  Future<void> procesar({bool manual = false, bool reanudar = false}) {
    final enCurso = _ciclo;
    if (enCurso != null) {
      _otroCiclo = true;
      _otroManual = _otroManual || manual;
      _otroReanudar = _otroReanudar || reanudar;
      return enCurso;
    }
    final ciclo = _ejecutarCiclo(manual: manual, reanudar: reanudar)
        .catchError((Object error) {
          debugPrint('cola_pedidos fallo inesperado error=${error.runtimeType}; los pedidos siguen guardados');
        })
        .whenComplete(() {
          _ciclo = null;
          if (_otroCiclo && !_cerrada) {
            final siguienteManual = _otroManual;
            final siguienteReanudar = _otroReanudar;
            _otroCiclo = false;
            _otroManual = false;
            _otroReanudar = false;
            unawaited(procesar(manual: siguienteManual, reanudar: siguienteReanudar));
          }
        });
    _ciclo = ciclo;
    return ciclo;
  }

  /// Anuncia un pedido resuelto como si lo hubiera decidido el servidor. Para las pruebas de quien escucha.
  @visibleForTesting
  void anunciarResuelto(PedidoSinConexion pedido) {
    if (!_cerrada && !_resueltos.isClosed) _resueltos.add(pedido);
  }

  /// Espera a que no quede ningún ciclo en marcha (ni el que se disparó mientras corría otro). Para las pruebas.
  @visibleForTesting
  Future<void> esperarCiclos() async {
    while (_ciclo != null) {
      await _ciclo;
    }
  }

  // ---- Estado --------------------------------------------------------------------------------------------------------

  void _fijar(EstadoCola nuevo) {
    _estado = nuevo;
    if (!_cerrada && !_estados.isClosed) _estados.add(nuevo);
  }

  void _notificarCambio() {
    if (!_cerrada && !_cambios.isClosed) _cambios.add(null);
  }

  void _reiniciarEstado() {
    _cancelarReintento();
    _limpiarPausa();
    _fallosSeguidos = 0;
  }

  void _limpiarPausa() {
    _clavePausadaPorSesion = null;
    _fijar(const EstadoCola());
  }

  bool _mismoAlcance(AlcanceCliente capturado) => _alcanceActual() == capturado;

  /// El repositorio, o null si no hay sesión o si la base local no abre (nunca lanza).
  Future<RepositorioCliente?> _repo() async {
    try {
      return await _repositorio();
    } catch (e) {
      debugPrint('cola_pedidos no se pudo abrir la base error=${e.runtimeType}');
      return null;
    }
  }

  void _notificarNuevoPedido() {
    if (_ciclo != null) {
      // El pedido se guardó después de que el ciclo leyó su lista: al terminar, el ciclo vuelve a mirar.
      _otroCiclo = true;
      return;
    }
    // Con un reintento ya programado (el servidor falló hace poco) no se martilla: el nuevo sale con el siguiente intento.
    if (_estado.fase == FaseCola.esperandoReintento) return;
    unawaited(procesar());
  }

  // ---- Ciclo ---------------------------------------------------------------------------------------------------------

  Future<void> _ejecutarCiclo({required bool manual, required bool reanudar}) async {
    final repo = await _repo();
    if (repo == null) return;
    final alcance = repo.alcance;
    final forzado = manual || reanudar;

    // Primero lo vencido: un pedido de más de 7 días no se envía y no cuenta como pendiente (también sin conexión).
    await _vencerCaducados(repo);

    final enLinea = manual ? await _conectividad.verificarAhora() : _conectividad.actual;
    if (!enLinea) {
      _notificarCambio();
      if (!_estado.detenida && await repo.contarSinEnviar() > 0) {
        _cancelarReintento();
        _fijar(const EstadoCola(fase: FaseCola.sinConexion));
      }
      return;
    }

    // Una sesión vencida solo se levanta al volver a entrar (lo maneja el cambio de sesión), no con la red ni el botón.
    if (_estado.fase == FaseCola.pausadaSesion) return;
    if (_estado.detenida && !forzado) return;
    if (_estado.detenida) _limpiarPausa();
    if (forzado) _fallosSeguidos = 0;
    _cancelarReintento();

    var detener = false;
    final pedidos = await repo.pedidosParaEnviar(_reloj.ahora(), huerfanoEnviando);
    for (final pedido in pedidos) {
      if (!_mismoAlcance(alcance)) return;
      // Orden estricto: si el más antiguo todavía espera su turno, los demás también.
      final proximo = pedido.proximoIntentoEn;
      if (!manual && proximo != null && proximo.isAfter(_reloj.ahora())) break;
      // La caducidad se revisa ANTES de cada envío (un ciclo largo o una espera pudo hacerlo vencer).
      if (pedido.estado == EstadoPedidoLocal.pendiente && _caducado(pedido)) {
        await _marcarVencido(repo, pedido.operacionId);
        continue;
      }

      _fijar(const EstadoCola(fase: FaseCola.sincronizando));
      if (!await repo.marcarEnviando(pedido.operacionId, _reloj.ahora())) continue;
      _notificarCambio();

      if (await _enviarUno(repo, alcance, pedido) == _Seguir.detener) {
        detener = true;
        break;
      }
    }

    if (!_mismoAlcance(alcance)) return;
    _notificarCambio();
    if (!detener) await _fijarEstadoTrasCiclo(repo);
  }

  /// Más de [pedidoCaducaDias] días desde que se creó en este teléfono.
  bool _caducado(PedidoSinConexion pedido) => _reloj.ahora().difference(pedido.creadoEn) > pedidoCaduca;

  Future<bool> _marcarVencido(RepositorioCliente repo, String operacionId) {
    return _cambiar(repo, operacionId, {
      'estado': EstadoPedidoLocal.vencido.name,
      'motivo': motivoPedidoVencido,
      'mensaje': mensajePedidoVencido,
      'resuelto_en': _iso(_reloj.ahora()),
      'ultimo_error': null,
      'proximo_intento_en': null,
      'visto': 0,
    });
  }

  /// Pasa a `vencido` los pedidos pendientes que ya pasaron el plazo. Solo los `pendiente`: un `enviando` puede estar
  /// decidido en el servidor.
  Future<void> _vencerCaducados(RepositorioCliente repo) async {
    var alguno = false;
    try {
      for (final pedido in await repo.pedidos()) {
        if (pedido.estado == EstadoPedidoLocal.pendiente &&
            _caducado(pedido) &&
            await _marcarVencido(repo, pedido.operacionId)) {
          alguno = true;
        }
      }
    } catch (e) {
      debugPrint('cola_pedidos no se pudo revisar la caducidad error=${e.runtimeType}');
    }
    if (alguno) _notificarCambio();
  }

  /// Envía UN pedido y guarda lo que pase.
  Future<_Seguir> _enviarUno(RepositorioCliente repo, AlcanceCliente alcance, PedidoSinConexion pedido) async {
    final cuerpo = PedidoDiferidoCrear(
      operacionId: pedido.operacionId,
      sucursalId: pedido.sucursalId,
      costoEnvioCentavos: pedido.costoEnvioCentavos,
      lineas: [for (final l in pedido.lineas) (varianteId: l.varianteId, cantidad: l.cantidad)],
      totalMaximoCentavos: pedido.totalMaximoCentavos,
      fechaPedido: pedido.fechaPedido,
    );

    final PedidoDiferidoRespuesta respuesta;
    try {
      respuesta = await _api.enviar(cuerpo).timeout(_tiempoLimite);
    } on TimeoutException {
      return _devolverPorFallo(repo, pedido, 'timeout');
    } on ErrorApp catch (e) {
      return _alFallar(repo, alcance, pedido, e);
    } catch (_) {
      return _devolverPorFallo(repo, pedido, 'error_red');
    }

    // El servidor también vence los pedidos de más de 7 días: decisión final, con un texto claro en vez del genérico.
    final mensaje = respuesta.motivo == motivoPedidoVencido ? mensajePedidoVencidoServidor : respuesta.mensaje;
    final guardado = await _cambiar(repo, pedido.operacionId, {
      'estado': respuesta.cobrado ? EstadoPedidoLocal.cobrado.name : EstadoPedidoLocal.rechazado.name,
      'motivo': respuesta.motivo,
      'mensaje': mensaje.isEmpty ? null : mensaje,
      'venta_id': respuesta.ventaId,
      'codigo_venta': respuesta.codigoVenta,
      'total_centavos': respuesta.totalCentavos,
      'total_usd': respuesta.totalUsd,
      'resuelto_en': _iso(_reloj.ahora()),
      'ultimo_error': null,
      'proximo_intento_en': null,
      'visto': 0,
    });
    _fallosSeguidos = 0;
    if (guardado && _mismoAlcance(alcance)) {
      final resuelto = await repo.pedido(pedido.operacionId);
      if (resuelto != null) await _avisarResultado(resuelto);
    }
    return _Seguir.seguir;
  }

  Future<_Seguir> _alFallar(
    RepositorioCliente repo,
    AlcanceCliente alcance,
    PedidoSinConexion pedido,
    ErrorApp e,
  ) async {
    final estado = e.estado;

    if (estado == 401 || e.tipo == TipoErrorApp.noAutorizado) {
      // El cliente HTTP ya intentó renovar la sesión: si llegó aquí, venció. El pedido sigue guardado.
      await _volverAPendiente(repo, pedido.operacionId, 'sesion_vencida', null);
      _cancelarReintento();
      if (_mismoAlcance(alcance)) {
        _clavePausadaPorSesion = alcance.clave;
        _fijar(const EstadoCola(fase: FaseCola.pausadaSesion, motivoPausa: motivoPausadaPorSesion));
      }
      return _Seguir.detener;
    }

    if (estado == 403 ||
        e.tipo == TipoErrorApp.prohibido ||
        e.tipo == TipoErrorApp.planNoIncluyeFuncionalidad ||
        e.tipo == TipoErrorApp.suscripcionNoActiva) {
      // La tienda no puede recibir pedidos ahora (suscripción, plan o permiso): no es un rechazo del pedido.
      final codigo = e.codigo ?? 'http_403';
      await _volverAPendiente(repo, pedido.operacionId, codigo, null);
      _cancelarReintento();
      if (_mismoAlcance(alcance)) {
        _fijar(
          EstadoCola(
            fase: FaseCola.pausada,
            motivoPausa: e.tipo == TipoErrorApp.suscripcionNoActiva
                ? 'La tienda no puede recibir pedidos por ahora. Tu pedido sigue guardado: inténtalo más tarde.'
                : 'No pudimos enviar tu pedido porque tu cuenta no tiene permiso para comprar. Tu pedido sigue guardado.',
          ),
        );
      }
      return _Seguir.detener;
    }

    if (estado == 400 || estado == 422) {
      // El servidor dice que el pedido tiene mala forma: reintentar no lo arregla. No se cobró; queda a la vista para
      // descartarlo.
      await _cambiar(repo, pedido.operacionId, {
        'estado': EstadoPedidoLocal.rechazado.name,
        'motivo': motivoPedidoInvalido,
        'mensaje': mensajePedidoInvalido,
        'resuelto_en': _iso(_reloj.ahora()),
        'ultimo_error': 'http_$estado',
        'proximo_intento_en': null,
        'visto': 0,
      });
      _fallosSeguidos = 0;
      return _Seguir.seguir;
    }

    if (estado == 429) return _devolverPorFallo(repo, pedido, 'http_429', e.reintentarDespues);

    if (e.tipo == TipoErrorApp.sinConexion) {
      if (!_conectividad.actual) {
        // Se fue la red a mitad del envío: no es un fallo del servidor. Espera sin castigo hasta volver la conexión.
        await _volverAPendiente(repo, pedido.operacionId, 'sin_conexion', null);
        _cancelarReintento();
        if (_mismoAlcance(alcance)) _fijar(const EstadoCola(fase: FaseCola.sinConexion));
        return _Seguir.detener;
      }
      return _devolverPorFallo(repo, pedido, 'sin_conexion');
    }

    // 503 `paypal_no_disponible` (resultado incierto) y cualquier otro fallo del servidor: se reintenta con la misma
    // operacion_id.
    return _devolverPorFallo(repo, pedido, e.codigo ?? (estado == null ? 'error_inesperado' : 'http_$estado'));
  }

  /// Red, tiempo agotado, 503, 5xx, 429...: el pedido vuelve a `pendiente` con espera y el ciclo termina.
  Future<_Seguir> _devolverPorFallo(
    RepositorioCliente repo,
    PedidoSinConexion pedido,
    String motivo, [
    Duration? esperaFija,
  ]) async {
    final espera = esperaFija ?? _espera(_fallosSeguidos + 1);
    await _volverAPendiente(repo, pedido.operacionId, motivo, espera);
    _registrarFallo(espera);
    return _Seguir.detener;
  }

  /// Suma un fallo seguido: reintenta sola con espera creciente y, pasado el tope, se detiene (siguen guardados).
  void _registrarFallo(Duration espera) {
    _fallosSeguidos += 1;
    if (_fallosSeguidos >= fallosAutomaticosMax) {
      _cancelarReintento();
      _fijar(const EstadoCola(fase: FaseCola.detenidaPorFallos, motivoPausa: motivoDetenidaPorFallos));
      return;
    }
    _programarReintento(espera);
  }

  // ---- Reintentos ----------------------------------------------------------------------------------------------------

  void _programarReintento(Duration espera) {
    _cancelarReintento();
    _fijar(EstadoCola(fase: FaseCola.esperandoReintento, proximoIntentoEn: _reloj.ahora().add(espera)));
    // Unos milisegundos de margen: al despertar, la espera del pedido ya tiene que haber pasado.
    _reintento = _temporizador(espera + const Duration(milliseconds: 25), () {
      _reintento = null;
      unawaited(procesar());
    });
  }

  void _cancelarReintento() {
    _reintento?.cancel();
    _reintento = null;
  }

  /// Terminado un ciclo sin fallos: si algún pedido sigue esperando su turno, se programa; si no, la cola descansa.
  Future<void> _fijarEstadoTrasCiclo(RepositorioCliente repo) async {
    if (_estado.detenida) return;
    DateTime? proxima;
    try {
      final ahora = _reloj.ahora();
      final esperando = (await repo.pedidosParaEnviar(
        ahora,
        huerfanoEnviando,
      )).map((p) => p.proximoIntentoEn).whereType<DateTime>().where((t) => t.isAfter(ahora));
      if (esperando.isNotEmpty) proxima = esperando.reduce((a, b) => a.isBefore(b) ? a : b);
    } catch (_) {
      proxima = null;
    }
    if (proxima != null) {
      final falta = proxima.difference(_reloj.ahora());
      _programarReintento(falta.isNegative ? Duration.zero : falta);
      return;
    }
    _cancelarReintento();
    _fijar(const EstadoCola());
  }

  // ---- Escrituras seguras y avisos -------------------------------------------------------------------------------------

  Future<void> _volverAPendiente(RepositorioCliente repo, String operacionId, String motivo, Duration? espera) async {
    await _cambiar(repo, operacionId, {
      'estado': EstadoPedidoLocal.pendiente.name,
      'ultimo_error': motivo,
      'proximo_intento_en': espera == null ? null : _iso(_reloj.ahora().add(espera)),
    });
  }

  /// Cambia un pedido sin lanzar: si no se puede (ya era final, falló la base) queda como estaba y se recupera después.
  Future<bool> _cambiar(RepositorioCliente repo, String operacionId, Map<String, Object?> cambios) async {
    try {
      await repo.actualizarPedido(operacionId, cambios);
      _notificarCambio();
      return true;
    } catch (e) {
      debugPrint('cola_pedidos no se pudo actualizar un pedido error=${e.runtimeType}');
      return false;
    }
  }

  /// Avisa cuando un pedido pasa a cobrado o rechazado. Si no tenía PayPal guardado, se recuerda para decidir sin red.
  Future<void> _avisarResultado(PedidoSinConexion pedido) async {
    if (pedido.estado == EstadoPedidoLocal.rechazado && pedido.motivo == motivoSinMetodoPago) {
      try {
        await alFaltarMetodoPago?.call();
      } catch (_) {
        // Recordarlo es un extra.
      }
    }
    if (!_cerrada && !_resueltos.isClosed) _resueltos.add(pedido);
  }

  String _iso(DateTime fecha) => fecha.toUtc().toIso8601String();
}
