import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin, map, of, switchMap } from 'rxjs';
import { ConectividadService } from '../../../core/conectividad.service';
import { instanteServidor } from '../../../core/date-utils';
import { CatalogoDetalle, ProductoImagenLookupItem } from '../../../core/models/catalogo.models';
import {
  EstadoSolicitudCambio,
  PlazoCambio,
  SolicitudCambio,
  SolicitudCambioCrear,
  Venta,
} from '../../../core/models/ventas.models';
import { IconoComponent } from '../../../shared/icono/icono.component';
import { CambiosService } from '../data/cambios.service';

/** Una prenda de la compra, con lo necesario para ofrecer su cambio. */
export interface LineaParaCambio {
  /** Id de la línea de la venta (`venta_detalle_id`). */
  id: number;
  varianteId: number;
  productoId: number | null;
  /** Lo que aún se puede cambiar de la línea: lo comprado menos lo ya devuelto (es el máximo por prenda). */
  cantidad: number;
  nombre: string;
  /** "M · Azul". */
  detalle: string;
}

/** Una talla o color por el que se puede cambiar una prenda (mismo producto y mismo precio, con stock). */
interface OpcionCambio {
  varianteId: number;
  etiqueta: string;
  disponible: number;
}

const ESTADOS: Record<EstadoSolicitudCambio, { texto: string; clase: string }> = {
  pendiente: { texto: 'Pendiente', clase: 'fs-chip--advertencia' },
  aprobada: { texto: 'Aprobada', clase: 'fs-chip--exito' },
  rechazada: { texto: 'Rechazada', clase: 'fs-chip--error' },
  cancelada: { texto: 'Cancelada', clase: '' },
  vencida: { texto: 'Vencida', clase: '' },
};

/** El motivo con que el servidor rechazó la solicitud, en palabras del cliente. */
function mensajeDeError(error: HttpErrorResponse): string {
  if (error.status === 0) return 'Sin conexión con el servidor. Inténtalo de nuevo.';
  if (error.status === 429) return 'Hiciste muchas solicitudes de cambio. Inténtalo de nuevo más tarde.';
  const detalle = error.error?.detail;
  if (typeof detalle === 'string' && detalle.trim()) return detalle;
  if (typeof detalle?.mensaje === 'string' && detalle.mensaje.trim()) return detalle.mensaje;
  return 'No se pudo enviar la solicitud. Inténtalo de nuevo.';
}

/**
 * Solicitud de cambio de talla o color desde el detalle de una compra (CU-17, Etapa 2). El cliente elige qué prendas
 * quiere cambiar y por cuál talla o color; la tienda la revisa cuando él lleva la prenda. No se reserva stock al
 * pedirla: las tallas que se ofrecen son las que hoy hay en la sucursal, y el servidor lo vuelve a comprobar al aprobar.
 */
@Component({
  selector: 'app-solicitar-cambio',
  standalone: true,
  imports: [DatePipe, FormsModule, IconoComponent],
  templateUrl: './solicitar-cambio.component.html',
  styleUrl: './solicitar-cambio.component.scss',
})
export class SolicitarCambioComponent implements OnInit {
  private readonly cambios = inject(CambiosService);
  private readonly conectividad = inject(ConectividadService);

  readonly venta = input.required<Venta>();
  readonly lineas = input.required<LineaParaCambio[]>();
  readonly plazo = input<PlazoCambio | null>(null);
  readonly sucursalNombre = input<string | null>(null);

  protected readonly solicitudes = signal<SolicitudCambio[]>([]);
  protected readonly abierto = signal(false);
  protected readonly cargandoOpciones = signal(false);
  protected readonly errorOpciones = signal(false);
  /** Por línea de la compra: las tallas o colores por los que se puede cambiar. */
  protected readonly opciones = signal<Record<number, OpcionCambio[]>>({});
  protected readonly cantidades = signal<Record<number, number>>({});
  protected readonly elegidas = signal<Record<number, number | null>>({});
  protected readonly motivo = signal('');
  protected readonly enviando = signal(false);
  protected readonly errorEnvio = signal<string | null>(null);
  /** La solicitud que se acaba de enviar: se confirma con adónde llevar la prenda. */
  protected readonly enviada = signal<SolicitudCambio | null>(null);
  /** La solicitud que se está por cancelar (pide confirmar). */
  protected readonly confirmandoCancelar = signal<number | null>(null);
  protected readonly cancelando = signal<number | null>(null);
  protected readonly errorCancelar = signal<string | null>(null);

