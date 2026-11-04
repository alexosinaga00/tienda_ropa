import { HttpClient, HttpContext } from '@angular/common/http';
import { Injectable, InjectionToken, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { SIN_TOAST_ERROR } from './http-contexts';
import {
  PedidoCreado,
  PedidoEstado,
  PedidoPagado,
  PedidoSolicitud,
  PruebaRespuesta,
  PruebaSolicitud,
} from './models/contratacion.models';

/** Dónde se guarda el token del pedido mientras el comprador está en PayPal (solo esta pestaña, se borra al cerrarla). */
export const CLAVE_PEDIDO_CONTRATACION = 'fs.contratacion.pedido';

/**
 * Lleva al comprador a la página de aprobación de PayPal. Es un token para que las pruebas lo simulen sin
 * navegar de verdad (`window.location.assign` no se puede espiar en el navegador de pruebas).
 */
export const IR_A_PAYPAL = new InjectionToken<(url: string) => void>('IR_A_PAYPAL', {
  providedIn: 'root',
  factory: () => (url: string) => window.location.assign(url),
});

/** Solo se manda a PayPal a una dirección https (nunca `javascript:`, `data:` ni http). */
export function esUrlHttps(texto: string | null | undefined): texto is string {
  if (!texto) return false;
  try {
    return new URL(texto).protocol === 'https:';
  } catch {
    return false;
  }
}

/**
 * Contratación de planes desde la portada: prueba gratuita y compra con PayPal (`/public/contratacion/...`).
 * Todas las rutas son anónimas. Los errores NO abren toast: la pantalla los muestra con
 * `errorDeContratacion` (`core/mensajes-contratacion`). Nunca se registra el token ni datos personales.
 */
@Injectable({ providedIn: 'root' })
export class ContratacionService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/public/contratacion`;

  iniciarPrueba(datos: PruebaSolicitud): Observable<PruebaRespuesta> {
    return this.http.post<PruebaRespuesta>(`${this.base}/prueba`, datos, { context: this.contexto() });
  }

  crearPedido(datos: PedidoSolicitud): Observable<PedidoCreado> {
    return this.http.post<PedidoCreado>(`${this.base}/pedidos`, datos, { context: this.contexto() });
  }

  consultarPedido(token: string): Observable<PedidoEstado> {
    return this.http.get<PedidoEstado>(this.rutaPedido(token), { context: this.contexto() });
  }

  /** Idempotente en el servidor: repetirla no cobra dos veces ni crea dos empresas. */
  capturarPedido(token: string): Observable<PedidoPagado> {
    return this.http.post<PedidoPagado>(`${this.rutaPedido(token)}/capturar`, null, { context: this.contexto() });
  }

  cancelarPedido(token: string): Observable<PedidoEstado> {
    return this.http.post<PedidoEstado>(`${this.rutaPedido(token)}/cancelar`, null, { context: this.contexto() });
  }

  // ---- Token del pedido en sessionStorage (puede no existir: navegación privada, datos bloqueados) --------------

  guardarToken(token: string): void {
    try {
      sessionStorage.setItem(CLAVE_PEDIDO_CONTRATACION, token);
    } catch {
      // Sin almacenamiento: el retorno de PayPal trae el token en la dirección.
    }
  }

  leerToken(): string | null {
    try {
      const token = sessionStorage.getItem(CLAVE_PEDIDO_CONTRATACION);
      return token !== null && token !== '' ? token : null;
    } catch {
      return null;
    }
  }

  limpiarToken(): void {
    try {
      sessionStorage.removeItem(CLAVE_PEDIDO_CONTRATACION);
    } catch {
      // nada que limpiar
    }
  }

  private rutaPedido(token: string): string {
    return `${this.base}/pedidos/${encodeURIComponent(token)}`;
  }

  private contexto(): HttpContext {
    return new HttpContext().set(SIN_TOAST_ERROR, true);
  }
}
