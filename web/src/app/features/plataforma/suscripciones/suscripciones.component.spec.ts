import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ConfirmationService, MessageService } from 'primeng/api';
import { environment } from '../../../../environments/environment';
import { fechaLocalIso } from '../../../core/date-utils';
import {
  EmpresaPlataforma,
  PlanPlataforma,
  SuscripcionPlataforma,
  severidadEstadoSuscripcion,
} from '../../../core/models/plataforma.models';
import { hoyLocal, sumarDias, sumarMeses } from '../data/fechas-plataforma';
import {
  OpcionRenovacion,
  SuscripcionesComponent,
  accionesPermitidas,
  baseDeRenovacion,
  nuevoVencimiento,
} from './suscripciones.component';

const BASE = `${environment.apiUrl}/plataforma`;

function enDias(dias: number): string {
  return fechaLocalIso(sumarDias(hoyLocal(), dias));
}

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

function empresa(id: number, nombre: string): EmpresaPlataforma {
  return {
    id,
    codigo: nombre.toLowerCase(),
    nombre,
    logo_url: null,
    color_acento: null,
    activo: true,
    plan_codigo: 'basico',
    suscripcion_estado: 'activa',
    fecha_inicio: enDias(-10),
    fecha_vencimiento: enDias(20),
    administrador_email: null,
  };
}

function suscripcion(id: number, estado: string, sobrescribir: Partial<SuscripcionPlataforma> = {}): SuscripcionPlataforma {
  return {
    id,
    empresa_id: id,
    plan_codigo: 'basico',
    plan_nombre: 'Básico',
    estado,
    estado_efectivo: estado,
    fecha_inicio: enDias(-30),
    fecha_vencimiento: enDias(15),
    creado_en: null,
    ...sobrescribir,
  };
}

interface Interno {
  filas(): { suscripcion: SuscripcionPlataforma; empresa: string; restante: string; acciones: ReturnType<typeof accionesPermitidas> }[];
  formularioPlan: {
    invalid: boolean;
    controls: Record<string, { setValue(v: unknown): void; valid: boolean }>;
  };
  opcionesPlanDialogo(): { value: string }[];
  dialogoPlanVisible(): boolean;
  dialogoRenovarVisible(): boolean;
  dialogoHistorialVisible(): boolean;
  opcionRenovar: { set(v: OpcionRenovacion): void };
  fechaLibre: { set(v: Date | null): void };
  fechaRenovada(): Date | null;
  renovacionValida(): boolean;
  filtroPlan: { set(v: string | null): void };
  abrirCambiarPlan(s: SuscripcionPlataforma): void;
  abrirAsignarPlan(s: SuscripcionPlataforma): void;
  guardarPlan(): void;
  abrirRenovar(s: SuscripcionPlataforma): void;
  guardarRenovacion(): void;
  reactivar(s: SuscripcionPlataforma): void;
  pedirSuspender(s: SuscripcionPlataforma): void;
  pedirCancelar(s: SuscripcionPlataforma): void;
  abrirHistorial(s: SuscripcionPlataforma): void;
  cambiarFiltroEmpresa(id: number | null): void;
  cambiarFiltroEstado(estado: 'activa' | null): void;
}

