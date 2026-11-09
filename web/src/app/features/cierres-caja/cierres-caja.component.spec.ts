import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, TestRequest, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { environment } from '../../../environments/environment';
import { AuthService } from '../../core/auth.service';
import { fechaLocalIso } from '../../core/date-utils';
import type { EstadoCajaSucursal, ResumenTurno, Turno, TurnoDetalle } from '../../core/models/caja.models';
import type { Reembolso } from '../../core/models/ventas.models';
import { CierresCajaComponent } from './cierres-caja.component';

const API = environment.apiUrl;
const URL_ESTADO = `${API}/caja/turnos/estado`;
const URL_LISTA = `${API}/caja/turnos`;

const HORA_MS = 3_600_000;

function turno(extra: Partial<Turno> = {}): Turno {
  return {
    id: 4,
    sucursal_id: 1,
    sucursal_nombre: 'Central',
    estado: 'cerrada',
    apertura_en: '2026-11-07T13:00:00Z',
    abierto_por_id: 5,
    abierto_por_nombre: 'Luis Paz',
    monto_inicial: '100.00',
    observacion_apertura: null,
    cierre_en: '2026-11-07T22:00:00Z',
    cerrado_por_id: 5,
    cerrado_por_nombre: 'Luis Paz',
    cierre_automatico: false,
    efectivo_contado: '250.00',
    diferencia: '0.00',
    pendientes_declarados: 0,
    observacion_cierre: null,
    conteo_en: null,
    conteo_por_nombre: null,
    observacion_conteo: null,
    conteo_hasta: null,
    monto_esperado: '250.00',
    resumen: null,
    ...extra,
  };
}

const RESUMEN: ResumenTurno = {
  ventas_efectivo: '180.00',
  cantidad_ventas: 3,
  reembolsos_efectivo: '30.00',
  ventas_otros_metodos: '75.00',
  ventas_online: '60.00',
  cantidad_ventas_online: 2,
  monto_esperado: '250.00',
};

function detalle(base: Turno, extra: Partial<TurnoDetalle> = {}): TurnoDetalle {
  return { ...base, ajuste_posterior: null, reembolsos: [], ...extra };
}

const REEMBOLSO: Reembolso = {
  id: 9,
  devolucion_id: 3,
  pago_id: 2,
  venta_id: 40,
  sucursal_id: 1,
  metodo: 'efectivo',
  monto: '30.00',
  monto_usd: null,
  estado: 'reembolsado',
  referencia_externa: null,
  motivo_fallo: null,
  creado_en: '2026-11-07T18:00:00Z',
  completado_en: '2026-11-07T18:00:00Z',
};

const CAJAS: EstadoCajaSucursal[] = [
  {
    sucursal_id: 1,
    sucursal_nombre: 'Central',
    turno: turno({ id: 7, estado: 'abierta', cierre_en: null, efectivo_contado: null, diferencia: null, monto_esperado: '320.50', resumen: RESUMEN }),
  },
  { sucursal_id: 2, sucursal_nombre: 'Equipetrol', turno: null },
];

function haceDias(dias: number): string {
  const fecha = new Date();
  fecha.setDate(fecha.getDate() - dias);
  return fechaLocalIso(fecha);
}

