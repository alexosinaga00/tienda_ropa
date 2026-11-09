import { DatePipe, DecimalPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, Injector, computed, inject, input, linkedSignal, output, signal } from '@angular/core';
import { AuthService } from '../../core/auth.service';
import { instanteServidor } from '../../core/date-utils';
import type { Reembolso } from '../../core/models/ventas.models';
import {
  EstadoReembolsoVista,
  VistaReembolso,
  comoSeDevolvio,
  estadoReembolso,
  reemplazarReembolso,
  sePuedeReintentar,
} from '../../core/reembolsos';
import { ReembolsosService } from '../../core/reembolsos.service';

/** El texto con que el servidor explicó el error (`detail` en texto, o `detail.mensaje` / `mensaje`). */
function mensajeDeError(error: HttpErrorResponse): string {
  if (error.status === 0) return 'Sin conexión con el servidor. Inténtalo de nuevo.';
  const detalle = error.error?.detail;
  if (typeof detalle === 'string' && detalle.trim()) return detalle;
  if (typeof detalle?.mensaje === 'string' && detalle.mensaje.trim()) return detalle.mensaje;
  return 'No se pudo reintentar el reembolso. Inténtalo de nuevo.';
}

/**
 * El dinero devuelto a quien compró: monto, cómo, cuándo y en qué estado. En la tienda (`vista = 'cliente'`) un fallo se
 * muestra como "En proceso"; en la Caja (`vista = 'personal'`) se ve el fallo y, con el permiso `pagos.gestionar`, el
 * botón "Reintentar" para el que quedó en proceso o falló. Al reintentar se actualiza solo y avisa con `actualizado`.
 */
@Component({
  selector: 'app-reembolsos',
  standalone: true,
  imports: [DatePipe, DecimalPipe],
  templateUrl: './reembolsos.component.html',
  styleUrl: './reembolsos.component.scss',
})
export class ReembolsosComponent {
  private readonly reembolsosService = inject(ReembolsosService);
  private readonly injector = inject(Injector);

  readonly reembolsos = input.required<Reembolso[]>();
  readonly vista = input<VistaReembolso>('cliente');
  /** Un reembolso quedó distinto tras reintentarlo (para que quien lo muestra actualice su copia). */
  readonly actualizado = output<Reembolso>();

  /** La lista que se dibuja: la de afuera, con los reintentos ya aplicados. */
  protected readonly items = linkedSignal(() => this.reembolsos());
  protected readonly reintentando = signal<number | null>(null);
  protected readonly errores = signal<Record<number, string>>({});

  /** Solo el personal con el permiso de pagos reintenta (el servidor lo vuelve a exigir). */
  protected readonly puedeReintentar = computed(
    () => this.vista() === 'personal' && this.injector.get(AuthService).tienePermiso('pagos.gestionar'),
  );

  /** Las fechas del servidor son UTC ("Z"); se muestran en la hora local del navegador. */
  protected readonly fecha = instanteServidor;

  protected estado(reembolso: Reembolso): EstadoReembolsoVista {
    return estadoReembolso(reembolso.estado, this.vista());
  }

  protected como(reembolso: Reembolso): string {
    return comoSeDevolvio(reembolso.metodo, this.vista());
  }

  protected monto(reembolso: Reembolso): number {
    return Number(reembolso.monto);
  }

  protected admiteReintento(reembolso: Reembolso): boolean {
    return this.puedeReintentar() && sePuedeReintentar(reembolso);
  }

  protected reintentar(reembolso: Reembolso): void {
    if (this.reintentando() !== null) return;
    this.reintentando.set(reembolso.id);
    this.errores.update(({ [reembolso.id]: _quitado, ...resto }) => resto);
    this.reembolsosService.reintentar(reembolso.id).subscribe({
      next: (nuevo) => {
        this.reintentando.set(null);
        this.items.update((lista) => reemplazarReembolso(lista, nuevo));
        this.actualizado.emit(nuevo);
      },
      error: (error: HttpErrorResponse) => {
        this.reintentando.set(null);
        this.errores.update((actuales) => ({ ...actuales, [reembolso.id]: mensajeDeError(error) }));
      },
    });
  }
}
