import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { DatePickerModule } from 'primeng/datepicker';
import { DialogModule } from 'primeng/dialog';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { Subscription } from 'rxjs';
import { fechaLocalIso, instanteServidor } from '../../core/date-utils';
import {
  EstadoCajaSucursal,
  EstadoTurno,
  Turno,
  TurnoDetalle,
  claseDiferencia,
  mensajeErrorCaja,
  textoDiferencia,
} from '../../core/models/caja.models';
import { TAMANIO_PAGINA_TURNOS, TurnosCajaService } from '../../core/turnos-caja.service';
import { ConteoTurnoComponent, ModoConteo } from '../caja/conteo-turno.component';
import { ResumenTurnoComponent } from '../caja/resumen-turno.component';
import { IconoComponent } from '../../shared/icono/icono.component';
import { ReembolsosComponent } from '../../shared/reembolsos/reembolsos.component';

/** Días hacia atrás del rango inicial del historial. */
export const DIAS_RANGO_INICIAL_CIERRES = 30;

interface OpcionEstado {
  label: string;
  value: EstadoTurno | null;
}

const OPCIONES_ESTADO: OpcionEstado[] = [
  { label: 'Todos los estados', value: null },
  { label: 'Abierta', value: 'abierta' },
  { label: 'Cerrada', value: 'cerrada' },
  { label: 'Cerrado sin conteo', value: 'cerrada_auto' },
];

/** El estado de un turno como lo ve el supervisor: un cierre automático sigue "sin conteo" hasta que se complete. */
export function etiquetaEstadoTurno(turno: Pick<Turno, 'estado' | 'conteo_en'>): string {
  if (turno.estado === 'abierta') return 'Abierta';
  if (turno.estado === 'cerrada_auto') return turno.conteo_en ? 'Cerrada (conteo completado)' : 'Cerrado sin conteo';
  return 'Cerrada';
}

export function claseEstadoTurno(turno: Pick<Turno, 'estado' | 'conteo_en'>): string {
  if (turno.estado === 'abierta') return 'fs-chip--exito';
  if (turno.estado === 'cerrada_auto' && !turno.conteo_en) return 'fs-chip--advertencia';
  return '';
}

/**
 * Cierres de caja (supervisor: encargado de su sucursal o administrador de todas). Arriba, "Cajas de hoy": una tarjeta por
 * sucursal con su turno y el efectivo esperado en vivo. Abajo, el historial de turnos con filtros y un detalle por turno
 * (resumen, ajuste posterior, observaciones y reembolsos) desde donde se cierra un turno ajeno o se completa el conteo de
 * un turno que se cerró solo al terminar el día.
 */
