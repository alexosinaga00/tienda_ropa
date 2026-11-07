import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AvisosNavegadorComponent } from '../../../shared/avisos-navegador/avisos-navegador.component';
import { PedidosSinConexionService } from '../state/pedidos-sin-conexion.service';
import { TiendaActualService } from '../state/tienda-actual.service';

export type PestanaCuenta = 'compras' | 'reservas' | 'metodo-pago' | 'sin-conexion';

/** Las pestañas de "Mi cuenta" (compras, reservas, método de pago y pedidos sin conexión), compartidas por sus pantallas. */
@Component({
  selector: 'app-mi-cuenta-pestanas',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, AvisosNavegadorComponent],
  template: `
    <nav class="fs-tabs pestanas" aria-label="Mi cuenta">
      <a
        class="fs-tab"
        [class.fs-tab--activa]="activa() === 'compras'"
        [attr.aria-current]="activa() === 'compras' ? 'page' : null"
        [routerLink]="tienda.ruta('mis-compras')"
        >Compras</a
      >
      <a
        class="fs-tab"
        [class.fs-tab--activa]="activa() === 'reservas'"
        [attr.aria-current]="activa() === 'reservas' ? 'page' : null"
        [routerLink]="tienda.ruta('mis-reservas')"
        >Reservas</a
      >
      <a
        class="fs-tab"
        [class.fs-tab--activa]="activa() === 'metodo-pago'"
        [attr.aria-current]="activa() === 'metodo-pago' ? 'page' : null"
        [routerLink]="tienda.ruta('mi-cuenta', 'metodo-pago')"
        >Método de pago</a
      >
      <a
        class="fs-tab"
        [class.fs-tab--activa]="activa() === 'sin-conexion'"
        [attr.aria-current]="activa() === 'sin-conexion' ? 'page' : null"
        [routerLink]="tienda.ruta('mi-cuenta', 'pedidos-sin-conexion')"
        >Sin conexión @if (cola.pendientes().length + cola.sinVer().length > 0) {
          <span class="fs-chip fs-chip--advertencia" data-estado="contador-sin-conexion">{{
            cola.pendientes().length + cola.sinVer().length
          }}</span>
        }</a
      >
    </nav>
    <app-avisos-navegador class="avisos" contexto="cliente" />
  `,
  styles: `
    :host {
      display: block;
      margin-bottom: 24px;
    }

    .avisos {
      margin-top: 16px;
    }

    .fs-tabs {
      overflow-x: auto;
    }

    .fs-tab {
      white-space: nowrap;
    }
  `,
})
export class MiCuentaPestanasComponent {
  protected readonly tienda = inject(TiendaActualService);
  protected readonly cola = inject(PedidosSinConexionService);
  readonly activa = input.required<PestanaCuenta>();
}
