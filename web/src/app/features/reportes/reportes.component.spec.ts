import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ChartModule } from 'primeng/chart';
import { vi } from 'vitest';
import { environment } from '../../../environments/environment';
import { PlanService } from '../../core/plan.service';
import { ReportesComponent } from './reportes.component';

const API = environment.apiUrl;

const DASHBOARD = {
  desde: '2026-10-01',
  hasta: '2026-10-22',
  ventas_del_periodo: 48520,
  transacciones: 196,
  ticket_promedio: 247.55,
  margen_bruto: 12000,
  top_productos: [
    { producto_id: 1, producto: 'Polera básica', cantidad_vendida: 84, total_vendido: 5000 },
    { producto_id: 2, producto: 'Camisa Oxford', cantidad_vendida: 42, total_vendido: 9000 },
  ],
  ventas_por_canal: [],
  ventas_por_sucursal: [],
  valor_inventario_total: 48200,
  variantes_bajo_minimo: 9,
  reservas_por_estado: [],
  tasa_conversion_reservas: 0.62,
  uso_probador: [{ estado: 'completado', cantidad: 5 }],
};

describe('ReportesComponent', () => {
  let http: HttpTestingController;

  // PrimeNG Tabs observa su tamaño con ResizeObserver, que jsdom no trae.
  beforeAll(() => {
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver ??= class {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    };
  });

  function abrir() {
    TestBed.configureTestingModule({
      imports: [ReportesComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    // Chart.js necesita un canvas real: aquí solo se prueba la pantalla.
    TestBed.overrideComponent(ReportesComponent, {
      remove: { imports: [ChartModule] },
      add: { schemas: [NO_ERRORS_SCHEMA] },
    });
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(ReportesComponent);
    fixture.detectChanges();
    http.expectOne(`${API}/sucursales?pagina=1&tamanio=100`).flush([{ id: 1, nombre: 'Central' }]);
    http.expectOne(`${API}/categorias?pagina=1&tamanio=100`).flush([]);
    http.expectOne(`${API}/empleados/yo`).flush({ id: 1, sucursal_id: null });
    http.expectOne((r) => r.url === `${API}/reportes/dashboard`).flush(DASHBOARD);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  afterEach(() => http.match(() => true));

  it('muestra la caja de pregunta a la IA con micrófono y las cuatro pestañas', () => {
    const { el } = abrir();

    expect(el.querySelector('.fs-eyebrow')?.textContent).toBe('Análisis');
    expect(el.querySelector('.pregunta h2')?.textContent).toBe('Pregúntale a la IA');
    expect(el.querySelector('.pregunta [aria-label="Dictar la pregunta"]')).not.toBeNull();
    const pestanias = Array.from(el.querySelectorAll('.p-tab')).map((t) => t.textContent?.trim());
    expect(pestanias).toEqual(['Dashboard', 'Ventas', 'Inventario', 'Reservas']);
  });

  it('con un plan sin reportes con IA no se muestra "Pregúntale a la IA" (el servidor respondería 403)', () => {
    const { fixture, el } = abrir();
    expect(el.querySelector('.pregunta')).not.toBeNull();

    TestBed.inject(PlanService).suscripcion.set({
      plan_codigo: 'basico',
      plan_nombre: 'Básico',
      estado: 'activa',
      fecha_inicio: '2026-01-01',
      fecha_vencimiento: '2099-01-01',
      max_sucursales: 2,
      sucursales_activas: 1,
      funcionalidades: ['reportes_convencionales'],
    });
    fixture.detectChanges();

    expect(el.querySelector('.pregunta')).toBeNull();
    // Los reportes convencionales siguen ahí.
    expect(Array.from(el.querySelectorAll('.p-tab')).map((t) => t.textContent?.trim())).toEqual([
      'Dashboard',
      'Ventas',
      'Inventario',
      'Reservas',
    ]);
  });

  it('dibuja las siete tarjetas del dashboard con iconos y marca "bajo mínimo" como alerta', () => {
    const { el } = abrir();

    expect(el.querySelectorAll('.kpi').length).toBe(7);
    const valores = Array.from(el.querySelectorAll('.kpi__valor')).map((v) => v.textContent?.trim());
    expect(valores[0]).toBe('Bs 48,520.00');
    expect(valores[1]).toBe('196');
    expect(valores[5]).toBe('9');
    expect(valores[6]).toBe('62%');
    expect(el.querySelectorAll('.kpi__icono fs-icono').length).toBe(7);
    expect(el.querySelector('.kpi__valor--alerta')?.textContent?.trim()).toBe('9');
  });

  it('los productos más vendidos van en ranking con barra proporcional', () => {
    const { el } = abrir();

    const filas = el.querySelectorAll('.ranking li');
    expect(filas.length).toBe(2);
    expect(filas[0].textContent).toContain('Polera básica');
    expect((filas[0].querySelector('.ranking__barra div') as HTMLElement).style.width).toBe('100%');
    expect((filas[1].querySelector('.ranking__barra div') as HTMLElement).style.width).toBe('50%');
    expect(el.querySelector('.chips-fila .fs-chip--exito')?.textContent).toContain('Completadas: 5');
  });

  it('Preguntar envía el texto y muestra la respuesta de la IA', () => {
    const { fixture, el } = abrir();
    const entrada = el.querySelector('.pregunta-texto') as HTMLInputElement;
    entrada.value = '¿Cuánto vendimos esta semana?';
    entrada.dispatchEvent(new Event('input'));
    fixture.detectChanges();

    (el.querySelector('.btn-preguntar') as HTMLButtonElement).click();
    const peticion = http.expectOne((r) => r.method === 'POST' && r.url === `${API}/ia/reporte-voz`);
    expect(peticion.request.body).toEqual({ texto: '¿Cuánto vendimos esta semana?' });
    peticion.flush({
      respuesta: 'Esta semana vendiste Bs 12,230.00.',
      tipo_reporte: 'dashboard',
      filtros_aplicados: { desde: '2026-10-19', hasta: '2026-10-22', sucursal_id: null, categoria_id: null, canal: null },
    });
    http.expectOne((r) => r.url === `${API}/reportes/dashboard`).flush(DASHBOARD);
    fixture.detectChanges();

    expect(el.querySelector('.pregunta-respuesta')?.textContent).toContain('Esta semana vendiste');
  });

  it('Exportar CSV de ventas descarga un archivo con encabezados y filas', async () => {
    const { fixture, el } = abrir();
    (fixture.componentInstance as unknown as { cambiarPestania(v: string): void }).cambiarPestania('ventas');
    http.expectOne((r) => r.url === `${API}/reportes/ventas`).flush({
      resumen: { transacciones: 1, total_ventas: 289, ticket_promedio: 289, margen_bruto: 100 },
      top_productos: [],
      por_canal: [],
      por_sucursal: [],
      detalle: [
        {
          fecha: '2026-10-22T10:00:00',
          codigo: 'V-1',
          canal: 'presencial',
          sucursal: 'Central',
          producto: 'Camisa Oxford',
          categoria: 'Camisas',
          cantidad: 1,
          subtotal: 289,
          margen: 100,
        },
      ],
    });
    fixture.detectChanges();

    const blobs: Blob[] = [];
    const crearUrl = vi.fn((blob: Blob) => {
      blobs.push(blob);
      return 'blob:prueba';
    });
    (URL as unknown as { createObjectURL: unknown }).createObjectURL = crearUrl;
    const clic = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);

    const exportar = Array.from(el.querySelectorAll('p-tabpanel[value="ventas"] button')).find((b) =>
      b.textContent?.includes('Exportar CSV'),
    ) as HTMLButtonElement;
    exportar.click();

    expect(clic).toHaveBeenCalledTimes(1);
    expect(crearUrl).toHaveBeenCalledTimes(1);
    const csv = await blobs[0].text();
    expect(csv).toContain('"Fecha","Código","Canal","Sucursal","Producto","Categoría","Cantidad","Subtotal","Margen"');
    expect(csv).toContain('"V-1","presencial","Central","Camisa Oxford","Camisas","1","289","100"');
    clic.mockRestore();
  });
});