  protected readonly sinConexion = computed(() => this.conectividad.estado() !== 'en_linea');
  protected readonly esDeCambio = computed(() => {
    const estado = this.venta().estado;
    return estado === 'pagada' || estado === 'entregada';
  });
  protected readonly vigente = computed(() => this.plazo()?.vigente === true);
  /** Líneas con una solicitud pendiente: no se pide otra mientras esa siga abierta. */
  protected readonly lineasPendientes = computed(
    () =>
      new Set(
        this.solicitudes()
          .filter((s) => s.estado === 'pendiente')
          .flatMap((s) => s.detalle.map((l) => l.venta_detalle_id)),
      ),
  );
  /** Las líneas que sí se pueden pedir ahora. */
  protected readonly lineasDisponibles = computed(() =>
    this.lineas().filter((l) => !this.lineasPendientes().has(l.id)),
  );
  protected readonly seleccion = computed(() =>
    this.lineasDisponibles().filter((l) => (this.cantidades()[l.id] ?? 0) > 0),
  );
  protected readonly hayPendiente = computed(() => this.solicitudes().some((s) => s.estado === 'pendiente'));

  ngOnInit(): void {
    // Una compra pendiente de pago o anulada no tiene nada que cambiar: no se consulta.
    if (this.esDeCambio()) this.cargarSolicitudes();
  }

  protected estado(solicitud: SolicitudCambio): { texto: string; clase: string } {
    return ESTADOS[solicitud.estado];
  }

  /** Las fechas del servidor son UTC ("Z"); se muestran en la hora local del navegador. */
  protected readonly fecha = instanteServidor;

  private cargarSolicitudes(): void {
    this.cambios.mias(this.venta().id).subscribe({
      next: (lista) => this.solicitudes.set(lista),
      // Sin la lista la pantalla igual funciona: se puede pedir, y el servidor avisa si ya hay una pendiente.
      error: () => undefined,
    });
  }

  // ---- Formulario ------------------------------------------------------------------------

  protected abrir(): void {
    this.abierto.set(true);
    this.enviada.set(null);
    this.errorEnvio.set(null);
    this.cantidades.set({});
    this.elegidas.set({});
    this.motivo.set('');
    this.cargarOpciones();
  }

  protected cerrar(): void {
    this.abierto.set(false);
    this.errorEnvio.set(null);
  }

  /**
   * Las otras tallas y colores de cada producto de la compra, del MISMO precio y con stock en la sucursal de la compra
   * (el servidor exige lo mismo). Si algo falla se avisa y se puede reintentar.
   */
  private cargarOpciones(): void {
    this.cargandoOpciones.set(true);
    this.errorOpciones.set(false);
    const sucursalId = this.venta().sucursal_id;
    const productos = [...new Set(this.lineas().map((l) => l.productoId).filter((id): id is number => id !== null))];
    const detalles$ = productos.length
      ? forkJoin(productos.map((id) => this.cambios.producto(id, sucursalId)))
      : of([] as CatalogoDetalle[]);
    detalles$
      .pipe(
        switchMap((detalles) => {
          const hermanas = [...new Set(detalles.flatMap((d) => d.variantes.map((v) => v.id)))];
          const etiquetas$ = hermanas.length ? this.cambios.etiquetas(hermanas) : of([] as ProductoImagenLookupItem[]);
          return etiquetas$.pipe(map((etiquetas) => ({ detalles, etiquetas })));
        }),
      )
      .subscribe({
        next: ({ detalles, etiquetas }) => {
          const nombres = new Map(
            etiquetas.map((e) => [e.variante_id, [e.talla_codigo, e.color_nombre].filter(Boolean).join(' · ')]),
          );
          const porLinea: Record<number, OpcionCambio[]> = {};
          for (const linea of this.lineas()) {
            const producto = detalles.find((d) => d.id === linea.productoId);
            const original = producto?.variantes.find((v) => v.id === linea.varianteId);
            if (!producto || !original) continue;
            porLinea[linea.id] = producto.variantes
              .filter(
                (v) =>
                  v.id !== original.id &&
                  Number(v.precio_efectivo) === Number(original.precio_efectivo) &&
                  (v.cantidad_disponible ?? 0) > 0,
              )
              .map((v) => ({
                varianteId: v.id,
                etiqueta: nombres.get(v.id) || v.sku,
                disponible: v.cantidad_disponible ?? 0,
              }));
          }
          this.opciones.set(porLinea);
          this.cargandoOpciones.set(false);
        },
        error: () => {
          this.cargandoOpciones.set(false);
          this.errorOpciones.set(true);
        },
      });
  }

