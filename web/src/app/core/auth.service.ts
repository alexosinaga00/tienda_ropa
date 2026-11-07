import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, Injector, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, Subscription, catchError, finalize, from, of, shareReplay, switchMap, tap, throwError } from 'rxjs';
import { environment } from '../../environments/environment';
import { TiendaActualService } from '../features/tienda/state/tienda-actual.service';
import { ConectividadService } from './conectividad.service';
import { RecuperarRespuesta, RegistroRequest, TokenRespuesta, Usuario, UsuarioYo } from './models/seguridad.models';
import { SesionOfflineService } from './offline/sesion-offline.service';
import type { ClienteOfflineService as ClienteOfflineServicio } from './offline-cliente/cliente-offline.service';

const CLAVE_ACCESS_TOKEN = 'fs_access_token';
const CLAVE_REFRESH_TOKEN = 'fs_refresh_token';
/**
 * Copia mínima del alcance de la última sesión ({empresaId, usuarioId}: dos enteros, ningún secreto). Al arrancar sin
 * red todavía no hay usuario, y el perfil guardado en IndexedDB se busca por esa pareja. Se escribe al cargar el
 * usuario y se borra al limpiar la sesión.
 */
const CLAVE_ALCANCE_SESION = 'fs_offline_sesion';

/** Rol global del superadministrador de la plataforma (`core/permisos.py`). */
export const ROL_SUPERADMINISTRADOR = 'superadministrador';

