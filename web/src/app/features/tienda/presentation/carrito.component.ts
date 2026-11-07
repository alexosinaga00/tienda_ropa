import { DecimalPipe } from '@angular/common';
import { HttpClient, HttpContext } from '@angular/common/http';
import { Component, OnInit, computed, effect, inject, signal, untracked } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { environment } from '../../../../environments/environment';
import { ConectividadService } from '../../../core/conectividad.service';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import { Venta } from '../../../core/models/ventas.models';
import { IconoComponent } from '../../../shared/icono/icono.component';
import { CarritoService } from '../data/carrito.service';
import { CarritoLocalService } from '../state/carrito-local.service';
import { CheckoutService } from '../state/checkout.service';
import { MetodoPagoLocalService } from '../state/metodo-pago-local.service';
import { TiendaActualService } from '../state/tienda-actual.service';
import { ResumenCompraComponent } from './resumen-compra.component';

/** Una línea tal como se dibuja, sea del carrito del servidor (con conexión) o del local (sin conexión). */
interface LineaVista {
  varianteId: number;
  nombre: string;
  detalle: string;
  precio: number;
  imagen: string | null;
  cantidad: number;
  disponible: boolean;
}

@Component({
  selector: 'app-carrito',
  standalone: true,
  imports: [RouterLink, DecimalPipe, IconoComponent, ResumenCompraComponent],
  templateUrl: './carrito.component.html',
  styleUrl: './carrito.component.scss',
})
export class CarritoComponent implements OnInit {
  protected readonly carritoService = inject(CarritoService);
  protected readonly carritoLocal = inject(CarritoLocalService);
  protected readonly metodoPagoLocal = inject(MetodoPagoLocalService);
  private readonly conectividad = inject(ConectividadService);
  private readonly checkoutService = inject(CheckoutService);
  private readonly router = inject(Router);
  protected readonly tienda = inject(TiendaActualService);

  private readonly http = inject(HttpClient);

  protected readonly cargando = signal(true);
  /** Compras que quedaron sin pagar: con ellas el carrito está vacío (las prendas pasaron a la compra). */
  protected readonly comprasPendientes = signal<Venta[]>([]);

  /** Sin red o con el servidor caído: se muestra el carrito local en vez del del servidor. */
  protected readonly sinConexion = computed(() => this.conectividad.estado() !== 'en_linea');

  /** Las líneas que se dibujan: las del carrito local sin conexión; con conexión, las del servidor. */
  protected readonly lineasVista = computed<LineaVista[]>(() =>
    this.sinConexion()
      ? this.carritoLocal.lineas().map((l) => ({
          varianteId: l.variante_id,
          nombre: l.producto_nombre,
          detalle: [l.talla, l.color].filter(Boolean).join(' · '),
          precio: Number(l.precio_unitario),
          imagen: l.imagen,
          cantidad: l.cantidad,
          disponible: true,
        }))
      : this.carritoService.lineas().map((l) => ({
          varianteId: l.variante_id,
          nombre: l.productoNombre ?? 'Prenda',
          detalle: [l.tallaCodigo, l.colorNombre].filter(Boolean).join(' · '),
          precio: l.precio_unitario,
          imagen: l.imagenPrincipal ?? null,
          cantidad: l.cantidad,
          disponible: l.disponible,
        })),
  );

  /** El backend rechaza la compra mientras haya prendas dadas de baja en el carrito. */
  protected readonly hayNoDisponibles = computed(() => this.lineasVista().some((l) => !l.disponible));

  /** Subtotal con los precios guardados (solo para el carrito local). */
  protected readonly subtotalLocal = computed(() => this.carritoLocal.subtotalCentavos() / 100);

  /** "Pasar a mi carrito" en curso y cómo salió. */
  protected readonly pasando = signal(false);
  protected readonly resultadoPaso = signal<string | null>(null);

  private estabaSinConexion = this.sinConexion();

