import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { ConectividadService } from '../../core/conectividad.service';
import { IndicadorConexionComponent } from './indicador-conexion.component';

describe('IndicadorConexionComponent', () => {
  beforeEach(() => TestBed.configureTestingModule({ providers: [provideRouter([])] }));

  afterEach(() => {
    delete (navigator as { onLine?: boolean }).onLine;
    vi.unstubAllGlobals();
  });

  function crear(entradas: { pendientes?: number; variante?: 'pastilla' | 'franja' } = {}): {
    fixture: ComponentFixture<IndicadorConexionComponent>;
    el: HTMLElement;
  } {
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => true });
    const fixture = TestBed.createComponent(IndicadorConexionComponent);
    for (const [nombre, valor] of Object.entries(entradas)) fixture.componentRef.setInput(nombre, valor);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  function sinConexion(fixture: ComponentFixture<IndicadorConexionComponent>): void {
    window.dispatchEvent(new Event('offline'));
    fixture.detectChanges();
  }

  it('en línea y sin pendientes no muestra texto, solo el punto con su aria-label', () => {
    const { el } = crear();

    expect(el.textContent?.trim()).toBe('');
    const punto = el.querySelector('[aria-label="En línea"]');
    expect(punto).not.toBeNull();
    expect(punto?.getAttribute('role')).toBe('img');
    expect(el.querySelector('.fs-chip')).toBeNull();
    // El contenedor que anuncia los cambios existe aunque no haya nada que decir.
    const estado = el.querySelector('[role="status"]');
    expect(estado?.getAttribute('aria-live')).toBe('polite');
  });

  it('sin conexión con 3 pendientes muestra "Sin conexión" y "3 por enviar" en un chip ámbar', () => {
    const { fixture, el } = crear({ pendientes: 3 });

    sinConexion(fixture);

    const chip = el.querySelector('.fs-chip') as HTMLElement;
    expect(chip.textContent).toContain('Sin conexión');
    expect(chip.textContent).toContain('3 por enviar');
    expect(chip.classList).toContain('fs-chip--advertencia');
    expect(el.querySelector('[aria-label="En línea"]')).toBeNull();
  });

  it('con el servidor caído muestra un chip rojo, sin decir que no hay conexión', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))));
    const { fixture, el } = crear();

    await TestBed.inject(ConectividadService).verificarServidor();
    fixture.detectChanges();

    const chip = el.querySelector('.fs-chip') as HTMLElement;
    expect(chip.textContent).toContain('Servidor no responde');
    expect(chip.textContent).not.toContain('Sin conexión');
    expect(chip.classList).toContain('fs-chip--error');
  });

  it('en línea con pendientes los anuncia en el chip, sin el punto solitario', () => {
    const { el } = crear({ pendientes: 2 });

    expect(el.querySelector('.fs-chip')?.textContent).toContain('2 por enviar');
    expect(el.querySelector('[aria-label="En línea"]')).toBeNull();
  });

  it('con `enlace` y pendientes el chip es un enlace a esa ruta', () => {
    const { fixture, el } = crear({ pendientes: 2 });
    fixture.componentRef.setInput('enlace', '/operaciones-pendientes');
    fixture.detectChanges();

    const enlace = el.querySelector('a.fs-chip') as HTMLAnchorElement;
    expect(enlace).not.toBeNull();
    expect(enlace.getAttribute('href')).toBe('/operaciones-pendientes');
    expect(enlace.textContent).toContain('2 por enviar');
  });

  it('con `enlace` pero sin pendientes no hay enlace (y sin `enlace` el chip sigue siendo texto)', () => {
    const { fixture, el } = crear();
    fixture.componentRef.setInput('enlace', '/operaciones-pendientes');
    window.dispatchEvent(new Event('offline'));
    fixture.detectChanges();

    expect(el.querySelector('.fs-chip')?.textContent).toContain('Sin conexión');
    expect(el.querySelector('a')).toBeNull();

    fixture.componentRef.setInput('pendientes', 1);
    fixture.componentRef.setInput('enlace', null);
    fixture.detectChanges();
    expect(el.querySelector('a')).toBeNull();
    expect(el.querySelector('span.fs-chip')?.textContent).toContain('1 por enviar');
  });

  it('variante franja: no muestra nada en línea y la franja completa sin conexión', () => {
    const { fixture, el } = crear({ variante: 'franja' });

    expect(el.querySelector('.franja')).toBeNull();
    expect(el.textContent?.trim()).toBe('');
    expect(el.querySelector('[role="status"]')).not.toBeNull();

    sinConexion(fixture);

    const franja = el.querySelector('.franja') as HTMLElement;
    expect(franja).not.toBeNull();
    expect(franja.textContent).toContain('Sin conexión: ves lo que ya tenías cargado. La información puede estar desactualizada.');
    expect(el.querySelector('.fs-chip')).toBeNull();
  });

  it('variante franja: con el servidor caído (hay red) no aparece', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))));
    const { fixture, el } = crear({ variante: 'franja' });

    await TestBed.inject(ConectividadService).verificarServidor();
    fixture.detectChanges();

    expect(el.querySelector('.franja')).toBeNull();
  });
});
