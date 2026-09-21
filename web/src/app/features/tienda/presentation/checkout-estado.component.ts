import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { MetodoPagoPasarela, Pago } from '../../../core/models/pagos.models';
import { PagosService } from '../data/pagos.service';
import { CheckoutService } from '../state/checkout.service';

const INTERVALO_MS = 3000;
const MAX_INTENTOS = 20;
// Corte propio, y más corto, para las consultas que fallan: varios errores
// seguidos son la red o el backend caídos, no una pasarela lenta. Sin un
// corte en la rama de error el intervalo seguía disparando para siempre y
// el interceptor apilaba un aviso cada 3 segundos.
const MAX_INTENTOS_ERROR = 5;

@Component({
  selector: 'app-checkout-estado',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './checkout-estado.component.html',
  styleUrl: './checkout-estado.component.scss',
})
export class CheckoutEstadoComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly pagosService = inject(PagosService);
  protected readonly checkoutService = inject(CheckoutService);

  protected readonly pagoId = signal(Number(this.route.snapshot.paramMap.get('pagoId')));
  protected readonly pago = signal<Pago | null>(null);
  protected readonly cargando = signal(true);
  protected readonly agotado = signal(false);
  protected readonly reintentando = signal(false);
  // Distinto de `agotado`: ahí la pasarela no confirmó, acá no pudimos ni
  // preguntarle. Mostrarlos igual ocultaba que la consulta estaba fallando.
  protected readonly errorConsulta = signal(false);

  private intervalo?: ReturnType<typeof setInterval>;
  private intentos = 0;
  private intentosError = 0;

  ngOnInit(): void {
    this.iniciarPolling();
  }

  ngOnDestroy(): void {
    clearInterval(this.intervalo);
  }

  consultarAhora(): void {
    this.cargando.set(true);
    this.consultar();
  }

  reintentar(): void {
    const venta = this.checkoutService.venta();
    const metodoPago = this.checkoutService.pagoIniciado()?.pago.metodo_pago as MetodoPagoPasarela | undefined;
    if (!venta || !metodoPago || this.reintentando()) return;

    this.reintentando.set(true);
    const ventana = window.open('', '_blank');
    ventana?.document.write('Redirigiendo a la pasarela de pago...');

    this.pagosService.iniciar(venta.id, metodoPago).subscribe({
      next: (pagoIniciado) => {
        this.checkoutService.confirmarPago(pagoIniciado);
        this.checkoutService.ventanaPago = ventana;
        if (ventana) {
          ventana.location.href = pagoIniciado.url_redireccion;
        }
        this.reintentando.set(false);
        this.pagoId.set(pagoIniciado.pago.id);
        this.intentos = 0;
        this.agotado.set(false);
        this.pago.set(null);
        this.iniciarPolling();
      },
      error: () => {
        ventana?.close();
        this.reintentando.set(false);
      },
    });
  }

  /** Vuelve a arrancar el sondeo después de que se cortó por errores. */
  volverAConsultar(): void {
    this.errorConsulta.set(false);
    this.iniciarPolling();
  }

  private iniciarPolling(): void {
    clearInterval(this.intervalo);
    this.intentosError = 0;
    this.errorConsulta.set(false);
    this.consultarAhora();
    this.intervalo = setInterval(() => this.consultar(), INTERVALO_MS);
  }

  private consultar(): void {
    this.pagosService.obtenerEstado(this.pagoId()).subscribe({
      next: (pago) => {
        this.cargando.set(false);
        // Una consulta buena corta la racha: solo interesan los errores
        // seguidos, no uno suelto en medio de una espera larga.
        this.intentosError = 0;
        this.errorConsulta.set(false);
        this.pago.set(pago);
        if (pago.estado === 'aprobado' || pago.estado === 'rechazado') {
          this.detener();
          return;
        }
        this.intentos += 1;
        if (this.intentos >= MAX_INTENTOS) {
          this.agotado.set(true);
          this.detener();
        }
      },
      error: () => {
        this.cargando.set(false);
        this.intentosError += 1;
        if (this.intentosError >= MAX_INTENTOS_ERROR) {
          this.errorConsulta.set(true);
          this.detener();
        }
      },
    });
  }

  private detener(): void {
    clearInterval(this.intervalo);
    this.checkoutService.ventanaPago?.close();
    this.checkoutService.ventanaPago = null;
  }

  irAMiCompra(): void {
    const ventaId = this.pago()?.venta_id;
    if (ventaId) {
      this.router.navigate(['/mis-compras', ventaId]);
    }
  }
}
