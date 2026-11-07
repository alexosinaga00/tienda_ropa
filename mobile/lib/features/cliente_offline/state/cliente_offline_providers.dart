import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/conectividad/conectividad_service.dart';
import '../../../core/network/providers.dart';
import '../../../core/utils/dinero.dart';
import '../../../core/utils/reloj.dart';
import '../../auth/models/usuario.dart';
import '../../auth/state/auth_controller.dart';
import '../../tienda/state/tienda_controller.dart';
import '../data/cache_catalogo_cliente.dart';
import '../data/metodo_pago_repository.dart';
import '../data/pedidos_diferidos_api.dart';
import '../data/repositorio_cliente.dart';
import '../models/linea_carrito_local.dart';
import '../models/metodo_pago.dart';
import '../models/pedido_diferido_api.dart';
import '../models/pedido_sin_conexion.dart';
import 'base_cliente.dart';
import 'carrito_local_controller.dart';
import 'cola_pedidos.dart';
import 'metodo_pago_controller.dart';

/// Con quién se opera sin conexión: la empresa y la persona de la sesión, SOLO si es un cliente (modo cliente). El personal
/// no tiene alcance aquí: usa su propia base. Sin sesión es null.
final alcanceClienteProvider = Provider<AlcanceCliente?>((ref) {
  final auth = ref.watch(authControllerProvider);
  final usuario = auth.usuario;
  final empresaId = usuario?.empresaId;
  if (!auth.estaAutenticado || usuario == null || usuario.modo != ModoApp.cliente || empresaId == null) return null;
  return AlcanceCliente(empresaId: empresaId, usuarioId: usuario.id);
});

/// Abre la base del cliente (si hace falta) y devuelve el repositorio acotado a la sesión actual, o null sin sesión de
/// cliente. Cada llamada arma uno liviano: no guarda estado.
final repositorioClienteProvider = Provider<Future<RepositorioCliente?> Function()>((ref) {
  return () async {
    final alcance = ref.read(alcanceClienteProvider);
    if (alcance == null) return null;
    return RepositorioCliente(await ref.read(baseClienteProvider.future), alcance: alcance);
  };
});

/// Lo público de la tienda que el cliente ya vio (prendas, detalles, tallas, colores, sucursales) para mostrarlo sin red.
final cacheCatalogoClienteProvider = Provider<CacheCatalogoCliente>((ref) {
  return CacheCatalogoClienteSqlite(
    () => ref.read(baseClienteProvider.future),
    () => ref.read(tiendaCodigoProvider),
    ref.read(relojProvider),
  );
});

final metodoPagoRepositoryProvider = Provider<MetodoPagoRepository>(
  (ref) => MetodoPagoRepository(ref.watch(apiClientProvider)),
);

final pedidosDiferidosApiProvider = Provider<PedidosDiferidosApi>((ref) => _ApiPedidosPerezosa(ref));

/// Pide el cliente de red al enviar (no al construir): la cola dura toda la sesión aunque cambie la tienda elegida.
class _ApiPedidosPerezosa implements PedidosDiferidosApi {
  _ApiPedidosPerezosa(this._ref);

  final Ref _ref;

  @override
  Future<PedidoDiferidoRespuesta> enviar(PedidoDiferidoCrear pedido) =>
      PedidosDiferidosApiHttp(_ref.read(apiClientProvider)).enviar(pedido);
}

/// Pide la conexión al usarla: así crear la cola (p. ej. para mostrar el contador) no despierta al servicio de red.
class _ConectividadPerezosa implements ConectividadService {
  _ConectividadPerezosa(this._ref);

  final Ref _ref;

  ConectividadService get _real => _ref.read(conectividadServiceProvider);

  @override
  Stream<bool> get enLinea => _real.enLinea;

  @override
  bool get actual => _real.actual;

  @override
  Future<bool> verificarAhora() => _real.verificarAhora();
}

// ---- Estado de la sesión del cliente ---------------------------------------------------------------------------------

/// El PayPal guardado que el teléfono recuerda. Una instancia por sesión.
final metodoPagoLocalProvider = StateNotifierProvider<MetodoPagoController, MetodoPagoRecordado?>((ref) {
  final activo = ref.watch(alcanceClienteProvider) != null;
  return MetodoPagoController(
    ref.read(repositorioClienteProvider),
    ref.watch(metodoPagoRepositoryProvider),
    ref.read(relojProvider),
    activo: activo,
  );
});

/// Verdadero solo si el servidor confirmó, alguna vez, que hay un PayPal guardado.
final tienePaypalGuardadoProvider = Provider<bool>((ref) => ref.watch(metodoPagoLocalProvider)?.guardado ?? false);

