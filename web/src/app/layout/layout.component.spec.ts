import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { MessageService } from 'primeng/api';
import { environment } from '../../environments/environment';
import { AuthService } from '../core/auth.service';
import { MiSuscripcion } from '../core/models/plan.models';
import { AlmacenOfflineService } from '../core/offline/almacen-offline.service';
import type { OperacionOffline } from '../core/offline/offline.models';
import { PlanService } from '../core/plan.service';
import { ITEMS_INICIO, ItemMenu, LayoutComponent } from './layout.component';

const API = environment.apiUrl;

@Component({ standalone: true, template: '' })
class PaginaVaciaComponent {}

/** jsdom no trae matchMedia: se simula una pantalla angosta (cajón) o ancha. */
function simularAncho(angosta: boolean): void {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (consulta: string) => ({
      matches: angosta,
      media: consulta,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }),
  });
}

/** Todos los permisos que el menú pregunta (un administrador de empresa los tiene). */
const PERMISOS_ADMIN = [
  'reportes.ver',
  'usuarios.gestionar',
  'roles.gestionar',
  'organizacion.gestionar',
  'catalogo.gestionar',
  'ventas.presencial',
  'ventas.gestionar',
  'reservas.gestionar_sucursal',
  'inventario.ver',
  'abastecimiento.gestionar',
  'entregas.gestionar',
  'probador.gestionar',
  'empresa.gestionar',
  'sincronizacion.supervisar',
  'bitacora.ver',
  'copias.gestionar',
];

// El orden del menú de antes. Esta lista NO se reordena: los ítems nuevos van al final de su lista.
const INICIO_ESPERADO = ['Dashboard', 'Reportes', 'Reportes con IA', 'Analítica'];
const GRUPOS_ESPERADOS: Record<string, string[]> = {
  Organización: ['Usuarios', 'Roles', 'Empleados', 'Ciudades', 'Sucursales', 'Auditoría', 'Copias de seguridad'],
  Catálogo: ['Productos', 'Categorías', 'Tallas', 'Colores', 'Temporadas', 'Colecciones'],
  Ventas: ['Caja', 'Promociones', 'Reservas', 'Catálogo local', 'Pendientes de envío', 'Sincronización'],
};
const FIN_ESPERADO_PREVIO = ['Inventario', 'Proveedores', 'Envíos', 'Zonas de envío', 'Assets del probador'];

function suscripcion(funcionalidades: string[], plan = 'Básico'): MiSuscripcion {
  return {
    plan_codigo: plan.toLowerCase(),
    plan_nombre: plan,
    estado: 'activa',
    fecha_inicio: '2026-01-01',
    fecha_vencimiento: '2099-01-01',
    max_sucursales: 2,
    sucursales_activas: 1,
    funcionalidades,
  };
}

