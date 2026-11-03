import { DatePipe } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, Input, Output, EventEmitter, ViewChild, computed, signal, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ConfirmationService } from 'primeng/api';
import { ConfirmDialogModule } from 'primeng/confirmdialog';
import { Table, TableModule } from 'primeng/table';
import { environment } from '../../../environments/environment';
import { IconoComponent } from '../icono/icono.component';

export interface ColumnaTabla<T> {
  campo: Extract<keyof T, string>;
  encabezado: string;
  tipo?: 'texto' | 'booleano' | 'fecha';
  /** Columna booleana: el chip se lee Activa/Inactiva (o Sí/No) en femenino. Por defecto, el de la tabla. */
  femenino?: boolean;
}

/**
 * Tabla CRUD genérica: recibe un endpoint y columnas, y resuelve la
 * paginación contra el backend (GET {endpoint}?pagina=&tamanio=), el
 * ordenamiento y el filtro de texto sobre la página cargada, y el borrado
 * (DELETE {endpoint}/{id}) con confirmación.
 *
 * Crear y editar se delegan al componente padre (vía los eventos `crear` y
 * `editar`) porque el formulario cambia por entidad; todo lo demás es
 * exactamente igual para cualquier pantalla de administración. Agregar el
 * CRUD de, por ejemplo, colores es: nueva ruta + este componente con sus
 * columnas + un diálogo de formulario propio (`app-dialogo-crud`). Nada más se
 * repite.
 *
 * Patrón visual (canvas `Crud`): si se pasa `titulo`, la tabla dibuja el
 * encabezado de la pantalla (`.fs-pagina-encabezado`, con el rótulo `eyebrow`
 * y el botón "Nuevo ..."). Sin `titulo` (pantallas que dibujan su propio
 * encabezado) el botón queda en la barra de búsqueda.
 */
@Component({
  selector: 'app-tabla-generica',
  standalone: true,
  imports: [DatePipe, FormsModule, TableModule, ConfirmDialogModule, IconoComponent],
  providers: [ConfirmationService],
  templateUrl: './tabla-generica.component.html',
  styleUrl: './tabla-generica.component.scss',
})
export class TablaGenericaComponent<T extends { id: number }> implements OnInit {
  @Input({ required: true }) endpoint!: string;
  @Input({ required: true }) columnas: ColumnaTabla<T>[] = [];
  @Input() tamanioPagina = 20;
  @Input() soloLectura = false;

  /** Título (h1) de la pantalla. Si se omite, la pantalla pone su propio encabezado. */
  @Input() titulo?: string;
  /** Rótulo en mayúsculas sobre el título (el grupo del menú: "Catálogo"). */
  @Input() eyebrow?: string;
  /** Texto del botón de crear: "Nueva categoría". */
  @Input() etiquetaNuevo = 'Nuevo';
  @Input() placeholderBusqueda = 'Buscar en esta página...';
  /** El chip Activo/Inactivo de las columnas booleanas va en femenino ("Activa") salvo que la columna diga otra cosa. */
  @Input() femenino = false;

  /** Acción propia de una pantalla, además de editar y borrar (por ejemplo,
   * "permisos" en roles). Es opcional: sin icono no se dibuja el botón, así
   * que las pantallas que ya usan esta tabla no cambian en nada. Acepta el
   * nombre de un `fs-icono` ("llave") o, por compatibilidad, una clase de
   * PrimeIcons ("pi pi-key"). */
  @Input() accionExtraIcono?: string;
  @Input() accionExtraEtiqueta = 'Acción';
  /** En `soloLectura`, dejar visible solo la acción extra (p. ej. "Ver permisos"): sin editar ni desactivar. */
  @Input() accionExtraEnLectura = false;

  /** La columna de acciones se dibuja si se puede modificar, o si en solo lectura queda la acción extra. */
  protected get mostrarAcciones(): boolean {
    return !this.soloLectura || (this.accionExtraEnLectura && !!this.accionExtraIcono);
  }

