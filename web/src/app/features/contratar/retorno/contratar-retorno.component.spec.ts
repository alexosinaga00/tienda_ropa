import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { MessageService } from 'primeng/api';
import { environment } from '../../../../environments/environment';
import { CLAVE_PEDIDO_CONTRATACION } from '../../../core/contratacion.service';
import { ContratarRetornoComponent } from './contratar-retorno.component';

const PEDIDOS = `${environment.apiUrl}/public/contratacion/pedidos`;

const PAGADO = {
  estado: 'completado',
  empresa_codigo: 'mi-boutique',
  empresa_nombre: 'Mi Boutique',
  plan_codigo: 'basico',
  plan_nombre: 'Básico',
  periodo: 'mensual',
  es_prueba: false,
  fecha_inicio: '2026-11-04',
  fecha_vencimiento: '2026-12-04',
  monto_bs: '120.00',
  monto_usd: '17.24',
};

const CANCELADO = {
  estado: 'cancelado',
  plan_codigo: 'basico',
  plan_nombre: 'Básico',
  periodo: 'anual',
  monto_bs: '1152.00',
  monto_usd: '165.52',
  tipo_cambio: '6.9600',
  expira_en: '2026-11-04T15:00:00Z',
  empresa_codigo: null,
};

function errorFuncional(codigo: string, status: number) {
  return [{ detail: codigo, codigo, mensaje: 'texto del servidor' }, { status, statusText: 'Error' }] as const;
}

