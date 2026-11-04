import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { IconoComponent } from '../../shared/icono/icono.component';
import { MarcaComponent } from '../../shared/marca/marca.component';

/**
 * Marco de las páginas de contratación (`/contratar` y `/contratar/retorno`): superficie oscura como la portada,
 * barra con la marca y "Volver a la portada", un hueco para los pasos y el cuerpo. No tiene lógica.
 */
@Component({
  selector: 'app-contratar-marco',
  standalone: true,
  imports: [RouterLink, IconoComponent, MarcaComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'fs-zona-oscura' },
  template: `
    <header class="marco__barra">
      <a class="marco__marca" routerLink="/" aria-label="FashionStore, inicio">
        <fs-marca nombre="FashionStore" variante="oscuro" />
      </a>
      <ng-content select="[pasos]" />
      <a class="marco__volver" routerLink="/" aria-label="Volver a la portada">
        <fs-icono nombre="flecha-izquierda" [tam]="24" />
        <span>Volver a la portada</span>
      </a>
    </header>
    <main class="marco__cuerpo">
      <ng-content />
    </main>
  `,
  styles: `
    :host {
      display: block;
      min-height: 100vh;
      min-height: 100svh;
      font-family: var(--fs-fuente-ui);
      font-size: 16px;
      line-height: 1.5;
    }

    .marco__barra {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 8px 24px;
      min-height: 72px;
      padding: 8px clamp(20px, 6.7vw, 92px);
      background: var(--fs-carbon);
      border-bottom: 1px solid var(--fs-carbon-borde);
    }

    .marco__marca {
      display: inline-flex;
      color: inherit;
      text-decoration: none;
    }

    .marco__volver {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: var(--fs-toque);
      padding: 0 14px;
      border-radius: var(--fs-radio-sm);
      color: var(--fs-claro-tenue);
      font-size: 14px;
      font-weight: 600;
      text-decoration: none;

      &:hover {
        color: var(--fs-claro);
        background: var(--fs-carbon-panel);
      }

      &:focus-visible {
        outline: 2px solid var(--fs-acento-oscuro);
        outline-offset: 2px;
      }
    }

    .marco__cuerpo {
      max-width: 1120px;
      margin: 0 auto;
      padding: 36px clamp(20px, 6.7vw, 92px) 64px;
    }

    @media (max-width: 700px) {
      .marco__volver span {
        display: none;
      }
    }
  `,
})
export class ContratarMarcoComponent {}
