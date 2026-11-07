import { inject } from '@angular/core';
import { CanActivateFn, Router, RouterStateSnapshot, UrlTree } from '@angular/router';
import { MessageService } from 'primeng/api';
import { CarritoService } from '../features/tienda/data/carrito.service';
import { TiendaActualService } from '../features/tienda/state/tienda-actual.service';
import { AuthService, RUTA_LOGIN_PERSONAL } from './auth.service';
import { destinoInternoSeguro } from './navegacion-sin-conexion';

/** Código de tienda al comienzo de una URL del comprador: /t/:codigo/... */
const PATRON_TIENDA = /^\/t\/([^/?#]+)/;

/** Pantalla de entrada del superadministrador y raíz de todo su panel. */
export const RUTA_INICIO_SUPERADMIN = '/plataforma/empresas';

/** Pantalla de entrada del personal de una empresa. */
export const RUTA_INICIO_PERSONAL = '/dashboard';

const PATRON_PLATAFORMA = /^\/plataforma(?:[/?#]|$)/;

/**
 * A dónde manda a quien no tiene sesión en una pantalla del personal: al acceso del personal, recordando la pantalla
 * que quería abrir (`returnTo`, solo si es una ruta interna) para volver a ella tras iniciar sesión. Así un QR que lleva
 * a la Caja (`/caja?venta=VTA-0001`) sigue funcionando aunque la sesión esté cerrada.
 */
function irAlAccesoDelPersonal(router: Router, state: RouterStateSnapshot): UrlTree {
  const destino = destinoInternoSeguro(state.url);
  // Sin un destino propio ("/") no hay a dónde volver: el acceso entra por su pantalla de siempre.
  return destino === '/'
    ? router.createUrlTree([RUTA_LOGIN_PERSONAL])
    : router.createUrlTree([RUTA_LOGIN_PERSONAL], { queryParams: { returnTo: destino } });
}

export const authGuard: CanActivateFn = (_route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (authService.estaAutenticado()) {
    return true;
  }
  const coincidencia = PATRON_TIENDA.exec(state.url);
  if (coincidencia) {
    return router.createUrlTree(['/t', decodeURIComponent(coincidencia[1]), 'login'], {
      queryParams: { returnTo: state.url },
    });
  }
  return irAlAccesoDelPersonal(router, state);
};

/**
 * Va después de `authGuard` en las rutas privadas de /t/:codigo. La sesión es
 * de UNA empresa: si el comprador entra a otra tienda (o es superadministrador,
 * sin empresa), se cierra la sesión y se lo manda a ingresar en esta tienda.
 * Mirar el catálogo es público y nunca pasa por acá.
 */
export const tiendaSesionGuard: CanActivateFn = (_route, state) => {
  const authService = inject(AuthService);
  const tienda = inject(TiendaActualService);
  const router = inject(Router);

  const codigo = tienda.codigo();
  if (codigo === null) {
    return true;
  }
  if (!authService.estaAutenticado() || authService.empresaCodigo() === codigo) {
    return true;
  }

  authService.limpiarSesion();
  inject(CarritoService).limpiar();
  const nombre = tienda.empresa()?.nombre ?? codigo;
  inject(MessageService).add({
    severity: 'info',
    summary: 'Sesión cerrada',
    detail: `Cerramos tu sesión porque entraste a otra tienda. Ingresa con tu cuenta de ${nombre}.`,
  });
  return router.createUrlTree(['/t', codigo, 'login'], { queryParams: { returnTo: state.url } });
};

/** Guarda de ruta por permiso (p. ej. "roles.gestionar"). */
export function permisoGuard(permiso: string): CanActivateFn {
  return (_route, state) => {
    const authService = inject(AuthService);
    const router = inject(Router);

    if (!authService.estaAutenticado()) {
      return irAlAccesoDelPersonal(router, state);
    }
    if (!authService.tienePermiso(permiso)) {
      return router.parseUrl(authService.esSuperadmin() ? RUTA_INICIO_SUPERADMIN : RUTA_INICIO_PERSONAL);
    }
    return true;
  };
}

/** Guarda de ruta por permiso: hay que tener TODOS los permisos indicados (p. ej. `reportes.ver` y el alcance global). */
export function todosLosPermisosGuard(...permisos: string[]): CanActivateFn {
  return (_route, state) => {
    const authService = inject(AuthService);
    const router = inject(Router);

    if (!authService.estaAutenticado()) {
      return irAlAccesoDelPersonal(router, state);
    }
    if (!permisos.every((permiso) => authService.tienePermiso(permiso))) {
      return router.parseUrl(authService.esSuperadmin() ? RUTA_INICIO_SUPERADMIN : RUTA_INICIO_PERSONAL);
    }
    return true;
  };
}

/** Guarda de ruta por permiso: basta con tener CUALQUIERA de los permisos indicados. */
export function cualquierPermisoGuard(...permisos: string[]): CanActivateFn {
  return (_route, state) => {
    const authService = inject(AuthService);
    const router = inject(Router);

    if (!authService.estaAutenticado()) {
      return irAlAccesoDelPersonal(router, state);
    }
    if (!permisos.some((permiso) => authService.tienePermiso(permiso))) {
      return router.parseUrl(authService.esSuperadmin() ? RUTA_INICIO_SUPERADMIN : RUTA_INICIO_PERSONAL);
    }
    return true;
  };
}

/** Guarda de ruta por rol (basta con tener uno de los roles indicados). */
export function rolGuard(...roles: string[]): CanActivateFn {
  return (_route, state) => {
    const authService = inject(AuthService);
    const router = inject(Router);

    if (!authService.estaAutenticado()) {
      return irAlAccesoDelPersonal(router, state);
    }
    if (!authService.roles().some((rol) => roles.includes(rol))) {
      return router.parseUrl(authService.esSuperadmin() ? RUTA_INICIO_SUPERADMIN : RUTA_INICIO_PERSONAL);
    }
    return true;
  };
}

/**
 * Panel de la plataforma (/plataforma/...): solo el superadministrador. Un
 * administrador de empresa que escribe la URL termina en su dashboard.
 */
export const superadminGuard: CanActivateFn = (_route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (!authService.estaAutenticado()) {
    return irAlAccesoDelPersonal(router, state);
  }
  if (!authService.esSuperadmin()) {
    return router.parseUrl(RUTA_INICIO_PERSONAL);
  }
  return true;
};

/**
 * Protege la raíz del back office: un cliente autenticado (rol único
 * "cliente") nunca debe ver ninguna pantalla de administración, ni
 * escribiendo la URL a mano. Reemplaza a `authGuard` en esa ruta.
 *
 * El superadministrador (sin empresa) solo trabaja en /plataforma/...: si pide
 * una pantalla del back office de una empresa va a /plataforma/empresas.
 */
export const staffGuard: CanActivateFn = (_route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (!authService.estaAutenticado()) {
    return irAlAccesoDelPersonal(router, state);
  }
  if (authService.esSuperadmin()) {
    return PATRON_PLATAFORMA.test(state.url) ? true : router.parseUrl(RUTA_INICIO_SUPERADMIN);
  }
  const roles = authService.roles();
  // Sin ningún rol de staff (incluye roles.length === 0, un usuario
  // logueado cuya asignación de roles quedó desincronizada) no hay nada
  // que autorice el back office -- antes, roles.length === 0 caía al
  // `return true` final y dejaba entrar a cualquiera sin permisos reales.
  const esStaff = roles.some((rol) => rol !== 'cliente');
  if (!esStaff) {
    const ultima = inject(TiendaActualService).ultimaTienda();
    return router.createUrlTree(ultima ? ['/t', ultima] : ['/']);
  }
  return true;
};
