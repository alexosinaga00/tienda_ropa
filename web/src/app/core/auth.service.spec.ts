import 'fake-indexeddb/auto';
import { HttpClient, HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { Subject, firstValueFrom } from 'rxjs';
import { environment } from '../../environments/environment';
import { TiendaActualService } from '../features/tienda/state/tienda-actual.service';
import { AuthService } from './auth.service';
import { ConectividadService } from './conectividad.service';
import { SIN_RENOVAR_SESION } from './http-contexts';
import type { UsuarioYo } from './models/seguridad.models';
import { AlmacenOfflineService } from './offline/almacen-offline.service';
import { BaseOffline } from './offline/db-offline';
import { SesionOfflineService } from './offline/sesion-offline.service';

const API = environment.apiUrl;

let contadorBases = 0;

describe('AuthService (tienda por empresa)', () => {
  let auth: AuthService;
  let tienda: TiendaActualService;
  let http: HttpTestingController;
  let router: Router;
  let base: BaseOffline;
  let volvioConexion: Subject<void>;

  /** Los mismos proveedores cada vez, con una base IndexedDB propia por prueba y la conectividad controlada. */
  function configurar(): void {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AlmacenOfflineService, useValue: Object.assign(new AlmacenOfflineService(), { base }) },
        { provide: ConectividadService, useValue: { volvioConexion$: volvioConexion.asObservable() } },
      ],
    });
    auth = TestBed.inject(AuthService);
    tienda = TestBed.inject(TiendaActualService);
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
  }

  beforeEach(() => {
    localStorage.clear();
    base = new BaseOffline(`prueba-auth-${++contadorBases}`);
    volvioConexion = new Subject<void>();
    configurar();
  });

  afterEach(async () => {
    vi.restoreAllMocks();
    localStorage.clear();
    http.verify();
    await base.delete();
  });

  function fijarAcme(): void {
    tienda.fijar('acme', 'lista', { codigo: 'acme', nombre: 'Acme', logo_url: null, color_acento: null });
  }

  describe('login', () => {
    it('manda la empresa en el cuerpo cuando viene', () => {
      auth.login('a@b.com', 'secreto123', 'acme').subscribe();
      const req = http.expectOne(`${API}/auth/login`);
      expect(req.request.body).toEqual({ empresa: 'acme', email: 'a@b.com', password: 'secreto123' });
      req.flush({ access_token: 'a', refresh_token: 'r', token_type: 'bearer' });
    });

    it('sin tercer parámetro NO manda el campo empresa', () => {
      auth.login('a@b.com', 'secreto123').subscribe();
      const req = http.expectOne(`${API}/auth/login`);
      expect(req.request.body).toEqual({ email: 'a@b.com', password: 'secreto123' });
      expect('empresa' in req.request.body).toBe(false);
      req.flush({ access_token: 'a', refresh_token: 'r', token_type: 'bearer' });
    });

    it('con empresa vacía o null tampoco manda el campo', () => {
      auth.login('a@b.com', 'x', '').subscribe();
      auth.login('a@b.com', 'x', null).subscribe();
      const reqs = http.match(`${API}/auth/login`);
      expect(reqs).toHaveLength(2);
      for (const req of reqs) {
        expect('empresa' in req.request.body).toBe(false);
        req.flush({ access_token: 'a', refresh_token: 'r', token_type: 'bearer' });
      }
    });
  });

  describe('esSuperadmin y esSoloCliente', () => {
    function iniciarSesion(roles: string[], empresaId: number | null | undefined): void {
      auth.guardarTokens({ access_token: 'a', refresh_token: 'r', token_type: 'bearer' });
      auth.cargarUsuarioActual().subscribe();
      http.expectOne(`${API}/auth/yo`).flush({
        id: 1,
        nombre: 'Ana',
        apellido: 'Paz',
        email: 'a@b.com',
        telefono: null,
        activo: true,
        roles,
        permisos: [],
        ...(empresaId === undefined ? {} : { empresa_id: empresaId }),
      });
    }

    it('sin sesión no es superadministrador', () => {
      expect(auth.esSuperadmin()).toBe(false);
      expect(auth.esSoloCliente()).toBe(false);
    });

    it('es superadministrador por el rol', () => {
      iniciarSesion(['superadministrador'], 7);
      expect(auth.esSuperadmin()).toBe(true);
    });

    it('es superadministrador si la sesión no tiene empresa (empresa_id null)', () => {
      iniciarSesion(['administrador'], null);
      expect(auth.esSuperadmin()).toBe(true);
    });

    it('el administrador de una empresa no lo es', () => {
      iniciarSesion(['administrador'], 7);
      expect(auth.esSuperadmin()).toBe(false);
    });

    it('si /auth/yo no trae empresa_id (undefined) no se lo trata como superadministrador', () => {
      iniciarSesion(['cajero'], undefined);
      expect(auth.esSuperadmin()).toBe(false);
    });

    it('esSoloCliente solo con el rol cliente', () => {
      iniciarSesion(['cliente'], 7);
      expect(auth.esSoloCliente()).toBe(true);
    });

    it('un usuario con cliente y otro rol no es solo cliente', () => {
      iniciarSesion(['cliente', 'cajero'], 7);
      expect(auth.esSoloCliente()).toBe(false);
    });
  });

  it('registrar usa /public/{codigo}/registro', () => {
    const datos = { nombre: 'Ana', apellido: 'Paz', email: 'ana@b.com', telefono: null, ci_nit: null, password: 'secreto123' };
    auth.registrar(datos, 'acme').subscribe();
    const req = http.expectOne(`${API}/public/acme/registro`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(datos);
    req.flush({});
  });

  describe('solicitarRecuperacion', () => {
    it('manda la empresa cuando viene', () => {
      auth.solicitarRecuperacion('a@b.com', 'acme').subscribe();
      const req = http.expectOne(`${API}/auth/recuperar`);
      expect(req.request.body).toEqual({ email: 'a@b.com', empresa: 'acme' });
      req.flush({ detail: 'ok' });
    });

    it('sin empresa manda solo el email', () => {
      auth.solicitarRecuperacion('a@b.com').subscribe();
      const req = http.expectOne(`${API}/auth/recuperar`);
      expect(req.request.body).toEqual({ email: 'a@b.com' });
      req.flush({ detail: 'ok' });
    });
  });

  it('confirmarRecuperacion manda solo token y password (sin empresa)', () => {
    auth.confirmarRecuperacion('tok', 'nueva1234').subscribe();
    const req = http.expectOne(`${API}/auth/recuperar/confirmar`);
    expect(req.request.body).toEqual({ token: 'tok', password: 'nueva1234' });
    req.flush({ detail: 'ok' });
  });

  describe('logout', () => {
    it('dentro de una tienda navega a /t/acme/login', () => {
      fijarAcme();
      const navegar = vi.spyOn(router, 'navigate').mockResolvedValue(true);
      auth.logout();
      expect(navegar).toHaveBeenCalledWith(['/t', 'acme', 'login']);
    });

    it('sin tienda navega a /admin/login', () => {
      const navegar = vi.spyOn(router, 'navigate').mockResolvedValue(true);
      auth.logout();
      expect(navegar).toHaveBeenCalledWith(['/admin/login']);
    });

    it('limpia los tokens guardados', () => {
      localStorage.setItem('fs_access_token', 'a');
      localStorage.setItem('fs_refresh_token', 'r');
      vi.spyOn(router, 'navigate').mockResolvedValue(true);
      auth.logout();
      expect(localStorage.getItem('fs_access_token')).toBeNull();
      expect(localStorage.getItem('fs_refresh_token')).toBeNull();
    });

    describe('avisos push del navegador', () => {
      afterEach(() => localStorage.removeItem('fs_push_web_token'));

      it('con avisos activados da de baja el token ANTES de borrar la sesión (con su token de acceso), sin renovarla', () => {
        localStorage.setItem('fs_access_token', 'acceso');
        localStorage.setItem('fs_refresh_token', 'refresco');
        localStorage.setItem('fs_push_web_token', 'tok-web');
        vi.spyOn(router, 'navigate').mockResolvedValue(true);
        // En este instante (cuando el interceptor agregaría el Authorization) la sesión todavía tiene su token de acceso.
        let accesoAlSalirLaBaja: string | null = null;
        const cliente = TestBed.inject(HttpClient);
        const publicar = cliente.post.bind(cliente);
        vi.spyOn(cliente, 'post').mockImplementation(((...args: Parameters<HttpClient['post']>) => {
          accesoAlSalirLaBaja = auth.getAccessToken();
          return publicar(...args);
        }) as HttpClient['post']);

        auth.logout();

        const baja = http.expectOne(`${API}/dispositivos-push/baja`);
        expect(baja.request.method).toBe('POST');
        expect(baja.request.body).toEqual({ token: 'tok-web' });
        expect(accesoAlSalirLaBaja).toBe('acceso');
        expect(baja.request.context.get(SIN_RENOVAR_SESION)).toBe(true);
        expect(localStorage.getItem('fs_access_token')).toBeNull();
        baja.flush(null, { status: 204, statusText: 'No Content' });
      });

      it('si la baja falla, salir funciona igual', () => {
        localStorage.setItem('fs_push_web_token', 'tok-web');
        const navegar = vi.spyOn(router, 'navigate').mockResolvedValue(true);

        auth.logout();
        http.expectOne(`${API}/dispositivos-push/baja`).flush({ detail: 'x' }, { status: 401, statusText: 'Unauthorized' });

        expect(navegar).toHaveBeenCalled();
        expect(auth.estaAutenticado()).toBe(false);
      });

      it('sin avisos activados no manda ninguna baja', () => {
        vi.spyOn(router, 'navigate').mockResolvedValue(true);
        auth.logout();
        http.expectNone(`${API}/dispositivos-push/baja`);
      });
    });
  });

  describe('modo sin conexión (E14a)', () => {
    const CLAVE_ALCANCE = 'fs_offline_sesion';
    const TOKENS = { access_token: 'a', refresh_token: 'r', token_type: 'bearer' };

    function yo(id = 5, empresaId: number | null = 7, roles: string[] = ['cajero'], permisos: string[] = ['ventas.crear']): UsuarioYo {
      return {
        id,
        nombre: 'Ana',
        apellido: 'Paz',
        email: 'ana@b.com',
        telefono: null,
        activo: true,
        roles,
        permisos,
        empresa_id: empresaId,
        empresa_codigo: 'acme',
        empresa_nombre: 'Acme',
      };
    }

    /** Simula "reabrir la app": servicios nuevos, pero con el mismo localStorage y la misma base IndexedDB. */
    function reabrirLaApp(): void {
      TestBed.resetTestingModule();
      configurar();
    }

    /** Inicia sesión como lo hace la app y espera a que el perfil quede guardado en IndexedDB. */
    async function iniciarSesionConPerfil(usuario: UsuarioYo): Promise<void> {
      auth.guardarTokens(TOKENS);
      auth.cargarUsuarioActual().subscribe();
      http.expectOne(`${API}/auth/yo`).flush(usuario);
      const sesion = TestBed.inject(SesionOfflineService);
      await vi.waitFor(async () => {
        expect(await sesion.perfilGuardado(usuario.empresa_id as number, usuario.id)).toEqual(usuario);
      });
    }

    /** Lanza restaurarSesion() y devuelve lo que ocurrió (el resultado o el error), sin dejar rechazos sueltos. */
    function restaurar(): Promise<{ usuario?: UsuarioYo; error?: unknown }> {
      const flujo = auth.restaurarSesion();
      expect(flujo).not.toBeNull();
      return firstValueFrom(flujo!).then(
        (usuario) => ({ usuario }),
        (error: unknown) => ({ error }),
      );
    }

    function sinRed(): void {
      http.expectOne(`${API}/auth/yo`).error(new ProgressEvent('error'), { status: 0, statusText: 'Unknown Error' });
    }

    describe('al cargar el usuario', () => {
      it('guarda el perfil y el alcance mínimo (solo empresa y usuario) para poder reabrir sin red', async () => {
        await iniciarSesionConPerfil(yo(5, 7));
        expect(JSON.parse(localStorage.getItem(CLAVE_ALCANCE) as string)).toEqual({ empresaId: 7, usuarioId: 5 });
      });

      it('el superadministrador no deja alcance ni perfil', async () => {
        auth.guardarTokens(TOKENS);
        auth.cargarUsuarioActual().subscribe();
        http.expectOne(`${API}/auth/yo`).flush(yo(1, null, ['superadministrador']));
        await new Promise((r) => setTimeout(r, 20));
        expect(localStorage.getItem(CLAVE_ALCANCE)).toBeNull();
        expect(await base.meta.count()).toBe(0);
      });

      it('si guardar el perfil falla, el inicio de sesión sigue y el error solo va a la consola', async () => {
        const aviso = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
        vi.spyOn(SesionOfflineService.prototype, 'alIniciarSesion').mockRejectedValue(new Error('IndexedDB no disponible'));
        auth.guardarTokens(TOKENS);
        let fallo: unknown = null;
        auth.cargarUsuarioActual().subscribe({ error: (e) => (fallo = e) });
        http.expectOne(`${API}/auth/yo`).flush(yo());

        expect(fallo).toBeNull();
        expect(auth.estaAutenticado()).toBe(true);
        await vi.waitFor(() => expect(aviso).toHaveBeenCalled());
      });

      it('un login nuevo descarta el alcance de la sesión anterior hasta cargar al usuario', () => {
        localStorage.setItem(CLAVE_ALCANCE, JSON.stringify({ empresaId: 7, usuarioId: 5 }));
        auth.login('b@b.com', 'secreto123', 'acme').subscribe();
        http.expectOne(`${API}/auth/login`).flush(TOKENS);
        expect(localStorage.getItem(CLAVE_ALCANCE)).toBeNull();
      });
    });

    describe('restaurarSesion', () => {
      it('sin tokens devuelve null (como siempre)', () => {
        expect(auth.restaurarSesion()).toBeNull();
      });

      it('con red restaura al usuario desde /auth/yo y NO queda sin verificar', async () => {
        auth.guardarTokens(TOKENS);
        const resultado = restaurar();
        http.expectOne(`${API}/auth/yo`).flush(yo());
        expect((await resultado).usuario?.id).toBe(5);
        expect(auth.sesionSinVerificar()).toBe(false);
        expect(auth.estaAutenticado()).toBe(true);
      });

      it('sin red (status 0) y con perfil guardado restaura la sesión desde el perfil y la marca sin verificar', async () => {
        const perfil = yo(5, 7, ['cajero'], ['ventas.crear', 'reservas.crear']);
        await iniciarSesionConPerfil(perfil);
        reabrirLaApp();
        expect(auth.usuario()).toBeNull();

        const resultado = restaurar();
        sinRed();
        const { usuario, error } = await resultado;

        expect(error).toBeUndefined();
        expect(usuario).toEqual(perfil);
        expect(auth.usuario()).toEqual(perfil);
        expect(auth.estaAutenticado()).toBe(true);
        expect(auth.permisos()).toEqual(['ventas.crear', 'reservas.crear']);
        expect(auth.empresaId()).toBe(7);
        expect(auth.sesionSinVerificar()).toBe(true);
        // Los tokens no se tocan.
        expect(localStorage.getItem('fs_access_token')).toBe('a');
        expect(localStorage.getItem('fs_refresh_token')).toBe('r');
      });

      it('con 401 propaga el error y deja la sesión nula (como hoy), aunque haya perfil guardado', async () => {
        await iniciarSesionConPerfil(yo());
        reabrirLaApp();

        const resultado = restaurar();
        http.expectOne(`${API}/auth/yo`).flush({ detail: 'No autorizado' }, { status: 401, statusText: 'Unauthorized' });
        const { usuario, error } = await resultado;

        expect(usuario).toBeUndefined();
        expect((error as HttpErrorResponse).status).toBe(401);
        expect(auth.usuario()).toBeNull();
        expect(auth.sesionSinVerificar()).toBe(false);
      });

      it('con 403 tampoco restaura desde el perfil', async () => {
        await iniciarSesionConPerfil(yo());
        reabrirLaApp();

        const resultado = restaurar();
        http.expectOne(`${API}/auth/yo`).flush({ detail: 'Prohibido' }, { status: 403, statusText: 'Forbidden' });
        const { error } = await resultado;

        expect((error as HttpErrorResponse).status).toBe(403);
        expect(auth.usuario()).toBeNull();
        expect(auth.sesionSinVerificar()).toBe(false);
      });

      it('con un error del servidor (500) no restaura desde el perfil: solo la falta de red lo hace', async () => {
        await iniciarSesionConPerfil(yo());
        reabrirLaApp();

        const resultado = restaurar();
        http.expectOne(`${API}/auth/yo`).flush({}, { status: 500, statusText: 'Server Error' });
        const { error } = await resultado;

        expect((error as HttpErrorResponse).status).toBe(500);
        expect(auth.usuario()).toBeNull();
      });

      it('sin red y SIN perfil guardado se comporta como hoy: error y sesión nula', async () => {
        auth.guardarTokens(TOKENS);
        const resultado = restaurar();
        sinRed();
        const { usuario, error } = await resultado;

        expect(usuario).toBeUndefined();
        expect((error as HttpErrorResponse).status).toBe(0);
        expect(auth.usuario()).toBeNull();
        expect(auth.sesionSinVerificar()).toBe(false);
      });

      it('sin red, con alcance recordado pero sin perfil de ESE usuario no restaura', async () => {
        await iniciarSesionConPerfil(yo(5, 7));
        reabrirLaApp();
        // El alcance apunta a otro usuario de la misma empresa que nunca guardó perfil.
        localStorage.setItem(CLAVE_ALCANCE, JSON.stringify({ empresaId: 7, usuarioId: 6 }));

        const resultado = restaurar();
        sinRed();
        const { error } = await resultado;

        expect((error as HttpErrorResponse).status).toBe(0);
        expect(auth.usuario()).toBeNull();
        expect(auth.sesionSinVerificar()).toBe(false);
      });

      it('sin red, con un alcance corrupto en localStorage no restaura ni lanza otra cosa', async () => {
        await iniciarSesionConPerfil(yo());
        reabrirLaApp();
        localStorage.setItem(CLAVE_ALCANCE, '{no es json');

        const resultado = restaurar();
        sinRed();
        const { error } = await resultado;

        expect((error as HttpErrorResponse).status).toBe(0);
        expect(auth.usuario()).toBeNull();
      });

      it('sin red, si el perfil guardado no coincide con el alcance (otra empresa) no restaura', async () => {
        await iniciarSesionConPerfil(yo(5, 7));
        reabrirLaApp();
        // El perfil de 5 está en la empresa 7; con la empresa 8 no hay nada (aislamiento por empresa).
        localStorage.setItem(CLAVE_ALCANCE, JSON.stringify({ empresaId: 8, usuarioId: 5 }));

        const resultado = restaurar();
        sinRed();
        const { error } = await resultado;

        expect((error as HttpErrorResponse).status).toBe(0);
        expect(auth.usuario()).toBeNull();
      });

      it('sin red, sin el token de refresco no restaura (la sesión no se podría mantener)', async () => {
        await iniciarSesionConPerfil(yo());
        reabrirLaApp();
        localStorage.removeItem('fs_refresh_token');

        const resultado = restaurar();
        sinRed();
        const { error } = await resultado;

        expect((error as HttpErrorResponse).status).toBe(0);
        expect(auth.usuario()).toBeNull();
      });
    });

    describe('al volver la conexión', () => {
      async function restaurarSinRed(perfil: UsuarioYo): Promise<void> {
        await iniciarSesionConPerfil(perfil);
        reabrirLaApp();
        const resultado = restaurar();
        sinRed();
        await resultado;
        expect(auth.sesionSinVerificar()).toBe(true);
      }

      it('verifica la sesión con /auth/yo, actualiza el usuario y quita la marca', async () => {
        await restaurarSinRed(yo(5, 7, ['cajero'], ['ventas.crear']));

        volvioConexion.next();
        http.expectOne(`${API}/auth/yo`).flush(yo(5, 7, ['cajero'], ['ventas.crear', 'reportes.ver']));

        expect(auth.sesionSinVerificar()).toBe(false);
        expect(auth.permisos()).toEqual(['ventas.crear', 'reportes.ver']);
        expect(auth.estaAutenticado()).toBe(true);
      });

      it('si el servidor responde 401, cierra la sesión', async () => {
        await restaurarSinRed(yo());
        const navegar = vi.spyOn(router, 'navigate').mockResolvedValue(true);

        volvioConexion.next();
        http.expectOne(`${API}/auth/yo`).flush({ detail: 'No autorizado' }, { status: 401, statusText: 'Unauthorized' });

        expect(auth.usuario()).toBeNull();
        expect(auth.sesionSinVerificar()).toBe(false);
        expect(localStorage.getItem('fs_access_token')).toBeNull();
        expect(navegar).toHaveBeenCalledTimes(1);
      });

      it('si todavía no hay red (status 0), la sesión sigue restaurada y sin verificar', async () => {
        await restaurarSinRed(yo());
        const navegar = vi.spyOn(router, 'navigate').mockResolvedValue(true);

        volvioConexion.next();
        sinRed();

        expect(auth.estaAutenticado()).toBe(true);
        expect(auth.sesionSinVerificar()).toBe(true);
        expect(localStorage.getItem('fs_access_token')).toBe('a');
        expect(navegar).not.toHaveBeenCalled();

        // Y en la siguiente recuperación se vuelve a intentar.
        volvioConexion.next();
        http.expectOne(`${API}/auth/yo`).flush(yo());
        expect(auth.sesionSinVerificar()).toBe(false);
      });

      it('si la sesión no estaba restaurada sin red, volver la conexión no pide nada', async () => {
        await iniciarSesionConPerfil(yo());
        volvioConexion.next();
        http.expectNone(`${API}/auth/yo`);
        expect(auth.sesionSinVerificar()).toBe(false);
      });
    });

    describe('logout', () => {
      it('borra los clientes y el perfil del usuario, y conserva catálogo y operaciones', async () => {
        await iniciarSesionConPerfil(yo(5, 7));
        await base.productos.put({
          empresa_id: 7,
          id: 1,
          codigo: 'P-1',
          nombre: 'Polera',
          nombre_norm: 'polera',
          categoria_id: 1,
          genero: 'hombre',
          temporada_id: null,
          imagen_principal: null,
        });
        await base.clientes_minimos.put({ empresa_id: 7, id: 1, nombre: 'Ana', apellido: 'Paz', ci_nit: '1', nombre_norm: 'ana paz' });
        await base.operaciones_pendientes.put({
          empresa_id: 7,
          usuario_id: 5,
          operacion_id: 'op-1',
          tipo: 'venta_contado',
          estado: 'registrada',
          fecha_operacion: '2026-10-30T10:00:00-04:00',
        });
        vi.spyOn(router, 'navigate').mockResolvedValue(true);

        auth.logout();

        // El alcance se tomó ANTES de limpiar el usuario: de lo contrario no se borraría nada.
        expect(auth.usuario()).toBeNull();
        await vi.waitFor(async () => {
          expect(await base.clientes_minimos.count()).toBe(0);
          expect(await base.meta.count()).toBe(0);
        });
        expect(await base.productos.count()).toBe(1);
        expect(await base.operaciones_pendientes.count()).toBe(1);
        expect(localStorage.getItem(CLAVE_ALCANCE)).toBeNull();
      });

      it('si limpiar el almacenamiento local falla, igual cierra la sesión y navega', async () => {
        await iniciarSesionConPerfil(yo());
        const aviso = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
        vi.spyOn(SesionOfflineService.prototype, 'alCerrarSesion').mockRejectedValue(new Error('IndexedDB no disponible'));
        const navegar = vi.spyOn(router, 'navigate').mockResolvedValue(true);

        auth.logout();

        expect(auth.usuario()).toBeNull();
        expect(localStorage.getItem('fs_access_token')).toBeNull();
        expect(navegar).toHaveBeenCalledTimes(1);
        await vi.waitFor(() => expect(aviso).toHaveBeenCalled());
      });
    });
  });
});
