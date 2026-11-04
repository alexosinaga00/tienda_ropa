import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { environment } from '../../../../environments/environment';
import { TiendaActualService } from '../state/tienda-actual.service';
import { CarritoComponent } from './carrito.component';
import { PasosCompraComponent } from './pasos-compra.component';
import { ResumenCompraComponent } from './resumen-compra.component';

@Component({
  standalone: true,
  imports: [PasosCompraComponent],
  template: '<app-pasos-compra [actual]="paso" />',
})
class PasosHost {
  paso: 0 | 1 | 2 | 3 = 1;
}

@Component({
  standalone: true,
  imports: [ResumenCompraComponent],
  template: `<app-resumen-compra [subtotal]="subtotal" [descuento]="descuento" [envio]="envio" [total]="total" [cargando]="cargando">
    <button class="accion">Pagar</button>
  </app-resumen-compra>`,
})
class ResumenHost {
  subtotal: number | null = 438;
  descuento = 43.8;
  envio: number | null = 15;
  total: number | null = 409.2;
  cargando = false;
}

describe('PasosCompraComponent', () => {
  it('marca los pasos anteriores como hechos, el actual como vigente y los demás como pendientes', () => {
    const fixture = TestBed.createComponent(PasosHost);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const pasos = Array.from(el.querySelectorAll('li.paso'));

    expect(pasos.map((p) => p.querySelector('.paso__titulo')?.textContent?.trim())).toEqual([
      'Entrega',
      'Pago',
      'Confirmación',
    ]);
    expect(pasos[0].classList).toContain('paso--hecho');
    expect(pasos[0].querySelector('svg')).not.toBeNull();
    expect(pasos[1].classList).toContain('paso--vigente');
    expect(pasos[1].getAttribute('aria-current')).toBe('step');
    expect(pasos[2].classList).not.toContain('paso--hecho');
    expect(pasos[2].classList).not.toContain('paso--vigente');
    expect(pasos[2].querySelector('.paso__circulo')?.textContent?.trim()).toBe('3');
  });

  it('los pasos hechos llevan el texto oculto "completado" para lectores de pantalla', () => {
    const fixture = TestBed.createComponent(PasosHost);
    fixture.detectChanges();
    const pasos = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('li.paso'));

    expect(pasos[0].querySelector('.solo-lector')?.textContent).toContain('completado');
    expect(pasos[1].querySelector('.solo-lector')).toBeNull();
    expect(pasos[2].querySelector('.solo-lector')).toBeNull();
  });

  it('con 3 los tres pasos están hechos y ninguno vigente', () => {
    const fixture = TestBed.createComponent(PasosHost);
    fixture.componentInstance.paso = 3;
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;

    expect(el.querySelectorAll('li.paso--hecho').length).toBe(3);
    expect(el.querySelector('li.paso--vigente')).toBeNull();
    expect(el.querySelector('[aria-current="step"]')).toBeNull();
  });
});

