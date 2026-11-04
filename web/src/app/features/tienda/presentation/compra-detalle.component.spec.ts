import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { environment } from '../../../../environments/environment';
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
