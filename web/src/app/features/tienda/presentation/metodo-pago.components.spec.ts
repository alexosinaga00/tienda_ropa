import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { MessageService } from 'primeng/api';
import { environment } from '../../../../environments/environment';
import { ConectividadService } from '../../../core/conectividad.service';
import { nuevoEntorno } from '../../../core/offline-cliente/ayudas-prueba';
import { ClienteOfflineService } from '../../../core/offline-cliente/cliente-offline.service';
import { TiendaActualService } from '../state/tienda-actual.service';
import { MetodoPagoComponent } from './metodo-pago.component';
import { PaypalGuardadoComponent } from './paypal-guardado.component';

const API = environment.apiUrl;
const URL_ESTADO = `${API}/metodos-pago/paypal`;

const GUARDADO = { guardado: true, correo_paypal: 'j***@gmail.com', guardado_en: '2026-11-05T10:00:00-04:00' };
const SIN_GUARDAR = { guardado: false, correo_paypal: null, guardado_en: null };

let entorno: ReturnType<typeof nuevoEntorno>;
let http: HttpTestingController;

function configurar(extra: object[] = []): void {
  TestBed.configureTestingModule({
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      MessageService,
      { provide: ClienteOfflineService, useValue: entorno.cliente },
      { provide: ConectividadService, useValue: entorno.conectividad },
      ...extra,
    ],
  });
  TestBed.inject(TiendaActualService).fijar('acme', 'lista', { codigo: 'acme', nombre: 'Acme', logo_url: null, color_acento: null });
  http = TestBed.inject(HttpTestingController);
}

async function esperar(fixture: ComponentFixture<unknown>): Promise<void> {
  for (let i = 0; i < 30; i++) await new Promise<void>((r) => setTimeout(r, 0));
  fixture.detectChanges();
}

const texto = (el: HTMLElement) => (el.textContent ?? '').replace(/\s+/g, ' ').trim();

beforeEach(() => {
  entorno = nuevoEntorno();
});

afterEach(async () => {
  // Deja terminar lo que las pantallas y servicios aún leen de IndexedDB antes de cerrarla.
  for (let i = 0; i < 20; i++) await new Promise<void>((r) => setTimeout(r, 0));
  TestBed.resetTestingModule();
  await entorno.cerrar();
});

