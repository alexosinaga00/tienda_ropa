import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/avisos/avisos_mostrados.dart';
import '../../../core/conectividad/conectividad_service.dart';
import '../../../core/push/registro_push.dart';
import '../../../core/push/servicio_push.dart';
import '../../../core/router/app_router.dart';
import '../../../core/sync/disparador_sincronizacion.dart' show mensajeroGlobal;
import '../../auth/state/auth_controller.dart';
import '../../auth/state/auth_state.dart';
import '../../compras/state/compras_providers.dart'
    show compraDetalleProvider, misSolicitudesCambioProvider, reembolsosDeCompraProvider;
import '../models/ruta_notificacion.dart';
import '../state/notificaciones_controller.dart';

/// Cuánto se espera tras volver la conexión antes de reintentar el alta del token.
const esperaPushTrasVolverConexion = Duration(seconds: 3);

/// Cada cuánto se revisa si la app ya salió de la pantalla de arranque para abrir un aviso tocado con la app cerrada.
const intervaloPushNavegacion = Duration(milliseconds: 200);

/// Cuántas revisiones como máximo (unos 10 s): pasado eso el aviso se descarta.
const _maxRevisionesNavegacion = 50;

/// Conecta las notificaciones push con la app, sin que nadie tenga que hacer nada:
/// - Con la app ABIERTA, un aviso se muestra dentro de la app (un SnackBar con "Ver"); Android no lo pinta solo.
/// - Con la app en SEGUNDO PLANO o CERRADA, el sistema muestra la notificación; al TOCARLA se abre la pantalla que
///   corresponde a su tipo (la misma regla que la lista de notificaciones: `rutaDeTipoNotificacion`), o la lista si el
///   tipo no tiene pantalla. Si la app estaba cerrada, el aviso espera a que la sesión termine de restaurarse y a que
///   salga de la pantalla de arranque.
/// - Reenvía el token cuando Firebase lo cambia y reintenta el alta cuando vuelve la conexión.
///
/// Solo actúa con una sesión abierta (personal o cliente). El alta y la baja del token al iniciar y cerrar sesión las
/// hace [AuthController] con [RegistroPush]. Un fallo de Firebase nunca llega hasta aquí: el servicio no lanza.
class DisparadorPush extends ConsumerStatefulWidget {
  const DisparadorPush({
    super.key,
    required this.child,
    this.esperaConexion = esperaPushTrasVolverConexion,
    this.intervaloNavegacion = intervaloPushNavegacion,
  });

  final Widget child;
  final Duration esperaConexion;
  final Duration intervaloNavegacion;

  @override
  ConsumerState<DisparadorPush> createState() => _DisparadorPushState();
}

class _DisparadorPushState extends ConsumerState<DisparadorPush> {
  final List<StreamSubscription<Object?>> _suscripciones = [];
  Timer? _esperaConexion;
  Timer? _revisionNavegacion;
  int _revisiones = 0;

  /// Un aviso tocado mientras la sesión todavía se restauraba.
  AvisoPush? _avisoEnEspera;

  /// La pantalla a abrir cuando la app salga de la pantalla de arranque.
  String? _rutaEnEspera;

  @override
  void initState() {
    super.initState();
    final servicio = ref.read(servicioPushProvider);
    _suscripciones
      ..add(servicio.alRefrescarToken.listen(_alRefrescarToken, onError: (Object _) {}))
      ..add(servicio.alAbrirAviso.listen(_alAbrirAviso, onError: (Object _) {}))
      ..add(servicio.alRecibirEnPrimerPlano.listen(_alRecibirEnPrimerPlano, onError: (Object _) {}));
    // Después de suscribirse: así el aviso con el que se abrió la app (si lo hay) no se pierde.
    unawaited(_iniciar(servicio));
  }

  Future<void> _iniciar(ServicioPush servicio) async {
    try {
      await servicio.iniciar();
    } catch (_) {
      // El servicio no debería lanzar; si lo hiciera, la app sigue sin avisos push.
    }
  }

  @override
  void dispose() {
    for (final suscripcion in _suscripciones) {
      unawaited(suscripcion.cancel());
    }
    _esperaConexion?.cancel();
    _revisionNavegacion?.cancel();
    super.dispose();
  }

  EstadoSesion get _estadoSesion => ref.read(authControllerProvider).estado;

  void _alRefrescarToken(String token) {
    if (_estadoSesion != EstadoSesion.autenticado) return;
    unawaited(ref.read(registroPushProvider).alRefrescarToken(token));
  }

