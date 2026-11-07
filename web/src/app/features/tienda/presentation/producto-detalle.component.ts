import { DecimalPipe } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
import { AuthService } from '../../../core/auth.service';
import { ConectividadService } from '../../../core/conectividad.service';
import { CatalogoDetalle, Color, Talla } from '../../../core/models/catalogo.models';
import { aCentavos, textoDinero } from '../../../core/offline-cliente/dinero';
import { Disponibilidad } from '../../../core/models/inventario.models';
import { Sucursal } from '../../../core/models/organizacion.models';
import { IconoComponent } from '../../../shared/icono/icono.component';
import { CarritoService } from '../data/carrito.service';
import { DisponibilidadService } from '../data/disponibilidad.service';
import { CarritoLocalService } from '../state/carrito-local.service';
import { ReservaCarritoService } from '../state/reserva-carrito.service';
import { TiendaActualService } from '../state/tienda-actual.service';

@Component({
  selector: 'app-producto-detalle',
  standalone: true,
  imports: [RouterLink, DecimalPipe, IconoComponent],
  templateUrl: './producto-detalle.component.html',
  styleUrl: './producto-detalle.component.scss',
})
export class ProductoDetalleComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly route = inject(ActivatedRoute);
  protected readonly tienda = inject(TiendaActualService);
  private readonly disponibilidadService = inject(DisponibilidadService);
  private readonly carritoService = inject(CarritoService);
  protected readonly reservaCarritoService = inject(ReservaCarritoService);
  protected readonly authService = inject(AuthService);
  private readonly conectividad = inject(ConectividadService);
  private readonly carritoLocal = inject(CarritoLocalService);

  private readonly productoId = Number(this.route.snapshot.paramMap.get('id'));
  protected readonly returnTo = `/producto/${this.productoId}`;

  protected readonly detalle = signal<CatalogoDetalle | null>(null);
  protected readonly tallas = signal<Talla[]>([]);
  protected readonly colores = signal<Color[]>([]);
  protected readonly sucursales = signal<Sucursal[]>([]);
  protected readonly disponibilidad = signal<Disponibilidad[]>([]);
  protected readonly imagenActiva = signal(0);

  protected readonly cargando = signal(true);
  protected readonly error = signal(false);
  protected readonly agregando = signal(false);
  protected readonly agregado = signal(false);
  /** Sin conexión no se pudo leer la disponibilidad de la variante elegida: "no se sabe", no "agotado". */
  protected readonly disponibilidadDesconocida = signal(false);
  protected readonly errorLocal = signal<string | null>(null);

  /** Sin red o con el servidor caído: se ve lo que ya estaba cargado y lo que se agrega va al carrito local. */
  protected readonly sinConexion = computed(() => this.conectividad.estado() !== 'en_linea');

  protected readonly tallaId = signal<number | null>(null);
  protected readonly colorId = signal<number | null>(null);

  protected readonly tallasDisponibles = computed(() => {
    const ids = new Set(this.detalle()?.variantes.map((v) => v.talla_id) ?? []);
    return this.tallas().filter((t) => ids.has(t.id));
  });

  protected readonly coloresDisponibles = computed(() => {
    const ids = new Set(this.detalle()?.variantes.map((v) => v.color_id) ?? []);
    return this.colores().filter((c) => ids.has(c.id));
  });

  protected readonly colorSeleccionado = computed(() => this.colores().find((c) => c.id === this.colorId()) ?? null);

  protected readonly varianteActiva = computed(() => {
    const tallaId = this.tallaId();
    const colorId = this.colorId();
    if (tallaId === null || colorId === null) return null;
    return this.detalle()?.variantes.find((v) => v.talla_id === tallaId && v.color_id === colorId) ?? null;
  });

  protected readonly precio = computed(() => this.varianteActiva()?.precio_efectivo ?? this.detalle()?.precio_base ?? 0);

  protected readonly imagenes = computed(() => {
    const todas = this.detalle()?.imagenes ?? [];
    const colorId = this.colorId();
    const filtradas = colorId !== null ? todas.filter((img) => img.color_id === null || img.color_id === colorId) : todas;
    return filtradas.length > 0 ? filtradas : todas;
  });

  protected readonly disponibilidadPorSucursal = computed(() => {
    const mapa = new Map(this.disponibilidad().map((d) => [d.sucursal_id, d.cantidad_disponible]));
    return this.sucursales().map((sucursal) => ({ sucursal, cantidad: mapa.get(sucursal.id) ?? 0 }));
  });

  ngOnInit(): void {
    forkJoin({
      detalle: this.http.get<CatalogoDetalle>(this.tienda.urlPublica(`catalogo/${this.productoId}`)),
      tallas: this.http.get<Talla[]>(this.tienda.urlPublica('tallas'), { params: { tamanio: 100 } }),
      colores: this.http.get<Color[]>(this.tienda.urlPublica('colores'), { params: { tamanio: 100 } }),
      sucursales: this.disponibilidadService.sucursales(),
    }).subscribe({
      next: ({ detalle, tallas, colores, sucursales }) => {
        this.detalle.set(detalle);
        this.tallas.set(tallas);
        this.colores.set(colores);
        this.sucursales.set(sucursales);
        this.cargando.set(false);
        // Con conexión se recuerdan las sucursales: sin red se necesitan para elegir dónde retirar.
        if (!this.sinConexion()) {
          void this.carritoLocal.recordarSucursales(sucursales.map((s) => ({ id: s.id, nombre: s.nombre, es_deposito: s.es_deposito })));
        }
      },
      error: () => {
        this.cargando.set(false);
        this.error.set(true);
      },
    });
  }

  seleccionarTalla(id: number): void {
    this.tallaId.set(id);
    this.imagenActiva.set(0);
    this.cargarDisponibilidad();
  }

  seleccionarColor(id: number): void {
    this.colorId.set(id);
    this.imagenActiva.set(0);
    this.cargarDisponibilidad();
  }

  private cargarDisponibilidad(): void {
    const variante = this.varianteActiva();
    this.disponibilidadDesconocida.set(false);
    if (!variante) {
      this.disponibilidad.set([]);
      return;
    }
    this.disponibilidadService.porVariante(variante.id).subscribe({
      next: (filas) => this.disponibilidad.set(filas),
      error: () => {
        // Sin datos no es lo mismo que agotado: se dice que no se sabe.
        this.disponibilidad.set([]);
        this.disponibilidadDesconocida.set(true);
      },
    });
  }

  agregarAlCarrito(): void {
    const variante = this.varianteActiva();
    if (!variante || this.agregando()) return;

    if (this.sinConexion()) {
      void this.agregarAlCarritoLocal();
      return;
    }

    this.agregando.set(true);
    this.carritoService.agregar(variante.id, 1).subscribe({
      next: () => {
        this.agregando.set(false);
        this.agregado.set(true);
        setTimeout(() => this.agregado.set(false), 2500);
      },
      error: () => {
        this.agregando.set(false);
      },
    });
  }

  /**
   * Sin conexión la prenda se guarda en el carrito LOCAL con todo lo necesario para mostrarla (nombre, talla, color,
   * precio, foto) y con la sucursal donde se sabía que había stock, si se sabía.
   */
  private async agregarAlCarritoLocal(): Promise<void> {
    const variante = this.varianteActiva();
    const detalle = this.detalle();
    if (!variante || !detalle) return;

    this.agregando.set(true);
    this.errorLocal.set(null);
    const conStock = this.disponibilidadPorSucursal().find((fila) => fila.cantidad > 0)?.sucursal ?? null;
    const guardado = await this.carritoLocal.agregar({
      variante_id: variante.id,
      producto_id: detalle.id,
      cantidad: 1,
      producto_nombre: detalle.nombre,
      talla: this.tallas().find((t) => t.id === variante.talla_id)?.codigo ?? null,
      color: this.colores().find((c) => c.id === variante.color_id)?.nombre ?? null,
      precio_unitario: textoDinero(aCentavos(variante.precio_efectivo)),
      imagen: this.imagenes()[0]?.url ?? null,
      sucursal_id: conStock?.id ?? null,
      sucursal_nombre: conStock?.nombre ?? null,
    });
    this.agregando.set(false);
    if (!guardado) {
      this.errorLocal.set('No pudimos guardar la prenda en tu equipo. Inicia sesión con conexión y vuelve a intentarlo.');
      return;
    }
    this.agregado.set(true);
    setTimeout(() => this.agregado.set(false), 2500);
  }

  reservarParaProbar(): void {
    const variante = this.varianteActiva();
    const detalle = this.detalle();
    if (!variante || !detalle) return;

    this.reservaCarritoService.agregar({
      varianteId: variante.id,
      productoNombre: detalle.nombre,
      tallaCodigo: this.tallas().find((t) => t.id === variante.talla_id)?.codigo ?? '',
      colorNombre: this.colores().find((c) => c.id === variante.color_id)?.nombre ?? '',
      imagenPrincipal: this.imagenes()[0]?.url ?? null,
    });
  }
}
