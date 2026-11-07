import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, TestRequest, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MessageService } from 'primeng/api';
import { environment } from '../../../../environments/environment';
import { AvisosMostradosService, claveDeVenta } from '../../../core/avisos-mostrados.service';
import { ConectividadService } from '../../../core/conectividad.service';
import { EMPRESA, USUARIO, linea, nuevoEntorno, pedido } from '../../../core/offline-cliente/ayudas-prueba';
import {
  FALLOS_AUTOMATICOS_MAX,
  MENSAJE_PEDIDO_VENCIDO,
  MENSAJE_PEDIDO_VENCIDO_SERVIDOR,
  PEDIDO_CADUCA_DIAS,
  PEDIDO_CADUCA_MS,
} from '../../../core/offline-cliente/cliente-offline.config';
import type { EntradaPedido } from './pedidos-sin-conexion.service';
import { ClienteOfflineService } from '../../../core/offline-cliente/cliente-offline.service';
import { MENSAJE_PEDIDO_INVALIDO, PedidosSinConexionService } from './pedidos-sin-conexion.service';
import { MetodoPagoLocalService } from './metodo-pago-local.service';

type Message = Parameters<MessageService['add']>[0];

const URL = `${environment.apiUrl}/pedidos-diferidos`;
const T0 = Date.parse('2026-11-06T18:00:00Z');
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

/** Respuesta de mentira del servidor a una petición. */
type Falsa = { status?: number; cuerpo?: unknown; headers?: Record<string, string> } | 'red' | 'colgar';

interface Peticion {
  operacionId: string;
  cuerpo: any;
}

function respuesta(operacionId: string, estado: 'cobrado' | 'rechazado', extra: Record<string, unknown> = {}): Record<string, unknown> {
  const cobrado = estado === 'cobrado';
  return {
    operacion_id: operacionId,
    estado,
    motivo: null,
    mensaje: cobrado ? 'Cobramos tu pedido.' : 'No pudimos cobrar tu pedido.',
    venta_id: cobrado ? 55 : null,
    codigo_venta: cobrado ? 'V-0055' : null,
    total: cobrado ? '398.00' : null,
    total_usd: cobrado ? '57.18' : null,
    duplicada: false,
    ...extra,
  };
}

const error503 = { status: 503, cuerpo: { detail: 'PayPal no responde', codigo: 'paypal_no_disponible', mensaje: 'PayPal no responde' } } as const;

