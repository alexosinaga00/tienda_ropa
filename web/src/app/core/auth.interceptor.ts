import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, switchMap, throwError } from 'rxjs';
import { environment } from '../../environments/environment';
import { AuthService } from './auth.service';
import { SIN_RENOVAR_SESION } from './http-contexts';

// '/catalogo' cubre /api/v1/catalogo, /catalogo/buscar y /catalogo/{id} --
// el resto del router de catálogo público. Sin esto, un 401 accidental ahí
// dispararía refrescarTokens()/logout() y mandaría a un visitante anónimo a
// /login.
// OJO: no agregar '/categorias' acá -- ese prefijo SÍ lo comparte el GET
// público con el POST/PUT/DELETE de administración de categorías, y
// meterlo rompería el refresh de sesión de esas pantallas.
// '/public/' son las rutas de cada tienda (/public/{codigo}/...): la empresa
// sale del código de la ruta, nunca del token, y no deben llevar Authorization
// (importa para el caché del Service Worker).
const RUTAS_SIN_TOKEN = ['/auth/login', '/auth/registro', '/auth/refresh', '/auth/recuperar', '/catalogo', '/public/'];

// Dos excepciones dentro de '/catalogo' que SÍ requieren JWT (catalogo/
// router.py: buscar_variantes_para_venta exige catalogo.ver, y
// obtener_detalle_para_dashboard exige cualquier usuario logueado) -- sin
// esto, el interceptor las trataría como públicas y nunca les mandaría el
// token, rompiendo la búsqueda de la caja y el lookup de detalle.
const RUTAS_CATALOGO_CON_TOKEN = ['/catalogo/variantes/buscar', '/catalogo/variantes/detalle'];

function esRutaPublica(url: string): boolean {
  if (RUTAS_CATALOGO_CON_TOKEN.some((ruta) => url.includes(ruta))) {
    return false;
  }
  return RUTAS_SIN_TOKEN.some((ruta) => url.includes(ruta));
}

function agregarToken(req: any, token: string | null) {
  if (!token) {
    return req;
  }
  return req.clone({ setHeaders: { Authorization: `Bearer ${token}` } });
}

/**
 * Agrega el JWT a cada request contra la API. Si el backend responde 401
 * (token vencido), intenta refrescar una sola vez y reintenta la request
 * original; si el refresh también falla, cierra la sesión.
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const authService = inject(AuthService);

  if (!req.url.startsWith(environment.apiUrl)) {
    return next(req);
  }

  const rutaPublica = esRutaPublica(req.url);
  const requestConToken = rutaPublica ? req : agregarToken(req, authService.getAccessToken());

  return next(requestConToken).pipe(
    catchError((error: unknown) => {
      const esNoAutorizado = error instanceof HttpErrorResponse && error.status === 401;
      if (!esNoAutorizado || rutaPublica || req.context.get(SIN_RENOVAR_SESION)) {
        return throwError(() => error);
      }

      // El catchError va DENTRO del pipe del refresh y ANTES del switchMap:
      // solo debe cerrar la sesión si falla el refresh. Encadenado después
      // del switchMap atrapaba también los errores de la request
      // reintentada, así que un refresh exitoso seguido de un 403/409/500
      // por cualquier otra causa deslogueaba al usuario en medio de un
      // checkout o de una venta en caja.
      return authService
        .refrescarTokensCompartido()
        .pipe(
          catchError((errorRefresh: unknown) => {
            // Sin red (status 0) la sesión sigue vigente: no se cierra, para no dejar al personal fuera al trabajar
            // sin conexión. Solo cierra cuando el servidor rechaza el refresh (401/403).
            const rechazado =
              errorRefresh instanceof HttpErrorResponse && (errorRefresh.status === 401 || errorRefresh.status === 403);
            if (rechazado) {
              authService.logout();
            }
            return throwError(() => errorRefresh);
          }),
        )
        .pipe(switchMap((tokens) => next(agregarToken(req, tokens.access_token))));
    }),
  );
};