describe('MetodoPagoComponent', () => {
  let fixture: ComponentFixture<MetodoPagoComponent>;
  let el: HTMLElement;

  async function montar(respuesta: object | 'sin_red' | 'error_500' | null): Promise<void> {
    configurar();
    fixture = TestBed.createComponent(MetodoPagoComponent);
    el = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
    const peticion = http.expectOne(URL_ESTADO);
    if (respuesta === 'sin_red') peticion.error(new ProgressEvent('error'));
    else if (respuesta === 'error_500') peticion.flush({ detail: 'Falla' }, { status: 500, statusText: 'Error' });
    else peticion.flush(respuesta);
    await esperar(fixture);
  }

  const q = (estado: string) => el.querySelector<HTMLElement>(`[data-estado="${estado}"]`);
  const boton = (estado: string) => q(estado) as HTMLButtonElement | null;

  it('sin PayPal guardado lo dice y ofrece "Guardar mi PayPal"', async () => {
    await montar(SIN_GUARDAR);

    expect(q('paypal-no-guardado')?.textContent).toContain('Sin guardar');
    expect(boton('guardar-paypal')!.disabled).toBe(false);
    expect(texto(boton('guardar-paypal')!)).toContain('Guardar mi PayPal');
    expect(q('quitar-paypal')).toBeNull();
  });

  it('explica que PayPal guarda el medio de pago y que nunca se ven datos de tarjeta', async () => {
    await montar(SIN_GUARDAR);

    const t = texto(el);
    expect(t).toContain('PayPal guarda tu medio de pago');
    expect(t).toContain('nunca vemos ni guardamos los datos de tu tarjeta');
    expect(t).toContain('siempre hasta el total que veas y aceptes');
  });

  it('"Guardar mi PayPal" inicia con canal web y redirige a la URL de aprobación', async () => {
    await montar(SIN_GUARDAR);
    const redirigir = vi.spyOn(fixture.componentInstance as unknown as { redirigir(url: string): void }, 'redirigir').mockImplementation(() => undefined);

    boton('guardar-paypal')!.click();
    const peticion = http.expectOne(`${URL_ESTADO}/iniciar`);
    expect(peticion.request.body).toEqual({ canal: 'web' });
    peticion.flush({ url_aprobacion: 'https://www.sandbox.paypal.com/vault/approve?token=abc', token_preparacion: 'tok' });
    fixture.detectChanges();

    expect(redirigir).toHaveBeenCalledWith('https://www.sandbox.paypal.com/vault/approve?token=abc');
    expect(boton('guardar-paypal')!.disabled).toBe(true);
  });

  it('si PayPal falla (503) lo dice en la pantalla y deja volver a intentar', async () => {
    await montar(SIN_GUARDAR);
    const redirigir = vi.spyOn(fixture.componentInstance as unknown as { redirigir(url: string): void }, 'redirigir').mockImplementation(() => undefined);

    boton('guardar-paypal')!.click();
    http
      .expectOne(`${URL_ESTADO}/iniciar`)
      .flush({ detail: 'PayPal no responde', codigo: 'paypal_no_disponible', mensaje: 'x' }, { status: 503, statusText: 'Service Unavailable' });
    fixture.detectChanges();

    expect(redirigir).not.toHaveBeenCalled();
    expect(q('error-metodo')?.textContent).toContain('PayPal no responde en este momento');
    expect(boton('guardar-paypal')!.disabled).toBe(false);
  });

  it('no sigue una URL de aprobación que no sea http(s)', async () => {
    await montar(SIN_GUARDAR);
    const redirigir = vi.spyOn(fixture.componentInstance as unknown as { redirigir(url: string): void }, 'redirigir').mockImplementation(() => undefined);

    boton('guardar-paypal')!.click();
    http.expectOne(`${URL_ESTADO}/iniciar`).flush({ url_aprobacion: 'javascript:alert(1)', token_preparacion: 'tok' });
    fixture.detectChanges();

    expect(redirigir).not.toHaveBeenCalled();
    expect(q('error-metodo')).not.toBeNull();
  });

  it('con PayPal guardado muestra el correo enmascarado que manda el servidor, y lo recuerda para decidir sin red', async () => {
    await montar(GUARDADO);

    expect(q('paypal-guardado')?.textContent).toContain('Guardado');
    expect(q('correo-paypal')?.textContent).toBe('j***@gmail.com');
    expect(texto(boton('guardar-paypal')!)).toContain('Cambiar mi PayPal');
    expect(await entorno.repo().leerMeta('metodo_pago')).toMatchObject({ guardado: true, correo_paypal: 'j***@gmail.com' });
  });

  it('"Quitar" pide confirmación; al confirmar borra y queda "Sin guardar"', async () => {
    await montar(GUARDADO);

    boton('quitar-paypal')!.click();
    fixture.detectChanges();
    expect(q('confirmar-quitar')).not.toBeNull();
    http.expectNone({ method: 'DELETE', url: URL_ESTADO });

    boton('confirmar-quitar-si')!.click();
    const peticion = http.expectOne(URL_ESTADO);
    expect(peticion.request.method).toBe('DELETE');
    peticion.flush(null, { status: 204, statusText: 'No Content' });
    await esperar(fixture);

    expect(q('paypal-no-guardado')).not.toBeNull();
    expect(q('confirmar-quitar')).toBeNull();
    expect(await entorno.repo().leerMeta('metodo_pago')).toMatchObject({ guardado: false, correo_paypal: null });
  });

  it('cancelar la confirmación no borra nada', async () => {
    await montar(GUARDADO);

    boton('quitar-paypal')!.click();
    fixture.detectChanges();
    Array.from(el.querySelectorAll<HTMLButtonElement>('.confirmar button'))
      .find((b) => b.textContent?.includes('Cancelar'))!
      .click();
    fixture.detectChanges();

    http.expectNone({ method: 'DELETE', url: URL_ESTADO });
    expect(q('confirmar-quitar')).toBeNull();
    expect(q('paypal-guardado')).not.toBeNull();
  });

  it('sin conexión deshabilita guardar y quitar con el motivo, y muestra lo que se recordaba', async () => {
    await entorno.repo().guardarMeta('metodo_pago', { guardado: true, correo_paypal: 'j***@gmail.com', guardado_en: null, verificado_en: 'x' });
    entorno.enLinea.set(false);
    configurar();
    fixture = TestBed.createComponent(MetodoPagoComponent);
    el = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
    http.expectOne(URL_ESTADO).error(new ProgressEvent('error'));
    await esperar(fixture);

    expect(q('sin-conexion')?.textContent).toContain('Sin conexión');
    expect(boton('guardar-paypal')!.disabled).toBe(true);
    expect(boton('guardar-paypal')!.getAttribute('title')).toBe('Requiere conexión');
    expect(boton('quitar-paypal')!.disabled).toBe(true);
    expect(q('motivo-sin-conexion')?.textContent).toContain('Necesitas conexión');
    // Se ve lo recordado y se avisa que lo es; no se muestra un error.
    expect(q('correo-paypal')?.textContent).toBe('j***@gmail.com');
    expect(q('dato-recordado')).not.toBeNull();
    expect(q('error-metodo')).toBeNull();

    boton('guardar-paypal')!.click();
    http.expectNone(`${URL_ESTADO}/iniciar`);
  });

  it('con el servidor caído y conexión muestra el error y no inventa un estado', async () => {
    await montar('error_500');

    expect(q('error-metodo')).not.toBeNull();
    expect(q('paypal-guardado')).toBeNull();
    expect(q('paypal-no-guardado')).toBeNull();
    expect(texto(el)).toContain('No pudimos consultar tu método de pago');
  });
});

