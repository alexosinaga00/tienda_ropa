import { DatePipe, DecimalPipe } from '@angular/common';
import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { switchMap } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { ProductoImagenLookupItem } from '../../../core/models/catalogo.models';
import { Envio, EstadoEnvio } from '../../../core/models/entregas.models';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import { MetodoPagoPasarela } from '../../../core/models/pagos.models';
import { PlazoCambio, Venta, VentaDetalle, etiquetaDevolucion } from '../../../core/models/ventas.models';
import { IconoComponent } from '../../../shared/icono/icono.component';
import { CarritoService } from '../data/carrito.service';
import { DireccionesService } from '../data/direcciones.service';
import { DisponibilidadService } from '../data/disponibilidad.service';
import { PagosService } from '../data/pagos.service';
import { PedidosService } from '../data/pedidos.service';
import { CheckoutService } from '../state/checkout.service';
import { TiendaActualService } from '../state/tienda-actual.service';
import { ResumenCompraComponent } from './resumen-compra.component';

const ETIQUETAS_ENVIO: Record<EstadoEnvio, string> = {
  programado: 'Programado',
  en_ruta: 'En camino',
  entregado: 'Entregado',
  fallido: 'No se pudo entregar',
};

/** Con qué se puede pagar una compra que quedó sin pagar (Libélula es un simulador: no se ofrece). */
const METODOS_REINTENTO: { codigo: MetodoPagoPasarela; etiqueta: string }[] = [
  { codigo: 'qr_online', etiqueta: 'QR' },
  { codigo: 'paypal', etiqueta: 'PayPal' },
];

interface LineaComprobante extends VentaDetalle {
  productoNombre?: string;
  imagenPrincipal?: string | null;
  tallaCodigo?: string | null;
  colorNombre?: string | null;
}

