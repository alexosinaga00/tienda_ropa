import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, provideRouter } from '@angular/router';
import { environment } from '../../../../environments/environment';
import { CheckoutService } from '../state/checkout.service';
import { TiendaActualService } from '../state/tienda-actual.service';
import { CompraDetalleComponent } from './compra-detalle.component';

const API = environment.apiUrl;

function venta(estado: string) {
  return {
    id: 42,
    codigo: 'V-0042',
    canal: 'digital',
    cliente_id: 1,
    sucursal_id: 1,
    cajero_id: null,
    reserva_id: null,
    estado,
    fecha: '2026-11-04T10:00:00',
    subtotal: 100,
    descuento: 0,
    costo_envio: 0,
    total: 100,
    detalle: [
      { id: 5, variante_id: 10, cantidad: 1, precio_unitario: 100, descuento_unitario: 0, costo_unitario: null, subtotal: 100 },
    ],
  };
}

const LOOKUP = [
  { variante_id: 10, producto_id: 1, producto_nombre: 'Polera', imagen_principal: null, talla_codigo: 'M', color_nombre: 'Azul' },
];

describe('CompraDetalleComponent: plazo para cambiar la prenda', () => {
  let http: HttpTestingController;

  function montar() {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: { get: () => '42' } } } },
      ],
    });
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(CompraDetalleComponent);
    fixture.detectChanges();
    return fixture;
  }

  function cargar(fixture: ReturnType<typeof montar>, estado: string) {
    http.expectOne(`${API}/ventas/42/comprobante`).flush(venta(estado));
    http.expectOne((r) => r.url === `${API}/catalogo/variantes/detalle`).flush(LOOKUP);
    fixture.detectChanges();
  }

  const plazo = (vigente: boolean) => ({
    venta_id: 42,
    fecha_venta: '2026-11-04T10:00:00Z',
    plazo_horas: 24,
    vence_en: '2026-11-05T10:00:00Z',
    vigente,
    estado_venta: 'pagada',
  });

  const aviso = (fixture: ReturnType<typeof montar>) =>
    (fixture.nativeElement as HTMLElement).querySelector('[data-estado="plazo-cambio"]');
  const texto = (el: Element | null) => (el?.textContent ?? '').replace(/\s+/g, ' ').trim();

  afterEach(() => http.match(() => true));

  it('una compra pagada dentro del plazo dice hasta cuándo se puede cambiar', () => {
    const fixture = montar();
    cargar(fixture, 'pagada');
    http.expectOne(`${API}/ventas/42/plazo-cambio`).flush(plazo(true));
    fixture.detectChanges();

    expect(texto(aviso(fixture))).toContain('Puedes cambiar tu prenda hasta el');
    expect(texto(aviso(fixture))).toContain('cambia la talla o el color en caja');
    expect(aviso(fixture)?.classList).not.toContain('plazo-cambio--vencido');
  });

  it('pasado el plazo lo dice y no ofrece el cambio', () => {
    const fixture = montar();
    cargar(fixture, 'entregada');
    http.expectOne(`${API}/ventas/42/plazo-cambio`).flush(plazo(false));
    fixture.detectChanges();

    expect(texto(aviso(fixture))).toContain('El plazo para cambiar esta compra venció el');
    expect(texto(aviso(fixture))).not.toContain('Puedes cambiar');
    expect(aviso(fixture)?.classList).toContain('plazo-cambio--vencido');
  });

  it('una compra pendiente de pago no consulta ni muestra el plazo', () => {
    const fixture = montar();
    cargar(fixture, 'pendiente_pago');

    http.expectNone(`${API}/ventas/42/plazo-cambio`);
    expect(aviso(fixture)).toBeNull();
  });

  it('si la consulta del plazo falla, el comprobante se ve igual y sin aviso', () => {
    const fixture = montar();
    cargar(fixture, 'pagada');
    http.expectOne(`${API}/ventas/42/plazo-cambio`).flush({ detail: 'Error' }, { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(aviso(fixture)).toBeNull();
    expect(texto(fixture.nativeElement as HTMLElement)).toContain('V-0042');
    expect(texto(fixture.nativeElement as HTMLElement)).toContain('Polera');
  });
});

