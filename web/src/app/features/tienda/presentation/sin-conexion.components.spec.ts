import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { MessageService } from 'primeng/api';
import { environment } from '../../../../environments/environment';
import { AuthService } from '../../../core/auth.service';
import { ConectividadService } from '../../../core/conectividad.service';
import { EMPRESA, USUARIO, linea, nuevoEntorno, pedido } from '../../../core/offline-cliente/ayudas-prueba';
import { ClienteOfflineService } from '../../../core/offline-cliente/cliente-offline.service';
import { CatalogoPublicoComponent } from '../../catalogo-publico/catalogo-publico.component';
import { AvisoPedidosSinConexionComponent } from '../aviso-pedidos-sin-conexion.component';
import { CarritoLocalService } from '../state/carrito-local.service';
import { TiendaActualService } from '../state/tienda-actual.service';
import { CarritoComponent } from './carrito.component';
import { CheckoutSinConexionComponent } from './checkout-sin-conexion.component';
import { PedidosSinConexionComponent } from './pedidos-sin-conexion.component';
import { ProductoDetalleComponent } from './producto-detalle.component';

const API = environment.apiUrl;
const PUBLICO = `${API}/public/acme`;

const METODO_GUARDADO = { guardado: true, correo_paypal: 'j***@gmail.com', guardado_en: null, verificado_en: '2026-11-06T10:00:00Z' };
const METODO_NO_GUARDADO = { guardado: false, correo_paypal: null, guardado_en: null, verificado_en: '2026-11-06T10:00:00Z' };
const SUCURSALES = [
  { id: 3, nombre: 'Centro', es_deposito: false },
  { id: 4, nombre: 'Depósito', es_deposito: true },
  { id: 5, nombre: 'Sur', es_deposito: false },
];

@Component({ template: '' })
class PaginaVacia {}

let entorno: ReturnType<typeof nuevoEntorno>;
let http: HttpTestingController;

