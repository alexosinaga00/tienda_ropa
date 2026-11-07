import { HttpClient, HttpContext } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import { PedidoDiferidoCrear, PedidoDiferidoRespuesta } from '../../../core/models/metodo-pago.models';

/**
 * Envío de un pedido hecho sin conexión (`POST /pedidos-diferidos`). Lo usa la cola de pedidos: no muestra aviso global
 * de error (la cola decide qué hacer con cada código y le cuenta al cliente en su pantalla).
 */
@Injectable({ providedIn: 'root' })
export class PedidosDiferidosService {
  private readonly http = inject(HttpClient);

  /** Responde 200 con una decisión FINAL (cobrado o rechazado), también al reenviar la misma `operacion_id`. */
  enviar(pedido: PedidoDiferidoCrear): Observable<PedidoDiferidoRespuesta> {
    return this.http.post<PedidoDiferidoRespuesta>(`${environment.apiUrl}/pedidos-diferidos`, pedido, {
      context: new HttpContext().set(SIN_TOAST_ERROR, true),
    });
  }
}
