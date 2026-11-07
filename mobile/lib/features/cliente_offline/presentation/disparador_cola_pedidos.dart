import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/avisos/avisos_mostrados.dart';
import '../../../core/conectividad/conectividad_service.dart';
import '../../../core/router/app_router.dart';
import '../../../core/sync/disparador_sincronizacion.dart' show mensajeroGlobal;
import '../../auth/state/auth_controller.dart';
import '../../catalogo/state/catalogo_providers.dart';
import '../config/cliente_offline_config.dart';
import '../models/linea_carrito_local.dart';
import '../models/pedido_sin_conexion.dart';
import '../state/cliente_offline_providers.dart';

/// Pone en marcha la cola de pedidos sin conexión del cliente sin que haga nada. Solo actúa con una sesión de cliente.
/// Disparadores: (a) la conexión pasa de sin red a en línea (con una espera de unos segundos), (b) se abre la app o se
/// inicia sesión, (c) la app vuelve al primer plano, (d) cada 60 s mientras haya sesión. Encolar un pedido y el botón
/// "Enviar ahora" los maneja la propia cola. Todos comparten el candado de la cola: un disparo durante otro envío no hace
/// otro envío en paralelo.
///
/// También avisa con un mensaje cuando un pedido se cobra o se rechaza, y al empezar la sesión (con red) recuerda el PayPal
/// guardado, las sucursales, las tallas y los colores para poder decidir sin conexión.
class DisparadorColaPedidos extends ConsumerStatefulWidget {
  const DisparadorColaPedidos({
    super.key,
    required this.child,
    this.esperaConexion = esperaTrasVolverConexionCliente,
    this.intervalo = intervaloColaCliente,
  });

  final Widget child;
  final Duration esperaConexion;
  final Duration intervalo;

  @override
  ConsumerState<DisparadorColaPedidos> createState() => _DisparadorColaPedidosState();
}

class _DisparadorColaPedidosState extends ConsumerState<DisparadorColaPedidos> with WidgetsBindingObserver {
  Timer? _esperaConexion;
  Timer? _temporizador;
  StreamSubscription<PedidoSinConexion>? _resueltos;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _temporizador = Timer.periodic(widget.intervalo, (_) => _alTemporizador());
    final cola = ref.read(colaPedidosProvider);
    _resueltos = cola.resueltos.listen(_avisar);
    // La sesión puede estar ya abierta cuando este widget se construye.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _alCambiarSesion(ref.read(alcanceClienteProvider));
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _esperaConexion?.cancel();
    _temporizador?.cancel();
    unawaited(_resueltos?.cancel());
    super.dispose();
  }

  bool get _hayCliente => ref.read(alcanceClienteProvider) != null;

  void _alCambiarSesion(AlcanceCliente? alcance) {
    ref.read(colaPedidosProvider).alCambiarAlcance(alcance);
    if (alcance != null) unawaited(_recordarParaSinConexion());
  }

  /// Con red, guarda lo que hace falta para decidir sin red. Todo en silencio: un fallo no molesta a nadie.
  Future<void> _recordarParaSinConexion() async {
    if (!(ref.read(enLineaProvider).valueOrNull ?? true)) return;
    try {
      unawaited(ref.read(metodoPagoLocalProvider.notifier).refrescar());
      await Future.wait([
        ref.read(sucursalesRefProvider.future),
        ref.read(tallasRefProvider.future),
        ref.read(coloresRefProvider.future),
      ]);
    } catch (_) {
      // Sin esto se puede vivir: la próxima vez con red se vuelve a intentar.
    }
  }

  // (c) La app vuelve al primer plano.
  @override
  void didChangeAppLifecycleState(AppLifecycleState estado) {
    if (estado != AppLifecycleState.resumed || !_hayCliente) return;
    unawaited(ref.read(colaPedidosProvider).procesar());
  }

  // (d) Con la app abierta.
  void _alTemporizador() {
    if (!mounted || !_hayCliente) return;
    unawaited(ref.read(colaPedidosProvider).procesar());
  }

  void _alVolverLaConexion() {
    if (!mounted || !_hayCliente) return;
    // Una sesión que se restauró sin red se confirma ahora con el servidor.
    if (!ref.read(authControllerProvider).verificada) {
      unawaited(ref.read(authControllerProvider.notifier).verificarSesion());
    }
    ref.read(colaPedidosProvider).alVolverConexion();
    unawaited(_recordarParaSinConexion());
  }

  void _avisar(PedidoSinConexion pedido) {
    // Un pedido cobrado es una compra pagada: si el push (o la pantalla del pago) ya la avisó, no se repite; y si la
    // persona ya está mirando esa compra, tampoco hace falta. El primero que llega gana.
    final ventaId = pedido.estado == EstadoPedidoLocal.cobrado ? pedido.ventaId : null;
    if (ventaId != null) {
      if (!ref.read(avisosMostradosProvider).marcar(AvisosMostrados.claveDeVenta(ventaId))) return;
      if (yaViendoLaCompra(rutaActualDe(ref.read(routerProvider)), ventaId)) return;
    }
    final mensajero = mensajeroGlobal.currentState;
    if (mensajero == null) return;
    mensajero
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text(textoAvisoPedido(pedido)),
          duration: const Duration(seconds: 8),
          action: SnackBarAction(
            label: pedido.estado == EstadoPedidoLocal.cobrado && pedido.ventaId != null ? 'Ver compra' : 'Ver',
            onPressed: () {
              final router = ref.read(routerProvider);
              unawaited(
                router.push(
                  pedido.estado == EstadoPedidoLocal.cobrado && pedido.ventaId != null
                      ? '/compras/${pedido.ventaId}'
                      : '/pedidos-sin-conexion',
                ),
              );
            },
          ),
        ),
      );
  }

  @override
  Widget build(BuildContext context) {
    // (b) Entra, sale o cambia la persona: arranca (o se reinicia) la cola de esa persona.
    ref.listen<AlcanceCliente?>(alcanceClienteProvider, (anterior, actual) => _alCambiarSesion(actual));

    // (a) La conexión vuelve: se espera unos segundos y se envía.
    ref.listen<AsyncValue<bool>>(enLineaProvider, (anterior, actual) {
      if (actual.valueOrNull != true || anterior?.valueOrNull != false) return;
      _esperaConexion?.cancel();
      _esperaConexion = Timer(widget.esperaConexion, _alVolverLaConexion);
    });

    return widget.child;
  }
}