describe('ResumenCompraComponent', () => {
  function crear(ajustes: Partial<ResumenHost> = {}): HTMLElement {
    const fixture = TestBed.createComponent(ResumenHost);
    Object.assign(fixture.componentInstance, ajustes);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('muestra subtotal, descuento, envío y total en Bs, y proyecta la acción', () => {
    const texto = crear().textContent ?? '';

    expect(texto).toContain('Bs 438.00');
    expect(texto).toContain('- Bs 43.80');
    expect(texto).toContain('Bs 15.00');
    expect(texto).toContain('Bs 409.20');
    expect(crear().querySelector('button.accion')).not.toBeNull();
  });

  it('omite el descuento en cero y el envío desconocido', () => {
    const texto = crear({ descuento: 0, envio: null }).textContent ?? '';

    expect(texto).not.toContain('Descuento');
    expect(texto).not.toContain('Envío');
  });

  it('sin importes avisa que se está calculando o que no se pudo', () => {
    expect(crear({ subtotal: null, total: null, cargando: true }).textContent).toContain('Calculando…');
    expect(crear({ subtotal: null, total: null, cargando: false }).textContent).toContain(
      'No se pudo calcular el resumen.',
    );
  });
});

describe('CarritoComponent', () => {
  let http: HttpTestingController;

  function montar(): { el: HTMLElement; fixture: ReturnType<typeof TestBed.createComponent<CarritoComponent>> } {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(CarritoComponent);
    fixture.detectChanges();
    return { el: fixture.nativeElement as HTMLElement, fixture };
  }

  function carrito(disponible: boolean) {
    return {
      id: 1,
      cliente_id: 1,
      sucursal_id: null,
      actualizado_en: '2026-10-22T10:00:00',
      subtotal: 289,
      detalle: [
        { id: 1, variante_id: 10, cantidad: 1, precio_unitario: 289, subtotal: 289, disponible },
      ],
    };
  }

  function cargarCon(disponible: boolean, fixture: ReturnType<typeof montar>['fixture']): void {
    http.expectOne(`${environment.apiUrl}/carrito`).flush(carrito(disponible));
    http
      .expectOne((r) => r.url === `${environment.apiUrl}/catalogo/variantes/detalle`)
      .flush([
        {
          variante_id: 10,
          producto_id: 1,
          producto_nombre: 'Camisa Oxford',
          imagen_principal: null,
          talla_codigo: 'M',
          color_nombre: 'Celeste',
        },
      ]);
    http
      .expectOne(`${environment.apiUrl}/carrito/aplicar-promocion`)
      .flush({ lineas: [], subtotal: 289, descuento: 28.9, total: 260.1 });
    fixture.detectChanges();
  }

  afterEach(() => localStorage.clear());

  it('carrito vacío: mensaje en tuteo y enlace al catálogo', () => {
    const { el, fixture } = montar();
    http.expectOne(`${environment.apiUrl}/carrito`).flush({ ...carrito(true), detalle: [] });
    fixture.detectChanges();

    expect(el.textContent).toContain('Todavía no has agregado ninguna prenda.');
    const enlace = Array.from(el.querySelectorAll('a')).find((a) => a.textContent?.includes('Ver catálogo'));
    expect(enlace?.getAttribute('href')).toBe('/t/acme');
  });

  it('muestra la prenda, el resumen con descuento y continúa al checkout', async () => {
    const { el, fixture } = montar();
    cargarCon(true, fixture);

    expect(el.textContent).toContain('Camisa Oxford');
    expect(el.textContent).toContain('M · Celeste');
    expect(el.textContent).toContain('Bs 289.00');
    expect(el.textContent).toContain('- Bs 28.90');
    expect(el.textContent).toContain('Bs 260.10');

    const navegar = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    const continuar = el.querySelector('button.continuar') as HTMLButtonElement;
    expect(continuar.disabled).toBe(false);
    continuar.click();
    expect(navegar).toHaveBeenCalledWith(['/t', 'acme', 'checkout', 'entrega']);
  });

  it('con una compra sin pagar avisa que sus prendas ya no están aquí y enlaza a ella', () => {
    const { el, fixture } = montar();
    http.expectOne(`${environment.apiUrl}/carrito`).flush({ ...carrito(true), detalle: [] });
    http.expectOne(`${environment.apiUrl}/ventas/mis-compras`).flush([
      { id: 9, codigo: 'V-0009', estado: 'pendiente_pago', total: 149, detalle: [] },
      { id: 8, codigo: 'V-0008', estado: 'pagada', total: 50, detalle: [] },
    ]);
    fixture.detectChanges();

    const aviso = el.querySelector('[data-estado="compras-pendientes"]');
    expect((aviso?.textContent ?? '').replace(/\s+/g, ' ')).toContain('Tienes una compra sin pagar');
    expect(aviso?.querySelector('a')?.getAttribute('href')).toBe('/t/acme/mis-compras/9');
    // El carrito sigue diciendo que está vacío: las prendas pasaron a la compra.
    expect(el.textContent).toContain('Todavía no has agregado ninguna prenda.');
  });

  it('sin compras pendientes (o si no se pudieron leer) no muestra aviso', () => {
    const { el, fixture } = montar();
    http.expectOne(`${environment.apiUrl}/carrito`).flush({ ...carrito(true), detalle: [] });
    http
      .expectOne(`${environment.apiUrl}/ventas/mis-compras`)
      .flush({ detail: 'x' }, { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(el.querySelector('[data-estado="compras-pendientes"]')).toBeNull();
    expect(el.textContent).toContain('Todavía no has agregado ninguna prenda.');
  });

  it('con una prenda que ya no está disponible avisa (en tuteo) y bloquea "Continuar"', () => {
    const { el, fixture } = montar();
    cargarCon(false, fixture);

    expect(el.textContent).toContain('Ya no está disponible: quítala para continuar');
    expect(el.querySelector('button.linea__quitar')?.getAttribute('aria-label')).toBe('Quitar Camisa Oxford');
    expect(el.textContent).toContain('Quita las prendas que ya no están disponibles');
    expect((el.querySelector('button.continuar') as HTMLButtonElement).disabled).toBe(true);
    expect((el.querySelector('button[aria-label="Aumentar cantidad"]') as HTMLButtonElement).disabled).toBe(true);
  });
});
