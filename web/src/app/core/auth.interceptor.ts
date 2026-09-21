import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, switchMap, throwError } from 'rxjs';
import { environment } from '../../environments/environment';
import { AuthService } from './auth.service';

// '/catalogo' cubre /api/v1/catalogo, /catalogo/buscar y /catalogo/{id} --
// el resto del router de catálogo público. Sin esto, un 401 accidental ahí
// dispararía refrescarTokens()/logout() y mandaría a un visitante anónimo a
// /login.
// OJO: no agregar '/categorias' acá -- ese prefijo SÍ lo comparte el GET
// público con el POST/PUT/DELETE de administración de categorías, y
// meterlo rompería el refresh de sesión de esas pantallas.
const RUTAS_SIN_TOKEN = ['/auth/login', '/auth/registro', '/auth/refresh', '/auth/recuperar', '/catalogo'];

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
      if (!esNoAutorizado || rutaPublica) {
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
          catchError((errorRefresh) => {
            authService.logout();
            return throwError(() => errorRefresh);
          }),
        )
        .pipe(switchMap((tokens) => next(agregarToken(req, tokens.access_token))));
    }),
  );
};
