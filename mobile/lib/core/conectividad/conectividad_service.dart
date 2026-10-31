import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config/api_config.dart';

/// Si el dispositivo puede hablar con el servidor. `true` = en línea.
abstract interface class ConectividadService {
  /// Emite solo cuando el estado cambia (nunca dos veces el mismo valor seguido).
  Stream<bool> get enLinea;

  /// El último estado conocido. Arranca en `true` (optimista) hasta la primera verificación.
  bool get actual;

  /// Verifica ahora mismo (interfaz de red y `/health`), actualiza el estado y lo devuelve.
  Future<bool> verificarAhora();
}

/// La fuente de cambios de red del sistema (por defecto, `connectivity_plus`).
typedef FuenteCambiosRed = Stream<List<ConnectivityResult>> Function();

/// Lee el estado actual de las interfaces de red (por defecto, `connectivity_plus`).
typedef LectorEstadoRed = Future<List<ConnectivityResult>> Function();

/// La raíz del servidor: la URL de la API sin el sufijo `/api/v1` (ahí vive `GET /health`).
String raizDeApi(String baseUrl) {
  var raiz = baseUrl.trim();
  while (raiz.endsWith('/')) {
    raiz = raiz.substring(0, raiz.length - 1);
  }
  if (raiz.endsWith('/api/v1')) raiz = raiz.substring(0, raiz.length - '/api/v1'.length);
  return raiz;
}

/// Solo está "en línea" si hay interfaz de red Y el servidor responde 200 en `/health`. El estado del sistema por sí
/// solo engaña (wifi sin internet), por eso cada cambio se confirma con el servidor.
class ConectividadReal implements ConectividadService {
  ConectividadReal({
    FuenteCambiosRed? cambios,
    LectorEstadoRed? lector,
    Dio? dio,
    String? urlHealth,
    this.debounce = const Duration(seconds: 1),
    this.timeout = const Duration(seconds: 4),
  })  : _lector = lector ?? (() => Connectivity().checkConnectivity()),
        _dioPropio = dio == null,
        _dio = dio ?? _crearDio(timeout),
        _urlHealth = urlHealth ?? '${raizDeApi(ApiConfig.baseUrl)}/health' {
    final fuente = cambios ?? (() => Connectivity().onConnectivityChanged);
    _suscripcion = fuente().listen(_alCambiarRed, onError: (_) {});
    // Una vez al iniciar.
    unawaited(_verificarYAplicar(null));
  }

  /// Un Dio APARTE: sin interceptores (ni token ni refresh) para que verificar no dispare nada de la sesión.
  static Dio _crearDio(Duration timeout) {
    return Dio(
      BaseOptions(connectTimeout: timeout, sendTimeout: timeout, receiveTimeout: timeout),
    );
  }

  /// Varios cambios seguidos del sistema emiten una sola verificación pasado este tiempo.
  final Duration debounce;

  /// Tiempo máximo de la verificación de `/health`.
  final Duration timeout;

  final LectorEstadoRed _lector;
  final Dio _dio;
  final bool _dioPropio;
  final String _urlHealth;
  final StreamController<bool> _controlador = StreamController<bool>.broadcast();
  late final StreamSubscription<List<ConnectivityResult>> _suscripcion;

  Timer? _temporizador;
  List<ConnectivityResult>? _ultimoEvento;
  bool _actual = true;
  bool _cerrado = false;

  /// Cada verificación o aviso manual invalida a las que estaban en vuelo (llegarían con información vieja).
  int _generacion = 0;

  @override
  Stream<bool> get enLinea => _controlador.stream;

  @override
  bool get actual => _actual;

  @override
  Future<bool> verificarAhora() {
    _temporizador?.cancel();
    return _verificarYAplicar(null);
  }

  /// Quien hace peticiones reales avisa de un fallo de red (sin respuesta del servidor) sin esperar al sistema.
  void informarFalloDeRed() => _fijarManual(false);

  /// Quien hace peticiones reales avisa de que el servidor respondió: hay conexión.
  void informarRespuestaOk() => _fijarManual(true);

  void _fijarManual(bool valor) {
    if (_cerrado) return;
    _generacion++;
    _temporizador?.cancel();
    _aplicar(valor);
  }

  void _alCambiarRed(List<ConnectivityResult> resultado) {
    if (_cerrado) return;
    _ultimoEvento = resultado;
    _temporizador?.cancel();
    _temporizador = Timer(debounce, () {
      final evento = _ultimoEvento;
      _ultimoEvento = null;
      unawaited(_verificarYAplicar(evento));
    });
  }

  Future<bool> _verificarYAplicar(List<ConnectivityResult>? interfaces) async {
    final generacion = ++_generacion;
    var valor = false;
    try {
      final redes = interfaces ?? await _lector();
      valor = await _evaluar(redes);
    } catch (_) {
      valor = false;
    }
    // Si llegó un aviso manual u otra verificación más nueva, este resultado ya es viejo.
    if (generacion != _generacion || _cerrado) return _actual;
    _aplicar(valor);
    return valor;
  }

  Future<bool> _evaluar(List<ConnectivityResult> redes) async {
    final sinInterfaz = redes.isEmpty || redes.every((r) => r == ConnectivityResult.none);
    if (sinInterfaz) return false;
    try {
      final respuesta = await _dio
          .get<Object?>(
            _urlHealth,
            options: Options(validateStatus: (_) => true, sendTimeout: timeout, receiveTimeout: timeout),
          )
          .timeout(timeout);
      return respuesta.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  void _aplicar(bool valor) {
    if (valor == _actual) return;
    _actual = valor;
    if (!_controlador.isClosed) _controlador.add(valor);
  }

  void dispose() {
    if (_cerrado) return;
    _cerrado = true;
    _temporizador?.cancel();
    unawaited(_suscripcion.cancel());
    unawaited(_controlador.close());
    if (_dioPropio) _dio.close(force: true);
  }
}

final conectividadServiceProvider = Provider<ConectividadService>((ref) {
  final servicio = ConectividadReal();
  ref.onDispose(servicio.dispose);
  return servicio;
});

/// `true` en línea. Emite primero el estado actual y luego cada cambio.
final enLineaProvider = StreamProvider<bool>((ref) {
  final servicio = ref.watch(conectividadServiceProvider);
  // Primero se escucha el servicio y luego se mete el valor actual: así no se pierde un cambio que ocurra entre los dos.
  final controlador = StreamController<bool>();
  final suscripcion = servicio.enLinea.listen(controlador.add);
  controlador.add(servicio.actual);
  ref.onDispose(() {
    unawaited(suscripcion.cancel());
    unawaited(controlador.close());
  });
  return controlador.stream;
});