describe('accionesPermitidas', () => {
  const hoy = new Date(2026, 9, 22);

  it('activa: cambiar plan, renovar, suspender y cancelar', () => {
    expect(accionesPermitidas({ estado_efectivo: 'activa', fecha_vencimiento: '2026-11-30' }, true, hoy)).toEqual({
      cambiarPlan: true,
      renovar: true,
      suspender: true,
      reactivar: false,
      cancelar: true,
      asignarPlan: false,
    });
  });

  it('vencida: renovar, cambiar plan y cancelar; no se reactiva ni se suspende', () => {
    expect(accionesPermitidas({ estado_efectivo: 'vencida', fecha_vencimiento: '2026-10-01' }, true, hoy)).toEqual({
      cambiarPlan: true,
      renovar: true,
      suspender: false,
      reactivar: false,
      cancelar: true,
      asignarPlan: false,
    });
  });

  it('suspendida vigente por fecha: reactivar y cancelar', () => {
    expect(accionesPermitidas({ estado_efectivo: 'suspendida', fecha_vencimiento: '2026-10-22' }, true, hoy)).toEqual({
      cambiarPlan: false,
      renovar: false,
      suspender: false,
      reactivar: true,
      cancelar: true,
      asignarPlan: false,
    });
  });

  it('suspendida con la fecha pasada: no se reactiva (el backend pide renovar primero)', () => {
    const acciones = accionesPermitidas({ estado_efectivo: 'suspendida', fecha_vencimiento: '2026-10-21' }, true, hoy);
    expect(acciones.reactivar).toBe(false);
    expect(acciones.renovar).toBe(true);
    expect(acciones.cancelar).toBe(true);
  });

  it('cancelada: solo asignar plan, y únicamente si la empresa no tiene otra vigente', () => {
    const base = { estado_efectivo: 'cancelada', fecha_vencimiento: '2026-10-01' };
    expect(accionesPermitidas(base, false, hoy)).toEqual({
      cambiarPlan: false,
      renovar: false,
      suspender: false,
      reactivar: false,
      cancelar: false,
      asignarPlan: true,
    });
    expect(accionesPermitidas(base, true, hoy).asignarPlan).toBe(false);
  });

  it('un estado desconocido no habilita nada', () => {
    const acciones = accionesPermitidas({ estado_efectivo: 'rara', fecha_vencimiento: '2026-10-22' }, false, hoy);
    expect(Object.values(acciones).every((v) => v === false)).toBe(true);
  });
});

describe('fechas de renovación', () => {
  const hoy = new Date(2026, 9, 22);

  it('cuenta desde el vencimiento si es futuro y desde hoy si ya venció', () => {
    expect(fechaLocalIso(baseDeRenovacion(new Date(2026, 11, 15), hoy))).toBe('2026-12-15');
    expect(fechaLocalIso(baseDeRenovacion(new Date(2026, 9, 1), hoy))).toBe('2026-10-22');
    expect(fechaLocalIso(baseDeRenovacion(new Date(2026, 9, 22), hoy))).toBe('2026-10-22');
  });

  it('+1 mes, +3 meses y +1 año', () => {
    const vence = new Date(2026, 11, 15);
    expect(fechaLocalIso(nuevoVencimiento('1m', vence, hoy))).toBe('2027-01-15');
    expect(fechaLocalIso(nuevoVencimiento('3m', vence, hoy))).toBe('2027-03-15');
    expect(fechaLocalIso(nuevoVencimiento('1a', vence, hoy))).toBe('2027-12-15');
    // Vencida: desde hoy.
    expect(fechaLocalIso(nuevoVencimiento('1m', new Date(2026, 8, 1), hoy))).toBe('2026-11-22');
  });

  it('sumar meses no desborda el fin de mes', () => {
    expect(fechaLocalIso(sumarMeses(new Date(2027, 0, 31), 1))).toBe('2027-02-28');
    expect(fechaLocalIso(sumarMeses(new Date(2028, 0, 31), 1))).toBe('2028-02-29');
    expect(fechaLocalIso(sumarMeses(new Date(2026, 10, 30), 3))).toBe('2027-02-28');
  });
});

describe('colores de estado', () => {
  it('activa verde, vencida roja, suspendida ámbar, cancelada gris', () => {
    expect(severidadEstadoSuscripcion('activa')).toBe('success');
    expect(severidadEstadoSuscripcion('vencida')).toBe('danger');
    expect(severidadEstadoSuscripcion('suspendida')).toBe('warn');
    expect(severidadEstadoSuscripcion('cancelada')).toBe('secondary');
  });
});

