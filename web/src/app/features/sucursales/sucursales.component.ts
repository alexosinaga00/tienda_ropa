import { HttpClient } from '@angular/common/http';
import { Component, OnInit, ViewChild, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { CheckboxModule } from 'primeng/checkbox';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { forkJoin } from 'rxjs';
import { environment } from '../../../environments/environment';
import { Ciudad } from '../../core/models/organizacion.models';
import { HorarioSucursal, Sucursal } from '../../core/models/organizacion.models';
import { ColumnaTabla, TablaGenericaComponent } from '../../shared/tabla-generica/tabla-generica.component';

const COLUMNAS: ColumnaTabla<Sucursal>[] = [
  { campo: 'codigo', encabezado: 'Código' },
  { campo: 'nombre', encabezado: 'Nombre' },
  { campo: 'direccion', encabezado: 'Dirección' },
  { campo: 'activo', encabezado: 'Activo', tipo: 'booleano' },
];

// dia_semana es 1=lunes...7=domingo (isoweekday), como lo valida
// HorarioCrear en organizacion/schemas.py.
const DIAS = [
  { numero: 1, nombre: 'Lunes' },
  { numero: 2, nombre: 'Martes' },
  { numero: 3, nombre: 'Miércoles' },
  { numero: 4, nombre: 'Jueves' },
  { numero: 5, nombre: 'Viernes' },
  { numero: 6, nombre: 'Sábado' },
  { numero: 7, nombre: 'Domingo' },
];

const APERTURA_POR_DEFECTO = '09:00';
const CIERRE_POR_DEFECTO = '19:00';

/** Un día en el formulario de horarios. `id` null = ese día todavía no tiene
 * fila en la base. La tabla tiene UNIQUE(sucursal_id, dia_semana), así que hay
 * como mucho un horario por día: por eso el formulario es una fila por día y
 * no una lista donde se puedan agregar varios. */
interface FilaHorario {
  dia_semana: number;
  nombre: string;
  id: number | null;
  abierto: boolean;
  hora_apertura: string;
  hora_cierre: string;
}

@Component({
  selector: 'app-sucursales',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    ButtonModule,
    DialogModule,
    InputTextModule,
    CheckboxModule,
    SelectModule,
    TablaGenericaComponent,
  ],
  templateUrl: './sucursales.component.html',
  styleUrl: './sucursales.component.scss',
})
export class SucursalesComponent implements OnInit {
  protected readonly columnas = COLUMNAS;
  protected readonly dialogoVisible = signal(false);
  protected readonly editando = signal<Sucursal | null>(null);
  protected readonly ciudades = signal<Ciudad[]>([]);

  // ---- Horarios de atención (RF06) ----
  protected readonly dialogoHorarios = signal(false);
  protected readonly sucursalHorarios = signal<Sucursal | null>(null);
  protected readonly filas = signal<FilaHorario[]>([]);
  protected readonly cargandoHorarios = signal(false);
  protected readonly guardandoHorarios = signal(false);
  private originales: HorarioSucursal[] = [];

  @ViewChild(TablaGenericaComponent) private tabla!: TablaGenericaComponent<Sucursal>;

  private readonly fb = inject(FormBuilder);
  private readonly http = inject(HttpClient);
  private readonly messageService = inject(MessageService);

  protected readonly formulario = this.fb.nonNullable.group({
    ciudad_id: [null as number | null, Validators.required],
    codigo: ['', Validators.required],
    nombre: ['', Validators.required],
    direccion: ['', Validators.required],
    telefono: [''],
    es_deposito: [false],
    activo: [true],
  });

  ngOnInit(): void {
    // Todas las ciudades activas caben cómodas en una sola página para un
    // combo; si el catálogo crece, esto se cambia por un select con búsqueda
    // server-side.
    this.http
      .get<Ciudad[]>(`${environment.apiUrl}/ciudades?pagina=1&tamanio=100`)
      .subscribe((ciudades) => this.ciudades.set(ciudades));
  }

  abrirCrear(): void {
    this.editando.set(null);
    this.formulario.reset({
      ciudad_id: null,
      codigo: '',
      nombre: '',
      direccion: '',
      telefono: '',
      es_deposito: false,
      activo: true,
    });
    this.dialogoVisible.set(true);
  }

  abrirEditar(sucursal: Sucursal): void {
    this.editando.set(sucursal);
    this.formulario.reset({
      ciudad_id: sucursal.ciudad_id,
      codigo: sucursal.codigo,
      nombre: sucursal.nombre,
      direccion: sucursal.direccion,
      telefono: sucursal.telefono ?? '',
      es_deposito: sucursal.es_deposito,
      activo: sucursal.activo,
    });
    this.dialogoVisible.set(true);
  }

