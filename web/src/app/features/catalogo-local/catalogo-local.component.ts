import { DatePipe } from '@angular/common';
import { Component, OnDestroy, OnInit, computed, effect, inject, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { ConectividadService } from '../../core/conectividad.service';
import { instanteServidor } from '../../core/date-utils';
import { CatalogoLocalService } from '../../core/offline/catalogo-local.service';
import type { FilaCategoria, FilaSucursal, ProductoLocal } from '../../core/offline/offline.models';
import { ErrorDescargaOffline, PaqueteOfflineService } from '../../core/offline/paquete-offline.service';
import { IconoComponent } from '../../shared/icono/icono.component';

/** Espera tras la última tecla antes de buscar (la búsqueda lee toda la base local). */
export const ESPERA_BUSQUEDA_MS = 250;
/** Cada cuánto se recalcula el "hace N h" de la franja. */
const REFRESCO_HACE_MS = 60_000;

// Se formatea con la convención en-US (siempre agrupa miles: "1,234.50") y se intercambian los separadores. Así no depende
// de los datos de idioma del navegador, que en español omiten el punto de miles por debajo de 10.000.
const FORMATO_BS = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const aSeparadoresBolivianos = (texto: string): string => texto.replace(/[,.]/g, (c) => (c === ',' ? '.' : ','));

const MENSAJES_ERROR: Record<ErrorDescargaOffline, string> = {
  sin_conexion: 'No pudimos conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.',
  plan_sin_offline: 'Tu plan no incluye la operación sin conexión. Pide a un administrador que revise el plan en Mi empresa.',
  suscripcion: 'La suscripción de tu empresa no está activa, por eso no podemos descargar los datos.',
  error: 'No pudimos descargar los datos. Inténtalo de nuevo en unos minutos.',
};

/** Una fila ya lista para mostrar: lo derivado de un producto con sus variantes. */
interface FilaCatalogo {
  producto: ProductoLocal;
  /** El menor precio de sus variantes (null si ninguna tiene un precio válido); `variosPrecios` dice si hay más de uno. */
  precioMin: number | null;
  variosPrecios: boolean;
  /** Tallas con stock conocido en alguna sucursal (sin repetir). */
  tallas: string[];
  /** Colores con stock conocido en alguna sucursal (sin repetir). */
  colores: { nombre: string; hex: string | null }[];
  /** Unidades conocidas por sucursal (suma de las variantes); falta la sucursal si no hay dato. */
  stockPorSucursal: Record<number, number>;
}

/**
 * "Catálogo local" (E14a, plan 4.6): lo que se descargó en este equipo para consultar y vender sin conexión. Solo lectura.
 * Siempre dice cuándo se descargó; si los datos están desactualizados lo advierte y deja a la vista [Actualizar datos].
 */
@Component({
  selector: 'app-catalogo-local',
  standalone: true,
  imports: [DatePipe, FormsModule, ButtonModule, SelectModule, TableModule, TagModule, IconoComponent],
  templateUrl: './catalogo-local.component.html',
  styleUrl: './catalogo-local.component.scss',
})
export class CatalogoLocalComponent implements OnInit, OnDestroy {
  private readonly catalogo = inject(CatalogoLocalService);
  protected readonly paquete = inject(PaqueteOfflineService);
  private readonly conectividad = inject(ConectividadService);

  protected readonly texto = signal('');
  protected readonly categoriaId = signal<number | null>(null);
  protected readonly categorias = signal<FilaCategoria[]>([]);
  protected readonly sucursales = signal<FilaSucursal[]>([]);
  private readonly productos = signal<ProductoLocal[]>([]);

  /** Verdadero hasta tener leído el estado de la descarga y la primera lista. */
  protected readonly cargando = signal(true);
  /** No se pudo LEER la base de este equipo (distinto de un error de descarga). */
  protected readonly errorLectura = signal(false);
  private readonly ahora = signal(Date.now());

  protected readonly hayConexion = computed(() => this.conectividad.estado() === 'en_linea');
  protected readonly sinDatos = computed(() => this.paquete.estadoDatos() === 'sin_datos');
  protected readonly desactualizados = computed(() => this.paquete.estadoDatos() === 'desactualizados');
  protected readonly mensajeError = computed(() => {
    const error = this.paquete.errorDescarga();
    return error === null ? null : MENSAJES_ERROR[error];
  });
  /** Con estos dos errores reintentar no sirve: se explica y no se ofrece el botón. */
  protected readonly descargaBloqueada = computed(() => {
    const error = this.paquete.errorDescarga();
    return error === 'plan_sin_offline' || error === 'suscripcion';
  });

  /** "hace 3 h": se recalcula cada minuto. */
  protected readonly haceCuanto = computed(() => {
    const ultima = this.paquete.ultimaDescarga();
    return ultima === null ? '' : textoHace(this.ahora() - instanteServidor(ultima).getTime());
  });

  protected readonly filas = computed<FilaCatalogo[]>(() => this.productos().map(aFila));
  protected readonly sucursalesConStock = computed(() => {
    const conDato = new Set(this.filas().flatMap((fila) => Object.keys(fila.stockPorSucursal).map(Number)));
    return this.sucursales().filter((sucursal) => conDato.has(sucursal.id));
  });
  protected readonly categoriasOrdenadas = computed(() =>
    [...this.categorias()].sort((a, b) => a.nombre.localeCompare(b.nombre, 'es')),
  );

  private temporizador: ReturnType<typeof setTimeout> | undefined;
  private refresco: ReturnType<typeof setInterval> | undefined;
  /** Para descartar la respuesta de una búsqueda que ya no es la última. */
  private secuencia = 0;
  private iniciado = false;
  private ultimaVista: string | null | undefined;

  constructor() {
    // Si la descarga termina mientras la pantalla está abierta (aquí o en segundo plano), la lista se vuelve a leer.
    effect(() => {
      const ultima = this.paquete.ultimaDescarga();
      untracked(() => {
        if (this.iniciado && ultima !== this.ultimaVista) void this.cargarLista();
      });
    });
  }

  async ngOnInit(): Promise<void> {
    this.refresco = setInterval(() => this.ahora.set(Date.now()), REFRESCO_HACE_MS);
    await this.paquete.cargarEstado();
    await this.cargarLista();
    this.iniciado = true;
  }

  ngOnDestroy(): void {
    clearTimeout(this.temporizador);
    clearInterval(this.refresco);
  }

  protected cambiarTexto(valor: string): void {
    this.texto.set(valor);
    clearTimeout(this.temporizador);
    this.temporizador = setTimeout(() => void this.cargarLista(), ESPERA_BUSQUEDA_MS);
  }

  protected cambiarCategoria(id: number | null): void {
    this.categoriaId.set(id);
    clearTimeout(this.temporizador);
    void this.cargarLista();
  }

  /** [Actualizar datos] y [Descargar datos]: baja el paquete y vuelve a leer la lista. */
  protected async actualizar(): Promise<void> {
    if (this.paquete.descargando()) return;
    const bien = await this.paquete.descargar();
    if (bien) await this.cargarLista();
  }

  protected reintentarLectura(): void {
    this.cargando.set(true);
    void this.cargarLista();
  }

  /** "Bs 1.234,50": miles con punto y centavos con coma, siempre con dos decimales. */
  protected bs(monto: number): string {
    return `Bs ${aSeparadoresBolivianos(FORMATO_BS.format(monto))}`;
  }

  private async cargarLista(): Promise<void> {
    const miSecuencia = ++this.secuencia;
    this.ultimaVista = this.paquete.ultimaDescarga();
    try {
      const [productos, categorias, sucursales] = await Promise.all([
        this.catalogo.buscarProductos(this.texto(), this.categoriaId()),
        this.catalogo.categorias(),
        this.catalogo.sucursales(),
      ]);
      if (miSecuencia !== this.secuencia) return;
      this.productos.set(productos);
      this.categorias.set(categorias);
      this.sucursales.set(sucursales);
      this.errorLectura.set(false);
    } catch {
      if (miSecuencia !== this.secuencia) return;
      this.productos.set([]);
      this.errorLectura.set(true);
    } finally {
      if (miSecuencia === this.secuencia) this.cargando.set(false);
    }
  }
}

function aFila(producto: ProductoLocal): FilaCatalogo {
  const precios = producto.variantes.map((v) => Number(v.precio)).filter((p) => Number.isFinite(p));
  const stockPorSucursal: Record<number, number> = {};
  const tallas: string[] = [];
  const colores: FilaCatalogo['colores'] = [];
  for (const variante of producto.variantes) {
    let unidades = 0;
    for (const [sucursalId, cantidad] of Object.entries(variante.stock)) {
      stockPorSucursal[Number(sucursalId)] = (stockPorSucursal[Number(sucursalId)] ?? 0) + cantidad;
      unidades += cantidad;
    }
    if (unidades <= 0) continue;
    if (variante.talla && !tallas.includes(variante.talla)) tallas.push(variante.talla);
    if (variante.color && !colores.some((c) => c.nombre === variante.color)) {
      colores.push({ nombre: variante.color, hex: variante.color_hex });
    }
  }
  const minimo = precios.length > 0 ? Math.min(...precios) : null;
  return {
    producto,
    precioMin: minimo,
    variosPrecios: precios.some((p) => p !== minimo),
    tallas,
    colores,
    stockPorSucursal,
  };
}

/** "hace unos segundos", "hace 12 min", "hace 3 h", "hace 2 días". */
export function textoHace(milisegundos: number): string {
  const minutos = Math.floor(milisegundos / 60_000);
  if (!Number.isFinite(minutos) || minutos < 1) return 'hace unos segundos';
  if (minutos < 60) return `hace ${minutos} min`;
  const horas = Math.floor(minutos / 60);
  if (horas < 48) return `hace ${horas} h`;
  return `hace ${Math.floor(horas / 24)} días`;
}
