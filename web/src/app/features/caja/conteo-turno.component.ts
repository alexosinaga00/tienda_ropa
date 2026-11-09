import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, DestroyRef, computed, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { DialogModule } from 'primeng/dialog';
import { Observable } from 'rxjs';
import { codigoFuncional } from '../../core/errores-funcionales';
import { instanteServidor } from '../../core/date-utils';
import {
  Turno,
  claseDiferencia,
  mensajeErrorCaja,
  montoParaServidor,
  textoDiferencia,
} from '../../core/models/caja.models';
import { TurnosCajaService } from '../../core/turnos-caja.service';
import { IconoComponent } from '../../shared/icono/icono.component';
import { ResumenTurnoComponent } from './resumen-turno.component';

export type ModoConteo = 'cerrar' | 'completar';

/**
 * Diálogo para CONTAR el efectivo del cajón: al cerrar un turno (`cerrar`) o al completar el conteo de un turno que se
 * cerró solo al terminar el día (`completar`, solo un supervisor).
 *
 * Cierre CIEGO: quien cierra su propio turno NO ve el esperado hasta enviar el conteo (`mostrarEsperado` es falso); recién
 * entonces el diálogo muestra el esperado, lo contado y la diferencia. Un supervisor sí lo ve antes (`mostrarEsperado`).
 * Si la diferencia no es cero la observación es obligatoria: el servidor responde `observacion_requerida` y el diálogo
 * muestra el campo para volver a intentar.
 *
 * El componente es el diálogo entero: quien lo usa lo pone con un `@if` y lo quita al recibir `terminado`.
 */
@Component({
  selector: 'app-conteo-turno',
  standalone: true,
  imports: [DatePipe, DecimalPipe, FormsModule, DialogModule, IconoComponent, ResumenTurnoComponent],
  templateUrl: './conteo-turno.component.html',
  styleUrl: './conteo-turno.component.scss',
})
export class ConteoTurnoComponent {
  private readonly servicio = inject(TurnosCajaService);
  private readonly destroyRef = inject(DestroyRef);

  readonly turno = input.required<Turno>();
  readonly modo = input<ModoConteo>('cerrar');
  /** Un supervisor ve el esperado antes de contar; quien cierra su propio turno, no. */
  readonly mostrarEsperado = input(false);
  /** Operaciones guardadas sin conexión en este equipo que aún no llegaron al servidor (solo al cerrar). */
  readonly pendientes = input(0);

  /** El servidor aceptó el conteo: quien lo usa ya puede refrescar su estado. El diálogo sigue abierto con el resultado. */
  readonly cerrado = output<Turno>();
  /** La persona cerró el diálogo (cancelar, la X o "Listo"). */
  readonly terminado = output<void>();

  protected readonly contado = signal<number | null>(null);
  protected readonly observacion = signal('');
  protected readonly enviando = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly pideObservacion = signal(false);
  protected readonly resultado = signal<Turno | null>(null);

  protected readonly esCompletar = computed(() => this.modo() === 'completar');
  protected readonly titulo = computed(() => (this.esCompletar() ? 'Completar conteo' : 'Cerrar turno'));
  protected readonly montoValido = computed(() => montoParaServidor(this.contado()) !== null);
  /** Al completar un conteo la observación siempre es obligatoria (3 a 300 caracteres). */
  protected readonly observacionValida = computed(() => !this.esCompletar() || this.observacion().trim().length >= 3);
  protected readonly mostrarObservacion = computed(
    () => this.esCompletar() || this.pideObservacion() || this.mostrarEsperado(),
  );
  protected readonly puedeEnviar = computed(
    () => this.montoValido() && this.observacionValida() && !this.enviando(),
  );

  protected readonly num = (valor: string | null | undefined): number => Number(valor ?? 0);
  protected readonly claseDiferencia = claseDiferencia;
  protected readonly textoDiferencia = textoDiferencia;
  protected readonly fecha = instanteServidor;

  protected confirmar(): void {
    const efectivo = montoParaServidor(this.contado());
    if (efectivo === null || !this.puedeEnviar()) return;
    const observacion = this.observacion().trim();
    const turno = this.turno();
    this.enviando.set(true);
    this.error.set(null);

    const peticion$: Observable<Turno> = this.esCompletar()
      ? this.servicio.completarConteo(turno.id, { efectivo_contado: efectivo, observacion })
      : this.servicio.cerrar(turno.id, {
          efectivo_contado: efectivo,
          ...(observacion ? { observacion } : {}),
          pendientes_sin_sincronizar: this.pendientes(),
        });

    peticion$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (actualizado) => {
        this.enviando.set(false);
        this.resultado.set(actualizado);
        this.cerrado.emit(actualizado);
      },
      error: (error: unknown) => {
        this.enviando.set(false);
        if (codigoFuncional(error) === 'observacion_requerida') this.pideObservacion.set(true);
        this.error.set(
          mensajeErrorCaja(error, this.esCompletar() ? 'No se pudo guardar el conteo.' : 'No se pudo cerrar el turno.'),
        );
      },
    });
  }

  protected terminar(): void {
    if (this.enviando()) return;
    this.terminado.emit();
  }

  protected plural(cantidad: number): string {
    return cantidad === 1 ? '1 operación sin sincronizar: no cuenta' : `${cantidad} operaciones sin sincronizar: no cuentan`;
  }
}
