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

  describe('comprobante con QR', () => {
    const ENLACE = 'https://fashionstore.example/caja?venta=V-0042';
    const comprobante = (fixture: ReturnType<typeof montar>) =>
      (fixture.nativeElement as HTMLElement).querySelector('[data-estado="comprobante-compra"]');

    function cargarConEnlace(fixture: ReturnType<typeof montar>, estado: string): void {
      http.expectOne(`${API}/ventas/42/comprobante`).flush({ ...venta(estado), enlace_verificacion: ENLACE });
      http.expectOne((r) => r.url === `${API}/catalogo/variantes/detalle`).flush(LOOKUP);
      fixture.detectChanges();
    }

    it.each(['pagada', 'entregada'])('una compra %s muestra el comprobante con sus prendas y el QR', async (estado) => {
      const fixture = montar();
      cargarConEnlace(fixture, estado);
      await vi.waitFor(() => {
        fixture.detectChanges();
        expect((fixture.nativeElement as HTMLElement).querySelector('svg[data-estado="comprobante-qr"]')).not.toBeNull();
      });

      expect(texto(comprobante(fixture))).toContain('V-0042');
      expect(texto(comprobante(fixture))).toContain('Polera');
      expect(texto(comprobante(fixture))).toContain('M · Azul');
    });

    it('una compra pendiente de pago o anulada no muestra comprobante', async () => {
      for (const estado of ['pendiente_pago', 'anulada']) {
        TestBed.resetTestingModule();
        const fixture = montar();
        cargarConEnlace(fixture, estado);
        await fixture.whenStable();
        fixture.detectChanges();

        expect(comprobante(fixture), estado).toBeNull();
        expect((fixture.nativeElement as HTMLElement).querySelector('svg[data-estado="comprobante-qr"]'), estado).toBeNull();
      }
    });

    it('va después del aviso del plazo y antes de la solicitud de cambio', async () => {
      const fixture = montar();
      cargarConEnlace(fixture, 'pagada');
      http.expectOne(`${API}/ventas/42/plazo-cambio`).flush(plazo(true));
      http.match((r) => r.url.includes('/solicitudes-cambio')).forEach((r) => r.flush([]));
      fixture.detectChanges();

      const el = fixture.nativeElement as HTMLElement;
      const orden = ['plazo-cambio', 'comprobante-compra', 'solicitar-cambio'].map((marca) =>
        Array.from(el.querySelectorAll('[data-estado]')).findIndex((nodo) => nodo.getAttribute('data-estado') === marca),
      );
      expect(orden.every((i) => i >= 0)).toBe(true);
      expect(orden).toEqual([...orden].sort((a, b) => a - b));
    });
  });

  it('una compra pendiente de pago no consulta ni muestra el plazo', () => {
    const fixture = montar();
    cargar(fixture, 'pendiente_pago');

    http.expectNone(`${API}/ventas/42/plazo-cambio`);
    expect(aviso(fixture)).toBeNull();
  });

  it('una compra pagada ofrece pedir el cambio y lee sus solicitudes; una pendiente de pago no', () => {
    const fixture = montar();
    cargar(fixture, 'pagada');
    http.expectOne(`${API}/ventas/42/plazo-cambio`).flush(plazo(true));
    const mias = http.expectOne((r) => r.url === `${API}/solicitudes-cambio/mias`);
    expect(mias.request.params.get('venta_id')).toBe('42');
    mias.flush([]);
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-estado="solicitar-cambio"]')).not.toBeNull();
    expect((el.querySelector('[data-estado="abrir-cambio"]') as HTMLButtonElement).disabled).toBe(false);
  });

  it('una compra pendiente de pago no muestra la solicitud de cambio ni la consulta', () => {
    const fixture = montar();
    cargar(fixture, 'pendiente_pago');

    http.expectNone((r) => r.url.includes('/solicitudes-cambio'));
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-estado="solicitar-cambio"]')).toBeNull();
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

describe('CompraDetalleComponent: sucursal y devolución', () => {
  let http: HttpTestingController;

  /** `conPlazo`: se espera la consulta del plazo (false cuando ya no queda nada por cambiar y no se consulta). */
  function montar(extra: object = {}, conPlazo = true) {
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
    http.expectOne(`${API}/ventas/42/comprobante`).flush({ ...venta('pagada'), sucursal_id: 2, ...extra });
    http.expectOne((r) => r.url === `${API}/catalogo/variantes/detalle`).flush(LOOKUP);
    if (conPlazo) {
      http.expectOne(`${API}/ventas/42/plazo-cambio`).flush({
        venta_id: 42,
        fecha_venta: '2026-11-04T10:00:00Z',
        plazo_horas: 24,
        vence_en: '2026-11-05T10:00:00Z',
        vigente: true,
        estado_venta: 'pagada',
      });
    } else {
      http.expectNone(`${API}/ventas/42/plazo-cambio`);
    }
    fixture.detectChanges();
    return fixture;
  }

  /** Una compra de 3 unidades en una sola línea (la 5), con `devueltas` ya devueltas. */
  const tresUnidades = (devueltas: number) => ({
    unidades_devueltas: devueltas,
    detalle: [
      {
        id: 5,
        variante_id: 10,
        cantidad: 3,
        cantidad_devuelta: devueltas,
        precio_unitario: 100,
        descuento_unitario: 0,
        costo_unitario: null,
        subtotal: 300,
      },
    ],
  });

  const texto = (e: Element | null | undefined) => (e?.textContent ?? '').replace(/\s+/g, ' ').trim();
  const sucursales = () => http.expectOne((r) => r.url.endsWith('/sucursales'));

  afterEach(() => http.match(() => true));

  it('dice en qué sucursal es la compra y adónde llevar la prenda a cambiar', () => {
    const fixture = montar();
    sucursales().flush([
      { id: 1, nombre: 'Equipetrol' },
      { id: 2, nombre: 'Centro' },
    ]);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;

    expect(texto(el.querySelector('[data-estado="sucursal-compra"]'))).toBe('· Centro');
    expect(texto(el.querySelector('[data-estado="plazo-cambio"]'))).toContain('Lleva la prenda a la sucursal Centro');
  });

  it('si no se puede leer la lista de sucursales, la pantalla queda como siempre', () => {
    const fixture = montar();
    sucursales().flush({ detail: 'x' }, { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;

    expect(el.querySelector('[data-estado="sucursal-compra"]')).toBeNull();
    expect(texto(el.querySelector('[data-estado="plazo-cambio"]'))).toContain('Lleva la prenda a la tienda');
  });

  it('una compra con devolución sigue pagada pero muestra la marca', () => {
    // El detalle de la venta de prueba tiene 1 unidad: devolver 1 es devolverla toda.
    const fixture = montar({ unidades_devueltas: 1 }, false);
    sucursales().flush([]);
    fixture.detectChanges();

    expect(texto((fixture.nativeElement as HTMLElement).querySelector('[data-estado="con-devolucion"]'))).toBe('Devuelta');
  });

  describe('devolución y cambio de prendas', () => {
    const el = (fixture: ReturnType<typeof montar>) => fixture.nativeElement as HTMLElement;
    const maximo = (fixture: ReturnType<typeof montar>) =>
      texto(el(fixture).querySelector('[data-estado="cantidad"]'));

    function abrirFormulario(fixture: ReturnType<typeof montar>): void {
      sucursales().flush([]);
      http.match((r) => r.url.includes('/solicitudes-cambio')).forEach((r) => r.flush([]));
      fixture.detectChanges();
      (el(fixture).querySelector('[data-estado="abrir-cambio"]') as HTMLButtonElement).click();
      // Las tallas del producto: sin otras variantes, lo que importa aquí son las líneas y su máximo.
      http
        .match((r) => /\/catalogo\/\d+$/.test(r.url))
        .forEach((r) => r.flush({ id: Number(r.request.url.split('/').pop()), variantes: [] }));
      fixture.detectChanges();
    }

    it('sin devolución ofrece el cambio de todas las prendas y no dice nada de devoluciones', () => {
      const fixture = montar(tresUnidades(0));
      abrirFormulario(fixture);

      expect(el(fixture).querySelector('[data-estado="plazo-cambio"]')).not.toBeNull();
      expect(el(fixture).querySelector('[data-estado="solicitar-cambio"]')).not.toBeNull();
      expect(el(fixture).querySelector('[data-estado="devolucion-parcial"]')).toBeNull();
      expect(el(fixture).querySelector('[data-estado="con-devolucion"]')).toBeNull();
      expect(maximo(fixture)).toBe('0 de 3');
    });

    it('devuelta toda la compra no muestra el plazo ni la sección de cambio, y no consulta el plazo', () => {
      const fixture = montar(tresUnidades(3), false);
      sucursales().flush([]);
      fixture.detectChanges();

      expect(el(fixture).querySelector('[data-estado="plazo-cambio"]')).toBeNull();
      expect(el(fixture).querySelector('[data-estado="solicitar-cambio"]')).toBeNull();
      expect(el(fixture).querySelector('[data-estado="devolucion-parcial"]')).toBeNull();
      expect(texto(el(fixture))).not.toContain('Puedes cambiar tu prenda');
      expect(texto(el(fixture).querySelector('[data-estado="con-devolucion"]'))).toBe('Devuelta');
      http.expectNone((r) => r.url.includes('/solicitudes-cambio'));
    });

    it('devuelta toda la compra solo con el total (servidor sin cantidad por línea) tampoco ofrece el cambio', () => {
      const { detalle } = tresUnidades(0);
      const sinPorLinea = detalle.map(({ cantidad_devuelta: _omitida, ...resto }) => resto);
      const fixture = montar({ unidades_devueltas: 3, detalle: sinPorLinea }, false);
      sucursales().flush([]);
      fixture.detectChanges();

      expect(el(fixture).querySelector('[data-estado="solicitar-cambio"]')).toBeNull();
    });

    it('devolución parcial: muestra todo pero solo con lo que queda, y lo dice', () => {
      const fixture = montar(tresUnidades(1));
      abrirFormulario(fixture);

      expect(texto(el(fixture).querySelector('[data-estado="devolucion-parcial"]'))).toBe(
        'Ya devolviste 1 de 3 prendas de esta compra. Solo puedes cambiar las que te quedan.',
      );
      expect(el(fixture).querySelector('[data-estado="plazo-cambio"]')).not.toBeNull();
      // El máximo por prenda es lo que queda (3 - 1), no lo comprado.
      expect(maximo(fixture)).toBe('0 de 2');
      const mas = el(fixture).querySelector('button[aria-label="Una más"]') as HTMLButtonElement;
      mas.click();
      mas.click();
      fixture.detectChanges();
      expect(maximo(fixture)).toBe('2 de 2');
      expect(mas.disabled).toBe(true);
    });

    it('en una compra con varias líneas se omiten las ya devueltas del todo', () => {
      const base = tresUnidades(0).detalle[0];
      const fixture = montar({
        unidades_devueltas: 3,
        detalle: [
          { ...base, id: 5, cantidad: 3, cantidad_devuelta: 3 },
          { ...base, id: 6, variante_id: 11, cantidad: 2, cantidad_devuelta: 0 },
        ],
      });
      abrirFormulario(fixture);

      expect(el(fixture).querySelectorAll('[data-linea]').length).toBe(1);
      expect(el(fixture).querySelector('[data-linea="6"]')).not.toBeNull();
      expect(maximo(fixture)).toBe('0 de 2');
    });
  });
});