  protected opcionesDe(linea: LineaParaCambio): OpcionCambio[] {
    return this.opciones()[linea.id] ?? [];
  }

  protected cantidadDe(linea: LineaParaCambio): number {
    return this.cantidades()[linea.id] ?? 0;
  }

  protected cambiarCantidad(linea: LineaParaCambio, delta: number): void {
    const nueva = Math.min(linea.cantidad, Math.max(0, this.cantidadDe(linea) + delta));
    this.cantidades.update((actual) => ({ ...actual, [linea.id]: nueva }));
    // Con una sola talla posible no hace falta elegir: queda marcada.
    const unica = this.opcionesDe(linea);
    if (nueva > 0 && this.elegidas()[linea.id] == null && unica.length === 1) this.elegir(linea, unica[0].varianteId);
  }

  protected elegir(linea: LineaParaCambio, varianteId: number | null): void {
    this.elegidas.update((actual) => ({ ...actual, [linea.id]: varianteId }));
  }

  protected elegidaDe(linea: LineaParaCambio): number | null {
    return this.elegidas()[linea.id] ?? null;
  }

  /** La talla elegida tiene menos unidades de las que se piden cambiar. */
  protected faltaStock(linea: LineaParaCambio): boolean {
    const elegida = this.opcionesDe(linea).find((o) => o.varianteId === this.elegidaDe(linea));
    return !!elegida && elegida.disponible < this.cantidadDe(linea);
  }

  /** Se puede enviar: hay prendas marcadas, cada una con su talla o color nuevo y con stock suficiente. */
  protected readonly puedeEnviar = computed(() => {
    const marcadas = this.seleccion();
    return (
      marcadas.length > 0 &&
      marcadas.every((l) => this.elegidaDe(l) !== null && !this.faltaStock(l)) &&
      !this.enviando() &&
      !this.sinConexion()
    );
  });

  protected enviar(): void {
    if (!this.puedeEnviar()) return;
    const datos: SolicitudCambioCrear = {
      venta_id: this.venta().id,
      motivo: this.motivo().trim() || null,
      detalle: this.seleccion().map((l) => ({
        venta_detalle_id: l.id,
        cantidad: this.cantidadDe(l),
        variante_nueva_id: this.elegidaDe(l)!,
      })),
    };
    this.enviando.set(true);
    this.errorEnvio.set(null);
    this.cambios.solicitar(datos).subscribe({
      next: (solicitud) => {
        this.enviando.set(false);
        this.enviada.set(solicitud);
        this.abierto.set(false);
        this.cargarSolicitudes();
      },
      error: (error: HttpErrorResponse) => {
        this.enviando.set(false);
        this.errorEnvio.set(mensajeDeError(error));
      },
    });
  }

  // ---- Cancelar --------------------------------------------------------------------------

  protected pedirCancelar(solicitud: SolicitudCambio): void {
    this.errorCancelar.set(null);
    this.confirmandoCancelar.set(solicitud.id);
  }

  protected noCancelar(): void {
    this.confirmandoCancelar.set(null);
  }

  protected cancelar(solicitud: SolicitudCambio): void {
    if (this.cancelando() !== null) return;
    this.cancelando.set(solicitud.id);
    this.errorCancelar.set(null);
    this.cambios.cancelar(solicitud.id).subscribe({
      next: () => {
        this.cancelando.set(null);
        this.confirmandoCancelar.set(null);
        this.cargarSolicitudes();
      },
      error: (error: HttpErrorResponse) => {
        this.cancelando.set(null);
        this.confirmandoCancelar.set(null);
        this.errorCancelar.set(mensajeDeError(error));
        // Pudo resolverse mientras tanto (aprobada o vencida): se vuelve a leer para mostrar lo real.
        this.cargarSolicitudes();
      },
    });
  }
}