describe('ContratarRetornoComponent', () => {
  let fixture: ComponentFixture<ContratarRetornoComponent>;
  let http: HttpTestingController;

  async function abrir(consulta: string): Promise<void> {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([{ path: 'contratar/retorno', children: [] }]),
        provideHttpClient(),
        provideHttpClientTesting(),
        MessageService,
      ],
    });
    http = TestBed.inject(HttpTestingController);
    await TestBed.inject(Router).navigateByUrl(`/contratar/retorno${consulta}`);
    fixture = TestBed.createComponent(ContratarRetornoComponent);
    fixture.detectChanges();
  }

  function html(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function boton(texto: string): HTMLButtonElement | undefined {
    return Array.from(html().querySelectorAll<HTMLButtonElement>('button')).find((b) => b.textContent?.includes(texto));
  }

  beforeEach(() => sessionStorage.clear());

  afterEach(() => {
    http.verify();
    sessionStorage.clear();
  });

  it('al volver de PayPal cierra el pedido UNA vez y muestra la tienda creada', async () => {
    sessionStorage.setItem(CLAVE_PEDIDO_CONTRATACION, 'tok-1');
    await abrir('?pedido=tok-1');

    expect(html().textContent).toContain('Confirmando tu pago');
    expect(html().querySelector('[aria-busy="true"]')).not.toBeNull();

    const req = http.expectOne(`${PEDIDOS}/tok-1/capturar`);
    expect(req.request.method).toBe('POST');
    req.flush(PAGADO);
    fixture.detectChanges();
    // Re-dibujar no repite la captura (http.verify lo comprueba en afterEach).
    fixture.detectChanges();

    const texto = html().textContent ?? '';
    expect(texto).toContain('Tu tienda está lista');
    expect(texto).toContain('Pago confirmado');
    expect(texto).toContain('Mi Boutique');
    expect(texto).toContain('4 de diciembre de 2026');
    expect(html().querySelector('a[href="/t/mi-boutique"]')).not.toBeNull();
    expect(html().querySelector('a[href="/admin/login"]')).not.toBeNull();
    // El pedido ya está cerrado: no queda el token guardado.
    expect(sessionStorage.getItem(CLAVE_PEDIDO_CONTRATACION)).toBeNull();
    // El token nunca se muestra.
    expect(texto).not.toContain('tok-1');
  });

  it('si la dirección no trae el pedido, usa el token guardado antes de ir a PayPal', async () => {
    sessionStorage.setItem(CLAVE_PEDIDO_CONTRATACION, 'tok-guardado');
    await abrir('');

    http.expectOne(`${PEDIDOS}/tok-guardado/capturar`).flush(PAGADO);
    fixture.detectChanges();
    expect(html().textContent).toContain('Tu tienda está lista');
  });

  it('sin token en ninguna parte no llama a la API y ofrece contratar', async () => {
    await abrir('');

    http.expectNone((r) => r.url.startsWith(PEDIDOS));
    expect(html().textContent).toContain('No encontramos tu pedido');
    expect(html().querySelector('a[href^="/contratar"]')).not.toBeNull();
  });

  it('cancelado=1: cancela el pedido, borra el token y ofrece volver a intentarlo con el mismo plan', async () => {
    sessionStorage.setItem(CLAVE_PEDIDO_CONTRATACION, 'tok-2');
    await abrir('?pedido=tok-2&cancelado=1');

    http.expectNone(`${PEDIDOS}/tok-2/capturar`);
    const req = http.expectOne(`${PEDIDOS}/tok-2/cancelar`);
    expect(req.request.method).toBe('POST');
    req.flush(CANCELADO);
    fixture.detectChanges();

    expect(html().textContent).toContain('Cancelaste el pago');
    expect(html().textContent).toContain('No se cobró nada');
    expect(sessionStorage.getItem(CLAVE_PEDIDO_CONTRATACION)).toBeNull();
    const reintento = Array.from(html().querySelectorAll('a')).find((a) => a.textContent?.includes('Volver a intentarlo'));
    expect(reintento?.getAttribute('href')).toBe('/contratar?modo=pago&plan=basico&periodo=anual');
  });

  it('cancelado=1 sobre un pedido que ya estaba pagado lo cierra en vez de cancelarlo', async () => {
    await abrir('?pedido=tok-3&cancelado=1');

    http.expectOne(`${PEDIDOS}/tok-3/cancelar`).flush(...errorFuncional('pedido_ya_pagado', 409));
    http.expectOne(`${PEDIDOS}/tok-3/capturar`).flush(PAGADO);
    fixture.detectChanges();

    expect(html().textContent).toContain('Tu tienda está lista');
  });

  it('PayPal caído (503): avisa que no se cobró nada, conserva el token y Reintentar vuelve a capturar una sola vez', async () => {
    sessionStorage.setItem(CLAVE_PEDIDO_CONTRATACION, 'tok-4');
    await abrir('?pedido=tok-4');

    http.expectOne(`${PEDIDOS}/tok-4/capturar`).flush(...errorFuncional('paypal_no_disponible', 503));
    fixture.detectChanges();

    expect(html().textContent).toContain('No pudimos confirmar tu pago');
    expect(html().querySelector('[role="alert"]')?.textContent).toContain('No se cobró nada');
    expect(sessionStorage.getItem(CLAVE_PEDIDO_CONTRATACION)).toBe('tok-4');

    const reintentar = boton('Reintentar')!;
    reintentar.click();
    reintentar.click();
    reintentar.click();
    http.expectOne(`${PEDIDOS}/tok-4/capturar`).flush(PAGADO);
    fixture.detectChanges();

    expect(html().textContent).toContain('Tu tienda está lista');
    expect(sessionStorage.getItem(CLAVE_PEDIDO_CONTRATACION)).toBeNull();
  });

  it('pago sin aprobar todavía: ofrece "Comprobar de nuevo" y no borra el pedido', async () => {
    sessionStorage.setItem(CLAVE_PEDIDO_CONTRATACION, 'tok-5');
    await abrir('?pedido=tok-5');

    http.expectOne(`${PEDIDOS}/tok-5/capturar`).flush(...errorFuncional('pago_no_aprobado', 409));
    fixture.detectChanges();

    expect(html().textContent).toContain('Todavía no vemos tu pago aprobado');
    expect(sessionStorage.getItem(CLAVE_PEDIDO_CONTRATACION)).toBe('tok-5');
    boton('Comprobar de nuevo')!.click();
    http.expectOne(`${PEDIDOS}/tok-5/capturar`).flush(PAGADO);
    fixture.detectChanges();
    expect(html().textContent).toContain('Tu tienda está lista');
  });

  it('pagado_sin_empresa: dice que el pago se recibió, manda a soporte y NO ofrece reintentar', async () => {
    sessionStorage.setItem(CLAVE_PEDIDO_CONTRATACION, 'tok-6');
    await abrir('?pedido=tok-6');

    http.expectOne(`${PEDIDOS}/tok-6/capturar`).flush(...errorFuncional('pagado_sin_empresa', 409));
    fixture.detectChanges();

    const texto = html().textContent ?? '';
    expect(texto).toContain('Recibimos tu pago');
    expect(texto).toContain('soporte');
    expect(texto).toContain('No vuelvas a pagar');
    expect(boton('Reintentar')).toBeUndefined();
    expect(boton('Comprobar de nuevo')).toBeUndefined();
    expect(html().textContent).not.toContain('pagado_sin_empresa');
  });

  it.each([
    ['pedido_vencido', 'venció'],
    ['pedido_cancelado', 'cancelado'],
    ['pedido_fallido', 'no se pudo completar'],
    ['pago_no_coincide', 'no coincide'],
  ])('%s: lo explica, borra el token y solo ofrece empezar de nuevo', async (codigo, fragmento) => {
    sessionStorage.setItem(CLAVE_PEDIDO_CONTRATACION, 'tok-7');
    await abrir('?pedido=tok-7');

    http.expectOne(`${PEDIDOS}/tok-7/capturar`).flush(...errorFuncional(codigo, 409));
    fixture.detectChanges();

    expect(html().textContent).toContain(fragmento);
    expect(sessionStorage.getItem(CLAVE_PEDIDO_CONTRATACION)).toBeNull();
    expect(boton('Reintentar')).toBeUndefined();
    expect(Array.from(html().querySelectorAll('a')).some((a) => a.textContent?.includes('Empezar de nuevo'))).toBe(true);
  });

  it('un pedido que no existe (404) lo dice y borra el token', async () => {
    sessionStorage.setItem(CLAVE_PEDIDO_CONTRATACION, 'tok-8');
    await abrir('?pedido=tok-8');

    http.expectOne(`${PEDIDOS}/tok-8/capturar`).flush({ detail: 'Pedido no encontrado' }, { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();

    expect(html().textContent).toContain('No encontramos este pedido');
    expect(sessionStorage.getItem(CLAVE_PEDIDO_CONTRATACION)).toBeNull();
  });

  it('sin conexión: se puede reintentar y el token se conserva', async () => {
    sessionStorage.setItem(CLAVE_PEDIDO_CONTRATACION, 'tok-9');
    await abrir('?pedido=tok-9');

    http.expectOne(`${PEDIDOS}/tok-9/capturar`).error(new ProgressEvent('error'));
    fixture.detectChanges();

    expect(html().textContent).toContain('Revisa tu conexión');
    expect(boton('Reintentar')).toBeDefined();
    expect(sessionStorage.getItem(CLAVE_PEDIDO_CONTRATACION)).toBe('tok-9');
  });
});
