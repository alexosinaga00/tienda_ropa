import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { IconoComponent } from '../../shared/icono/icono.component';
import { PedidosSinConexionService } from './state/pedidos-sin-conexion.service';
import { TiendaActualService } from './state/tienda-actual.service';

/**
 * Franja de la tienda sobre los pedidos hechos sin conexión: avisa cuando uno pasó a cobrado o rechazado (hasta que el
 * cliente abre la pantalla) y, mientras no haya resultados nuevos, cuántos siguen por enviar.
 */
@Component({
  selector: 'app-aviso-pedidos-sin-conexion',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, IconoComponent],
  template: `
    <div role="status" aria-live="polite">
      @if (cobrados() > 0 || rechazados() > 0) {
        <div class="franja" [class.franja--error]="rechazados() > 0" data-estado="aviso-resultado">
          <fs-icono [nombre]="rechazados() > 0 ? 'alerta' : 'check'" [tam]="24" />
          <span class="franja__texto">{{ textoResultado() }}</span>
          <a class="franja__enlace" [routerLink]="tienda.ruta('mi-cuenta', 'pedidos-sin-conexion')">Ver</a>
        </div>
      } @else if (cola.pendientes().length > 0) {
        <div class="franja" data-estado="aviso-pendientes">
          <fs-icono nombre="reloj" [tam]="24" />
          <span class="franja__texto">
            {{
              cola.pendientes().length === 1
                ? 'Tienes 1 pedido sin conexión por enviar.'
                : 'Tienes ' + cola.pendientes().length + ' pedidos sin conexión por enviar.'
            }}
          </span>
          <a class="franja__enlace" [routerLink]="tienda.ruta('mi-cuenta', 'pedidos-sin-conexion')">Ver</a>
        </div>
      }
    </div>
  `,
  styles: `
    .franja {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 10px 16px;
      font-size: 14px;
      color: var(--fs-advertencia);
      background: var(--fs-advertencia-suave);
    }

    .franja--error {
      color: var(--fs-error);
      background: var(--fs-error-suave);
    }

    .franja__texto {
      flex: 1;
      min-width: 0;
    }

    .franja__enlace {
      display: inline-flex;
      align-items: center;
      min-height: var(--fs-toque);
      font-weight: 600;
      color: inherit;
      text-decoration: underline;
    }
  `,
})
export class AvisoPedidosSinConexionComponent {
  protected readonly cola = inject(PedidosSinConexionService);
  protected readonly tienda = inject(TiendaActualService);

  protected readonly cobrados = computed(() => this.cola.sinVer().filter((p) => p.estado === 'cobrado').length);
  protected readonly rechazados = computed(() => this.cola.sinVer().filter((p) => p.estado === 'rechazado').length);

  protected readonly textoResultado = computed(() => {
    const cobrados = this.cobrados();
    const rechazados = this.rechazados();
    const partes: string[] = [];
    if (cobrados > 0) partes.push(cobrados === 1 ? 'Cobramos 1 pedido que hiciste sin conexión' : `Cobramos ${cobrados} pedidos que hiciste sin conexión`);
    if (rechazados > 0) partes.push(rechazados === 1 ? 'no pudimos cobrar 1' : `no pudimos cobrar ${rechazados}`);
    const texto = partes.join(' y ');
    return `${texto.charAt(0).toUpperCase()}${texto.slice(1)}.`;
  });
}
