import { Injectable, computed, signal } from '@angular/core';
import { CotizacionEnvio } from '../../../core/models/entregas.models';
import { PagoIniciarRespuesta } from '../../../core/models/pagos.models';
import { Venta } from '../../../core/models/ventas.models';

export type TipoEntrega = 'retiro' | 'domicilio';

interface CheckoutState {
  tipoEntrega: TipoEntrega | null;
  sucursalId: number | null;
  direccionId: number | null;
  cotizacion: CotizacionEnvio | null;
  venta: Venta | null;
  pagoIniciado: PagoIniciarRespuesta | null;
}

const ESTADO_INICIAL: CheckoutState = {
  tipoEntrega: null,
  sucursalId: null,
  direccionId: null,
  cotizacion: null,
  venta: null,
  pagoIniciado: null,
};

/**
 * Estado del wizard de checkout completo (carrito -> entrega -> pago ->
 * estado del pago), calco de `checkout_controller.dart` en Flutter. Vive en
 * un servicio `providedIn: 'root'` (no un signal local del componente) para
 * que sobreviva la navegación entre esas rutas -- se reinicia con
 * `reiniciar()` al entrar a un carrito limpio o tras confirmar una compra.
 */
@Injectable({ providedIn: 'root' })
export class CheckoutService {
  private readonly estado = signal<CheckoutState>({ ...ESTADO_INICIAL });

  /** Ventana emergente abierta para la pasarela de pago (ver checkout-pago). */
  ventanaPago: Window | null = null;

  readonly tipoEntrega = computed(() => this.estado().tipoEntrega);
  readonly sucursalId = computed(() => this.estado().sucursalId);
  readonly direccionId = computed(() => this.estado().direccionId);
  readonly cotizacion = computed(() => this.estado().cotizacion);
  readonly venta = computed(() => this.estado().venta);
  readonly pagoIniciado = computed(() => this.estado().pagoIniciado);

  readonly costoEnvio = computed(() => (this.tipoEntrega() === 'domicilio' ? (this.cotizacion()?.costo ?? 0) : 0));

  // Para domicilio también hace falta la cotización de ESA dirección: sin
  // ella costoEnvio valdría 0 y el backend rechaza el envío cuando el costo
  // de la venta no coincide con la tarifa real de la zona (CU-42).
  readonly listoParaPagar = computed(() => {
    const estado = this.estado();
    return (
      estado.sucursalId !== null &&
      (estado.tipoEntrega === 'retiro' || (estado.direccionId !== null && estado.cotizacion !== null))
    );
  });

  elegirTipoEntrega(tipo: TipoEntrega): void {
    this.estado.update((actual) =>
      // También se olvida la sucursal: la del envío (p. ej. el depósito) no necesariamente sirve para retirar.
      actual.tipoEntrega === tipo
        ? actual
        : { ...actual, tipoEntrega: tipo, direccionId: null, cotizacion: null, sucursalId: null },
    );
  }

  elegirSucursal(sucursalId: number): void {
    this.estado.update((actual) => ({ ...actual, sucursalId }));
  }

  elegirDireccion(direccionId: number): void {
    // La cotización anterior era de otra dirección (otra zona): se descarta
    // hasta que llegue la nueva.
    this.estado.update((actual) => ({ ...actual, direccionId, cotizacion: null }));
  }

  fijarCotizacion(cotizacion: CotizacionEnvio): void {
    this.estado.update((actual) => ({ ...actual, cotizacion }));
  }

  confirmarVenta(venta: Venta): void {
    this.estado.update((actual) => ({ ...actual, venta }));
  }

  confirmarPago(pagoIniciado: PagoIniciarRespuesta): void {
    this.estado.update((actual) => ({ ...actual, pagoIniciado }));
  }

  reiniciar(): void {
    this.estado.set({ ...ESTADO_INICIAL });
    this.ventanaPago = null;
  }
}
