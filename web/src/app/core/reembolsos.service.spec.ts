import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../environments/environment';
import { SIN_TOAST_ERROR } from './http-contexts';
import type { Reembolso } from './models/ventas.models';
import { comoSeDevolvio, estadoReembolso, reemplazarReembolso, sePuedeReintentar } from './reembolsos';
import { ReembolsosService } from './reembolsos.service';

const API = environment.apiUrl;

const REEMBOLSO: Reembolso = {
  id: 31,
  devolucion_id: 5,
  pago_id: 12,
  venta_id: 42,
  sucursal_id: 1,
  metodo: 'paypal',
  monto: '90.00',
  monto_usd: '12.93',
  estado: 'pendiente',
  referencia_externa: null,
  motivo_fallo: null,
  creado_en: '2026-11-08T15:00:00Z',
  completado_en: null,
};

describe('ReembolsosService', () => {
  let http: HttpTestingController;
  let servicio: ReembolsosService;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
    servicio = TestBed.inject(ReembolsosService);
  });

  afterEach(() => http.verify());

  it('lee los reembolsos de una venta sin activar el aviso global de error', () => {
    let recibidos: Reembolso[] | undefined;
    servicio.deVenta(42).subscribe((lista) => (recibidos = lista));

    const peticion = http.expectOne(`${API}/ventas/42/reembolsos`);
    expect(peticion.request.method).toBe('GET');
    expect(peticion.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    peticion.flush([REEMBOLSO]);

    expect(recibidos).toEqual([REEMBOLSO]);
  });

  it('reintenta un reembolso con POST, sin cuerpo y sin aviso global de error', () => {
    let recibido: Reembolso | undefined;
    servicio.reintentar(31).subscribe((r) => (recibido = r));

    const peticion = http.expectOne(`${API}/reembolsos/31/reintentar`);
    expect(peticion.request.method).toBe('POST');
    expect(peticion.request.body).toBeNull();
    expect(peticion.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    peticion.flush({ ...REEMBOLSO, estado: 'reembolsado' });

    expect(recibido?.estado).toBe('reembolsado');
  });

  it('deja pasar el error para que la pantalla lo muestre', () => {
    let estado: number | undefined;
    servicio.reintentar(31).subscribe({ error: (e) => (estado = e.status) });

    http.expectOne(`${API}/reembolsos/31/reintentar`).flush({ detail: 'ya hecho' }, { status: 409, statusText: 'Conflict' });

    expect(estado).toBe(409);
  });
});

describe('textos del reembolso', () => {
  it.each([
    ['efectivo', 'en efectivo, en la tienda'],
    ['paypal', 'a tu PayPal'],
    ['qr', 'por QR'],
    ['qr_online', 'por QR'],
    ['tarjeta', 'a tu tarjeta'],
    ['transferencia', 'por transferencia'],
    ['libelula', 'por el mismo medio con que pagaste'],
  ])('al cliente le dice cómo se devolvió con %s', (metodo, esperado) => {
    expect(comoSeDevolvio(metodo)).toBe(esperado);
  });

  it('al personal le habla del cliente en tercera persona', () => {
    expect(comoSeDevolvio('paypal', 'personal')).toBe('al PayPal del cliente');
    expect(comoSeDevolvio('tarjeta', 'personal')).toBe('a la tarjeta del cliente');
    expect(comoSeDevolvio('otro', 'personal')).toBe('por el mismo medio con que pagó el cliente');
    expect(comoSeDevolvio('efectivo', 'personal')).toBe('en efectivo, en la tienda');
  });

  it('los estados en palabras', () => {
    expect(estadoReembolso('reembolsado')).toEqual({ texto: 'Reembolsado', clase: 'fs-chip--exito' });
    expect(estadoReembolso('pendiente').texto).toBe('En proceso');
    expect(estadoReembolso('pendiente', 'personal').texto).toBe('En proceso');
  });

  it('un fallido: el personal lo ve, el cliente lo ve "En proceso"', () => {
    expect(estadoReembolso('fallido', 'personal')).toEqual({ texto: 'No se pudo reembolsar', clase: 'fs-chip--error' });
    expect(estadoReembolso('fallido', 'cliente').texto).toBe('En proceso');
    expect(estadoReembolso('fallido').texto).toBe('En proceso');
  });

  it('solo se reintenta lo pendiente o fallido', () => {
    expect(sePuedeReintentar({ estado: 'pendiente' })).toBe(true);
    expect(sePuedeReintentar({ estado: 'fallido' })).toBe(true);
    expect(sePuedeReintentar({ estado: 'reembolsado' })).toBe(false);
  });

  it('reemplaza por id o agrega si no estaba', () => {
    const otro = { ...REEMBOLSO, id: 32 };
    const hecho = { ...REEMBOLSO, estado: 'reembolsado' as const };
    expect(reemplazarReembolso([REEMBOLSO, otro], hecho)).toEqual([hecho, otro]);
    expect(reemplazarReembolso([otro], hecho)).toEqual([otro, hecho]);
  });
});
