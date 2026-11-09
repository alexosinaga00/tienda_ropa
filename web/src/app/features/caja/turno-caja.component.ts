import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, DestroyRef, Injector, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DialogModule } from 'primeng/dialog';
import { Subscription } from 'rxjs';
import { AuthService } from '../../core/auth.service';
import { ConectividadService } from '../../core/conectividad.service';
import { instanteServidor } from '../../core/date-utils';
import { codigoFuncional } from '../../core/errores-funcionales';
import { Turno, mensajeErrorCaja, montoParaServidor } from '../../core/models/caja.models';
import { ColaSincronizacionService } from '../../core/offline/cola-sincronizacion.service';
import { TurnosCajaService } from '../../core/turnos-caja.service';
import { IconoComponent } from '../../shared/icono/icono.component';
import { ConteoTurnoComponent } from './conteo-turno.component';

/**
 * Barra de turno de la Caja: la caja es de la SUCURSAL y a lo sumo hay un turno abierto por sucursal. Sin turno avisa que
 * lo que se cobre no entra a ninguna caja (vender sin turno sigue permitido) y ofrece abrirlo con un monto inicial; con
 * turno dice quién lo abrió y desde cuándo, y ofrece cerrarlo contando el efectivo (cierre ciego: ver `ConteoTurnoComponent`).
 * Un supervisor ve además el efectivo esperado en vivo.
 *
 * Cargar el turno NUNCA bloquea ni rompe el cobro: si la consulta falla solo se muestra un aviso discreto. Sin conexión no
 * se consulta nada y abrir o cerrar quedan desactivados.
 */
@Component({
  selector: 'app-turno-caja',
  standalone: true,
  imports: [DatePipe, DecimalPipe, FormsModule, DialogModule, IconoComponent, ConteoTurnoComponent],
  templateUrl: './turno-caja.component.html',
  styleUrl: './turno-caja.component.scss',
})
export class TurnoCajaComponent {
  private readonly servicio = inject(TurnosCajaService);
  private readonly auth = inject(AuthService);
  private readonly conectividad = inject(ConectividadService);
  private readonly injector = inject(Injector);

  /** La sucursal de la caja (la elegida, para el administrador). */
  readonly sucursalId = input<number | null>(null);
  /** El administrador (alcance global) manda `sucursal_id`; el cajero no: el servidor usa la suya. */
  readonly enviarSucursal = input(false);
  /** Cambia con cada venta cobrada: un supervisor vuelve a leer el esperado en vivo. */
  readonly actualizarCon = input<unknown>(null);
  /** Hay un diálogo del turno abierto: la Caja no debe atender sus atajos de teclado (F2, F9...). */
  readonly dialogoAbierto = output<boolean>();

  protected readonly turno = signal<Turno | null>(null);
  protected readonly sugerido = signal<string | null>(null);
  protected readonly cargando = signal(false);
  protected readonly errorCarga = signal(false);
  /** Ya se supo, al menos una vez, cómo está el turno de esta sucursal. */
  protected readonly conocido = signal(false);

  protected readonly sinConexion = computed(() => this.conectividad.estado() !== 'en_linea');
  protected readonly esSupervisor = computed(() => this.auth.tienePermiso('caja.supervisar'));

  // ---- Abrir ----
  protected readonly abriendo = signal(false);
  protected readonly montoInicial = signal<number | null>(null);
  protected readonly observacionApertura = signal('');
  protected readonly enviandoApertura = signal(false);
  protected readonly errorApertura = signal<string | null>(null);
  protected readonly montoInicialValido = computed(() => montoParaServidor(this.montoInicial()) !== null);

  // ---- Cerrar ----
  /** El turno que se está cerrando; sigue ahí mientras el diálogo muestra el resultado, aunque `turno` ya sea null. */
  protected readonly cerrando = signal<Turno | null>(null);
  protected readonly preparandoCierre = signal(false);
  protected readonly pendientesLocales = signal(0);

  private peticion?: Subscription;
  private sucursalCargada: number | null | undefined = undefined;

