import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, TestRequest, provideHttpClientTesting } from '@angular/common/http/testing';
import { WritableSignal, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { environment } from '../../../environments/environment';
import { AuthService } from '../../core/auth.service';
import { ConectividadService, EstadoConexion } from '../../core/conectividad.service';
import { SIN_TOAST_ERROR } from '../../core/http-contexts';
import type { ResumenTurno, Turno } from '../../core/models/caja.models';
import { ColaSincronizacionService } from '../../core/offline/cola-sincronizacion.service';
import { TurnoCajaComponent } from './turno-caja.component';

const API = environment.apiUrl;
const URL_ACTUAL = `${API}/caja/turnos/actual`;
const URL_ABRIR = `${API}/caja/turnos`;

const APERTURA = '2026-11-08T14:05:00Z';

function turno(extra: Partial<Turno> = {}): Turno {
  return {
    id: 4,
    sucursal_id: 1,
    sucursal_nombre: 'Central',
    estado: 'abierta',
    apertura_en: APERTURA,
    abierto_por_id: 5,
    abierto_por_nombre: 'Luis Paz',
    monto_inicial: '100.00',
    observacion_apertura: null,
    cierre_en: null,
    cerrado_por_id: null,
    cerrado_por_nombre: null,
    cierre_automatico: false,
    efectivo_contado: null,
    diferencia: null,
    pendientes_declarados: 0,
    observacion_cierre: null,
    conteo_en: null,
    conteo_por_nombre: null,
    observacion_conteo: null,
    conteo_hasta: null,
    monto_esperado: null,
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

/** La hora local que muestra la barra para `APERTURA` ("HH:mm"). */
function horaLocal(): string {
  const d = new Date(APERTURA);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

describe('TurnoCajaComponent', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<TurnoCajaComponent>;
  let el: HTMLElement;
  let estado: WritableSignal<EstadoConexion>;
  let pendientes: number;
  let abierto: boolean[];

  interface Opciones {
    permisos?: string[];
    sucursalId?: number | null;
    enviarSucursal?: boolean;
    conexion?: EstadoConexion;
    pendientes?: number;
  }

  function montar({
    permisos = [],
    sucursalId = 1,
    enviarSucursal = false,
    conexion = 'en_linea',
    pendientes: pend = 0,
  }: Opciones = {}): void {
    estado = signal<EstadoConexion>(conexion);
    pendientes = pend;
    TestBed.configureTestingModule({
      imports: [TurnoCajaComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: { tienePermiso: (p: string) => permisos.includes(p) } },
        { provide: ConectividadService, useValue: { estado } },
        {
          provide: ColaSincronizacionService,
          useValue: {
            refrescarConteos: () => Promise.resolve(),
            pendientes: () => pendientes,
            pendientesDeOtros: () => 0,
          },
        },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(TurnoCajaComponent);
    el = fixture.nativeElement as HTMLElement;
    abierto = [];
    fixture.componentInstance.dialogoAbierto.subscribe((v) => abierto.push(v));
    fixture.componentRef.setInput('sucursalId', sucursalId);
    fixture.componentRef.setInput('enviarSucursal', enviarSucursal);
    fixture.detectChanges();
  }

  const actual = (): TestRequest => http.expectOne((r) => r.url === URL_ACTUAL);
  const responderActual = (turnoActual: Turno | null, sugerido: string | null = null): void => {
    actual().flush({ sucursal_id: 1, turno: turnoActual, monto_inicial_sugerido: sugerido });
    fixture.detectChanges();
  };
  const q = (selector: string) => el.querySelector(selector) as HTMLElement | null;
  const boton = (estadoDe: string) => q(`[data-estado="${estadoDe}"]`) as HTMLButtonElement;
  const texto = () => (el.textContent ?? '').replace(/\s+/g, ' ').trim();
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

  describe('sin turno abierto', () => {
    it('avisa que lo que se cobre no entra a ninguna caja y ofrece abrir el turno', () => {
      montar();
      responderActual(null);

      expect(q('[data-estado="sin-turno"]')?.textContent).toContain(
        'No tienes un turno abierto: lo que cobres no entra a ninguna caja.',
      );
      expect(boton('abrir-turno').textContent).toContain('Abrir turno');
      expect(boton('abrir-turno').disabled).toBe(false);
      expect(q('[data-estado="turno-abierto"]')).toBeNull();
    });

    it('un cajero consulta sin sucursal_id y sin toast de error', () => {
      montar();
      const req = actual();
      expect(req.request.params.has('sucursal_id')).toBe(false);
      expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
      req.flush({ sucursal_id: 1, turno: null, monto_inicial_sugerido: null });
    });

    it('el diálogo para abrir viene con el monto inicial sugerido y manda monto y observación', async () => {
      montar();
      responderActual(null, '120.00');

      boton('abrir-turno').click();
      await estabilizar();
      const monto = q('[data-estado="monto-inicial"]') as HTMLInputElement;
      expect(monto.value).toBe('120');
      escribir('[data-estado="monto-inicial"]', '150.5');
      escribir('[data-estado="observacion-apertura"]', '  Con sencillo  ');

      boton('confirmar-apertura').click();
      const req = http.expectOne((r) => r.method === 'POST' && r.url === URL_ABRIR);
      expect(req.request.body).toEqual({ monto_inicial: '150.50', observacion: 'Con sencillo' });
      expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
      req.flush(turno());
      await estabilizar();

      expect(q('[data-estado="turno-abierto"]')?.textContent).toContain(`Turno abierto desde ${horaLocal()} por Luis Paz`);
      expect(q('[data-estado="confirmar-apertura"]')).toBeNull();
    });

    it('sin monto válido no se puede abrir', async () => {
      montar();
      responderActual(null);
      boton('abrir-turno').click();
      await estabilizar();

      expect(boton('confirmar-apertura').disabled).toBe(true);
      escribir('[data-estado="monto-inicial"]', '-5');
      expect(boton('confirmar-apertura').disabled).toBe(true);
      escribir('[data-estado="monto-inicial"]', '0');
      expect(boton('confirmar-apertura').disabled).toBe(false);
    });

    it('si el servidor dice que ya hay un turno abierto lo explica y vuelve a leer la barra', async () => {
      montar();
      responderActual(null);
      boton('abrir-turno').click();
      await estabilizar();
      escribir('[data-estado="monto-inicial"]', '100');
      boton('confirmar-apertura').click();
      http
        .expectOne((r) => r.method === 'POST' && r.url === URL_ABRIR)
        .flush(
          { detail: 'turno_ya_abierto', codigo: 'turno_ya_abierto', mensaje: 'Ya hay un turno abierto en la sucursal.' },
          { status: 409, statusText: 'Conflict' },
        );
      fixture.detectChanges();

      expect(q('[data-estado="error-apertura"]')?.textContent).toContain('ya tiene un turno abierto');
      // La barra se actualiza con el turno que ya existía.
      responderActual(turno({ abierto_por_nombre: 'Marta Ríos' }));
      expect(q('[data-estado="turno-abierto"]')?.textContent).toContain('por Marta Ríos');
    });
  });

  describe('con turno abierto', () => {
    it('dice desde qué hora y quién lo abrió, y un cajero NO ve el esperado', () => {
      montar();
      responderActual(turno());

      expect(q('[data-estado="turno-abierto"]')?.textContent).toContain(`Turno abierto desde ${horaLocal()} por Luis Paz`);
      expect(q('[data-estado="esperado-en-vivo"]')).toBeNull();
      expect(texto()).not.toContain('Esperado');
      expect(boton('cerrar-turno').textContent).toContain('Cerrar turno');
      expect(q('[data-estado="sin-turno"]')).toBeNull();
    });

    it('un supervisor ve además el esperado en vivo y se actualiza con cada venta', () => {
      montar({ permisos: ['caja.supervisar'] });
      responderActual(turno({ monto_esperado: '250.00', resumen: RESUMEN }));
      expect(q('[data-estado="esperado-en-vivo"]')?.textContent).toContain('Esperado en el cajón: Bs 250.00');

      fixture.componentRef.setInput('actualizarCon', { id: 77 });
      fixture.detectChanges();
      responderActual(turno({ monto_esperado: '280.00', resumen: RESUMEN }));
      expect(q('[data-estado="esperado-en-vivo"]')?.textContent).toContain('Bs 280.00');
    });

    it('un cajero no vuelve a leer el turno con cada venta', () => {
      montar();
      responderActual(turno());
      fixture.componentRef.setInput('actualizarCon', { id: 77 });
      fixture.detectChanges();
      http.expectNone((r) => r.url === URL_ACTUAL);
    });
  });

  describe('cierre ciego', () => {
    it('no muestra el esperado hasta cerrar; manda lo contado y los pendientes sin sincronizar', async () => {
      montar({ pendientes: 2 });
      responderActual(turno());

      boton('cerrar-turno').click();
      await estabilizar();

      // Antes de contar: nada del esperado.
      const dialogo = q('p-dialog') as HTMLElement;
      expect(dialogo.textContent).not.toContain('Esperado');
      expect(dialogo.textContent).not.toContain('250');
      expect(q('[data-estado="aviso-pendientes"]')?.textContent).toContain(
        'Hay 2 operaciones sin sincronizar: no cuentan en el esperado.',
      );

      escribir('[data-estado="efectivo-contado"]', '240');
      boton('confirmar').click();
      const req = http.expectOne((r) => r.method === 'POST' && r.url === `${API}/caja/turnos/4/cerrar`);
      expect(req.request.body).toEqual({ efectivo_contado: '240.00', pendientes_sin_sincronizar: 2 });
      expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
      req.flush(
        turno({
          estado: 'cerrada',
          cierre_en: '2026-11-08T22:00:00Z',
          efectivo_contado: '240.00',
          diferencia: '-10.00',
          monto_esperado: '250.00',
          resumen: RESUMEN,
          pendientes_declarados: 2,
        }),
      );
      await estabilizar();

      // Recién ahora aparecen esperado, contado y diferencia (faltante en rojo).
      expect(q('[data-estado="cifra-esperado"]')?.textContent).toContain('Bs 250.00');
      expect(q('[data-estado="cifra-contado"]')?.textContent).toContain('Bs 240.00');
      const diferencia = q('[data-estado="cifra-diferencia"]') as HTMLElement;
      expect(diferencia.textContent).toContain('Faltan Bs 10.00');
      expect(diferencia.classList).toContain('fs-chip--error');
      expect(q('[data-estado="resumen-turno"]')?.textContent).toContain('Efectivo cobrado (3 ventas)');
      expect(q('[data-estado="resumen-informativo"]')?.textContent).toContain('Ventas online del día (2)');
      // La barra ya pasó a "sin turno" mientras se ve el resultado.
      expect(q('[data-estado="sin-turno"]')).not.toBeNull();

      boton('listo').click();
      await estabilizar();
      expect(q('p-dialog')).toBeNull();
    });

    it('la diferencia en verde cuando cuadra y en ámbar cuando sobra', async () => {
      for (const [diferencia, clase, frase] of [
        ['0.00', 'fs-chip--exito', 'Cuadra'],
        ['5.00', 'fs-chip--advertencia', 'Sobran Bs 5.00'],
      ]) {
        TestBed.resetTestingModule();
        montar();
        responderActual(turno());
        boton('cerrar-turno').click();
        await estabilizar();
        escribir('[data-estado="efectivo-contado"]', '250');
        boton('confirmar').click();
        http
          .expectOne((r) => r.method === 'POST' && r.url === `${API}/caja/turnos/4/cerrar`)
          .flush(turno({ estado: 'cerrada', efectivo_contado: '250.00', diferencia, monto_esperado: '250.00', resumen: RESUMEN }));
        await estabilizar();
        const chip = q('[data-estado="cifra-diferencia"]') as HTMLElement;
        expect(chip.classList).toContain(clase);
        expect(chip.textContent).toContain(frase);
      }
    });

    it('sin pendientes en este equipo no hay aviso y se manda 0', async () => {
      montar({ pendientes: 0 });
      responderActual(turno());
      boton('cerrar-turno').click();
      await estabilizar();

      expect(q('[data-estado="aviso-pendientes"]')).toBeNull();
      escribir('[data-estado="efectivo-contado"]', '100');
      boton('confirmar').click();
      const req = http.expectOne((r) => r.method === 'POST' && r.url === `${API}/caja/turnos/4/cerrar`);
      expect(req.request.body).toEqual({ efectivo_contado: '100.00', pendientes_sin_sincronizar: 0 });
      req.flush(turno({ estado: 'cerrada', efectivo_contado: '100.00', diferencia: '0.00', monto_esperado: '100.00' }));
    });

    it('una sola operación pendiente se avisa en singular', async () => {
      montar({ pendientes: 1 });
      responderActual(turno());
      boton('cerrar-turno').click();
      await estabilizar();

      expect(q('[data-estado="aviso-pendientes"]')?.textContent).toContain(
        'Hay 1 operación sin sincronizar: no cuenta en el esperado.',
      );
    });

    it('si el servidor pide observación muestra el campo y deja reintentar con ella', async () => {
      montar();
      responderActual(turno());
      boton('cerrar-turno').click();
      await estabilizar();
      expect(q('[data-estado="observacion"]')).toBeNull();

      escribir('[data-estado="efectivo-contado"]', '200');
      boton('confirmar').click();
      http
        .expectOne((r) => r.method === 'POST' && r.url === `${API}/caja/turnos/4/cerrar`)
        .flush(
          { detail: 'observacion_requerida', codigo: 'observacion_requerida', mensaje: 'Falta la observación' },
          { status: 400, statusText: 'Bad Request' },
        );
      await estabilizar();

      expect(q('[data-estado="error-conteo"]')?.textContent).toContain('escribe una observación');
      expect(q('[data-estado="observacion"]')).not.toBeNull();
      // Sigue sin revelarse el esperado.
      expect(q('p-dialog')?.textContent).not.toContain('Esperado');

      escribir('[data-estado="observacion"]', 'Se pagó un delivery');
      boton('confirmar').click();
      const reintento = http.expectOne((r) => r.method === 'POST' && r.url === `${API}/caja/turnos/4/cerrar`);
      expect(reintento.request.body).toEqual({
        efectivo_contado: '200.00',
        observacion: 'Se pagó un delivery',
        pendientes_sin_sincronizar: 0,
      });
      reintento.flush(
        turno({ estado: 'cerrada', efectivo_contado: '200.00', diferencia: '-50.00', monto_esperado: '250.00', resumen: RESUMEN }),
      );
      await estabilizar();
      expect(q('[data-estado="cifra-esperado"]')).not.toBeNull();
    });

    it('un turno ya cerrado por otra persona se explica en el diálogo', async () => {
      montar();
      responderActual(turno());
      boton('cerrar-turno').click();
      await estabilizar();
      escribir('[data-estado="efectivo-contado"]', '200');
      boton('confirmar').click();
      http
        .expectOne((r) => r.method === 'POST' && r.url === `${API}/caja/turnos/4/cerrar`)
        .flush({ detail: 'turno_cerrado', codigo: 'turno_cerrado', mensaje: 'x' }, { status: 409, statusText: 'Conflict' });
      await estabilizar();

      expect(q('[data-estado="error-conteo"]')?.textContent).toContain('ya está cerrado');
    });

    it('un supervisor sí ve el esperado antes de contar', async () => {
      montar({ permisos: ['caja.supervisar'] });
      responderActual(turno({ monto_esperado: '250.00', resumen: RESUMEN }));
      boton('cerrar-turno').click();
      await estabilizar();

      expect(q('[data-estado="esperado-visible"]')?.textContent).toContain('Bs 250.00');
      expect(q('[data-estado="observacion"]')).not.toBeNull();
    });

    it('cancelar cierra el diálogo sin mandar nada', async () => {
      montar();
      responderActual(turno());
      boton('cerrar-turno').click();
      await estabilizar();
      boton('cancelar').click();
      await estabilizar();

      expect(q('p-dialog')).toBeNull();
      http.expectNone((r) => r.method === 'POST');
    });
  });

  describe('administrador con varias sucursales', () => {
    it('consulta y abre con la sucursal elegida, y reacciona cuando cambia', async () => {
      montar({ sucursalId: 3, enviarSucursal: true });
      const primera = actual();
      expect(primera.request.params.get('sucursal_id')).toBe('3');
      primera.flush({ sucursal_id: 3, turno: null, monto_inicial_sugerido: null });
      fixture.detectChanges();

      boton('abrir-turno').click();
      await estabilizar();
      escribir('[data-estado="monto-inicial"]', '100');
      boton('confirmar-apertura').click();
      const apertura = http.expectOne((r) => r.method === 'POST' && r.url === URL_ABRIR);
      expect(apertura.request.body).toEqual({ sucursal_id: 3, monto_inicial: '100.00' });
      apertura.flush(turno({ sucursal_id: 3 }));
      await estabilizar();
      expect(q('[data-estado="turno-abierto"]')).not.toBeNull();

      // Otra sucursal: la barra olvida el turno anterior y consulta la nueva.
      fixture.componentRef.setInput('sucursalId', 4);
      fixture.detectChanges();
      expect(q('[data-estado="turno-abierto"]')).toBeNull();
      const segunda = actual();
      expect(segunda.request.params.get('sucursal_id')).toBe('4');
      segunda.flush({ sucursal_id: 4, turno: null, monto_inicial_sugerido: null });
      fixture.detectChanges();
      expect(q('[data-estado="sin-turno"]')).not.toBeNull();
    });

    it('una respuesta vieja no pisa a la de la sucursal nueva', () => {
      montar({ sucursalId: 3, enviarSucursal: true });
      const vieja = actual();
      fixture.componentRef.setInput('sucursalId', 4);
      fixture.detectChanges();
      const nueva = actual();

      expect(vieja.cancelled).toBe(true);
      nueva.flush({ sucursal_id: 4, turno: turno({ sucursal_id: 4, abierto_por_nombre: 'Rosa' }), monto_inicial_sugerido: null });
      fixture.detectChanges();
      expect(q('[data-estado="turno-abierto"]')?.textContent).toContain('por Rosa');
    });

    it('sin sucursal elegida no consulta nada', () => {
      montar({ sucursalId: null, enviarSucursal: true });
      http.expectNone((r) => r.url === URL_ACTUAL);
    });
  });

  describe('sin conexión', () => {
    it('desde el inicio no consulta, no ofrece abrir y explica que hace falta conexión', () => {
      montar({ conexion: 'sin_conexion' });

      http.expectNone((r) => r.url === URL_ACTUAL);
      expect(q('[data-estado="turno-sin-conexion"]')?.textContent).toContain(
        'Para abrir o cerrar el turno necesitas conexión',
      );
      expect(q('[data-estado="sin-turno"]')).toBeNull();
    });

    it('si se pierde la conexión los botones quedan desactivados y vuelven al reconectar', () => {
      montar();
      responderActual(null);
      expect(boton('abrir-turno').disabled).toBe(false);

      estado.set('sin_conexion');
      fixture.detectChanges();
      expect(boton('abrir-turno').disabled).toBe(true);
      expect(q('[data-estado="turno-sin-conexion"]')?.textContent).toContain(
        'Para abrir o cerrar el turno necesitas conexión',
      );
      // Aunque se fuerce el método, no sale ninguna petición.
      (fixture.componentInstance as unknown as { abrirDialogoApertura(): void }).abrirDialogoApertura();
      http.expectNone(() => true);
      expect(q('[data-estado="monto-inicial"]')).toBeNull();

      estado.set('en_linea');
      fixture.detectChanges();
      responderActual(turno());
      expect(boton('cerrar-turno').disabled).toBe(false);
      expect(q('[data-estado="turno-sin-conexion"]')).toBeNull();
    });

    it('con turno abierto y sin conexión no se puede cerrar', () => {
      montar();
      responderActual(turno());
      estado.set('servidor_no_responde');
      fixture.detectChanges();

      expect(boton('cerrar-turno').disabled).toBe(true);
    });
  });

  describe('si la consulta falla', () => {
    it('muestra un aviso discreto con "Reintentar" y no lanza ningún error', () => {
      montar();
      actual().flush(null, { status: 500, statusText: 'Server Error' });
      fixture.detectChanges();

      expect(q('[data-estado="turno-error"]')?.textContent).toContain('Puedes seguir cobrando');
      expect(q('[data-estado="sin-turno"]')).toBeNull();

      boton('reintentar-turno').click();
      responderActual(turno());
      expect(q('[data-estado="turno-abierto"]')).not.toBeNull();
      expect(q('[data-estado="turno-error"]')).toBeNull();
    });
  });

  describe('diálogos abiertos (para los atajos de la Caja)', () => {
    it('avisa con dialogoAbierto mientras el diálogo de abrir o el de cerrar están a la vista', async () => {
      montar();
      responderActual(null);
      expect(abierto.at(-1)).toBe(false);

      boton('abrir-turno').click();
      await estabilizar();
      expect(abierto.at(-1)).toBe(true);

      boton('cancelar-apertura').click();
      await estabilizar();
      expect(abierto.at(-1)).toBe(false);
    });

    it('también mientras se ve el cierre y hasta que se pulsa "Listo"', async () => {
      montar();
      responderActual(turno());
      boton('cerrar-turno').click();
      await estabilizar();
      expect(abierto.at(-1)).toBe(true);

      escribir('[data-estado="efectivo-contado"]', '100');
      boton('confirmar').click();
      http
        .expectOne((r) => r.method === 'POST' && r.url === `${API}/caja/turnos/4/cerrar`)
        .flush(turno({ estado: 'cerrada', efectivo_contado: '100.00', diferencia: '0.00', monto_esperado: '100.00' }));
      await estabilizar();
      // La barra ya no tiene turno, pero el resultado sigue a la vista: los atajos siguen bloqueados.
      expect(abierto.at(-1)).toBe(true);

      boton('listo').click();
      await estabilizar();
      expect(abierto.at(-1)).toBe(false);
    });
  });
});
