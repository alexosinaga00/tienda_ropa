import { DatePipe, DecimalPipe } from '@angular/common';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { switchMap } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { ProductoImagenLookupItem } from '../../../core/models/catalogo.models';
import { Envio, EstadoEnvio } from '../../../core/models/entregas.models';
import { Venta, VentaDetalle } from '../../../core/models/ventas.models';
import { DireccionesService } from '../data/direcciones.service';
import { PedidosService } from '../data/pedidos.service';

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
  imports: [RouterLink, DatePipe, DecimalPipe],
  templateUrl: './compra-detalle.component.html',
  styleUrl: './compra-detalle.component.scss',
})
export class CompraDetalleComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly route = inject(ActivatedRoute);
  private readonly pedidosService = inject(PedidosService);
  private readonly direccionesService = inject(DireccionesService);

  protected readonly venta = signal<Venta | null>(null);
  protected readonly envio = signal<Envio | null>(null);
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
