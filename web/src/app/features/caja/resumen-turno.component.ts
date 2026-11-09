import { DecimalPipe } from '@angular/common';
import { Component, input } from '@angular/core';
import type { Turno } from '../../core/models/caja.models';

/**
 * De dónde sale el efectivo esperado de un turno: monto inicial + efectivo cobrado - efectivo devuelto. Debajo, lo que
 * es solo informativo y NO entra al cajón (QR, tarjeta, transferencia y compras online). Sin `resumen` (un cajero con el
 * turno abierto) no dibuja nada: el cierre es ciego.
 */
@Component({
  selector: 'app-resumen-turno',
  standalone: true,
  imports: [DecimalPipe],
  template: `
    @if (turno().resumen; as r) {
      <dl class="resumen" data-estado="resumen-turno">
        <div><dt>Monto inicial</dt><dd class="fs-num">Bs {{ n(turno().monto_inicial) | number: '1.2-2' }}</dd></div>
        <div>
          <dt>Efectivo cobrado ({{ r.cantidad_ventas }} {{ r.cantidad_ventas === 1 ? 'venta' : 'ventas' }})</dt>
          <dd class="fs-num">+ Bs {{ n(r.ventas_efectivo) | number: '1.2-2' }}</dd>
        </div>
        <div><dt>Reembolsos en efectivo</dt><dd class="fs-num">- Bs {{ n(r.reembolsos_efectivo) | number: '1.2-2' }}</dd></div>
        <div class="total"><dt>Efectivo esperado</dt><dd class="fs-num">Bs {{ n(r.monto_esperado) | number: '1.2-2' }}</dd></div>
      </dl>
      <p class="aparte">Solo informativo, no entra al cajón</p>
      <dl class="resumen resumen--info" data-estado="resumen-informativo">
        <div><dt>QR, tarjeta y transferencia</dt><dd class="fs-num">Bs {{ n(r.ventas_otros_metodos) | number: '1.2-2' }}</dd></div>
        <div>
          <dt>Ventas online del día ({{ r.cantidad_ventas_online }})</dt>
          <dd class="fs-num">Bs {{ n(r.ventas_online) | number: '1.2-2' }}</dd>
        </div>
      </dl>
    }
  `,
  styles: `
    :host {
      display: block;
    }
    .resumen {
      margin: 0;
      display: grid;
      gap: var(--fs-espacio-1);
      font-size: 14px;
    }
    .resumen div {
      display: flex;
      justify-content: space-between;
      gap: var(--fs-espacio-3);
    }
    dt {
      color: var(--fs-texto-tenue);
    }
    dd {
      margin: 0;
      text-align: right;
    }
    .total {
      padding-top: var(--fs-espacio-1);
      border-top: 1px solid var(--fs-borde);
      font-weight: 600;
    }
    .total dt {
      color: var(--fs-texto);
    }
    .aparte {
      margin: var(--fs-espacio-3) 0 var(--fs-espacio-1);
      font-size: 12px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--fs-texto-tenue);
    }
  `,
})
export class ResumenTurnoComponent {
  readonly turno = input.required<Turno>();

  /** Los montos del servidor llegan como texto decimal. */
  protected n(valor: string | null | undefined): number {
    return Number(valor ?? 0);
  }
}