function configurar(extra: object[] = []): void {
  TestBed.configureTestingModule({
    providers: [
      provideRouter([{ path: '**', component: PaginaVacia }]),
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
  await fixture.whenStable();
  fixture.detectChanges();
}

const texto = (el: HTMLElement) => (el.textContent ?? '').replace(/\s+/g, ' ').trim();
const qs = (el: HTMLElement, estado: string) => el.querySelector<HTMLElement>(`[data-estado="${estado}"]`);

beforeEach(() => {
  entorno = nuevoEntorno();
});

afterEach(async () => {
  // Deja terminar lo que las pantallas y servicios aún leen de IndexedDB antes de cerrarla.
  for (let i = 0; i < 20; i++) await new Promise<void>((r) => setTimeout(r, 0));
  TestBed.resetTestingModule();
  await entorno.cerrar();
});

// ---- Pagar sin conexión -----------------------------------------------------------------------------------------------------

describe('CheckoutSinConexionComponent', () => {
  let fixture: ComponentFixture<CheckoutSinConexionComponent>;
  let el: HTMLElement;
  let navegar: ReturnType<typeof vi.spyOn>;

  async function montar(
    opciones: { metodo?: object | null; sucursales?: object[] | null; lineas?: number[]; sucursalDeLaSegunda?: number } = {},
  ): Promise<void> {
    entorno.enLinea.set(false);
    const repo = entorno.repo();
    for (const n of opciones.lineas ?? [1, 2]) {
      await repo.agregarLinea(
        linea(n, {
          cantidad: n === 1 ? 2 : 1,
          precio_unitario: n === 1 ? '199.00' : '50.50',
          sucursal_id: n === 2 && opciones.sucursalDeLaSegunda ? opciones.sucursalDeLaSegunda : 3,
        }),
        20,
      );
    }
    if (opciones.metodo !== null) await repo.guardarMeta('metodo_pago', opciones.metodo ?? METODO_GUARDADO);
    if (opciones.sucursales !== null) await repo.guardarMeta('sucursales', opciones.sucursales ?? SUCURSALES);
    configurar();
    navegar = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    fixture = TestBed.createComponent(CheckoutSinConexionComponent);
    el = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
    await esperar(fixture);
  }

  const q = (estado: string) => qs(el, estado);
  const confirmar = () => q('confirmar-pedido') as HTMLButtonElement;
  const casilla = () => q('aceptar-total') as HTMLInputElement;
  const pastillas = () => Array.from(el.querySelectorAll<HTMLButtonElement>('.fs-pill'));

  it('muestra las prendas, el total con los precios guardados y pide aceptar "Se cobrará hasta Bs X"', async () => {
    await montar();

    expect(texto(el)).toContain('Polera 1');
    expect(texto(el)).toContain('2 × Bs 199.00');
    expect(texto(el)).toContain('Bs 448.50');
    expect(q('texto-aceptacion')?.textContent).toContain('Se cobrará hasta');
    expect(q('texto-aceptacion')?.textContent).toContain('Bs 448.50');
    expect(q('texto-aceptacion')?.textContent).toContain('cuando vuelva la conexión');
    expect(q('metodo-paypal-guardado')?.textContent).toContain('j***@gmail.com');
  });

  it('solo ofrece retirar en las sucursales (no el depósito) y sugiere la única donde había stock', async () => {
    await montar();

    expect(pastillas().map((p) => texto(p))).toEqual(['Centro', 'Sur']);
    // Las dos prendas se guardaron sabiendo que había stock en Centro (id 3).
    expect(pastillas()[0].getAttribute('aria-pressed')).toBe('true');
  });

  it('si las prendas se guardaron con sucursales distintas no sugiere ninguna: hay que elegir una', async () => {
    await montar({ lineas: [1, 2], sucursalDeLaSegunda: 5 });

    expect(pastillas().map((p) => p.getAttribute('aria-pressed'))).toEqual(['false', 'false']);
    casilla().click();
    fixture.detectChanges();
    expect(confirmar().disabled).toBe(true); // aceptó el total, pero falta la sucursal
    pastillas()[1].click();
    fixture.detectChanges();
    expect(confirmar().disabled).toBe(false);
  });

  it('confirma: deja el pedido en la cola con el total aceptado, vacía el carrito local y lleva a Pedidos sin conexión', async () => {
    await montar();
    expect(confirmar().disabled).toBe(true);

    pastillas()[0].click();
    fixture.detectChanges();
    expect(confirmar().disabled).toBe(true); // falta aceptar el total
    casilla().click();
    fixture.detectChanges();
    expect(confirmar().disabled).toBe(false);

    confirmar().click();
    await esperar(fixture);

    const pedidos = await entorno.repo().pedidos();
    expect(pedidos).toHaveLength(1);
    expect(pedidos[0]).toMatchObject({
      estado: 'pendiente',
      sucursal_id: 3,
      sucursal_nombre: 'Centro',
      costo_envio: '0.00',
      total_maximo: '448.50',
    });
    expect(pedidos[0].lineas.map((l) => [l.variante_id, l.cantidad])).toEqual([[101, 2], [102, 1]]);
    expect(pedidos[0].operacion_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(await entorno.repo().carrito()).toEqual([]);
    expect(navegar).toHaveBeenCalledWith(['/t', 'acme', 'mi-cuenta', 'pedidos-sin-conexion'], { queryParams: { nuevo: pedidos[0].operacion_id } });
    // Sin conexión no sale ninguna petición.
    http.expectNone(() => true);
  });

  it('sin PayPal guardado la opción sale deshabilitada, con el texto y el enlace, y no se puede confirmar', async () => {
    await montar({ metodo: METODO_NO_GUARDADO });

    expect(q('metodo-paypal-no-disponible')?.textContent).toContain('Guarda tu PayPal con conexión para pagar sin internet');
    expect(q('metodo-paypal-no-disponible')?.getAttribute('aria-disabled')).toBe('true');
    expect(q('metodo-paypal-guardado')).toBeNull();
    expect(el.querySelector<HTMLAnchorElement>('a.enlace-metodo')?.getAttribute('href')).toBe('/t/acme/mi-cuenta/metodo-pago');
    expect(casilla().disabled).toBe(true);
    expect(confirmar().disabled).toBe(true);
  });

  it('si nunca se guardó el método de pago tampoco se puede (no hay nada que cobrar)', async () => {
    await montar({ metodo: null });

    expect(q('metodo-paypal-no-disponible')).not.toBeNull();
    expect(confirmar().disabled).toBe(true);
  });

  it('sin sucursales guardadas ni caché del catálogo lo dice y no deja confirmar', async () => {
    entorno.enLinea.set(false);
    await entorno.repo().agregarLinea(linea(1), 20);
    await entorno.repo().guardarMeta('metodo_pago', METODO_GUARDADO);
    configurar();
    fixture = TestBed.createComponent(CheckoutSinConexionComponent);
    el = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
    await esperar(fixture);
    // Se intenta con lo que el Service Worker tenga del catálogo; sin red falla.
    http.expectOne((r) => r.url === `${PUBLICO}/sucursales`).error(new ProgressEvent('error'));
    await esperar(fixture);

    expect(q('sin-sucursales')?.textContent).toContain('No tenemos sucursales guardadas');
    expect(confirmar().disabled).toBe(true);
  });

  it('con el carrito vacío no hay nada que pagar', async () => {
    await montar({ lineas: [] });

    expect(q('carrito-vacio')).not.toBeNull();
    expect(q('confirmar-pedido')).toBeNull();
  });

  it('si ya volvió la conexión lo avisa y deja usar el pago normal', async () => {
    await montar();
    entorno.enLinea.set(true);
    fixture.detectChanges();

    expect(q('volvio-conexion')?.textContent).toContain('Ya tienes conexión');
  });
});

// ---- El carrito sin conexión -------------------------------------------------------------------------------------------------

describe('CarritoComponent con y sin conexión', () => {
  let fixture: ComponentFixture<CarritoComponent>;
  let el: HTMLElement;
  let navegar: ReturnType<typeof vi.spyOn>;

  async function montar(enLinea: boolean, opciones: { metodo?: object; lineas?: number[] } = {}): Promise<void> {
    entorno.enLinea.set(enLinea);
    const repo = entorno.repo();
    for (const n of opciones.lineas ?? [1]) await repo.agregarLinea(linea(n, { cantidad: 2 }), 20);
    if (opciones.metodo) await repo.guardarMeta('metodo_pago', opciones.metodo);
    configurar();
    navegar = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    fixture = TestBed.createComponent(CarritoComponent);
    el = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
    await esperar(fixture);
  }

  const q = (estado: string) => qs(el, estado);

  it('sin conexión muestra el carrito local con su aviso, sin pedir nada al servidor', async () => {
    await montar(false, { lineas: [1, 2] });

    http.expectNone(() => true);
    expect(q('carrito-sin-conexion')?.textContent).toContain('Sin conexión');
    expect(el.querySelectorAll('.linea')).toHaveLength(2);
    expect(texto(el)).toContain('Polera 1');
    expect(texto(el)).toContain('M · Negro');
    expect(texto(el)).toContain('Bs 199.00');
    expect(texto(el)).toContain('Bs 796.00'); // 2 x 199 + 2 x 199
  });

  it('sin conexión se puede cambiar la cantidad y quitar, todo en IndexedDB', async () => {
    await montar(false, { lineas: [1, 2] });

    el.querySelectorAll<HTMLButtonElement>('[aria-label="Aumentar cantidad"]')[0].click();
    await esperar(fixture);
    expect((await entorno.repo().carrito()).find((l) => l.variante_id === 101)?.cantidad).toBe(3);

    el.querySelector<HTMLButtonElement>('[aria-label="Quitar Polera 2"]')!.click();
    await esperar(fixture);
    expect((await entorno.repo().carrito()).map((l) => l.variante_id)).toEqual([101]);
    http.expectNone(() => true);
  });

  it('sin PayPal guardado "Pagar con mi PayPal guardado" sale deshabilitado con el texto y el enlace', async () => {
    await montar(false);

    const boton = q('pagar-paypal-guardado') as HTMLButtonElement;
    expect(boton.disabled).toBe(true);
    expect(q('sin-paypal-guardado')?.textContent).toContain('Guarda tu PayPal con conexión para pagar sin internet');
    expect(q('sin-paypal-guardado')?.querySelector('a')?.getAttribute('href')).toBe('/t/acme/mi-cuenta/metodo-pago');
  });

  it('con PayPal guardado "Pagar con mi PayPal guardado" lleva al pago sin conexión', async () => {
    await montar(false, { metodo: METODO_GUARDADO });

    const boton = q('pagar-paypal-guardado') as HTMLButtonElement;
    expect(boton.disabled).toBe(false);
    expect(q('sin-paypal-guardado')).toBeNull();
    boton.click();

    expect(navegar).toHaveBeenCalledWith(['/t', 'acme', 'checkout', 'sin-conexion']);
  });

  it('sin conexión y sin prendas guardadas explica cómo agregar', async () => {
    await montar(false, { lineas: [] });

    expect(texto(el)).toContain('Todavía no has agregado ninguna prenda');
    expect(texto(el)).toContain('que ya cargaste');
  });

  it('con conexión ofrece "Pasar a mi carrito" y "Descartar" para lo guardado sin conexión (no lo mezcla solo)', async () => {
    await montar(true, { lineas: [1] });
    http.expectOne(`${API}/carrito`).flush({ id: 1, cliente_id: 1, sucursal_id: null, actualizado_en: '', detalle: [], subtotal: 0 });
    http.expectOne((r) => r.url === `${API}/ventas/mis-compras`).flush([]);
    await esperar(fixture);

    expect(q('carrito-local-pendiente')?.textContent).toContain('2 prendas guardadas');
    expect(q('carrito-local-pendiente')?.textContent).toContain('Bs 398.00');
    expect(q('pasar-a-mi-carrito')).not.toBeNull();
    // Nada se mandó al servidor por su cuenta.
    http.expectNone({ method: 'POST', url: `${API}/carrito` });
  });

  it('"Pasar a mi carrito" agrega cada línea al carrito del servidor y vacía el local', async () => {
    await montar(true, { lineas: [1] });
    http.expectOne(`${API}/carrito`).flush({ id: 1, cliente_id: 1, sucursal_id: null, actualizado_en: '', detalle: [], subtotal: 0 });
    http.expectOne((r) => r.url === `${API}/ventas/mis-compras`).flush([]);
    await esperar(fixture);

    (q('pasar-a-mi-carrito') as HTMLButtonElement).click();
    for (let i = 0; i < 40; i++) {
      for (const p of http.match((r) => r.method === 'POST' && r.url === `${API}/carrito`)) {
        expect(p.request.body).toEqual({ variante_id: 101, cantidad: 2 });
        p.flush({ id: 1, cliente_id: 1, sucursal_id: null, actualizado_en: '', detalle: [], subtotal: 0 });
      }
      await new Promise<void>((r) => setTimeout(r, 0));
    }
    // Después recarga el carrito del servidor.
    for (const g of http.match((r) => r.method === 'GET' && r.url === `${API}/carrito`)) {
      g.flush({ id: 1, cliente_id: 1, sucursal_id: null, actualizado_en: '', detalle: [], subtotal: 0 });
    }
    await esperar(fixture);

    expect(await entorno.repo().carrito()).toEqual([]);
    expect(q('resultado-paso')?.textContent).toContain('Pasamos 1 prenda a tu carrito');
    expect(q('carrito-local-pendiente')).toBeNull();
  });

  it('"Descartar" vacía el carrito local sin tocar el servidor', async () => {
    await montar(true, { lineas: [1] });
    http.expectOne(`${API}/carrito`).flush({ id: 1, cliente_id: 1, sucursal_id: null, actualizado_en: '', detalle: [], subtotal: 0 });
    http.expectOne((r) => r.url === `${API}/ventas/mis-compras`).flush([]);
    await esperar(fixture);

    (q('descartar-carrito-local') as HTMLButtonElement).click();
    await esperar(fixture);

    expect(await entorno.repo().carrito()).toEqual([]);
    expect(q('carrito-local-pendiente')).toBeNull();
    http.expectNone({ method: 'POST', url: `${API}/carrito` });
  });

  it('al volver la conexión con la pantalla abierta trae el carrito del servidor y deja a la vista el local', async () => {
    await montar(false, { lineas: [1] });
    http.expectNone(() => true);

    entorno.enLinea.set(true);
    fixture.detectChanges();
    TestBed.tick();
    http.expectOne(`${API}/carrito`).flush({ id: 1, cliente_id: 1, sucursal_id: null, actualizado_en: '', detalle: [], subtotal: 0 });
    http.expectOne((r) => r.url === `${API}/ventas/mis-compras`).flush([]);
    await esperar(fixture);

    expect(q('carrito-sin-conexion')).toBeNull();
    expect(q('carrito-local-pendiente')).not.toBeNull();
  });
});

// ---- Ver y agregar prendas sin conexión ---------------------------------------------------------------------------------------

describe('ProductoDetalleComponent sin conexión', () => {
  let fixture: ComponentFixture<ProductoDetalleComponent>;
  let el: HTMLElement;

  const DETALLE = {
    id: 9,
    codigo: 'P-9',
    nombre: 'Camisa Oxford',
    descripcion: null,
    categoria_id: 1,
    genero: 'hombre',
    precio_base: 289,
    admite_probador: false,
    variantes: [{ id: 100, talla_id: 1, color_id: 1, sku: 'S1', precio_efectivo: 289, cantidad_disponible: 3 }],
    imagenes: [{ id: 1, producto_id: 9, color_id: null, public_id: 'a', url: 'https://cdn.example.com/a.jpg', orden: 0, es_principal: true }],
  };

  function montar(): void {
    localStorage.clear();
    configurar([
      { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ id: '9' }) } } },
      { provide: AuthService, useValue: { estaAutenticado: () => true } },
    ]);
    fixture = TestBed.createComponent(ProductoDetalleComponent);
    el = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
  }

  /** Lo que el Service Worker devuelve del catálogo público ya visitado. */
  function responderDesdeCache(): void {
    http.expectOne(`${PUBLICO}/catalogo/9`).flush(DETALLE);
    http.expectOne((r) => r.url === `${PUBLICO}/tallas`).flush([{ id: 1, codigo: 'M', descripcion: null, orden: 1 }]);
    http.expectOne((r) => r.url === `${PUBLICO}/colores`).flush([{ id: 1, nombre: 'Celeste', codigo_hex: '#b9cad6' }]);
    http.expectOne((r) => r.url === `${PUBLICO}/sucursales`).flush(SUCURSALES);
    fixture.detectChanges();
  }

  const q = (estado: string) => qs(el, estado);

  afterEach(() => localStorage.clear());

  it('muestra la prenda con lo que el Service Worker tenía guardado', () => {
    entorno.enLinea.set(false);
    montar();
    responderDesdeCache();

    expect(el.querySelector('h1')?.textContent).toContain('Camisa Oxford');
    expect(el.querySelector('.precio')?.textContent).toContain('Bs 289.00');
    expect(q('prenda-sin-conexion')).toBeNull();
  });

  it('lo que no estaba guardado falla con un mensaje claro y un enlace de vuelta, no con una pantalla rota', () => {
    entorno.enLinea.set(false);
    montar();
    // Con una que falle, forkJoin descarta las demás.
    http.match(() => true)[0].error(new ProgressEvent('error'));
    fixture.detectChanges();

    expect(q('prenda-sin-conexion')?.textContent).toContain('Sin conexión: esta prenda no estaba guardada');
    expect(el.querySelector('a[href="/t/acme"]')).not.toBeNull();
  });

  it('sin disponibilidad guardada dice "no podemos mostrarla" (no "Agotado") y agrega al carrito LOCAL con todos sus datos', async () => {
    entorno.enLinea.set(false);
    montar();
    responderDesdeCache();

    el.querySelector<HTMLButtonElement>('button[aria-label="Color Celeste"]')!.click();
    Array.from(el.querySelectorAll<HTMLButtonElement>('.tallas .fs-pill')).find((b) => texto(b) === 'M')!.click();
    http.expectOne((r) => r.url === `${PUBLICO}/inventario/disponibilidad`).error(new ProgressEvent('error'));
    fixture.detectChanges();

    expect(q('disponibilidad-desconocida')?.textContent).toContain('Sin conexión: no podemos mostrar la disponibilidad');
    expect(texto(el)).not.toContain('Agotado');
    expect(q('aviso-carrito-local')?.textContent).toContain('PayPal guardado');

    const agregar = Array.from(el.querySelectorAll<HTMLButtonElement>('.acciones button')).find((b) => texto(b).includes('Agregar al carrito sin conexión'))!;
    agregar.click();
    await esperar(fixture);

    http.expectNone({ method: 'POST', url: `${API}/carrito` });
    const guardado = await entorno.repo().carrito();
    expect(guardado).toHaveLength(1);
    expect(guardado[0]).toMatchObject({
      variante_id: 100,
      producto_id: 9,
      cantidad: 1,
      producto_nombre: 'Camisa Oxford',
      talla: 'M',
      color: 'Celeste',
      precio_unitario: '289.00',
      imagen: 'https://cdn.example.com/a.jpg',
      sucursal_id: null,
      empresa_id: EMPRESA,
      usuario_id: USUARIO,
    });
    expect(texto(el)).toContain('Agregado');
    expect(TestBed.inject(CarritoLocalService).cantidadLineas()).toBe(1);
  });

  it('si había disponibilidad guardada, la línea recuerda la sucursal con stock', async () => {
    entorno.enLinea.set(false);
    montar();
    responderDesdeCache();

    el.querySelector<HTMLButtonElement>('button[aria-label="Color Celeste"]')!.click();
    Array.from(el.querySelectorAll<HTMLButtonElement>('.tallas .fs-pill')).find((b) => texto(b) === 'M')!.click();
    http
      .expectOne((r) => r.url === `${PUBLICO}/inventario/disponibilidad`)
      .flush([
        { sucursal_id: 3, variante_id: 100, cantidad_disponible: 0 },
        { sucursal_id: 5, variante_id: 100, cantidad_disponible: 4 },
      ]);
    fixture.detectChanges();

    Array.from(el.querySelectorAll<HTMLButtonElement>('.acciones button')).find((b) => texto(b).includes('sin conexión'))!.click();
    await esperar(fixture);

    expect((await entorno.repo().carrito())[0]).toMatchObject({ sucursal_id: 5, sucursal_nombre: 'Sur' });
  });

  it('con conexión recuerda las sucursales (para elegir dónde retirar sin red) y agrega al carrito del servidor como siempre', async () => {
    montar();
    responderDesdeCache();
    await esperar(fixture);

    expect(await entorno.repo().leerMeta('sucursales')).toEqual(SUCURSALES);

    el.querySelector<HTMLButtonElement>('button[aria-label="Color Celeste"]')!.click();
    Array.from(el.querySelectorAll<HTMLButtonElement>('.tallas .fs-pill')).find((b) => texto(b) === 'M')!.click();
    http.expectOne((r) => r.url === `${PUBLICO}/inventario/disponibilidad`).flush([]);
    fixture.detectChanges();
    Array.from(el.querySelectorAll<HTMLButtonElement>('.acciones button')).find((b) => texto(b) === 'Agregar al carrito')!.click();

    const peticion = http.expectOne({ method: 'POST', url: `${API}/carrito` });
    expect(peticion.request.body).toEqual({ variante_id: 100, cantidad: 1 });
    expect(await entorno.repo().carrito()).toEqual([]);
  });
});

