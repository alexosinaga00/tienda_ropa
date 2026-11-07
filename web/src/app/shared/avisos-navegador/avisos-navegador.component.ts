import { ChangeDetectionStrategy, Component, OnInit, computed, inject, input } from '@angular/core';
import { PushWebService } from '../../core/push/push-web.service';
import { IconoComponent } from '../icono/icono.component';

/**
 * Tarjeta "Avisos en este navegador": activar o desactivar los avisos push de la web. El permiso del navegador se pide
 * SOLO al tocar "Activar avisos", nunca al cargar la página. Sin soporte, sin https o con el permiso bloqueado dice por
 * qué y no ofrece el botón.
 */
@Component({
  selector: 'app-avisos-navegador',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconoComponent],
  template: `
    <section class="avisos" data-estado="avisos-navegador" aria-label="Avisos en este navegador">
      <fs-icono nombre="campana" [tam]="24" />
      <div class="avisos__texto">
        <div class="avisos__titulo">Avisos en este navegador</div>
        <p class="avisos__detalle" data-estado="avisos-detalle" role="status">{{ detalle() }}</p>
      </div>
      @if (push.estado() === 'inactivo' || push.estado() === 'activando') {
        <button
          type="button"
          class="fs-btn fs-btn--secundario fs-btn--sm"
          data-estado="activar-avisos"
          [disabled]="push.estado() === 'activando'"
          (click)="push.activar()"
        >
          {{ push.estado() === 'activando' ? 'Activando…' : 'Activar avisos' }}
        </button>
      } @else if (push.estado() === 'activo') {
        <button type="button" class="fs-btn fs-btn--secundario fs-btn--sm" data-estado="desactivar-avisos" (click)="push.desactivar()">
          Desactivar
        </button>
      }
    </section>
  `,
  styles: `
    :host {
      display: block;
    }

    .avisos {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 12px;
      padding: 12px 16px;
      background: var(--fs-superficie);
      border: 1px solid var(--fs-borde);
      border-radius: var(--fs-radio-md);
      color: var(--fs-texto);
    }

    .avisos__texto {
      flex: 1 1 160px;
      min-width: 0;
    }

    .avisos__titulo {
      font-size: 14px;
      font-weight: 600;
    }

    .avisos__detalle {
      margin: 2px 0 0;
      font-size: 13px;
      color: var(--fs-texto-tenue);
    }

    .fs-btn {
      flex: none;
    }
  `,
})
export class AvisosNavegadorComponent implements OnInit {
  protected readonly push = inject(PushWebService);

  /** A quién se dirige el texto: el cliente de la tienda o el personal del back office. */
  readonly contexto = input<'cliente' | 'personal'>('cliente');

  protected readonly detalle = computed(() => {
    const mensaje = this.push.mensaje();
    if (mensaje) return mensaje;
    const que =
      this.contexto() === 'personal'
        ? 'nuevas reservas y operaciones sincronizadas'
        : 'tu compra confirmada, tus envíos y tus reservas';
    return this.push.estado() === 'activo'
      ? `Activados en este navegador: te avisaremos de ${que} aunque la pestaña esté cerrada.`
      : `Recibe un aviso de ${que} sin tener la pestaña abierta.`;
  });

  ngOnInit(): void {
    // Si ya estaban activados, deja el token al día y escuchando. No pide ningún permiso.
    void this.push.sincronizarSiActivo();
  }
}
