import 'package:flutter_riverpod/flutter_riverpod.dart';
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

  bool get listoParaPagar =>
      sucursalId != null && (tipoEntrega == TipoEntrega.retiro || direccionId != null);

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

  void elegirDireccion(int direccionId) => state = state._copyWith(direccionId: direccionId);

  void fijarCotizacion(CotizacionEnvio cotizacion) => state = state._copyWith(cotizacion: cotizacion);

  void confirmarVenta(Venta venta) => state = state._copyWith(venta: venta);

  void confirmarPago(PagoIniciado pago) => state = state._copyWith(pagoIniciado: pago);

  void reiniciar() => state = const CheckoutState();
}

final checkoutControllerProvider = StateNotifierProvider<CheckoutController, CheckoutState>(
  (ref) => CheckoutController(),
);
