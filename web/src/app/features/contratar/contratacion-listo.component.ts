import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { RUTA_LOGIN_PERSONAL } from '../../core/auth.service';
import { fechaDesdeIso } from '../../core/date-utils';
import { IconoComponent } from '../../shared/icono/icono.component';
import { MarcaComponent } from '../../shared/marca/marca.component';

/** "2026-11-17" -> "17 de noviembre de 2026". Una fecha ilegible se muestra tal cual. */
export function fechaLarga(iso: string | null | undefined): string {
  if (!iso) return '';
  const fecha = fechaDesdeIso(iso);
  if (Number.isNaN(fecha.getTime())) return iso;
  return new Intl.DateTimeFormat('es-BO', { day: 'numeric', month: 'long', year: 'numeric' }).format(fecha);
}

/**
 * Pantalla "tu tienda está lista", común a la prueba gratuita (`/contratar`) y a la compra (`/contratar/retorno`).
 * Lleva a la tienda recién creada y al acceso del personal. No muestra tokens ni la contraseña.
 */
@Component({
  selector: 'app-contratacion-listo',
  standalone: true,
  imports: [RouterLink, IconoComponent, MarcaComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './contratacion-listo.component.html',
  styleUrl: './contratacion-listo.component.scss',
})
export class ContratacionListoComponent {
  readonly empresaCodigo = input.required<string>();
  readonly empresaNombre = input.required<string>();
  readonly planNombre = input<string>('');
  readonly esPrueba = input(false);
  readonly fechaVencimiento = input<string | null>(null);
  /** Correo con el que entra el administrador (solo se conoce en la prueba, porque se acaba de escribir). */
  readonly correo = input<string | null>(null);

  protected readonly rutaAcceso = RUTA_LOGIN_PERSONAL;
  protected readonly vence = computed(() => fechaLarga(this.fechaVencimiento()));
  protected readonly subtitulo = computed(() => {
    const plan = this.planNombre() ? ` ${this.planNombre()}` : '';
    const hasta = this.vence();
    if (this.esPrueba()) {
      return `Plan${plan} en prueba gratis${hasta ? ` hasta el ${hasta}` : ''}. No pagaste nada.`;
    }
    return `Pago confirmado. Plan${plan}${hasta ? ` activo hasta el ${hasta}` : ' activo'}.`;
  });
}