describe('PedidosSinConexionService', () => {
  let entorno: ReturnType<typeof nuevoEntorno>;
  let http: HttpTestingController;
  let servicio: PedidosSinConexionService;
  let mensajes: Message[];
  let peticiones: Peticion[];
  let alPedido: (cuerpo: any, n: number) => Falsa;

  const cobrar = (cuerpo: any): Falsa => ({ cuerpo: respuesta(cuerpo.operacion_id, 'cobrado') });

  beforeEach(async () => {
    // Fechas y temporizadores falsos; los de IndexedDB usan setImmediate (no se falsea), así la base sigue funcionando.
    vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
    vi.setSystemTime(T0);
    // Sin variación en las esperas: 5 s, 10 s, 20 s... exactos.
    vi.spyOn(Math, 'random').mockReturnValue(0.5);

    entorno = nuevoEntorno();
    peticiones = [];
    mensajes = [];
    alPedido = cobrar;

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        MessageService,
        { provide: ClienteOfflineService, useValue: entorno.cliente },
        { provide: ConectividadService, useValue: entorno.conectividad },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    TestBed.inject(MessageService).messageObserver.subscribe((m) => mensajes.push(...(Array.isArray(m) ? m : [m])));
    servicio = TestBed.inject(PedidosSinConexionService);
    TestBed.tick();
    await reposo();
  });

  afterEach(async () => {
    TestBed.resetTestingModule();
    vi.useRealTimers();
    vi.restoreAllMocks();
    await entorno.cerrar();
  });

  // ---- Un servidor de mentira ----------------------------------------------------------------------------------------------

  // `setImmediate` no se falsea (como en IndexedDB falso): sirve para ceder el turno aunque setTimeout sea falso.
  const inmediato = (globalThis as unknown as { setImmediate: (tarea: () => void) => void }).setImmediate;
  const ceder = () => new Promise<void>((resolver) => inmediato(resolver));
  const ciclo = () => (servicio as unknown as { cicloEnCurso: Promise<void> | null }).cicloEnCurso;

  function atender(req: TestRequest): void {
    const cuerpo = req.request.body;
    peticiones.push({ operacionId: cuerpo.operacion_id, cuerpo });
    const falsa = alPedido(cuerpo, peticiones.length);
    if (falsa === 'colgar') return;
    if (falsa === 'red') {
      req.error(new ProgressEvent('error'));
    } else if (falsa.status && falsa.status >= 400) {
      req.flush(falsa.cuerpo ?? { detail: 'falla de prueba' }, { status: falsa.status, statusText: 'Falla', headers: falsa.headers });
    } else {
      req.flush(falsa.cuerpo as object);
    }
  }

  const atenderPendientes = () => {
    for (const req of http.match(() => true)) atender(req);
  };

  /** Atiende peticiones hasta que la cola descanse: sin ciclo en curso (y unos turnos de gracia para los disparos pendientes). */
  async function reposo(minimo = 25): Promise<void> {
    for (let i = 0; i < 6000; i++) {
      atenderPendientes();
      if (i >= minimo && ciclo() === null) break;
      await ceder();
    }
    atenderPendientes();
  }

  async function avanzar(ms: number): Promise<void> {
    await vi.advanceTimersByTimeAsync(ms);
    await reposo();
  }

  /** Espera el próximo POST sin responderlo; falla si hay dos a la vez. */
  async function tomarPeticion(): Promise<TestRequest> {
    for (let i = 0; i < 3000; i++) {
      const abiertas = http.match((r) => r.method === 'POST' && r.url === URL);
      if (abiertas.length > 1) throw new Error('Se enviaron dos pedidos a la vez.');
      if (abiertas.length === 1) {
        peticiones.push({ operacionId: abiertas[0].request.body.operacion_id, cuerpo: abiertas[0].request.body });
        return abiertas[0];
      }
      await ceder();
    }
    throw new Error('El servicio nunca envió el pedido.');
  }

  const entrada = (n = 1): EntradaPedido => ({
    sucursalId: 3,
    sucursalNombre: 'Centro',
    costoEnvioCentavos: 0,
    lineas: [linea(n, { cantidad: 2, precio_unitario: '199.00' })],
  });

  /** Encola un pedido nuevo con la hora del reloj falso corrida 1 s (para que el orden sea determinista). */
  async function encolar(n = 1): Promise<string> {
    vi.setSystemTime(Date.now() + 1000);
    const creado = await servicio.encolar(entrada(n));
    expect(creado).not.toBeNull();
    return creado!.operacion_id;
  }

  const guardado = (id: string) => entorno.repo().pedido(id);

  // ---- Encolar ---------------------------------------------------------------------------------------------------------------

  describe('encolar', () => {
    it('guarda el pedido con su operacion_id (UUID v4), el total que el cliente aceptó y vacía el carrito local', async () => {
      entorno.enLinea.set(false);
      await entorno.repo().agregarLinea(linea(1), 5);

      const creado = await servicio.encolar({
        sucursalId: 3,
        sucursalNombre: 'Centro',
        costoEnvioCentavos: 0,
        lineas: [linea(1, { cantidad: 2, precio_unitario: '199.00' }), linea(2, { cantidad: 1, precio_unitario: '50.50' })],
      });

      expect(creado).toMatchObject({
        estado: 'pendiente',
        sucursal_id: 3,
        costo_envio: '0.00',
        total_maximo: '448.50',
        intentos: 0,
        empresa_id: EMPRESA,
        usuario_id: USUARIO,
      });
      expect(creado?.operacion_id).toMatch(UUID_V4);
      expect(creado?.lineas.map((l) => [l.variante_id, l.cantidad, l.precio_unitario])).toEqual([[101, 2, '199.00'], [102, 1, '50.50']]);
      expect(await entorno.repo().carrito()).toEqual([]);
      expect(servicio.pendientes()).toHaveLength(1);
    });

    it('suma el costo de envío al total máximo', async () => {
      entorno.enLinea.set(false);
      const creado = await servicio.encolar({ ...entrada(1), costoEnvioCentavos: 1500 });
      expect(creado?.costo_envio).toBe('15.00');
      expect(creado?.total_maximo).toBe('413.00');
    });

    it('no guarda sin sesión, ni un pedido vacío', async () => {
      entorno.enLinea.set(false);
      expect(await servicio.encolar({ ...entrada(1), lineas: [] })).toBeNull();
      entorno.alcance.set(null);
      expect(await servicio.encolar(entrada(1))).toBeNull();
    });
  });

  // ---- Volver la red y enviar ------------------------------------------------------------------------------------------------

  describe('registrar sin conexión, volver la red y enviar', () => {
    it('sin red el pedido espera; al volver la red sale UNA vez y queda cobrado SIN borrarse', async () => {
      entorno.enLinea.set(false);
      const id = await encolar();
      await reposo();

      expect(peticiones).toHaveLength(0);
      expect(servicio.estadoCola()).toBe('sin_conexion');
      expect((await guardado(id))?.estado).toBe('pendiente');
      expect((await guardado(id))?.intentos).toBe(0);

      entorno.enLinea.set(true);
      entorno.volvio.next();
      await reposo();

      expect(peticiones).toHaveLength(1);
      expect(peticiones[0].cuerpo).toEqual({
        operacion_id: id,
        sucursal_id: 3,
        costo_envio: '0.00',
        lineas: [{ variante_id: 101, cantidad: 2 }],
        total_maximo: '398.00',
        fecha_pedido: expect.any(String),
      });
      const pedidoFinal = await guardado(id);
      expect(pedidoFinal).toMatchObject({
        estado: 'cobrado',
        venta_id: 55,
        codigo_venta: 'V-0055',
        total: '398.00',
        total_usd: '57.18',
        intentos: 1,
        visto: false,
        proximo_intento_en: null,
      });
      expect(pedidoFinal?.resuelto_en).not.toBeNull();
      expect(servicio.estadoCola()).toBe('inactiva');
      expect(servicio.sinVer()).toHaveLength(1);
      expect(mensajes.map((m) => [m.severity, m.summary])).toEqual([['success', 'Cobramos tu pedido']]);
      expect(mensajes[0].detail).toContain('V-0055');
    });

    it('el toast del cobro anota la compra en AvisosMostrados: un aviso push de la misma venta ya no avisa otra vez', async () => {
      const avisos = TestBed.inject(AvisosMostradosService);
      await encolar();
      await reposo();

      expect(mensajes.map((m) => m.summary)).toEqual(['Cobramos tu pedido']);
      expect(avisos.registrar(claveDeVenta(55))).toBe(false);
    });

    it('si ya se le avisó de esa compra (aviso push o pago aprobado), el cobro NO repite el toast pero el pedido queda cobrado', async () => {
      TestBed.inject(AvisosMostradosService).registrar(claveDeVenta(55));
      const id = await encolar();
      await reposo();

      expect(mensajes).toEqual([]);
      expect((await guardado(id))?.estado).toBe('cobrado');
      expect(servicio.sinVer()).toHaveLength(1);
    });

    it('con red, el pedido sale solo al encolarlo', async () => {
      const id = await encolar();
      await reposo();

      expect(peticiones.map((p) => p.operacionId)).toEqual([id]);
      expect((await guardado(id))?.estado).toBe('cobrado');
    });

    it('un rechazo del servidor (200) es final: queda rechazado con su motivo y mensaje, y NO se reenvía', async () => {
      alPedido = (c) => ({
        cuerpo: respuesta(c.operacion_id, 'rechazado', { motivo: 'stock_insuficiente', mensaje: 'La Polera 1 ya no tiene stock. No se cobró nada.' }),
      });
      const id = await encolar();
      await reposo();
      await avanzar(600_000);

      expect(peticiones).toHaveLength(1);
      expect(await guardado(id)).toMatchObject({
        estado: 'rechazado',
        motivo: 'stock_insuficiente',
        mensaje: 'La Polera 1 ya no tiene stock. No se cobró nada.',
        venta_id: null,
        visto: false,
      });
      expect(mensajes.map((m) => [m.severity, m.summary])).toEqual([['warn', 'No pudimos cobrar tu pedido']]);
      expect(mensajes[0].detail).toContain('ya no tiene stock');
    });

    it('un rechazo por falta de PayPal guardado se recuerda para decidir sin red', async () => {
      await entorno.repo().guardarMeta('metodo_pago', { guardado: true, correo_paypal: 'j***@gmail.com', guardado_en: null, verificado_en: 'x' });
      const metodo = TestBed.inject(MetodoPagoLocalService);
      await metodo.cargar();
      expect(metodo.tienePaypal()).toBe(true);

      alPedido = (c) => ({ cuerpo: respuesta(c.operacion_id, 'rechazado', { motivo: 'sin_metodo_pago', mensaje: 'No tienes un PayPal guardado.' }) });
      await encolar();
      await reposo();

      expect(metodo.tienePaypal()).toBe(false);
    });

    it('una respuesta con duplicada:true es un reenvío seguro y se trata como cualquier decisión', async () => {
      alPedido = (c) => ({ cuerpo: respuesta(c.operacion_id, 'cobrado', { duplicada: true }) });
      const id = await encolar();
      await reposo();

      expect((await guardado(id))?.estado).toBe('cobrado');
    });

    it('una respuesta que no es una decisión (ni cobrado ni rechazado) se trata como fallo y se reintenta', async () => {
      alPedido = (c, n) => (n === 1 ? { cuerpo: { operacion_id: c.operacion_id, estado: 'quien_sabe' } } : cobrar(c));
      const id = await encolar();
      await reposo();
      expect((await guardado(id))?.estado).toBe('pendiente');
      expect((await guardado(id))?.ultimo_error).toBe('respuesta_invalida');

      await avanzar(5_100);

      expect((await guardado(id))?.estado).toBe('cobrado');
    });
  });

  // ---- Reintentos con la misma operacion_id ------------------------------------------------------------------------------------

  describe('reintentos', () => {
    it('503 (resultado incierto): el pedido sigue pendiente y se reintenta con espera creciente y la MISMA operacion_id', async () => {
      alPedido = (c, n) => (n <= 2 ? { ...error503 } : cobrar(c));
      const id = await encolar();
      await reposo();

      expect(peticiones).toHaveLength(1);
      expect(await guardado(id)).toMatchObject({ estado: 'pendiente', ultimo_error: 'paypal_no_disponible', intentos: 1 });
      expect(servicio.estadoCola()).toBe('esperando_reintento');
      expect(servicio.proximoIntentoEn()).not.toBeNull();

      await avanzar(4_000);
      expect(peticiones).toHaveLength(1);

      await avanzar(1_500); // 5 s: primer reintento (vuelve a fallar)
      expect(peticiones).toHaveLength(2);
      expect(await guardado(id)).toMatchObject({ estado: 'pendiente', intentos: 2 });

      await avanzar(9_000); // la espera ahora es de 10 s: todavía no
      expect(peticiones).toHaveLength(2);
      await avanzar(1_500);

      expect(peticiones).toHaveLength(3);
      expect(new Set(peticiones.map((p) => p.operacionId))).toEqual(new Set([id]));
      expect(await guardado(id)).toMatchObject({ estado: 'cobrado', intentos: 3 });
      expect(servicio.estadoCola()).toBe('inactiva');
    });

    it('sin respuesta de la red (con red en el navegador) también reintenta con la misma operacion_id', async () => {
      alPedido = (c, n) => (n === 1 ? 'red' : cobrar(c));
      const id = await encolar();
      await reposo();
      expect((await guardado(id))?.ultimo_error).toBe('sin_conexion');

      await avanzar(5_100);

      expect(peticiones.map((p) => p.operacionId)).toEqual([id, id]);
      expect((await guardado(id))?.estado).toBe('cobrado');
    });

    it('se fue la red a mitad del envío: espera sin castigo hasta volver la conexión', async () => {
      alPedido = () => {
        entorno.enLinea.set(false);
        return 'red';
      };
      const id = await encolar();
      await reposo();
      await avanzar(600_000);

      expect(peticiones).toHaveLength(1);
      expect(servicio.estadoCola()).toBe('sin_conexion');
      expect(await guardado(id)).toMatchObject({ estado: 'pendiente', ultimo_error: 'sin_conexion', proximo_intento_en: null });

      alPedido = cobrar;
      entorno.enLinea.set(true);
      entorno.volvio.next();
      await reposo();
      expect((await guardado(id))?.estado).toBe('cobrado');
      expect(peticiones.map((p) => p.operacionId)).toEqual([id, id]);
    });

    it('429 espera lo que diga Retry-After', async () => {
      alPedido = (c, n) => (n === 1 ? { status: 429, cuerpo: { detail: 'Demasiadas' }, headers: { 'Retry-After': '60' } } : cobrar(c));
      await encolar();
      await reposo();

      await avanzar(59_000);
      expect(peticiones).toHaveLength(1);
      await avanzar(1_500);
      expect(peticiones).toHaveLength(2);
    });

    it('tras muchos fallos seguidos la cola se detiene (sigue guardado) y "Enviar ahora" la reanuda', { timeout: 30_000 }, async () => {
      alPedido = () => ({ ...error503 });
      const id = await encolar();
      await reposo();
      for (let i = 0; i < FALLOS_AUTOMATICOS_MAX + 2; i++) await avanzar(310_000);

      expect(peticiones).toHaveLength(FALLOS_AUTOMATICOS_MAX);
      expect(servicio.estadoCola()).toBe('detenida_por_fallos');
      expect(servicio.motivoPausa()).toContain('Sigue guardado');
      expect((await guardado(id))?.estado).toBe('pendiente');

      alPedido = cobrar;
      void servicio.enviarAhora();
      await reposo();

      expect((await guardado(id))?.estado).toBe('cobrado');
      expect(peticiones.at(-1)?.operacionId).toBe(id);
    });

    it('un pedido que quedó "enviando" por un cierre brusco se reenvía con la misma operacion_id', async () => {
      entorno.enLinea.set(false);
      const huerfano = pedido(7, { estado: 'enviando', intentos: 1, ultimo_intento_en: new Date(T0 - 600_000).toISOString() });
      await entorno.repo().registrarPedido(huerfano);

      entorno.enLinea.set(true);
      entorno.volvio.next();
      await reposo();

      expect(peticiones.map((p) => p.operacionId)).toEqual([huerfano.operacion_id]);
      expect((await guardado(huerfano.operacion_id))?.estado).toBe('cobrado');
    });

    it('un "enviando" reciente (lo está enviando otra pestaña) no se toca', async () => {
      const reciente = pedido(8, { estado: 'enviando', intentos: 1, ultimo_intento_en: new Date(T0 - 5_000).toISOString() });
      await entorno.repo().registrarPedido(reciente);

      entorno.volvio.next();
      await reposo();

      expect(peticiones).toHaveLength(0);
    });
  });

  // ---- Uno a uno, en orden, sin duplicar -------------------------------------------------------------------------------------

  describe('orden y duplicados', () => {
    it('envía los pedidos uno a uno y en orden (el más antiguo primero); nunca dos a la vez', async () => {
      entorno.enLinea.set(false);
      const ids = [await encolar(1), await encolar(2), await encolar(3)];

      entorno.enLinea.set(true);
      entorno.volvio.next();
      for (const esperado of ids) {
        const req = await tomarPeticion();
        expect(req.request.body.operacion_id).toBe(esperado);
        // Mientras éste no responde, no sale ninguno más.
        for (let i = 0; i < 40; i++) await ceder();
        expect(http.match((r) => r.method === 'POST' && r.url === URL)).toHaveLength(0);
        req.flush(respuesta(esperado, 'cobrado'));
      }
      await reposo();

      expect(peticiones.map((p) => p.operacionId)).toEqual(ids);
      for (const id of ids) expect((await guardado(id))?.estado).toBe('cobrado');
    });

    it('si el primero falla por algo temporal, los demás esperan su turno (no lo adelantan)', async () => {
      entorno.enLinea.set(false);
      const [a, b] = [await encolar(1), await encolar(2)];
      alPedido = (c, n) => (n === 1 ? { ...error503 } : cobrar(c));

      entorno.enLinea.set(true);
      entorno.volvio.next();
      await reposo();

      expect(peticiones.map((p) => p.operacionId)).toEqual([a]);
      expect((await guardado(b))?.estado).toBe('pendiente');
      expect((await guardado(b))?.intentos).toBe(0);

      await avanzar(5_100);
      expect(peticiones.map((p) => p.operacionId)).toEqual([a, a, b]);
    });

    it('varios disparos a la vez (red, botón, pestaña, temporizador) no envían dos veces el mismo pedido', async () => {
      entorno.enLinea.set(false);
      const id = await encolar();
      entorno.enLinea.set(true);

      entorno.volvio.next();
      void servicio.enviarAhora();
      void servicio.enviarAhora();
      document.dispatchEvent(new Event('visibilitychange'));
      await avanzar(61_000);
      entorno.volvio.next();
      await reposo();

      expect(peticiones.map((p) => p.operacionId)).toEqual([id]);
    });

    it('un pedido ya cobrado no se vuelve a enviar aunque vuelva la red', async () => {
      const id = await encolar();
      await reposo();
      entorno.volvio.next();
      await reposo();
      void servicio.enviarAhora();
      await reposo();

      expect(peticiones.map((p) => p.operacionId)).toEqual([id]);
    });

    it('solo se envían los pedidos de la persona de la sesión', async () => {
      await entorno.repo(EMPRESA, 9).registrarPedido(pedido(7, { usuario_id: 9 }));
      await entorno.repo(2, USUARIO).registrarPedido(pedido(8, { empresa_id: 2 }));

      entorno.volvio.next();
      await reposo();
      void servicio.enviarAhora();
      await reposo();

      expect(peticiones).toHaveLength(0);
      expect(servicio.pedidos()).toEqual([]);
    });
  });

  // ---- Sesión, permisos y datos inválidos ----------------------------------------------------------------------------------------

  describe('401, 403 y 422', () => {
    it('401 (sesión vencida): pausa y avisa, el pedido sigue guardado, y se reanuda cuando la MISMA persona vuelve a entrar', async () => {
      alPedido = () => ({ status: 401, cuerpo: { detail: 'No autorizado' } });
      const id = await encolar();
      await reposo();

      expect(servicio.estadoCola()).toBe('pausada_sesion');
      expect(servicio.motivoPausa()).toContain('Inicia sesión');
      expect(await guardado(id)).toMatchObject({ estado: 'pendiente', ultimo_error: 'sesion_vencida' });

      // Ni la red, ni el botón, ni el tiempo la reanudan: hace falta volver a entrar.
      entorno.volvio.next();
      void servicio.enviarAhora();
      await avanzar(600_000);
      expect(peticiones).toHaveLength(1);

      alPedido = cobrar;
      entorno.alcance.set(null);
      TestBed.tick();
      await reposo();
      expect(servicio.pedidos()).toEqual([]);
      expect(servicio.estadoCola()).toBe('pausada_sesion');

      entorno.alcance.set({ empresaId: EMPRESA, usuarioId: USUARIO });
      TestBed.tick();
      await reposo();

      expect((await guardado(id))?.estado).toBe('cobrado');
      expect(peticiones.map((p) => p.operacionId)).toEqual([id, id]);
    });

    it('otra persona que entra no hereda la pausa ni ve pedidos ajenos', async () => {
      alPedido = () => ({ status: 401, cuerpo: { detail: 'No autorizado' } });
      await encolar();
      await reposo();

      entorno.alcance.set(null);
      TestBed.tick();
      entorno.alcance.set({ empresaId: EMPRESA, usuarioId: 9 });
      TestBed.tick();
      await reposo();

      expect(servicio.estadoCola()).toBe('inactiva');
      expect(servicio.pedidos()).toEqual([]);
    });

    it('403 (la tienda no puede recibir pedidos): pausa sin rechazar el pedido; "Reintentar" lo vuelve a intentar', async () => {
      alPedido = () => ({ status: 403, cuerpo: { detail: 'x', codigo: 'suscripcion_no_activa', mensaje: 'x' } });
      const id = await encolar();
      await reposo();

      expect(servicio.estadoCola()).toBe('pausada');
      expect(servicio.motivoPausa()).toContain('no puede recibir pedidos');
      expect(await guardado(id)).toMatchObject({ estado: 'pendiente', ultimo_error: 'suscripcion_no_activa' });
      await avanzar(600_000);
      expect(peticiones).toHaveLength(1);

      alPedido = cobrar;
      void servicio.enviarAhora();
      await reposo();
      expect((await guardado(id))?.estado).toBe('cobrado');
    });

    it('422: el pedido no es válido, no se cobró nada; queda a la vista para descartarlo y no se reintenta', async () => {
      alPedido = () => ({ status: 422, cuerpo: { detail: [{ msg: 'mal' }] } });
      const id = await encolar();
      await reposo();
      await avanzar(600_000);

      expect(peticiones).toHaveLength(1);
      expect(await guardado(id)).toMatchObject({ estado: 'rechazado', motivo: 'pedido_invalido', mensaje: MENSAJE_PEDIDO_INVALIDO });
    });
  });

  // ---- Caducidad de 7 días ----------------------------------------------------------------------------------------------------

  describe('caducidad de 7 días', () => {
    const DIA = 24 * 60 * 60 * 1000;

    it('el plazo es de 7 días y vive en un solo lugar (la config)', () => {
      expect(PEDIDO_CADUCA_DIAS).toBe(7);
      expect(PEDIDO_CADUCA_MS).toBe(7 * DIA);
      expect(MENSAJE_PEDIDO_VENCIDO).toBe('Venció: pasaron más de 7 días sin conexión');
    });

    it('un pedido de más de 7 días NO se envía: pasa a vencido, con su mensaje, y deja de contar como pendiente', async () => {
      entorno.enLinea.set(false);
      const id = await encolar();
      await reposo();
      expect(servicio.pendientes()).toHaveLength(1);

      vi.setSystemTime(Date.now() + 7 * DIA + 60_000);
      entorno.enLinea.set(true);
      entorno.volvio.next();
      await reposo();

      expect(peticiones).toHaveLength(0);
      expect(await guardado(id)).toMatchObject({ estado: 'vencido', motivo: 'pedido_vencido', mensaje: MENSAJE_PEDIDO_VENCIDO, intentos: 0 });
      expect(servicio.pendientes()).toHaveLength(0);
      expect(servicio.sinVer()).toHaveLength(0);
      // Sigue en la lista para poder descartarlo.
      expect(servicio.pedidos().map((p) => p.estado)).toEqual(['vencido']);
    });

    it('sin conexión también se marca vencido (el contador no cuenta pedidos que ya no saldrán)', async () => {
      entorno.enLinea.set(false);
      const id = await encolar();
      await reposo();

      vi.setSystemTime(Date.now() + 8 * DIA);
      void servicio.enviarAhora();
      await reposo();

      expect(peticiones).toHaveLength(0);
      expect((await guardado(id))?.estado).toBe('vencido');
      expect(servicio.pendientes()).toHaveLength(0);
    });

    it('con 6 días y 23 horas todavía se envía', async () => {
      entorno.enLinea.set(false);
      const id = await encolar();
      await reposo();

      vi.setSystemTime(Date.now() + 7 * DIA - 3_600_000);
      entorno.enLinea.set(true);
      entorno.volvio.next();
      await reposo();

      expect(peticiones.map((p) => p.operacionId)).toEqual([id]);
      expect((await guardado(id))?.estado).toBe('cobrado');
    });

    it('el chequeo corre antes de CADA envío: el viejo vence y el reciente sale en el mismo ciclo', async () => {
      entorno.enLinea.set(false);
      const viejo = await encolar(1);
      vi.setSystemTime(Date.now() + 5 * DIA);
      const reciente = await encolar(2);

      vi.setSystemTime(Date.now() + 3 * DIA); // el viejo ya pasó los 7 días; el reciente lleva 3
      entorno.enLinea.set(true);
      entorno.volvio.next();
      await reposo();

      expect(peticiones.map((p) => p.operacionId)).toEqual([reciente]);
      expect((await guardado(viejo))?.estado).toBe('vencido');
      expect((await guardado(reciente))?.estado).toBe('cobrado');
    });

    it('si el servidor rechaza con pedido_vencido es un rechazo FINAL con mensaje amigable y no se reenvía', async () => {
      alPedido = (c) => ({
        cuerpo: respuesta(c.operacion_id, 'rechazado', { motivo: 'pedido_vencido', mensaje: 'fecha_pedido fuera de plazo' }),
      });
      const id = await encolar();
      await reposo();
      await avanzar(600_000);

      expect(peticiones).toHaveLength(1);
      expect(await guardado(id)).toMatchObject({ estado: 'rechazado', motivo: 'pedido_vencido', mensaje: MENSAJE_PEDIDO_VENCIDO_SERVIDOR });
      expect(MENSAJE_PEDIDO_VENCIDO_SERVIDOR).toContain('pasaron más de 7 días');
      expect(mensajes.at(-1)?.detail).toBe(MENSAJE_PEDIDO_VENCIDO_SERVIDOR);
    });

    it('un pedido vencido se puede descartar, y no se envía aunque vuelva la red', async () => {
      entorno.enLinea.set(false);
      const id = await encolar();
      vi.setSystemTime(Date.now() + 8 * DIA);
      void servicio.enviarAhora();
      await reposo();
      expect((await guardado(id))?.estado).toBe('vencido');

      entorno.enLinea.set(true);
      entorno.volvio.next();
      await reposo();
      expect(peticiones).toHaveLength(0);

      expect(await servicio.descartar(id)).toBe(true);
      expect(servicio.pedidos()).toEqual([]);
    });
  });

  // ---- Borrarlo todo al salir -------------------------------------------------------------------------------------------------

  describe('borrarTodoDeEstaCuenta', () => {
    it('quita pedidos sin enviar, resueltos y carrito de esta cuenta, y deja los de otras', async () => {
      entorno.enLinea.set(false);
      await encolar(1);
      await entorno.repo().registrarPedido(pedido(5, { estado: 'cobrado' }));
      await entorno.repo().agregarLinea(linea(2), 5);
      await entorno.repo(EMPRESA, 9).registrarPedido(pedido(7, { usuario_id: 9 }));

      expect(await servicio.borrarTodoDeEstaCuenta()).toBe(true);

      expect(await entorno.repo().pedidos()).toEqual([]);
      expect(await entorno.repo().carrito()).toEqual([]);
      expect(servicio.pedidos()).toEqual([]);
      expect(await entorno.repo(EMPRESA, 9).pedidos()).toHaveLength(1);
    });
  });


  describe('descartar y ver resultados', () => {
    it('descarta un pedido que todavía no salió; uno cobrado no se puede descartar', async () => {
      entorno.enLinea.set(false);
      const pendiente = await encolar(1);
      expect(await servicio.descartar(pendiente)).toBe(true);
      expect(servicio.pedidos()).toEqual([]);

      entorno.enLinea.set(true);
      const cobrado = await encolar(2);
      await reposo();
      expect(await servicio.descartar(cobrado)).toBe(false);
      expect((await guardado(cobrado))?.estado).toBe('cobrado');
    });

    it('un pedido descartado no se envía nunca', async () => {
      entorno.enLinea.set(false);
      const id = await encolar();
      await servicio.descartar(id);

      entorno.enLinea.set(true);
      entorno.volvio.next();
      await reposo();

      expect(peticiones).toHaveLength(0);
    });

    it('marcarVistos quita los resultados nuevos pero conserva los pedidos', async () => {
      await encolar();
      await reposo();
      expect(servicio.sinVer()).toHaveLength(1);

      await servicio.marcarVistos();

      expect(servicio.sinVer()).toHaveLength(0);
      expect(servicio.pedidos()).toHaveLength(1);
    });
  });
});
