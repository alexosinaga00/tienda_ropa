import { HttpClient, HttpContext, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { codigoFuncional } from '../../../core/errores-funcionales';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import { CanalPaypal, MetodoPagoPaypal, PaypalIniciarRespuesta } from '../../../core/models/metodo-pago.models';

/**
 * Método de pago guardado del cliente (PayPal Vault). El servidor guarda el token; aquí solo se pide el estado y se
 * inicia, confirma o quita. Los errores se muestran en la propia pantalla, no como aviso global: por eso estas
 * llamadas no activan el aviso automático de error.
 */
@Injectable({ providedIn: 'root' })
export class MetodoPagoService {
  private readonly http = inject(HttpClient);

  private readonly sinAviso = () => new HttpContext().set(SIN_TOAST_ERROR, true);

  estado(): Observable<MetodoPagoPaypal> {
    return this.http.get<MetodoPagoPaypal>(`${environment.apiUrl}/metodos-pago/paypal`, { context: this.sinAviso() });
  }

  /** Crea la preparación en PayPal. Las URLs de retorno las arma el servidor: el cliente nunca las manda. */
  iniciar(canal: CanalPaypal = 'web'): Observable<PaypalIniciarRespuesta> {
    return this.http.post<PaypalIniciarRespuesta>(
      `${environment.apiUrl}/metodos-pago/paypal/iniciar`,
      { canal },
      { context: this.sinAviso() },
    );
  }

  /** Cambia el token de preparación (el que PayPal devolvió al volver) por el método guardado. Idempotente. */
  confirmar(tokenPreparacion: string): Observable<MetodoPagoPaypal> {
    return this.http.post<MetodoPagoPaypal>(
      `${environment.apiUrl}/metodos-pago/paypal/confirmar`,
      { token_preparacion: tokenPreparacion },
      { context: this.sinAviso() },
    );
  }

  /** Quita el método guardado (204, idempotente). */
  quitar(): Observable<void> {
    return this.http.delete<void>(`${environment.apiUrl}/metodos-pago/paypal`, { context: this.sinAviso() });
  }
}

/** El texto que se le muestra al cliente cuando falla una llamada del método de pago. */
export function mensajeErrorMetodoPago(error: unknown): string {
  if (!(error instanceof HttpErrorResponse)) return 'No se pudo completar la operación. Prueba de nuevo.';
  if (error.status === 0) return 'No hay conexión con el servidor. Conéctate e inténtalo de nuevo.';
  const codigo = codigoFuncional(error);
  if (codigo === 'paypal_no_disponible') return 'PayPal no responde en este momento. Prueba de nuevo en unos minutos.';
  if (codigo === 'paypal_no_aprobado') return 'No terminaste de autorizar tu PayPal. Vuelve a intentarlo.';
  if (error.status === 404) return 'Este enlace ya no es válido. Vuelve a guardar tu PayPal desde tu cuenta.';
  const cuerpo = error.error as { mensaje?: unknown; detail?: unknown } | null;
  if (typeof cuerpo?.mensaje === 'string' && cuerpo.mensaje) return cuerpo.mensaje;
  if (typeof cuerpo?.detail === 'string' && cuerpo.detail && !/^[a-z][a-z0-9_]*$/.test(cuerpo.detail)) return cuerpo.detail;
  if (error.status === 429) return 'Hiciste muchos intentos. Espera un momento e inténtalo de nuevo.';
  return 'No se pudo completar la operación. Prueba de nuevo.';
}