// ---- La lista de prendas sin conexión ------------------------------------------------------------------------------------------

describe('CatalogoPublicoComponent sin conexión', () => {
  const ITEM = { id: 9, codigo: 'P-9', nombre: 'Camisa Oxford', categoria_id: 1, genero: 'hombre', precio_base: 289, admite_probador: false, imagen_principal: null };

  function montar(): { fixture: ComponentFixture<CatalogoPublicoComponent>; el: HTMLElement; avisos: unknown[] } {
    configurar();
    const avisos: unknown[] = [];
    TestBed.inject(MessageService).messageObserver.subscribe((m) => avisos.push(m));
    const fixture = TestBed.createComponent(CatalogoPublicoComponent);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement, avisos };
  }

  const referencias = () => {
    for (const lista of ['categorias', 'tallas', 'colores', 'materiales', 'temporadas']) {
      http.expectOne((r) => r.url.startsWith(`${PUBLICO}/${lista}?`)).flush([]);
    }
  };

  it('muestra las prendas que el Service Worker tenía guardadas', () => {
    entorno.enLinea.set(false);
    const { fixture, el } = montar();
    http.expectOne((r) => r.url.startsWith(`${PUBLICO}/catalogo?`)).flush([ITEM]);
    referencias();
    fixture.detectChanges();

    expect(texto(el)).toContain('Camisa Oxford');
    expect(qs(el, 'catalogo-error')).toBeNull();
  });

  it('lo que no estaba guardado dice que no estaba guardado en tu equipo, sin un aviso de error más', () => {
    entorno.enLinea.set(false);
    const { fixture, el, avisos } = montar();
    http.expectOne((r) => r.url.startsWith(`${PUBLICO}/catalogo?`)).error(new ProgressEvent('error'));
    referencias();
    fixture.detectChanges();

    expect(qs(el, 'catalogo-error')?.textContent).toContain('Sin conexión: esta parte del catálogo no estaba guardada');
    expect(avisos).toEqual([]);
  });

  it('con conexión el error sigue siendo el de siempre y avisa', () => {
    const { fixture, el, avisos } = montar();
    http.expectOne((r) => r.url.startsWith(`${PUBLICO}/catalogo?`)).flush({ detail: 'Falla' }, { status: 500, statusText: 'Error' });
    referencias();
    fixture.detectChanges();

    expect(qs(el, 'catalogo-error')?.textContent).toContain('No se pudo cargar el catálogo');
    expect(avisos).toHaveLength(1);
  });
});

