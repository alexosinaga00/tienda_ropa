import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../../environments/environment';
import { AuthService } from '../../core/auth.service';
import { DashboardComponent } from './dashboard.component';

const API = environment.apiUrl;

function ventaDeHoy(id: number, estado: string, total: number, hora: string) {
  const hoy = new Date();
  const dia = `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, '0')}-${String(hoy.getDate()).padStart(2, '0')}`;
  return {
    id,
    codigo: `V-00${id}`,
    canal: 'presencial',
    cliente_id: null,
    sucursal_id: 1,
    cajero_id: 2,
    reserva_id: null,
    estado,
    fecha: `${dia}T${hora}:00`,
    subtotal: total,
    descuento: 0,
    costo_envio: 0,
    total,
    detalle: [{ variante_id: 10 + id, cantidad: id, precio_unitario: 1, subtotal: 1 }],
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

  it('saluda con rótulo "Resumen" y muestra la sucursal', () => {
    iniciarSesion(['cajero'], ['ventas.gestionar_sucursal']);
    const { fixture, el } = crear();
    http.expectOne(`${API}/empleados/yo`).flush({ id: 1, usuario_id: 1, sucursal_id: 1, activo: true });
    http.expectOne(`${API}/sucursales/1`).flush({ id: 1, nombre: 'Central' });
    http.match(() => true).forEach((r) => r.flush([]));
    fixture.detectChanges();

    expect(el.querySelector('.fs-eyebrow')?.textContent).toBe('Resumen');
    expect(el.querySelector('h1')?.textContent).toBe('Hola, Ana');
    expect(el.querySelector('.dash-sucursal')?.textContent).toBe('Central');
  });

  it('sin sucursal avisa en tuteo', () => {
    iniciarSesion(['cajero'], ['ventas.gestionar_sucursal']);
    const { fixture, el } = crear();
    http.expectOne(`${API}/empleados/yo`).flush({ id: 1, usuario_id: 1, sucursal_id: null, activo: true });
    fixture.detectChanges();

    const aviso = el.querySelector('.fs-aviso')?.textContent ?? '';
    expect(aviso).toContain('No tienes una sucursal asignada.');
    expect(aviso).toContain('Pídele a un administrador');
    expect(el.querySelector('.dash-kpis')).toBeNull();
  });

  it('con permisos de ventas muestra la tarjeta de ventas, las barras y las últimas ventas con chips de estado', () => {
    iniciarSesion(['cajero'], ['ventas.gestionar_sucursal']);
    const { fixture, el } = crear();
    http.expectOne(`${API}/empleados/yo`).flush({ id: 1, usuario_id: 1, sucursal_id: 1, activo: true });
    http.expectOne(`${API}/sucursales/1`).flush({ id: 1, nombre: 'Central' });
    http
      .expectOne(`${API}/ventas/sucursal/1`)
      .flush([
        ventaDeHoy(1, 'pagada', 100, '09:30'),
        ventaDeHoy(2, 'pendiente_pago', 250.5, '11:15'),
        ventaDeHoy(3, 'anulada', 80, '12:00'),
      ]);
    http.match((r) => r.url.includes('/catalogo/variantes/detalle')).forEach((r) => r.flush([]));
    fixture.detectChanges();

    const kpi = el.querySelector('.dash-kpi') as HTMLElement;
    expect(kpi.textContent).toContain('Ventas de hoy');
    // Solo la pagada cuenta como vendida: la pendiente de pago y la anulada no suman.
    expect(kpi.querySelector('.dash-kpi__valor')?.textContent).toContain('Bs 100.00');
    expect(kpi.querySelector('.dash-kpi__nota')?.textContent).toContain('1 ticket');
    expect(kpi.querySelector('.dash-kpi__nota')?.textContent).not.toContain('tickets');
    // La pendiente de pago se avisa aparte.
    expect(kpi.querySelector('.dash-kpi__nota--por-cobrar')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
      'Por cobrar: 1 venta (Bs 250.50)',
    );
    // Ícono de 30 px dentro del cuadro de 52 px.
    expect(kpi.querySelector('.dash-kpi__icono svg')?.getAttribute('width')).toBe('30');

    // Barras: una por prenda vendida (solo de la venta pagada); la más vendida va resaltada.
    const barras = el.querySelectorAll('.dash-barra');
    expect(barras.length).toBe(1);
    expect(el.querySelectorAll('.dash-barra__relleno--max').length).toBe(1);

    // Últimas ventas: la más reciente primero, con su chip.
    const filas = Array.from(el.querySelectorAll('.dash-tabla tbody tr'));
    expect(filas.map((f) => f.querySelector('td')?.textContent?.trim())).toEqual(['V-003', 'V-002', 'V-001']);
    const chips = Array.from(el.querySelectorAll('.dash-tabla .fs-chip'));
    expect(chips.map((c) => c.textContent?.trim())).toEqual(['Anulada', 'Pendiente de pago', 'Pagada']);
    expect(chips[0].classList).toContain('fs-chip--error');
    expect(chips[1].classList).toContain('fs-chip--advertencia');
    expect(chips[2].classList).toContain('fs-chip--exito');
  });

  it('una venta con devolución sigue pagada (y cuenta como vendida) pero "Últimas ventas" dice que se devolvió', () => {
    iniciarSesion(['cajero'], ['ventas.gestionar_sucursal']);
    const { fixture, el } = crear();
    http.expectOne(`${API}/empleados/yo`).flush({ id: 1, usuario_id: 1, sucursal_id: 1, activo: true });
    http.expectOne(`${API}/sucursales/1`).flush({ id: 1, nombre: 'Central' });
    http.expectOne(`${API}/ventas/sucursal/1`).flush([
      { ...ventaDeHoy(2, 'pagada', 100, '10:00'), unidades_devueltas: 1 }, // vendió 2, devolvió 1
      { ...ventaDeHoy(1, 'pagada', 50, '09:00'), unidades_devueltas: 1 }, // vendió 1, devolvió 1
    ]);
    http.match((r) => r.url.includes('/catalogo/variantes/detalle')).forEach((r) => r.flush([]));
    fixture.detectChanges();

    const marcas = Array.from(el.querySelectorAll('.dash-tabla [data-estado="con-devolucion"]')).map((c) =>
      c.textContent?.trim(),
    );
    expect(marcas).toEqual(['Con devolución (1 de 2)', 'Devuelta']);
    // El estado sigue siendo "Pagada" y la venta sigue sumando (la devolución no resta ingresos).
    expect(el.querySelector('.dash-tabla .fs-chip')?.textContent?.trim()).toBe('Pagada');
    expect(el.querySelector('.dash-kpi__valor')?.textContent).toContain('Bs 150.00');
  });

  it('una venta anulada no cuenta como vendida: ni total, ni tickets, ni gráfico, ni "Por cobrar"', () => {
    iniciarSesion(['cajero'], ['ventas.gestionar_sucursal']);
    const { fixture, el } = crear();
    http.expectOne(`${API}/empleados/yo`).flush({ id: 1, usuario_id: 1, sucursal_id: 1, activo: true });
    http.expectOne(`${API}/sucursales/1`).flush({ id: 1, nombre: 'Central' });
    http.expectOne(`${API}/ventas/sucursal/1`).flush([ventaDeHoy(1, 'anulada', 189, '05:03')]);
    http.match((r) => r.url.includes('/catalogo/variantes/detalle')).forEach((r) => r.flush([]));
    fixture.detectChanges();

    expect(el.querySelector('.dash-kpi__valor')?.textContent).toContain('Bs 0.00');
    expect(el.querySelector('.dash-kpi__nota')?.textContent).toContain('0 tickets');
    expect(el.querySelector('.dash-kpi__nota--por-cobrar')).toBeNull();
    expect(el.querySelector('.dash-barras')).toBeNull();
    // Pero en "Últimas ventas" sí se ve, con su etiqueta.
    expect(el.querySelector('.dash-tabla .fs-chip')?.textContent?.trim()).toBe('Anulada');
  });

  it('las ventas entregadas también cuentan como vendidas y varias pendientes se suman en "Por cobrar"', () => {
    iniciarSesion(['cajero'], ['ventas.gestionar_sucursal']);
    const { fixture, el } = crear();
    http.expectOne(`${API}/empleados/yo`).flush({ id: 1, usuario_id: 1, sucursal_id: 1, activo: true });
    http.expectOne(`${API}/sucursales/1`).flush({ id: 1, nombre: 'Central' });
    http
      .expectOne(`${API}/ventas/sucursal/1`)
      .flush([
        ventaDeHoy(1, 'entregada', 40, '09:00'),
        ventaDeHoy(2, 'pagada', 60, '10:00'),
        ventaDeHoy(3, 'pendiente_pago', 10, '11:00'),
        ventaDeHoy(4, 'pendiente_pago', 20.5, '12:00'),
      ]);
    http.match((r) => r.url.includes('/catalogo/variantes/detalle')).forEach((r) => r.flush([]));
    fixture.detectChanges();

    expect(el.querySelector('.dash-kpi__valor')?.textContent).toContain('Bs 100.00');
    expect(el.querySelector('.dash-kpi__nota')?.textContent).toContain('2 tickets');
    expect(el.querySelector('.dash-kpi__nota--por-cobrar')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
      'Por cobrar: 2 ventas (Bs 30.50)',
    );
  });

  it('un rol sin ventas, inventario ni reservas (proveedor) ve un aviso claro y no un panel vacío', () => {
    iniciarSesion(['proveedor'], ['catalogo.ver']);
    const { fixture, el } = crear();
    http.expectOne(`${API}/empleados/yo`).flush({ id: 1, usuario_id: 1, sucursal_id: null, activo: true });
    fixture.detectChanges();

    const aviso = el.querySelector('.fs-aviso')?.textContent ?? '';
    expect(aviso).toContain('Tu rol no tiene indicadores en este resumen.');
    expect(aviso).not.toContain('No tienes una sucursal asignada');
    expect(el.querySelector('.dash-kpis')).toBeNull();
  });

  it('muestra el stock bajo con el total real de alertas', () => {
    iniciarSesion(['encargado'], ['inventario.ver']);
    const { fixture, el } = crear();
    http.expectOne(`${API}/empleados/yo`).flush({ id: 1, usuario_id: 1, sucursal_id: 1, activo: true });
    http.expectOne(`${API}/sucursales/1`).flush({ id: 1, nombre: 'Central' });
    const alertas = Array.from({ length: 6 }, (_, i) => ({
      producto_id: i + 1,
      producto: `Prenda ${i + 1}`,
      variante_id: i + 1,
      cantidad_disponible: 1,
      stock_minimo: 3,
    }));
    http.expectOne((r) => r.url.startsWith(`${API}/inventario/alertas`)).flush(alertas);
    http.match((r) => r.url.includes('/catalogo/variantes/detalle')).forEach((r) => r.flush([]));
    fixture.detectChanges();

    expect(el.querySelector('.dash-kpi__valor')?.textContent?.trim()).toBe('6');
    expect(el.querySelectorAll('.dash-lista__fila').length).toBe(4);
    expect(el.querySelector('.dash-lista__cantidad')?.textContent).toContain('1 u.');
    // Sin permiso de ventas no hay tabla de ventas.
    expect(el.querySelector('.dash-tabla')).toBeNull();
  });

  it('mientras no se conoce al usuario el título es "Hola" (sin coma ni nombre vacío)', () => {
    const { el } = crear();
    http.expectOne(`${API}/empleados/yo`);

    expect(el.querySelector('h1')?.textContent).toBe('Hola');
  });

  it('las ventas sin datos muestran estados vacíos: sin gráfico y "Todavía no hay ventas hoy."', () => {
    iniciarSesion(['cajero'], ['ventas.gestionar_sucursal']);
    const { fixture, el } = crear();
    http.expectOne(`${API}/empleados/yo`).flush({ id: 1, usuario_id: 1, sucursal_id: 1, activo: true });
    http.expectOne(`${API}/sucursales/1`).flush({ id: 1, nombre: 'Central' });
    http.expectOne(`${API}/ventas/sucursal/1`).flush([]);
    fixture.detectChanges();

    expect(el.querySelector('.dash-barras')).toBeNull();
    expect(el.querySelector('.dash-tabla .fs-estado-vacio')?.textContent).toContain('Todavía no hay ventas hoy.');
    expect(el.querySelector('.dash-kpi__valor')?.textContent).toContain('Bs 0.00');
  });

  it('el gráfico de barras tiene una alternativa textual con los valores', () => {
    iniciarSesion(['cajero'], ['ventas.gestionar_sucursal']);
    const { fixture, el } = crear();
    http.expectOne(`${API}/empleados/yo`).flush({ id: 1, usuario_id: 1, sucursal_id: 1, activo: true });
    http.expectOne(`${API}/sucursales/1`).flush({ id: 1, nombre: 'Central' });
    http.expectOne(`${API}/ventas/sucursal/1`).flush([ventaDeHoy(1, 'pagada', 100, '09:30'), ventaDeHoy(2, 'pagada', 50, '10:00')]);
    http
      .match((r) => r.url.includes('/catalogo/variantes/detalle'))
      .forEach((r) =>
        r.flush([
          { variante_id: 11, producto_id: 1, producto_nombre: 'Camisa Oxford', imagen_principal: null, talla_codigo: null, color_nombre: null },
        ]),
      );
    fixture.detectChanges();

    expect(el.querySelector('.dash-barras')?.getAttribute('aria-hidden')).toBe('true');
    const lista = el.querySelector('ul.sr-solo') as HTMLElement;
    expect(lista.getAttribute('aria-label')).toBe('Unidades vendidas hoy por prenda');
    expect(Array.from(lista.querySelectorAll('li')).map((li) => li.textContent?.trim())).toEqual([
      'Variante 12: 2',
      'Camisa Oxford: 1',
    ]);
  });

  it('las reservas de hoy muestran su cantidad por estado en texto', () => {
    iniciarSesion(['encargado'], ['reservas.gestionar_sucursal']);
    const { fixture, el } = crear();
    http.expectOne(`${API}/empleados/yo`).flush({ id: 1, usuario_id: 1, sucursal_id: 1, activo: true });
    http.expectOne(`${API}/sucursales/1`).flush({ id: 1, nombre: 'Central' });
    const hoy = new Date();
    const dia = `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, '0')}-${String(hoy.getDate()).padStart(2, '0')}`;
    http
      .expectOne(`${API}/reservas/sucursal/1`)
      .flush([
        { id: 1, estado: 'pendiente', fecha_visita: dia },
        { id: 2, estado: 'pendiente', fecha_visita: dia },
        { id: 3, estado: 'completada', fecha_visita: dia },
        { id: 4, estado: 'cancelada', fecha_visita: '2000-01-01' },
      ]);
    fixture.detectChanges();

    const pills = Array.from(el.querySelectorAll('.dash-pill')).map((p) => p.textContent?.replace(/\s+/g, ' ').trim());
    expect(pills).toEqual(['Pendientes 2', 'En prueba 0', 'Completadas 1', 'Canceladas 0']);
    expect(el.querySelector('.dash-apilada')?.getAttribute('aria-hidden')).toBe('true');
  });
});