describe('CierresCajaComponent', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<CierresCajaComponent>;
  let el: HTMLElement;

  function montar(permisos: string[] = ['caja.supervisar', 'pagos.gestionar']): void {
    TestBed.configureTestingModule({
      imports: [CierresCajaComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: { tienePermiso: (p: string) => permisos.includes(p) } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(CierresCajaComponent);
    el = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
  }

  const estado = (): TestRequest => http.expectOne((r) => r.url === URL_ESTADO);
  const lista = (): TestRequest => http.expectOne((r) => r.url === URL_LISTA);

  /** Monta y responde las dos consultas iniciales. */
  function montarConDatos(cajas: EstadoCajaSucursal[] = CAJAS, turnos: Turno[] = [turno()]): void {
    montar();
    estado().flush(cajas);
    lista().flush(turnos);
    fixture.detectChanges();
  }

  const q = (selector: string) => el.querySelector(selector) as HTMLElement | null;
  const qq = (selector: string) => Array.from(el.querySelectorAll(selector)) as HTMLElement[];
  const texto = (nodo: Element | null | undefined) => (nodo?.textContent ?? '').replace(/\s+/g, ' ').trim();
  const filas = () => qq('tr.fila-turno');
  const boton = (estadoDe: string) => q(`[data-estado="${estadoDe}"]`) as HTMLButtonElement;

  function elegir(filtro: string, valor: unknown): void {
    const campo = fixture.debugElement.query(By.css(`[data-filtro="${filtro}"]`));
    expect(campo, `no existe el filtro ${filtro}`).not.toBeNull();
    campo.triggerEventHandler('ngModelChange', valor);
    fixture.detectChanges();
  }

  function escribir(selector: string, valor: string): void {
    const campo = q(selector) as HTMLInputElement;
    campo.value = valor;
    campo.dispatchEvent(new Event('input'));
    fixture.detectChanges();
  }

  async function estabilizar(): Promise<void> {
    await fixture.whenStable();
    fixture.detectChanges();
  }

  afterEach(() => http.match(() => true));

  describe('Cajas de hoy', () => {
    it('una tarjeta por sucursal: abierta con quién abrió, desde cuándo y el esperado en vivo; o sin turno', () => {
      montarConDatos();

      const tarjetas = qq('.tarjeta');
      expect(tarjetas).toHaveLength(2);

      const central = tarjetas[0];
      expect(texto(central.querySelector('h3'))).toBe('Central');
      expect(texto(central.querySelector('[data-estado="estado-caja"]'))).toBe('Abierta');
      expect(texto(central)).toContain('Abrió Luis Paz desde las');
      expect(texto(central.querySelector('[data-estado="esperado-en-vivo"]'))).toContain('Bs 320.50');

      const equipetrol = tarjetas[1];
      expect(texto(equipetrol.querySelector('[data-estado="estado-caja"]'))).toBe('Sin turno');
      expect(equipetrol.querySelector('[data-estado="esperado-en-vivo"]')).toBeNull();
      expect(texto(equipetrol)).toContain('Nadie abrió la caja hoy');
    });

    it('pide /caja/turnos/estado y muestra esqueletos mientras llega', () => {
      montar();
      expect(q('[data-estado="cargando-cajas"]')).not.toBeNull();
      expect(qq('.tarjeta')).toHaveLength(0);
      estado().flush(CAJAS);
      lista().flush([]);
      fixture.detectChanges();
      expect(q('[data-estado="cargando-cajas"]')).toBeNull();
    });

    it('sin sucursales dice que no hay cajas', () => {
      montarConDatos([], []);
      expect(q('[data-estado="sin-cajas"]')).not.toBeNull();
    });

    it('si falla ofrece Reintentar y vuelve a pedirlas', () => {
      montar();
      estado().flush(null, { status: 500, statusText: 'Server Error' });
      lista().flush([]);
      fixture.detectChanges();

      expect(q('[data-estado="error-cajas"]')?.textContent).toContain('No pudimos cargar las cajas de hoy');
      (q('[data-estado="error-cajas"] button') as HTMLButtonElement).click();
      estado().flush(CAJAS);
      fixture.detectChanges();
      expect(q('[data-estado="error-cajas"]')).toBeNull();
      expect(qq('.tarjeta')).toHaveLength(2);
    });

    it('"Ver turno" abre el detalle del turno abierto', () => {
      montarConDatos();
      (qq('[data-estado="ver-caja"]')[0] as HTMLButtonElement).click();
      const req = http.expectOne(`${API}/caja/turnos/7`);
      req.flush(detalle(CAJAS[0].turno!));
      fixture.detectChanges();
      expect(q('[data-estado="detalle-turno"]')).not.toBeNull();
    });
  });

  describe('historial', () => {
    it('pide los últimos 30 días, página 1 de 20, sin sucursal ni estado', () => {
      montar();
      estado().flush(CAJAS);
      const req = lista();

      expect(req.request.params.get('desde')).toBe(haceDias(30));
      expect(req.request.params.get('hasta')).toBe(haceDias(0));
      expect(req.request.params.get('pagina')).toBe('1');
      expect(req.request.params.get('tamanio')).toBe('20');
      expect(req.request.params.has('sucursal_id')).toBe(false);
      expect(req.request.params.has('estado')).toBe(false);
      expect(q('[data-estado="cargando"]')).not.toBeNull();
      req.flush([]);
    });

    it('la tabla muestra fecha, sucursal, abrió/cerró, inicial, esperado, contado, diferencia y estado', () => {
      montarConDatos(CAJAS, [turno({ diferencia: '-10.00', efectivo_contado: '240.00' })]);

      expect(filas()).toHaveLength(1);
      const celdas = Array.from(filas()[0].querySelectorAll('td')).map((td) => texto(td));
      expect(celdas[1]).toBe('Central');
      expect(celdas[2]).toBe('Abrió: Luis Paz Cerró: Luis Paz');
      expect(celdas[3]).toBe('Bs 100.00');
      expect(celdas[4]).toBe('Bs 250.00');
      expect(celdas[5]).toBe('Bs 240.00');
      expect(celdas[6]).toBe('Faltan Bs 10.00');
      expect(celdas[7]).toBe('Cerrada');
      expect(filas()[0].querySelector('[data-estado="diferencia"]')?.classList).toContain('fs-chip--error');
    });

    it('la diferencia es verde si cuadra y ámbar si sobra', () => {
      montarConDatos(CAJAS, [turno({ id: 1, diferencia: '0.00' }), turno({ id: 2, diferencia: '5.00' })]);

      const chips = qq('[data-estado="diferencia"]');
      expect(chips[0].classList).toContain('fs-chip--exito');
      expect(texto(chips[0])).toBe('Cuadra');
      expect(chips[1].classList).toContain('fs-chip--advertencia');
      expect(texto(chips[1])).toBe('Sobran Bs 5.00');
    });

    it('un cierre automático lleva la etiqueta "Cerrado sin conteo" hasta que se complete', () => {
      montarConDatos(CAJAS, [
        turno({
          id: 1,
          estado: 'cerrada_auto',
          cierre_automatico: true,
          cerrado_por_nombre: null,
          efectivo_contado: null,
          diferencia: null,
        }),
        turno({ id: 2, estado: 'cerrada_auto', cierre_automatico: true, conteo_en: '2026-11-08T10:00:00Z', conteo_por_nombre: 'Ana' }),
      ]);

      const sinConteo = filas()[0];
      expect(texto(sinConteo.querySelector('[data-estado="estado-turno"]'))).toBe('Cerrado sin conteo');
      expect(sinConteo.querySelector('[data-estado="estado-turno"]')?.classList).toContain('fs-chip--advertencia');
      expect(texto(sinConteo)).toContain('Cerró: automático');
      const celdas = Array.from(sinConteo.querySelectorAll('td')).map((td) => texto(td));
      expect(celdas[5]).toBe('—');
      expect(celdas[6]).toBe('—');

      expect(texto(filas()[1].querySelector('[data-estado="estado-turno"]'))).toBe('Cerrada (conteo completado)');
    });

    it('un turno abierto se muestra "Sin cerrar" y sin contado', () => {
      montarConDatos(CAJAS, [turno({ estado: 'abierta', cierre_en: null, cerrado_por_nombre: null, efectivo_contado: null, diferencia: null })]);
      expect(texto(filas()[0])).toContain('Sin cerrar');
      expect(texto(filas()[0].querySelector('[data-estado="estado-turno"]'))).toBe('Abierta');
    });

    it('sin turnos en el periodo dice que está vacío', () => {
      montarConDatos(CAJAS, []);
      expect(q('[data-estado="vacio"]')?.textContent).toContain('No hay turnos de caja en ese periodo');
    });

    it('si falla ofrece Reintentar', () => {
      montar();
      estado().flush(CAJAS);
      lista().flush(null, { status: 500, statusText: 'Server Error' });
      fixture.detectChanges();
      expect(q('[data-estado="error"]')?.textContent).toContain('No pudimos cargar los cierres de caja');

      boton('reintentar').click();
      lista().flush([turno()]);
      fixture.detectChanges();
      expect(q('[data-estado="error"]')).toBeNull();
      expect(filas()).toHaveLength(1);
    });
  });

  describe('filtros', () => {
    it('el filtro de sucursal solo se ofrece a quien ve varias', () => {
      montarConDatos();
      expect(q('[data-filtro="sucursal"]')).not.toBeNull();
      TestBed.resetTestingModule();

      montarConDatos([CAJAS[0]]);
      expect(q('[data-filtro="sucursal"]')).toBeNull();
      expect(q('[data-filtro="estado"]')).not.toBeNull();
    });

    it('cada filtro vuelve a la página 1 y pide con sus parámetros', () => {
      montarConDatos();

      elegir('sucursal', 2);
      let req = lista();
      expect(req.request.params.get('sucursal_id')).toBe('2');
      req.flush([]);
      fixture.detectChanges();

      elegir('estado', 'cerrada_auto');
      req = lista();
      expect(req.request.params.get('sucursal_id')).toBe('2');
      expect(req.request.params.get('estado')).toBe('cerrada_auto');
      req.flush([]);
      fixture.detectChanges();

      elegir('desde', new Date(2026, 10, 1));
      req = lista();
      expect(req.request.params.get('desde')).toBe('2026-11-01');
      req.flush([]);
      fixture.detectChanges();

      elegir('hasta', new Date(2026, 10, 7));
      req = lista();
      expect(req.request.params.get('hasta')).toBe('2026-11-07');
      expect(req.request.params.get('pagina')).toBe('1');
      req.flush([]);
    });

    it('un rango al revés avisa y no consulta', () => {
      montarConDatos();
      elegir('desde', new Date(2026, 10, 9));
      elegir('hasta', new Date(2026, 10, 1));

      http.expectNone((r) => r.url === URL_LISTA);
      expect(q('[data-estado="rango"]')?.textContent).toContain('La fecha inicial no puede ser posterior a la final.');
    });

    it('con una página llena se puede pasar a la siguiente y volver', () => {
      const veinte = Array.from({ length: 20 }, (_, i) => turno({ id: i + 1 }));
      montarConDatos(CAJAS, veinte);

      const siguiente = el.querySelector('button[aria-label="Página siguiente"]') as HTMLButtonElement;
      expect(siguiente.disabled).toBe(false);
      siguiente.click();
      const req = lista();
      expect(req.request.params.get('pagina')).toBe('2');
      req.flush([turno({ id: 21 })]);
      fixture.detectChanges();
      expect(texto(q('[data-estado="resumen-paginacion"]'))).toBe('Página 2');
      expect((el.querySelector('button[aria-label="Página siguiente"]') as HTMLButtonElement).disabled).toBe(true);

      (el.querySelector('button[aria-label="Página anterior"]') as HTMLButtonElement).click();
      expect(lista().request.params.get('pagina')).toBe('1');
    });

    it('una página corta no ofrece la siguiente', () => {
      montarConDatos();
      expect((el.querySelector('button[aria-label="Página siguiente"]') as HTMLButtonElement).disabled).toBe(true);
    });
  });

  describe('detalle de un turno', () => {
    function abrirDetalle(base: Turno, extra: Partial<TurnoDetalle> = {}): void {
      montarConDatos(CAJAS, [base]);
      boton('ver-detalle').click();
      http.expectOne(`${API}/caja/turnos/${base.id}`).flush(detalle(base, extra));
      fixture.detectChanges();
    }

    it('resumen: efectivo cobrado, reembolsos en efectivo y lo informativo rotulado como tal', () => {
      abrirDetalle(turno({ resumen: RESUMEN, observacion_cierre: 'Faltó sencillo' }));

      // Cada término y su valor, separados por un espacio.
      const filasDe = (selector: string) =>
        Array.from(q(selector)?.querySelectorAll('dt, dd') ?? [])
          .map((n) => texto(n))
          .join(' ');
      const resumen = filasDe('[data-estado="resumen-turno"]');
      expect(resumen).toContain('Monto inicial Bs 100.00');
      expect(resumen).toContain('Efectivo cobrado (3 ventas) + Bs 180.00');
      expect(resumen).toContain('Reembolsos en efectivo - Bs 30.00');
      expect(resumen).toContain('Efectivo esperado Bs 250.00');
      expect(texto(q('app-resumen-turno'))).toContain('Solo informativo, no entra al cajón');
      const informativo = filasDe('[data-estado="resumen-informativo"]');
      expect(informativo).toContain('QR, tarjeta y transferencia Bs 75.00');
      expect(informativo).toContain('Ventas online del día (2) Bs 60.00');
      expect(texto(q('[data-estado="detalle-turno"]'))).toContain('Faltó sencillo');
    });

    it('muestra quién abrió y cerró, el contado y los reembolsos del turno', () => {
      abrirDetalle(turno({ resumen: RESUMEN, observacion_apertura: 'Con sencillo' }), { reembolsos: [REEMBOLSO] });

      const detalleTexto = texto(q('[data-estado="detalle-turno"]'));
      expect(detalleTexto).toContain('Abrió Luis Paz el');
      expect(detalleTexto).toContain('Con sencillo');
      expect(detalleTexto).toContain('Cerró Luis Paz el');
      expect(detalleTexto).toContain('Efectivo contado: Bs 250.00');
      expect(detalleTexto).toContain('Reembolsos del turno');
      expect(q('[data-estado="detalle-turno"] app-reembolsos')).not.toBeNull();
    });

    it('el ajuste posterior positivo dice que llegaron ventas sincronizadas tarde', () => {
      abrirDetalle(turno({ resumen: RESUMEN }), { ajuste_posterior: '45.00' });
      expect(texto(q('[data-estado="ajuste-posterior"]'))).toContain('Llegaron ventas sincronizadas tarde');
      expect(texto(q('[data-estado="ajuste-posterior"]'))).toContain('Bs 45.00');
    });

    it('el ajuste posterior negativo dice que se devolvió algo después', () => {
      abrirDetalle(turno({ resumen: RESUMEN }), { ajuste_posterior: '-12.50' });
      expect(texto(q('[data-estado="ajuste-posterior"]'))).toContain('Se devolvió algo después del cierre');
      expect(texto(q('[data-estado="ajuste-posterior"]'))).toContain('Bs 12.50');
    });

    it('sin ajuste (0 o nulo) no dice nada', () => {
      abrirDetalle(turno({ resumen: RESUMEN }), { ajuste_posterior: '0.00' });
      expect(q('[data-estado="ajuste-posterior"]')).toBeNull();
    });

    it('avisa los pendientes que el cajero declaró al cerrar', () => {
      abrirDetalle(turno({ resumen: RESUMEN, pendientes_declarados: 3 }));
      expect(texto(q('[data-estado="pendientes-declarados"]'))).toContain('Al cerrar quedaban 3 operaciones sin sincronizar');
    });

    it('si el detalle falla se explica y se puede reintentar', () => {
      montarConDatos();
      boton('ver-detalle').click();
      http.expectOne(`${API}/caja/turnos/4`).flush(null, { status: 500, statusText: 'Server Error' });
      fixture.detectChanges();

      expect(q('[data-estado="error-detalle"]')?.textContent).toContain('No pudimos cargar el detalle del turno');
      (q('[data-estado="error-detalle"] button') as HTMLButtonElement).click();
      http.expectOne(`${API}/caja/turnos/4`).flush(detalle(turno()));
      fixture.detectChanges();
      expect(q('[data-estado="error-detalle"]')).toBeNull();
    });
  });

  describe('cerrar el turno de otra persona', () => {
    const abierta = () =>
      turno({
        id: 8,
        estado: 'abierta',
        cierre_en: null,
        cerrado_por_nombre: null,
        efectivo_contado: null,
        diferencia: null,
        monto_esperado: '250.00',
        resumen: RESUMEN,
      });

    it('el supervisor sí ve el esperado, cuenta y el listado se refresca', async () => {
      montarConDatos(CAJAS, [abierta()]);
      boton('ver-detalle').click();
      http.expectOne(`${API}/caja/turnos/8`).flush(detalle(abierta()));
      fixture.detectChanges();

      boton('cerrar-turno-ajeno').click();
      await estabilizar();
      expect(q('[data-estado="esperado-visible"]')?.textContent).toContain('Bs 250.00');

      escribir('[data-estado="efectivo-contado"]', '250');
      boton('confirmar').click();
      const req = http.expectOne((r) => r.method === 'POST' && r.url === `${API}/caja/turnos/8/cerrar`);
      expect(req.request.body).toEqual({ efectivo_contado: '250.00', pendientes_sin_sincronizar: 0 });
      req.flush(turno({ id: 8, estado: 'cerrada', efectivo_contado: '250.00', diferencia: '0.00', monto_esperado: '250.00', resumen: RESUMEN }));
      await estabilizar();

      // Se refrescan tarjetas, tabla y detalle.
      estado().flush(CAJAS);
      lista().flush([turno({ id: 8 })]);
      http.expectOne(`${API}/caja/turnos/8`).flush(detalle(turno({ id: 8 })));
      await estabilizar();

      expect(q('[data-estado="cifra-diferencia"]')?.textContent).toContain('Cuadra');
      // El detalle ya no ofrece cerrar.
      expect(q('[data-estado="cerrar-turno-ajeno"]')).toBeNull();
    });
  });

  describe('completar el conteo de un cierre automático', () => {
    const auto = (extra: Partial<Turno> = {}) =>
      turno({
        id: 11,
        estado: 'cerrada_auto',
        cierre_automatico: true,
        cerrado_por_nombre: null,
        efectivo_contado: null,
        diferencia: null,
        monto_esperado: '250.00',
        resumen: RESUMEN,
        conteo_hasta: new Date(Date.now() + 30 * HORA_MS).toISOString(),
        ...extra,
      });

    function abrirDetalle(base: Turno): void {
      montarConDatos(CAJAS, [base]);
      boton('ver-detalle').click();
      http.expectOne(`${API}/caja/turnos/${base.id}`).flush(detalle(base));
      fixture.detectChanges();
    }

    it('con plazo vigente ofrece "Completar conteo", muestra la fecha límite y exige observación', async () => {
      abrirDetalle(auto());

      expect(q('[data-estado="plazo-conteo"]')?.textContent).toContain('Puedes completar el conteo hasta el');
      expect(texto(q('[data-estado="detalle-turno"]'))).toContain('Se cerró solo al terminar el día');
      boton('completar-conteo').click();
      await estabilizar();

      expect(q('p-dialog [data-estado="esperado-visible"]')?.textContent).toContain('Bs 250.00');
      escribir('[data-estado="efectivo-contado"]', '245');
      // Sin observación (3 a 300 caracteres) no se puede guardar.
      expect(boton('confirmar').disabled).toBe(true);
      escribir('[data-estado="observacion"]', 'ab');
      expect(boton('confirmar').disabled).toBe(true);
      escribir('[data-estado="observacion"]', 'Contado a la mañana');
      expect(boton('confirmar').disabled).toBe(false);

      boton('confirmar').click();
      const req = http.expectOne((r) => r.method === 'POST' && r.url === `${API}/caja/turnos/11/completar-conteo`);
      expect(req.request.body).toEqual({ efectivo_contado: '245.00', observacion: 'Contado a la mañana' });
      req.flush(
        auto({
          efectivo_contado: '245.00',
          diferencia: '-5.00',
          conteo_en: new Date().toISOString(),
          conteo_por_nombre: 'Ana',
          observacion_conteo: 'Contado a la mañana',
        }),
      );
      await estabilizar();

      expect(q('[data-estado="cifra-diferencia"]')?.textContent).toContain('Faltan Bs 5.00');
      estado().flush(CAJAS);
      lista().flush([auto({ conteo_en: new Date().toISOString(), efectivo_contado: '245.00', diferencia: '-5.00' })]);
      http.expectOne(`${API}/caja/turnos/11`).flush(detalle(auto({ conteo_en: new Date().toISOString(), conteo_por_nombre: 'Ana' })));
      await estabilizar();
    });

    it('un error del servidor (conteo ya registrado) se explica en el diálogo', async () => {
      abrirDetalle(auto());
      boton('completar-conteo').click();
      await estabilizar();
      escribir('[data-estado="efectivo-contado"]', '245');
      escribir('[data-estado="observacion"]', 'Contado a la mañana');
      boton('confirmar').click();
      http
        .expectOne((r) => r.method === 'POST' && r.url === `${API}/caja/turnos/11/completar-conteo`)
        .flush({ detail: 'conteo_ya_registrado', codigo: 'conteo_ya_registrado', mensaje: 'x' }, { status: 409, statusText: 'Conflict' });
      await estabilizar();

      expect(q('[data-estado="error-conteo"]')?.textContent).toContain('ya se registró');
    });

    it('con el plazo vencido no se puede completar y se dice por qué', () => {
      abrirDetalle(auto({ conteo_hasta: new Date(Date.now() - HORA_MS).toISOString() }));

      expect(q('[data-estado="completar-conteo"]')).toBeNull();
      expect(q('[data-estado="conteo-vencido"]')?.textContent).toContain('Pasó el plazo para completar el conteo');
    });

    it('con el conteo ya hecho no se ofrece de nuevo', () => {
      abrirDetalle(auto({ conteo_en: '2026-11-08T10:00:00Z', conteo_por_nombre: 'Ana', efectivo_contado: '250.00', diferencia: '0.00' }));

      expect(q('[data-estado="completar-conteo"]')).toBeNull();
      expect(q('[data-estado="conteo-vencido"]')).toBeNull();
      expect(texto(q('[data-estado="detalle-turno"]'))).toContain('Ana completó el conteo el');
    });

    it('un turno cerrado normalmente no ofrece ninguna acción', () => {
      abrirDetalle(turno({ resumen: RESUMEN }));

      expect(q('[data-estado="completar-conteo"]')).toBeNull();
      expect(q('[data-estado="cerrar-turno-ajeno"]')).toBeNull();
    });
  });
});
