import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import type { Venta } from '../../../core/models/ventas.models';
import { TiendaActualService } from '../state/tienda-actual.service';
import { ComprobanteCompraComponent, LineaDeComprobante, tieneComprobante } from './comprobante-compra.component';

const ENLACE = 'https://fashionstore.example/caja?venta=V-0042';

function venta(estado: string, extra: Partial<Venta> = {}): Venta {
  return {
    id: 42,
    codigo: 'V-0042',
    canal: 'digital',
    cliente_id: 1,
    sucursal_id: 3,
    cajero_id: null,
    reserva_id: null,
    estado,
    fecha: '2026-11-04T14:30:00Z',
    subtotal: 220,
    descuento: 20,
    costo_envio: 0,
    total: 200,
    detalle: [],
    enlace_verificacion: ENLACE,
    ...extra,
  } as unknown as Venta;
}

const LINEAS: LineaDeComprobante[] = [
  { id: 1, nombre: 'Polera Nike', detalle: 'M · Azul', cantidad: 2, subtotal: 200 },
];

describe('ComprobanteCompraComponent', () => {
  let fixture: ComponentFixture<ComprobanteCompraComponent>;

  function montar(v: Venta, lineas: LineaDeComprobante[] = LINEAS, sucursal: string | null = 'Central') {
    TestBed.configureTestingModule({ providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()] });
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    fixture = TestBed.createComponent(ComprobanteCompraComponent);
    fixture.componentRef.setInput('venta', v);
    fixture.componentRef.setInput('sucursalNombre', sucursal);
    fixture.componentRef.setInput('lineas', lineas);
    fixture.detectChanges();
  }

  /** El QR se dibuja de forma asíncrona (carga la librería bajo demanda). */
  async function esperarQr(): Promise<void> {
    // La primera carga de `qrcode` (import dinámico) puede tardar más de 1 s con la máquina cargada.
    await vi.waitFor(
      () => {
        fixture.detectChanges();
        expect(el().querySelector('[data-estado="comprobante-qr"]')).not.toBeNull();
      },
      { timeout: 10_000 },
    );
  }

  const el = () => fixture.nativeElement as HTMLElement;
  const texto = () => (el().textContent ?? '').replace(/\s+/g, ' ').trim();

  afterEach(() => vi.restoreAllMocks());

  it('solo una compra pagada o entregada tiene comprobante', () => {
    expect(tieneComprobante({ estado: 'pagada' })).toBe(true);
    expect(tieneComprobante({ estado: 'entregada' })).toBe(true);
    expect(tieneComprobante({ estado: 'pendiente_pago' })).toBe(false);
    expect(tieneComprobante({ estado: 'anulada' })).toBe(false);
  });

  it.each(['pagada', 'entregada'])('una compra %s muestra código, fecha local, sucursal, prendas, total y el QR', async (estado) => {
    montar(venta(estado));
    await esperarQr();

    expect(el().querySelector('[data-estado="comprobante-compra"]')).not.toBeNull();
    expect(el().querySelector('[data-estado="comprobante-codigo"]')?.textContent).toBe('V-0042');
    expect(texto()).toContain('Central');
    expect(texto()).toContain('Polera Nike');
    expect(texto()).toContain('M · Azul');
    expect(texto()).toContain('x2');
    expect(el().querySelector('[data-estado="comprobante-total"]')?.textContent).toContain('200.00');
    // La fecha sale en la hora LOCAL del navegador, no cortando el texto UTC.
    const local = new Date('2026-11-04T14:30:00Z');
    const dia = String(local.getDate()).padStart(2, '0');
    const hora = String(local.getHours()).padStart(2, '0');
    expect(texto()).toContain(`${dia}/11/2026 ${hora}:30`);

    const qr = el().querySelector('svg[data-estado="comprobante-qr"]') as SVGElement;
    expect(qr.getAttribute('viewBox')).toMatch(/^0 0 \d+ \d+$/);
    expect(qr.querySelector('path')?.getAttribute('d')?.length).toBeGreaterThan(100);
  });

  it.each(['pendiente_pago', 'anulada'])('una compra %s no muestra comprobante ni QR', async (estado) => {
    montar(venta(estado));
    await fixture.whenStable();
    fixture.detectChanges();

    expect(el().querySelector('[data-estado="comprobante-compra"]')).toBeNull();
    expect(el().querySelector('svg')).toBeNull();
    expect(el().querySelector('[data-estado="imprimir-comprobante"]')).toBeNull();
  });

  it('dibuja EXACTAMENTE el texto de enlace_verificacion: otro enlace da otro código', async () => {
    montar(venta('pagada'));
    await esperarQr();
    const rutaQr = () => el().querySelector('svg[data-estado="comprobante-qr"] path')?.getAttribute('d');
    const ruta = rutaQr();

    fixture.componentRef.setInput('venta', venta('pagada', { enlace_verificacion: 'https://fashionstore.example/caja?venta=V-0099' }));
    await vi.waitFor(() => {
      fixture.detectChanges();
      expect(rutaQr()).not.toBe(ruta);
    });
  });

  it('sin enlace_verificacion (el servidor aún no lo manda) muestra el comprobante sin QR y sin error', async () => {
    montar(venta('pagada', { enlace_verificacion: null }));
    await fixture.whenStable();
    fixture.detectChanges();

    expect(el().querySelector('[data-estado="comprobante-compra"]')).not.toBeNull();
    expect(el().querySelector('svg[data-estado="comprobante-qr"]')).toBeNull();
    expect(el().querySelector('[data-estado="comprobante-qr-error"]')).toBeNull();
  });

  it('"Imprimir o guardar PDF" abre el diálogo de impresión y le pone el código al título mientras dura', async () => {
    montar(venta('pagada'));
    await esperarQr();
    const titulo = document.title;
    let tituloAlImprimir = '';
    const imprimir = vi.spyOn(window, 'print').mockImplementation(() => {
      tituloAlImprimir = document.title;
    });

    (el().querySelector('[data-estado="imprimir-comprobante"]') as HTMLButtonElement).click();

    expect(imprimir).toHaveBeenCalledTimes(1);
    expect(tituloAlImprimir).toBe('Comprobante V-0042');
    // Al terminar de imprimir (o cancelar) el título vuelve a ser el de la página.
    window.dispatchEvent(new Event('afterprint'));
    expect(document.title).toBe(titulo);
  });

  it('la tarjeta es el área imprimible (la regla @media print de styles.scss solo deja ver #area-imprimible)', async () => {
    montar(venta('pagada'));
    await esperarQr();

    expect(el().querySelector('#area-imprimible')).not.toBeNull();
    expect(el().querySelector('#area-imprimible [data-estado="comprobante-qr"]')).not.toBeNull();
  });
});
