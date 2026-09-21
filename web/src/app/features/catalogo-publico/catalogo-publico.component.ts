import { DecimalPipe } from '@angular/common';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MessageService } from 'primeng/api';
import { environment } from '../../../environments/environment';
import {
  CatalogoItem,
  Categoria,
  Color,
  Genero,
  Material,
  Talla,
  Temporada,
} from '../../core/models/catalogo.models';

const DEMORA_BUSQUEDA_MS = 350;

// Mismo tamaño de página que usa la app móvil (catalogo_controller.dart), y
// dentro del máximo que acepta `paginacion_catalogo` del backend (50).
const TAMANIO_PAGINA = 20;

// Los géneros que declara el backend (catalogo/schemas.py: Genero).
const GENEROS: { valor: Genero; etiqueta: string }[] = [
  { valor: 'hombre', etiqueta: 'Hombre' },
  { valor: 'mujer', etiqueta: 'Mujer' },
  { valor: 'unisex', etiqueta: 'Unisex' },
  { valor: 'nino', etiqueta: 'Niño' },
];

@Component({
  selector: 'app-catalogo-publico',
  standalone: true,
  imports: [DecimalPipe, FormsModule, RouterLink],
  templateUrl: './catalogo-publico.component.html',
  styleUrl: './catalogo-publico.component.scss',
})
export class CatalogoPublicoComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly messageService = inject(MessageService);
  private temporizadorBusqueda?: ReturnType<typeof setTimeout>;

  protected readonly generos = GENEROS;

  // Tablas de referencia para los desplegables de filtro.
  protected readonly categorias = signal<Categoria[]>([]);
  protected readonly tallas = signal<Talla[]>([]);
  protected readonly colores = signal<Color[]>([]);
  protected readonly materiales = signal<Material[]>([]);
  protected readonly temporadas = signal<Temporada[]>([]);

  protected readonly productos = signal<CatalogoItem[]>([]);
  protected readonly cargando = signal(true);
  protected readonly cargandoMas = signal(false);
  protected readonly error = signal(false);

  // `hayMas` no viene del backend: /catalogo y /catalogo/buscar devuelven una
  // lista pelada, sin total. Se deduce igual que en la app móvil -- si la
  // página vino completa, asumimos que hay otra.
  protected readonly hayMas = signal(false);
  private pagina = 1;

  protected readonly panelFiltros = signal(false);

  // Filtros. `texto` y los de precio van con [(ngModel)] directo; el resto son
  // signals porque además se leen desde la plantilla para pintar el estado.
  protected texto = '';
  protected readonly categoriaSeleccionada = signal<number | null>(null);
  protected readonly tallaId = signal<number | null>(null);
  protected readonly colorId = signal<number | null>(null);
  protected readonly materialId = signal<number | null>(null);
  protected readonly temporadaId = signal<number | null>(null);
  protected readonly genero = signal<Genero | null>(null);
  protected precioMin: number | null = null;
  protected precioMax: number | null = null;

  ngOnInit(): void {
    this.cargarReferencias();
    this.cargarProductos();
  }

  /** Cuántos filtros hay puestos, sin contar el texto ni la categoría (esos
   * ya se ven solos en el buscador y en las pastillas). Es el número del
   * globito del botón "Filtros". */
  protected contarFiltros(): number {
    const puestos = [
      this.tallaId(),
      this.colorId(),
      this.materialId(),
      this.temporadaId(),
      this.genero(),
      this.precioMin,
      this.precioMax,
    ];
    return puestos.filter((v) => v !== null && v !== undefined && v !== ('' as unknown)).length;
  }

  private cargarReferencias(): void {
    // tamanio=100 como en el resto del back office: los desplegables tienen
    // que traer todas las opciones, no la primera página de 20.
    const sufijo = '?pagina=1&tamanio=100';
    // Las referencias son un extra sobre el catálogo: si alguna falla, el
    // catálogo sigue siendo navegable y ese filtro simplemente no aparece,
    // así que no se muestra error por esto.
    this.http
      .get<Categoria[]>(`${environment.apiUrl}/categorias${sufijo}`)
      .subscribe({ next: (v) => this.categorias.set(v), error: () => this.categorias.set([]) });
    this.http
      .get<Talla[]>(`${environment.apiUrl}/tallas${sufijo}`)
      .subscribe({ next: (v) => this.tallas.set(v), error: () => this.tallas.set([]) });
    this.http
      .get<Color[]>(`${environment.apiUrl}/colores${sufijo}`)
      .subscribe({ next: (v) => this.colores.set(v), error: () => this.colores.set([]) });
    this.http
      .get<Material[]>(`${environment.apiUrl}/materiales${sufijo}`)
      .subscribe({ next: (v) => this.materiales.set(v), error: () => this.materiales.set([]) });
    this.http
      .get<Temporada[]>(`${environment.apiUrl}/temporadas${sufijo}`)
      .subscribe({ next: (v) => this.temporadas.set(v), error: () => this.temporadas.set([]) });
  }

  /** Primera página: reemplaza la grilla. */
  protected cargarProductos(): void {
    this.pagina = 1;
    this.cargando.set(true);
    this.error.set(false);

    this.pedirPagina(1).subscribe({
      next: (productos) => {
        this.productos.set(productos);
        this.hayMas.set(productos.length === TAMANIO_PAGINA);
        this.cargando.set(false);
      },
      error: (err: HttpErrorResponse) => {
        this.cargando.set(false);
        this.error.set(true);
        this.hayMas.set(false);
        this.avisarError(err);
      },
    });
  }

  /** Página siguiente: se suma a lo que ya está en pantalla. */
  protected cargarMas(): void {
    if (this.cargando() || this.cargandoMas() || !this.hayMas()) return;

    this.cargandoMas.set(true);
    const siguiente = this.pagina + 1;

    this.pedirPagina(siguiente).subscribe({
      next: (nuevos) => {
        this.pagina = siguiente;
        this.productos.update((actuales) => [...actuales, ...nuevos]);
        this.hayMas.set(nuevos.length === TAMANIO_PAGINA);
        this.cargandoMas.set(false);
      },
      error: (err: HttpErrorResponse) => {
        // Que falle "una página más" no rompe la grilla que ya se veía: se
        // deja de cargar y el botón queda disponible para reintentar.
        this.cargandoMas.set(false);
        this.avisarError(err);
      },
    });
  }

  private pedirPagina(pagina: number) {
    const filtros = this.armarParametros();
    // Sin ningún filtro se usa /catalogo, que es el listado llano y tiene más
    // margen de rate limit (60/min) que /catalogo/buscar (30/min).
    const base = filtros ? `${environment.apiUrl}/catalogo/buscar` : `${environment.apiUrl}/catalogo`;
    const paginado = `pagina=${pagina}&tamanio=${TAMANIO_PAGINA}`;
    return this.http.get<CatalogoItem[]>(`${base}?${paginado}${filtros ? `&${filtros}` : ''}`);
  }

  /** Los 7 filtros que enumera el RF10, más el texto. Los nombres de los
   * parámetros son los que declara `buscar_catalogo` en catalogo/router.py. */
  private armarParametros(): string {
    const params = new URLSearchParams();
    const texto = this.texto.trim();
    if (texto) params.set('q', texto);
    if (this.categoriaSeleccionada() !== null) params.set('categoria_id', String(this.categoriaSeleccionada()));
    if (this.tallaId() !== null) params.set('talla_id', String(this.tallaId()));
    if (this.colorId() !== null) params.set('color_id', String(this.colorId()));
    if (this.materialId() !== null) params.set('material_id', String(this.materialId()));
    if (this.temporadaId() !== null) params.set('temporada_id', String(this.temporadaId()));
    if (this.genero() !== null) params.set('genero', String(this.genero()));
    if (this.precioMin !== null && this.precioMin !== undefined) params.set('precio_min', String(this.precioMin));
    if (this.precioMax !== null && this.precioMax !== undefined) params.set('precio_max', String(this.precioMax));
    return params.toString();
  }

  private avisarError(err: HttpErrorResponse): void {
    // El 429 ya lo explica el interceptor de errores: no se duplica el aviso.
    if (err.status === 429) return;
    this.messageService.add({
      severity: 'error',
      summary: 'No se pudo cargar el catálogo',
      detail: 'Probá de nuevo en un momento.',
    });
  }

  protected onBuscar(): void {
    clearTimeout(this.temporizadorBusqueda);
    this.temporizadorBusqueda = setTimeout(() => this.cargarProductos(), DEMORA_BUSQUEDA_MS);
  }

  protected seleccionarCategoria(id: number | null): void {
    this.categoriaSeleccionada.set(id);
    this.cargarProductos();
  }

  /** Cualquier cambio de filtro vuelve a la primera página: seguir en la 3 con
   * otros filtros mostraría un tramo arbitrario de los resultados nuevos. */
  protected aplicarFiltro(destino: 'talla' | 'color' | 'material' | 'temporada' | 'genero', valor: string): void {
    const id = valor === '' ? null : Number(valor);
    switch (destino) {
      case 'talla':
        this.tallaId.set(id);
        break;
      case 'color':
        this.colorId.set(id);
        break;
      case 'material':
        this.materialId.set(id);
        break;
      case 'temporada':
        this.temporadaId.set(id);
        break;
      case 'genero':
        this.genero.set(valor === '' ? null : (valor as Genero));
        break;
    }
    this.cargarProductos();
  }

  protected onPrecioCambiado(): void {
    clearTimeout(this.temporizadorBusqueda);
    this.temporizadorBusqueda = setTimeout(() => this.cargarProductos(), DEMORA_BUSQUEDA_MS);
  }

  protected limpiarFiltros(): void {
    this.tallaId.set(null);
    this.colorId.set(null);
    this.materialId.set(null);
    this.temporadaId.set(null);
    this.genero.set(null);
    this.precioMin = null;
    this.precioMax = null;
    this.cargarProductos();
  }

  protected alternarPanelFiltros(): void {
    this.panelFiltros.update((abierto) => !abierto);
  }
}
