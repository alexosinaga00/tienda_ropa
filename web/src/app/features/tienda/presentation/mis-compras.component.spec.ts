import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { environment } from '../../../../environments/environment';
import { TiendaActualService } from '../state/tienda-actual.service';
import { MisComprasComponent } from './mis-compras.component';

const API = environment.apiUrl;

const compra = (id: number, estado: string) => ({
  id,
  codigo: `V-${id}`,
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
  detalle: [],
});

describe('MisComprasComponent: compras sin pagar', () => {
  let http: HttpTestingController;

  function montar(compras: object[]) {
    TestBed.configureTestingModule({ providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()] });
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(MisComprasComponent);
    fixture.detectChanges();
    http.expectOne(`${API}/ventas/mis-compras`).flush(compras);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  const aviso = (el: HTMLElement) => el.querySelector('[data-estado="compras-pendientes"]');
  const texto = (el: Element | null) => (el?.textContent ?? '').replace(/\s+/g, ' ').trim();

  it('avisa arriba cuando hay una compra sin pagar', () => {
    const el = montar([compra(1, 'pendiente_pago'), compra(2, 'pagada')]);

    expect(texto(aviso(el))).toContain('Tienes una compra sin pagar.');
    expect(texto(aviso(el))).toContain('pagarla o cancelarla');
  });

  it('con varias lo dice en plural', () => {
    const el = montar([compra(1, 'pendiente_pago'), compra(2, 'pendiente_pago')]);

    expect(texto(aviso(el))).toContain('Tienes 2 compras sin pagar.');
  });

  it('una compra con devolución sigue "Pagada" pero lo dice (parcial o total)', () => {
    const linea = { id: 1, variante_id: 3, cantidad: 4, precio_unitario: 25, descuento_unitario: 0, costo_unitario: null, subtotal: 100 };
    const el = montar([
      { ...compra(1, 'pagada'), detalle: [linea], unidades_devueltas: 1 },
      { ...compra(2, 'pagada'), detalle: [linea], unidades_devueltas: 4 },
      { ...compra(3, 'pagada'), detalle: [linea] },
    ]);

    const marcas = Array.from(el.querySelectorAll('.fila')).map(
      (fila) => fila.querySelector('[data-estado="con-devolucion"]')?.textContent?.trim() ?? null,
    );
    expect(marcas).toEqual(['Con devolución (1 de 4)', 'Devuelta', null]);
    expect(texto(el.querySelector('.fila .fs-chip'))).toBe('Pagada');
  });

  it('sin compras pendientes no muestra ningún aviso', () => {
    const el = montar([compra(1, 'pagada'), compra(2, 'anulada')]);

    expect(aviso(el)).toBeNull();
  });
});

describe('MisComprasComponent: solicitudes de cambio pendientes', () => {
  let http: HttpTestingController;

  function montar(compras: object[], respuesta: { solicitudes?: object[]; falla?: boolean }) {
    TestBed.configureTestingModule({ providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()] });
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(MisComprasComponent);
    fixture.detectChanges();
    http.expectOne(`${API}/ventas/mis-compras`).flush(compras);
    const mias = http.expectOne(`${API}/solicitudes-cambio/mias`);
    if (respuesta.falla) mias.flush({}, { status: 500, statusText: 'Server Error' });
    else mias.flush(respuesta.solicitudes ?? []);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  const solicitud = (ventaId: number, estado: string) => ({ id: ventaId * 10, venta_id: ventaId, estado });
  const chips = (el: HTMLElement) =>
    Array.from(el.querySelectorAll('.fila')).map(
      (fila) => fila.querySelector('[data-estado="cambio-pendiente"]')?.textContent?.trim() ?? null,
    );

  it('marca solo las compras con una solicitud de cambio pendiente', () => {
    const el = montar([compra(1, 'pagada'), compra(2, 'pagada'), compra(3, 'entregada')], {
      solicitudes: [solicitud(1, 'pendiente'), solicitud(2, 'rechazada'), solicitud(2, 'aprobada')],
    });

    expect(chips(el)).toEqual(['Cambio pendiente', null, null]);
  });

  it('si la consulta de solicitudes falla, la lista de compras se ve igual y sin marcas', () => {
    const el = montar([compra(1, 'pagada')], { falla: true });

    expect(chips(el)).toEqual([null]);
    expect(el.textContent).toContain('V-1');
  });
});