describe('SuscripcionesComponent', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [SuscripcionesComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), MessageService],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function crear(
    lista: SuscripcionPlataforma[] = [
      suscripcion(1, 'activa'),
      suscripcion(2, 'vencida', { fecha_vencimiento: enDias(-3) }),
      suscripcion(3, 'suspendida'),
      suscripcion(4, 'cancelada'),
    ],
  ) {
    const fixture = TestBed.createComponent(SuscripcionesComponent);
    fixture.detectChanges();
    http
      .expectOne((r) => r.url === `${BASE}/planes`)
      .flush([plan('basico', 'Básico', 2), plan('profesional', 'Profesional', 10), plan('viejo', 'Viejo', 1, false)]);
    http
      .expectOne((r) => r.url === `${BASE}/empresas`)
      .flush([empresa(1, 'Alfa'), empresa(2, 'Beta'), empresa(3, 'Gamma')]);
    const req = http.expectOne((r) => r.url === `${BASE}/suscripciones`);
    expect(req.request.params.get('pagina')).toBe('1');
    expect(req.request.params.get('tamanio')).toBe('20');
    expect(req.request.params.has('estado')).toBe(false);
    req.flush(lista);
    fixture.detectChanges();
    return { fixture, comp: fixture.componentInstance as unknown as Interno };
  }

  function recargaPendiente(respuesta: SuscripcionPlataforma[] = []) {
    http.expectOne((r) => r.url === `${BASE}/suscripciones`).flush(respuesta);
  }

  it('muestra el nombre de la empresa, o "Empresa #id" si no está en la lista', () => {
    const { comp } = crear([suscripcion(1, 'activa'), suscripcion(77, 'activa', { empresa_id: 77 })]);
    expect(comp.filas().map((f) => f.empresa)).toEqual(['Alfa', 'Empresa #77']);
  });

  it('habilita en cada fila solo los botones que corresponden al estado efectivo', () => {
    const { fixture, comp } = crear();
    const porEstado = Object.fromEntries(comp.filas().map((f) => [f.suscripcion.estado_efectivo, f.acciones]));
    expect(porEstado['activa']).toMatchObject({ cambiarPlan: true, renovar: true, suspender: true, cancelar: true, reactivar: false });
    expect(porEstado['vencida']).toMatchObject({ renovar: true, cambiarPlan: true, cancelar: true, suspender: false, reactivar: false });
    expect(porEstado['suspendida']).toMatchObject({ reactivar: true, cancelar: true, suspender: false, renovar: false });
    expect(porEstado['cancelada']).toMatchObject({ asignarPlan: true, renovar: false, cancelar: false });

    const filas = (fixture.nativeElement as HTMLElement).querySelectorAll('tbody tr');
    const etiquetas = (i: number) => Array.from(filas[i].querySelectorAll('button')).map((b) => b.textContent?.trim());
    expect(etiquetas(0)).toEqual(['Cambiar plan', 'Renovar', 'Suspender', 'Cancelar', 'Historial']);
    expect(etiquetas(1)).toEqual(['Cambiar plan', 'Renovar', 'Cancelar', 'Historial']);
    expect(etiquetas(2)).toEqual(['Reactivar', 'Cancelar', 'Historial']);
    expect(etiquetas(3)).toEqual(['Asignar plan', 'Historial']);
  });

  it('una cancelada de una empresa con otra vigente en la lista no ofrece asignar plan', () => {
    const { comp } = crear([suscripcion(1, 'cancelada', { empresa_id: 1 }), suscripcion(5, 'activa', { empresa_id: 1 })]);
    expect(comp.filas()[0].acciones.asignarPlan).toBe(false);
  });

  it('el filtro de empresa y de estado va al servidor; el de plan, al cliente', () => {
    const { comp } = crear([
      suscripcion(1, 'activa'),
      suscripcion(2, 'activa', { plan_codigo: 'profesional', plan_nombre: 'Profesional' }),
    ]);
    comp.filtroPlan.set('profesional');
    expect(comp.filas().map((f) => f.suscripcion.id)).toEqual([2]);

    comp.cambiarFiltroEmpresa(2);
    const porEmpresa = http.expectOne((r) => r.url === `${BASE}/suscripciones`);
    expect(porEmpresa.request.params.get('empresa_id')).toBe('2');
    porEmpresa.flush([]);

    comp.cambiarFiltroEstado('activa');
    const porEstado = http.expectOne((r) => r.url === `${BASE}/suscripciones`);
    expect(porEstado.request.params.get('estado')).toBe('activa');
    expect(porEstado.request.params.get('empresa_id')).toBe('2');
    porEstado.flush([]);
  });

  it('el historial pide todas las suscripciones de la empresa, sin filtrar por estado', () => {
    const { fixture, comp } = crear();
    comp.abrirHistorial(suscripcion(1, 'activa'));
    const req = http.expectOne((r) => r.url === `${BASE}/suscripciones`);
    expect(req.request.params.get('empresa_id')).toBe('1');
    expect(req.request.params.has('estado')).toBe(false);
    req.flush([suscripcion(9, 'cancelada', { empresa_id: 1 }), suscripcion(1, 'activa')]);
    fixture.detectChanges();
    expect(comp.dialogoHistorialVisible()).toBe(true);
    expect(document.body.textContent ?? '').toContain('Historial de Alfa');
    expect(document.body.textContent ?? '').toContain('Cancelada');
  });

  describe('cambiar plan', () => {
    it('no ofrece el plan actual ni los inactivos, y manda plan_codigo y fechas', () => {
      const { comp } = crear();
      comp.abrirCambiarPlan(suscripcion(1, 'activa'));
      expect(comp.opcionesPlanDialogo().map((o) => o.value)).toEqual(['profesional']);

      const inicio = new Date(2026, 9, 22);
      const vence = sumarDias(hoyLocal(), 60);
      comp.formularioPlan.controls['plan_codigo'].setValue('profesional');
      comp.formularioPlan.controls['fecha_inicio'].setValue(inicio);
      comp.formularioPlan.controls['fecha_vencimiento'].setValue(vence);
      comp.guardarPlan();

      const post = http.expectOne(`${BASE}/suscripciones`);
      expect(post.request.method).toBe('POST');
      expect(post.request.body).toEqual({
        empresa_id: 1,
        plan_codigo: 'profesional',
        fecha_inicio: '2026-10-22',
        fecha_vencimiento: fechaLocalIso(vence),
      });
      post.flush(suscripcion(10, 'activa', { plan_codigo: 'profesional', plan_nombre: 'Profesional' }));
      recargaPendiente();
      expect(comp.dialogoPlanVisible()).toBe(false);
    });

    it('sin plan, o con vencimiento anterior al inicio o a hoy, no llama a la API', () => {
      const { comp } = crear();
      comp.abrirCambiarPlan(suscripcion(1, 'activa'));
      comp.guardarPlan();
      http.expectNone(`${BASE}/suscripciones`);

      comp.formularioPlan.controls['plan_codigo'].setValue('profesional');
      comp.formularioPlan.controls['fecha_vencimiento'].setValue(hoyLocal());
      expect(comp.formularioPlan.controls['fecha_vencimiento'].valid).toBe(false);
      comp.guardarPlan();
      http.expectNone(`${BASE}/suscripciones`);

      comp.formularioPlan.controls['fecha_inicio'].setValue(sumarDias(hoyLocal(), 40));
      comp.formularioPlan.controls['fecha_vencimiento'].setValue(sumarDias(hoyLocal(), 10));
      comp.guardarPlan();
      http.expectNone(`${BASE}/suscripciones`);
      expect(comp.formularioPlan.invalid).toBe(true);
    });

    it('un rechazo del backend (409) deja el diálogo abierto', () => {
      const { comp } = crear();
      comp.abrirCambiarPlan(suscripcion(1, 'activa'));
      comp.formularioPlan.controls['plan_codigo'].setValue('profesional');
      comp.guardarPlan();
      http
        .expectOne(`${BASE}/suscripciones`)
        .flush({ detail: 'x', codigo: 'limite_plan_excedido' }, { status: 409, statusText: 'Conflict' });
      expect(comp.dialogoPlanVisible()).toBe(true);
    });
  });

  describe('asignar plan a una cancelada', () => {
    it('abre el diálogo si la empresa no tiene suscripción vigente', () => {
      const { comp } = crear();
      comp.abrirAsignarPlan(suscripcion(4, 'cancelada', { empresa_id: 3 }));
      const historial = http.expectOne((r) => r.url === `${BASE}/suscripciones`);
      expect(historial.request.params.get('empresa_id')).toBe('3');
      historial.flush([suscripcion(4, 'cancelada', { empresa_id: 3 })]);
      expect(comp.dialogoPlanVisible()).toBe(true);
      expect(comp.opcionesPlanDialogo().map((o) => o.value)).toEqual(['basico', 'profesional']);
    });

    it('si la empresa ya tiene una vigente, avisa y no abre el diálogo', () => {
      const { comp } = crear();
      comp.abrirAsignarPlan(suscripcion(4, 'cancelada', { empresa_id: 3 }));
      http
        .expectOne((r) => r.url === `${BASE}/suscripciones`)
        .flush([suscripcion(4, 'cancelada', { empresa_id: 3 }), suscripcion(8, 'suspendida', { empresa_id: 3 })]);
      expect(comp.dialogoPlanVisible()).toBe(false);
    });
  });

  describe('renovar', () => {
    it('+1 mes manda fecha_vencimiento contada desde el vencimiento', () => {
      const { comp } = crear();
      const s = suscripcion(1, 'activa', { fecha_vencimiento: enDias(15) });
      comp.abrirRenovar(s);
      const esperado = fechaLocalIso(sumarMeses(sumarDias(hoyLocal(), 15), 1));
      expect(fechaLocalIso(comp.fechaRenovada()!)).toBe(esperado);

      comp.guardarRenovacion();
      const put = http.expectOne(`${BASE}/suscripciones/1/renovar`);
      expect(put.request.method).toBe('PUT');
      expect(put.request.body).toEqual({ fecha_vencimiento: esperado });
      put.flush(s);
      recargaPendiente();
      expect(comp.dialogoRenovarVisible()).toBe(false);
    });

    it('una vencida se renueva desde hoy; +3 meses y +1 año', () => {
      const { comp } = crear();
      comp.abrirRenovar(suscripcion(2, 'vencida', { fecha_vencimiento: enDias(-20) }));
      comp.opcionRenovar.set('3m');
      expect(fechaLocalIso(comp.fechaRenovada()!)).toBe(fechaLocalIso(sumarMeses(hoyLocal(), 3)));
      comp.opcionRenovar.set('1a');
      expect(fechaLocalIso(comp.fechaRenovada()!)).toBe(fechaLocalIso(sumarMeses(hoyLocal(), 12)));
    });

    it('con "otra fecha" manda esa fecha, y no manda nada si no es posterior a hoy', () => {
      const { comp } = crear();
      comp.abrirRenovar(suscripcion(1, 'activa'));
      comp.opcionRenovar.set('libre');
      expect(comp.renovacionValida()).toBe(false);
      comp.guardarRenovacion();
      http.expectNone(`${BASE}/suscripciones/1/renovar`);

      comp.fechaLibre.set(hoyLocal());
      expect(comp.renovacionValida()).toBe(false);

      comp.fechaLibre.set(new Date(2030, 5, 30));
      expect(comp.renovacionValida()).toBe(true);
      comp.guardarRenovacion();
      const put = http.expectOne(`${BASE}/suscripciones/1/renovar`);
      expect(put.request.body).toEqual({ fecha_vencimiento: '2030-06-30' });
      put.flush(suscripcion(1, 'activa'));
      recargaPendiente();
    });

    it('avisa que la renovación es simulada', () => {
      const { fixture, comp } = crear();
      comp.abrirRenovar(suscripcion(1, 'activa'));
      fixture.detectChanges();
      expect(document.body.textContent ?? '').toContain('Renovación simulada: no se cobra nada.');
    });
  });

  describe('estado', () => {
    it('reactivar manda estado "activa" sin pedir confirmación', () => {
      const { comp } = crear();
      comp.reactivar(suscripcion(3, 'suspendida'));
      const put = http.expectOne(`${BASE}/suscripciones/3/estado`);
      expect(put.request.method).toBe('PUT');
      expect(put.request.body).toEqual({ estado: 'activa' });
      put.flush(suscripcion(3, 'activa'));
      recargaPendiente();
    });

    it('suspender pide confirmación y manda "suspendida"', () => {
      const { fixture, comp } = crear();
      const espia = vi.spyOn(fixture.debugElement.injector.get(ConfirmationService), 'confirm');
      comp.pedirSuspender(suscripcion(1, 'activa'));
      expect(espia).toHaveBeenCalledTimes(1);
      http.expectNone(`${BASE}/suscripciones/1/estado`);

      espia.mock.calls[0][0].accept?.();
      const put = http.expectOne(`${BASE}/suscripciones/1/estado`);
      expect(put.request.body).toEqual({ estado: 'suspendida' });
      put.flush(suscripcion(1, 'suspendida'));
      recargaPendiente();
    });

    it('cancelar pide confirmación (sin campo de motivo) y manda "cancelada"', () => {
      const { fixture, comp } = crear();
      const espia = vi.spyOn(fixture.debugElement.injector.get(ConfirmationService), 'confirm');
      comp.pedirCancelar(suscripcion(2, 'vencida'));
      http.expectNone(`${BASE}/suscripciones/2/estado`);

      espia.mock.calls[0][0].accept?.();
      const put = http.expectOne(`${BASE}/suscripciones/2/estado`);
      expect(put.request.body).toEqual({ estado: 'cancelada' });
      put.flush(suscripcion(2, 'cancelada'));
      recargaPendiente();
    });
  });
});
