import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { PlanPublico } from '../../../core/models/plan.models';
import { PlanesComparativoComponent } from './planes-comparativo.component';

/** Los tres planes reales de hoy, tal como los entrega GET /public/planes. */
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
const ESTANDAR: PlanPublico = {
  ...BASICO,
  codigo: 'estandar',
  nombre: 'Estándar',
  max_sucursales: 5,
  max_copias_historial: 6,
  plazo_cambio_horas_defecto: 48,
  precio_mensual_bs: '290.00',
  reportes_ia: true,
};
const PROFESIONAL: PlanPublico = {
  ...ESTANDAR,
  codigo: 'profesional',
  nombre: 'Profesional',
  max_sucursales: 10,
  max_copias_historial: 10,
  plazo_cambio_horas_defecto: 72,
  precio_mensual_bs: '590.00',
  analitica_ml: true,
};

describe('PlanesComparativoComponent', () => {
  let fixture: ComponentFixture<PlanesComparativoComponent>;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
  });

  function mostrar(planes: PlanPublico[]): void {
    fixture = TestBed.createComponent(PlanesComparativoComponent);
    fixture.componentRef.setInput('planes', planes);
    fixture.detectChanges();
  }

  function html(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function tarjeta(nombre: string): HTMLElement {
    const encontrada = Array.from(html().querySelectorAll<HTMLElement>('.plan')).find(
      (t) => t.querySelector('.plan__nombre')?.textContent?.trim() === nombre,
    );
    expect(encontrada, `tarjeta ${nombre}`).toBeDefined();
    return encontrada!;
  }

  function filas(nombre: string): string[] {
    return Array.from(tarjeta(nombre).querySelectorAll('.plan__fila')).map((f) =>
      (f.textContent ?? '').replace(/\s+/g, ' ').trim(),
    );
  }

  it('con los tres planes reales: una tarjeta por plan, en el orden recibido', () => {
    mostrar([BASICO, ESTANDAR, PROFESIONAL]);

    const nombres = Array.from(html().querySelectorAll('.plan__nombre')).map((n) => n.textContent?.trim());
    expect(nombres).toEqual(['Básico', 'Estándar', 'Profesional']);
  });

  it('la línea "Todos los planes incluyen" trae lo común, con las etiquetas de FUNCIONES_PLAN', () => {
    mostrar([BASICO, ESTANDAR, PROFESIONAL]);

    const comunes = html().querySelector('.planes-comunes')?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
    expect(comunes).toContain('Todos los planes incluyen:');
    for (const etiqueta of ['Gestión de productos', 'Gestión de ventas', 'Reservas', 'Reportes', 'Operación sin conexión']) {
      expect(comunes).toContain(etiqueta);
    }
    // Lo que cambia entre planes no va en la línea común.
    expect(comunes).not.toContain('Reportes con IA');
    expect(comunes).not.toContain('Machine Learning');
    expect(comunes).not.toContain('Copias de seguridad');
  });

  it('cada tarjeta muestra solo lo que cambia: sucursales, plazo, copias y las funciones que varían', () => {
    mostrar([BASICO, ESTANDAR, PROFESIONAL]);

    expect(filas('Básico')).toEqual([
      'Hasta 2 sucursales activas',
      'Plazo de cambio: 24 h',
      'Copias de seguridad: guarda 3',
      'No incluye: Reportes con IA',
      'No incluye: Analítica con Machine Learning',
    ]);
    expect(filas('Estándar')).toEqual([
      'Hasta 5 sucursales activas',
      'Plazo de cambio: 48 h',
      'Copias de seguridad: guarda 6',
      'Reportes con IA',
      'No incluye: Analítica con Machine Learning',
    ]);
    expect(filas('Profesional')).toEqual([
      'Hasta 10 sucursales activas',
      'Plazo de cambio: 72 h',
      'Copias de seguridad: guarda 10',
      'Reportes con IA',
      'Analítica con Machine Learning',
    ]);
  });

  it('lo no incluido lleva guion y el texto oculto "No incluye:" para el lector de pantalla', () => {
    mostrar([BASICO, ESTANDAR, PROFESIONAL]);

    const noIncluidas = tarjeta('Básico').querySelectorAll('.plan__fila--no');
    expect(noIncluidas.length).toBe(2);
    noIncluidas.forEach((fila) => {
      expect(fila.querySelector('.sr-only')?.textContent).toContain('No incluye:');
      expect(fila.querySelector('fs-icono path')?.getAttribute('d')).toBe('M5 12h14');
    });
    // Lo incluido lleva check y ningún texto oculto.
    const incluida = tarjeta('Profesional').querySelector('.plan__fila')!;
    expect(incluida.querySelector('.sr-only')).toBeNull();
    expect(incluida.querySelector('fs-icono path')?.getAttribute('d')).toBe('M5 12l5 5 9-10');
    expect(tarjeta('Profesional').querySelector('.plan__fila--no')).toBeNull();
  });

  it('resalta como "plan completo" solo el plan con más sucursales', () => {
    mostrar([BASICO, ESTANDAR, PROFESIONAL]);

    expect(html().querySelectorAll('.plan--completo').length).toBe(1);
    expect(tarjeta('Profesional').classList).toContain('plan--completo');
    expect(tarjeta('Profesional').textContent).toContain('Plan completo');
    expect(tarjeta('Básico').textContent).not.toContain('Plan completo');
  });

  it('con dos planes también funciona', () => {
    mostrar([BASICO, PROFESIONAL]);

    expect(html().querySelectorAll('.plan').length).toBe(2);
    expect(filas('Básico')).toContain('No incluye: Reportes con IA');
    expect(filas('Profesional')).toContain('Reportes con IA');
    expect(tarjeta('Profesional').classList).toContain('plan--completo');
  });

  it('con cinco planes funciona y no repite lo común', () => {
    const cinco: PlanPublico[] = [
      BASICO,
      { ...BASICO, codigo: 'p2', nombre: 'Plan 2', max_sucursales: 3 },
      ESTANDAR,
      { ...ESTANDAR, codigo: 'p4', nombre: 'Plan 4', max_sucursales: 7 },
      PROFESIONAL,
    ];
    mostrar(cinco);

    expect(html().querySelectorAll('.plan').length).toBe(5);
    expect(html().querySelectorAll('.plan--completo').length).toBe(1);
    expect(filas('Plan 2')[0]).toBe('Hasta 3 sucursales activas');
    expect(html().querySelectorAll('.planes-comunes').length).toBe(1);
  });

  it('un plan sin copias lo dice con guion; si ninguno las tiene, no hay fila de copias', () => {
    mostrar([{ ...BASICO, copias_seguridad: false }, PROFESIONAL]);
    expect(filas('Básico')).toContain('No incluye: Copias de seguridad');
    expect(filas('Profesional')).toContain('Copias de seguridad: guarda 10');

    mostrar([
      { ...BASICO, copias_seguridad: false },
      { ...PROFESIONAL, copias_seguridad: false },
    ]);
    expect(html().textContent).not.toContain('Copias de seguridad');
  });

  it('con un solo plan no resalta ninguno; con empate en sucursales tampoco', () => {
    mostrar([BASICO]);
    expect(html().querySelectorAll('.plan--completo').length).toBe(0);

    mostrar([BASICO, { ...BASICO, codigo: 'otro', nombre: 'Otro' }]);
    expect(html().querySelectorAll('.plan--completo').length).toBe(0);
  });

  it('sin planes no pinta tarjetas ni la línea común', () => {
    mostrar([]);
    expect(html().querySelectorAll('.plan').length).toBe(0);
    expect(html().querySelector('.planes-comunes')).toBeNull();
  });

  it('cada plan muestra su precio por mes en bolivianos, sin dólares ni cifras de relleno', () => {
    mostrar([BASICO, ESTANDAR, PROFESIONAL]);

    const precios = Array.from(html().querySelectorAll('.plan__precio')).map((p) =>
      (p.textContent ?? '').replace(/\s+/g, ' ').trim(),
    );
    expect(precios).toEqual(['Bs 120 al mes', 'Bs 290 al mes', 'Bs 590 al mes']);
    expect(html().textContent ?? '').not.toMatch(/\$|USD|\[N\]|\[precio\]/i);
  });

  it('"Elegir plan" lleva a /contratar con el código del plan, y es el único botón por tarjeta', () => {
    mostrar([BASICO, ESTANDAR, PROFESIONAL]);

    const botones = Array.from(html().querySelectorAll<HTMLAnchorElement>('.plan__elegir'));
    expect(botones.map((b) => b.getAttribute('href'))).toEqual([
      '/contratar?plan=basico',
      '/contratar?plan=estandar',
      '/contratar?plan=profesional',
    ]);
    expect(botones.every((b) => b.textContent?.trim() === 'Elegir plan')).toBe(true);
    expect(botones[1].getAttribute('aria-label')).toBe('Elegir plan Estándar, Bs 290 al mes');
    // La prueba gratis va una sola vez, en el inicio de la portada: aquí no se repite.
    expect(html().textContent ?? '').not.toMatch(/gratis|prueba/i);
    for (const tarjeta of Array.from(html().querySelectorAll('.plan'))) {
      expect(tarjeta.querySelectorAll('a, button').length).toBe(1);
    }
  });

  it('el plan completo lleva el botón de acento; los demás, contorno (oscuro) o secundario (claro)', () => {
    mostrar([BASICO, PROFESIONAL]);
    expect(tarjeta('Profesional').querySelector('.plan__elegir')?.classList).toContain('fs-btn--acento');
    expect(tarjeta('Básico').querySelector('.plan__elegir')?.classList).toContain('fs-btn--secundario');

    fixture.componentRef.setInput('variante', 'oscuro');
    fixture.detectChanges();
    expect(tarjeta('Profesional').querySelector('.plan__elegir')?.classList).toContain('fs-btn--acento');
    expect(tarjeta('Básico').querySelector('.plan__elegir')?.classList).toContain('fs-btn--contorno');
  });

  it('un plan sin precio o con precio 0 dice "Precio a consultar" y no se puede elegir', () => {
    mostrar([
      { ...BASICO, precio_mensual_bs: null },
      { ...ESTANDAR, precio_mensual_bs: '0.00' },
      PROFESIONAL,
    ]);

    expect(tarjeta('Básico').textContent).toContain('Precio a consultar');
    expect(tarjeta('Básico').querySelector('.plan__elegir')).toBeNull();
    expect(tarjeta('Estándar').textContent).toContain('Precio a consultar');
    expect(tarjeta('Estándar').querySelector('.plan__elegir')).toBeNull();
    expect(tarjeta('Profesional').querySelector('.plan__elegir')).not.toBeNull();
  });

  it('los precios con decimales o miles se muestran con formato de Bolivia', () => {
    mostrar([
      { ...BASICO, precio_mensual_bs: '99.50' },
      { ...PROFESIONAL, precio_mensual_bs: '1250.00' },
    ]);
    expect(tarjeta('Básico').querySelector('.plan__monto')?.textContent?.trim()).toBe('Bs 99,50');
    expect(tarjeta('Profesional').querySelector('.plan__monto')?.textContent?.trim()).toBe('Bs 1.250');
  });

  it('la variante es clara por omisión y "oscuro" agrega la clase para ir sobre la escena 3D', () => {
    mostrar([BASICO, PROFESIONAL]);
    expect(html().classList.contains('planes--oscuro')).toBe(false);

    fixture.componentRef.setInput('variante', 'oscuro');
    fixture.detectChanges();
    expect(html().classList.contains('planes--oscuro')).toBe(true);
    // El contenido es el mismo.
    expect(html().querySelectorAll('.plan').length).toBe(2);
  });
});
