import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Lo que la app recuerda de las notificaciones push entre aperturas, en el almacenamiento seguro (mismo criterio que
/// [TokenStorage]): el último token registrado en el servidor y el token cuya baja quedó pendiente (se cerró la sesión
/// sin red). Solo guarda el token del dispositivo, nunca datos de la cuenta. Las pruebas lo reemplazan por un falso.
class AlmacenPush {
  const AlmacenPush();

  static const _claveRegistrado = 'fs_push_token_registrado';
  static const _clavePendiente = 'fs_push_baja_pendiente';

  static const _storage = FlutterSecureStorage();

  /// El último token que el servidor aceptó para la sesión que está abierta (o estuvo abierta).
  Future<String?> leerTokenRegistrado() => _storage.read(key: _claveRegistrado);

  Future<void> guardarTokenRegistrado(String token) => _storage.write(key: _claveRegistrado, value: token);

  Future<void> borrarTokenRegistrado() => _storage.delete(key: _claveRegistrado);

  /// El token al que le falta avisar su baja al servidor.
  Future<String?> leerBajaPendiente() => _storage.read(key: _clavePendiente);

  Future<void> guardarBajaPendiente(String token) => _storage.write(key: _clavePendiente, value: token);

  Future<void> borrarBajaPendiente() => _storage.delete(key: _clavePendiente);
}

/// Lo mismo en memoria, sin tocar el dispositivo. Es el valor por defecto del proveedor (así las pruebas que no lo
/// reemplazan, como las de cerrar sesión, no esperan a un canal de plataforma); `main.dart` pone el real.
class AlmacenPushMemoria extends AlmacenPush {
  AlmacenPushMemoria();

  String? _registrado;
  String? _pendiente;

  @override
  Future<String?> leerTokenRegistrado() async => _registrado;

  @override
  Future<void> guardarTokenRegistrado(String token) async => _registrado = token;

  @override
  Future<void> borrarTokenRegistrado() async => _registrado = null;

  @override
  Future<String?> leerBajaPendiente() async => _pendiente;

  @override
  Future<void> guardarBajaPendiente(String token) async => _pendiente = token;

  @override
  Future<void> borrarBajaPendiente() async => _pendiente = null;
}
