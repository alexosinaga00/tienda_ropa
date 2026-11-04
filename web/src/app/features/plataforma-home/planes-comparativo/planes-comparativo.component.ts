import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { FUNCIONES_PLAN, FuncionPlan, PlanPublico } from '../../../core/models/plan.models';
import { formatearBs, tienePrecio } from '../../../core/utils/precio-plan';
import { IconoComponent } from '../../../shared/icono/icono.component';

/** Una fila de la tarjeta de un plan. */
interface FilaPlan {
  texto: string;
  incluida: boolean;
}

interface TarjetaPlan {
  codigo: string;
  nombre: string;
  /** El plan con más sucursales (si es uno solo): se resalta como "plan completo". */
  completo: boolean;
  /** "Bs 120" (por mes); cadena vacía si el plan no tiene precio publicado: entonces no se puede elegir. */
  precio: string;
  filas: FilaPlan[];
}

/** Las copias de seguridad llevan un número propio, así que tienen su fila aparte. */
const FUNCION_COPIAS: FuncionPlan = 'copias_seguridad';

function etiquetaDe(id: FuncionPlan): string {
  return FUNCIONES_PLAN.find((f) => f.id === id)?.etiqueta ?? id;
}

function textoSucursales(n: number): string {
  return `Hasta ${n} ${n === 1 ? 'sucursal activa' : 'sucursales activas'}`;
}

/**
 * Comparativo de planes de la portada. Sirve para cualquier cantidad de planes: lo que todos
 * incluyen va en una línea y cada tarjeta muestra solo lo que cambia, con su precio por mes y un
 * "Elegir plan" que lleva a la página de contratación (`/contratar?plan=<código>`). Un plan sin precio
 * publicado dice "Precio a consultar" y no se puede elegir. El anual se calcula en la página de compra.
 */
@Component({
  selector: 'app-planes-comparativo',
  standalone: true,
  imports: [IconoComponent, RouterLink],
  templateUrl: './planes-comparativo.component.html',
  styleUrl: './planes-comparativo.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '[class.planes--oscuro]': 'variante() === "oscuro"' },
})
export class PlanesComparativoComponent {
  /** Planes activos, ya ordenados por sucursales (el servidor los entrega así). */
  readonly planes = input.required<readonly PlanPublico[]>();
  /** `oscuro`: tarjetas traslúcidas para ir sobre la escena 3D de la portada. Por omisión, el diseño claro. */
  readonly variante = input<'claro' | 'oscuro'>('claro');

  /** Ruta de la página de contratación. */
  protected readonly rutaContratar = '/contratar';

  /** Funcionalidades (sin copias) que TODOS los planes incluyen. */
  protected readonly comunes = computed<string[]>(() => {
    const planes = this.planes();
    if (!planes.length) return [];
    return FUNCIONES_PLAN.filter((f) => f.id !== FUNCION_COPIAS && planes.every((p) => p[f.id])).map(
      (f) => f.etiqueta,
    );
  });

  protected readonly tarjetas = computed<TarjetaPlan[]>(() => {
    const planes = this.planes();
    if (!planes.length) return [];
    const maximo = Math.max(...planes.map((p) => p.max_sucursales));
    const hayCompleto = planes.length > 1 && planes.filter((p) => p.max_sucursales === maximo).length === 1;
    // Solo las funcionalidades que cambian: si todos las tienen o ninguno, no distinguen un plan de otro.
    const variables = FUNCIONES_PLAN.filter(
      (f) => f.id !== FUNCION_COPIAS && planes.some((p) => p[f.id]) && !planes.every((p) => p[f.id]),
    );
    const hayCopias = planes.some((p) => p[FUNCION_COPIAS]);

    return planes.map((plan) => {
      const filas: FilaPlan[] = [
        { texto: textoSucursales(plan.max_sucursales), incluida: true },
        { texto: `Plazo de cambio: ${plan.plazo_cambio_horas_defecto} h`, incluida: true },
      ];
      if (hayCopias) {
        filas.push({
          texto: plan[FUNCION_COPIAS]
            ? `${etiquetaDe(FUNCION_COPIAS)}: guarda ${plan.max_copias_historial}`
            : etiquetaDe(FUNCION_COPIAS),
          incluida: plan[FUNCION_COPIAS],
        });
      }
      for (const funcion of variables) {
        filas.push({ texto: funcion.etiqueta, incluida: plan[funcion.id] });
      }
      return {
        codigo: plan.codigo,
        nombre: plan.nombre,
        completo: hayCompleto && plan.max_sucursales === maximo,
        precio: tienePrecio(plan.precio_mensual_bs) ? formatearBs(plan.precio_mensual_bs) : '',
        filas,
      };
    });
  });
}