// ---- Mis pedidos sin conexión -------------------------------------------------------------------------------------------------

describe('PedidosSinConexionComponent', () => {
  let fixture: ComponentFixture<PedidosSinConexionComponent>;
  let el: HTMLElement;

  async function montar(enLinea: boolean, pedidos: ReturnType<typeof pedido>[]): Promise<void> {
    entorno.enLinea.set(enLinea);
    for (const p of pedidos) await entorno.repo().registrarPedido(p);
    configurar();
    fixture = TestBed.createComponent(PedidosSinConexionComponent);
    el = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
    await esperar(fixture);
  }

  const tarjeta = (n: number) => el.querySelector<HTMLElement>(`[data-operacion="${pedido(n).operacion_id}"]`)!;

  it('sin pedidos explica cómo funciona', async () => {
    await montar(false, []);

    expect(qs(el, 'sin-pedidos')?.textContent).toContain('No tienes pedidos hechos sin conexión');
  });

  it('lista cada pedido con su estado: Pendiente de envío, Cobrado (con enlace a la compra) y Rechazado (con el motivo)', async () => {
    await montar(false, [
      pedido(1),
      pedido(2, { estado: 'cobrado', venta_id: 55, codigo_venta: 'V-0055', total: '398.00', mensaje: 'Cobramos tu pedido.', visto: false }),
      pedido(3, { estado: 'rechazado', motivo: 'stock_insuficiente', mensaje: 'La Polera 3 ya no tiene stock. No se cobró nada.' }),
    ]);

    expect(qs(tarjeta(1), 'chip-estado')?.textContent).toContain('Pendiente de envío');
    expect(texto(tarjeta(1))).toContain('Hasta Bs 398.00');

    expect(qs(tarjeta(2), 'chip-estado')?.textContent).toContain('Cobrado');
    expect(texto(tarjeta(2))).toContain('V-0055');
    expect(qs(tarjeta(2), 'ver-compra')?.getAttribute('href')).toBe('/t/acme/mis-compras/55');

    expect(qs(tarjeta(3), 'chip-estado')?.textContent).toContain('Rechazado');
    expect(qs(tarjeta(3), 'mensaje-rechazo')?.textContent).toContain('ya no tiene stock');
    expect(qs(tarjeta(3), 'ver-compra')).toBeNull();
    expect(qs(tarjeta(3), 'descartar-pedido')).toBeNull();
  });

  it('sin conexión avisa que los pedidos saldrán solos al volver la red', async () => {
    await montar(false, [pedido(1)]);

    expect(qs(el, 'cola-sin-conexion')?.textContent).toContain('cuando vuelva la conexión');
  });

  it('descartar un pedido pendiente pide confirmación y lo quita; cancelar lo deja', async () => {
    await montar(false, [pedido(1), pedido(2)]);

    (qs(tarjeta(1), 'descartar-pedido') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(qs(tarjeta(1), 'confirmar-descarte')?.textContent).toContain('No se cobrará nada');
    Array.from(tarjeta(1).querySelectorAll<HTMLButtonElement>('.confirmar button')).find((b) => texto(b) === 'Cancelar')!.click();
    fixture.detectChanges();
    expect(await entorno.repo().pedidos()).toHaveLength(2);

    (qs(tarjeta(1), 'descartar-pedido') as HTMLButtonElement).click();
    fixture.detectChanges();
    (qs(tarjeta(1), 'descartar-si') as HTMLButtonElement).click();
    await esperar(fixture);

    expect((await entorno.repo().pedidos()).map((p) => p.operacion_id)).toEqual([pedido(2).operacion_id]);
    expect(el.querySelector(`[data-operacion="${pedido(1).operacion_id}"]`)).toBeNull();
  });

  it('si ya se intentó enviar, la confirmación avisa que podría haberse cobrado', async () => {
    await montar(false, [pedido(1, { intentos: 2, ultimo_error: 'paypal_no_disponible' })]);

    (qs(tarjeta(1), 'descartar-pedido') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(qs(tarjeta(1), 'confirmar-descarte')?.textContent).toContain('si llegó a cobrarse, lo verás en Mis compras');
    expect(qs(tarjeta(1), 'nota-reintento')).not.toBeNull();
  });

  it('un pedido vencido lo dice con el texto del plazo, se puede descartar y no cuenta como pendiente', async () => {
    await montar(false, [
      pedido(1, { estado: 'vencido', motivo: 'pedido_vencido', mensaje: 'Venció: pasaron más de 7 días sin conexión', resuelto_en: '2026-11-14T12:00:00Z' }),
    ]);

    expect(qs(tarjeta(1), 'chip-estado')?.textContent).toContain('Vencido');
    expect(qs(tarjeta(1), 'mensaje-vencido')?.textContent).toContain('Venció: pasaron más de 7 días sin conexión');
    expect(qs(el, 'cola-sin-conexion')).toBeNull();

    (qs(tarjeta(1), 'descartar-pedido') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(qs(tarjeta(1), 'confirmar-descarte')?.textContent).toContain('No se cobrará nada');
    (qs(tarjeta(1), 'descartar-si') as HTMLButtonElement).click();
    await esperar(fixture);

    expect(await entorno.repo().pedidos()).toEqual([]);
  });

  it('un pedido que se está enviando no se puede descartar', async () => {
    await montar(false, [pedido(1, { estado: 'enviando', intentos: 1, ultimo_intento_en: new Date().toISOString() })]);

    expect(qs(tarjeta(1), 'chip-estado')?.textContent).toContain('Enviando');
    expect(qs(tarjeta(1), 'descartar-pedido')).toBeNull();
  });

  it('ver la pantalla marca los resultados como vistos', async () => {
    await montar(false, [pedido(1, { estado: 'cobrado', visto: false })]);

    expect((await entorno.repo().pedido(pedido(1).operacion_id))?.visto).toBe(true);
  });

  it('con conexión muestra los avisos del servidor de tipo pedido_diferido (y solo esos), sin avisar de errores', async () => {
    await montar(true, [pedido(1, { estado: 'cobrado' })]);
    const peticion = http.expectOne(`${API}/notificaciones`);
    expect(peticion.request.context.get((await import('../../../core/http-contexts')).SIN_TOAST_ERROR)).toBe(true);
    peticion.flush([
      { id: 1, titulo: 'Cobramos tu pedido V-0055', mensaje: 'Total Bs 398.00', tipo: 'pedido_diferido', referencia_id: 55, leida: false, creado_en: '2026-11-06T18:00:00Z' },
      { id: 2, titulo: 'Otra cosa', mensaje: null, tipo: 'stock_bajo', referencia_id: null, leida: false, creado_en: '2026-11-06T18:00:00Z' },
    ]);
    await esperar(fixture);

    const avisos = qs(el, 'avisos-servidor')!;
    expect(avisos.textContent).toContain('Cobramos tu pedido V-0055');
    expect(avisos.textContent).not.toContain('Otra cosa');
  });

  it('si el servidor no entrega notificaciones al cliente, la pantalla sigue igual', async () => {
    await montar(true, [pedido(1)]);
    http.expectOne(`${API}/notificaciones`).flush({ detail: 'Prohibido' }, { status: 403, statusText: 'Forbidden' });
    await esperar(fixture);

    expect(qs(el, 'avisos-servidor')).toBeNull();
    expect(el.querySelectorAll('article.pedido')).toHaveLength(1);
  });
});

// ---- La franja de aviso de la tienda --------------------------------------------------------------------------------------------

describe('AvisoPedidosSinConexionComponent', () => {
  let fixture: ComponentFixture<AvisoPedidosSinConexionComponent>;
  let el: HTMLElement;

  async function montar(pedidos: ReturnType<typeof pedido>[]): Promise<void> {
    entorno.enLinea.set(false);
    for (const p of pedidos) await entorno.repo().registrarPedido(p);
    configurar();
    fixture = TestBed.createComponent(AvisoPedidosSinConexionComponent);
    el = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
    await esperar(fixture);
  }

  it('sin pedidos no muestra nada', async () => {
    await montar([]);
    expect(texto(el)).toBe('');
  });

  it('con pedidos por enviar cuenta cuántos hay y enlaza a la lista', async () => {
    await montar([pedido(1), pedido(2)]);

    expect(qs(el, 'aviso-pendientes')?.textContent).toContain('Tienes 2 pedidos sin conexión por enviar');
    expect(qs(el, 'aviso-pendientes')?.querySelector('a')?.getAttribute('href')).toBe('/t/acme/mi-cuenta/pedidos-sin-conexion');
  });

  it('cuando un pedido pasa a cobrado avisa con el resultado (y gana a "por enviar")', async () => {
    await montar([pedido(1), pedido(2, { estado: 'cobrado', visto: false })]);

    expect(qs(el, 'aviso-resultado')?.textContent).toContain('Cobramos 1 pedido que hiciste sin conexión');
    expect(qs(el, 'aviso-pendientes')).toBeNull();
  });

  it('cuando un pedido fue rechazado lo avisa como error', async () => {
    await montar([pedido(1, { estado: 'rechazado', visto: false, motivo: 'stock_insuficiente' })]);

    expect(qs(el, 'aviso-resultado')?.textContent).toContain('No pudimos cobrar 1');
    expect(qs(el, 'aviso-resultado')?.classList).toContain('franja--error');
  });

  it('un resultado ya visto no vuelve a avisar', async () => {
    await montar([pedido(1, { estado: 'cobrado', visto: true })]);

    expect(texto(el)).toBe('');
  });
});