  @Output() crear = new EventEmitter<void>();
  @Output() editar = new EventEmitter<T>();
  @Output() accionExtra = new EventEmitter<T>();

  @ViewChild('tabla') tabla!: Table;

  protected readonly filas = signal<T[]>([]);
  protected readonly cargando = signal(false);
  protected readonly pagina = signal(1);
  protected readonly hayPaginaSiguiente = signal(false);
  protected readonly error = signal(false);
  private readonly filtroActivo = signal(false);
  private readonly conteoFiltrado = signal<number | null>(null);

  /** El contador solo conoce la página cargada (la API no informa el total) y respeta la búsqueda. */
  protected readonly conteoTexto = computed(() => {
    const total = this.filas().length;
    if (this.filtroActivo()) return `${this.conteoFiltrado() ?? total} de ${total} en esta página`;
    return `${total} ${total === 1 ? 'registro' : 'registros'} en esta página`;
  });

  constructor(
    private readonly http: HttpClient,
    private readonly confirmationService: ConfirmationService,
  ) {}

  ngOnInit(): void {
    this.cargar();
  }

  recargar(): void {
    this.cargar();
  }

  irAPaginaAnterior(): void {
    if (this.pagina() > 1) {
      this.pagina.set(this.pagina() - 1);
      this.cargar();
    }
  }

  irAPaginaSiguiente(): void {
    if (this.hayPaginaSiguiente()) {
      this.pagina.set(this.pagina() + 1);
      this.cargar();
    }
  }

  protected esIconoPrime(icono: string): boolean {
    return icono.startsWith('pi ');
  }

  /** "activo" se lee Activo/Inactivo (Activa/Inactiva en femenino); cualquier otro booleano, Sí/No. */
  protected etiquetaBooleano(columna: ColumnaTabla<T>, valor: unknown): string {
    if (columna.campo !== 'activo') return valor ? 'Sí' : 'No';
    const femenino = columna.femenino ?? this.femenino;
    if (valor) return femenino ? 'Activa' : 'Activo';
    return femenino ? 'Inactiva' : 'Inactivo';
  }

  filtrarGlobal(valor: string): void {
    this.filtroActivo.set(valor.trim() !== '');
    if (!this.filtroActivo()) this.conteoFiltrado.set(null);
    this.tabla.filterGlobal(valor, 'contains');
  }

  protected alFiltrar(evento: { filteredValue?: unknown[] | null }): void {
    this.conteoFiltrado.set(evento.filteredValue ? evento.filteredValue.length : null);
  }

  reintentar(): void {
    this.cargar();
  }

  confirmarEliminar(fila: T): void {
    this.confirmationService.confirm({
      message: '¿Desactivar este registro?',
      header: 'Confirmar',
      icon: 'pi pi-exclamation-triangle',
      acceptLabel: 'Sí, desactivar',
      rejectLabel: 'Cancelar',
      accept: () => this.eliminar(fila),
    });
  }

  private cargar(): void {
    this.cargando.set(true);
    this.error.set(false);
    const url = `${environment.apiUrl}${this.endpoint}?pagina=${this.pagina()}&tamanio=${this.tamanioPagina}`;
    this.http.get<T[]>(url).subscribe({
      next: (datos) => {
        this.filas.set(datos);
        this.hayPaginaSiguiente.set(datos.length === this.tamanioPagina);
        this.cargando.set(false);
        // La tabla vuelve a aplicar la búsqueda activa al recibir las filas nuevas.
        if (this.filtroActivo()) {
          this.conteoFiltrado.set(null);
          setTimeout(() => this.conteoFiltrado.set(this.tabla?.filteredValue?.length ?? null));
        }
      },
      error: () => {
        this.cargando.set(false);
        this.error.set(true);
      },
    });
  }

  private eliminar(fila: T): void {
    this.http.delete<void>(`${environment.apiUrl}${this.endpoint}/${fila.id}`).subscribe(() => {
      this.cargar();
    });
  }
}
