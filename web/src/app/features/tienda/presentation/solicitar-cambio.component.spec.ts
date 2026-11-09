import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { environment } from '../../../../environments/environment';
import { ConectividadService, EstadoConexion } from '../../../core/conectividad.service';
import type { PlazoCambio, SolicitudCambio, Venta } from '../../../core/models/ventas.models';
import { TiendaActualService } from '../state/tienda-actual.service';
import { LineaParaCambio, SolicitarCambioComponent } from './solicitar-cambio.component';

const API = environment.apiUrl;
const URL_PRODUCTO = `${API}/public/acme/catalogo/1`;
const URL_ETIQUETAS = `${API}/catalogo/variantes/detalle`;

const VENTA = {
  id: 42,
  codigo: 'V-0042',
  canal: 'digital',
  cliente_id: 1,
  sucursal_id: 3,
  cajero_id: null,
  reserva_id: null,
  estado: 'pagada',
  fecha: '2026-11-04T10:00:00',
  subtotal: 200,
  descuento: 0,
  costo_envio: 0,
  total: 200,
  detalle: [],
} as unknown as Venta;

const LINEAS: LineaParaCambio[] = [
  { id: 5, varianteId: 10, productoId: 1, cantidad: 2, nombre: 'Polera Nike', detalle: 'M · Azul' },
];

const PLAZO: PlazoCambio = {
  venta_id: 42,
  fecha_venta: '2026-11-04T10:00:00Z',
  plazo_horas: 24,
  vence_en: '2026-11-05T10:00:00Z',
  vigente: true,
  estado_venta: 'pagada',
};

/** La M (la que compró) y tres más: una L del mismo precio con stock, una XL de otro precio y una S sin stock. */
const PRODUCTO = {
  id: 1,
  variantes: [
    { id: 10, talla_id: 1, color_id: 1, sku: 'P-M', precio_efectivo: 100, cantidad_disponible: 4 },
    { id: 11, talla_id: 2, color_id: 1, sku: 'P-L', precio_efectivo: 100, cantidad_disponible: 5 },
    { id: 12, talla_id: 3, color_id: 1, sku: 'P-XL', precio_efectivo: 120, cantidad_disponible: 5 },
    { id: 13, talla_id: 4, color_id: 1, sku: 'P-S', precio_efectivo: 100, cantidad_disponible: 0 },
  ],
};

const ETIQUETAS = [
  { variante_id: 10, producto_id: 1, producto_nombre: 'Polera Nike', imagen_principal: null, talla_codigo: 'M', color_nombre: 'Azul' },
  { variante_id: 11, producto_id: 1, producto_nombre: 'Polera Nike', imagen_principal: null, talla_codigo: 'L', color_nombre: 'Azul' },
  { variante_id: 12, producto_id: 1, producto_nombre: 'Polera Nike', imagen_principal: null, talla_codigo: 'XL', color_nombre: 'Azul' },
  { variante_id: 13, producto_id: 1, producto_nombre: 'Polera Nike', imagen_principal: null, talla_codigo: 'S', color_nombre: 'Azul' },
];

function solicitud(extra: Partial<SolicitudCambio> = {}): SolicitudCambio {
  return {
    id: 9,
    codigo: 'SOL-0009',
    venta_id: 42,
    venta_codigo: 'V-0042',
    sucursal_id: 3,
    cliente_nombre: 'Ana',
    fecha: '2026-11-04T15:00:00Z',
    estado: 'pendiente',
    motivo: null,
    motivo_rechazo: null,
    resuelta_en: null,
    atender_hasta: '2026-11-07T15:00:00Z',
    detalle: [
      {
        venta_detalle_id: 5,
        cantidad: 1,
        variante_devuelta_id: 10,
        prenda_devuelta: 'Polera Nike · talla M · Azul',
        variante_nueva_id: 11,
        prenda_nueva: 'Polera Nike · talla L · Azul',
        disponible_nueva: null,
      },
    ],
    ...extra,
  };
}

