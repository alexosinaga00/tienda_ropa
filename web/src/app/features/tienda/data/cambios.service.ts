import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import { CatalogoDetalle, ProductoImagenLookupItem } from '../../../core/models/catalogo.models';
import { SolicitudCambio, SolicitudCambioCrear } from '../../../core/models/ventas.models';
import { TiendaActualService } from '../state/tienda-actual.service';

/**
 * Solicitudes de cambio de talla o color del cliente (CU-17, Etapa 2). El cliente pide el cambio desde su compra y el
 * personal de la sucursal lo aprueba cuando trae la prenda. Los errores se muestran en la pantalla, no como aviso
 * global: por eso estas llamadas no activan el aviso automático de error.
 */
@Injectable({ providedIn: 'root' })
export class CambiosService {
  private readonly http = inject(HttpClient);
  private readonly tienda = inject(TiendaActualService);

  private readonly sinAviso = () => new HttpContext().set(SIN_TOAST_ERROR, true);

  solicitar(datos: SolicitudCambioCrear): Observable<SolicitudCambio> {
    return this.http.post<SolicitudCambio>(`${environment.apiUrl}/solicitudes-cambio`, datos, {
      context: this.sinAviso(),
    });
  }

  /** Las solicitudes del cliente: las de una compra, o todas si no se indica. */
  mias(ventaId?: number): Observable<SolicitudCambio[]> {
    const params = ventaId === undefined ? new HttpParams() : new HttpParams().set('venta_id', ventaId);
    return this.http.get<SolicitudCambio[]>(`${environment.apiUrl}/solicitudes-cambio/mias`, {
      params,
      context: this.sinAviso(),
    });
  }

  cancelar(solicitudId: number): Observable<SolicitudCambio> {
    return this.http.post<SolicitudCambio>(`${environment.apiUrl}/solicitudes-cambio/${solicitudId}/cancelar`, {}, {
      context: this.sinAviso(),
    });
  }

  /** Las tallas y colores de un producto con su precio y su stock en la sucursal de la compra (catálogo público). */
  producto(productoId: number, sucursalId: number): Observable<CatalogoDetalle> {
    return this.http.get<CatalogoDetalle>(this.tienda.urlPublica(`catalogo/${productoId}`), {
      params: { sucursal_id: sucursalId },
      context: this.sinAviso(),
    });
  }

  /** "Talla · color" de varias variantes a la vez. */
  etiquetas(varianteIds: number[]): Observable<ProductoImagenLookupItem[]> {
    return this.http.get<ProductoImagenLookupItem[]>(`${environment.apiUrl}/catalogo/variantes/detalle`, {
      params: { variante_ids: varianteIds.join(',') },
      context: this.sinAviso(),
    });
  }
}
