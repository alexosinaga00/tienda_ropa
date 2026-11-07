import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../network/providers.dart';
import 'almacen_push.dart';
import 'dispositivos_push_repository.dart';
import 'servicio_push.dart';

/// Lo máximo que cerrar sesión espera a la baja del token: cerrar sesión nunca debe quedarse colgado por la red.
const esperaMaximaBajaPush = Duration(seconds: 3);

/// Mantiene el token push de este teléfono al día en el servidor: lo registra al iniciar sesión (y al restaurarla con
/// red), lo reenvía cuando Firebase lo cambia y lo da de baja al cerrar sesión. Todo es de mejor esfuerzo: NINGÚN método
/// lanza ni bloquea, y el token completo nunca se imprime.
///
/// Baja sin red: si al cerrar sesión no se pudo avisar, el token queda guardado como "baja pendiente". Con la sesión
/// cerrada ya no hay credenciales para pedir la baja, así que se resuelve en el siguiente inicio de sesión de cualquiera
/// (ver [_resolverBajaPendiente]): si es el mismo token, el alta lo reasigna y basta olvidar la baja; si es otro, se
/// intenta la baja y, sin red, se conserva para la próxima vez.
class RegistroPush {
  RegistroPush({
    required this._servicio,
    required this._repositorio,
    required this._almacen,
    this.esperaBaja = esperaMaximaBajaPush,
  });

  final ServicioPush _servicio;
  final DispositivosPushRepository _repositorio;
  final AlmacenPush _almacen;
  final Duration esperaBaja;

  /// El token que el servidor aceptó en esta apertura de la app; null = todavía no (o ya se dio de baja).
  String? _tokenRegistrado;

  bool get registrado => _tokenRegistrado != null;

  /// Inicio de sesión (o sesión restaurada y confirmada con el servidor). Con [pedirPermiso] muestra el diálogo del
  /// sistema si hace falta; sin permiso o sin token no registra nada y no pasa nada más.
  Future<void> alIniciarSesion({bool pedirPermiso = false}) async {
    try {
      var permiso = await _servicio.permisoConcedido();
      if (!permiso && pedirPermiso) permiso = await _servicio.solicitarPermiso();
      if (!permiso) return;
      final token = await _servicio.obtenerToken();
      if (token == null || token.isEmpty) return;
      await _registrar(token);
    } catch (e) {
      _avisarFallo('registro', e);
    }
  }

  /// La persona entró a la pantalla de notificaciones: buen momento para pedir el permiso si aún falta y registrar.
  Future<void> alEntrarANotificaciones() async {
    if (_tokenRegistrado != null) return;
    await alIniciarSesion(pedirPermiso: true);
  }

  /// Firebase cambió el token del dispositivo: se reenvía el nuevo (hay sesión abierta, lo decide quien llama).
  Future<void> alRefrescarToken(String token) async {
    if (token.isEmpty) return;
    try {
      await _registrar(token);
    } catch (e) {
      _avisarFallo('refresco', e);
    }
  }

  /// Volvió la conexión con la sesión abierta: si el alta no se completó, se reintenta.
  Future<void> alVolverConexion() async {
    if (_tokenRegistrado != null) return;
    await alIniciarSesion();
  }

  /// Cierre de sesión: da de baja el token ANTES de que se borren las credenciales. Con [intentarBaja] en falso (la sesión
  /// ya venció: pedirla dispararía otro cierre) o si la baja falla o tarda, el token queda como baja pendiente.
  Future<void> alCerrarSesion({bool intentarBaja = true}) async {
    try {
      final token = _tokenRegistrado ?? await _almacen.leerTokenRegistrado();
      _tokenRegistrado = null;
      if (token == null || token.isEmpty) return;
      var hecho = false;
      if (intentarBaja) {
        try {
          await _repositorio.baja(token).timeout(esperaBaja);
          hecho = true;
        } catch (e) {
          _avisarFallo('baja', e);
        }
      }
      if (hecho) {
        if (await _almacen.leerBajaPendiente() == token) await _almacen.borrarBajaPendiente();
      } else {
        await _almacen.guardarBajaPendiente(token);
      }
      await _almacen.borrarTokenRegistrado();
    } catch (e) {
      _avisarFallo('cierre', e);
    }
  }

  Future<void> _registrar(String token) async {
    await _resolverBajaPendiente(token);
    await _repositorio.registrar(token);
    _tokenRegistrado = token;
    try {
      await _almacen.guardarTokenRegistrado(token);
    } catch (_) {
      // Solo sirve para dar de baja si la app se reinicia antes de cerrar sesión: no es motivo para fallar.
    }
  }

  Future<void> _resolverBajaPendiente(String actual) async {
    try {
      final pendiente = await _almacen.leerBajaPendiente();
      if (pendiente == null) return;
      if (pendiente == actual) {
        // El alta de abajo lo reasigna a esta cuenta; pedir la baja después la desactivaría.
        await _almacen.borrarBajaPendiente();
        return;
      }
      await _repositorio.baja(pendiente).timeout(esperaBaja);
      await _almacen.borrarBajaPendiente();
    } catch (e) {
      _avisarFallo('baja pendiente', e);
    }
  }

  void _avisarFallo(String paso, Object error) {
    debugPrint('push: no se pudo completar $paso (${error.runtimeType})');
  }
}

/// En memoria por defecto; `main.dart` lo reemplaza por el almacenamiento seguro del dispositivo.
final almacenPushProvider = Provider<AlmacenPush>((ref) => AlmacenPushMemoria());

final dispositivosPushRepositoryProvider = Provider<DispositivosPushRepository>(
  (ref) => DispositivosPushRepository(() => ref.read(apiClientProvider)),
);

final registroPushProvider = Provider<RegistroPush>((ref) {
  return RegistroPush(
    servicio: ref.watch(servicioPushProvider),
    repositorio: ref.watch(dispositivosPushRepositoryProvider),
    almacen: ref.watch(almacenPushProvider),
  );
});
