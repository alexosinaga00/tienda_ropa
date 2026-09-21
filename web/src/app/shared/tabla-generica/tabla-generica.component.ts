import { DatePipe } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, Input, Output, EventEmitter, ViewChild, signal, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { ConfirmationService } from 'primeng/api';
import { ConfirmDialogModule } from 'primeng/confirmdialog';
import { IconFieldModule } from 'primeng/iconfield';
import { InputIconModule } from 'primeng/inputicon';
import { InputTextModule } from 'primeng/inputtext';
import { Table, TableModule } from 'primeng/table';
import { environment } from '../../../environments/environment';

export interface ColumnaTabla<T> {
  campo: Extract<keyof T, string>;
  encabezado: string;
  tipo?: 'texto' | 'booleano' | 'fecha';
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
 * columnas + un diálogo de formulario propio. Nada más se repite.
 */
@Component({
  selector: 'app-tabla-generica',
  standalone: true,
  imports: [
    DatePipe,
    FormsModule,
    TableModule,
    ButtonModule,
    InputTextModule,
    IconFieldModule,
    InputIconModule,
    ConfirmDialogModule,
  ],
  providers: [ConfirmationService],
  templateUrl: './tabla-generica.component.html',
  styleUrl: './tabla-generica.component.scss',
})
export class TablaGenericaComponent<T extends { id: number }> implements OnInit {
  @Input({ required: true }) endpoint!: string;
  @Input({ required: true }) columnas: ColumnaTabla<T>[] = [];
  @Input() tamanioPagina = 20;
  @Input() soloLectura = false;

  /** Acción propia de una pantalla, además de editar y borrar (por ejemplo,
   * "permisos" en roles). Es opcional: sin icono no se dibuja el botón, así
   * que las pantallas que ya usan esta tabla no cambian en nada. */
  @Input() accionExtraIcono?: string;
  @Input() accionExtraEtiqueta = 'Acción';

  @Output() crear = new EventEmitter<void>();
  @Output() editar = new EventEmitter<T>();
  @Output() accionExtra = new EventEmitter<T>();

  @ViewChild('tabla') tabla!: Table;

  protected readonly filas = signal<T[]>([]);
  protected readonly cargando = signal(false);
  protected readonly pagina = signal(1);
  protected readonly hayPaginaSiguiente = signal(false);

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

  filtrarGlobal(valor: string): void {
    this.tabla.filterGlobal(valor, 'contains');
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
    const url = `${environment.apiUrl}${this.endpoint}?pagina=${this.pagina()}&tamanio=${this.tamanioPagina}`;
    this.http.get<T[]>(url).subscribe({
      next: (datos) => {
        this.filas.set(datos);
        this.hayPaginaSiguiente.set(datos.length === this.tamanioPagina);
        this.cargando.set(false);
      },
      error: () => this.cargando.set(false),
    });
  }

  private eliminar(fila: T): void {
    this.http.delete<void>(`${environment.apiUrl}${this.endpoint}/${fila.id}`).subscribe(() => {
      this.cargar();
    });
  }
}