  constructor() {
    inject(DestroyRef).onDestroy(() => this.peticion?.unsubscribe());

    // Al conocer la sucursal (o cambiarla, o volver la conexión) se lee el turno.
    effect(() => {
      const sucursal = this.sucursalId();
      this.enviarSucursal();
      this.sinConexion();
      untracked(() => {
        if (sucursal !== this.sucursalCargada) {
          this.sucursalCargada = sucursal;
          this.peticion?.unsubscribe();
          this.turno.set(null);
          this.sugerido.set(null);
          this.conocido.set(false);
          this.errorCarga.set(false);
        }
        this.cargar(true);
      });
    });

    // Una venta cobrada cambia el esperado en vivo: solo lo ve un supervisor.
    effect(() => {
      const venta = this.actualizarCon();
      untracked(() => {
        if (venta != null && this.esSupervisor() && this.turno() !== null) this.cargar(false);
      });
    });

    // Avisa a la Caja si hay un diálogo abierto para que no dispare sus atajos de teclado.
    const hayDialogo = computed(() => this.abriendo() || this.cerrando() !== null);
    effect(() => this.dialogoAbierto.emit(hayDialogo()));
  }

  /** Lee el turno de la sucursal. Un fallo no molesta al cobro: queda un aviso discreto con "Reintentar". */
  protected cargar(conIndicador = true): void {
    this.peticion?.unsubscribe();
    const sucursal = this.sucursalId();
    if (this.sinConexion() || (this.enviarSucursal() && sucursal === null)) {
      this.cargando.set(false);
      return;
    }
    if (conIndicador) this.cargando.set(true);
    this.errorCarga.set(false);
    this.peticion = this.servicio.actual(this.enviarSucursal() ? sucursal : null).subscribe({
      next: (respuesta) => {
        this.cargando.set(false);
        this.conocido.set(true);
        this.turno.set(respuesta.turno);
        this.sugerido.set(respuesta.monto_inicial_sugerido);
      },
      error: () => {
        this.cargando.set(false);
        this.errorCarga.set(true);
      },
    });
  }

  protected hora(iso: string): Date {
    return instanteServidor(iso);
  }

  protected num(valor: string | null | undefined): number {
    return Number(valor ?? 0);
  }

  // ---- Abrir turno ----

  protected abrirDialogoApertura(): void {
    if (this.sinConexion() || this.enviandoApertura()) return;
    const sugerido = this.sugerido();
    this.montoInicial.set(sugerido !== null && Number.isFinite(Number(sugerido)) ? Number(sugerido) : null);
    this.observacionApertura.set('');
    this.errorApertura.set(null);
    this.abriendo.set(true);
  }

  protected cancelarApertura(): void {
    if (this.enviandoApertura()) return;
    this.abriendo.set(false);
  }

  protected abrirTurno(): void {
    const monto = montoParaServidor(this.montoInicial());
    if (monto === null || this.enviandoApertura() || this.sinConexion()) return;
    const observacion = this.observacionApertura().trim();
    this.enviandoApertura.set(true);
    this.errorApertura.set(null);
    this.servicio
      .abrir({
        ...(this.enviarSucursal() && this.sucursalId() !== null ? { sucursal_id: this.sucursalId()! } : {}),
        monto_inicial: monto,
        ...(observacion ? { observacion } : {}),
      })
      .subscribe({
        next: (turno) => {
          this.enviandoApertura.set(false);
          this.abriendo.set(false);
          this.conocido.set(true);
          this.turno.set(turno);
        },
        error: (error: unknown) => {
          this.enviandoApertura.set(false);
          this.errorApertura.set(mensajeErrorCaja(error, 'No se pudo abrir el turno.'));
          // Otra persona ya lo abrió: se lee para que la barra diga la verdad.
          if (codigoFuncional(error) === 'turno_ya_abierto') this.cargar(false);
        },
      });
  }

  // ---- Cerrar turno ----

  /** Cuenta las operaciones sin sincronizar de este equipo antes de abrir el cierre: no cuentan en el esperado. */
  protected async abrirCierre(): Promise<void> {
    const turno = this.turno();
    if (turno === null || this.sinConexion() || this.preparandoCierre()) return;
    this.preparandoCierre.set(true);
    try {
      this.pendientesLocales.set(await this.contarPendientes());
    } finally {
      this.preparandoCierre.set(false);
    }
    this.cerrando.set(turno);
  }

  /** Pendientes de envío de este equipo (los míos y los de otros usuarios). Un fallo cuenta como 0: no frena el cierre. */
  private async contarPendientes(): Promise<number> {
    try {
      const cola = this.injector.get(ColaSincronizacionService);
      await cola.refrescarConteos();
      return cola.pendientes() + cola.pendientesDeOtros();
    } catch {
      return 0;
    }
  }

  /** El servidor aceptó el cierre: la barra pasa a "sin turno" y el diálogo sigue mostrando el resultado. */
  protected alCerrar(): void {
    this.turno.set(null);
    this.cargar(false);
  }

  protected finalizarCierre(): void {
    this.cerrando.set(null);
  }
}
