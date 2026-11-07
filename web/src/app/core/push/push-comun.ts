import { HttpClient, HttpContext } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../../environments/environment';
import { SIN_RENOVAR_SESION, SIN_TOAST_ERROR } from '../http-contexts';

/**
 * Lo mínimo de los avisos push que necesita el arranque de la app (cerrar sesión, el toast de avisos). Va aparte de
 * `PushWebService` a propósito: ese servicio se carga bajo demanda y esto no debe arrastrarlo al paquete inicial.
 */

/** Dónde se recuerda el token de este navegador: solo identifica al dispositivo ante FCM (no es una sesión ni un secreto de la cuenta). */
export const CLAVE_TOKEN_PUSH_WEB = 'fs_push_web_token';

/** El `key` del toast de avisos (con botón "Ver"): lo dibuja `app.html`. */
export const CLAVE_TOAST_AVISO = 'aviso-push';

/** El token recordado de este navegador, o null si los avisos no están activados. */
export function leerTokenPushGuardado(): string | null {
  try {
    return localStorage.getItem(CLAVE_TOKEN_PUSH_WEB);
  } catch {
    return null;
  }
}

/**
 * `POST /dispositivos-push/baja`. Mejor esfuerzo: sin aviso de error y SIN intentar renovar la sesión si responde 401
 * (al cerrar sesión, renovarla sería reabrir el cierre que ya está en marcha). La petición sale en el momento de llamar,
 * con el token de acceso que todavía vale.
 */
export function pedirBajaDelToken(http: HttpClient, token: string): Promise<unknown> {
  return firstValueFrom(
    http.post(`${environment.apiUrl}/dispositivos-push/baja`, { token }, {
      context: new HttpContext().set(SIN_TOAST_ERROR, true).set(SIN_RENOVAR_SESION, true),
    }),
  );
}
