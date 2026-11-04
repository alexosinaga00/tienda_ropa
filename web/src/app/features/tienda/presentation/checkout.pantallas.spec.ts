import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, TestRequest, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { environment } from '../../../../environments/environment';
import { Venta } from '../../../core/models/ventas.models';
import { CarritoService } from '../data/carrito.service';
import { CheckoutService } from '../state/checkout.service';
import { TiendaActualService } from '../state/tienda-actual.service';
import { CheckoutEntregaComponent } from './checkout-entrega.component';
import { CheckoutEstadoComponent } from './checkout-estado.component';
import { CheckoutPagoComponent } from './checkout-pago.component';

const API = environment.apiUrl;
const PROMOCION = `${API}/carrito/aplicar-promocion`;

describe('pantallas del checkout', () => {
  let http: HttpTestingController;

  function preparar(extra: object[] = []): void {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting(), ...extra],
    });
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    http = TestBed.inject(HttpTestingController);
  }

  /** Deja una prenda en el carrito (lo que pide el carrito al cargar). */
  function cargarCarrito(vacio = false): void {
    TestBed.inject(CarritoService).cargar().subscribe();
    http.expectOne(`${API}/carrito`).flush({
      id: 1,
      cliente_id: 1,
      sucursal_id: null,
      actualizado_en: '2026-10-22T10:00:00',
      subtotal: 438,
      detalle: vacio
        ? []
        : [{ id: 1, variante_id: 10, cantidad: 2, precio_unitario: 219, subtotal: 438, disponible: true }],
    });
    if (vacio) return;
    http
      .expectOne((r) => r.url === `${API}/catalogo/variantes/detalle`)
      .flush([
        { variante_id: 10, producto_id: 1, producto_nombre: 'Polera', imagen_principal: null, talla_codigo: 'M', color_nombre: 'Blanco' },
      ]);
  }

  function promocion(): TestRequest {
    return http.expectOne(PROMOCION);
  }

  const RESUMEN = { lineas: [], subtotal: 438, descuento: 43.8, total: 394.2 };
  const COTIZACION = { zona_envio_id: 1, zona_nombre: 'Zona Sur', peso_kg: 1, tarifa_base: 15, recargo_peso: 0, costo: 15 };

  afterEach(() => localStorage.clear());

  describe('CheckoutEntregaComponent', () => {
    function montar(): { el: HTMLElement; fixture: ReturnType<typeof TestBed.createComponent<CheckoutEntregaComponent>> } {
      preparar();
      cargarCarrito();
      const fixture = TestBed.createComponent(CheckoutEntregaComponent);
      fixture.detectChanges();
      http.expectOne((r) => r.url.endsWith('/sucursales')).flush([
        { id: 1, nombre: 'Central', es_deposito: false },
        { id: 2, nombre: 'Depósito', es_deposito: true },
      ]);
      http
        .expectOne((r) => r.url.endsWith('/inventario/disponibilidad'))
        .flush([
          { sucursal_id: 1, cantidad_disponible: 9 },
          { sucursal_id: 2, cantidad_disponible: 9 },
        ]);
      promocion().flush(RESUMEN);
      fixture.detectChanges();
      return { el: fixture.nativeElement as HTMLElement, fixture };
    }

    function boton(el: HTMLElement, texto: string): HTMLButtonElement {
      return Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes(texto)) as HTMLButtonElement;
    }

    it('muestra el indicador en el paso 1 y el resumen sin envío mientras no se elige el tipo', () => {
      const { el } = montar();

      expect(el.querySelector('li.paso--vigente .paso__titulo')?.textContent).toContain('Entrega');
      expect(el.textContent).toContain('Bs 438.00');
      expect(el.textContent).toContain('- Bs 43.80');
      expect(el.textContent).toContain('Bs 394.20');
      expect(Array.from(el.querySelectorAll('.resumen__fila')).some((f) => f.textContent?.includes('Envío'))).toBe(false);
      expect(boton(el, 'Continuar al pago').disabled).toBe(true);
    });

    it('retiro: envío en Bs 0.00, total sin recargo y sin depósito entre las sucursales', () => {
      const { el, fixture } = montar();

      boton(el, 'Retiro en sucursal').click();
      fixture.detectChanges();

      expect(el.textContent).toContain('¿En qué sucursal retiras?');
      expect(el.textContent).toContain('Envío');
      expect(el.textContent).toContain('Bs 0.00');
      expect(el.textContent).toContain('Bs 394.20');
      expect(el.textContent).toContain('Central');
      expect(el.textContent).not.toContain('Depósito');

      boton(el, 'Central').click();
      fixture.detectChanges();
      expect(boton(el, 'Continuar al pago').disabled).toBe(false);
    });

    it('domicilio: el envío cotizado se suma al total', () => {
      const { el, fixture } = montar();

      boton(el, 'Envío a domicilio').click();
      http.expectOne(`${API}/clientes/direcciones`).flush([{ id: 7, alias: 'Casa', direccion: 'Av. Banzer 1240' }]);
      fixture.detectChanges();
      // Sin cotización todavía no se muestra el envío ni se inventa un total.
      expect(el.textContent).not.toContain('Bs 409.20');

      boton(el, 'Casa').click();
      http.expectOne(`${API}/envios/cotizar`).flush(COTIZACION);
      fixture.detectChanges();

      expect(el.textContent).toContain('Envío a Zona Sur');
      expect(el.textContent).toContain('Bs 15.00');
      expect(el.textContent).toContain('Bs 409.20');
    });
  });

  describe('CheckoutPagoComponent', () => {
    function venta(): Venta {
      return { id: 3, subtotal: 400, descuento: 40, costo_envio: 15, total: 375, detalle: [] } as unknown as Venta;
    }

    it('sin venta: pide el resumen y el botón paga el total más el envío', () => {
      preparar();
      cargarCarrito();
      const checkout = TestBed.inject(CheckoutService);
      checkout.elegirTipoEntrega('domicilio');
      checkout.fijarCotizacion(COTIZACION);
      const fixture = TestBed.createComponent(CheckoutPagoComponent);
      fixture.detectChanges();
      promocion().flush(RESUMEN);
      fixture.detectChanges();
      const el = fixture.nativeElement as HTMLElement;

      expect(el.querySelector('li.paso--vigente .paso__titulo')?.textContent).toContain('Pago');
      expect(el.textContent).toContain('Pagar Bs 409.20');
      expect(el.textContent).toContain('Costo de envío Bs 15.00');
      // Solo QR y PayPal: Libélula ya no se ofrece.
      expect(Array.from(el.querySelectorAll('.metodo__nombre')).map((n) => n.textContent?.trim())).toEqual(['QR', 'PayPal']);
      expect(el.textContent).not.toContain('Libélula');
      expect(el.querySelector('a.entrega__cambiar')).not.toBeNull();
    });

    it('con la venta ya registrada usa sus importes y no vuelve a pedir el resumen', () => {
      preparar();
      cargarCarrito(true);
      const checkout = TestBed.inject(CheckoutService);
      checkout.elegirTipoEntrega('domicilio');
      checkout.fijarCotizacion(COTIZACION);
      checkout.confirmarVenta(venta());
      const fixture = TestBed.createComponent(CheckoutPagoComponent);
      fixture.detectChanges();
      const el = fixture.nativeElement as HTMLElement;

      http.expectNone(PROMOCION);
      expect(el.textContent).toContain('Pagar Bs 375.00');
      expect(el.textContent).toContain('Bs 400.00');
      expect(el.textContent).toContain('- Bs 40.00');
      expect(el.querySelector('a.entrega__cambiar')).toBeNull();
    });

    it('con el carrito vacío y sin venta no pide el resumen', () => {
      preparar();
      cargarCarrito(true);
      const fixture = TestBed.createComponent(CheckoutPagoComponent);
      fixture.detectChanges();

      http.expectNone(PROMOCION);
      expect((fixture.nativeElement as HTMLElement).textContent).toContain('No se pudo calcular el resumen.');
    });
  });

  describe('CheckoutEstadoComponent', () => {
    function montar(): { el: HTMLElement; fixture: ReturnType<typeof TestBed.createComponent<CheckoutEstadoComponent>> } {
      preparar([
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: convertToParamMap({ pagoId: '5' }) } },
        },
      ]);
      const fixture = TestBed.createComponent(CheckoutEstadoComponent);
      fixture.detectChanges();
      return { el: fixture.nativeElement as HTMLElement, fixture };
    }

    function estadoPago(estado: string) {
      return { id: 5, venta_id: 3, monto: 10, referencia_externa: null, fecha: '2026-10-22', metodo_pago: 'qr_online', estado };
    }

    const consulta = () => http.expectOne(`${API}/pagos/5/estado`);

    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('mientras consulta muestra el estado de espera', () => {
      const { el } = montar();

      expect(el.textContent).toContain('Consultando el estado del pago...');
      consulta().flush(estadoPago('iniciado'));
    });

    it('aprobado: panel de éxito y los tres pasos hechos', () => {
      const { el, fixture } = montar();
      consulta().flush(estadoPago('aprobado'));
      fixture.detectChanges();

      expect(el.textContent).toContain('¡Pago aprobado!');
      expect(el.querySelectorAll('li.paso--hecho').length).toBe(3);
      expect(el.querySelector('li.paso--vigente')).toBeNull();
      expect(el.querySelector('.paso .solo-lector')?.textContent).toContain('completado');
    });

    it('rechazado: panel de error, reintentar y el paso 3 sigue vigente', () => {
      const { el, fixture } = montar();
      consulta().flush(estadoPago('rechazado'));
      fixture.detectChanges();

      expect(el.textContent).toContain('El pago fue rechazado');
      expect(el.textContent).toContain('Puedes intentarlo de nuevo');
      expect(el.querySelector('li.paso--vigente .paso__titulo')?.textContent).toContain('Confirmación');
      expect(el.querySelectorAll('li.paso--hecho').length).toBe(2);
    });

    it('espera de la pasarela: ofrece "Ya completé el pago"', () => {
      const { el, fixture } = montar();
      consulta().flush(estadoPago('iniciado'));
      fixture.detectChanges();

      expect(el.textContent).toContain('Esperando la confirmación de la pasarela...');
      expect(el.textContent).toContain('Ya completé el pago');
    });

    it('tras varias consultas pendientes queda "pendiente de confirmación"', () => {
      const { el, fixture } = montar();
      consulta().flush(estadoPago('iniciado'));
      for (let i = 0; i < 19; i++) {
        vi.advanceTimersByTime(3000);
        consulta().flush(estadoPago('iniciado'));
      }
      fixture.detectChanges();

      expect(el.textContent).toContain('Pago pendiente de confirmación');
      expect(el.textContent).toContain('Puedes reintentar el pago');
    });

    it('tras varios errores de red avisa que no pudo consultar', () => {
      const { el, fixture } = montar();
      consulta().flush('x', { status: 500, statusText: 'Error' });
      for (let i = 0; i < 4; i++) {
        vi.advanceTimersByTime(3000);
        consulta().flush('x', { status: 500, statusText: 'Error' });
      }
      fixture.detectChanges();

      expect(el.textContent).toContain('No pudimos consultar el estado');
      expect(el.textContent).toContain('revísalo en "Mis compras"');
      expect(el.textContent).toContain('Volver a consultar');
    });
  });
});
