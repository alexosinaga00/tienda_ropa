import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ConfirmationService, MessageService } from 'primeng/api';
import { environment } from '../../../../environments/environment';
import { fechaLocalIso } from '../../../core/date-utils';
import { EmpresaPlataforma, PlanPlataforma } from '../../../core/models/plataforma.models';
import { hoyLocal, sumarDias } from '../data/fechas-plataforma';
import { EmpresasComponent } from './empresas.component';

const BASE = `${environment.apiUrl}/plataforma`;
const CLAVE = 'Clave-Inicial-7788';

function plan(codigo: string, nombre: string, max: number, activo = true): PlanPlataforma {
  return {
    id: codigo === 'basico' ? 1 : 2,
    codigo,
    nombre,
    max_sucursales: max,
    max_copias_historial: 0,
    plazo_cambio_horas_defecto: 24,
    precio_mensual_bs: null,
    reportes_convencionales: true,
    reportes_ia: false,
    operacion_offline: false,
    analitica_ml: false,
    copias_seguridad: false,
    gestion_productos: true,
    gestion_ventas: true,
    reservas: true,
    activo,
  };
}

function empresa(id: number, sobrescribir: Partial<EmpresaPlataforma> = {}): EmpresaPlataforma {
  return {
    id,
    codigo: `tienda-${id}`,
    nombre: `Tienda ${id}`,
    logo_url: null,
    color_acento: null,
    activo: true,
    plan_codigo: 'basico',
    suscripcion_estado: 'activa',
    fecha_inicio: '2026-10-01',
    fecha_vencimiento: '2026-11-30',
    administrador_email: `admin${id}@tienda.com`,
    ...sobrescribir,
  };
}

interface Interno {
  formulario: {
    invalid: boolean;
    controls: Record<string, { setValue(v: unknown): void; valid: boolean; errors: Record<string, unknown> | null }> & {
      administrador: { controls: Record<string, { setValue(v: unknown): void; valid: boolean }> };
    };
    getRawValue(): { administrador: { password: string } };
  };
  codigoVistaPrevia(): string;
  claveInicial(): string | null;
  creada(): { codigo: string } | null;
  errorNombre(): string | null;
  dialogoNuevoVisible(): boolean;
  filas(): EmpresaPlataforma[];
  filtroEstado: { set(v: string | null): void };
  filtroPlan: { set(v: string | null): void };
  abrirNueva(): void;
  crear(): void;
  cerrarNueva(): void;
  armarAlta(): unknown;
  escribirBusqueda(v: string): void;
  abrirEditar(e: EmpresaPlataforma): void;
  guardarEdicion(): void;
  formularioEdicion: { controls: Record<string, { setValue(v: unknown): void }> };
  pedirCambioActivo(e: EmpresaPlataforma): void;
}

