import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, provideRouter } from '@angular/router';
import { environment } from '../../../../environments/environment';
import { AvisosMostradosService, claveDeVenta } from '../../../core/avisos-mostrados.service';
import { TiendaActualService } from '../state/tienda-actual.service';
import { CheckoutEstadoComponent } from './checkout-estado.component';

const API = environment.apiUrl;

const pago = (estado: string) => ({
  id: 9,
  venta_id: 42,
  monto: 200,
  referencia_externa: null,
  fecha: '2026-11-04T10:00:00Z',
  metodo_pago: 'paypal',
  estado,
});

describe('CheckoutEstadoComponent: pago aprobado', () => {
  let http: HttpTestingController;

  function montar() {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: { get: () => '9' } } } },
      ],
    });
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(CheckoutEstadoComponent);
    fixture.detectChanges();
    return fixture;
  }

  afterEach(() => http.match(() => true));

  it('un pago aprobado ofrece "Ver mi compra" y "Ver comprobante", y los dos llevan al detalle de la compra', () => {
    const fixture = montar();
    http.expectOne(`${API}/pagos/9/estado`).flush(pago('aprobado'));
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const navegar = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    const comprobante = el.querySelector('[data-estado="ver-comprobante"]') as HTMLButtonElement;
    expect(comprobante.textContent).toContain('Ver comprobante');
    comprobante.click();

    expect(navegar).toHaveBeenCalledWith(['/t', 'acme', 'mis-compras', '42']);
    const botones = Array.from(el.querySelectorAll('.panel__acciones button')).map((b) => b.textContent?.trim());
    expect(botones).toEqual(['Ver mi compra', 'Ver comprobante']);
  });

  it('el panel de pago aprobado anota la compra: el aviso push de esa venta ya no sale como toast', () => {
    const fixture = montar();
    const avisos = TestBed.inject(AvisosMostradosService);
    expect(avisos.yaAvisado(claveDeVenta(42))).toBe(false);

    http.expectOne(`${API}/pagos/9/estado`).flush(pago('aprobado'));
    fixture.detectChanges();

    expect(avisos.yaAvisado(claveDeVenta(42))).toBe(true);
  });

  it('un pago rechazado o pendiente no ofrece comprobante ni anota nada', () => {
    const fixture = montar();
    http.expectOne(`${API}/pagos/9/estado`).flush(pago('rechazado'));
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).querySelector('[data-estado="ver-comprobante"]')).toBeNull();
    expect(TestBed.inject(AvisosMostradosService).yaAvisado(claveDeVenta(42))).toBe(false);
  });
});
