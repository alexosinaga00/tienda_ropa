import { HttpClient, HttpContext } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { SIN_TOAST_ERROR } from './http-contexts';
import type { Reembolso } from './models/ventas.models';

/**
 * Reembolsos (CU-17 y CU-18): el dinero que se devuelve a quien compró. Quien compró o el personal de la sucursal lee los
 * de una venta; solo quien tiene `pagos.gestionar` reintenta uno que quedó en proceso o falló. Los errores se muestran en
 * la propia pantalla (o se ignoran, en la lista de la tienda): por eso no activan el aviso global.
 */
@Injectable({ providedIn: 'root' })
export class ReembolsosService {
  private readonly http = inject(HttpClient);

  private readonly sinAviso = () => new HttpContext().set(SIN_TOAST_ERROR, true);

  /** Los reembolsos de una venta (vacío si no hubo ninguno). */
  deVenta(ventaId: number): Observable<Reembolso[]> {
    return this.http.get<Reembolso[]>(`${environment.apiUrl}/ventas/${ventaId}/reembolsos`, {
      context: this.sinAviso(),
    });
  }

  /** Vuelve a pedirle el dinero a la pasarela. 409 si ya estaba reembolsado. */
  reintentar(reembolsoId: number): Observable<Reembolso> {
    return this.http.post<Reembolso>(`${environment.apiUrl}/reembolsos/${reembolsoId}/reintentar`, null, {
      context: this.sinAviso(),
    });
  }
}
