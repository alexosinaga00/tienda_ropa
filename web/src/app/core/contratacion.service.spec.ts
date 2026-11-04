import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../environments/environment';
import { CLAVE_PEDIDO_CONTRATACION, ContratacionService, esUrlHttps } from './contratacion.service';
import { SIN_TOAST_ERROR } from './http-contexts';
import { errorDeContratacion } from './mensajes-contratacion';
import { PedidoSolicitud, PruebaSolicitud } from './models/contratacion.models';

const BASE = `${environment.apiUrl}/public/contratacion`;

const PRUEBA: PruebaSolicitud = {
  nombre: 'Mi Boutique',
  plan_codigo: 'basico',
  administrador: { nombre: 'Ana', apellido: 'Rojas', email: 'ana@miboutique.bo', password: 'clave-segura-1' },
};

describe('ContratacionService', () => {
  let servicio: ContratacionService;
  let http: HttpTestingController;

  beforeEach(() => {
    sessionStorage.clear();
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    servicio = TestBed.inject(ContratacionService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    sessionStorage.clear();
  });

  it('prueba: POST /contratacion/prueba con el cuerpo tal cual y sin toast de error', () => {
    servicio.iniciarPrueba(PRUEBA).subscribe();
    const req = http.expectOne(`${BASE}/prueba`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(PRUEBA);
    expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    req.flush({});
  });

  it('crear pedido: POST /contratacion/pedidos con el periodo y SIN montos', () => {
    const pedido: PedidoSolicitud = { ...PRUEBA, periodo: 'anual' };
    servicio.crearPedido(pedido).subscribe();
    const req = http.expectOne(`${BASE}/pedidos`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(pedido);
    expect(Object.keys(req.request.body)).not.toContain('monto_bs');
    expect(Object.keys(req.request.body)).not.toContain('monto_usd');
    expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    req.flush({});
  });

  it('consultar, capturar y cancelar usan el token en la ruta (codificado)', () => {
    servicio.consultarPedido('abc').subscribe();
    const consulta = http.expectOne(`${BASE}/pedidos/abc`);
    expect(consulta.request.method).toBe('GET');
    consulta.flush({});

    servicio.capturarPedido('abc').subscribe();
    const captura = http.expectOne(`${BASE}/pedidos/abc/capturar`);
    expect(captura.request.method).toBe('POST');
    expect(captura.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    captura.flush({});

    servicio.cancelarPedido('abc').subscribe();
    const cancelacion = http.expectOne(`${BASE}/pedidos/abc/cancelar`);
    expect(cancelacion.request.method).toBe('POST');
    cancelacion.flush({});

    servicio.consultarPedido('a/b?c').subscribe();
    http.expectOne(`${BASE}/pedidos/a%2Fb%3Fc`).flush({});
  });

  it('el token del pedido se guarda, se lee y se limpia en sessionStorage', () => {
    expect(servicio.leerToken()).toBeNull();
    servicio.guardarToken('tok-1');
    expect(sessionStorage.getItem(CLAVE_PEDIDO_CONTRATACION)).toBe('tok-1');
    expect(servicio.leerToken()).toBe('tok-1');
    servicio.limpiarToken();
    expect(servicio.leerToken()).toBeNull();
  });

  it('sin sessionStorage (datos bloqueados) no lanza', () => {
    const original = Object.getOwnPropertyDescriptor(window, 'sessionStorage');
    Object.defineProperty(window, 'sessionStorage', {
      configurable: true,
      get() {
        throw new Error('bloqueado');
      },
    });
    try {
      expect(() => servicio.guardarToken('x')).not.toThrow();
      expect(servicio.leerToken()).toBeNull();
      expect(() => servicio.limpiarToken()).not.toThrow();
    } finally {
      if (original) Object.defineProperty(window, 'sessionStorage', original);
    }
  });

  it('solo se acepta una dirección https para ir a PayPal', () => {
    expect(esUrlHttps('https://www.sandbox.paypal.com/checkoutnow?token=1')).toBe(true);
    expect(esUrlHttps('http://www.paypal.com/x')).toBe(false);
    expect(esUrlHttps('javascript:alert(1)')).toBe(false);
    expect(esUrlHttps('data:text/html,hola')).toBe(false);
    expect(esUrlHttps('no es url')).toBe(false);
    expect(esUrlHttps('')).toBe(false);
    expect(esUrlHttps(null)).toBe(false);
  });
});

describe('errorDeContratacion', () => {
  function falla(status: number, cuerpo: unknown): HttpErrorResponse {
    return new HttpErrorResponse({ status, error: cuerpo });
  }

  it.each([
    ['plan_sin_precio', 409, 'precio'],
    ['nombre_empresa_reservado', 422, 'no se puede usar'],
    ['prueba_ya_usada', 409, 'prueba gratuita'],
    ['paypal_no_disponible', 503, 'PayPal no responde'],
    ['pago_no_aprobado', 409, 'aprobado'],
    ['pago_no_coincide', 409, 'no coincide'],
    ['pagado_sin_empresa', 409, 'soporte'],
    ['pedido_vencido', 409, 'venció'],
    ['pedido_cancelado', 409, 'cancelado'],
    ['pedido_fallido', 409, 'no se pudo completar'],
  ])('%s (%i) se explica en lenguaje claro, sin el código', (codigo, status, fragmento) => {
    const error = errorDeContratacion(falla(status, { detail: codigo, codigo, mensaje: 'texto del servidor' }));
    expect(error.codigo).toBe(codigo);
    expect(error.mensaje).toContain(fragmento);
    expect(error.mensaje).not.toContain(codigo);
  });

  it('solo es reintentable lo que puede funcionar al repetir', () => {
    expect(errorDeContratacion(falla(503, { detail: 'x', codigo: 'paypal_no_disponible', mensaje: 'm' })).reintentable).toBe(
      true,
    );
    expect(errorDeContratacion(falla(0, null)).reintentable).toBe(true);
    expect(errorDeContratacion(falla(429, null)).reintentable).toBe(true);
    expect(errorDeContratacion(falla(409, { detail: 'x', codigo: 'pagado_sin_empresa', mensaje: 'm' })).reintentable).toBe(
      false,
    );
    expect(errorDeContratacion(falla(409, { detail: 'x', codigo: 'pedido_vencido', mensaje: 'm' })).reintentable).toBe(false);
  });

  it('un código desconocido usa el mensaje del servidor', () => {
    const error = errorDeContratacion(falla(409, { detail: 'nuevo', codigo: 'nuevo', mensaje: 'Un aviso del servidor' }));
    expect(error.mensaje).toBe('Un aviso del servidor');
  });

  it('el 409 de nombre repetido llega solo con detail', () => {
    const error = errorDeContratacion(falla(409, { detail: 'Ya existe una empresa con ese nombre' }));
    expect(error.codigo).toBe('nombre_repetido');
    expect(error.mensaje).toContain('Ya existe una empresa');
  });

  it('404 de plan, 404 de pedido, 422, 429, sin red y error raro', () => {
    expect(errorDeContratacion(falla(404, { detail: 'Plan no encontrado' })).codigo).toBe('plan_no_encontrado');
    expect(errorDeContratacion(falla(404, { detail: 'Pedido no encontrado' })).codigo).toBe('pedido_no_encontrado');
    expect(errorDeContratacion(falla(422, { detail: [{ msg: 'x' }] })).codigo).toBe('datos_invalidos');
    expect(errorDeContratacion(falla(429, null)).codigo).toBe('demasiados_intentos');
    expect(errorDeContratacion(falla(0, null)).codigo).toBe('sin_conexion');
    expect(errorDeContratacion(falla(500, null)).codigo).toBe('error_inesperado');
    expect(errorDeContratacion(new Error('x')).codigo).toBe('error_inesperado');
  });
});
