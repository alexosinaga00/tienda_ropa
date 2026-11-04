import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { UsuarioYo } from '../../core/models/seguridad.models';
import { TiendaShellComponent } from './tienda-shell.component';
import { TiendaActualService } from './state/tienda-actual.service';

@Component({ template: '' })
class PaginaVacia {}

function usuario(empresaCodigo: string): UsuarioYo {
  return {
    id: 1,
    nombre: 'Ana',
    apellido: 'Pérez',
    email: 'ana@example.com',
    telefono: null,
    activo: true,
    roles: ['cliente'],
    permisos: [],
    empresa_id: 7,
    empresa_codigo: empresaCodigo,
  };
}

describe('TiendaShellComponent', () => {
  let http: HttpTestingController;

  function iniciarSesion(empresaCodigo: string): void {
    const auth = TestBed.inject(AuthService);
    auth.cargarUsuarioActual().subscribe();
    http.expectOne((peticion) => peticion.url.endsWith('/auth/yo')).flush(usuario(empresaCodigo));
  }

  function crear(): HTMLElement {
    const fixture = TestBed.createComponent(TiendaShellComponent);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      imports: [TiendaShellComponent],
      providers: [
        provideRouter([
          {
            path: 't/:codigo',
            children: [
              { path: '', component: PaginaVacia },
              { path: 'carrito', component: PaginaVacia },
              { path: 'checkout/pago', component: PaginaVacia },
            ],
          },
        ]),
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpTestingController);
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: null,
      color_acento: null,
    });
  });

  afterEach(() => localStorage.clear());

  it('muestra la marca de la tienda (nombre y monograma) y apunta a su portada', () => {
    const el = crear();
    const enlace = el.querySelector('a.cab__marca') as HTMLAnchorElement;
    const marca = enlace.querySelector('fs-marca') as HTMLElement;

    expect(marca.getAttribute('aria-label')).toBe('Acme');
    expect(marca.textContent).toContain('Acme');
    expect(marca.textContent).toContain('AC');
    expect(enlace.getAttribute('href')).toBe('/t/acme');
    expect(el.querySelector('footer.tienda-pie')?.textContent).toContain('Con la tecnología de FashionStore');
  });

  it('con sesión de otra empresa muestra "Iniciar sesión"', () => {
    iniciarSesion('otra');
    const el = crear();
    const texto = el.textContent ?? '';

    expect(texto).toContain('Iniciar sesión');
    expect(texto).not.toContain('Mi cuenta');
    expect(texto).not.toContain('Salir');
    const login = Array.from(el.querySelectorAll('a')).find((a) => a.textContent?.includes('Iniciar sesión'));
    expect(login?.getAttribute('href')).toBe('/t/acme/login');
    const registro = Array.from(el.querySelectorAll('a')).find((a) => a.textContent?.includes('Registrarse'));
    expect(registro?.getAttribute('href')).toBe('/t/acme/registro');
  });

  it('con sesión de la misma empresa muestra "Mi cuenta" (a Mis compras) y "Salir"', () => {
    iniciarSesion('acme');
    const el = crear();
    const texto = el.textContent ?? '';

    expect(texto).toContain('Mi cuenta');
    expect(texto).toContain('Salir');
    expect(texto).not.toContain('Iniciar sesión');
    const cuenta = Array.from(el.querySelectorAll('a')).find((a) => a.textContent?.includes('Mi cuenta'));
    expect(cuenta?.getAttribute('href')).toBe('/t/acme/mis-compras');
    // El efecto del carrito pide el carrito de esta tienda; no hace falta responderlo.
    http.match((peticion) => peticion.url.endsWith('/carrito'));
  });

  it('muestra el logo si hay logo_url http(s) y vuelve al monograma si falla', () => {
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: 'https://cdn.example.com/acme.png',
      color_acento: null,
    });
    const fixture = TestBed.createComponent(TiendaShellComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;

    const img = el.querySelector('a.cab__marca img') as HTMLImageElement;
    expect(img.getAttribute('src')).toBe('https://cdn.example.com/acme.png');
    expect(img.getAttribute('alt')).toBe('Acme');

    img.dispatchEvent(new Event('error'));
    fixture.detectChanges();

    expect(el.querySelector('a.cab__marca img')).toBeNull();
    expect(el.querySelector('a.cab__marca fs-marca')?.textContent).toContain('Acme');
  });

  it('un logo que no es http(s) no se usa: queda el monograma', () => {
    TestBed.inject(TiendaActualService).fijar('acme', 'lista', {
      codigo: 'acme',
      nombre: 'Acme',
      logo_url: 'javascript:alert(1)',
      color_acento: null,
    });
    const el = crear();

    expect(el.querySelector('a.cab__marca img')).toBeNull();
    expect(el.querySelector('a.cab__marca fs-marca')?.textContent).toContain('AC');
  });

  describe('cabecera según la pantalla', () => {
    it('en la portada es oscura y ofrece la búsqueda', async () => {
      await TestBed.inject(Router).navigateByUrl('/t/acme');
      const el = crear();

      expect(el.querySelector('header.cab')?.classList).toContain('fs-zona-oscura');
      expect(el.querySelector('fs-marca')?.classList).toContain('marca--oscuro');
      expect(el.querySelector('button[aria-label="Buscar prendas"]')).not.toBeNull();
      expect(el.querySelector('.cab__enlace--activo')?.textContent).toContain('Inicio');
    });

    it('los tres iconos dicen qué son al pasar el cursor (buscar, reserva y carrito)', async () => {
      await TestBed.inject(Router).navigateByUrl('/t/acme');
      const el = crear();

      expect(el.querySelector('button[aria-label="Buscar prendas"]')?.getAttribute('title')).toBe('Buscar prendas');
      expect(el.querySelector('a[aria-label="Ver reserva"]')?.getAttribute('title')).toContain('Mi reserva');
      expect(el.querySelector('a[aria-label="Ver reserva"]')?.getAttribute('title')).toContain('probártelas');
      expect(el.querySelector('a[aria-label="Ver carrito"]')?.getAttribute('title')).toBe('Mi carrito de compra');
    });

    it('en las demás páginas es clara y sin búsqueda', async () => {
      await TestBed.inject(Router).navigateByUrl('/t/acme/carrito');
      const el = crear();

      expect(el.querySelector('header.cab')?.classList).not.toContain('fs-zona-oscura');
      expect(el.querySelector('fs-marca')?.classList).toContain('marca--claro');
      expect(el.querySelector('button[aria-label="Buscar prendas"]')).toBeNull();
      expect(el.querySelector('a[aria-label="Ver carrito"]')).not.toBeNull();
    });

    it('cambia al navegar entre la portada y otra página', async () => {
      const router = TestBed.inject(Router);
      await router.navigateByUrl('/t/acme');
      const fixture = TestBed.createComponent(TiendaShellComponent);
      fixture.detectChanges();
      const el = fixture.nativeElement as HTMLElement;
      expect(el.querySelector('header.cab')?.classList).toContain('fs-zona-oscura');

      await router.navigateByUrl('/t/acme/carrito');
      fixture.detectChanges();
      expect(el.querySelector('header.cab')?.classList).not.toContain('fs-zona-oscura');
    });

    it('en el checkout se reduce a la marca y "Compra segura"', async () => {
      await TestBed.inject(Router).navigateByUrl('/t/acme/checkout/pago');
      const el = crear();

      expect(el.querySelector('.cab__seguro')?.textContent).toContain('Compra segura');
      expect(el.querySelector('a[aria-label="Ver carrito"]')).toBeNull();
      expect(el.querySelector('nav')).toBeNull();
    });
  });

  it('Escape cierra el menú abierto y devuelve el foco al botón', () => {
    const fixture = TestBed.createComponent(TiendaShellComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    document.body.append(el);
    const boton = el.querySelector('button.cab__menu') as HTMLButtonElement;
    const panel = el.querySelector('#tienda-menu') as HTMLElement;

    boton.click();
    fixture.detectChanges();
    expect(panel.classList).toContain('abierto');

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    fixture.detectChanges();

    expect(panel.classList).not.toContain('abierto');
    expect(document.activeElement).toBe(boton);
    el.remove();
  });

  it('Escape con el menú cerrado no mueve el foco', () => {
    const fixture = TestBed.createComponent(TiendaShellComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    document.body.append(el);

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));

    expect(document.activeElement).not.toBe(el.querySelector('button.cab__menu'));
    el.remove();
  });

  it('el botón de menú abre y cierra el panel de enlaces', () => {
    const fixture = TestBed.createComponent(TiendaShellComponent);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const boton = el.querySelector('button.cab__menu') as HTMLButtonElement;
    const panel = el.querySelector('#tienda-menu') as HTMLElement;

    expect(boton.getAttribute('aria-expanded')).toBe('false');
    expect(panel.classList).not.toContain('abierto');

    boton.click();
    fixture.detectChanges();
    expect(boton.getAttribute('aria-expanded')).toBe('true');
    expect(boton.getAttribute('aria-label')).toBe('Cerrar menú');
    expect(panel.classList).toContain('abierto');

    boton.click();
    fixture.detectChanges();
    expect(panel.classList).not.toContain('abierto');
  });
});