describe('EmpresasComponent', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    TestBed.configureTestingModule({
      imports: [EmpresasComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), MessageService],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    vi.useRealTimers();
    http.verify();
    localStorage.clear();
    sessionStorage.clear();
  });

  function crear(empresas: EmpresaPlataforma[] = [empresa(1), empresa(2)]) {
    const fixture = TestBed.createComponent(EmpresasComponent);
    fixture.detectChanges();
    http
      .expectOne((r) => r.url === `${BASE}/planes`)
      .flush([plan('basico', 'Básico', 2), plan('profesional', 'Profesional', 10)]);
    const lista = http.expectOne((r) => r.url === `${BASE}/empresas`);
    expect(lista.request.params.get('pagina')).toBe('1');
    expect(lista.request.params.get('tamanio')).toBe('20');
    lista.flush(empresas);
    fixture.detectChanges();
    return { fixture, comp: fixture.componentInstance as unknown as Interno };
  }

  function llenarAlta(comp: Interno, sobrescribir: { nombre?: string; password?: string; email?: string } = {}) {
    const c = comp.formulario.controls;
    c['nombre'].setValue(sobrescribir.nombre ?? 'Moda Ñandú & Hijos');
    c['logo_url'].setValue('https://img.test/logo.png');
    c['color_acento'].setValue('#2563EB');
    const a = c.administrador.controls;
    a['nombre'].setValue('Ana');
    a['apellido'].setValue('Paz');
    a['email'].setValue(sobrescribir.email ?? 'ana@moda.com');
    a['telefono'].setValue('70000000');
    a['password'].setValue(sobrescribir.password ?? CLAVE);
  }

  it('lista las empresas con su plan, estado y vencimiento', () => {
    const { fixture } = crear();
    const texto = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(texto).toContain('Tienda 1');
    expect(texto).toContain('tienda-2');
    expect(texto).toContain('Básico');
    expect(texto).toContain('Activa');
    expect(texto).toContain('30/11/2026');
  });

  it('el enlace "ver tienda" abre /t/<codigo> en una pestaña nueva', () => {
    const { fixture } = crear();
    const enlace = (fixture.nativeElement as HTMLElement).querySelector('a[title="Ver tienda"]');
    expect(enlace?.getAttribute('href')).toBe('/t/tienda-1');
    expect(enlace?.getAttribute('target')).toBe('_blank');
  });

  it('filtra por estado y por plan sobre la página cargada', () => {
    const { comp } = crear([
      empresa(1),
      empresa(2, { suscripcion_estado: 'vencida', plan_codigo: 'profesional' }),
      empresa(3, { suscripcion_estado: null, plan_codigo: null }),
    ]);
    comp.filtroEstado.set('vencida');
    expect(comp.filas().map((e) => e.id)).toEqual([2]);
    comp.filtroEstado.set('sin_suscripcion');
    expect(comp.filas().map((e) => e.id)).toEqual([3]);
    comp.filtroEstado.set(null);
    comp.filtroPlan.set('basico');
    expect(comp.filas().map((e) => e.id)).toEqual([1]);
  });

  it('la búsqueda espera 350 ms y manda q al servidor', () => {
    vi.useFakeTimers();
    const { comp } = crear();
    comp.escribirBusqueda('mo');
    comp.escribirBusqueda('moda');
    vi.advanceTimersByTime(349);
    http.expectNone((r) => r.url === `${BASE}/empresas`);
    vi.advanceTimersByTime(2);
    const req = http.expectOne((r) => r.url === `${BASE}/empresas`);
    expect(req.request.params.get('q')).toBe('moda');
    expect(req.request.params.get('pagina')).toBe('1');
    req.flush([]);
  });

  describe('alta', () => {
    it('muestra en vivo el código calculado y que no cambia', () => {
      const { fixture, comp } = crear();
      comp.abrirNueva();
      comp.formulario.controls['nombre'].setValue('Moda Ñandú & Hijos');
      fixture.detectChanges();
      expect(comp.codigoVistaPrevia()).toBe('moda-nandu-hijos');
      const texto = document.body.textContent ?? '';
      expect(texto).toContain('moda-nandu-hijos');
      expect(texto).toContain('No cambia aunque cambies el nombre.');
      expect(texto).toContain('Simulación de contratación: no se realiza ningún cobro.');
    });

    it('avisa que un color con poco contraste cae al color base, y no avisa con uno bueno', () => {
      const { fixture, comp } = crear();
      comp.abrirNueva();
      comp.formulario.controls['color_acento'].setValue('#FFFF00');
      fixture.detectChanges();
      expect(document.body.textContent ?? '').toContain('contrasta poco con el blanco');

      comp.formulario.controls['color_acento'].setValue('#1F4E79');
      fixture.detectChanges();
      expect(document.body.textContent ?? '').not.toContain('contrasta poco con el blanco');
    });

    it('arranca con Básico y un vencimiento a 30 días', () => {
      const { comp } = crear();
      comp.abrirNueva();
      const v = comp.formulario.getRawValue() as unknown as { plan_codigo: string; fecha_vencimiento: Date };
      expect(v.plan_codigo).toBe('basico');
      expect(fechaLocalIso(v.fecha_vencimiento)).toBe(fechaLocalIso(sumarDias(hoyLocal(), 30)));
    });

    it('valida nombre, correo y clave antes de llamar a la API', () => {
      const { comp } = crear();
      comp.abrirNueva();
      const c = comp.formulario.controls;
      const a = c.administrador.controls;
      llenarAlta(comp);
      expect(comp.formulario.invalid).toBe(false);

      for (const malo of ['', ' ', 'A', '---&&&']) {
        c['nombre'].setValue(malo);
        expect(c['nombre'].valid, `nombre "${malo}"`).toBe(false);
      }
      c['nombre'].setValue('Moda');
      expect(c['nombre'].valid).toBe(true);

      for (const malo of ['', 'sin-arroba', 'a@']) {
        a['email'].setValue(malo);
        expect(a['email'].valid, `correo "${malo}"`).toBe(false);
      }
      a['email'].setValue('ana@moda.com');
      expect(a['email'].valid).toBe(true);

      a['password'].setValue('1234567');
      expect(a['password'].valid).toBe(false);
      a['password'].setValue('12345678');
      expect(a['password'].valid).toBe(true);
      a['password'].setValue('x'.repeat(73));
      expect(a['password'].valid).toBe(false);

      c['color_acento'].setValue('rojo');
      expect(c['color_acento'].valid).toBe(false);
      c['color_acento'].setValue('#2563eb');
      expect(c['color_acento'].valid).toBe(true);

      c['logo_url'].setValue('javascript:alert(1)');
      expect(c['logo_url'].valid).toBe(false);

      c['nombre'].setValue('');
      comp.crear();
      http.expectNone(`${BASE}/empresas`);
    });

    it('rechaza un vencimiento que no es posterior a hoy', () => {
      const { comp } = crear();
      comp.abrirNueva();
      llenarAlta(comp);
      comp.formulario.controls['fecha_vencimiento'].setValue(hoyLocal());
      expect(comp.formulario.controls['fecha_vencimiento'].valid).toBe(false);
      comp.formulario.controls['fecha_vencimiento'].setValue(sumarDias(hoyLocal(), 1));
      expect(comp.formulario.controls['fecha_vencimiento'].valid).toBe(true);
    });

    it('manda el cuerpo exacto con el administrador', () => {
      const { comp } = crear();
      comp.abrirNueva();
      llenarAlta(comp);
      const vence = new Date(2027, 0, 31);
      comp.formulario.controls['fecha_vencimiento'].setValue(vence);

      comp.crear();
      const post = http.expectOne(`${BASE}/empresas`);
      expect(post.request.method).toBe('POST');
      expect(post.request.body).toEqual({
        nombre: 'Moda Ñandú & Hijos',
        plan_codigo: 'basico',
        fecha_vencimiento: '2027-01-31',
        color_acento: '#2563eb',
        logo_url: 'https://img.test/logo.png',
        administrador: {
          nombre: 'Ana',
          apellido: 'Paz',
          email: 'ana@moda.com',
          telefono: '70000000',
          password: CLAVE,
        },
      });
      post.flush(empresa(9, { codigo: 'moda-nandu-hijos', nombre: 'Moda Ñandú & Hijos' }));
      http.expectOne((r) => r.url === `${BASE}/empresas`).flush([]);
    });

    it('omite logo, color y teléfono si están vacíos', () => {
      const { comp } = crear();
      comp.abrirNueva();
      llenarAlta(comp);
      comp.formulario.controls['logo_url'].setValue('');
      comp.formulario.controls['color_acento'].setValue('');
      comp.formulario.controls.administrador.controls['telefono'].setValue('');
      const cuerpo = comp.armarAlta() as Record<string, unknown> & { administrador: Record<string, unknown> };
      expect('logo_url' in cuerpo).toBe(false);
      expect('color_acento' in cuerpo).toBe(false);
      expect('telefono' in cuerpo.administrador).toBe(false);
    });

    it('muestra la clave inicial una sola vez y no la deja en ningún storage', () => {
      const { fixture, comp } = crear();
      comp.abrirNueva();
      llenarAlta(comp);
      comp.crear();
      http
        .expectOne(`${BASE}/empresas`)
        .flush(empresa(9, { codigo: 'moda-nandu-hijos', nombre: 'Moda Ñandú & Hijos', administrador_email: 'ana@moda.com' }));
      http.expectOne((r) => r.url === `${BASE}/empresas`).flush([]);
      fixture.detectChanges();

      // El resumen muestra código, enlace a la tienda y la clave con su aviso.
      const texto = document.body.textContent ?? '';
      expect(comp.creada()?.codigo).toBe('moda-nandu-hijos');
      expect(texto).toContain('moda-nandu-hijos');
      expect(texto).toContain(CLAVE);
      expect(texto).toContain('Anota la clave inicial: no se vuelve a mostrar.');
      expect(document.querySelector('a[href="/t/moda-nandu-hijos"]')).not.toBeNull();

      // El formulario ya no guarda la clave y ningún storage la tiene.
      expect(comp.formulario.getRawValue().administrador.password).toBe('');
      const volcado = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage });
      expect(volcado).not.toContain(CLAVE);

      // Al cerrar se borra y no vuelve a verse.
      comp.cerrarNueva();
      fixture.detectChanges();
      expect(comp.claveInicial()).toBeNull();
      expect(comp.creada()).toBeNull();
      expect(document.body.textContent ?? '').not.toContain(CLAVE);
      expect(JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage })).not.toContain(CLAVE);

      // Abrir de nuevo tampoco la recupera.
      comp.abrirNueva();
      fixture.detectChanges();
      expect(document.body.textContent ?? '').not.toContain(CLAVE);
    });

    it('un nombre repetido (409) se explica junto al campo y no cierra el diálogo', () => {
      const { fixture, comp } = crear();
      comp.abrirNueva();
      llenarAlta(comp);
      comp.crear();
      http
        .expectOne(`${BASE}/empresas`)
        .flush({ detail: 'Ya existe una empresa con ese nombre' }, { status: 409, statusText: 'Conflict' });
      fixture.detectChanges();

      expect(comp.errorNombre()).toContain('Ya existe una empresa con ese nombre');
      expect(comp.creada()).toBeNull();
      expect(comp.dialogoNuevoVisible()).toBe(true);
      expect(document.body.textContent ?? '').toContain('Prueba con otro nombre comercial');
      // La clave no se conserva si el alta falló.
      expect(comp.claveInicial()).toBeNull();

      // Al corregir el nombre, el aviso desaparece.
      comp.formulario.controls['nombre'].setValue('Moda Otra');
      expect(comp.errorNombre()).toBeNull();
    });
  });

  describe('edición y estado', () => {
    it('pide el resumen y manda nombre, logo y color (null borra)', () => {
      const { comp } = crear();
      comp.abrirEditar(empresa(1, { color_acento: '#2563eb' }));
      http.expectOne(`${BASE}/empresas/1/resumen`).flush({
        ...empresa(1),
        usuarios_activos: 3,
        sucursales_activas: 1,
        max_sucursales: 2,
      });

      comp.formularioEdicion.controls['nombre'].setValue('  Nuevo nombre ');
      comp.formularioEdicion.controls['color_acento'].setValue('');
      comp.guardarEdicion();
      const put = http.expectOne(`${BASE}/empresas/1`);
      expect(put.request.method).toBe('PUT');
      expect(put.request.body).toEqual({ nombre: 'Nuevo nombre', logo_url: null, color_acento: null });
      put.flush(empresa(1));
      http.expectOne((r) => r.url === `${BASE}/empresas`).flush([]);
    });

    it('el diálogo de edición muestra el código deshabilitado, con su explicación, y el uso', () => {
      const { fixture, comp } = crear();
      comp.abrirEditar(empresa(1));
      http.expectOne(`${BASE}/empresas/1/resumen`).flush({
        ...empresa(1),
        usuarios_activos: 3,
        sucursales_activas: 1,
        max_sucursales: 2,
      });
      fixture.detectChanges();
      const codigo = document.querySelector<HTMLInputElement>('#ed-codigo');
      expect(codigo?.disabled).toBe(true);
      expect(codigo?.value).toBe('tienda-1');
      const texto = document.body.textContent ?? '';
      expect(texto).toContain('no cambia aunque cambies el nombre');
      expect(texto).toContain('1 de 2');
    });

    it('en la edición también avisa del color con poco contraste', () => {
      const { fixture, comp } = crear();
      comp.abrirEditar(empresa(1));
      http.expectOne(`${BASE}/empresas/1/resumen`).flush({
        ...empresa(1),
        usuarios_activos: 1,
        sucursales_activas: 1,
        max_sucursales: 2,
      });
      comp.formularioEdicion.controls['color_acento'].setValue('#FFFF00');
      fixture.detectChanges();

      expect(document.body.textContent ?? '').toContain('contrasta poco con el blanco');
    });

    it('desactivar pide confirmación y luego manda PUT {activo:false}', () => {
      const { fixture, comp } = crear();
      const confirmacion = fixture.debugElement.injector.get(ConfirmationService);
      const espia = vi.spyOn(confirmacion, 'confirm');

      comp.pedirCambioActivo(empresa(1));
      expect(espia).toHaveBeenCalledTimes(1);
      const opciones = espia.mock.calls[0][0];
      expect(opciones.message).toBe('La tienda dejará de verse y su personal no podrá operar.');
      http.expectNone(`${BASE}/empresas/1`);

      opciones.accept?.();
      const put = http.expectOne(`${BASE}/empresas/1`);
      expect(put.request.body).toEqual({ activo: false });
      put.flush(empresa(1, { activo: false }));
      http.expectOne((r) => r.url === `${BASE}/empresas`).flush([]);
    });

    it('activar una empresa inactiva manda PUT {activo:true}', () => {
      const { fixture, comp } = crear();
      const confirmacion = fixture.debugElement.injector.get(ConfirmationService);
      const espia = vi.spyOn(confirmacion, 'confirm');

      comp.pedirCambioActivo(empresa(1, { activo: false }));
      espia.mock.calls[0][0].accept?.();
      const put = http.expectOne(`${BASE}/empresas/1`);
      expect(put.request.body).toEqual({ activo: true });
      put.flush(empresa(1));
      http.expectOne((r) => r.url === `${BASE}/empresas`).flush([]);
    });

    it('un error del servidor al desactivar no rompe la pantalla', () => {
      const { fixture, comp } = crear();
      const confirmacion = fixture.debugElement.injector.get(ConfirmationService);
      const espia = vi.spyOn(confirmacion, 'confirm');
      comp.pedirCambioActivo(empresa(1));
      espia.mock.calls[0][0].accept?.();
      http.expectOne(`${BASE}/empresas/1`).flush({ detail: 'x' }, { status: 500, statusText: 'Error' });
      http.expectNone((r) => r.url === `${BASE}/empresas`); // no recarga: nada cambió
    });
  });
});