describe('SolicitarCambioComponent', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<SolicitarCambioComponent>;
  let el: HTMLElement;
  let conexion: ReturnType<typeof signal<EstadoConexion>>;

  function montar(
    opciones: {
      estado?: string;
      plazo?: PlazoCambio | null;
      mias?: SolicitudCambio[];
      conexion?: EstadoConexion;
      lineas?: LineaParaCambio[];
    } = {},
  ): void {
    conexion = signal<EstadoConexion>(opciones.conexion ?? 'en_linea');
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ConectividadService, useValue: { estado: conexion } },
      ],
    });
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(SolicitarCambioComponent);
    fixture.componentRef.setInput('venta', { ...VENTA, estado: opciones.estado ?? 'pagada' });
    fixture.componentRef.setInput('lineas', opciones.lineas ?? LINEAS);
    fixture.componentRef.setInput('plazo', opciones.plazo === undefined ? PLAZO : opciones.plazo);
    fixture.componentRef.setInput('sucursalNombre', 'Centro');
    el = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
    if ((opciones.estado ?? 'pagada') === 'pagada') {
      const peticion = http.expectOne((r) => r.url === `${API}/solicitudes-cambio/mias`);
      expect(peticion.request.params.get('venta_id')).toBe('42');
      peticion.flush(opciones.mias ?? []);
      fixture.detectChanges();
    }
  }

  /** Abre el formulario y responde el catálogo del producto y las etiquetas de sus variantes. */
  function abrirFormulario(catalogo: object = PRODUCTO): void {
    q('abrir-cambio')!.click();
    const producto = http.expectOne((r) => r.url === URL_PRODUCTO);
    expect(producto.request.params.get('sucursal_id')).toBe('3');
    producto.flush(catalogo);
    http.expectOne((r) => r.url === URL_ETIQUETAS).flush(ETIQUETAS);
    fixture.detectChanges();
  }

  const q = (estado: string) => el.querySelector<HTMLElement>(`[data-estado="${estado}"]`);
  const boton = (estado: string) => q(estado) as HTMLButtonElement | null;
  const select = () => q('cambiar-por') as HTMLSelectElement;
  const texto = () => (el.textContent ?? '').replace(/\s+/g, ' ').trim();
  const masUno = () => el.querySelector<HTMLButtonElement>('[aria-label="Una más"]')!;

  afterEach(() => http.match(() => true));

  it('una compra pendiente de pago no muestra nada ni consulta', () => {
    montar({ estado: 'pendiente_pago' });

    expect(q('solicitar-cambio')).toBeNull();
    http.expectNone((r) => r.url.includes('/solicitudes-cambio'));
  });

  it('dentro del plazo ofrece "Solicitar cambio"', () => {
    montar();

    expect(boton('abrir-cambio')!.disabled).toBe(false);
    expect(texto()).toContain('la sucursal Centro');
  });

  it('pasado el plazo no ofrece pedirlo y lo dice', () => {
    montar({ plazo: { ...PLAZO, vigente: false } });

    expect(boton('abrir-cambio')).toBeNull();
    expect(q('plazo-vencido-cambio')?.textContent).toContain('ya venció');
  });

  it('sin conexión el botón está deshabilitado y dice "Requiere conexión"', () => {
    montar({ conexion: 'sin_conexion' });

    expect(boton('abrir-cambio')!.disabled).toBe(true);
    expect(boton('abrir-cambio')!.getAttribute('title')).toBe('Requiere conexión');
    expect(q('cambio-sin-conexion')).not.toBeNull();
  });

  it('ofrece solo las otras tallas del mismo precio y con stock', async () => {
    montar();
    abrirFormulario();
    await fixture.whenStable(); // ngModel aplica `disabled` y el valor en un microtask

    const opciones = Array.from(select().querySelectorAll('option')).map((o) => (o.textContent ?? '').trim());
    expect(opciones).toEqual(['Cambiar por…', 'L · Azul']);
    expect(select().disabled).toBe(true); // hasta marcar una cantidad
    expect(boton('enviar-cambio')!.disabled).toBe(true);
  });

  it('marcar una cantidad deja elegida la única talla posible y permite enviar', async () => {
    montar();
    abrirFormulario();

    masUno().click();
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    await fixture.whenStable();

    expect(q('cantidad')!.textContent).toContain('1 de 2');
    expect(select().disabled).toBe(false);
    expect(select().selectedOptions[0].textContent).toContain('L · Azul');
    expect(boton('enviar-cambio')!.disabled).toBe(false);
  });

  it('envía la solicitud, confirma adónde llevar la prenda y vuelve a leer las solicitudes', () => {
    montar();
    abrirFormulario();
    masUno().click();
    fixture.detectChanges();
    const motivo = q('motivo-cambio') as HTMLTextAreaElement;
    motivo.value = '  Me queda grande ';
    motivo.dispatchEvent(new Event('input'));
    fixture.detectChanges();

    boton('enviar-cambio')!.click();
    const peticion = http.expectOne(`${API}/solicitudes-cambio`);
    expect(peticion.request.body).toEqual({
      venta_id: 42,
      motivo: 'Me queda grande',
      detalle: [{ venta_detalle_id: 5, cantidad: 1, variante_nueva_id: 11 }],
    });
    peticion.flush(solicitud());
    http.expectOne((r) => r.url === `${API}/solicitudes-cambio/mias`).flush([solicitud()]);
    fixture.detectChanges();

    expect(q('solicitud-enviada')!.textContent).toContain('SOL-0009');
    expect(q('solicitud-enviada')!.textContent).toContain('sucursal Centro');
    expect(q('formulario-cambio')).toBeNull();
    expect(el.querySelector('[data-solicitud="SOL-0009"]')).not.toBeNull();
  });

  it('no se puede cambiar más unidades de las que hay de la talla nueva', () => {
    montar();
    // De la L solo queda 1 y se compraron 2.
    abrirFormulario({
      ...PRODUCTO,
      variantes: PRODUCTO.variantes.map((v) => (v.id === 11 ? { ...v, cantidad_disponible: 1 } : v)),
    });
    expect(Array.from(select().querySelectorAll('option')).map((o) => (o.textContent ?? '').trim())).toEqual([
      'Cambiar por…',
      'L · Azul (quedan 1)',
    ]);

    masUno().click();
    masUno().click();
    fixture.detectChanges();
    expect(q('falta-stock')).not.toBeNull();
    expect(boton('enviar-cambio')!.disabled).toBe(true);

    el.querySelector<HTMLButtonElement>('[aria-label="Una menos"]')!.click();
    fixture.detectChanges();
    expect(q('falta-stock')).toBeNull();
    expect(boton('enviar-cambio')!.disabled).toBe(false);
  });

  it('el límite de cantidad es lo que se compró', () => {
    montar();
    abrirFormulario();

    masUno().click();
    masUno().click();
    fixture.detectChanges();

    expect(q('cantidad')!.textContent).toContain('2 de 2');
    expect(masUno().disabled).toBe(true);
  });

  it('si el servidor responde 409 muestra su explicación en la pantalla', () => {
    montar();
    abrirFormulario();
    masUno().click();
    fixture.detectChanges();

    boton('enviar-cambio')!.click();
    http
      .expectOne(`${API}/solicitudes-cambio`)
      .flush({ detail: 'Ya tienes una solicitud de cambio pendiente para esa prenda' }, { status: 409, statusText: 'Conflict' });
    fixture.detectChanges();

    expect(q('error-cambio')!.textContent).toContain('Ya tienes una solicitud de cambio pendiente');
    expect(boton('enviar-cambio')!.disabled).toBe(false); // puede corregir y reintentar
  });

  it('con demasiadas solicitudes (429) lo dice con claridad', () => {
    montar();
    abrirFormulario();
    masUno().click();
    fixture.detectChanges();

    boton('enviar-cambio')!.click();
    http.expectOne(`${API}/solicitudes-cambio`).flush({ detail: 'Demasiados intentos' }, { status: 429, statusText: 'Too Many Requests' });
    fixture.detectChanges();

    expect(q('error-cambio')!.textContent).toContain('muchas solicitudes de cambio');
  });

  it('si no se pudieron ver las tallas avisa y deja reintentar', () => {
    montar();
    boton('abrir-cambio')!.click();
    http.expectOne((r) => r.url === URL_PRODUCTO).flush({}, { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(q('error-opciones')).not.toBeNull();
    el.querySelector<HTMLButtonElement>('[data-estado="error-opciones"] .enlace')!.click();
    http.expectOne((r) => r.url === URL_PRODUCTO).flush(PRODUCTO);
    http.expectOne((r) => r.url === URL_ETIQUETAS).flush(ETIQUETAS);
    fixture.detectChanges();

    expect(q('error-opciones')).toBeNull();
    expect(select()).not.toBeNull();
  });

  it('una prenda con solicitud pendiente no se vuelve a ofrecer', () => {
    montar({ mias: [solicitud()] });

    expect(boton('abrir-cambio')!.disabled).toBe(true);
    expect(texto()).toContain('Ya pediste el cambio de todas las prendas');
  });

  describe('devolver y recibir mi dinero', () => {
    const casilla = (linea = 5) =>
      el.querySelector<HTMLInputElement>(`[data-linea="${linea}"] [data-estado="devolver-dinero"]`)!;
    const marcarDevolver = (linea = 5) => {
      casilla(linea).click(); // el clic alterna la casilla y dispara `change`
      fixture.detectChanges();
    };
    const sinCambio = (extra: Partial<SolicitudCambio> = {}) =>
      solicitud({
        detalle: [
          { ...solicitud().detalle[0], variante_nueva_id: null, prenda_nueva: null, disponible_nueva: null },
        ],
        ...extra,
      });

    it('cada prenda ofrece la casilla, deshabilitada hasta marcar una cantidad', () => {
      montar();
      abrirFormulario();

      expect(casilla()).not.toBeNull();
      expect(casilla().disabled).toBe(true);
      expect(texto()).toContain('Devolver y recibir mi dinero');

      masUno().click();
      fixture.detectChanges();
      expect(casilla().disabled).toBe(false);
    });

    it('una prenda para devolver se envía SIN variante_nueva_id y no pide elegir talla', async () => {
      montar();
      abrirFormulario();
      masUno().click();
      fixture.detectChanges();
      await fixture.whenStable();
      marcarDevolver();
      await fixture.whenStable();
      fixture.detectChanges();

      expect(select().disabled).toBe(true);
      expect(texto()).toContain('te lo devolvemos cuando la revisa');
      expect(boton('enviar-cambio')!.disabled).toBe(false);

      boton('enviar-cambio')!.click();
      const peticion = http.expectOne(`${API}/solicitudes-cambio`);
      expect(peticion.request.body).toEqual({
        venta_id: 42,
        motivo: null,
        detalle: [{ venta_detalle_id: 5, cantidad: 1 }],
      });
      expect('variante_nueva_id' in peticion.request.body.detalle[0]).toBe(false);
      peticion.flush(sinCambio());
      http.expectOne((r) => r.url === `${API}/solicitudes-cambio/mias`).flush([sinCambio()]);
    });

    it('sin otra talla disponible se puede devolver igual', () => {
      montar();
      abrirFormulario({ id: 1, variantes: [PRODUCTO.variantes[0]] });

      expect(q('sin-opciones')).not.toBeNull();
      masUno().click();
      fixture.detectChanges();
      expect(boton('enviar-cambio')!.disabled).toBe(true); // sin elegir qué hacer no se envía
      marcarDevolver();
      expect(boton('enviar-cambio')!.disabled).toBe(false);
    });

    it('devolver no exige stock de ninguna talla, y desmarcar vuelve a pedir la talla', async () => {
      montar();
      // De la L quedan 1 y se compraron 2: cambiar 2 no alcanza, pero devolver 2 sí.
      abrirFormulario({
        ...PRODUCTO,
        variantes: PRODUCTO.variantes.map((v) => (v.id === 11 ? { ...v, cantidad_disponible: 1 } : v)),
      });
      masUno().click();
      masUno().click();
      fixture.detectChanges();
      await fixture.whenStable();
      expect(q('falta-stock')).not.toBeNull();

      marcarDevolver();
      expect(q('falta-stock')).toBeNull();
      expect(boton('enviar-cambio')!.disabled).toBe(false);

      marcarDevolver(); // desmarca: otra vez hay que cambiar por una talla
      await fixture.whenStable();
      fixture.detectChanges();
      expect(casilla().checked).toBe(false);
      expect(q('falta-stock')).not.toBeNull();
      expect(boton('enviar-cambio')!.disabled).toBe(true);
    });

    it('una solicitud puede mezclar una prenda de cambio y otra de devolución', async () => {
      const otraLinea: LineaParaCambio = { id: 6, varianteId: 10, productoId: 1, cantidad: 1, nombre: 'Polera Nike', detalle: 'M · Azul' };
      montar({ lineas: [...LINEAS, otraLinea] });
      abrirFormulario();
      el.querySelectorAll<HTMLButtonElement>('[aria-label="Una más"]').forEach((b) => b.click());
      fixture.detectChanges();
      await fixture.whenStable();
      marcarDevolver(6);
      await fixture.whenStable();
      fixture.detectChanges();

      boton('enviar-cambio')!.click();
      const peticion = http.expectOne(`${API}/solicitudes-cambio`);
      expect(peticion.request.body.detalle).toEqual([
        { venta_detalle_id: 5, cantidad: 1, variante_nueva_id: 11 },
        { venta_detalle_id: 6, cantidad: 1 },
      ]);
    });

    it('"Tus solicitudes" dice "Devuelves: X · Quieres: que te devolvamos tu dinero" cuando no hay cambio', () => {
      montar({ mias: [sinCambio()] });

      const linea = q('linea-devolucion');
      expect(linea).not.toBeNull();
      const t = (linea!.textContent ?? '').replace(/\s+/g, ' ').trim();
      expect(t).toContain('Devuelves: Polera Nike · talla M · Azul (x1)');
      expect(t).toContain('Quieres: que te devolvamos tu dinero');
    });

    it('una solicitud de cambio se sigue mostrando con la flecha', () => {
      montar({ mias: [solicitud()] });

      expect(q('linea-devolucion')).toBeNull();
      expect(el.querySelector('[data-solicitud="SOL-0009"]')?.textContent).toContain('Polera Nike · talla L · Azul');
    });

    it('al aprobarse muestra el reembolso resultante en hora local, con su estado', () => {
      montar({
        mias: [
          sinCambio({
            estado: 'aprobada',
            reembolsos: [
              {
                id: 31,
                devolucion_id: 5,
                pago_id: 12,
                venta_id: 42,
                sucursal_id: 3,
                metodo: 'paypal',
                monto: '100.00',
                monto_usd: '14.37',
                estado: 'reembolsado',
                referencia_externa: 'REF-1',
                motivo_fallo: null,
                creado_en: '2026-11-08T15:00:00Z',
                completado_en: '2026-11-08T15:00:03Z',
              },
            ],
          }),
        ],
      });

      const t = texto();
      expect(t).toContain('Devolución hecha.');
      const bloque = q('reembolso-solicitud')!;
      expect(bloque.textContent).toContain('Bs 100.00');
      expect(bloque.textContent).toContain('a tu PayPal');
      expect(bloque.textContent).toContain('Reembolsado');
      expect(bloque.querySelector('[data-estado="reintentar-reembolso"]')).toBeNull(); // el cliente no reintenta
    });
  });

  it('muestra el estado de cada solicitud y el motivo del rechazo', () => {
    montar({
      mias: [
        solicitud({ id: 1, codigo: 'SOL-0001', estado: 'rechazada', motivo_rechazo: 'La prenda llegó usada' }),
        solicitud({ id: 2, codigo: 'SOL-0002', estado: 'aprobada' }),
        solicitud({ id: 3, codigo: 'SOL-0003', estado: 'vencida' }),
      ],
    });

    const lista = q('solicitudes-cambio')!;
    expect(lista.textContent).toContain('Rechazada');
    expect(lista.textContent).toContain('Motivo: La prenda llegó usada');
    expect(lista.textContent).toContain('Aprobada');
    expect(lista.textContent).toContain('Vencida');
    expect(lista.querySelector('[data-estado="cancelar-solicitud"]')).toBeNull(); // solo las pendientes se cancelan
  });

  it('cancela una solicitud pendiente después de confirmar', () => {
    montar({ mias: [solicitud()] });

    boton('cancelar-solicitud')!.click();
    fixture.detectChanges();
    expect(texto()).toContain('¿Cancelar esta solicitud?');
    http.expectNone(`${API}/solicitudes-cambio/9/cancelar`);

    boton('confirmar-cancelar')!.click();
    http.expectOne(`${API}/solicitudes-cambio/9/cancelar`).flush(solicitud({ estado: 'cancelada' }));
    http.expectOne((r) => r.url === `${API}/solicitudes-cambio/mias`).flush([solicitud({ estado: 'cancelada' })]);
    fixture.detectChanges();

    expect(q('estado-solicitud')!.textContent).toContain('Cancelada');
    expect(boton('abrir-cambio')!.disabled).toBe(false); // la prenda vuelve a poder pedirse
  });

  it('si al cancelar el servidor dice que ya se resolvió, lo muestra y vuelve a leer', () => {
    montar({ mias: [solicitud()] });
    boton('cancelar-solicitud')!.click();
    fixture.detectChanges();

    boton('confirmar-cancelar')!.click();
    http
      .expectOne(`${API}/solicitudes-cambio/9/cancelar`)
      .flush({ detail: 'La solicitud ya fue resuelta (estado: aprobada)' }, { status: 409, statusText: 'Conflict' });
    http.expectOne((r) => r.url === `${API}/solicitudes-cambio/mias`).flush([solicitud({ estado: 'aprobada' })]);
    fixture.detectChanges();

    expect(q('error-cancelar')!.textContent).toContain('ya fue resuelta');
    expect(q('estado-solicitud')!.textContent).toContain('Aprobada');
  });
});
