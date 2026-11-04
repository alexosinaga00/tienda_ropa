import { DecimalPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { catchError, map, of, switchMap, throwError } from 'rxjs';
import { MetodoPagoPasarela } from '../../../core/models/pagos.models';
import { IconoComponent } from '../../../shared/icono/icono.component';
import { NombreIcono } from '../../../shared/icono/iconos';
import { CarritoService } from '../data/carrito.service';
import { DireccionesService } from '../data/direcciones.service';
import { PagosService } from '../data/pagos.service';
import { PedidosService } from '../data/pedidos.service';
import { CheckoutService } from '../state/checkout.service';
import { TiendaActualService } from '../state/tienda-actual.service';
import { PasosCompraComponent } from './pasos-compra.component';
import { ResumenCompraComponent } from './resumen-compra.component';

// QR primero y por defecto. Libélula ya no se ofrece al comprar (era un simulador que nunca confirmaba el pago; la
// app móvil tampoco lo ofrece). El backend sigue aceptándolo por si una compra antigua lo tenía.
const METODOS: { codigo: MetodoPagoPasarela; etiqueta: string; texto: string; icono: NombreIcono }[] = [
  { codigo: 'qr_online', etiqueta: 'QR', texto: 'Escanea el código desde la app de tu banco.', icono: 'qr' },
  { codigo: 'paypal', etiqueta: 'PayPal', texto: 'Paga con tu cuenta PayPal o con tarjeta.', icono: 'tarjeta' },
];

@Component({
  selector: 'app-checkout-pago',
  standalone: true,
  imports: [DecimalPipe, RouterLink, IconoComponent, PasosCompraComponent, ResumenCompraComponent],
  templateUrl: './checkout-pago.component.html',
  styleUrl: './checkout-pago.component.scss',
})
export class CheckoutPagoComponent implements OnInit {
  protected readonly checkoutService = inject(CheckoutService);
  protected readonly carritoService = inject(CarritoService);
  private readonly pedidosService = inject(PedidosService);
  private readonly direccionesService = inject(DireccionesService);
  private readonly pagosService = inject(PagosService);
  private readonly router = inject(Router);
  protected readonly tienda = inject(TiendaActualService);

  protected readonly metodos = METODOS;
  protected readonly metodo = signal<MetodoPagoPasarela>('qr_online');
  protected readonly procesando = signal(false);
  protected readonly error = signal<string | null>(null);

  /**
   * Importes que se muestran: los de la venta si ya se registró (un reintento
   * después de un fallo posterior) y, si no, los del carrito más el envío.
   */
  protected readonly resumenVista = computed<{ subtotal: number; descuento: number; total: number } | null>(() => {
    const venta = this.checkoutService.venta();
    if (venta) return { subtotal: venta.subtotal, descuento: venta.descuento, total: venta.total };
    const resumen = this.carritoService.resumen();
    if (resumen === null) return null;
    return { ...resumen, total: resumen.total + this.checkoutService.costoEnvio() };
  });

  ngOnInit(): void {
    // Con la venta ya registrada el carrito está vacío (lo vació el backend): se usan los importes de la venta.
    if (this.checkoutService.venta() || this.carritoService.lineas().length === 0) return;
    this.carritoService.refrescarResumen();
  }

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
          this.router.navigate(this.tienda.ruta('checkout', 'estado', String(pagoIniciado.pago.id)));
        },
        error: () => {
          ventana?.close();
          this.procesando.set(false);
          this.error.set('No se pudo iniciar el pago. Prueba de nuevo.');
        },
      });
  }
}