describe('LayoutComponent', () => {
  let http: HttpTestingController;
  let auth: AuthService;
  let plan: PlanService;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      imports: [LayoutComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting(), MessageService],
    });
    http = TestBed.inject(HttpTestingController);
    auth = TestBed.inject(AuthService);
    plan = TestBed.inject(PlanService);
  });

  afterEach(() => {
    localStorage.clear();
    http.match(() => true);
    delete (window as { matchMedia?: unknown }).matchMedia;
  });

  function iniciarSesion(roles: string[], permisos: string[], empresaId: number | null): void {
    auth.guardarTokens({ access_token: 'a', refresh_token: 'r', token_type: 'bearer' });
    auth.cargarUsuarioActual().subscribe();
    http.expectOne(`${API}/auth/yo`).flush({
      id: 1,
      nombre: 'Ana',
      apellido: 'Paz',
      email: 'a@b.com',
      telefono: null,
      activo: true,
      roles,
      permisos,
      empresa_id: empresaId,
    });
  }

  function crear() {
    const fixture = TestBed.createComponent(LayoutComponent);
    fixture.detectChanges();
    const comp = fixture.componentInstance as any;
    return { fixture, comp, el: fixture.nativeElement as HTMLElement };
  }

  const etiquetas = (items: { etiqueta: string }[]) => items.map((i) => i.etiqueta);

  describe('orden del menú de una empresa', () => {
    it('los ítems existentes mantienen su orden y los nuevos van al final de su lista', () => {
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      const { fixture, comp } = crear();

      expect(etiquetas(comp.itemsInicio())).toEqual(INICIO_ESPERADO);

      const grupos = Object.fromEntries(
        (comp.gruposMenu() as { etiqueta: string; items: { etiqueta: string }[] }[]).map((g) => [
          g.etiqueta,
          etiquetas(g.items),
        ]),
      );
      expect(grupos).toEqual(GRUPOS_ESPERADOS);
      expect(Object.keys(grupos)).toEqual(['Organización', 'Catálogo', 'Ventas']);

      expect(etiquetas(comp.itemsFin())).toEqual([...FIN_ESPERADO_PREVIO, 'Mi empresa']);
      fixture.destroy();
    });

    it('"Mi empresa" solo aparece con el permiso empresa.gestionar', () => {
      iniciarSesion(['cajero'], ['ventas.presencial', 'inventario.ver'], 7);
      const { fixture, comp } = crear();

      expect(etiquetas(comp.itemsFin())).toEqual(['Inventario']);
      fixture.destroy();
    });

    it('un empleado sin permisos de gestión solo ve Dashboard', () => {
      iniciarSesion(['cajero'], [], 7);
      const { fixture, comp } = crear();

      expect(etiquetas(comp.itemsInicio())).toEqual(['Dashboard']);
      expect(comp.gruposMenu()).toEqual([]);
      fixture.destroy();
    });

    it('el personal de una empresa nunca ve el grupo Plataforma', () => {
      iniciarSesion(['administrador'], [...PERMISOS_ADMIN, 'plataforma.gestionar'], 7);
      const { fixture, comp } = crear();

      expect(etiquetas(comp.gruposMenu())).not.toContain('Plataforma');
      fixture.destroy();
    });
  });

  describe('funcionalidades que el plan no incluye', () => {
    // "Reportes con IA" y "Analítica" (E17) y "Sincronización" (E16 parte 2) son ítems reales del menú.

    it('con plan Básico salen deshabilitados, en su lugar, con candado y enlace a Mi empresa', () => {
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      plan.suscripcion.set(suscripcion(['operacion_offline']));
      const { fixture, el } = crear();
      fixture.detectChanges();

      const enlaces = Array.from(el.querySelectorAll('nav a.layout__enlace'));
      const textos = enlaces.map((a) => (a.textContent ?? '').trim());
      // Mismo lugar y orden: justo después de "Reportes".
      const posicion = textos.indexOf('Reportes');
      expect(textos.slice(posicion, posicion + 3)).toEqual(['Reportes', 'Reportes con IA', 'Analítica']);

      const ia = enlaces.find((a) => (a.textContent ?? '').includes('Reportes con IA')) as HTMLElement;
      expect(ia.classList).toContain('layout__enlace--deshabilitado');
      expect(ia.getAttribute('aria-disabled')).toBe('true');
      expect(ia.getAttribute('href')).toBe('/mi-empresa?ver=funcionalidades');
      expect(ia.querySelector('.layout__candado')).not.toBeNull();
      expect(ia.getAttribute('title')).toBe('Tu plan Básico no incluye esto. Más info en Mi empresa.');

      const analitica = enlaces.find((a) => (a.textContent ?? '').includes('Analítica')) as HTMLElement;
      expect(analitica.classList).toContain('layout__enlace--deshabilitado');
      expect(analitica.getAttribute('href')).toBe('/mi-empresa?ver=funcionalidades');
      expect(analitica.querySelector('.layout__candado')).not.toBeNull();

      // "Reportes" (convencional) no depende del plan.
      const reportes = enlaces.find((a) => (a.textContent ?? '').trim() === 'Reportes') as HTMLElement;
      expect(reportes.classList).not.toContain('layout__enlace--deshabilitado');
      expect(reportes.getAttribute('href')).toBe('/reportes');

      // Lo que el plan sí incluye es un enlace normal.
      const offline = enlaces.find((a) => (a.textContent ?? '').includes('Sincronización')) as HTMLElement;
      expect(offline.classList).not.toContain('layout__enlace--deshabilitado');
      expect(offline.getAttribute('href')).toBe('/sincronizacion');
      fixture.destroy();
    });

    it('con plan Profesional los ítems son normales', () => {
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      plan.suscripcion.set(suscripcion(['reportes_ia', 'analitica_ml', 'operacion_offline'], 'Profesional'));
      const { fixture, el } = crear();

      const enlaces = Array.from(el.querySelectorAll('nav a.layout__enlace'));
      const ia = enlaces.find((a) => (a.textContent ?? '').includes('Reportes con IA')) as HTMLElement;
      expect(ia.classList).not.toContain('layout__enlace--deshabilitado');
      expect(ia.getAttribute('href')).toBe('/reportes-ia');
      expect(ia.querySelector('.layout__candado')).toBeNull();
      const analitica = enlaces.find((a) => (a.textContent ?? '').includes('Analítica')) as HTMLElement;
      expect(analitica.classList).not.toContain('layout__enlace--deshabilitado');
      expect(analitica.getAttribute('href')).toBe('/analitica');
      fixture.destroy();
    });

    it('un plan con reportes con IA pero sin analítica deshabilita solo la analítica', () => {
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      plan.suscripcion.set(suscripcion(['reportes_ia'], 'Estándar'));
      const { fixture, el } = crear();

      const enlaces = Array.from(el.querySelectorAll('nav a.layout__enlace'));
      const ia = enlaces.find((a) => (a.textContent ?? '').includes('Reportes con IA')) as HTMLElement;
      const analitica = enlaces.find((a) => (a.textContent ?? '').includes('Analítica')) as HTMLElement;
      expect(ia.classList).not.toContain('layout__enlace--deshabilitado');
      expect(analitica.classList).toContain('layout__enlace--deshabilitado');
      fixture.destroy();
    });

    it('"Copias de seguridad" (E22) va al final de Organización: gris con candado sin la función, normal con ella', () => {
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      plan.suscripcion.set(suscripcion(['reportes_ia', 'analitica_ml', 'operacion_offline'], 'Estándar'));
      const { fixture, el } = crear();

      const enlaces = Array.from(el.querySelectorAll('nav a.layout__enlace'));
      const copias = enlaces.find((a) => (a.textContent ?? '').includes('Copias de seguridad')) as HTMLElement;
      expect(copias.classList).toContain('layout__enlace--deshabilitado');
      expect(copias.getAttribute('aria-disabled')).toBe('true');
      expect(copias.getAttribute('href')).toBe('/mi-empresa?ver=funcionalidades');
      expect(copias.querySelector('.layout__candado')).not.toBeNull();
      // El resto del plan sigue normal.
      const analitica = enlaces.find((a) => (a.textContent ?? '').includes('Analítica')) as HTMLElement;
      expect(analitica.classList).not.toContain('layout__enlace--deshabilitado');

      plan.suscripcion.set(suscripcion(['copias_seguridad'], 'Profesional'));
      fixture.detectChanges();
      const habilitada = Array.from(el.querySelectorAll('nav a.layout__enlace')).find((a) =>
        (a.textContent ?? '').includes('Copias de seguridad'),
      ) as HTMLElement;
      expect(habilitada.classList).not.toContain('layout__enlace--deshabilitado');
      expect(habilitada.getAttribute('href')).toBe('/copias-seguridad');
      expect(habilitada.querySelector('.layout__candado')).toBeNull();
      fixture.destroy();
    });

    it('"Copias de seguridad" solo la ve quien tiene copias.gestionar', () => {
      iniciarSesion(['encargado'], PERMISOS_ADMIN.filter((p) => p !== 'copias.gestionar'), 7);
      const { fixture, el } = crear();

      const textos = Array.from(el.querySelectorAll('nav a.layout__enlace')).map((a) => (a.textContent ?? '').trim());
      expect(textos).not.toContain('Copias de seguridad');
      fixture.destroy();
    });

    it('si no se conoce el plan (empleado sin acceso a Mi empresa) no se deshabilita nada', () => {
      iniciarSesion(['cajero'], ['inventario.ver'], 7);
      const { fixture, comp } = crear();

      expect(comp.itemsFin().every((i: { deshabilitado: boolean }) => !i.deshabilitado)).toBe(true);
      fixture.destroy();
    });
  });

  describe('superadministrador', () => {
    it('solo ve el grupo Plataforma, con Empresas, Planes y Suscripciones', () => {
      iniciarSesion(['superadministrador'], ['plataforma.gestionar'], null);
      const { fixture, comp } = crear();

      expect(comp.itemsInicio()).toEqual([]);
      expect(comp.itemsFin()).toEqual([]);
      expect(etiquetas(comp.gruposMenu())).toEqual(['Plataforma']);
      expect(etiquetas(comp.gruposMenu()[0].items)).toEqual(['Empresas', 'Planes', 'Suscripciones', 'Auditoría']);
      expect(comp.gruposMenu()[0].items.map((i: ItemMenu) => i.ruta)).toEqual([
        '/plataforma/empresas',
        '/plataforma/planes',
        '/plataforma/suscripciones',
        '/plataforma/auditoria',
      ]);
      fixture.destroy();
    });

    it('no pide notificaciones, no las consulta cada 20 s y no pide el plan', () => {
      vi.useFakeTimers();
      try {
        iniciarSesion(['superadministrador'], ['plataforma.gestionar', 'empresa.gestionar'], null);
        const { fixture } = crear();
        vi.advanceTimersByTime(60_000);

        http.expectNone((req) => req.url.includes('/notificaciones'));
        http.expectNone((req) => req.url.includes('/mi-empresa'));
        fixture.destroy();
      } finally {
        vi.useRealTimers();
      }
    });

    it('no tiene campana de notificaciones ni franja de suscripción', () => {
      iniciarSesion(['superadministrador'], ['plataforma.gestionar'], null);
      plan.marcarBloqueada('vencida');
      const { fixture, el } = crear();
      fixture.detectChanges();

      expect(el.querySelector('.layout__campana')).toBeNull();
      expect(el.querySelector('app-aviso-suscripcion')).toBeNull();
      fixture.destroy();
    });
  });

  describe('menú agrupado como el canvas', () => {
    const seccionesVista = (comp: any) =>
      Object.fromEntries(
        (comp.secciones() as { etiqueta: string; items: { etiqueta: string }[] }[]).map((s) => [
          s.etiqueta,
          etiquetas(s.items),
        ]),
      );

    it('un administrador ve las mismas opciones repartidas en General, Catálogo, Comercial, Análisis y Organización', () => {
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      const { fixture, comp } = crear();

      expect(seccionesVista(comp)).toEqual({
        General: ['Dashboard', 'Caja'],
        Catálogo: [
          'Productos',
          'Inventario',
          'Categorías',
          'Tallas',
          'Colores',
          'Temporadas',
          'Colecciones',
          'Proveedores',
          'Assets del probador',
        ],
        Comercial: [
          'Reservas',
          'Envíos',
          'Zonas de envío',
          'Promociones',
          'Catálogo local',
          'Pendientes de envío',
          'Sincronización',
        ],
        Análisis: ['Reportes', 'Reportes con IA', 'Analítica'],
        Organización: [
          'Sucursales',
          'Ciudades',
          'Empleados',
          'Usuarios',
          'Roles',
          'Mi empresa',
          'Auditoría',
          'Copias de seguridad',
        ],
      });
      fixture.destroy();
    });

    it('cada opción solo aparece si la persona tiene su permiso (no se pierde ni se agrega ninguna)', () => {
      iniciarSesion(['cajero'], ['ventas.presencial', 'inventario.ver'], 7);
      const { fixture, comp } = crear();

      expect(seccionesVista(comp)).toEqual({
        General: ['Dashboard', 'Caja'],
        Catálogo: ['Inventario'],
        Comercial: ['Catálogo local', 'Pendientes de envío'],
      });
      fixture.destroy();
    });

    describe('"Catálogo local" (necesita alguno de dos permisos)', () => {
      const comercial = (comp: any): string[] => seccionesVista(comp)['Comercial'] ?? [];

      it('lo ve quien solo tiene ventas.presencial', () => {
        iniciarSesion(['cajero'], ['ventas.presencial'], 7);
        const { fixture, comp } = crear();

        expect(comercial(comp)).toEqual(['Catálogo local', 'Pendientes de envío']);
        fixture.destroy();
      });

      it('lo ve quien solo tiene reservas.gestionar_sucursal (y también ve Reservas)', () => {
        iniciarSesion(['encargado'], ['reservas.gestionar_sucursal'], 7);
        const { fixture, comp } = crear();

        expect(comercial(comp)).toEqual(['Reservas', 'Catálogo local', 'Pendientes de envío']);
        fixture.destroy();
      });

      it('no lo ve quien tiene otros permisos pero ninguno de los dos', () => {
        iniciarSesion(['encargado'], ['inventario.ver', 'reportes.ver', 'ventas.gestionar'], 7);
        const { fixture, comp } = crear();

        expect(comercial(comp)).not.toContain('Catálogo local');
        expect(comercial(comp)).not.toContain('Pendientes de envío');
        fixture.destroy();
      });

      it('con un plan sin operación sin conexión sigue en su lugar, deshabilitado y con candado', () => {
        iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
        plan.suscripcion.set(suscripcion([]));
        const { fixture, el } = crear();
        fixture.detectChanges();

        const enlace = Array.from(el.querySelectorAll('nav a.layout__enlace')).find((a) =>
          (a.textContent ?? '').includes('Catálogo local'),
        ) as HTMLElement;
        expect(enlace.classList).toContain('layout__enlace--deshabilitado');
        expect(enlace.querySelector('.layout__candado')).not.toBeNull();
        fixture.destroy();
      });

      it('con un plan que lo incluye es un enlace normal a /catalogo-local', () => {
        iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
        plan.suscripcion.set(suscripcion(['operacion_offline'], 'Profesional'));
        const { fixture, el } = crear();
        fixture.detectChanges();

        const enlace = Array.from(el.querySelectorAll('nav a.layout__enlace')).find((a) =>
          (a.textContent ?? '').includes('Catálogo local'),
        ) as HTMLElement;
        expect(enlace.classList).not.toContain('layout__enlace--deshabilitado');
        expect(enlace.getAttribute('href')).toBe('/catalogo-local');
        fixture.destroy();
      });
    });

    describe('"Sincronización" (sincronizacion.supervisar y plan con operación sin conexión)', () => {
      const comercial = (comp: any): string[] => seccionesVista(comp)['Comercial'] ?? [];
      const enlaceSincronizacion = (el: HTMLElement) =>
        Array.from(el.querySelectorAll('nav a.layout__enlace')).find((a) =>
          (a.textContent ?? '').includes('Sincronización'),
        ) as HTMLElement | undefined;

      it('va al final de Comercial para quien supervisa', () => {
        iniciarSesion(['encargado'], ['sincronizacion.supervisar'], 7);
        const { fixture, comp } = crear();

        expect(comercial(comp)).toEqual(['Sincronización']);
        fixture.destroy();
      });

      it('no la ve quien tiene otros permisos de venta pero no sincronizacion.supervisar', () => {
        iniciarSesion(['cajero'], ['ventas.presencial', 'sincronizacion.operar', 'sincronizacion.resolver'], 7);
        const { fixture, comp } = crear();

        expect(comercial(comp)).not.toContain('Sincronización');
        fixture.destroy();
      });

      it('con un plan sin operación sin conexión queda en su lugar, deshabilitada y con candado', () => {
        iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
        plan.suscripcion.set(suscripcion([]));
        const { fixture, el } = crear();
        fixture.detectChanges();

        const enlace = enlaceSincronizacion(el)!;
        expect(enlace.classList).toContain('layout__enlace--deshabilitado');
        expect(enlace.querySelector('.layout__candado')).not.toBeNull();
        fixture.destroy();
      });

      it('con un plan que la incluye es un enlace normal a /sincronizacion', () => {
        iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
        plan.suscripcion.set(suscripcion(['operacion_offline'], 'Profesional'));
        const { fixture, el } = crear();
        fixture.detectChanges();

        const enlace = enlaceSincronizacion(el)!;
        expect(enlace.classList).not.toContain('layout__enlace--deshabilitado');
        expect(enlace.getAttribute('href')).toBe('/sincronizacion');
        fixture.destroy();
      });
    });

    it('Análisis y Plataforma también se pliegan y arrancan cerradas', () => {
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      const { fixture, comp, el } = crear();

      expect(comp.estaAbierto('analisis')).toBe(false);
      expect((el.querySelector('#menu-seccion-analisis') as HTMLElement).hasAttribute('hidden')).toBe(true);

      const rotulo = Array.from(el.querySelectorAll('button.layout__rotulo--boton')).find((b) =>
        (b.textContent ?? '').includes('Análisis'),
      ) as HTMLButtonElement;
      rotulo.click();
      fixture.detectChanges();

      expect(comp.estaAbierto('analisis')).toBe(true);
      expect((el.querySelector('#menu-seccion-analisis') as HTMLElement).hasAttribute('hidden')).toBe(false);
      fixture.destroy();
    });

    it('Analítica solo se ofrece con alcance global: un encargado con reportes.ver no la ve', () => {
      iniciarSesion(['encargado_sucursal'], ['reportes.ver', 'inventario.ver'], 7);
      const { fixture, comp } = crear();

      const etiquetas = (comp.itemsInicio() as ItemMenu[]).map((i) => i.etiqueta);
      expect(etiquetas).toContain('Reportes');
      expect(etiquetas).toContain('Reportes con IA');
      expect(etiquetas).not.toContain('Analítica');
      fixture.destroy();
    });

    it('las secciones plegables arrancan cerradas y se abren con su rótulo; Dashboard y Caja siempre están a la vista', () => {
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      const { fixture, comp, el } = crear();

      expect(comp.estaAbierto('general')).toBe(true);
      expect(comp.estaAbierto('catalogo')).toBe(false);
      const catalogo = el.querySelector('#menu-seccion-catalogo') as HTMLElement;
      expect(catalogo.hasAttribute('hidden')).toBe(true);

      const rotulo = el.querySelector('button.layout__rotulo--boton') as HTMLButtonElement;
      expect(rotulo.textContent).toContain('Catálogo');
      rotulo.click();
      fixture.detectChanges();

      expect(comp.estaAbierto('catalogo')).toBe(true);
      expect(catalogo.hasAttribute('hidden')).toBe(false);
      expect(rotulo.getAttribute('aria-expanded')).toBe('true');
      fixture.destroy();
    });

    it('el pie muestra a la persona y su rol, y la marca lleva el nombre de la empresa', () => {
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      const { fixture, el } = crear();

      expect(el.querySelector('.layout__usuario-nombre')?.textContent).toContain('Ana Paz');
      expect(el.querySelector('.layout__usuario-rol')?.textContent?.trim()).toBe('Administrador');
      expect(el.querySelector('fs-marca')).not.toBeNull();
      fixture.destroy();
    });

    it('en pantallas angostas el botón de la barra abre y cierra el menú', () => {
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      const { fixture, el } = crear();
      const raiz = el.querySelector('.layout') as HTMLElement;
      const boton = el.querySelector('.layout__hamburguesa') as HTMLButtonElement;

      expect(boton.getAttribute('aria-label')).toBe('Abrir el menú');
      boton.click();
      fixture.detectChanges();
      expect(raiz.classList).toContain('layout--menu-abierto');
      expect(boton.getAttribute('aria-expanded')).toBe('true');

      (el.querySelector('.layout__fondo') as HTMLElement).click();
      fixture.detectChanges();
      expect(raiz.classList).not.toContain('layout--menu-abierto');
      fixture.destroy();
    });

    it('el superadministrador ve solo Plataforma, con "Modo plataforma" bajo la marca', () => {
      iniciarSesion(['superadministrador'], ['plataforma.gestionar'], null);
      const { fixture, comp, el } = crear();

      expect(seccionesVista(comp)).toEqual({ Plataforma: ['Empresas', 'Planes', 'Suscripciones', 'Auditoría'] });
      expect(el.querySelector('.layout__marca-sub')?.textContent).toContain('Modo plataforma');
      fixture.destroy();
    });
  });

  describe('Auditoría en el menú (bitácora)', () => {
    const enlacesDelMenu = (el: HTMLElement) =>
      Array.from(el.querySelectorAll('nav a.layout__enlace')).map((a) => ({
        texto: (a.textContent ?? '').trim(),
        href: a.getAttribute('href'),
      }));

    it('el administrador (bitacora.ver) la ve en Organización, enlazada a /auditoria (solo "Copias de seguridad" va después)', () => {
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      const { fixture, comp, el } = crear();

      const organizacion = (comp.secciones() as { id: string; items: { etiqueta: string; ruta: string }[] }[]).find(
        (s) => s.id === 'organizacion',
      )!;
      expect(organizacion.items.at(-2)).toMatchObject({ etiqueta: 'Auditoría', ruta: '/auditoria' });
      expect(organizacion.items.at(-1)).toMatchObject({ etiqueta: 'Copias de seguridad', ruta: '/copias-seguridad' });
      expect(enlacesDelMenu(el)).toContainEqual({ texto: 'Auditoría', href: '/auditoria' });
      fixture.destroy();
    });

    it('el cajero no la ve', () => {
      iniciarSesion(['cajero'], ['ventas.presencial', 'inventario.ver'], 7);
      const { fixture, el } = crear();

      expect(enlacesDelMenu(el).map((e) => e.texto)).not.toContain('Auditoría');
      fixture.destroy();
    });

    it('el encargado (sin bitacora.ver) no la ve aunque tenga otros permisos de gestión', () => {
      iniciarSesion(['encargado'], ['reportes.ver', 'inventario.ver', 'reservas.gestionar_sucursal', 'organizacion.gestionar'], 7);
      const { fixture, el } = crear();

      expect(enlacesDelMenu(el).map((e) => e.texto)).not.toContain('Auditoría');
      fixture.destroy();
    });

    it('un administrador sin el permiso bitacora.ver no la ve', () => {
      iniciarSesion(['administrador'], PERMISOS_ADMIN.filter((p) => p !== 'bitacora.ver'), 7);
      const { fixture, el } = crear();

      expect(enlacesDelMenu(el).map((e) => e.texto)).not.toContain('Auditoría');
      fixture.destroy();
    });

    it('el superadministrador la ve en Plataforma, enlazada a /plataforma/auditoria, y solo esa', () => {
      iniciarSesion(['superadministrador'], ['plataforma.gestionar', 'bitacora.ver'], null);
      const { fixture, el } = crear();

      const auditorias = enlacesDelMenu(el).filter((e) => e.texto === 'Auditoría');
      expect(auditorias).toEqual([{ texto: 'Auditoría', href: '/plataforma/auditoria' }]);
      fixture.destroy();
    });

    it('un administrador de empresa nunca ve la entrada de Plataforma (/plataforma/auditoria)', () => {
      iniciarSesion(['administrador'], [...PERMISOS_ADMIN, 'plataforma.gestionar'], 7);
      const { fixture, el } = crear();

      expect(enlacesDelMenu(el).map((e) => e.href)).not.toContain('/plataforma/auditoria');
      fixture.destroy();
    });
  });

  describe('cajón del menú en pantallas angostas', () => {
    const pulsarEscape = () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));

    it('al abrir: el cajón es un diálogo modal, el resto de la página queda inert y el foco va a la primera opción', () => {
      simularAncho(true);
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      const { fixture, el } = crear();
      const aside = el.querySelector('aside') as HTMLElement;
      const contenido = el.querySelector('.layout__contenido') as HTMLElement;

      expect(aside.getAttribute('role')).toBeNull();
      expect(contenido.hasAttribute('inert')).toBe(false);

      (el.querySelector('.layout__hamburguesa') as HTMLButtonElement).click();
      fixture.detectChanges();

      expect(aside.getAttribute('role')).toBe('dialog');
      expect(aside.getAttribute('aria-modal')).toBe('true');
      expect(contenido.hasAttribute('inert')).toBe(true);
      expect(document.activeElement).toBe(aside.querySelector('a.layout__enlace'));
      expect(document.activeElement?.textContent).toContain('Dashboard');
      fixture.destroy();
    });

    it('Escape lo cierra y devuelve el foco a la hamburguesa', () => {
      simularAncho(true);
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      const { fixture, el } = crear();
      const boton = el.querySelector('.layout__hamburguesa') as HTMLButtonElement;
      boton.click();
      fixture.detectChanges();

      pulsarEscape();
      fixture.detectChanges();

      expect(el.querySelector('.layout')?.classList).not.toContain('layout--menu-abierto');
      expect(el.querySelector('.layout__contenido')?.hasAttribute('inert')).toBe(false);
      expect(document.activeElement).toBe(boton);
      fixture.destroy();
    });

    it('el fondo es un botón real que cierra el cajón', () => {
      simularAncho(true);
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      const { fixture, el } = crear();
      (el.querySelector('.layout__hamburguesa') as HTMLButtonElement).click();
      fixture.detectChanges();

      const fondo = el.querySelector('.layout__fondo') as HTMLButtonElement;
      expect(fondo.tagName).toBe('BUTTON');
      expect(fondo.getAttribute('aria-label')).toBe('Cerrar el menú');
      fondo.click();
      fixture.detectChanges();

      expect(el.querySelector('.layout')?.classList).not.toContain('layout--menu-abierto');
      fixture.destroy();
    });

    it('se cierra al navegar a otra opción', async () => {
      simularAncho(true);
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      TestBed.inject(Router).resetConfig([{ path: '**', component: PaginaVaciaComponent }]);
      const { fixture, el } = crear();
      (el.querySelector('.layout__hamburguesa') as HTMLButtonElement).click();
      fixture.detectChanges();
      expect(el.querySelector('.layout')?.classList).toContain('layout--menu-abierto');

      await TestBed.inject(Router).navigateByUrl('/usuarios');
      fixture.detectChanges();

      expect(el.querySelector('.layout')?.classList).not.toContain('layout--menu-abierto');
      fixture.destroy();
    });

    it('en pantalla ancha el menú no es un diálogo ni deja nada inert', () => {
      simularAncho(false);
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      const { fixture, el } = crear();
      (el.querySelector('.layout__hamburguesa') as HTMLButtonElement).click();
      fixture.detectChanges();

      expect(el.querySelector('aside')?.getAttribute('role')).toBeNull();
      expect(el.querySelector('.layout__contenido')?.hasAttribute('inert')).toBe(false);
      fixture.destroy();
    });
  });

  describe('accesibilidad del menú y de la barra', () => {
    it('la opción de la ruta activa lleva aria-current="page"', async () => {
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      TestBed.inject(Router).resetConfig([{ path: '**', component: PaginaVaciaComponent }]);
      const { fixture, el } = crear();

      await TestBed.inject(Router).navigateByUrl('/usuarios');
      fixture.detectChanges();

      const activos = Array.from(el.querySelectorAll('nav a[aria-current="page"]'));
      expect(activos.map((a) => a.textContent?.trim())).toEqual(['Usuarios']);
      fixture.destroy();
    });

    it('la campana dice cuántas notificaciones hay sin leer', () => {
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      const { fixture, el } = crear();
      const campana = () => el.querySelector('.layout__campana') as HTMLButtonElement;
      expect(campana().getAttribute('aria-label')).toBe('Notificaciones');

      http
        .expectOne((req) => req.url.includes('/notificaciones'))
        .flush([
          { id: 1, titulo: 'a', mensaje: null, leida: false },
          { id: 2, titulo: 'b', mensaje: null, leida: false },
          { id: 3, titulo: 'c', mensaje: null, leida: true },
        ]);
      fixture.detectChanges();

      expect(campana().getAttribute('aria-label')).toBe('Notificaciones, 2 sin leer');
      fixture.destroy();
    });

    it('el motivo de una opción deshabilitada por el plan se lee con aria-describedby, no solo con title', () => {
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      plan.suscripcion.set(suscripcion([]));
      const { fixture, el } = crear();
      fixture.detectChanges();

      const enlace = Array.from(el.querySelectorAll('nav a.layout__enlace')).find((a) =>
        (a.textContent ?? '').includes('Reportes con IA'),
      ) as HTMLElement;
      const motivo = el.querySelector(`#${enlace.getAttribute('aria-describedby')}`);
      expect(motivo?.textContent).toBe('Tu plan Básico no incluye esto. Más info en Mi empresa.');
      fixture.destroy();
    });

    it('un administrador ve el logo de su empresa en la marca; sin logo queda el monograma', () => {
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      const { fixture, el } = crear();
      expect(el.querySelector('fs-marca .marca__monograma')).not.toBeNull();

      http.expectOne(`${API}/mi-empresa`).flush({
        id: 7,
        codigo: 'boutique-andina',
        nombre: 'Boutique Andina',
        logo_url: 'https://cdn.example/logo.png',
        color_acento: null,
        activo: true,
      });
      fixture.detectChanges();

      const logo = el.querySelector('fs-marca img.marca__logo') as HTMLImageElement;
      expect(logo.getAttribute('src')).toBe('https://cdn.example/logo.png');
      fixture.destroy();
    });

    it('quien no administra la empresa no pide /mi-empresa', () => {
      iniciarSesion(['cajero'], ['inventario.ver'], 7);
      const { fixture } = crear();

      http.expectNone(`${API}/mi-empresa`);
      fixture.destroy();
    });
  });

  describe('personal de una empresa', () => {
    it('pide notificaciones y su plan, y tiene campana', () => {
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      const { fixture, el } = crear();

      http.expectOne((req) => req.url.includes('/notificaciones')).flush([]);
      http.expectOne(`${API}/mi-empresa/suscripcion`).flush(suscripcion(['operacion_offline']));
      fixture.detectChanges();

      expect(el.querySelector('.layout__campana')).not.toBeNull();
      expect(el.querySelector('app-aviso-suscripcion')).not.toBeNull();
      fixture.destroy();
    });

    it('el indicador de conexión es lo primero de la barra de acciones, antes de la campana y de Salir', () => {
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      const { fixture, el } = crear();

      const acciones = el.querySelector('.layout__barra-acciones') as HTMLElement;
      const hijos = Array.from(acciones.children).map((h) => h.tagName.toLowerCase() + '.' + h.className);
      expect(hijos[0]).toBe('app-indicador-conexion.');
      expect(hijos.indexOf('button.layout__boton-icono layout__campana')).toBe(1);
      expect(hijos.length).toBe(3);
      fixture.destroy();
    });

    describe('consulta de notificaciones cada 20 s', () => {
      const cargasDeNotificaciones = () => http.match((req) => req.url.includes('/notificaciones'));

      afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
        delete (navigator as { onLine?: boolean }).onLine;
      });

      it('en línea consulta en cada intervalo; sin conexión se detiene y al volver la red se reanuda', () => {
        vi.useFakeTimers();
        vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true } as Response)));
        iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
        const { fixture } = crear();
        expect(cargasDeNotificaciones().length).toBe(1); // la carga inicial

        vi.advanceTimersByTime(20_000);
        expect(cargasDeNotificaciones().length).toBe(1);

        window.dispatchEvent(new Event('offline'));
        vi.advanceTimersByTime(60_000);
        expect(cargasDeNotificaciones().length).toBe(0);

        window.dispatchEvent(new Event('online'));
        vi.advanceTimersByTime(20_000);
        expect(cargasDeNotificaciones().length).toBe(1);
        fixture.destroy();
      });
    });

    it('con la suscripción vencida muestra la franja entre la barra y el contenido', () => {
      iniciarSesion(['administrador'], PERMISOS_ADMIN, 7);
      plan.suscripcion.set({ ...suscripcion([]), estado: 'vencida', fecha_vencimiento: '2026-10-12' });
      const { fixture, el } = crear();
      fixture.detectChanges();

      const franja = el.querySelector('.aviso-suscripcion');
      expect(franja?.textContent).toContain('vencida desde el 12/10/2026');
      const contenido = el.querySelector('.layout__contenido') as HTMLElement;
      const hijos = Array.from(contenido.children).map((h) => h.tagName.toLowerCase() + '.' + h.className);
      expect(hijos.indexOf('app-aviso-suscripcion.')).toBeGreaterThan(hijos.indexOf('header.layout__barra'));
      expect(hijos.indexOf('app-aviso-suscripcion.')).toBeLessThan(hijos.indexOf('main.layout__panel'));
      fixture.destroy();
    });
  });

  describe('cola de envío en la barra', () => {
    afterEach(() => delete (navigator as { onLine?: boolean }).onLine);

    it('el indicador muestra cuántas operaciones esperan en el equipo y enlaza a "Pendientes de envío"', async () => {
      // Sin red la cola no intenta enviar: así solo se prueba el conteo que llega a la barra.
      Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => false });
      iniciarSesion(['cajero'], ['ventas.presencial'], 7);
      const operacion = {
        empresa_id: 7,
        usuario_id: 1,
        operacion_id: '00000000-0000-4000-8000-0000000000aa',
        tipo: 'venta_contado',
        estado: 'registrada',
        fecha_operacion: '2026-10-30T10:00:00.000Z',
      } as unknown as OperacionOffline;
      await TestBed.inject(AlmacenOfflineService).repositorio({ empresaId: 7, usuarioId: 1 }).registrarOperacion(operacion);

      const { fixture, el } = crear();

      await vi.waitFor(() => {
        fixture.detectChanges();
        const chip = el.querySelector('app-indicador-conexion a.fs-chip') as HTMLAnchorElement | null;
        expect(chip?.textContent).toContain('1 por enviar');
        expect(chip?.getAttribute('href')).toBe('/operaciones-pendientes');
      });
      fixture.destroy();
    });
  });

  it('exporta las listas de ítems (las usan las pruebas de orden)', () => {
    expect(ITEMS_INICIO.length).toBe(4);
  });

  it('los ítems de la E17 van al final de Análisis, sin cambiar el orden previo, y dependen del plan', () => {
    expect(ITEMS_INICIO.map((i) => i.etiqueta)).toEqual(['Dashboard', 'Reportes', 'Reportes con IA', 'Analítica']);
    const ia = ITEMS_INICIO.find((i) => i.ruta === '/reportes-ia');
    const analitica = ITEMS_INICIO.find((i) => i.ruta === '/analitica');
    expect(ia).toMatchObject({ permiso: 'reportes.ver', funcion: 'reportes_ia' });
    expect(analitica).toMatchObject({ permiso: 'reportes.ver', funcion: 'analitica_ml' });
  });
});
