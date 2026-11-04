import { DatePipe, DecimalPipe } from '@angular/common';
import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { switchMap } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { ProductoImagenLookupItem } from '../../../core/models/catalogo.models';
import { Envio, EstadoEnvio } from '../../../core/models/entregas.models';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import { PlazoCambio, Venta, VentaDetalle } from '../../../core/models/ventas.models';
import { IconoComponent } from '../../../shared/icono/icono.component';
import { DireccionesService } from '../data/direcciones.service';
import { PedidosService } from '../data/pedidos.service';
import { TiendaActualService } from '../state/tienda-actual.service';
import { ResumenCompraComponent } from './resumen-compra.component';

const ETIQUETAS_ENVIO: Record<EstadoEnvio, string> = {
  programado: 'Programado',
  en_ruta: 'En camino',
  entregado: 'Entregado',
  fallido: 'No se pudo entregar',
};

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

  protected readonly venta = signal<Venta | null>(null);
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

  protected etiquetaEnvio(estado: EstadoEnvio): string {
    return ETIQUETAS_ENVIO[estado];
  }

  /** El backend manda las fechas en UTC sin zona ("2026-09-20T16:52:29"): sin la 'Z' se leerían como hora local. */
  protected fechaLocal(iso: string): Date {
    const tieneZona = /(Z|[+-]\d{2}:?\d{2})$/.test(iso);
    return new Date(tieneZona ? iso : `${iso}Z`);
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