/// El carrito local (el de sin conexión). Una instancia por sesión: el de una persona no queda a la vista de la siguiente.
final carritoLocalProvider = StateNotifierProvider<CarritoLocalController, List<LineaCarritoLocal>>((ref) {
  final activo = ref.watch(alcanceClienteProvider) != null;
  return CarritoLocalController(ref.read(repositorioClienteProvider), ref.read(relojProvider), activo: activo);
});

final carritoLocalSubtotalProvider = Provider<int>((ref) => totalDeLineasCentavos(ref.watch(carritoLocalProvider)));

final carritoLocalCantidadProvider = Provider<int>(
  (ref) => ref.watch(carritoLocalProvider).fold(0, (suma, l) => suma + l.cantidad),
);

// ---- La cola -------------------------------------------------------------------------------------------------------------

/// La cola de pedidos sin conexión: UNA para toda la app. Vive aunque se cambie de pantalla; atiende a la persona de la sesión.
final colaPedidosProvider = Provider<ColaPedidos>((ref) {
  final cola = ColaPedidos(
    repositorio: ref.read(repositorioClienteProvider),
    alcanceActual: () => ref.read(alcanceClienteProvider),
    api: ref.read(pedidosDiferidosApiProvider),
    reloj: ref.read(relojProvider),
    conectividad: _ConectividadPerezosa(ref),
    alFaltarMetodoPago: () => ref.read(metodoPagoLocalProvider.notifier).recordar(MetodoPagoPaypal.sinGuardar),
  );
  ref.onDispose(cola.dispose);
  return cola;
});

/// En qué está la cola (pausada, esperando un reintento, sin conexión...). Emite primero el estado actual.
final estadoColaProvider = StreamProvider<EstadoCola>((ref) {
  final cola = ref.watch(colaPedidosProvider);
  final controlador = StreamController<EstadoCola>();
  final suscripcion = cola.estados.listen(controlador.add);
  controlador.add(cola.estado);
  ref.onDispose(() {
    unawaited(suscripcion.cancel());
    unawaited(controlador.close());
  });
  return controlador.stream;
});

/// Mis pedidos hechos sin conexión, del más nuevo al más viejo. Se vuelve a leer cada vez que la cola avisa un cambio.
class PedidosSinConexionController extends StateNotifier<AsyncValue<List<PedidoSinConexion>>> {
  PedidosSinConexionController(this._cola) : super(const AsyncValue.loading()) {
    _suscripcion = _cola.cambios.listen((_) => cargar());
    cargar();
  }

  final ColaPedidos _cola;
  late final StreamSubscription<void> _suscripcion;

  Future<void> cargar() async {
    final pedidos = await _cola.pedidos();
    if (mounted) state = AsyncValue.data(pedidos);
  }

  @override
  void dispose() {
    unawaited(_suscripcion.cancel());
    super.dispose();
  }
}

final pedidosSinConexionProvider =
    StateNotifierProvider<PedidosSinConexionController, AsyncValue<List<PedidoSinConexion>>>((ref) {
      // Otra persona = otra lista.
      ref.watch(alcanceClienteProvider);
      return PedidosSinConexionController(ref.watch(colaPedidosProvider));
    });

/// Cuántos pedidos siguen sin enviar (pendientes o enviándose). Los vencidos y los resueltos no cuentan.
final pedidosSinEnviarProvider = Provider<int>((ref) {
  final pedidos = ref.watch(pedidosSinConexionProvider).valueOrNull ?? const <PedidoSinConexion>[];
  return pedidos.where((p) => p.estado.sinEnviar).length;
});

/// Cuántos pedidos ya resueltos (cobrados, rechazados, vencidos) el cliente todavía no vio.
final pedidosSinVerProvider = Provider<int>((ref) {
  final pedidos = ref.watch(pedidosSinConexionProvider).valueOrNull ?? const <PedidoSinConexion>[];
  return pedidos.where((p) => p.estado.esFinal && !p.visto).length;
});

/// El aviso de un pedido que acaba de cobrarse o rechazarse.
String textoAvisoPedido(PedidoSinConexion pedido) {
  if (pedido.estado == EstadoPedidoLocal.cobrado) {
    final codigo = pedido.codigoVenta == null ? '' : ' ${pedido.codigoVenta}';
    final total = pedido.totalCentavos == null ? '' : ' por ${formatearBs(pedido.totalCentavos!)}';
    return 'Cobramos tu pedido$codigo$total.';
  }
  final mensaje = pedido.mensaje;
  return mensaje == null || mensaje.isEmpty ? 'No pudimos cobrar tu pedido. No se cobró nada.' : mensaje;
}
