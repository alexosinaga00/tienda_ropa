import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, input, output } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By, Title } from '@angular/platform-browser';
import { Router, provideRouter } from '@angular/router';
import { MessageService } from 'primeng/api';
import { environment } from '../../../environments/environment';
import { ResumenTienda } from '../../core/models/empresa.models';
import { PlanPublico } from '../../core/models/plan.models';
import { CLAVE_ULTIMA_TIENDA } from '../tienda/state/tienda-actual.service';
import { MarcaDemo, PlanEscena, TiendaEscena } from './escena-3d/contrato';
import { EscenaTiendaComponent } from './escena-3d/escena-tienda.component';
import { HistoriaTiendaComponent } from './historia-tienda/historia-tienda.component';
import {
  PUEDE_USAR_ESCENA_3D,
  PlataformaHomeComponent,
  RUTA_ACCESO_PERSONAL,
  TAMANIO_PAGINA_TIENDAS,
} from './plataforma-home.component';

/** Sustituye a la escena real (WebGL) en el modo historia. */
@Component({ selector: 'app-escena-tienda', standalone: true, template: '' })
class EscenaFalsa {
  readonly planes = input<readonly PlanEscena[]>([]);
  readonly tiendas = input<readonly TiendaEscena[]>([]);
  readonly marca = input<MarcaDemo>();
  readonly tiendaElegida = output<string>();
  readonly sinEscena = output<void>();
}

const URL_TIENDAS = `${environment.apiUrl}/public/tiendas`;
const URL_PLANES = `${environment.apiUrl}/public/planes`;