@Component({
  selector: 'app-compra-detalle',
  standalone: true,
  imports: [RouterLink, DatePipe, DecimalPipe, IconoComponent, ResumenCompraComponent],
  templateUrl: './compra-detalle.component.html',
  styleUrl: './compra-detalle.component.scss',
})
export class CompraDetalleComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly route = inject(ActivatedRoute);
  protected readonly tienda = inject(TiendaActualService);
  private readonly pedidosService = inject(PedidosService);
  private readonly direccionesService = inject(DireccionesService);
  private readonly disponibilidadService = inject(DisponibilidadService);
  private readonly pagosService = inject(PagosService);
  private readonly checkoutService = inject(CheckoutService);
  private readonly carritoService = inject(CarritoService);
  private readonly router = inject(Router);

  // ---- Una compra que quedó sin pagar: se puede pagar o cancelar desde aquí ----
  protected readonly metodos = METODOS_REINTENTO;
  protected readonly metodo = signal<MetodoPagoPasarela>('qr_online');
  protected readonly procesando = signal(false);
  protected readonly errorPago = signal<string | null>(null);
  protected readonly confirmandoCancelar = signal(false);
  /** Se acaba de cancelar: se avisa que las prendas volvieron al carrito. */
  protected readonly canceladaAhora = signal(false);

  protected readonly venta = signal<Venta | null>(null);
  /** Nombre de la sucursal de la compra (dónde retirar o llevar la prenda a cambiar). Sin dato, no se muestra. */
  protected readonly sucursalNombre = signal<string | null>(null);
  /** "Con devolución (1 de 4)" / "Devuelta", o null si no se devolvió nada. */
  protected readonly marcaDevolucion = computed(() => {
    const venta = this.venta();
    return venta ? etiquetaDevolucion(venta) : null;
  });
  protected readonly esPendiente = computed(() => this.venta()?.estado === 'pendiente_pago');
  protected readonly envio = signal<Envio | null>(null);
  /** Hasta cuándo se puede cambiar la compra (lo dice el servidor). Sin dato, no se muestra nada. */
  protected readonly plazo = signal<PlazoCambio | null>(null);
  protected readonly lineas = signal<LineaComprobante[]>([]);
  protected readonly cargando = signal(true);
  protected readonly error = signal(false);

  ngOnInit(): void {
    const ventaId = Number(this.route.snapshot.paramMap.get('id'));
    this.pedidosService
      .obtenerComprobante(ventaId)
      .pipe(
        switchMap((venta) => {
          this.venta.set(venta);
          this.cargarSeguimiento(venta);
          this.cargarPlazo(venta);
          this.cargarSucursal(venta);
          const params = new HttpParams().set('variante_ids', venta.detalle.map((d) => d.variante_id).join(','));
          return this.http.get<ProductoImagenLookupItem[]>(`${environment.apiUrl}/catalogo/variantes/detalle`, {
            params,
          });
        }),
      )
      .subscribe({
        next: (lookup) => {
          const porVariante = new Map(lookup.map((item) => [item.variante_id, item]));
          const detalle = this.venta()!.detalle;
          this.lineas.set(
            detalle.map((linea) => {
              const item = porVariante.get(linea.variante_id);
              return {
                ...linea,
                productoNombre: item?.producto_nombre,
                imagenPrincipal: item?.imagen_principal,
                tallaCodigo: item?.talla_codigo,
                colorNombre: item?.color_nombre,
              };
            }),
          );
          this.cargando.set(false);
        },
        error: () => {
          this.cargando.set(false);
          this.error.set(true);
        },
      });
  }

  protected elegirMetodo(codigo: MetodoPagoPasarela): void {
    this.metodo.set(codigo);
  }

  /**
   * Paga una compra que quedó pendiente. La ventana de la pasarela se abre ANTES de llamar al servidor (dentro del
   * clic) para que el navegador no la bloquee como emergente; después se sigue en la pantalla de estado del pago,
   * que consulta si se aprobó y permite reintentar.
   */
  protected pagarAhora(): void {
    const venta = this.venta();
    if (!venta || this.procesando()) return;

    const ventana = window.open('', '_blank');
    ventana?.document.write('Redirigiendo a la pasarela de pago...');
    this.procesando.set(true);
    this.errorPago.set(null);

    this.pagosService.iniciar(venta.id, this.metodo()).subscribe({
      next: (pagoIniciado) => {
        this.checkoutService.reiniciar();
        this.checkoutService.confirmarVenta(venta);
        this.checkoutService.confirmarPago(pagoIniciado);
        this.checkoutService.ventanaPago = ventana;
        if (ventana) ventana.location.href = pagoIniciado.url_redireccion;
        this.procesando.set(false);
        this.router.navigate(this.tienda.ruta('checkout', 'estado', String(pagoIniciado.pago.id)));
      },
      error: () => {
        ventana?.close();
        this.procesando.set(false);
        this.errorPago.set('No se pudo iniciar el pago. Prueba de nuevo.');
      },
    });
  }

  protected pedirCancelar(): void {
    this.confirmandoCancelar.set(true);
  }

  protected noCancelar(): void {
    this.confirmandoCancelar.set(false);
  }

  /** Cancela la compra sin pagar: se libera el stock y las prendas vuelven al carrito. */
  protected cancelarCompra(): void {
    const venta = this.venta();
    if (!venta || this.procesando()) return;
    this.procesando.set(true);
    this.errorPago.set(null);

    this.pagosService.cancelarCompra(venta.id).subscribe({
      next: () => {
        this.procesando.set(false);
        this.confirmandoCancelar.set(false);
        this.canceladaAhora.set(true);
        this.venta.set({ ...venta, estado: 'anulada' });
        // Las prendas volvieron al carrito: se vuelve a leer para que el contador de la barra lo refleje.
        this.carritoService.cargar().subscribe({ error: () => undefined });
      },
      error: () => {
        this.procesando.set(false);
        this.confirmandoCancelar.set(false);
        this.errorPago.set('No se pudo cancelar la compra. Prueba de nuevo.');
      },
    });
  }

  protected etiquetaEnvio(estado: EstadoEnvio): string {
    return ETIQUETAS_ENVIO[estado];
  }

  /** El backend manda las fechas en UTC sin zona ("2026-09-20T16:52:29"): sin la 'Z' se leerían como hora local. */
  protected fechaLocal(iso: string): Date {
    const tieneZona = /(Z|[+-]\d{2}:?\d{2})$/.test(iso);
    return new Date(tieneZona ? iso : `${iso}Z`);
  }

  /** El nombre de la sucursal sale de la lista pública de la tienda. Si falla, la pantalla queda como siempre. */
  private cargarSucursal(venta: Venta): void {
    this.disponibilidadService.sucursales().subscribe({
      next: (sucursales) => this.sucursalNombre.set(sucursales.find((s) => s.id === venta.sucursal_id)?.nombre ?? null),
      error: () => this.sucursalNombre.set(null),
    });
  }

  /**
   * El plazo para cambiar la prenda, solo en una compra pagada o entregada (una pendiente o anulada no tiene nada
   * que cambiar). Si la consulta falla, el comprobante igual se muestra, sin aviso ni mensaje de error.
   */
  private cargarPlazo(venta: Venta): void {
    if (venta.estado !== 'pagada' && venta.estado !== 'entregada') return;
    this.http
      .get<PlazoCambio>(`${environment.apiUrl}/ventas/${venta.id}/plazo-cambio`, {
        context: new HttpContext().set(SIN_TOAST_ERROR, true),
      })
      .subscribe({ next: (plazo) => this.plazo.set(plazo), error: () => this.plazo.set(null) });
  }

  /**
   * Solo si el envío está en marcha (compra pagada o entregada): con la compra
   * pendiente o anulada no hay nada que seguir. Si falla, el comprobante
   * igual se muestra (el error ya lo avisa el manejo global).
   */
  private cargarSeguimiento(venta: Venta): void {
    const enMarcha = venta.estado === 'pagada' || venta.estado === 'entregada';
    if (venta.costo_envio <= 0 || !enMarcha) return;
    this.direccionesService.obtenerEnvioDeVenta(venta.id).subscribe({ next: (envio) => this.envio.set(envio) });
  }
}
