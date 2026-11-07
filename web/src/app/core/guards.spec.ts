import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, CanActivateFn, Router, RouterStateSnapshot, UrlTree, provideRouter } from '@angular/router';
import { MessageService } from 'primeng/api';
import { CLAVE_ULTIMA_TIENDA, TiendaActualService } from '../features/tienda/state/tienda-actual.service';
import { AuthService } from './auth.service';
import { UsuarioYo } from './models/seguridad.models';
import {
  authGuard,
  cualquierPermisoGuard,
  permisoGuard,
  rolGuard,
  staffGuard,
  superadminGuard,
  tiendaSesionGuard,
  todosLosPermisosGuard,
} from './guards';

function usuario(roles: string[], empresaCodigo: string | null): UsuarioYo {
  return {
    id: 1,
    nombre: 'Ana',
    apellido: 'Pérez',
    email: 'ana@example.com',
    telefono: null,
    activo: true,
    roles,
    permisos: [],
    empresa_id: empresaCodigo === null ? null : 7,
    empresa_codigo: empresaCodigo,
  };
}

describe('guards', () => {
  let auth: AuthService;
  let http: HttpTestingController;
  let router: Router;
  let mensajes: MessageService;

  const ruta = {} as ActivatedRouteSnapshot;
  const estado = (url: string) => ({ url }) as RouterStateSnapshot;
  const ejecutar = (guard: CanActivateFn, url: string) =>
    TestBed.runInInjectionContext(() => guard(ruta, estado(url)));

  function iniciarSesion(datos: UsuarioYo): void {
    auth.guardarTokens({ access_token: 'acceso', refresh_token: 'refresco' } as never);
    auth.cargarUsuarioActual().subscribe();
    http.expectOne((peticion) => peticion.url.endsWith('/auth/yo')).flush(datos);
  }

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting(), MessageService],
    });
    auth = TestBed.inject(AuthService);
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    mensajes = TestBed.inject(MessageService);
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
  });

  afterEach(() => localStorage.clear());

  describe('tiendaSesionGuard', () => {
    it('cierra la sesión de otra empresa y redirige al login de la tienda', () => {
      iniciarSesion(usuario(['cliente'], 'otra'));
      const agregar = vi.spyOn(mensajes, 'add');

      const resultado = ejecutar(tiendaSesionGuard, '/t/acme/carrito');

      expect(resultado).toBeInstanceOf(UrlTree);
      expect(router.serializeUrl(resultado as UrlTree)).toBe('/t/acme/login?returnTo=%2Ft%2Facme%2Fcarrito');
      expect(auth.estaAutenticado()).toBe(false);
      expect(auth.getAccessToken()).toBeNull();
      expect(agregar).toHaveBeenCalledWith(
        expect.objectContaining({
          severity: 'info',
          summary: 'Sesión cerrada',
          detail: 'Cerramos tu sesión porque entraste a otra tienda. Ingresa con tu cuenta de Acme.',
        }),
      );
    });

    it('cierra la sesión de un superadministrador (sin empresa)', () => {
      iniciarSesion(usuario(['superadministrador'], null));

      const resultado = ejecutar(tiendaSesionGuard, '/t/acme/mis-compras');

      expect(router.serializeUrl(resultado as UrlTree)).toBe('/t/acme/login?returnTo=%2Ft%2Facme%2Fmis-compras');
      expect(auth.estaAutenticado()).toBe(false);
    });

    it('deja pasar a quien tiene sesión de la misma empresa', () => {
      iniciarSesion(usuario(['cliente'], 'acme'));

      expect(ejecutar(tiendaSesionGuard, '/t/acme/carrito')).toBe(true);
      expect(auth.estaAutenticado()).toBe(true);
    });
  });

  describe('authGuard', () => {
    it('sin sesión en una tienda va al login de esa tienda', () => {
      const resultado = ejecutar(authGuard, '/t/acme/carrito?x=1');

      expect(router.serializeUrl(resultado as UrlTree)).toBe(
        '/t/acme/login?returnTo=%2Ft%2Facme%2Fcarrito%3Fx%3D1',
      );
    });

    it('sin sesión fuera de una tienda va a /admin/login', () => {
      const resultado = ejecutar(authGuard, '/dashboard');

      expect(router.serializeUrl(resultado as UrlTree)).toBe('/admin/login?returnTo=%2Fdashboard');
    });

    it('con sesión devuelve true', () => {
      iniciarSesion(usuario(['cliente'], 'acme'));

      expect(ejecutar(authGuard, '/t/acme/carrito')).toBe(true);
    });
  });

  describe('staffGuard', () => {
    it('manda al cliente a la última tienda', () => {
      localStorage.setItem(CLAVE_ULTIMA_TIENDA, 'acme');
      iniciarSesion(usuario(['cliente'], 'acme'));

      const resultado = ejecutar(staffGuard, '/dashboard');

      expect(router.serializeUrl(resultado as UrlTree)).toBe('/t/acme');
    });

    it('manda al cliente a / si no hay última tienda', () => {
      iniciarSesion(usuario(['cliente'], 'acme'));
      localStorage.removeItem(CLAVE_ULTIMA_TIENDA);

      const resultado = ejecutar(staffGuard, '/dashboard');

      expect(router.serializeUrl(resultado as UrlTree)).toBe('/');
    });

    it('deja pasar al staff', () => {
      iniciarSesion(usuario(['administrador'], 'acme'));

      expect(ejecutar(staffGuard, '/dashboard')).toBe(true);
    });

    it('sin sesión va a /admin/login y recuerda la pantalla que quería abrir (returnTo)', () => {
      const resultado = ejecutar(staffGuard, '/dashboard');

      expect(router.serializeUrl(resultado as UrlTree)).toBe('/admin/login?returnTo=%2Fdashboard');
    });

    it('sin sesión, el enlace del QR de un comprobante (/caja?venta=...) vuelve a la Caja con su venta tras entrar', () => {
      const resultado = ejecutar(staffGuard, '/caja?venta=VTA-0001') as UrlTree;

      expect(router.serializeUrl(resultado)).toBe('/admin/login?returnTo=%2Fcaja%3Fventa%3DVTA-0001');
      expect(resultado.queryParamMap.get('returnTo')).toBe('/caja?venta=VTA-0001');
    });

    it('un destino que no es una ruta interna no se recuerda (nunca otro sitio)', () => {
      for (const url of ['//otro.com/caja', 'https://otro.com/caja', '/\\otro.com']) {
        const resultado = ejecutar(staffGuard, url);
        expect(router.serializeUrl(resultado as UrlTree), url).toBe('/admin/login');
      }
    });

    it('manda al superadministrador que pide una pantalla del back office a /plataforma/empresas', () => {
      iniciarSesion(usuario(['superadministrador'], null));

      for (const url of ['/dashboard', '/caja', '/mi-empresa', '/']) {
        const resultado = ejecutar(staffGuard, url);
        expect(router.serializeUrl(resultado as UrlTree)).toBe('/plataforma/empresas');
      }
    });

    it('deja al superadministrador entrar a /plataforma/...', () => {
      iniciarSesion(usuario(['superadministrador'], null));

      expect(ejecutar(staffGuard, '/plataforma/empresas')).toBe(true);
      expect(ejecutar(staffGuard, '/plataforma/planes?x=1')).toBe(true);
    });

    it('no confunde /plataformas con /plataforma', () => {
      iniciarSesion(usuario(['superadministrador'], null));

      const resultado = ejecutar(staffGuard, '/plataformas');
      expect(router.serializeUrl(resultado as UrlTree)).toBe('/plataforma/empresas');
    });
  });

  describe('superadminGuard', () => {
    it('deja pasar al superadministrador', () => {
      iniciarSesion(usuario(['superadministrador'], null));

      expect(ejecutar(superadminGuard, '/plataforma/empresas')).toBe(true);
    });

    it('un administrador de empresa que escribe /plataforma/... termina en /dashboard', () => {
      iniciarSesion(usuario(['administrador'], 'acme'));

      const resultado = ejecutar(superadminGuard, '/plataforma/empresas');
      expect(router.serializeUrl(resultado as UrlTree)).toBe('/dashboard');
    });

    it('un cliente tampoco entra', () => {
      iniciarSesion(usuario(['cliente'], 'acme'));

      const resultado = ejecutar(superadminGuard, '/plataforma/empresas');
      expect(router.serializeUrl(resultado as UrlTree)).toBe('/dashboard');
    });

    it('sin sesión va a /admin/login con returnTo', () => {
      const resultado = ejecutar(superadminGuard, '/plataforma/empresas');

      expect(router.serializeUrl(resultado as UrlTree)).toBe('/admin/login?returnTo=%2Fplataforma%2Fempresas');
    });
  });

  describe('rolGuard', () => {
    it('sin sesión va a /admin/login con returnTo', () => {
      const resultado = ejecutar(rolGuard('administrador'), '/x');
      expect(router.serializeUrl(resultado as UrlTree)).toBe('/admin/login?returnTo=%2Fx');
    });

    it('deja pasar a quien tiene uno de los roles', () => {
      iniciarSesion(usuario(['cajero', 'encargado'], 'acme'));

      expect(ejecutar(rolGuard('administrador', 'encargado'), '/x')).toBe(true);
    });

    it('manda al dashboard a quien no tiene ninguno', () => {
      iniciarSesion(usuario(['cajero'], 'acme'));

      const resultado = ejecutar(rolGuard('administrador'), '/x');
      expect(router.serializeUrl(resultado as UrlTree)).toBe('/dashboard');
    });

    it('al superadministrador sin el rol pedido lo manda a su panel', () => {
      iniciarSesion(usuario(['superadministrador'], null));

      const resultado = ejecutar(rolGuard('administrador'), '/x');
      expect(router.serializeUrl(resultado as UrlTree)).toBe('/plataforma/empresas');
    });
  });

  describe('permisoGuard', () => {
    it('sin el permiso manda al dashboard', () => {
      iniciarSesion(usuario(['cajero'], 'acme'));

      const resultado = ejecutar(permisoGuard('empresa.gestionar'), '/mi-empresa');
      expect(router.serializeUrl(resultado as UrlTree)).toBe('/dashboard');
    });

    it('con el permiso deja pasar', () => {
      iniciarSesion({ ...usuario(['administrador'], 'acme'), permisos: ['empresa.gestionar'] });

      expect(ejecutar(permisoGuard('empresa.gestionar'), '/mi-empresa')).toBe(true);
    });

    it('sin sesión va a /admin/login con returnTo', () => {
      const resultado = ejecutar(permisoGuard('empresa.gestionar'), '/mi-empresa');
      expect(router.serializeUrl(resultado as UrlTree)).toBe('/admin/login?returnTo=%2Fmi-empresa');
    });

    it('sin sesión conserva la query del destino (la Caja del QR)', () => {
      const resultado = ejecutar(permisoGuard('ventas.presencial'), '/caja?venta=VTA-0001');
      expect(router.serializeUrl(resultado as UrlTree)).toBe('/admin/login?returnTo=%2Fcaja%3Fventa%3DVTA-0001');
    });
  });

  describe('cualquierPermisoGuard', () => {
    const guardia = () => cualquierPermisoGuard('ventas.presencial', 'reservas.gestionar_sucursal');

    it('deja pasar con el primero de los permisos', () => {
      iniciarSesion({ ...usuario(['cajero'], 'acme'), permisos: ['ventas.presencial'] });

      expect(ejecutar(guardia(), '/catalogo-local')).toBe(true);
    });

    it('deja pasar con solo el segundo de los permisos', () => {
      iniciarSesion({ ...usuario(['encargado'], 'acme'), permisos: ['reservas.gestionar_sucursal'] });

      expect(ejecutar(guardia(), '/catalogo-local')).toBe(true);
    });

    it('sin ninguno de los permisos (aunque tenga otros) manda al dashboard', () => {
      iniciarSesion({ ...usuario(['encargado'], 'acme'), permisos: ['inventario.ver', 'reportes.ver'] });

      const resultado = ejecutar(guardia(), '/catalogo-local');
      expect(router.serializeUrl(resultado as UrlTree)).toBe('/dashboard');
    });

    it('tener un permiso que no está en la lista no basta', () => {
      iniciarSesion({ ...usuario(['cajero'], 'acme'), permisos: ['ventas.presencial'] });

      const resultado = ejecutar(cualquierPermisoGuard('empresa.gestionar', 'roles.gestionar'), '/x');
      expect(router.serializeUrl(resultado as UrlTree)).toBe('/dashboard');
    });

    it('el superadministrador sin esos permisos va a su panel', () => {
      iniciarSesion({ ...usuario(['superadministrador'], null), permisos: ['plataforma.gestionar'] });

      const resultado = ejecutar(guardia(), '/catalogo-local');
      expect(router.serializeUrl(resultado as UrlTree)).toBe('/plataforma/empresas');
    });

    it('sin sesión va a /admin/login con returnTo', () => {
      const resultado = ejecutar(guardia(), '/catalogo-local');
      expect(router.serializeUrl(resultado as UrlTree)).toBe('/admin/login?returnTo=%2Fcatalogo-local');
    });
  });

  describe('todosLosPermisosGuard (Analítica: reportes.ver y alcance global)', () => {
    const guardia = () => todosLosPermisosGuard('reportes.ver', 'organizacion.gestionar');

    it('el administrador (tiene los dos permisos) pasa', () => {
      iniciarSesion({ ...usuario(['administrador'], 'acme'), permisos: ['reportes.ver', 'organizacion.gestionar'] });

      expect(ejecutar(guardia(), '/analitica')).toBe(true);
    });

    it('un encargado con solo reportes.ver va al dashboard, ni escribiendo la URL entra', () => {
      iniciarSesion({ ...usuario(['encargado_sucursal'], 'acme'), permisos: ['reportes.ver'] });

      const resultado = ejecutar(guardia(), '/analitica');
      expect(router.serializeUrl(resultado as UrlTree)).toBe('/dashboard');
    });

    it('con solo el alcance global pero sin reportes.ver tampoco pasa', () => {
      iniciarSesion({ ...usuario(['administrador'], 'acme'), permisos: ['organizacion.gestionar'] });

      const resultado = ejecutar(guardia(), '/analitica');
      expect(router.serializeUrl(resultado as UrlTree)).toBe('/dashboard');
    });

    it('sin sesión va a /admin/login con returnTo', () => {
      const resultado = ejecutar(guardia(), '/analitica');
      expect(router.serializeUrl(resultado as UrlTree)).toBe('/admin/login?returnTo=%2Fanalitica');
    });
  });
});
