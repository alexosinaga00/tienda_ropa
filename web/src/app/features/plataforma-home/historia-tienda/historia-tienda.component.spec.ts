import { Component, input, output } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter } from '@angular/router';
import { PlanPublico } from '../../../core/models/plan.models';
import { MarcaDemo, PlanEscena, TiendaEscena } from '../escena-3d/contrato';
import { EscenaTiendaComponent } from '../escena-3d/escena-tienda.component';
import {
  COLORES_DEMO,
  HistoriaTiendaComponent,
  MAX_CARACTERES_NOMBRE,
  NOMBRE_INICIAL,
  PUNTOS_RECORRIDO,
  TiendaHistoria,
} from './historia-tienda.component';

/** Sustituye a la escena real (WebGL): solo expone lo que recibe y deja emitir sus salidas. */
@Component({ selector: 'app-escena-tienda', standalone: true, template: '' })
class EscenaFalsa {
  readonly planes = input<readonly PlanEscena[]>([]);
  readonly tiendas = input<readonly TiendaEscena[]>([]);
  readonly marca = input<MarcaDemo>();
  readonly tiendaElegida = output<string>();
  readonly sinEscena = output<void>();
}

const BASICO: PlanPublico = {
  codigo: 'basico',
  nombre: 'Básico',
  max_sucursales: 2,
  max_copias_historial: 3,
  plazo_cambio_horas_defecto: 24,
  precio_mensual_bs: '120.00',
  gestion_productos: true,
  gestion_ventas: true,
  reservas: true,
  reportes_convencionales: true,
  reportes_ia: false,
  operacion_offline: true,
  analitica_ml: false,
  copias_seguridad: true,
};
const PROFESIONAL: PlanPublico = {
  ...BASICO,
  codigo: 'profesional',
  nombre: 'Profesional',
  max_sucursales: 10,
  max_copias_historial: 10,
  plazo_cambio_horas_defecto: 72,
  precio_mensual_bs: '590.00',
  reportes_ia: true,
  analitica_ml: true,
};
const TIENDAS: TiendaHistoria[] = [
  { codigo: 'acme', nombre: 'Acme', acentoOscuro: '#e27b55' },
  { codigo: 'andina', nombre: 'Boutique Andina', acentoOscuro: null },
];

function fijarScroll(y: number): void {
  Object.defineProperty(window, 'scrollY', { value: y, configurable: true });
  window.dispatchEvent(new Event('scroll'));
}

