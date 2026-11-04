import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { DisponibilidadService } from '../data/disponibilidad.service';
import { ReservaCarritoService } from '../state/reserva-carrito.service';
import { TiendaActualService } from '../state/tienda-actual.service';
import { ReservaConfirmarComponent } from './reserva-confirmar.component';

describe('ReservaConfirmarComponent: sin prendas apartadas', () => {
  function montar(conPrendas: boolean) {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: DisponibilidadService, useValue: { sucursalesConStock: () => of([]) } },
      ],
    });
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
    const reservas = TestBed.inject(ReservaCarritoService);
    reservas.cambiarTienda('acme');
    if (conPrendas) {
      reservas.agregar({
        varianteId: 3,
        productoNombre: 'Polera',
        tallaCodigo: 'M',
        colorNombre: 'Azul',
        imagenPrincipal: null,
      });
    }
    const navegar = vi.spyOn(TestBed.inject(Router), 'navigate');
    const fixture = TestBed.createComponent(ReservaConfirmarComponent);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement, navegar };
  }

  const texto = (el: Element | null) => (el?.textContent ?? '').replace(/\s+/g, ' ').trim();

  it('en vez de volver al inicio en silencio, explica qué hacer y ofrece dos caminos', () => {
    const { el, navegar } = montar(false);

    expect(navegar).not.toHaveBeenCalled();
    const vacio = el.querySelector('[data-estado="reserva-vacia"]');
    expect(vacio).not.toBeNull();
    expect(texto(vacio)).toContain('Todavía no apartaste ninguna prenda');
    expect(texto(vacio)).toContain('Reservar para probarte');
    const enlaces = Array.from(vacio!.querySelectorAll('a')).map((a) => texto(a));
    expect(enlaces).toEqual(['Ver colección', 'Ver mis reservas']);
    // Nada del formulario de reserva (sucursal, fecha, confirmar).
    expect(el.querySelector('#fecha-visita')).toBeNull();
    expect(el.querySelector('button.confirmar')).toBeNull();
  });

  it('con prendas apartadas sigue el formulario de siempre y no muestra el mensaje vacío', () => {
    const { el } = montar(true);

    expect(el.querySelector('[data-estado="reserva-vacia"]')).toBeNull();
    expect(texto(el)).toContain('Polera');
    expect(texto(el)).toContain('¿En qué sucursal te pruebas las prendas?');
    expect(el.querySelector('button.confirmar')).not.toBeNull();
  });
});