  constructor() {
    // Al volver la conexión con la pantalla abierta, se trae el carrito del servidor (el local se queda a la vista).
    effect(() => {
      const sin = this.sinConexion();
      untracked(() => {
        if (this.estabaSinConexion && !sin) {
          this.recargar();
          this.cargarComprasPendientes();
        }
        this.estabaSinConexion = sin;
      });
    });
  }

  ngOnInit(): void {
    void this.carritoLocal.cargar();
    void this.metodoPagoLocal.cargar();
    if (this.sinConexion()) {
      this.cargando.set(false);
      return;
    }
    this.recargar();
    this.cargarComprasPendientes();
  }

  /** Si algo falla, simplemente no se muestra el aviso (el carrito sigue igual y sin mensaje de error). */
  private cargarComprasPendientes(): void {
    this.http
      .get<Venta[]>(`${environment.apiUrl}/ventas/mis-compras`, { context: new HttpContext().set(SIN_TOAST_ERROR, true) })
      .subscribe({
        next: (compras) => this.comprasPendientes.set(compras.filter((c) => c.estado === 'pendiente_pago')),
        error: () => this.comprasPendientes.set([]),
      });
  }

  private recargar(): void {
    this.cargando.set(true);
    this.carritoService.cargar().subscribe({
      next: () => {
        this.cargando.set(false);
        this.cargarResumen();
      },
      error: () => this.cargando.set(false),
    });
  }

  private cargarResumen(): void {
    this.carritoService.refrescarResumen();
  }

  aumentar(varianteId: number, cantidadActual: number): void {
    if (this.sinConexion()) {
      void this.carritoLocal.cambiarCantidad(varianteId, cantidadActual + 1);
      return;
    }
    this.carritoService.actualizarCantidad(varianteId, cantidadActual + 1).subscribe(() => this.cargarResumen());
  }

  disminuir(varianteId: number, cantidadActual: number): void {
    if (cantidadActual <= 1) {
      this.quitar(varianteId);
      return;
    }
    if (this.sinConexion()) {
      void this.carritoLocal.cambiarCantidad(varianteId, cantidadActual - 1);
      return;
    }
    this.carritoService.actualizarCantidad(varianteId, cantidadActual - 1).subscribe(() => this.cargarResumen());
  }

  quitar(varianteId: number): void {
    if (this.sinConexion()) {
      void this.carritoLocal.quitar(varianteId);
      return;
    }
    this.carritoService.quitar(varianteId).subscribe(() => this.cargarResumen());
  }

  continuar(): void {
    if (this.hayNoDisponibles()) return;
    if (this.sinConexion()) {
      // Sin conexión solo se paga con el PayPal guardado.
      if (this.carritoLocal.cantidadLineas() === 0 || !this.metodoPagoLocal.tienePaypal()) return;
      this.router.navigate(this.tienda.ruta('checkout', 'sin-conexion'));
      return;
    }
    this.checkoutService.reiniciar();
    this.router.navigate(this.tienda.ruta('checkout', 'entrega'));
  }

  /** Con conexión otra vez: cada prenda guardada sin conexión se agrega al carrito del servidor y sale del local. */
  protected async pasarAMiCarrito(): Promise<void> {
    if (this.pasando() || this.sinConexion()) return;
    this.pasando.set(true);
    this.resultadoPaso.set(null);
    const { pasadas, fallidas } = await this.carritoLocal.pasarAlServidor();
    this.pasando.set(false);
    this.resultadoPaso.set(
      fallidas === 0
        ? `Pasamos ${pasadas} ${pasadas === 1 ? 'prenda' : 'prendas'} a tu carrito.`
        : `Pasamos ${pasadas} y ${fallidas} no se pudo pasar (quizá ya no hay stock). Quedaron guardadas aquí.`,
    );
    this.recargar();
  }

  protected descartarLocal(): void {
    void this.carritoLocal.vaciar();
    this.resultadoPaso.set(null);
  }
}