const PLAN_BASICO: PlanPublico = {
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
const PLAN_PROFESIONAL: PlanPublico = {
  ...PLAN_BASICO,
  codigo: 'profesional',
  nombre: 'Profesional',
  max_sucursales: 10,
  max_copias_historial: 10,
  plazo_cambio_horas_defecto: 72,
  precio_mensual_bs: '590.00',
  reportes_ia: true,
  analitica_ml: true,
};

function tienda(codigo: string, nombre = codigo, extra: Partial<ResumenTienda> = {}): ResumenTienda {
  return { codigo, nombre, logo_url: null, color_acento: null, ...extra };
}

function filas(cantidad: number, desde = 0): ResumenTienda[] {
  return Array.from({ length: cantidad }, (_, i) => tienda(`t${desde + i}`, `Tienda ${desde + i}`));
}

describe('PlataformaHomeComponent', () => {
  let controller: HttpTestingController;
  let fixture: ComponentFixture<PlataformaHomeComponent>;

  function crear(modo3d = false): void {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        MessageService,
        // La capacidad de la escena depende del navegador (WebGL, movimiento): aquí se simula.
        { provide: PUEDE_USAR_ESCENA_3D, useValue: () => modo3d },
      ],
    });
    TestBed.overrideComponent(HistoriaTiendaComponent, {
      remove: { imports: [EscenaTiendaComponent] },
      add: { imports: [EscenaFalsa] },
    });
    controller = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(PlataformaHomeComponent);
    fixture.detectChanges();
  }

  function pedidoTiendas(pagina: number, q = '') {
    return controller.expectOne(
      (r) =>
        r.url === URL_TIENDAS &&
        r.params.get('pagina') === String(pagina) &&
        r.params.get('q') === q &&
        r.params.get('tamanio') === String(TAMANIO_PAGINA_TIENDAS),
    );
  }

  /** Atiende GET /public/planes (la portada lo pide al iniciar). */
  function pedidoPlanes() {
    return controller.expectOne(URL_PLANES);
  }

  function html(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  afterEach(() => {
    vi.useRealTimers();
    // GET /public/planes lo pide la portada al iniciar; las pruebas de tiendas no lo miran.
    controller.match(URL_PLANES).forEach((p) => p.flush([]));
    try {
      localStorage.clear();
    } catch {
      // sin localStorage
    }
  });

  it('fija el título de la plataforma y muestra el acceso del personal', () => {
    crear();
    pedidoTiendas(1).flush([]);
    fixture.detectChanges();

    expect(TestBed.inject(Title).getTitle()).toBe('FashionStore | Tiendas de ropa');
    const acceso = html().querySelector<HTMLAnchorElement>('.home-acceso');
    expect(acceso?.textContent).toContain('Acceso del personal');
    expect(acceso?.getAttribute('href')).toBe(RUTA_ACCESO_PERSONAL);
    expect(html().textContent).toContain('Visita una tienda');
    expect(html().textContent).toContain('FashionStore · Plataforma para tiendas de ropa');
  });

  it('presenta los servicios y no promete como futuro lo que ya existe', () => {
    crear();
    pedidoTiendas(1).flush([]);
    pedidoPlanes().flush([PLAN_BASICO, PLAN_PROFESIONAL]);
    fixture.detectChanges();

    const texto = html().textContent ?? '';
    expect(html().querySelectorAll('.home-servicio').length).toBe(6);
    expect(texto).not.toMatch(/próximamente/i);
    expect(texto).not.toMatch(/\[(N|precio)\]/);
    expect(texto).not.toContain('Bs [');
    // Sin endpoint de alta: la franja final lleva al acceso del personal, no a un formulario.
    expect(html().querySelector('form')).toBeNull();
    expect(html().querySelector('.home-cta__enlace')?.getAttribute('href')).toBe(RUTA_ACCESO_PERSONAL);
  });

  it('pide los planes al iniciar y los presenta en el comparativo, con su precio por mes', () => {
    crear();
    pedidoTiendas(1).flush([]);
    expect(html().querySelectorAll('.home-plan-esqueleto').length).toBe(3);

    pedidoPlanes().flush([PLAN_BASICO, PLAN_PROFESIONAL]);
    fixture.detectChanges();

    expect(html().querySelectorAll('.home-plan-esqueleto').length).toBe(0);
    expect(html().textContent).toContain('Crece a tu ritmo');
    expect(Array.from(html().querySelectorAll('.plan__nombre')).map((n) => n.textContent?.trim())).toEqual([
      'Básico',
      'Profesional',
    ]);
    expect(html().textContent).toContain('Todos los planes incluyen:');
    const seccion = html().querySelector('#planes')!;
    expect(Array.from(seccion.querySelectorAll('.plan__monto')).map((m) => m.textContent?.trim())).toEqual([
      'Bs 120',
      'Bs 590',
    ]);
    expect(
      Array.from(seccion.querySelectorAll<HTMLAnchorElement>('.plan__elegir')).map((a) => a.getAttribute('href')),
    ).toEqual(['/contratar?plan=basico', '/contratar?plan=profesional']);
  });

  it('la prueba gratis aparece una sola vez, en el inicio, y lleva a /contratar?modo=prueba', () => {
    crear();
    pedidoTiendas(1).flush([]);
    pedidoPlanes().flush([PLAN_BASICO, PLAN_PROFESIONAL]);
    fixture.detectChanges();

    const enlaces = Array.from(html().querySelectorAll<HTMLAnchorElement>('a')).filter((a) =>
      /gratis/i.test(a.textContent ?? ''),
    );
    expect(enlaces.length).toBe(1);
    expect(enlaces[0].textContent?.replace(/\s+/g, ' ').trim()).toBe('Probar 14 días gratis');
    expect(enlaces[0].getAttribute('href')).toBe('/contratar?modo=prueba');
    expect(enlaces[0].closest('.home-hero')).not.toBeNull();
    expect(html().querySelector('#planes')?.textContent).not.toMatch(/gratis/i);
  });

  it('si los planes no cargan, avisa y Reintentar vuelve a pedirlos', () => {
    crear();
    pedidoTiendas(1).flush([]);
    pedidoPlanes().flush('boom', { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(html().textContent).toContain('No pudimos cargar los planes');
    expect(html().querySelectorAll('.plan').length).toBe(0);
    const boton = Array.from(html().querySelectorAll('button')).find(
      (b) => b.closest('#planes') && b.textContent?.includes('Reintentar'),
    );
    expect(boton).toBeDefined();

    boton!.click();
    pedidoPlanes().flush([PLAN_BASICO]);
    fixture.detectChanges();

    expect(html().textContent).not.toContain('No pudimos cargar los planes');
    expect(html().querySelectorAll('.plan').length).toBe(1);
  });

  it('muestra esqueletos mientras carga y luego una tarjeta por tienda, con enlace a /t/<codigo>', () => {
    crear();
    expect(html().querySelectorAll('.tarjeta--esqueleto').length).toBe(6);

    pedidoTiendas(1).flush([tienda('acme', 'Acme', { color_acento: '#9a3e1f' }), tienda('andina', 'Boutique Andina')]);
    fixture.detectChanges();

    expect(html().querySelectorAll('.tarjeta--esqueleto').length).toBe(0);
    const enlaces = Array.from(html().querySelectorAll<HTMLAnchorElement>('a.tarjeta'));
    expect(enlaces.map((a) => a.getAttribute('href'))).toEqual(['/t/acme', '/t/andina']);
    expect(enlaces[0].textContent).toContain('Acme');
    // Sin logo: las siglas de la marca.
    expect(enlaces[0].querySelector('.marca__monograma')?.textContent?.trim()).toBe('AC');
    expect(enlaces[0].style.getPropertyValue('--tarjeta-acento')).toBe('#9a3e1f');
    // Sin color propio: queda el acento base de la app.
    expect(enlaces[1].style.getPropertyValue('--tarjeta-acento')).toBe('');
  });

  it('solo usa logos http/https; otro esquema muestra las siglas', () => {
    crear();
    pedidoTiendas(1).flush([
      tienda('con', 'Con logo', { logo_url: 'https://cdn.example.com/logo.png' }),
      tienda('mala', 'Mala', { logo_url: 'javascript:alert(1)' }),
    ]);
    fixture.detectChanges();

    const tarjetas = html().querySelectorAll('a.tarjeta');
    expect(tarjetas[0].querySelector('img')?.getAttribute('src')).toBe('https://cdn.example.com/logo.png');
    expect(tarjetas[1].querySelector('img')).toBeNull();
    expect(tarjetas[1].querySelector('.marca__monograma')?.textContent?.trim()).toBe('MA');
  });

  it('si el logo no carga, muestra las siglas', () => {
    crear();
    pedidoTiendas(1).flush([tienda('rota', 'Rota', { logo_url: 'https://cdn.example.com/rota.png' })]);
    fixture.detectChanges();

    html().querySelector('img')?.dispatchEvent(new Event('error'));
    fixture.detectChanges();

    expect(html().querySelector('img')).toBeNull();
    expect(html().querySelector('a.tarjeta .marca__monograma')?.textContent?.trim()).toBe('RO');
  });

  it('el buscador espera 350 ms y pide con ?q=', () => {
    vi.useFakeTimers();
    crear();
    pedidoTiendas(1).flush(filas(2));
    fixture.detectChanges();

    const input = html().querySelector<HTMLInputElement>('input')!;
    input.value = 'bout';
    input.dispatchEvent(new Event('input'));

    vi.advanceTimersByTime(349);
    controller.expectNone((r) => r.url === URL_TIENDAS);

    vi.advanceTimersByTime(1);
    pedidoTiendas(1, 'bout').flush([tienda('andina', 'Boutique Andina')]);
    fixture.detectChanges();

    expect(html().querySelectorAll('a.tarjeta').length).toBe(1);
    pedidoPlanes().flush([]);
    controller.verify();
  });

  it('sin resultados muestra el mensaje de vacío', () => {
    crear();
    pedidoTiendas(1).flush([]);
    fixture.detectChanges();

    expect(html().textContent).toContain('No encontramos tiendas con ese nombre.');
    expect(html().querySelectorAll('a.tarjeta').length).toBe(0);
  });

  it('con error muestra el mensaje y Reintentar vuelve a pedir', () => {
    crear();
    pedidoTiendas(1).flush('boom', { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(html().textContent).toContain('No pudimos cargar las tiendas');
    const boton = Array.from(html().querySelectorAll('button')).find((b) => b.textContent?.includes('Reintentar'));
    expect(boton).toBeDefined();

    boton!.click();
    pedidoTiendas(1).flush([tienda('acme', 'Acme')]);
    fixture.detectChanges();

    expect(html().textContent).not.toContain('No pudimos cargar las tiendas');
    expect(html().querySelectorAll('a.tarjeta').length).toBe(1);
  });

  it('"Ver más" aparece si la página vino completa, pide la siguiente y se oculta con una página corta', () => {
    crear();
    pedidoTiendas(1).flush(filas(TAMANIO_PAGINA_TIENDAS));
    fixture.detectChanges();

    const verMas = () => Array.from(html().querySelectorAll('button')).find((b) => b.textContent?.includes('Ver más'));
    expect(verMas()).toBeDefined();

    verMas()!.click();
    pedidoTiendas(2).flush(filas(3, TAMANIO_PAGINA_TIENDAS));
    fixture.detectChanges();

    expect(html().querySelectorAll('a.tarjeta').length).toBe(TAMANIO_PAGINA_TIENDAS + 3);
    expect(verMas()).toBeUndefined();
    pedidoPlanes().flush([]);
    controller.verify();
  });

  it('sin tienda anterior no pide ni muestra "Volver a"', () => {
    crear();
    pedidoTiendas(1).flush([]);
    controller.expectNone((r) => r.url.endsWith('/tienda'));
    expect(html().textContent).not.toContain('Volver a');
  });

  it('muestra "Volver a <nombre>" arriba de la lista con la última tienda', () => {
    localStorage.setItem(CLAVE_ULTIMA_TIENDA, 'acme');
    crear();
    controller.expectOne(`${environment.apiUrl}/public/acme/tienda`).flush(tienda('acme', 'Acme Ropa'));
    pedidoTiendas(1).flush([tienda('andina', 'Boutique Andina')]);
    fixture.detectChanges();

    const volver = html().querySelector<HTMLAnchorElement>('.tarjeta--volver');
    expect(volver?.textContent).toContain('Volver a');
    expect(volver?.textContent).toContain('Acme Ropa');
    expect(volver?.getAttribute('href')).toBe('/t/acme');
    // Se agrega: la lista sigue completa.
    expect(html().querySelectorAll('a.tarjeta:not(.tarjeta--volver)').length).toBe(1);
  });

  it('si la última tienda ya no existe, no muestra "Volver a"', () => {
    localStorage.setItem(CLAVE_ULTIMA_TIENDA, 'vieja');
    crear();
    controller.expectOne(`${environment.apiUrl}/public/vieja/tienda`).flush('no', { status: 404, statusText: 'Not Found' });
    pedidoTiendas(1).flush([tienda('andina', 'Boutique Andina')]);
    fixture.detectChanges();

    expect(html().querySelector('.tarjeta--volver')).toBeNull();
  });

  describe('modo historia (escena 3D)', () => {
    function escena(): EscenaFalsa {
      return fixture.debugElement.query(By.directive(EscenaFalsa)).componentInstance as EscenaFalsa;
    }

    it('por omisión es el diseño clásico: sin historia ni escena', () => {
      crear();
      pedidoTiendas(1).flush([]);
      fixture.detectChanges();

      expect(html().querySelector('app-historia-tienda')).toBeNull();
      expect(html().querySelector('.home-hero')).not.toBeNull();
      expect(html().classList.contains('home--3d')).toBe(false);
      expect(html().querySelector('#tiendas')?.classList.contains('fs-zona-oscura')).toBe(false);
    });

    it('si la escena es posible muestra la historia en lugar del héroe, los servicios, los pasos y los planes clásicos', () => {
      crear(true);
      pedidoTiendas(1).flush([]);
      pedidoPlanes().flush([PLAN_BASICO, PLAN_PROFESIONAL]);
      fixture.detectChanges();

      expect(html().querySelector('app-historia-tienda')).not.toBeNull();
      expect(html().classList.contains('home--3d')).toBe(true);
      expect(html().querySelectorAll('section.paso').length).toBe(6);
      expect(html().querySelector('.home-hero')).toBeNull();
      expect(html().querySelector('.home-servicio')).toBeNull();
      expect(html().querySelector('.home-banda')).toBeNull();
      expect(html().querySelector('#servicios')).toBeNull();
      // Los planes llegan al comparativo de la historia (el clásico no se pinta).
      expect(html().querySelectorAll('.plan__nombre').length).toBe(2);
      expect(html().querySelectorAll('section.home-seccion').length).toBe(0);
    });

    it('mantiene la lista de tiendas, la CTA y el pie igual que en el modo clásico', () => {
      crear(true);
      pedidoTiendas(1).flush([tienda('acme', 'Acme'), tienda('andina', 'Boutique Andina')]);
      fixture.detectChanges();

      const lista = html().querySelector('#tiendas');
      expect(lista?.textContent).toContain('Visita una tienda');
      expect(lista?.querySelector('input[type="search"]')).not.toBeNull();
      expect(lista?.classList.contains('fs-zona-oscura')).toBe(true);
      expect(Array.from(html().querySelectorAll('a.tarjeta')).map((a) => a.getAttribute('href'))).toEqual([
        '/t/acme',
        '/t/andina',
      ]);
      expect(html().querySelector('.home-cta__enlace')?.getAttribute('href')).toBe(RUTA_ACCESO_PERSONAL);
      expect(html().querySelector('.home-pie')?.textContent).toContain('Plataforma para tiendas de ropa');
    });

    it('la calle recibe las tiendas con su acento sobre oscuro, y buscar en la lista no la cambia', () => {
      vi.useFakeTimers();
      crear(true);
      pedidoTiendas(1).flush([tienda('acme', 'Acme', { color_acento: '#9a3e1f' }), tienda('andina', 'Boutique Andina')]);
      fixture.detectChanges();

      const calle = escena().tiendas();
      expect(calle.map((t) => t.codigo)).toEqual(['acme', 'andina']);
      expect(calle[0].acento).toMatch(/^#[0-9a-f]{6}$/);
      expect(calle[0].acento).not.toBe('#9a3e1f'); // se aclaró para contrastar con el carbón
      expect(calle[1].acento).toBeNull();

      const entrada = html().querySelector<HTMLInputElement>('#tiendas input')!;
      entrada.value = 'bout';
      entrada.dispatchEvent(new Event('input'));
      vi.advanceTimersByTime(350);
      pedidoTiendas(1, 'bout').flush([tienda('andina', 'Boutique Andina')]);
      fixture.detectChanges();

      expect(html().querySelectorAll('a.tarjeta').length).toBe(1);
      expect(escena().tiendas().length).toBe(2);
    });

    it('un clic en un local de la calle abre la tienda', () => {
      crear(true);
      pedidoTiendas(1).flush([tienda('acme', 'Acme')]);
      const navegar = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);

      escena().tiendaElegida.emit('acme');

      expect(navegar).toHaveBeenCalledWith(['/t', 'acme']);
    });

    it('si la escena no puede crearse, vuelve al diseño clásico y conserva la lista', () => {
      crear(true);
      pedidoTiendas(1).flush([tienda('acme', 'Acme')]);
      fixture.detectChanges();
      expect(html().querySelector('app-historia-tienda')).not.toBeNull();

      escena().sinEscena.emit();
      fixture.detectChanges();

      expect(html().querySelector('app-historia-tienda')).toBeNull();
      expect(html().querySelector('.home-hero')).not.toBeNull();
      expect(html().classList.contains('home--3d')).toBe(false);
      expect(html().querySelectorAll('a.tarjeta').length).toBe(1);
    });

    it('si los planes no cargan, la historia lo dice y Reintentar los vuelve a pedir', () => {
      crear(true);
      pedidoTiendas(1).flush([]);
      pedidoPlanes().flush('boom', { status: 500, statusText: 'Server Error' });
      fixture.detectChanges();

      expect(html().querySelector('app-historia-tienda')?.textContent).toContain('No pudimos cargar los planes');
      const boton = Array.from(html().querySelectorAll('app-historia-tienda button')).find((b) =>
        b.textContent?.includes('Reintentar'),
      ) as HTMLButtonElement;
      boton.click();
      pedidoPlanes().flush([PLAN_BASICO]);
      fixture.detectChanges();

      expect(html().textContent).not.toContain('No pudimos cargar los planes');
      expect(html().querySelectorAll('.plan').length).toBe(1);
    });
  });
});
