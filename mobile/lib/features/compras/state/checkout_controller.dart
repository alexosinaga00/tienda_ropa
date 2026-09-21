import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../auth/state/auth_controller.dart';
import '../models/cotizacion_envio.dart';
import '../models/pago.dart';
import '../models/venta.dart';

enum TipoEntrega { retiro, domicilio }

/// Estado del wizard de checkout completo (carrito -> entrega -> pago ->
/// estado del pago). Un solo provider, no autoDispose, para que sobreviva
/// la navegación entre esas pantallas -- se reinicia con `reiniciar()` al
/// entrar a un carrito limpio o después de confirmar una compra.
class CheckoutState {
  const CheckoutState({
    this.tipoEntrega,
    this.sucursalId,
    this.direccionId,
    this.cotizacion,
    this.venta,
    this.pagoIniciado,
  });

  final TipoEntrega? tipoEntrega;
  final int? sucursalId;
  final int? direccionId;
  final CotizacionEnvio? cotizacion;
  final Venta? venta;
  final PagoIniciado? pagoIniciado;

  double get costoEnvio => tipoEntrega == TipoEntrega.domicilio ? (cotizacion?.costo ?? 0) : 0;

  // Para domicilio también hace falta la cotización de ESA dirección: sin
  // ella costoEnvio valdría 0 y el backend rechaza el envío cuando el costo
  // de la venta no coincide con la tarifa real de la zona (CU-42).
  bool get listoParaPagar =>
      sucursalId != null &&
      (tipoEntrega == TipoEntrega.retiro || (direccionId != null && cotizacion != null));

  CheckoutState _copyWith({
    TipoEntrega? tipoEntrega,
    int? sucursalId,
    int? direccionId,
    CotizacionEnvio? cotizacion,
    Venta? venta,
    PagoIniciado? pagoIniciado,
    bool limpiarDireccion = false,
    bool limpiarCotizacion = false,
  }) {
    return CheckoutState(
      tipoEntrega: tipoEntrega ?? this.tipoEntrega,
      sucursalId: sucursalId ?? this.sucursalId,
      direccionId: limpiarDireccion ? null : (direccionId ?? this.direccionId),
      cotizacion: limpiarCotizacion ? null : (cotizacion ?? this.cotizacion),
      venta: venta ?? this.venta,
      pagoIniciado: pagoIniciado ?? this.pagoIniciado,
    );
  }
}

class CheckoutController extends StateNotifier<CheckoutState> {
  CheckoutController() : super(const CheckoutState());

  void elegirTipoEntrega(TipoEntrega tipo) {
    if (tipo == state.tipoEntrega) return;
    // También se olvida la sucursal: la del envío (p. ej. el depósito) no
    // necesariamente sirve para retirar.
    state = CheckoutState(tipoEntrega: tipo, venta: state.venta, pagoIniciado: state.pagoIniciado);
  }

  void elegirSucursal(int sucursalId) => state = state._copyWith(sucursalId: sucursalId);

  void elegirDireccion(int direccionId) {
    if (direccionId == state.direccionId) return;
    // La cotización anterior era de otra dirección (otra zona): se descarta
    // hasta que entrega_screen fije la nueva.
    state = state._copyWith(direccionId: direccionId, limpiarCotizacion: true);
  }

  void fijarCotizacion(CotizacionEnvio cotizacion) => state = state._copyWith(cotizacion: cotizacion);

  void confirmarVenta(Venta venta) => state = state._copyWith(venta: venta);

  void confirmarPago(PagoIniciado pago) => state = state._copyWith(pagoIniciado: pago);

  void reiniciar() => state = const CheckoutState();
}

/// Una instancia por sesión: el wizard no es autoDispose a propósito (tiene
/// que sobrevivir la navegación entre pantallas del checkout), así que sin
/// esto un cierre de sesión dejaba la dirección y la venta a medio confirmar
/// del cliente anterior.
final checkoutControllerProvider = StateNotifierProvider<CheckoutController, CheckoutState>((ref) {
  ref.watch(authControllerProvider.select((s) => s.estaAutenticado));
  return CheckoutController();
});
