import { isPlatformBrowser } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, PLATFORM_ID, computed, inject, signal } from '@angular/core';
import { Title } from '@angular/platform-browser';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ContratacionService } from '../../../core/contratacion.service';
import { ErrorContratacion, errorDeContratacion } from '../../../core/mensajes-contratacion';
import { PedidoEstado, PedidoPagado } from '../../../core/models/contratacion.models';
import { IconoComponent } from '../../../shared/icono/icono.component';
import { ContratacionListoComponent } from '../contratacion-listo.component';
import { ContratarMarcoComponent } from '../contratar-marco.component';

export type EstadoRetorno = 'procesando' | 'listo' | 'cancelado' | 'soporte' | 'error' | 'sin_pedido';

/** Errores tras los cuales el pedido ya no sirve: se borra el token guardado y se empieza de nuevo. */
const CODIGOS_FINALES: ReadonlySet<string> = new Set([
  'pedido_vencido',
  'pedido_cancelado',
  'pedido_fallido',
  'pedido_no_encontrado',
  'pago_no_coincide',
]);

/**
 * `/contratar/retorno?pedido=<token>[&cancelado=1]`: adonde PayPal devuelve al comprador.
 * - Sin `cancelado`: cierra el pedido UNA vez (`POST .../capturar`, idempotente en el servidor: repetirlo no cobra
 *   dos veces ni crea dos empresas) y muestra la tienda creada. 503 y "pago no aprobado" se pueden reintentar;
 *   `pagado_sin_empresa` no (el pago se recibió y soporte lo resuelve).
 * - Con `cancelado=1`: cancela el pedido (`POST .../cancelar`) y ofrece volver a intentarlo.
 * El token sale de la dirección o, si falta, de sessionStorage. Nunca se escribe en logs ni se muestra.
 */
@Component({
  selector: 'app-contratar-retorno',
  standalone: true,
  imports: [RouterLink, IconoComponent, ContratarMarcoComponent, ContratacionListoComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './contratar-retorno.component.html',
  styleUrl: './contratar-retorno.component.scss',
})
export class ContratarRetornoComponent implements OnInit {
  private readonly ruta = inject(ActivatedRoute);
  private readonly servicio = inject(ContratacionService);
  private readonly titulo = inject(Title);
  private readonly esNavegador = isPlatformBrowser(inject(PLATFORM_ID));

  protected readonly estado = signal<EstadoRetorno>('procesando');
  protected readonly cargando = signal(false);
  protected readonly error = signal<ErrorContratacion | null>(null);
  protected readonly pagado = signal<PedidoPagado | null>(null);
  protected readonly cancelado = signal<PedidoEstado | null>(null);
  /** La página se abrió para cancelar (PayPal devuelve `cancelado=1` si el comprador se arrepintió). */
  protected readonly cancelando = signal(false);

  private token: string | null = null;

  /** Para "Volver a intentarlo": conserva el plan y el periodo del pedido si se conocen. */
  protected readonly nuevoIntento = computed<Record<string, string>>(() => {
    const pedido = this.cancelado();
    const base: Record<string, string> = { modo: 'pago' };
    if (pedido !== null) {
      base['plan'] = pedido.plan_codigo;
      base['periodo'] = pedido.periodo;
    }
    return base;
  });

  /** Reintentar sirve cuando repetir la misma petición puede funcionar (PayPal caído, sin red, pago sin aprobar aún). */
  protected readonly puedeReintentar = computed(() => {
    const error = this.error();
    return error !== null && (error.reintentable || error.codigo === 'pago_no_aprobado');
  });

  ngOnInit(): void {
    this.titulo.setTitle('Confirmando tu pago | FashionStore');
    // En el servidor (prerender) no se toca nada: el pedido se cierra solo en el navegador del comprador.
    if (!this.esNavegador) return;

    const parametros = this.ruta.snapshot.queryParamMap;
    this.token = parametros.get('pedido') || this.servicio.leerToken();
    this.cancelando.set(parametros.get('cancelado') === '1');
    if (this.token === null) {
      this.estado.set('sin_pedido');
      return;
    }
    this.ejecutar();
  }

  /** "Reintentar" / "Comprobar de nuevo". Ignorado mientras una petición está en curso. */
  protected reintentar(): void {
    if (this.cargando() || !this.puedeReintentar()) return;
    this.ejecutar();
  }

  private ejecutar(): void {
    const token = this.token;
    if (token === null || this.cargando()) return;
    this.cargando.set(true);
    this.error.set(null);
    this.estado.set('procesando');

    if (this.cancelando()) {
      this.servicio.cancelarPedido(token).subscribe({
        next: (pedido) => {
          this.servicio.limpiarToken();
          this.cancelado.set(pedido);
          this.estado.set('cancelado');
          this.cargando.set(false);
        },
        error: (falla: unknown) => {
          const error = errorDeContratacion(falla);
          // Si ya estaba pagado, lo correcto es cerrarlo (la captura devuelve la empresa sin cobrar otra vez).
          if (error.codigo === 'pedido_ya_pagado') {
            this.cancelando.set(false);
            this.cargando.set(false);
            this.ejecutar();
            return;
          }
          this.fallar(error);
        },
      });
      return;
    }

    this.servicio.capturarPedido(token).subscribe({
      next: (resultado) => {
        this.servicio.limpiarToken();
        this.pagado.set(resultado);
        this.estado.set('listo');
        this.titulo.setTitle('Tu tienda está lista | FashionStore');
        this.cargando.set(false);
      },
      error: (falla: unknown) => this.fallar(errorDeContratacion(falla)),
    });
  }

  private fallar(error: ErrorContratacion): void {
    this.cargando.set(false);
    this.error.set(error);
    if (CODIGOS_FINALES.has(error.codigo)) this.servicio.limpiarToken();
    // Con el pago ya recibido no se ofrece reintentar: lo resuelve soporte.
    this.estado.set(error.codigo === 'pagado_sin_empresa' ? 'soporte' : 'error');
  }
}
