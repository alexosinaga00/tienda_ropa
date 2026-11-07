import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../../environments/environment';
import { AuthService } from '../../core/auth.service';
import { ResumenInicio, VentaRecienteInicio } from '../../core/models/inicio.models';
import { DashboardComponent } from './dashboard.component';

const API = environment.apiUrl;
const RESUMEN = `${API}/inicio/resumen`;

function venta(id: number, estado: VentaRecienteInicio['estado'], total: string, extra: Partial<VentaRecienteInicio> = {}) {
  return {
    id,
    codigo: `V-00${id}`,
    fecha: '2026-11-07T15:00:00Z',
    total,
    estado,
    unidades_vendidas: 1,
    unidades_devueltas: 0,
    ...extra,
  } satisfies VentaRecienteInicio;
}

/** Un resumen con solo ventas, que cada prueba ajusta. */
function resumen(cambios: Partial<ResumenInicio> = {}): ResumenInicio {
  return {
    fecha: '2026-11-07',
    sucursal_id: 1,
    sucursal_nombre: 'Central',
    ventas: {
      tickets: 0,
      total_ventas: '0.00',
      por_cobrar_cantidad: 0,
      por_cobrar_total: '0.00',
      mas_vendidas: [],
      recientes: [],
    },
    stock: null,
    reservas: null,
    ...cambios,
  };
}

