import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../../../environments/environment';
import { SIN_TOAST_ERROR } from '../../../core/http-contexts';
import { PedidoDiferidoCrear } from '../../../core/models/metodo-pago.models';
import { MetodoPagoService, mensajeErrorMetodoPago } from './metodo-pago.service';
import { PedidosDiferidosService } from './pedidos-diferidos.service';

const API = environment.apiUrl;

describe('MetodoPagoService', () => {
  let http: HttpTestingController;
  let servicio: MetodoPagoService;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
    servicio = TestBed.inject(MetodoPagoService);
  });

  afterEach(() => http.verify());

  it('estado: GET /metodos-pago/paypal, con el error en la pantalla (sin aviso global)', () => {
    let respuesta: unknown;
    servicio.estado().subscribe((r) => (respuesta = r));

    const peticion = http.expectOne(`${API}/metodos-pago/paypal`);
    expect(peticion.request.method).toBe('GET');
    expect(peticion.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    peticion.flush({ guardado: true, correo_paypal: 'j***@gmail.com', guardado_en: '2026-11-06T10:00:00-04:00' });
    expect(respuesta).toEqual({ guardado: true, correo_paypal: 'j***@gmail.com', guardado_en: '2026-11-06T10:00:00-04:00' });
  });

  it('iniciar: manda solo el canal (nunca las URLs de retorno)', () => {
    servicio.iniciar('web').subscribe();

    const peticion = http.expectOne(`${API}/metodos-pago/paypal/iniciar`);
    expect(peticion.request.method).toBe('POST');
    expect(peticion.request.body).toEqual({ canal: 'web' });
    expect(peticion.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    peticion.flush({ url_aprobacion: 'https://paypal.test/aprobar', token_preparacion: 'tok' });
  });

  it('confirmar: manda el token de preparación', () => {
    servicio.confirmar('tok-1').subscribe();

    const peticion = http.expectOne(`${API}/metodos-pago/paypal/confirmar`);
    expect(peticion.request.method).toBe('POST');
    expect(peticion.request.body).toEqual({ token_preparacion: 'tok-1' });
    expect(peticion.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    peticion.flush({ guardado: true, correo_paypal: null, guardado_en: null });
  });

  it('quitar: DELETE sin aviso global', () => {
    servicio.quitar().subscribe();

    const peticion = http.expectOne(`${API}/metodos-pago/paypal`);
    expect(peticion.request.method).toBe('DELETE');
    expect(peticion.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    peticion.flush(null, { status: 204, statusText: 'No Content' });
  });
});

describe('mensajeErrorMetodoPago', () => {
  const error = (status: number, cuerpo: unknown) => new HttpErrorResponse({ status, error: cuerpo });

  it('explica en palabras los errores conocidos', () => {
    expect(mensajeErrorMetodoPago(error(0, null))).toContain('conexión');
    expect(mensajeErrorMetodoPago(error(503, { detail: 'x', codigo: 'paypal_no_disponible', mensaje: 'x' }))).toContain('PayPal no responde');
    expect(mensajeErrorMetodoPago(error(409, { detail: 'x', codigo: 'paypal_no_aprobado', mensaje: 'x' }))).toContain('No terminaste de autorizar');
    expect(mensajeErrorMetodoPago(error(404, { detail: 'No encontrado' }))).toContain('ya no es válido');
  });

  it('usa el mensaje del servidor si lo trae y un texto general si no', () => {
    expect(mensajeErrorMetodoPago(error(409, { detail: 'x', codigo: 'otro', mensaje: 'Tu suscripción venció.' }))).toBe('Tu suscripción venció.');
    expect(mensajeErrorMetodoPago(error(500, null))).toContain('No se pudo completar');
    expect(mensajeErrorMetodoPago('algo raro')).toContain('No se pudo completar');
  });
});

describe('PedidosDiferidosService', () => {
  it('POST /pedidos-diferidos con el cuerpo tal cual y sin aviso global de error', () => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    const http = TestBed.inject(HttpTestingController);
    const pedido: PedidoDiferidoCrear = {
      operacion_id: '00000000-0000-4000-8000-000000000001',
      sucursal_id: 3,
      costo_envio: '0.00',
      lineas: [{ variante_id: 10, cantidad: 2 }],
      total_maximo: '398.00',
      fecha_pedido: '2026-11-06T14:03:00-04:00',
    };

    TestBed.inject(PedidosDiferidosService).enviar(pedido).subscribe();

    const peticion = http.expectOne(`${API}/pedidos-diferidos`);
    expect(peticion.request.method).toBe('POST');
    expect(peticion.request.body).toEqual(pedido);
    expect(peticion.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    peticion.flush({});
    http.verify();
  });
});
