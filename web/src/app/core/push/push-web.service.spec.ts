import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { MessageService } from 'primeng/api';
import { environment } from '../../../environments/environment';
import { AvisosMostradosService, claveDeVenta } from '../avisos-mostrados.service';
import { SIN_RENOVAR_SESION, SIN_TOAST_ERROR } from '../http-contexts';
import { MENSAJERIA_PUSH, MensajePush, MensajeriaPush } from './firebase-mensajeria';
import { CLAVE_TOAST_AVISO, CLAVE_TOKEN_PUSH_WEB, PushWebService } from './push-web.service';

const API = environment.apiUrl;
const URL_ALTA = `${API}/dispositivos-push`;
const URL_BAJA = `${API}/dispositivos-push/baja`;
const URL_NOTIFICACIONES = `${API}/notificaciones`;

type Message = Parameters<MessageService['add']>[0];

describe('PushWebService (con Firebase simulado: ninguna prueba toca a Firebase ni al navegador real)', () => {
  let http: HttpTestingController;
  let servicio: PushWebService;
  let mensajeria: MensajeriaPush;
  let toasts: Message[];
  let recibir: ((mensaje: MensajePush) => void) | null;
  let dejarDeEscuchar: ReturnType<typeof vi.fn>;
  let permiso: NotificationPermission;
  let respuestaPermiso: NotificationPermission;
  let token: string;
  let pedirPermiso: ReturnType<typeof vi.fn>;

  /** Un navegador con push (o sin él), con el permiso en el estado indicado. */
  function navegador(opciones: { soporta?: boolean; permiso?: NotificationPermission; responde?: NotificationPermission } = {}): void {
    permiso = opciones.permiso ?? 'default';
    respuestaPermiso = opciones.responde ?? 'granted';
    pedirPermiso = vi.fn(async () => {
      permiso = respuestaPermiso;
      return permiso;
    });
    if (opciones.soporta === false) {
      Reflect.deleteProperty(navigator, 'serviceWorker');
      Reflect.deleteProperty(globalThis, 'Notification');
      Reflect.deleteProperty(globalThis, 'PushManager');
      return;
    }
    Object.defineProperty(navigator, 'serviceWorker', { value: {}, configurable: true });
    vi.stubGlobal('PushManager', class {});
    vi.stubGlobal('Notification', {
      get permission() {
        return permiso;
      },
      requestPermission: pedirPermiso,
    });
  }

  function montar(): void {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        MessageService,
        { provide: MENSAJERIA_PUSH, useValue: async () => mensajeria },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    toasts = [];
    TestBed.inject(MessageService).messageObserver.subscribe((m) => toasts.push(...(Array.isArray(m) ? m : [m])));
    servicio = TestBed.inject(PushWebService);
  }

  /** Deja pasar las promesas pendientes (el servicio espera a Firebase antes de hablar con el servidor). */
  const reposo = async () => {
    for (let i = 0; i < 8; i++) await Promise.resolve();
  };

  /** Atiende la próxima alta/baja con 204 y espera a que el servicio termine. */
  async function responder204(url: string): Promise<{ cuerpo: any; context: any }> {
    let peticion: ReturnType<HttpTestingController['match']>[number] | undefined;
    await vi.waitFor(() => {
      peticion = http.match((r) => r.url === url)[0];
      expect(peticion).toBeDefined();
    });
    peticion!.flush(null, { status: 204, statusText: 'No Content' });
    return { cuerpo: peticion!.request.body, context: peticion!.request.context };
  }

  beforeEach(() => {
    localStorage.clear();
    token = 'tok-1';
    recibir = null;
    dejarDeEscuchar = vi.fn();
    mensajeria = {
      soportado: vi.fn(async () => true),
      registrarServiceWorker: vi.fn(async () => ({}) as ServiceWorkerRegistration),
      obtenerToken: vi.fn(async () => token),
      borrarToken: vi.fn(async () => true),
      alRecibir: vi.fn(async (escuchar) => {
        recibir = escuchar;
        return dejarDeEscuchar as () => void;
      }),
    };
    navegador();
  });

  afterEach(() => {
    http.match(() => true);
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    Reflect.deleteProperty(navigator, 'serviceWorker');
    localStorage.clear();
  });

  describe('permiso del navegador', () => {
    it('NUNCA lo pide al cargar: ni al crear el servicio ni al sincronizar', async () => {
      montar();
      await servicio.sincronizarSiActivo();

      expect(pedirPermiso).not.toHaveBeenCalled();
      expect(servicio.estado()).toBe('inactivo');
      expect(mensajeria.obtenerToken).not.toHaveBeenCalled();
    });

    it('solo lo pide "Activar avisos" (activar)', async () => {
      montar();
      const hecho = servicio.activar();
      await responder204(URL_ALTA);
      await hecho;

      expect(pedirPermiso).toHaveBeenCalledTimes(1);
    });

    it('si ya estaba concedido no vuelve a pedirlo', async () => {
      navegador({ permiso: 'granted' });
      montar();
      const hecho = servicio.activar();
      await responder204(URL_ALTA);
      await hecho;

      expect(pedirPermiso).not.toHaveBeenCalled();
    });
  });

  describe('activar', () => {
    it('obtiene el token, lo manda a POST /dispositivos-push con plataforma "web", lo recuerda y queda activo', async () => {
      montar();
      const hecho = servicio.activar();
      const alta = await responder204(URL_ALTA);

      expect(await hecho).toBe(true);
      expect(alta.cuerpo).toEqual({ token: 'tok-1', plataforma: 'web' });
      expect(alta.context.get(SIN_TOAST_ERROR)).toBe(true);
      expect(mensajeria.registrarServiceWorker).toHaveBeenCalledTimes(1);
      expect(localStorage.getItem(CLAVE_TOKEN_PUSH_WEB)).toBe('tok-1');
      expect(servicio.estado()).toBe('activo');
      expect(mensajeria.alRecibir).toHaveBeenCalledTimes(1);
    });

    it('permiso rechazado en el diálogo del navegador: queda bloqueado, sin token ni petición', async () => {
      navegador({ responde: 'denied' });
      montar();

      expect(await servicio.activar()).toBe(false);
      expect(servicio.estado()).toBe('bloqueado');
      expect(servicio.mensaje()).toContain('Bloqueaste los avisos');
      expect(mensajeria.obtenerToken).not.toHaveBeenCalled();
      http.expectNone(URL_ALTA);
      expect(localStorage.getItem(CLAVE_TOKEN_PUSH_WEB)).toBeNull();
    });

    it('permiso ya bloqueado: lo dice desde el principio y no ofrece activar', async () => {
      navegador({ permiso: 'denied' });
      montar();

      expect(servicio.estado()).toBe('bloqueado');
      expect(await servicio.activar()).toBe(false);
      expect(pedirPermiso).not.toHaveBeenCalled();
    });

    it('cerrar el diálogo sin decidir deja los avisos apagados con un mensaje claro', async () => {
      navegador({ responde: 'default' });
      montar();

      expect(await servicio.activar()).toBe(false);
      expect(servicio.estado()).toBe('inactivo');
      expect(servicio.mensaje()).toContain('No diste el permiso');
    });

    it('un navegador sin push lo dice y no pide nada', async () => {
      navegador({ soporta: false });
      montar();

      expect(servicio.estado()).toBe('no_soportado');
      expect(servicio.mensaje()).toContain('no puede recibir avisos');
      expect(await servicio.activar()).toBe(false);
      expect(mensajeria.obtenerToken).not.toHaveBeenCalled();
    });

    it('en iPhone explica que hace falta instalar la web (iOS 16.4 o más)', () => {
      navegador({ soporta: false });
      vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue('Mozilla/5.0 (iPhone; CPU iPhone OS 16_4 like Mac OS X)');
      montar();

      expect(servicio.mensaje()).toContain('iPhone');
      expect(servicio.mensaje()).toContain('16.4');
    });

    it('sin una conexión segura (http) lo dice y no intenta nada', async () => {
      Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true });
      try {
        montar();

        expect(servicio.estado()).toBe('sin_https');
        expect(servicio.mensaje()).toContain('https');
        expect(await servicio.activar()).toBe(false);
        expect(pedirPermiso).not.toHaveBeenCalled();
      } finally {
        Reflect.deleteProperty(window, 'isSecureContext');
      }
    });

    it('Firebase que dice "no soportado" deja el estado como no soportado', async () => {
      (mensajeria.soportado as ReturnType<typeof vi.fn>).mockResolvedValue(false);
      montar();

      expect(await servicio.activar()).toBe(false);
      expect(servicio.estado()).toBe('no_soportado');
      expect(pedirPermiso).not.toHaveBeenCalled();
    });

    it('si el servidor rechaza el alta no queda activo ni recuerda el token', async () => {
      montar();
      const hecho = servicio.activar();
      let alta: ReturnType<HttpTestingController['match']>[number] | undefined;
      await vi.waitFor(() => {
        alta = http.match(URL_ALTA)[0];
        expect(alta).toBeDefined();
      });
      alta!.flush({ detail: 'Error' }, { status: 500, statusText: 'Server Error' });

      expect(await hecho).toBe(false);
      expect(servicio.estado()).toBe('inactivo');
      expect(servicio.mensaje()).toContain('No pudimos activar');
      expect(localStorage.getItem(CLAVE_TOKEN_PUSH_WEB)).toBeNull();
    });

    it('si Firebase falla al dar el token no queda activo', async () => {
      (mensajeria.obtenerToken as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('fcm'));
      montar();

      expect(await servicio.activar()).toBe(false);
      expect(servicio.estado()).toBe('inactivo');
      http.expectNone(URL_ALTA);
    });

    it('activar dos veces seguidas pide una sola vez', async () => {
      montar();
      const primera = servicio.activar();
      const segunda = servicio.activar();
      await responder204(URL_ALTA);

      expect(await primera).toBe(true);
      expect(await segunda).toBe(false); // ya estaba activando
      expect(pedirPermiso).toHaveBeenCalledTimes(1);
    });
  });

  describe('sincronizarSiActivo (token que cambia)', () => {
    it('sin avisos activados no hace nada', async () => {
      navegador({ permiso: 'granted' });
      montar();
      await servicio.sincronizarSiActivo();

      expect(mensajeria.obtenerToken).not.toHaveBeenCalled();
      http.expectNone(URL_ALTA);
    });

    it('con el mismo token no reenvía nada, pero deja escuchando', async () => {
      navegador({ permiso: 'granted' });
      localStorage.setItem(CLAVE_TOKEN_PUSH_WEB, 'tok-1');
      montar();
      await servicio.sincronizarSiActivo();

      http.expectNone(URL_ALTA);
      expect(servicio.estado()).toBe('activo');
      expect(mensajeria.alRecibir).toHaveBeenCalledTimes(1);
    });

    it('si Firebase cambió el token, reenvía el nuevo y lo recuerda', async () => {
      navegador({ permiso: 'granted' });
      localStorage.setItem(CLAVE_TOKEN_PUSH_WEB, 'tok-viejo');
      token = 'tok-nuevo';
      montar();
      const hecho = servicio.sincronizarSiActivo();
      const alta = await responder204(URL_ALTA);
      await hecho;

      expect(alta.cuerpo).toEqual({ token: 'tok-nuevo', plataforma: 'web' });
      expect(localStorage.getItem(CLAVE_TOKEN_PUSH_WEB)).toBe('tok-nuevo');
      expect(pedirPermiso).not.toHaveBeenCalled();
    });

    it('si quitaron el permiso en el navegador, olvida el token y deja de escuchar', async () => {
      navegador({ permiso: 'denied' });
      localStorage.setItem(CLAVE_TOKEN_PUSH_WEB, 'tok-1');
      montar();
      await servicio.sincronizarSiActivo();

      expect(localStorage.getItem(CLAVE_TOKEN_PUSH_WEB)).toBeNull();
      expect(servicio.estado()).toBe('bloqueado');
      expect(mensajeria.obtenerToken).not.toHaveBeenCalled();
    });

    it('sin red o sin Firebase no lanza ni molesta: lo intentará la próxima vez', async () => {
      navegador({ permiso: 'granted' });
      localStorage.setItem(CLAVE_TOKEN_PUSH_WEB, 'tok-1');
      (mensajeria.obtenerToken as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('sin red'));
      montar();

      await expect(servicio.sincronizarSiActivo()).resolves.toBeUndefined();
      expect(localStorage.getItem(CLAVE_TOKEN_PUSH_WEB)).toBe('tok-1');
      expect(toasts).toEqual([]);
    });
  });

  describe('desactivar y baja al cerrar sesión', () => {
    async function activo(): Promise<void> {
      montar();
      const hecho = servicio.activar();
      await responder204(URL_ALTA);
      await hecho;
    }

    it('"Desactivar" da de baja el token en el servidor y en Firebase, y deja de escuchar', async () => {
      await activo();
      const hecho = servicio.desactivar();
      const baja = await responder204(URL_BAJA);

      expect(await hecho).toBe(true);
      expect(baja.cuerpo).toEqual({ token: 'tok-1' });
      expect(mensajeria.borrarToken).toHaveBeenCalledTimes(1);
      expect(dejarDeEscuchar).toHaveBeenCalledTimes(1);
      expect(localStorage.getItem(CLAVE_TOKEN_PUSH_WEB)).toBeNull();
      expect(servicio.estado()).toBe('inactivo');
    });

    it('si el servidor no responde la baja, sigue activo y lo dice', async () => {
      await activo();
      const hecho = servicio.desactivar();
      let baja: ReturnType<HttpTestingController['match']>[number] | undefined;
      await vi.waitFor(() => {
        baja = http.match(URL_BAJA)[0];
        expect(baja).toBeDefined();
      });
      baja!.flush({ detail: 'Error' }, { status: 500, statusText: 'Server Error' });

      expect(await hecho).toBe(false);
      expect(servicio.estado()).toBe('activo');
      expect(servicio.mensaje()).toContain('No pudimos desactivar');
      expect(localStorage.getItem(CLAVE_TOKEN_PUSH_WEB)).toBe('tok-1');
    });

    it('al cerrar sesión da de baja el token ENSEGUIDA (con la sesión puesta), sin renovar la sesión y sin avisos de error', async () => {
      await activo();
      servicio.darDeBajaAlSalir();

      // La petición ya salió, sin esperar a nada: así lleva el token de la sesión que todavía vale.
      const baja = http.expectOne(URL_BAJA);
      expect(baja.request.body).toEqual({ token: 'tok-1' });
      expect(baja.request.context.get(SIN_RENOVAR_SESION)).toBe(true);
      expect(baja.request.context.get(SIN_TOAST_ERROR)).toBe(true);
      baja.flush(null, { status: 204, statusText: 'No Content' });

      expect(localStorage.getItem(CLAVE_TOKEN_PUSH_WEB)).toBeNull();
      expect(servicio.estado()).toBe('inactivo');
      expect(dejarDeEscuchar).toHaveBeenCalledTimes(1);
      await reposo();
      expect(mensajeria.borrarToken).toHaveBeenCalledTimes(1);
    });

    it('un fallo de la baja al salir no molesta (mejor esfuerzo)', async () => {
      await activo();
      servicio.darDeBajaAlSalir();
      http.expectOne(URL_BAJA).flush({ detail: 'x' }, { status: 401, statusText: 'Unauthorized' });
      await reposo();

      expect(localStorage.getItem(CLAVE_TOKEN_PUSH_WEB)).toBeNull();
      expect(toasts).toEqual([]);
    });

    it('si los avisos no estaban activados, salir no manda nada', () => {
      montar();
      servicio.darDeBajaAlSalir();
      http.expectNone(URL_BAJA);
    });
  });

  describe('con la pestaña abierta (onMessage)', () => {
    const compra = (tipo: string, ventaId = 42, extra: Record<string, string> = {}): MensajePush => ({
      notification: { title: 'Compra confirmada', body: 'Tu compra V-0042 por Bs 200.00 está pagada.' },
      data: { tipo, referencia_id: String(ventaId), notificacion_id: '7', empresa_codigo: 'acme', ...extra },
    });
    const refrescos = () => http.match((r) => r.url === URL_NOTIFICACIONES);

    async function conEscucha(): Promise<void> {
      montar();
      const hecho = servicio.activar();
      await responder204(URL_ALTA);
      await hecho;
      expect(recibir).not.toBeNull();
    }

    it('muestra un aviso con el título, el cuerpo y la ruta de la compra para el botón "Ver", y refresca las notificaciones', async () => {
      await conEscucha();
      recibir!(compra('compra_confirmada'));

      expect(toasts).toHaveLength(1);
      expect(toasts[0]).toMatchObject({
        key: CLAVE_TOAST_AVISO,
        summary: 'Compra confirmada',
        detail: 'Tu compra V-0042 por Bs 200.00 está pagada.',
        data: { ruta: '/t/acme/mis-compras/42' },
      });
      const lista = refrescos();
      expect(lista).toHaveLength(1);
      expect(lista[0].request.context.get(SIN_TOAST_ERROR)).toBe(true);
    });

    it('compra_confirmada y pedido_diferido de la MISMA venta son el mismo aviso: sale una sola vez', async () => {
      await conEscucha();
      recibir!(compra('compra_confirmada'));
      recibir!(compra('pedido_diferido', 42, { notificacion_id: '8' }));

      expect(toasts).toHaveLength(1);
      // Pero la lista de notificaciones sí se refresca las dos veces.
      expect(refrescos()).toHaveLength(2);
    });

    it('el mismo mensaje repetido no avisa dos veces', async () => {
      await conEscucha();
      recibir!(compra('compra_confirmada'));
      recibir!(compra('compra_confirmada'));

      expect(toasts).toHaveLength(1);
    });

    it('otra venta sí avisa', async () => {
      await conEscucha();
      recibir!(compra('compra_confirmada', 42));
      recibir!(compra('compra_confirmada', 43));

      expect(toasts).toHaveLength(2);
    });

    it('si el toast del pedido sin conexión o el panel "Pago aprobado" ya avisó de esa venta, no repite', async () => {
      await conEscucha();
      TestBed.inject(AvisosMostradosService).registrar(claveDeVenta(42));
      recibir!(compra('compra_confirmada'));

      expect(toasts).toEqual([]);
      expect(refrescos()).toHaveLength(1); // igual se actualiza la lista
    });

    it('si la persona ya está viendo esa compra, solo se refresca (sin toast)', async () => {
      await conEscucha();
      vi.spyOn(TestBed.inject(Router), 'url', 'get').mockReturnValue('/t/acme/mis-compras/42');
      recibir!(compra('compra_confirmada'));

      expect(toasts).toEqual([]);
      expect(refrescos()).toHaveLength(1);
    });

    it('en la pantalla del estado del pago ("¡Pago aprobado!") tampoco se repite con un toast', async () => {
      await conEscucha();
      vi.spyOn(TestBed.inject(Router), 'url', 'get').mockReturnValue('/t/acme/checkout/estado/9');
      recibir!(compra('compra_confirmada'));

      expect(toasts).toEqual([]);
    });

    it('otra compra distinta de la que se está viendo sí avisa', async () => {
      await conEscucha();
      vi.spyOn(TestBed.inject(Router), 'url', 'get').mockReturnValue('/t/acme/mis-compras/42');
      recibir!(compra('compra_confirmada', 421));

      expect(toasts).toHaveLength(1);
    });

    it('los avisos del personal llevan a su pantalla; un tipo sin pantalla avisa sin botón', async () => {
      await conEscucha();
      recibir!({ notification: { title: 'Nueva reserva' }, data: { tipo: 'reserva', referencia_id: '5', notificacion_id: '1', empresa_codigo: 'acme' } });
      recibir!({ notification: { title: 'Algo' }, data: { tipo: 'otro_tipo', referencia_id: '5', notificacion_id: '2' } });

      expect(toasts.map((t) => t.data)).toEqual([{ ruta: '/reservas' }, { ruta: null }]);
    });

    it('al desactivar deja de escuchar', async () => {
      await conEscucha();
      const hecho = servicio.desactivar();
      await responder204(URL_BAJA);
      await hecho;

      expect(dejarDeEscuchar).toHaveBeenCalled();
    });
  });
});