describe('DashboardComponent', () => {
  let http: HttpTestingController;
  let auth: AuthService;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      imports: [DashboardComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    auth = TestBed.inject(AuthService);
  });

  afterEach(() => {
    localStorage.clear();
    http.match(() => true);
  });

  function iniciarSesion(roles: string[], permisos: string[]): void {
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
      empresa_id: 7,
    });
  }

  function crear() {
    const fixture = TestBed.createComponent(DashboardComponent);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  /** Abre la pantalla y responde el resumen: la única llamada que hace. */
  function abrirCon(respuesta: ResumenInicio, roles = ['cajero'], permisos = ['ventas.gestionar_sucursal']) {
    iniciarSesion(roles, permisos);
    const abierta = crear();
    http.expectOne(RESUMEN).flush(respuesta);
    abierta.fixture.detectChanges();
    return abierta;
  }

  it('saluda con rótulo "Resumen" y muestra la sucursal', () => {
    const { el } = abrirCon(resumen());

    expect(el.querySelector('.fs-eyebrow')?.textContent).toBe('Resumen');
    expect(el.querySelector('h1')?.textContent).toBe('Hola, Ana');
    expect(el.querySelector('.dash-sucursal')?.textContent).toBe('Central');
  });

  it('hace UNA sola llamada: no pide empleado, sucursales, ventas, reservas ni fotos por separado', () => {
    iniciarSesion(['administrador'], ['ventas.gestionar_sucursal', 'inventario.ver', 'reservas.gestionar_sucursal']);
    const { fixture } = crear();
    http.expectOne(RESUMEN).flush(resumen({ sucursal_id: null, sucursal_nombre: 'Todas las sucursales' }));
    fixture.detectChanges();

    http.expectNone(`${API}/empleados/yo`);
    http.expectNone((r) => r.url.includes('/ventas/sucursal'));
    http.expectNone((r) => r.url.includes('/reservas/sucursal'));
    http.expectNone((r) => r.url.includes('/catalogo/variantes/detalle'));
    http.expectNone((r) => r.url.includes('/inventario/alertas'));
    http.expectNone(`${API}/sucursales?tamanio=100`);
  });

  it('mientras llega el resumen muestra esqueletos y NO un 0 de relleno', () => {
    iniciarSesion(['administrador'], ['ventas.gestionar_sucursal', 'inventario.ver', 'reservas.gestionar_sucursal']);
    const { fixture, el } = crear();

    expect(el.querySelectorAll('.dash-kpi').length).toBe(3);
    expect(el.querySelectorAll('.dash-kpi .dash-esqueleto--valor').length).toBe(3);
    expect(el.querySelector('.dash-kpi__valor')).toBeNull();
    expect(el.querySelector('.dash-kpis')?.getAttribute('aria-busy')).toBe('true');
    expect(el.querySelector('.dash-sucursal')?.textContent).toBe('');

    http.expectOne(RESUMEN).flush(
      resumen({
        stock: { total_alertas: 0, alertas: [] },
        reservas: { total: 0, por_estado: [] },
      }),
    );
    fixture.detectChanges();

    expect(el.querySelector('.dash-esqueleto')).toBeNull();
    expect(el.querySelectorAll('.dash-kpi__valor').length).toBe(3);
    expect(el.querySelector('.dash-kpis')?.getAttribute('aria-busy')).toBe('false');
  });

  it('con permisos de ventas muestra la tarjeta de ventas, las barras y las últimas ventas con chips de estado', () => {
    const { el } = abrirCon(
      resumen({
        ventas: {
          tickets: 1,
          total_ventas: '100.00',
          por_cobrar_cantidad: 1,
          por_cobrar_total: '250.50',
          mas_vendidas: [{ variante_id: 11, nombre: 'Camisa Oxford', cantidad: 1 }],
          recientes: [venta(3, 'anulada', '80.00'), venta(2, 'pendiente_pago', '250.50'), venta(1, 'pagada', '100.00')],
        },
      }),
    );

    const kpi = el.querySelector('.dash-kpi') as HTMLElement;
    expect(kpi.textContent).toContain('Ventas de hoy');
    expect(kpi.querySelector('.dash-kpi__valor')?.textContent).toContain('Bs 100.00');
    expect(kpi.querySelector('.dash-kpi__nota')?.textContent).toContain('1 ticket');
    expect(kpi.querySelector('.dash-kpi__nota')?.textContent).not.toContain('tickets');
    expect(kpi.querySelector('.dash-kpi__nota--por-cobrar')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
      'Por cobrar: 1 venta (Bs 250.50)',
    );
    expect(kpi.querySelector('.dash-kpi__icono svg')?.getAttribute('width')).toBe('30');

    expect(el.querySelectorAll('.dash-barra').length).toBe(1);
    expect(el.querySelectorAll('.dash-barra__relleno--max').length).toBe(1);

    const filas = Array.from(el.querySelectorAll('.dash-tabla tbody tr'));
    expect(filas.map((f) => f.querySelector('td')?.textContent?.trim())).toEqual(['V-003', 'V-002', 'V-001']);
    const chips = Array.from(el.querySelectorAll('.dash-tabla .fs-chip'));
    expect(chips.map((c) => c.textContent?.trim())).toEqual(['Anulada', 'Pendiente de pago', 'Pagada']);
    expect(chips[0].classList).toContain('fs-chip--error');
    expect(chips[1].classList).toContain('fs-chip--advertencia');
    expect(chips[2].classList).toContain('fs-chip--exito');
  });

  it('el plural de tickets y de ventas por cobrar sale del conteo que manda el servidor', () => {
    const { el } = abrirCon(
      resumen({
        ventas: {
          tickets: 2,
          total_ventas: '100.00',
          por_cobrar_cantidad: 2,
          por_cobrar_total: '30.50',
          mas_vendidas: [],
          recientes: [],
        },
      }),
    );

    expect(el.querySelector('.dash-kpi__nota')?.textContent).toContain('2 tickets');
    expect(el.querySelector('.dash-kpi__nota--por-cobrar')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
      'Por cobrar: 2 ventas (Bs 30.50)',
    );
  });

  it('una venta con devolución sigue pagada pero "Últimas ventas" dice que se devolvió', () => {
    const { el } = abrirCon(
      resumen({
        ventas: {
          tickets: 2,
          total_ventas: '150.00',
          por_cobrar_cantidad: 0,
          por_cobrar_total: '0.00',
          mas_vendidas: [],
          recientes: [
            venta(2, 'pagada', '100.00', { unidades_vendidas: 2, unidades_devueltas: 1 }),
            venta(1, 'pagada', '50.00', { unidades_vendidas: 1, unidades_devueltas: 1 }),
          ],
        },
      }),
    );

    const marcas = Array.from(el.querySelectorAll('.dash-tabla [data-estado="con-devolucion"]')).map((c) =>
      c.textContent?.trim(),
    );
    expect(marcas).toEqual(['Con devolución (1 de 2)', 'Devuelta']);
    expect(el.querySelector('.dash-tabla .fs-chip')?.textContent?.trim()).toBe('Pagada');
    expect(el.querySelector('.dash-kpi__valor')?.textContent).toContain('Bs 150.00');
  });

  it('sin ventas hoy muestra Bs 0.00 y los estados vacíos (sin gráfico)', () => {
    const { el } = abrirCon(resumen());

    expect(el.querySelector('.dash-kpi__valor')?.textContent).toContain('Bs 0.00');
    expect(el.querySelector('.dash-kpi__nota')?.textContent).toContain('0 tickets');
    expect(el.querySelector('.dash-kpi__nota--por-cobrar')).toBeNull();
    expect(el.querySelector('.dash-barras')).toBeNull();
    expect(el.querySelector('.dash-tabla .fs-estado-vacio')?.textContent).toContain('Todavía no hay ventas hoy.');
  });

  it('el gráfico de barras tiene una alternativa textual con los valores', () => {
    const { el } = abrirCon(
      resumen({
        ventas: {
          tickets: 2,
          total_ventas: '150.00',
          por_cobrar_cantidad: 0,
          por_cobrar_total: '0.00',
          mas_vendidas: [
            { variante_id: 12, nombre: 'Camisa Oxford', cantidad: 2 },
            { variante_id: 11, nombre: 'Polera Lisa', cantidad: 1 },
          ],
          recientes: [],
        },
      }),
    );

    expect(el.querySelector('.dash-barras')?.getAttribute('aria-hidden')).toBe('true');
    const lista = el.querySelector('ul.sr-solo') as HTMLElement;
    expect(lista.getAttribute('aria-label')).toBe('Unidades vendidas hoy por prenda');
    expect(Array.from(lista.querySelectorAll('li')).map((li) => li.textContent?.trim())).toEqual([
      'Camisa Oxford: 2',
      'Polera Lisa: 1',
    ]);
  });

  it('muestra el stock bajo con el total real de alertas y la foto de cada prenda', () => {
    const alertas = Array.from({ length: 4 }, (_, i) => ({
      producto_id: i + 1,
      variante_id: i + 1,
      producto: `Prenda ${i + 1}`,
      stock_minimo: 3,
      cantidad_disponible: 1,
      imagen: i === 0 ? 'https://res.cloudinary.com/x/foto.jpg' : null,
    }));
    const { el } = abrirCon(resumen({ ventas: null, stock: { total_alertas: 6, alertas } }), ['encargado'], ['inventario.ver']);

    expect(el.querySelector('.dash-kpi__valor')?.textContent?.trim()).toBe('6');
    expect(el.querySelectorAll('.dash-lista__fila').length).toBe(4);
    expect(el.querySelector('.dash-lista__cantidad')?.textContent).toContain('1 u.');
    expect(el.querySelector('.dash-lista__foto img')?.getAttribute('src')).toBe('https://res.cloudinary.com/x/foto.jpg');
    expect(el.querySelector('.dash-tabla')).toBeNull(); // sin ventas no hay tabla de ventas
  });

  it('las reservas de hoy muestran su cantidad por estado en texto', () => {
    const { el } = abrirCon(
      resumen({
        ventas: null,
        reservas: {
          total: 3,
          por_estado: [
            { codigo: 'pendiente', nombre: 'Pendiente', cantidad: 2 },
            { codigo: 'completada', nombre: 'Completada', cantidad: 1 },
          ],
        },
      }),
      ['encargado'],
      ['reservas.gestionar_sucursal'],
    );

    const pills = Array.from(el.querySelectorAll('.dash-pill')).map((p) => p.textContent?.replace(/\s+/g, ' ').trim());
    expect(pills).toEqual(['Pendientes 2', 'En prueba 0', 'Completadas 1', 'Canceladas 0']);
    expect(el.querySelector('.dash-kpi__valor')?.textContent?.trim()).toBe('3');
    expect(el.querySelector('.dash-apilada')?.getAttribute('aria-hidden')).toBe('true');
  });

  it('una sección que el servidor no manda (el plan no la incluye) no se dibuja aunque el rol la permita', () => {
    const { el } = abrirCon(resumen({ reservas: null }), ['administrador'], [
      'ventas.gestionar_sucursal',
      'reservas.gestionar_sucursal',
    ]);

    expect(el.querySelector('.dash-kpi')?.textContent).toContain('Ventas de hoy');
    expect(el.textContent).not.toContain('Reservas de hoy');
  });

  it('un administrador ve "Todas las sucursales"', () => {
    const { el } = abrirCon(resumen({ sucursal_id: null, sucursal_nombre: 'Todas las sucursales' }), ['administrador']);

    expect(el.querySelector('.dash-sucursal')?.textContent).toBe('Todas las sucursales');
  });

  it('sin sucursal asignada (403) avisa en tuteo y no dibuja indicadores', () => {
    iniciarSesion(['cajero'], ['ventas.gestionar_sucursal']);
    const { fixture, el } = crear();
    http.expectOne(RESUMEN).flush({ detail: 'No tenés una sucursal asignada' }, { status: 403, statusText: 'Forbidden' });
    fixture.detectChanges();

    const aviso = el.querySelector('.fs-aviso')?.textContent ?? '';
    expect(aviso).toContain('No tienes una sucursal asignada.');
    expect(aviso).toContain('Pídele a un administrador');
    expect(el.querySelector('.dash-kpis')).toBeNull();
  });

  it('si falla la carga ofrece reintentar y al reintentar vuelve a pedir el resumen', () => {
    iniciarSesion(['cajero'], ['ventas.gestionar_sucursal']);
    const { fixture, el } = crear();
    http.expectOne(RESUMEN).flush('error', { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(el.querySelector('[data-testid="dash-fallo"]')?.textContent).toContain('No se pudo cargar el resumen de hoy.');
    expect(el.querySelector('.dash-kpis')).toBeNull();

    (el.querySelector('[data-testid="dash-fallo"] button') as HTMLButtonElement).click();
    http.expectOne(RESUMEN).flush(resumen());
    fixture.detectChanges();

    expect(el.querySelector('[data-testid="dash-fallo"]')).toBeNull();
    expect(el.querySelector('.dash-kpi__valor')?.textContent).toContain('Bs 0.00');
  });

  it('un rol sin ventas, inventario ni reservas (proveedor) ve un aviso claro y no un panel vacío', () => {
    iniciarSesion(['proveedor'], ['catalogo.ver']);
    const { fixture, el } = crear();
    http.expectOne(RESUMEN).flush(resumen({ sucursal_id: null, sucursal_nombre: '', ventas: null }));
    fixture.detectChanges();

    const aviso = el.querySelector('.fs-aviso')?.textContent ?? '';
    expect(aviso).toContain('Tu rol no tiene indicadores en este resumen.');
    expect(aviso).not.toContain('No tienes una sucursal asignada');
    expect(el.querySelector('.dash-kpis')).toBeNull();
  });

  it('mientras no se conoce al usuario el título es "Hola" (sin coma ni nombre vacío)', () => {
    const { el } = crear();
    http.expectOne(RESUMEN);

    expect(el.querySelector('h1')?.textContent).toBe('Hola');
  });
});
