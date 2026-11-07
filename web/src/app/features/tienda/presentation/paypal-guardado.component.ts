import { Component, OnInit, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { MetodoPagoPaypal } from '../../../core/models/metodo-pago.models';
import { IconoComponent } from '../../../shared/icono/icono.component';
import { MetodoPagoService, mensajeErrorMetodoPago } from '../data/metodo-pago.service';
import { MetodoPagoLocalService } from '../state/metodo-pago-local.service';
import { TiendaActualService } from '../state/tienda-actual.service';

export type ResultadoRetornoPaypal = 'confirmando' | 'exito' | 'cancelado' | 'error' | 'sin_datos';

/**
 * A donde PayPal devuelve al cliente (`/t/<codigo>/mi-cuenta/paypal-guardado`). Lee `approval_token_id` (o
 * `cancelado=1`), le pide al servidor que confirme y cuenta cómo salió. Confirmar es idempotente: al recargar la página
 * se vuelve a confirmar y da el mismo resultado.
 */
@Component({
  selector: 'app-paypal-guardado',
  standalone: true,
  imports: [RouterLink, IconoComponent],
  templateUrl: './paypal-guardado.component.html',
  styleUrl: './paypal-guardado.component.scss',
})
export class PaypalGuardadoComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly api = inject(MetodoPagoService);
  private readonly local = inject(MetodoPagoLocalService);
  protected readonly tienda = inject(TiendaActualService);

  protected readonly resultado = signal<ResultadoRetornoPaypal>('confirmando');
  protected readonly metodo = signal<MetodoPagoPaypal | null>(null);
  protected readonly mensajeError = signal<string | null>(null);

  private token: string | null = null;

  ngOnInit(): void {
    const parametros = this.route.snapshot.queryParamMap;
    if (parametros.get('cancelado') === '1') {
      this.resultado.set('cancelado');
      return;
    }
    this.token = parametros.get('approval_token_id');
    if (!this.token) {
      this.resultado.set('sin_datos');
      return;
    }
    this.confirmar();
  }

  protected confirmar(): void {
    if (!this.token) return;
    this.resultado.set('confirmando');
    this.mensajeError.set(null);
    this.api.confirmar(this.token).subscribe({
      next: (metodo) => {
        this.metodo.set(metodo);
        this.resultado.set('exito');
        void this.local.recordar(metodo);
      },
      error: (error: unknown) => {
        this.mensajeError.set(mensajeErrorMetodoPago(error));
        this.resultado.set('error');
      },
    });
  }
}