describe('CompraDetalleComponent: una compra que quedó sin pagar', () => {
  let http: HttpTestingController;

  function montar() {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: { get: () => '42' } } } },
      ],
    });
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(CompraDetalleComponent);
    fixture.detectChanges();
    http.expectOne(`${API}/ventas/42/comprobante`).flush(venta('pendiente_pago'));
    http.expectOne((r) => r.url === `${API}/catalogo/variantes/detalle`).flush(LOOKUP);
    fixture.detectChanges();
    return fixture;
  }

  const el = (fixture: ReturnType<typeof montar>) => fixture.nativeElement as HTMLElement;
  const texto = (e: Element | null) => (e?.textContent ?? '').replace(/\s+/g, ' ').trim();
  const boton = (fixture: ReturnType<typeof montar>, etiqueta: string) =>
    Array.from(el(fixture).querySelectorAll('button')).find((b) => texto(b) === etiqueta) as HTMLButtonElement;

  afterEach(() => {
    http.match(() => true);
    vi.restoreAllMocks();
  });

  it('ofrece Pagar ahora y Cancelar compra, y no consulta el plazo de cambio', () => {
    const fixture = montar();

    expect(el(fixture).querySelector('[data-estado="compra-pendiente"]')).not.toBeNull();
    expect(texto(el(fixture))).toContain('Esta compra todavía no está pagada');
    expect(boton(fixture, 'Pagar ahora')).toBeTruthy();
    expect(boton(fixture, 'Cancelar compra')).toBeTruthy();
    expect(Array.from(el(fixture).querySelectorAll('.fs-pill')).map((b) => texto(b))).toEqual(['QR', 'PayPal']);
    http.expectNone(`${API}/ventas/42/plazo-cambio`);
  });

  it('Pagar ahora inicia el pago con el método elegido y sigue en la pantalla de estado', () => {
    const ventana = { document: { write: vi.fn() }, location: { href: '' }, close: vi.fn() } as unknown as Window;
    vi.spyOn(window, 'open').mockReturnValue(ventana);
    const fixture = montar();
    const navegar = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    Array.from(el(fixture).querySelectorAll('.fs-pill'))
      .find((b) => texto(b) === 'PayPal')!
      .dispatchEvent(new Event('click'));
    fixture.detectChanges();

    boton(fixture, 'Pagar ahora').click();

    const peticion = http.expectOne(`${API}/pagos/iniciar`);
    expect(peticion.request.body).toEqual({ venta_id: 42, metodo_pago: 'paypal' });
    peticion.flush({ pago: { id: 77, metodo_pago: 'paypal', venta_id: 42 }, url_redireccion: 'https://pasarela.test/p' });
    expect(ventana.location.href).toBe('https://pasarela.test/p');
    expect(navegar).toHaveBeenCalledWith(['/t', 'acme', 'checkout', 'estado', '77']);
    // La pantalla de estado puede reintentar porque la venta quedó en el estado del checkout.
    expect(TestBed.inject(CheckoutService).venta()?.id).toBe(42);
  });

  it('si no se puede iniciar el pago, lo dice, cierra la ventana y deja intentar de nuevo', () => {
    const ventana = { document: { write: vi.fn() }, location: { href: '' }, close: vi.fn() } as unknown as Window;
    vi.spyOn(window, 'open').mockReturnValue(ventana);
    const fixture = montar();

    boton(fixture, 'Pagar ahora').click();
    http.expectOne(`${API}/pagos/iniciar`).flush({ detail: 'x' }, { status: 502, statusText: 'Bad Gateway' });
    fixture.detectChanges();

    expect(texto(el(fixture))).toContain('No se pudo iniciar el pago. Prueba de nuevo.');
    expect(ventana.close).toHaveBeenCalled();
    expect(boton(fixture, 'Pagar ahora').disabled).toBe(false);
  });

  it('Cancelar compra pide confirmación y, al confirmar, libera la compra y avisa que volvió al carrito', () => {
    const fixture = montar();

    boton(fixture, 'Cancelar compra').click();
    fixture.detectChanges();
    expect(texto(el(fixture))).toContain('¿Cancelar esta compra?');
    http.expectNone(`${API}/pagos/venta/42/cancelar`);

    boton(fixture, 'Sí, cancelar').click();
    http.expectOne(`${API}/pagos/venta/42/cancelar`).flush({});
    fixture.detectChanges();

    expect(el(fixture).querySelector('[data-estado="compra-cancelada"]')).not.toBeNull();
    expect(texto(el(fixture))).toContain('Compra cancelada. Tus prendas volvieron al carrito.');
    expect(el(fixture).querySelector('[data-estado="compra-pendiente"]')).toBeNull();
    // El contador de la barra se actualiza volviendo a leer el carrito.
    expect(http.match((r) => r.url === `${API}/carrito`).length).toBeGreaterThan(0);
  });

  it('"No" deja la compra como estaba', () => {
    const fixture = montar();

    boton(fixture, 'Cancelar compra').click();
    fixture.detectChanges();
    boton(fixture, 'No').click();
    fixture.detectChanges();

    expect(boton(fixture, 'Pagar ahora')).toBeTruthy();
    http.expectNone(`${API}/pagos/venta/42/cancelar`);
  });

  it('una compra pagada no ofrece pagar ni cancelar', () => {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: { get: () => '42' } } } },
      ],
    });
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(CompraDetalleComponent);
    fixture.detectChanges();
    http.expectOne(`${API}/ventas/42/comprobante`).flush(venta('pagada'));
    http.expectOne((r) => r.url === `${API}/catalogo/variantes/detalle`).flush(LOOKUP);
    fixture.detectChanges();

    expect(el(fixture as never).querySelector('[data-estado="compra-pendiente"]')).toBeNull();
  });
});