describe('PaypalGuardadoComponent (retorno de PayPal)', () => {
  let fixture: ComponentFixture<PaypalGuardadoComponent>;
  let el: HTMLElement;

  async function montar(consulta: Record<string, string>): Promise<void> {
    configurar([{ provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: convertToParamMap(consulta) } } }]);
    fixture = TestBed.createComponent(PaypalGuardadoComponent);
    el = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
  }

  const q = (estado: string) => el.querySelector<HTMLElement>(`[data-estado="${estado}"]`);

  it('con approval_token_id confirma con el servidor y muestra el éxito', async () => {
    await montar({ approval_token_id: 'tok-123' });
    expect(q('confirmando')).not.toBeNull();

    const peticion = http.expectOne(`${URL_ESTADO}/confirmar`);
    expect(peticion.request.body).toEqual({ token_preparacion: 'tok-123' });
    peticion.flush(GUARDADO);
    await esperar(fixture);

    expect(q('paypal-exito')?.textContent).toContain('guardamos tu PayPal');
    expect(q('paypal-exito')?.textContent).toContain('j***@gmail.com');
    expect(q('volver-metodo-pago')?.getAttribute('href')).toBe('/t/acme/mi-cuenta/metodo-pago');
    expect(await entorno.repo().leerMeta('metodo_pago')).toMatchObject({ guardado: true });
  });

  it('al recargar la página vuelve a confirmar y da el mismo resultado (confirmar es idempotente)', async () => {
    await montar({ approval_token_id: 'tok-123' });
    http.expectOne(`${URL_ESTADO}/confirmar`).flush(GUARDADO);
    await esperar(fixture);
    expect(q('paypal-exito')).not.toBeNull();

    TestBed.resetTestingModule();
    entorno = nuevoEntorno();
    await montar({ approval_token_id: 'tok-123' });
    const otra = http.expectOne(`${URL_ESTADO}/confirmar`);
    expect(otra.request.body).toEqual({ token_preparacion: 'tok-123' });
    otra.flush(GUARDADO);
    await esperar(fixture);

    expect(q('paypal-exito')).not.toBeNull();
  });

  it('cancelado=1 no llama al servidor y dice que no se guardó nada', async () => {
    await montar({ cancelado: '1' });

    http.expectNone(`${URL_ESTADO}/confirmar`);
    expect(q('paypal-cancelado')?.textContent).toContain('No guardamos tu PayPal');
    expect(q('paypal-cancelado')?.textContent).toContain('no se cobró nada');
    expect(q('volver-metodo-pago')).not.toBeNull();
  });

  it('sin token en el enlace lo dice y lleva de vuelta', async () => {
    await montar({});

    http.expectNone(`${URL_ESTADO}/confirmar`);
    expect(q('paypal-sin-datos')).not.toBeNull();
    expect(q('volver-metodo-pago')).not.toBeNull();
  });

  it('si el cliente no aprobó (409) lo explica y "Reintentar" vuelve a confirmar', async () => {
    await montar({ approval_token_id: 'tok-123' });
    http
      .expectOne(`${URL_ESTADO}/confirmar`)
      .flush({ detail: 'x', codigo: 'paypal_no_aprobado', mensaje: 'x' }, { status: 409, statusText: 'Conflict' });
    await esperar(fixture);

    expect(q('paypal-error')?.textContent).toContain('No terminaste de autorizar');
    (q('reintentar-confirmar') as HTMLButtonElement).click();
    http.expectOne(`${URL_ESTADO}/confirmar`).flush(GUARDADO);
    await esperar(fixture);

    expect(q('paypal-exito')).not.toBeNull();
    expect(q('paypal-error')).toBeNull();
  });

  it('un token ajeno o vencido (404) muestra un error claro, no una pantalla rota', async () => {
    await montar({ approval_token_id: 'ajeno' });
    http.expectOne(`${URL_ESTADO}/confirmar`).flush({ detail: 'No encontrado' }, { status: 404, statusText: 'Not Found' });
    await esperar(fixture);

    expect(q('paypal-error')?.textContent).toContain('ya no es válido');
    expect(q('volver-metodo-pago')).not.toBeNull();
  });
});
