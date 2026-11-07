import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

import 'servicio_push.dart';

/// Se ejecuta en un aislado aparte cuando llega un mensaje con la app en segundo plano o cerrada. No hace nada: los
/// mensajes traen el bloque `notification` y el sistema ya los muestra solo; al tocarlos la app los recibe por
/// `onMessageOpenedApp` o `getInitialMessage`.
@pragma('vm:entry-point')
Future<void> manejadorPushEnSegundoPlano(RemoteMessage mensaje) async {}

/// La implementación real sobre `firebase_core` y `firebase_messaging`. En Android no hay `firebase_options.dart`: el
/// plugin de Gradle `google-services` deja la configuración lista y basta `Firebase.initializeApp()`.
///
/// Nada de lo que hace lanza una excepción hacia afuera ni imprime el token.
class ServicioPushFirebase implements ServicioPush {
  ServicioPushFirebase();

  final StreamController<String> _refresco = StreamController<String>.broadcast();
  final StreamController<AvisoPush> _abierto = StreamController<AvisoPush>.broadcast();
  final StreamController<AvisoPush> _primerPlano = StreamController<AvisoPush>.broadcast();

  Future<void>? _inicio;
  bool _disponible = false;

  @override
  Stream<String> get alRefrescarToken => _refresco.stream;

  @override
  Stream<AvisoPush> get alAbrirAviso => _abierto.stream;

  @override
  Stream<AvisoPush> get alRecibirEnPrimerPlano => _primerPlano.stream;

  @override
  Future<void> iniciar() => _inicio ??= _iniciar();

  Future<void> _iniciar() async {
    try {
      try {
        await Firebase.initializeApp();
      } on FirebaseException catch (e) {
        if (e.code != 'duplicate-app') rethrow;
      }
      final mensajeria = FirebaseMessaging.instance;
      FirebaseMessaging.onBackgroundMessage(manejadorPushEnSegundoPlano);
      mensajeria.onTokenRefresh.listen(_refresco.add, onError: (Object _) {});
      FirebaseMessaging.onMessage.listen((m) => _emitir(_primerPlano, m), onError: (Object _) {});
      FirebaseMessaging.onMessageOpenedApp.listen((m) => _emitir(_abierto, m), onError: (Object _) {});
      _disponible = true;
      // La app estaba cerrada y se abrió tocando un aviso.
      final inicial = await mensajeria.getInitialMessage();
      if (inicial != null) _emitir(_abierto, inicial);
    } catch (e) {
      _disponible = false;
      debugPrint('push: Firebase no disponible (${e.runtimeType})');
    }
  }

  void _emitir(StreamController<AvisoPush> destino, RemoteMessage mensaje) {
    if (destino.isClosed) return;
    destino.add(
      AvisoPush.desdeDatos(mensaje.data, titulo: mensaje.notification?.title, cuerpo: mensaje.notification?.body),
    );
  }

  @override
  Future<bool> permisoConcedido() async {
    try {
      await iniciar();
      if (!_disponible) return false;
      final estado = (await FirebaseMessaging.instance.getNotificationSettings()).authorizationStatus;
      return estado == AuthorizationStatus.authorized || estado == AuthorizationStatus.provisional;
    } catch (_) {
      return false;
    }
  }

  @override
  Future<bool> solicitarPermiso() async {
    try {
      await iniciar();
      if (!_disponible) return false;
      final estado = (await FirebaseMessaging.instance.requestPermission()).authorizationStatus;
      return estado == AuthorizationStatus.authorized || estado == AuthorizationStatus.provisional;
    } catch (_) {
      return false;
    }
  }

  @override
  Future<String?> obtenerToken() async {
    try {
      await iniciar();
      if (!_disponible) return null;
      final token = await FirebaseMessaging.instance.getToken();
      return (token == null || token.isEmpty) ? null : token;
    } catch (_) {
      return null;
    }
  }
}