@Component({
  selector: 'app-cierres-caja',
  standalone: true,
  imports: [
    DatePipe,
    DecimalPipe,
    FormsModule,
    ButtonModule,
    DatePickerModule,
    DialogModule,
    SelectModule,
    TableModule,
    IconoComponent,
    ReembolsosComponent,
    ResumenTurnoComponent,
    ConteoTurnoComponent,
  ],
  templateUrl: './cierres-caja.component.html',
  styleUrl: './cierres-caja.component.scss',
})
export class CierresCajaComponent implements OnInit {
  private readonly servicio = inject(TurnosCajaService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly tamanioPagina = TAMANIO_PAGINA_TURNOS;
  protected readonly hoy = new Date();
  protected readonly opcionesEstado = OPCIONES_ESTADO;

  // ---- Cajas de hoy ----
  protected readonly cajas = signal<EstadoCajaSucursal[]>([]);
  protected readonly cargandoCajas = signal(false);
  protected readonly errorCajas = signal(false);

  // ---- Historial ----
  protected readonly desde = signal<Date | null>(this.diasAtras(DIAS_RANGO_INICIAL_CIERRES));
  protected readonly hasta = signal<Date | null>(new Date());
  protected readonly filtroSucursal = signal<number | null>(null);
  protected readonly filtroEstado = signal<EstadoTurno | null>(null);
  protected readonly turnos = signal<Turno[]>([]);
  protected readonly pagina = signal(1);
  protected readonly cargando = signal(false);
  protected readonly error = signal(false);

  /** El filtro de sucursal solo se ofrece a quien ve más de una (el administrador). */
  protected readonly opcionesSucursal = computed(() => [
    { label: 'Todas las sucursales', value: null as number | null },
    ...this.cajas().map((c) => ({ label: c.sucursal_nombre, value: c.sucursal_id as number | null })),
  ]);
  protected readonly variasSucursales = computed(() => this.cajas().length > 1);

  protected readonly errorRango = computed(() => {
    const desde = this.desde();
    const hasta = this.hasta();
    if (desde === null || hasta === null) return 'Elige la fecha inicial y la final.';
    if (fechaLocalIso(desde) > fechaLocalIso(hasta)) return 'La fecha inicial no puede ser posterior a la final.';
    return null;
  });

  /** Una página llena puede tener otra detrás: el servidor no manda el total. */
  protected readonly hayMas = computed(() => this.turnos().length >= this.tamanioPagina);

  // ---- Detalle ----
  protected readonly detalleDe = signal<Turno | null>(null);
  protected readonly detalle = signal<TurnoDetalle | null>(null);
  protected readonly cargandoDetalle = signal(false);
  protected readonly errorDetalle = signal<string | null>(null);
  protected readonly conteo = signal<{ turno: Turno; modo: ModoConteo } | null>(null);

  protected readonly etiquetaEstado = etiquetaEstadoTurno;
  protected readonly claseEstado = claseEstadoTurno;
  protected readonly claseDiferencia = claseDiferencia;
  protected readonly textoDiferencia = textoDiferencia;
  protected readonly fecha = instanteServidor;
  protected readonly num = (valor: string | null | undefined): number => Number(valor ?? 0);

  private peticionCajas?: Subscription;
  private peticion?: Subscription;
  private peticionDetalle?: Subscription;

  constructor() {
    this.destroyRef.onDestroy(() => {
      this.peticionCajas?.unsubscribe();
      this.peticion?.unsubscribe();
      this.peticionDetalle?.unsubscribe();
    });
  }

  ngOnInit(): void {
    this.cargarCajas();
    this.cargar();
  }

  // ---- Cajas de hoy ----

  protected cargarCajas(): void {
    this.peticionCajas?.unsubscribe();
    this.cargandoCajas.set(true);
    this.errorCajas.set(false);
    this.peticionCajas = this.servicio.estado().subscribe({
      next: (cajas) => {
        this.cajas.set(cajas);
        this.cargandoCajas.set(false);
      },
      error: () => {
        this.cargandoCajas.set(false);
        this.errorCajas.set(true);
      },
    });
  }

  protected actualizar(): void {
    this.cargarCajas();
    this.cargar();
  }

  // ---- Historial ----

  protected cargar(): void {
    this.peticion?.unsubscribe();
    if (this.errorRango() !== null) {
      this.cargando.set(false);
      return;
    }
    this.cargando.set(true);
    this.error.set(false);
    this.peticion = this.servicio
      .listar({
        sucursal_id: this.filtroSucursal(),
        estado: this.filtroEstado(),
        desde: fechaLocalIso(this.desde()!),
        hasta: fechaLocalIso(this.hasta()!),
        pagina: this.pagina(),
        tamanio: this.tamanioPagina,
      })
      .subscribe({
        next: (turnos) => {
          this.turnos.set(turnos);
          this.cargando.set(false);
        },
        error: () => {
          this.turnos.set([]);
          this.cargando.set(false);
          this.error.set(true);
        },
      });
  }

  private volverALaPrimera(): void {
    this.pagina.set(1);
    this.cargar();
  }

  protected cambiarDesde(fecha: Date | null): void {
    this.desde.set(fecha);
    this.volverALaPrimera();
  }

  protected cambiarHasta(fecha: Date | null): void {
    this.hasta.set(fecha);
    this.volverALaPrimera();
  }

  protected cambiarSucursal(id: number | null): void {
    this.filtroSucursal.set(id);
    this.volverALaPrimera();
  }

  protected cambiarEstado(estado: EstadoTurno | null): void {
    this.filtroEstado.set(estado);
    this.volverALaPrimera();
  }

  protected irAPaginaAnterior(): void {
    if (this.pagina() > 1) {
      this.pagina.update((p) => p - 1);
      this.cargar();
    }
  }

  protected irAPaginaSiguiente(): void {
    if (this.hayMas()) {
      this.pagina.update((p) => p + 1);
      this.cargar();
    }
  }

  // ---- Detalle de un turno ----

  protected verDetalle(turno: Turno): void {
    this.detalleDe.set(turno);
    this.detalle.set(null);
    this.errorDetalle.set(null);
    this.leerDetalle(turno.id);
  }

  private leerDetalle(turnoId: number): void {
    this.peticionDetalle?.unsubscribe();
    this.cargandoDetalle.set(true);
    this.peticionDetalle = this.servicio.detalle(turnoId).subscribe({
      next: (detalle) => {
        this.cargandoDetalle.set(false);
        this.detalle.set(detalle);
        this.detalleDe.set(detalle);
      },
      error: (error: unknown) => {
        this.cargandoDetalle.set(false);
        this.errorDetalle.set(mensajeErrorCaja(error, 'No pudimos cargar el detalle del turno.'));
      },
    });
  }

  protected reintentarDetalle(): void {
    const turno = this.detalleDe();
    if (turno === null) return;
    this.errorDetalle.set(null);
    this.leerDetalle(turno.id);
  }

  protected cerrarDetalle(): void {
    this.peticionDetalle?.unsubscribe();
    this.detalleDe.set(null);
    this.detalle.set(null);
    this.conteo.set(null);
  }

  /** Un supervisor puede completar el conteo de un cierre automático una vez y mientras no pase el plazo. */
  protected puedeCompletarConteo(turno: Turno): boolean {
    if (turno.estado !== 'cerrada_auto' || turno.conteo_en || !turno.conteo_hasta) return false;
    return instanteServidor(turno.conteo_hasta).getTime() > Date.now();
  }

  protected conteoVencido(turno: Turno): boolean {
    return turno.estado === 'cerrada_auto' && !turno.conteo_en && !this.puedeCompletarConteo(turno);
  }

  protected abrirConteo(turno: Turno, modo: ModoConteo): void {
    this.conteo.set({ turno, modo });
  }

  protected finalizarConteo(): void {
    this.conteo.set(null);
  }

  /** El servidor aceptó el conteo: se refrescan las tarjetas, la tabla y el detalle abierto. */
  protected alContar(turno: Turno): void {
    this.cargarCajas();
    this.cargar();
    if (this.detalleDe() !== null) this.leerDetalle(turno.id);
  }

  /** Cuánto cambió el esperado desde el cierre, con una frase que explica por qué (0 o nulo = no se dice nada). */
  protected explicarAjuste(ajuste: string | null): { texto: string } | null {
    const numero = Number(ajuste ?? 0);
    if (!Number.isFinite(numero) || numero === 0) return null;
    const monto = Math.abs(numero).toFixed(2);
    return numero > 0
      ? { texto: `Llegaron ventas sincronizadas tarde: el esperado subió Bs ${monto} desde el cierre.` }
      : { texto: `Se devolvió algo después del cierre: el esperado bajó Bs ${monto}.` };
  }

  private diasAtras(dias: number): Date {
    const fecha = new Date();
    fecha.setDate(fecha.getDate() - dias);
    return fecha;
  }
}