/** Entrada del personal (administrador, encargado, cajero y superadministrador). */
export const RUTA_LOGIN_PERSONAL = '/admin/login';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly usuarioActual = signal<UsuarioYo | null>(null);
  private refrescoEnCurso$: Observable<TokenRespuesta> | null = null;
  private suscripcionVerificacion: Subscription | null = null;
  private readonly sinVerificar = signal(false);

  /**
   * La sesión se restauró sin red desde el perfil guardado y el servidor aún no la confirmó (E14). Vuelve a false al
   * confirmarla (al volver la conexión) o al cerrar la sesión.
   */
  readonly sesionSinVerificar = this.sinVerificar.asReadonly();
  readonly usuario = this.usuarioActual.asReadonly();
  readonly estaAutenticado = computed(() => this.usuarioActual() !== null);
  readonly permisos = computed(() => this.usuarioActual()?.permisos ?? []);
  readonly roles = computed(() => this.usuarioActual()?.roles ?? []);
  /** Empresa de la sesión (null = sin sesión o superadministrador de la plataforma). */
  readonly empresaId = computed(() => this.usuarioActual()?.empresa_id ?? null);
  /** Código de la empresa de la sesión: lo que se compara con la tienda actual (/t/:codigo). */
  readonly empresaCodigo = computed(() => this.usuarioActual()?.empresa_codigo ?? null);
  /** Superadministrador de la plataforma: rol propio o sesión sin empresa. */
  readonly esSuperadmin = computed(() => {
    const usuario = this.usuarioActual();
    return usuario !== null && (usuario.roles.includes(ROL_SUPERADMINISTRADOR) || usuario.empresa_id === null);
  });
  /** Cuenta de comprador: su único rol es "cliente" (no entra al back office). */
  readonly esSoloCliente = computed(() => {
    const roles = this.roles();
    return roles.length > 0 && roles.every((rol) => rol === 'cliente');
  });

  private readonly tienda = inject(TiendaActualService);
  /** Para obtener SesionOfflineService (y ConectividadService) de forma perezosa: SesionOfflineService inyecta a AuthService. */
  private readonly injector = inject(Injector);

  constructor(
    private readonly http: HttpClient,
    private readonly router: Router,
  ) {}

  tienePermiso(codigo: string): boolean {
    return this.permisos().includes(codigo);
  }

  /** `empresa` (código de la tienda) solo se envía cuando viene; sin ella solo entra un superadministrador. */
  login(email: string, password: string, empresa?: string | null): Observable<TokenRespuesta> {
    const cuerpo = empresa ? { empresa, email, password } : { email, password };
    return this.http
      .post<TokenRespuesta>(`${environment.apiUrl}/auth/login`, cuerpo)
      .pipe(
        tap((tokens) => {
          // Tokens nuevos: el alcance de una sesión anterior ya no corresponde hasta que se cargue este usuario.
          this.borrarAlcanceGuardado();
          this.guardarTokens(tokens);
        }),
      );
  }

  /** Recarga el usuario (roles y permisos reales) desde /auth/yo. */
  cargarUsuarioActual(): Observable<UsuarioYo> {
    return this.http.get<UsuarioYo>(`${environment.apiUrl}/auth/yo`).pipe(
      tap((usuario) => {
        this.usuarioActual.set(usuario);
        this.sinVerificar.set(false);
        this.recordarAlcance(usuario);
        this.guardarPerfilSinBloquear(usuario);
      }),
    );
  }

  /**
   * Se llama al iniciar la app: si hay tokens guardados, restaura la sesión. Si no hay red (status 0) y hay un perfil
   * guardado de esa empresa y ese usuario, restaura desde él y marca `sesionSinVerificar` hasta que vuelva la conexión.
   * Con 401/403 o sin perfil guardado, el error se propaga como siempre.
   */
  restaurarSesion(): Observable<UsuarioYo> | null {
    if (!this.getAccessToken()) {
      return null;
    }
    return this.cargarUsuarioActual().pipe(
      catchError((error: unknown) => {
        if (!(error instanceof HttpErrorResponse) || error.status !== 0) {
          return throwError(() => error);
        }
        return from(this.perfilParaReabrirSinRed()).pipe(
          switchMap((perfil) => {
            if (!perfil) {
              return throwError(() => error);
            }
            this.usuarioActual.set(perfil);
            this.sinVerificar.set(true);
            this.verificarAlVolverLaConexion();
            return of(perfil);
          }),
        );
      }),
    );
  }

  /** El perfil guardado del último usuario de este equipo, solo si coincide con el alcance recordado. Nunca lanza. */
  private async perfilParaReabrirSinRed(): Promise<UsuarioYo | null> {
    try {
      if (!this.getRefreshToken()) return null;
      const texto = localStorage.getItem(CLAVE_ALCANCE_SESION);
      if (!texto) return null;
      const alcance = JSON.parse(texto) as { empresaId?: unknown; usuarioId?: unknown };
      if (!Number.isInteger(alcance.empresaId) || !Number.isInteger(alcance.usuarioId)) return null;
      const empresaId = alcance.empresaId as number;
      const usuarioId = alcance.usuarioId as number;
      // El del personal y, si no hay, el del comprador de una tienda (cada uno vive en su propia base).
      const perfil =
        (await this.injector.get(SesionOfflineService).perfilGuardado(empresaId, usuarioId)) ??
        (await (await this.clienteOffline()).perfilGuardado(empresaId, usuarioId));
      // El perfil guardado debe ser exactamente de esa empresa y ese usuario.
      if (!perfil || perfil.id !== usuarioId || perfil.empresa_id !== empresaId) return null;
      return perfil;
    } catch {
      return null;
    }
  }

  /** Al volver la conexión confirma la sesión restaurada sin red: 401/403 la cierra; otro fallo la deja sin verificar. */
  private verificarAlVolverLaConexion(): void {
    if (this.suscripcionVerificacion) return;
    this.suscripcionVerificacion = this.injector.get(ConectividadService).volvioConexion$.subscribe(() => {
      if (!this.sinVerificar()) return;
      this.cargarUsuarioActual().subscribe({
        error: (error: unknown) => {
          const rechazada = error instanceof HttpErrorResponse && (error.status === 401 || error.status === 403);
          // Si el interceptor ya cerró la sesión (refresh rechazado), `sinVerificar` ya es false y no se repite.
          if (rechazada && this.sinVerificar()) {
            this.logout();
          }
        },
      });
    });
  }

  private recordarAlcance(usuario: UsuarioYo): void {
    const empresaId = usuario.empresa_id;
    if (typeof empresaId !== 'number' || usuario.roles.includes(ROL_SUPERADMINISTRADOR)) {
      this.borrarAlcanceGuardado();
      return;
    }
    try {
      localStorage.setItem(CLAVE_ALCANCE_SESION, JSON.stringify({ empresaId, usuarioId: usuario.id }));
    } catch {
      // Sin localStorage no se podrá reabrir sin red, pero el inicio de sesión sigue.
    }
  }

  private borrarAlcanceGuardado(): void {
    try {
      localStorage.removeItem(CLAVE_ALCANCE_SESION);
    } catch {
      // Nada que borrar.
    }
  }

  /** Guarda el perfil local sin bloquear ni romper el inicio de sesión: un fallo solo queda en la consola. */
  private guardarPerfilSinBloquear(usuario: UsuarioYo): void {
    try {
      // Un comprador de la tienda guarda su perfil en su propia base (la del personal no lo acepta).
      const esComprador = usuario.roles.length > 0 && usuario.roles.every((rol) => rol === 'cliente');
      const guardado = esComprador
        ? this.clienteOffline().then((cliente) => cliente.alIniciarSesion(usuario))
        : this.injector.get(SesionOfflineService).alIniciarSesion(usuario);
      guardado.catch((error: unknown) => console.warn('No se pudo guardar el perfil para el modo sin conexión.', error));
    } catch (error) {
      console.warn('No se pudo guardar el perfil para el modo sin conexión.', error);
    }
  }

  /** El almacén sin conexión del comprador se carga aparte: el arranque de la app no lo paga (solo lo usan los compradores). */
  private async clienteOffline(): Promise<ClienteOfflineServicio> {
    const { ClienteOfflineService } = await import('./offline-cliente/cliente-offline.service');
    return this.injector.get(ClienteOfflineService);
  }

  /** Los clientes se registran por tienda: POST /public/{codigo}/registro. */
  registrar(datos: RegistroRequest, codigoTienda: string): Observable<Usuario> {
    return this.http.post<Usuario>(
      `${environment.apiUrl}/public/${encodeURIComponent(codigoTienda)}/registro`,
      datos,
    );
  }

  solicitarRecuperacion(email: string, empresa?: string | null): Observable<RecuperarRespuesta> {
    const cuerpo = empresa ? { email, empresa } : { email };
    return this.http.post<RecuperarRespuesta>(`${environment.apiUrl}/auth/recuperar`, cuerpo);
  }

  confirmarRecuperacion(token: string, password: string): Observable<{ detail: string }> {
    return this.http.post<{ detail: string }>(`${environment.apiUrl}/auth/recuperar/confirmar`, {
      token,
      password,
    });
  }

  /** Borra tokens y usuario, sin navegar a ningún lado. */
  limpiarSesion(): void {
    localStorage.removeItem(CLAVE_ACCESS_TOKEN);
    localStorage.removeItem(CLAVE_REFRESH_TOKEN);
    this.borrarAlcanceGuardado();
    this.usuarioActual.set(null);
    this.sinVerificar.set(false);
  }

  logout(): void {
    // Antes de limpiar el usuario: el alcance (empresa y usuario) sale de la sesión. Sin esperar: salir no depende de IndexedDB.
    this.limpiarLocalSinBloquear();
    this.limpiarSesion();
    // Dentro de una tienda se vuelve a su login; fuera, al login del personal.
    if (this.tienda.codigo()) {
      this.router.navigate(this.tienda.ruta('login'));
    } else {
      this.router.navigate([RUTA_LOGIN_PERSONAL]);
    }
  }

  private limpiarLocalSinBloquear(): void {
    try {
      // El alcance del comprador se toma AHORA (síncrono): el almacén se carga aparte y para entonces la sesión ya se limpió.
      const usuario = this.usuarioActual();
      const alcanceComprador =
        this.esSoloCliente() && usuario !== null && typeof usuario.empresa_id === 'number'
          ? { empresaId: usuario.empresa_id, usuarioId: usuario.id }
          : null;
      const limpieza =
        alcanceComprador !== null
          ? this.clienteOffline().then((cliente) => cliente.alCerrarSesion(alcanceComprador))
          : this.injector.get(SesionOfflineService).alCerrarSesion();
      limpieza.catch((error: unknown) => console.warn('No se pudo limpiar el almacenamiento local al salir.', error));
    } catch (error) {
      console.warn('No se pudo limpiar el almacenamiento local al salir.', error);
    }
  }

  private refrescarTokens(): Observable<TokenRespuesta> {
    const refreshToken = this.getRefreshToken();
    return this.http
      .post<TokenRespuesta>(`${environment.apiUrl}/auth/refresh`, { refresh_token: refreshToken })
      .pipe(tap((tokens) => this.guardarTokens(tokens)));
  }

  /**
   * Igual que refrescarTokens(), pero deduplicada: si varias requests
   * reciben 401 casi al mismo tiempo (p. ej. varios GET en paralelo de un
   * dashboard), todas comparten esta misma llamada en vez de disparar cada
   * una su propio POST /auth/refresh. Sin esto, si el backend rota el
   * refresh token, la segunda llamada en paralelo usa un refresh token ya
   * invalidado por la primera y falla, cerrando la sesión de un usuario
   * cuyo access token en realidad sí se pudo renovar (ver W-1, auditoría).
   */
  refrescarTokensCompartido(): Observable<TokenRespuesta> {
    if (!this.refrescoEnCurso$) {
      this.refrescoEnCurso$ = this.refrescarTokens().pipe(
        finalize(() => (this.refrescoEnCurso$ = null)),
        shareReplay(1),
      );
    }
    return this.refrescoEnCurso$;
  }

  guardarTokens(tokens: TokenRespuesta): void {
    localStorage.setItem(CLAVE_ACCESS_TOKEN, tokens.access_token);
    localStorage.setItem(CLAVE_REFRESH_TOKEN, tokens.refresh_token);
  }

  getAccessToken(): string | null {
    return localStorage.getItem(CLAVE_ACCESS_TOKEN);
  }

  getRefreshToken(): string | null {
    return localStorage.getItem(CLAVE_REFRESH_TOKEN);
  }
}
