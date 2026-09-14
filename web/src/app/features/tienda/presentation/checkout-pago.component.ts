import { DecimalPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, map, of, switchMap, throwError } from 'rxjs';
import { MetodoPagoPasarela } from '../../../core/models/pagos.models';
import { CarritoService } from '../data/carrito.service';
import { DireccionesService } from '../data/direcciones.service';
import { PagosService } from '../data/pagos.service';
import { PedidosService } from '../data/pedidos.service';
import { CheckoutService } from '../state/checkout.service';

const METODOS: { codigo: MetodoPagoPasarela; etiqueta: string }[] = [
  { codigo: 'libelula', etiqueta: 'Libélula' },
  { codigo: 'paypal', etiqueta: 'PayPal' },
  { codigo: 'qr_online', etiqueta: 'QR' },
];

@Component({
  selector: 'app-checkout-pago',
  standalone: true,
  imports: [DecimalPipe],
  templateUrl: './checkout-pago.component.html',
  styleUrl: './checkout-pago.component.scss',
})
export class CheckoutPagoComponent {
  protected readonly checkoutService = inject(CheckoutService);
  private readonly carritoService = inject(CarritoService);
  private readonly pedidosService = inject(PedidosService);
  private readonly direccionesService = inject(DireccionesService);
  private readonly pagosService = inject(PagosService);
  private readonly router = inject(Router);

  protected readonly metodos = METODOS;
  protected readonly metodo = signal<MetodoPagoPasarela>('libelula');
  protected readonly procesando = signal(false);
  protected readonly error = signal<string | null>(null);

  elegirMetodo(codigo: MetodoPagoPasarela): void {
    this.metodo.set(codigo);
  }

  pagar(): void {
    if (!this.checkoutService.listoParaPagar() || this.procesando()) return;

    // La ventana se reserva ANTES de cualquier llamada async, dentro de la
    // misma interacción del usuario (el clic) -- si se abriera después de
    // que resuelva el POST /pagos/iniciar, el navegador la bloquearía como
    // popup. Se le fija la URL real más abajo, cuando llega.
    const ventana = window.open('', '_blank');
    ventana?.document.write('Redirigiendo a la pasarela de pago...');
    this.checkoutService.ventanaPago = ventana;

    this.procesando.set(true);
    this.error.set(null);

    const sucursalId = this.checkoutService.sucursalId()!;
    const costoEnvio = this.checkoutService.costoEnvio();

    // Si una llamada anterior a pagar() ya creó la venta pero falló en un
    // paso posterior (envío/pago), esta venta sigue guardada en
    // checkoutService: se reanuda con ella en vez de volver a registrar
    // otra venta digital (eso además fallaría igual, porque el backend ya
    // vació el carrito la primera vez).
    const ventaExistente = this.checkoutService.venta();
    const venta$ = ventaExistente
      ? of(ventaExistente)
      : this.pedidosService.registrarVentaDigital({ sucursal_id: sucursalId, costo_envio: costoEnvio }).pipe(
          map((venta) => {
            this.checkoutService.confirmarVenta(venta);
            // El backend ya vació el carrito al registrar la venta.
            this.carritoService.limpiar();
            return venta;
          }),
        );

    venta$
      .pipe(
        switchMap((venta) => {
          const direccionId = this.checkoutService.direccionId();
          if (this.checkoutService.tipoEntrega() !== 'domicilio' || direccionId === null) {
            return of(venta);
          }
          return this.direccionesService.crearEnvio({ venta_id: venta.id, direccion_id: direccionId }).pipe(
            map(() => venta),
            catchError((err: unknown) => {
              // Reanudando una venta de un intento anterior: el envío ya
              // quedó creado esa vez (el backend responde 409, "ya tiene
              // un envío registrado"). No es un error real, se sigue al pago.
              if (err instanceof HttpErrorResponse && err.status === 409) {
                return of(venta);
              }
              return throwError(() => err);
            }),
          );
        }),
        switchMap((venta) => this.pagosService.iniciar(venta.id, this.metodo())),
      )
      .subscribe({
        next: (pagoIniciado) => {
          this.checkoutService.confirmarPago(pagoIniciado);
          if (ventana) {
            ventana.location.href = pagoIniciado.url_redireccion;
          }
          this.procesando.set(false);
          this.router.navigate(['/checkout/estado', pagoIniciado.pago.id]);
        },
        error: () => {
          ventana?.close();
          this.procesando.set(false);
          this.error.set('No se pudo iniciar el pago. Probá de nuevo.');
        },
      });
  }
}
