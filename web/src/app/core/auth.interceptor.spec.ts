import { HttpClient, HttpContext, HttpErrorResponse, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { environment } from '../../environments/environment';
import { authInterceptor } from './auth.interceptor';
import { AuthService } from './auth.service';
import { SIN_RENOVAR_SESION } from './http-contexts';

describe('authInterceptor', () => {
  let http: HttpClient;
  let controller: HttpTestingController;

  beforeEach(() => {
    localStorage.setItem('fs_access_token', 'token-de-prueba');
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    controller = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    controller.verify();
    localStorage.clear();
  });

  it('no manda Authorization a las rutas públicas de una tienda', () => {
    http.get(`${environment.apiUrl}/public/acme/catalogo`).subscribe();
    const req = controller.expectOne(`${environment.apiUrl}/public/acme/catalogo`);
    expect(req.request.headers.has('Authorization')).toBe(false);
    req.flush([]);
  });

  it('manda Authorization a una ruta privada', () => {
    http.get(`${environment.apiUrl}/carrito`).subscribe();
    const req = controller.expectOne(`${environment.apiUrl}/carrito`);
    expect(req.request.headers.get('Authorization')).toBe('Bearer token-de-prueba');
    req.flush({});
  });

  describe('401 y refresco de tokens', () => {
    const URL_PRIVADA = `${environment.apiUrl}/carrito`;
    const URL_REFRESH = `${environment.apiUrl}/auth/refresh`;
    let logout: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
      localStorage.setItem('fs_refresh_token', 'refresh-de-prueba');
      logout = vi.spyOn(TestBed.inject(AuthService), 'logout').mockImplementation(() => undefined);
    });

    /** Lanza una petición privada y deja resuelto el 401 inicial; devuelve lo que recibe quien la hizo. */
    function peticionConRefreshPendiente(): { resultado: () => { valor?: unknown; error?: unknown; termino: boolean } } {
      let estado: { valor?: unknown; error?: unknown; termino: boolean } = { termino: false };
      http.get(URL_PRIVADA).subscribe({
        next: (valor) => (estado = { valor, termino: true }),
        error: (error) => (estado = { error, termino: true }),
      });
      controller.expectOne(URL_PRIVADA).flush({}, { status: 401, statusText: 'Unauthorized' });
      return { resultado: () => estado };
    }

    it('si el refresh falla SIN RED (status 0) NO cierra la sesión y propaga el error original', () => {
      const { resultado } = peticionConRefreshPendiente();
      controller.expectOne(URL_REFRESH).error(new ProgressEvent('error'), { status: 0, statusText: 'Unknown Error' });

      expect(logout).not.toHaveBeenCalled();
      expect(resultado().termino).toBe(true);
      expect(resultado().error).toBeInstanceOf(HttpErrorResponse);
      expect((resultado().error as HttpErrorResponse).status).toBe(0);
      // Los tokens siguen guardados: al volver la red se podrá refrescar.
      expect(localStorage.getItem('fs_access_token')).toBe('token-de-prueba');
      expect(localStorage.getItem('fs_refresh_token')).toBe('refresh-de-prueba');
    });

    it('si el refresh responde 401 cierra la sesión y propaga ese error', () => {
      const { resultado } = peticionConRefreshPendiente();
      controller.expectOne(URL_REFRESH).flush({ detail: 'Token inválido' }, { status: 401, statusText: 'Unauthorized' });

      expect(logout).toHaveBeenCalledTimes(1);
      expect((resultado().error as HttpErrorResponse).status).toBe(401);
    });

    it('una petición marcada SIN_RENOVAR_SESION que recibe 401 propaga el error sin intentar renovar ni cerrar la sesión', () => {
      let error: unknown;
      http
        .post(`${environment.apiUrl}/dispositivos-push/baja`, { token: 't' }, { context: new HttpContext().set(SIN_RENOVAR_SESION, true) })
        .subscribe({ error: (e) => (error = e) });
      controller
        .expectOne(`${environment.apiUrl}/dispositivos-push/baja`)
        .flush({}, { status: 401, statusText: 'Unauthorized' });

      controller.expectNone(URL_REFRESH);
      expect(logout).not.toHaveBeenCalled();
      expect((error as HttpErrorResponse).status).toBe(401);
    });

    it('si el refresh responde 403 también cierra la sesión', () => {
      const { resultado } = peticionConRefreshPendiente();
      controller.expectOne(URL_REFRESH).flush({ detail: 'Prohibido' }, { status: 403, statusText: 'Forbidden' });

      expect(logout).toHaveBeenCalledTimes(1);
      expect((resultado().error as HttpErrorResponse).status).toBe(403);
    });

    it('si el refresh funciona, reintenta la petición con el token nuevo y no cierra la sesión', () => {
      const { resultado } = peticionConRefreshPendiente();
      controller
        .expectOne(URL_REFRESH)
        .flush({ access_token: 'token-nuevo', refresh_token: 'refresh-nuevo', token_type: 'bearer' });

      const reintento = controller.expectOne(URL_PRIVADA);
      expect(reintento.request.headers.get('Authorization')).toBe('Bearer token-nuevo');
      reintento.flush({ ok: true });

      expect(logout).not.toHaveBeenCalled();
      expect(resultado().valor).toEqual({ ok: true });
    });
  });
});