  void _alRecibirEnPrimerPlano(AvisoPush aviso) {
    if (_estadoSesion != EstadoSesion.autenticado) return;
    // La campana y la lista se actualizan siempre; lo que se decide aparte es si además sale el SnackBar.
    unawaited(_refrescarLista());
    _refrescarCompraSiEsReembolso(aviso);
    if (!_hayQueMostrar(aviso)) return;
    final mensajero = mensajeroGlobal.currentState;
    final titulo = aviso.titulo;
    final cuerpo = aviso.cuerpo;
    if (mensajero == null || ((titulo == null || titulo.isEmpty) && (cuerpo == null || cuerpo.isEmpty))) return;
    mensajero
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (titulo != null && titulo.isNotEmpty) Text(titulo, style: const TextStyle(fontWeight: FontWeight.w700)),
              if (cuerpo != null && cuerpo.isNotEmpty) Text(cuerpo),
            ],
          ),
          duration: const Duration(seconds: 8),
          action: SnackBarAction(label: 'Ver', onPressed: () => _abrir(aviso)),
        ),
      );
  }

  /// Un reembolso cambia lo que muestra el detalle de esa compra (el dinero devuelto, las devoluciones y la solicitud de
  /// cambio aprobada): si la pantalla está abierta, o queda en memoria debajo de otra, se vuelve a pedir en vez de
  /// quedarse con lo viejo. No es parte de la deduplicación de la compra confirmada: es otro hecho.
  void _refrescarCompraSiEsReembolso(AvisoPush aviso) {
    final venta = aviso.referenciaId;
    if (aviso.tipo != 'reembolso' || venta == null) return;
    ref.invalidate(reembolsosDeCompraProvider(venta));
    ref.invalidate(compraDetalleProvider(venta));
    ref.invalidate(misSolicitudesCambioProvider(venta));
  }

  /// Si el aviso en primer plano debe salir como SnackBar. No sale cuando el mismo hecho ya se avisó (el pago
  /// aprobado en pantalla o el pedido sin conexión cobrado por la cola) ni cuando la persona ya está mirando esa
  /// compra. Una compra confirmada y un pedido sin conexión cobrado con la misma referencia son el mismo hecho.
  bool _hayQueMostrar(AvisoPush aviso) {
    final avisos = ref.read(avisosMostradosProvider);
    final referencia = aviso.referenciaId;
    final notificacionId = aviso.notificacionId;
    final esCompra = tiposDeCompraConfirmada.contains(aviso.tipo) && referencia != null;

    var nuevo = true;
    if (esCompra) nuevo = avisos.marcar(AvisosMostrados.claveDeVenta(referencia));
    if (notificacionId != null) nuevo = avisos.marcar(AvisosMostrados.claveDeNotificacion(notificacionId)) && nuevo;
    if (!nuevo) return false;

    final rutaActual = rutaActualDe(ref.read(routerProvider));
    final ruta = rutaDeTipoNotificacion(aviso.tipo, referencia);
    if (esCompra && yaViendoLaCompra(rutaActual, referencia)) {
      // La pantalla de la compra puede estar mostrando "Pendiente de pago": se vuelve a pedir.
      ref.invalidate(compraDetalleProvider(referencia));
      return false;
    }
    return ruta == null || ruta != rutaActual;
  }

  void _alAbrirAviso(AvisoPush aviso) {
    switch (_estadoSesion) {
      case EstadoSesion.autenticado:
        _abrir(aviso);
      case EstadoSesion.inicial || EstadoSesion.cargando:
        // La app se abrió desde la notificación: se espera a saber si hay sesión.
        _avisoEnEspera = aviso;
      case EstadoSesion.noAutenticado:
        break; // sin sesión no hay a dónde llevar al visitante
    }
  }

  /// Lleva a la pantalla del aviso (o a la lista de notificaciones si su tipo no tiene pantalla propia).
  void _abrir(AvisoPush aviso) {
    _refrescarCompraSiEsReembolso(aviso);
    unawaited(_refrescarYMarcar(aviso.notificacionId));
    _irA(rutaDeTipoNotificacion(aviso.tipo, aviso.referenciaId) ?? '/notificaciones');
  }

  Future<void> _refrescarLista() async {
    try {
      await ref.read(notificacionesProvider.notifier).refrescar();
    } catch (_) {
      // La campana se actualizará la próxima vez que se pida la lista.
    }
  }

  /// Actualiza la campana y marca como leída la notificación que se acaba de abrir.
  Future<void> _refrescarYMarcar(int? notificacionId) async {
    try {
      final controlador = ref.read(notificacionesProvider.notifier);
      await controlador.refrescar();
      if (notificacionId != null) await controlador.marcarLeida(notificacionId);
    } catch (_) {
      // Mejor esfuerzo.
    }
  }

  bool _enPantallaDeArranque() {
    try {
      return ref.read(routerProvider).routerDelegate.currentConfiguration.uri.path == '/splash';
    } catch (_) {
      return false;
    }
  }

  void _irA(String ruta) {
    if (!_enPantallaDeArranque()) {
      _revisionNavegacion?.cancel();
      _rutaEnEspera = null;
      unawaited(ref.read(routerProvider).push(ruta));
      return;
    }
    // Aún en la pantalla de arranque: abrir encima la dejaría debajo de otra redirección. Se espera a que salga.
    _rutaEnEspera = ruta;
    _revisiones = 0;
    _revisionNavegacion?.cancel();
    _revisionNavegacion = Timer.periodic(widget.intervaloNavegacion, (temporizador) {
      _revisiones++;
      final ruta = _rutaEnEspera;
      if (!mounted || ruta == null || _revisiones > _maxRevisionesNavegacion) {
        temporizador.cancel();
        _rutaEnEspera = null;
        return;
      }
      if (_enPantallaDeArranque()) return;
      temporizador.cancel();
      _rutaEnEspera = null;
      unawaited(ref.read(routerProvider).push(ruta));
    });
  }

  void _alCambiarSesion(AuthState? anterior, AuthState actual) {
    if (actual.estado == EstadoSesion.autenticado) {
      final aviso = _avisoEnEspera;
      _avisoEnEspera = null;
      if (aviso != null) _abrir(aviso);
    } else if (actual.estado == EstadoSesion.noAutenticado) {
      _avisoEnEspera = null;
      _rutaEnEspera = null;
      _revisionNavegacion?.cancel();
    }
  }

  void _alVolverLaConexion() {
    if (!mounted || _estadoSesion != EstadoSesion.autenticado) return;
    unawaited(ref.read(registroPushProvider).alVolverConexion());
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<AuthState>(authControllerProvider, _alCambiarSesion);

    ref.listen<AsyncValue<bool>>(enLineaProvider, (anterior, actual) {
      if (actual.valueOrNull != true || anterior?.valueOrNull != false) return;
      _esperaConexion?.cancel();
      _esperaConexion = Timer(widget.esperaConexion, _alVolverLaConexion);
    });

    return widget.child;
  }
}