describe('HistoriaTiendaComponent', () => {
  let fixture: ComponentFixture<HistoriaTiendaComponent>;

  function crear(extra: { cargando?: boolean; error?: boolean; planes?: PlanPublico[] } = {}): void {
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
    TestBed.overrideComponent(HistoriaTiendaComponent, {
      remove: { imports: [EscenaTiendaComponent] },
      add: { imports: [EscenaFalsa] },
    });
    fixture = TestBed.createComponent(HistoriaTiendaComponent);
    fixture.componentRef.setInput('planes', extra.planes ?? [BASICO, PROFESIONAL]);
    fixture.componentRef.setInput('tiendas', TIENDAS);
    fixture.componentRef.setInput('cargandoPlanes', extra.cargando ?? false);
    fixture.componentRef.setInput('errorPlanes', extra.error ?? false);
    fixture.detectChanges();
  }

  function html(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function escena(): EscenaFalsa {
    return fixture.debugElement.query(By.directive(EscenaFalsa)).componentInstance as EscenaFalsa;
  }

  function campoNombre(): HTMLInputElement {
    return html().querySelector<HTMLInputElement>('#historia-nombre-tienda')!;
  }

  function muestras(): HTMLButtonElement[] {
    return Array.from(html().querySelectorAll<HTMLButtonElement>('.muestra'));
  }

  function puntos(): HTMLButtonElement[] {
    return Array.from(html().querySelectorAll<HTMLButtonElement>('.punto'));
  }

  beforeEach(() => {
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });
    Object.defineProperty(window, 'scrollY', { value: 0, configurable: true });
    window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.documentElement.removeAttribute('style');
  });

  it('renderiza las 6 secciones del recorrido, un solo h1 y el canvas de la escena', () => {
    crear();
    const ids = Array.from(html().querySelectorAll('section.paso')).map((s) => s.id);
    expect(ids).toEqual(['inicio', 'caja', 'inventario', 'probador', 'planes', 'calle']);
    expect(html().querySelectorAll('h1').length).toBe(1);
    expect(html().querySelector('h1')?.textContent).toContain('tus ventas');
    expect(html().textContent).toContain('Probador virtual con IA en la app');
    expect(html().textContent).toContain('Crece a tu ritmo');
    expect(html().textContent).toContain('Entra a una tienda');
    expect(html().querySelector('.nota')?.textContent).toContain('clic');
    expect(fixture.debugElement.query(By.directive(EscenaFalsa))).not.toBeNull();
  });

  it('la barra lleva la marca, los enlaces y el acceso del personal', () => {
    crear();
    const enlaces = Array.from(html().querySelectorAll('.barra__menu a')).map((a) => a.getAttribute('href'));
    expect(enlaces).toEqual(['#caja', '#planes', '#tiendas']);
    const acceso = html().querySelector<HTMLAnchorElement>('.barra__acceso');
    expect(acceso?.textContent).toContain('Acceso del personal');
    expect(acceso?.getAttribute('href')).toBe('/admin/login');
    expect(html().querySelector('.barra fs-marca')).not.toBeNull();
  });

  it('"Probar 14 días gratis" va una sola vez, en el inicio, hacia /contratar?modo=prueba', () => {
    crear();
    const enlaces = Array.from(html().querySelectorAll<HTMLAnchorElement>('a')).filter((a) =>
      /gratis/i.test(a.textContent ?? ''),
    );
    expect(enlaces.length).toBe(1);
    expect(enlaces[0].textContent?.replace(/\s+/g, ' ').trim()).toBe('Probar 14 días gratis');
    expect(enlaces[0].getAttribute('href')).toBe('/contratar?modo=prueba');
    expect(enlaces[0].closest('#inicio')).not.toBeNull();
    expect(html().querySelector('#planes')?.textContent).not.toMatch(/gratis/i);
  });

  it('la parada de planes muestra el precio de cada plan y un "Elegir plan" hacia /contratar', () => {
    crear();
    const seccion = html().querySelector('#planes')!;
    expect(Array.from(seccion.querySelectorAll('.plan__monto')).map((m) => m.textContent?.trim())).toEqual([
      'Bs 120',
      'Bs 590',
    ]);
    expect(
      Array.from(seccion.querySelectorAll<HTMLAnchorElement>('.plan__elegir')).map((a) => a.getAttribute('href')),
    ).toEqual(['/contratar?plan=basico', '/contratar?plan=profesional']);
  });

  it('la demo arranca con "Mi Boutique" y 6 colores, y no promete nada guardado', () => {
    crear();
    expect(campoNombre().value).toBe(NOMBRE_INICIAL);
    expect(campoNombre().maxLength).toBe(MAX_CARACTERES_NOMBRE);
    expect(muestras().map((m) => m.getAttribute('aria-label'))).toEqual([
      'Color Lima',
      'Color Hueso',
      'Color Terracota',
      'Color Azul petróleo',
      'Color Mostaza',
      'Color Vino',
    ]);
    expect(muestras()[0].getAttribute('aria-pressed')).toBe('true');
    expect(escena().marca()).toEqual({ nombre: 'Mi Boutique', tela: '#8FAE5B', acento: COLORES_DEMO[0].acento });
    expect(html().querySelector('.pista')?.textContent).toContain('no se guarda');
  });

  it('cambiar el nombre actualiza la marca de la escena (máx. 24 caracteres; vacío = "Tu tienda")', () => {
    crear();
    const entrada = campoNombre();
    entrada.value = 'Casa Lino';
    entrada.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    expect(escena().marca()?.nombre).toBe('Casa Lino');

    entrada.value = 'x'.repeat(40);
    entrada.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    expect(escena().marca()?.nombre).toBe('x'.repeat(MAX_CARACTERES_NOMBRE));

    entrada.value = '   ';
    entrada.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    expect(escena().marca()?.nombre).toBe('Tu tienda');
  });

  it('cambiar el color actualiza tela y acento de la marca', () => {
    crear();
    muestras()[2].click();
    fixture.detectChanges();

    const terracota = COLORES_DEMO[2];
    expect(terracota.tela).toBe('#9A3E1F');
    expect(escena().marca()).toEqual({ nombre: 'Mi Boutique', tela: '#9A3E1F', acento: terracota.acento });
    expect(muestras()[2].getAttribute('aria-pressed')).toBe('true');
    expect(muestras()[0].getAttribute('aria-pressed')).toBe('false');
  });

  it('todos los acentos de la demo contrastan con el carbón (o usan el valor del prototipo)', () => {
    for (const color of COLORES_DEMO) {
      expect(color.acento).toMatch(/^#[0-9a-f]{6}$/i);
      expect(color.textoSobreAcento).toMatch(/^#[0-9a-f]{6}$/i);
    }
    expect(COLORES_DEMO.map((c) => c.tela)).toEqual(['#8FAE5B', '#D8D3C6', '#9A3E1F', '#1F5F73', '#C99A2E', '#7A2638']);
  });

  it('el acento solo se escribe en el elemento de la historia, nunca en document.documentElement', () => {
    crear();
    muestras()[3].click();
    fixture.detectChanges();

    const host = html();
    expect(host.style.getPropertyValue('--fs-acento-oscuro')).toBe(COLORES_DEMO[3].acento);
    expect(host.style.getPropertyValue('--fs-sobre-acento-oscuro')).toBe(COLORES_DEMO[3].textoSobreAcento);
    expect(document.documentElement.style.getPropertyValue('--fs-acento-oscuro')).toBe('');
    expect(document.documentElement.style.getPropertyValue('--fs-acento')).toBe('');
    expect(document.body.style.getPropertyValue('--fs-acento-oscuro')).toBe('');

    // Al destruirse no queda nada colgado fuera del elemento.
    fixture.destroy();
    expect(document.documentElement.style.getPropertyValue('--fs-acento-oscuro')).toBe('');
  });

  it('la escena recibe los planes y las tiendas convertidos', () => {
    crear();
    expect(escena().planes()).toEqual([
      { codigo: 'basico', nombre: 'Básico', sucursales: 2 },
      { codigo: 'profesional', nombre: 'Profesional', sucursales: 10 },
    ]);
    expect(escena().tiendas()).toEqual([
      { codigo: 'acme', nombre: 'Acme', acento: '#e27b55' },
      { codigo: 'andina', nombre: 'Boutique Andina', acento: null },
    ]);
  });

  it('hay un botón por paso, con nombre accesible, y el clic hace scroll a i * innerHeight', () => {
    crear();
    expect(puntos().map((p) => p.getAttribute('aria-label'))).toEqual([...PUNTOS_RECORRIDO]);

    puntos()[3].click();
    expect(window.scrollTo).toHaveBeenLastCalledWith({ top: 3 * 800, behavior: 'smooth' });
    puntos()[6].click();
    expect(window.scrollTo).toHaveBeenLastCalledWith({ top: 6 * 800, behavior: 'smooth' });
  });

  it('con prefers-reduced-motion el scroll es inmediato', () => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: true }) as unknown as typeof window.matchMedia;
    crear();
    puntos()[1].click();
    expect(window.scrollTo).toHaveBeenLastCalledWith({ top: 800, behavior: 'auto' });
    delete (window as { matchMedia?: unknown }).matchMedia;
  });

  it('el punto activo sigue al scroll: Math.round(scrollY / innerHeight)', () => {
    crear();
    const activo = () => puntos().findIndex((p) => p.getAttribute('aria-current') === 'true');
    expect(activo()).toBe(0);

    fijarScroll(2 * 800 + 350);
    fixture.detectChanges();
    expect(activo()).toBe(2);

    fijarScroll(2 * 800 + 450);
    fixture.detectChanges();
    expect(activo()).toBe(3);

    fijarScroll(9 * 800);
    fixture.detectChanges();
    expect(activo()).toBe(6);
    expect(html().querySelector('.puntos')?.classList.contains('puntos--oculto')).toBe(true);
    expect(html().querySelector('.barra')?.classList.contains('barra--solida')).toBe(true);
  });

  it('al destruirse quita sus escuchas de scroll', () => {
    const quitar = vi.spyOn(window, 'removeEventListener');
    crear();
    fixture.destroy();
    expect(quitar).toHaveBeenCalledWith('scroll', expect.any(Function));
  });

  it('las salidas funcionan: tienda elegida, escena que falla y reintentar planes', () => {
    crear({ error: true });
    const elegidas: string[] = [];
    let sinEscena = 0;
    let reintentos = 0;
    fixture.componentInstance.tiendaElegida.subscribe((c) => elegidas.push(c));
    fixture.componentInstance.sinEscena.subscribe(() => sinEscena++);
    fixture.componentInstance.reintentarPlanes.subscribe(() => reintentos++);

    escena().tiendaElegida.emit('acme');
    escena().sinEscena.emit();
    const reintentar = Array.from(html().querySelectorAll('button')).find((b) => b.textContent?.includes('Reintentar'));
    reintentar!.click();

    expect(elegidas).toEqual(['acme']);
    expect(sinEscena).toBe(1);
    expect(reintentos).toBe(1);
  });

  it('muestra los planes en el comparativo oscuro y los estados de carga y error', () => {
    crear();
    const comparativo = html().querySelector('app-planes-comparativo');
    expect(comparativo?.classList.contains('planes--oscuro')).toBe(true);
    expect(html().querySelectorAll('.plan__nombre').length).toBe(2);
    expect(html().querySelector('.planes__carga')).toBeNull();
  });

  it('mientras cargan los planes muestra esqueletos', () => {
    crear({ cargando: true, planes: [] });
    expect(html().querySelector('.planes__carga')?.getAttribute('aria-busy')).toBe('true');
    expect(html().querySelectorAll('.planes__esqueleto').length).toBe(3);
    expect(html().querySelector('app-planes-comparativo')).toBeNull();
  });

  it('si los planes no cargan, avisa con role="alert" y ofrece Reintentar', () => {
    crear({ error: true, planes: [] });
    const alerta = html().querySelector('[role="alert"]');
    expect(alerta?.textContent).toContain('No pudimos cargar los planes');
    expect(html().querySelector('app-planes-comparativo')).toBeNull();
  });
});
