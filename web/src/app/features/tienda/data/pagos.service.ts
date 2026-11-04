import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { MetodoPagoPasarela, Pago, PagoIniciarRespuesta } from '../../../core/models/pagos.models';

@Injectable({ providedIn: 'root' })
export class PagosService {
  private readonly http = inject(HttpClient);

  iniciar(ventaId: number, metodoPago: MetodoPagoPasarela): Observable<PagoIniciarRespuesta> {
    return this.http.post<PagoIniciarRespuesta>(`${environment.apiUrl}/pagos/iniciar`, {
      venta_id: ventaId,
      metodo_pago: metodoPago,
    });
  }

  /** Cancela una compra sin pagar: el backend libera el stock y devuelve las prendas al carrito. */
  cancelarCompra(ventaId: number): Observable<unknown> {
    return this.http.post(`${environment.apiUrl}/pagos/venta/${ventaId}/cancelar`, {});
  }

  obtenerEstado(pagoId: number): Observable<Pago> {
    return this.http.get<Pago>(`${environment.apiUrl}/pagos/${pagoId}/estado`);
  }
}