  guardar(): void {
    if (this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    const datos = this.formulario.getRawValue();
    const sucursal = this.editando();
    const peticion = sucursal
      ? this.http.put(`${environment.apiUrl}/sucursales/${sucursal.id}`, datos)
      : this.http.post(`${environment.apiUrl}/sucursales`, datos);

    peticion.subscribe(() => {
      this.dialogoVisible.set(false);
      this.tabla.recargar();
    });
  }

  // ---- Horarios ----

  abrirHorarios(sucursal: Sucursal): void {
    this.sucursalHorarios.set(sucursal);
    this.filas.set([]);
    this.cargandoHorarios.set(true);
    this.dialogoHorarios.set(true);

    this.http.get<HorarioSucursal[]>(`${this.urlHorarios(sucursal.id)}`).subscribe({
      next: (horarios) => {
        this.originales = horarios;
        this.filas.set(this.armarFilas(horarios));
        this.cargandoHorarios.set(false);
      },
      error: () => {
        this.cargandoHorarios.set(false);
        this.dialogoHorarios.set(false);
        this.messageService.add({
          severity: 'error',
          summary: 'No se pudieron cargar los horarios',
          detail: 'Probá de nuevo en un momento.',
        });
      },
    });
  }

  /** Siempre los 7 días: los que no tienen fila aparecen como cerrados, para
   * que se vea de un vistazo qué falta cargar en vez de una lista corta que
   * no dice nada de los días ausentes. */
  private armarFilas(horarios: HorarioSucursal[]): FilaHorario[] {
    const porDia = new Map(horarios.map((h) => [h.dia_semana, h]));
    return DIAS.map((dia) => {
      const existente = porDia.get(dia.numero);
      return {
        dia_semana: dia.numero,
        nombre: dia.nombre,
        id: existente?.id ?? null,
        abierto: existente !== undefined,
        hora_apertura: this.aHoraCorta(existente?.hora_apertura) ?? APERTURA_POR_DEFECTO,
        hora_cierre: this.aHoraCorta(existente?.hora_cierre) ?? CIERRE_POR_DEFECTO,
      };
    });
  }

  /** El backend serializa dt.time como "HH:MM:SS"; <input type="time"> quiere
   * "HH:MM". */
  private aHoraCorta(hora: string | undefined): string | null {
    return hora ? hora.slice(0, 5) : null;
  }

  protected alternarDia(dia: number): void {
    this.filas.update((filas) =>
      filas.map((f) => (f.dia_semana === dia ? { ...f, abierto: !f.abierto } : f)),
    );
  }

  protected cambiarHora(dia: number, campo: 'hora_apertura' | 'hora_cierre', valor: string): void {
    this.filas.update((filas) => filas.map((f) => (f.dia_semana === dia ? { ...f, [campo]: valor } : f)));
  }

  /** Los días abiertos con un rango inválido. El backend también lo valida
   * (ck_horario_cierre_despues_apertura y el model_validator del schema),
   * pero avisar acá evita mandar una tanda que va a fallar a la mitad. */
  protected diasInvalidos(): string[] {
    return this.filas()
      .filter((f) => f.abierto && f.hora_cierre <= f.hora_apertura)
      .map((f) => f.nombre);
  }

  guardarHorarios(): void {
    const sucursal = this.sucursalHorarios();
    if (!sucursal || this.guardandoHorarios()) return;

    if (this.diasInvalidos().length) {
      this.messageService.add({
        severity: 'warn',
        summary: 'Revisá los horarios',
        detail: `La hora de cierre tiene que ser posterior a la de apertura: ${this.diasInvalidos().join(', ')}.`,
      });
      return;
    }

    const base = this.urlHorarios(sucursal.id);
    const porDia = new Map(this.originales.map((h) => [h.dia_semana, h]));
    const peticiones = [];

    for (const fila of this.filas()) {
      const existente = porDia.get(fila.dia_semana);
      const cuerpo = { hora_apertura: fila.hora_apertura, hora_cierre: fila.hora_cierre };

      if (fila.abierto && !existente) {
        peticiones.push(this.http.post(base, { dia_semana: fila.dia_semana, ...cuerpo }));
      } else if (fila.abierto && existente && this.cambio(existente, fila)) {
        peticiones.push(this.http.put(`${base}/${existente.id}`, cuerpo));
      } else if (!fila.abierto && existente) {
        // OJO: este DELETE es físico. `horario_sucursal` no tiene columna
        // `activo` (ver el modelo), así que marcar un día como cerrado borra
        // la fila y no se puede deshacer.
        peticiones.push(this.http.delete(`${base}/${existente.id}`));
      }
    }

    if (!peticiones.length) {
      this.dialogoHorarios.set(false);
      return;
    }

    this.guardandoHorarios.set(true);
    forkJoin(peticiones).subscribe({
      next: () => {
        this.guardandoHorarios.set(false);
        this.dialogoHorarios.set(false);
        this.messageService.add({
          severity: 'success',
          summary: 'Horarios actualizados',
          detail: `Se guardaron los horarios de ${sucursal.nombre}.`,
        });
      },
      error: () => {
        // forkJoin corta al primer error, así que puede haber quedado una
        // parte aplicada: se recargan los horarios reales en vez de dejar en
        // pantalla un estado que no coincide con la base.
        this.guardandoHorarios.set(false);
        this.abrirHorarios(sucursal);
      },
    });
  }

  private cambio(existente: HorarioSucursal, fila: FilaHorario): boolean {
    return (
      this.aHoraCorta(existente.hora_apertura) !== fila.hora_apertura ||
      this.aHoraCorta(existente.hora_cierre) !== fila.hora_cierre
    );
  }

  private urlHorarios(sucursalId: number): string {
    return `${environment.apiUrl}/sucursales/${sucursalId}/horarios`;
  }
}
