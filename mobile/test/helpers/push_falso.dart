import 'dart:async';

import 'package:mobile/core/push/almacen_push.dart';
import 'package:mobile/core/push/servicio_push.dart';

/// Doble de [ServicioPush] para tests: nada toca Firebase. El permiso, el token y los avisos se manejan a mano.
class ServicioPushFalso implements ServicioPush {
  ServicioPushFalso({this.permiso = true, this.concedeAlPedir = true, this.token = 'TOKEN-A'});

  /// Si el permiso de notificaciones ya está concedido.
  bool permiso;

  /// Lo que responde el diálogo del sistema cuando se pide el permiso.
  bool concedeAlPedir;

  /// El token del dispositivo (null = Firebase no lo da).
  String? token;

  /// Hace que `obtenerToken` lance, como si Firebase fallara por dentro.
  bool fallaAlObtenerToken = false;

  /// Hace que `iniciar` lance (un servicio real no debería hacerlo; comprueba que la app aguanta aunque pase).
  bool fallaAlIniciar = false;

  int iniciadas = 0;
  int permisosPedidos = 0;

  final StreamController<String> _refresco = StreamController<String>.broadcast();
  final StreamController<AvisoPush> _abierto = StreamController<AvisoPush>.broadcast();
  final StreamController<AvisoPush> _primerPlano = StreamController<AvisoPush>.broadcast();

  /// Un aviso que se entrega apenas se llama a `iniciar` (la app se abrió tocando una notificación).
  AvisoPush? avisoInicial;

  void refrescarToken(String nuevo) => _refresco.add(nuevo);

  void tocarAviso(AvisoPush aviso) => _abierto.add(aviso);

  void recibirEnPrimerPlano(AvisoPush aviso) => _primerPlano.add(aviso);

  @override
  Future<void> iniciar() async {
    iniciadas++;
    if (fallaAlIniciar) throw StateError('Firebase no responde');
    final inicial = avisoInicial;
    if (inicial != null) _abierto.add(inicial);
  }

  @override
  Future<bool> permisoConcedido() async => permiso;

  @override
  Future<bool> solicitarPermiso() async {
    permisosPedidos++;
    permiso = concedeAlPedir;
    return permiso;
  }

  @override
  Future<String?> obtenerToken() async {
    if (fallaAlObtenerToken) throw StateError('Firebase no responde');
    return token;
  }

  @override
  Stream<String> get alRefrescarToken => _refresco.stream;

  @override
  Stream<AvisoPush> get alAbrirAviso => _abierto.stream;

  @override
  Stream<AvisoPush> get alRecibirEnPrimerPlano => _primerPlano.stream;
}

/// Doble en memoria de [AlmacenPush]: el real usa flutter_secure_storage, que no existe en `flutter test`.
class AlmacenPushFalso extends AlmacenPush {
  AlmacenPushFalso({this.registrado, this.pendiente});

  String? registrado;
  String? pendiente;

  @override
  Future<String?> leerTokenRegistrado() async => registrado;

  @override
  Future<void> guardarTokenRegistrado(String token) async => registrado = token;

  @override
  Future<void> borrarTokenRegistrado() async => registrado = null;

  @override
  Future<String?> leerBajaPendiente() async => pendiente;

  @override
  Future<void> guardarBajaPendiente(String token) async => pendiente = token;

  @override
  Future<void> borrarBajaPendiente() async => pendiente = null;
}
