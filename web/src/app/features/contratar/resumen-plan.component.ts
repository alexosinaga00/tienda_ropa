import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { FUNCIONES_PLAN, PlanPublico } from '../../core/models/plan.models';
import {
  DESCUENTO_ANUAL_PORCENTAJE,
  DIAS_PRUEBA,
  PeriodoPlan,
  ahorroAnual,
  aNumeroBs,
  equivalenteMensualAnual,
  formatearBs,
  montoDelPeriodo,
  tienePrecio,
} from '../../core/utils/precio-plan';
import { IconoComponent } from '../../shared/icono/icono.component';

export type ModoContratacion = 'prueba' | 'pago';

/**
 * Resumen fijo del plan elegido (columna derecha de `/contratar`): nombre, precio del periodo, mensual/anual (solo al
 * pagar), lo que incluye y la nota de la prueba. Solo MUESTRA: el cobro lo calcula siempre el servidor.
 */
@Component({
  selector: 'app-resumen-plan',
  standalone: true,
  imports: [IconoComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './resumen-plan.component.html',
  styleUrl: './resumen-plan.component.scss',
})
export class ResumenPlanComponent {
  readonly plan = input<PlanPublico | null>(null);
  readonly modo = input<ModoContratacion>('prueba');
  readonly periodo = input<PeriodoPlan>('mensual');

  readonly periodoCambia = output<PeriodoPlan>();

  protected readonly descuento = DESCUENTO_ANUAL_PORCENTAJE;
  protected readonly diasPrueba = DIAS_PRUEBA;

  protected readonly mensual = computed(() => aNumeroBs(this.plan()?.precio_mensual_bs));
  protected readonly conPrecio = computed(() => tienePrecio(this.plan()?.precio_mensual_bs));
  protected readonly alPagar = computed(() => this.modo() === 'pago');
  protected readonly anual = computed(() => this.alPagar() && this.periodo() === 'anual');

  protected readonly precio = computed(() => {
    const mensual = this.mensual();
    if (mensual === null || !this.conPrecio()) return '';
    return formatearBs(montoDelPeriodo(mensual, this.anual() ? 'anual' : 'mensual'));
  });
  protected readonly sufijo = computed(() => (this.anual() ? 'al año' : 'al mes'));
  protected readonly equivalente = computed(() => {
    const mensual = this.mensual();
    return mensual === null ? '' : formatearBs(equivalenteMensualAnual(mensual));
  });
  protected readonly ahorro = computed(() => {
    const mensual = this.mensual();
    return mensual === null ? '' : formatearBs(ahorroAnual(mensual));
  });

  protected readonly filas = computed<string[]>(() => {
    const plan = this.plan();
    if (plan === null) return [];
    const filas = [
      `Hasta ${plan.max_sucursales} ${plan.max_sucursales === 1 ? 'sucursal activa' : 'sucursales activas'}`,
      `Plazo de cambio: ${plan.plazo_cambio_horas_defecto} h`,
    ];
    for (const funcion of FUNCIONES_PLAN) {
      if (!plan[funcion.id]) continue;
      filas.push(
        funcion.id === 'copias_seguridad' ? `${funcion.etiqueta}: guarda ${plan.max_copias_historial}` : funcion.etiqueta,
      );
    }
    return filas;
  });

  protected elegirPeriodo(periodo: PeriodoPlan): void {
    if (periodo !== this.periodo()) this.periodoCambia.emit(periodo);
  }
}
