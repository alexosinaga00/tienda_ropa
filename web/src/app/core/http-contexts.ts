import { HttpContextToken } from '@angular/common/http';

/**
 * Marca una petición cuyo error ya se muestra en la propia pantalla (p. ej.
 * "No encontramos esta tienda"): el `errorInterceptor` no abre el toast rojo.
 * Uso: `http.get(url, { context: new HttpContext().set(SIN_TOAST_ERROR, true) })`.
 */
export const SIN_TOAST_ERROR = new HttpContextToken<boolean>(() => false);

/**
 * Petición de mejor esfuerzo que NO debe intentar renovar la sesión si recibe 401 (el `authInterceptor` la deja pasar
 * tal cual). La usa la baja del aviso push al cerrar sesión: si la sesión ya no vale, renovarla sería reabrir un cierre
 * de sesión que ya está en marcha.
 */
export const SIN_RENOVAR_SESION = new HttpContextToken<boolean>(() => false);
