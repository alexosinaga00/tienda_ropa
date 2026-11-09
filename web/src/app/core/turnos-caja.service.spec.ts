import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../environments/environment';
import { SIN_TOAST_ERROR } from './http-contexts';
import {
  Turno,
  claseDiferencia,
  mensajeErrorCaja,
  montoParaServidor,
  textoDiferencia,
} from './models/caja.models';
import { TurnosCajaService } from './turnos-caja.service';

const API = environment.apiUrl;
const BASE = `${API}/caja`;

const TURNO = { id: 4, sucursal_id: 2, estado: 'abierta' } as Turno;

describe('TurnosCajaService', () => {
  let servicio: TurnosCajaService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    servicio = TestBed.inject(TurnosCajaService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  describe('actual', () => {
    it('un cajero no manda sucursal_id', () => {
      servicio.actual().subscribe();
      const req = http.expectOne((r) => r.url === `${BASE}/turnos/actual`);
      expect(req.request.method).toBe('GET');
      expect(req.request.params.has('sucursal_id')).toBe(false);
      expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
      req.flush({ sucursal_id: 1, turno: null, monto_inicial_sugerido: null });
    });

    it('el administrador manda la sucursal elegida', () => {
      servicio.actual(3).subscribe();
      const req = http.expectOne((r) => r.url === `${BASE}/turnos/actual`);
      expect(req.request.params.get('sucursal_id')).toBe('3');
      req.flush({ sucursal_id: 3, turno: null, monto_inicial_sugerido: '150.00' });
    });
  });

  it('abrir y cerrar mandan el cuerpo tal cual, sin toast de error', () => {
    servicio.abrir({ sucursal_id: 2, monto_inicial: '100.00', observacion: 'Con sencillo' }).subscribe();
    const abrir = http.expectOne(`${BASE}/turnos`);
    expect(abrir.request.method).toBe('POST');
    expect(abrir.request.body).toEqual({ sucursal_id: 2, monto_inicial: '100.00', observacion: 'Con sencillo' });
    expect(abrir.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    abrir.flush(TURNO);

    servicio.cerrar(4, { efectivo_contado: '250.00', pendientes_sin_sincronizar: 2 }).subscribe();
    const cerrar = http.expectOne(`${BASE}/turnos/4/cerrar`);
    expect(cerrar.request.method).toBe('POST');
    expect(cerrar.request.body).toEqual({ efectivo_contado: '250.00', pendientes_sin_sincronizar: 2 });
    expect(cerrar.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    cerrar.flush(TURNO);
  });

  it('estado pide "Cajas de hoy" y detalle pide un turno', () => {
    servicio.estado().subscribe();
    http.expectOne(`${BASE}/turnos/estado`).flush([]);

    servicio.detalle(9).subscribe();
    const req = http.expectOne(`${BASE}/turnos/9`);
    expect(req.request.method).toBe('GET');
    req.flush({ ...TURNO, ajuste_posterior: null, reembolsos: [] });
  });

  describe('listar', () => {
    it('sin filtros pide la página 1 de 20', () => {
      servicio.listar().subscribe();
      const req = http.expectOne((r) => r.url === `${BASE}/turnos`);
      expect(req.request.params.get('pagina')).toBe('1');
      expect(req.request.params.get('tamanio')).toBe('20');
      for (const clave of ['sucursal_id', 'estado', 'desde', 'hasta']) {
        expect(req.request.params.has(clave)).toBe(false);
      }
      req.flush([]);
    });

    it('manda cada filtro cuando se pide', () => {
      servicio
        .listar({ sucursal_id: 2, estado: 'cerrada_auto', desde: '2026-11-01', hasta: '2026-11-07', pagina: 3, tamanio: 50 })
        .subscribe();
      const req = http.expectOne((r) => r.url === `${BASE}/turnos`);
      expect(req.request.params.get('sucursal_id')).toBe('2');
      expect(req.request.params.get('estado')).toBe('cerrada_auto');
      expect(req.request.params.get('desde')).toBe('2026-11-01');
      expect(req.request.params.get('hasta')).toBe('2026-11-07');
      expect(req.request.params.get('pagina')).toBe('3');
      expect(req.request.params.get('tamanio')).toBe('50');
      req.flush([]);
    });
  });

  it('completarConteo manda el conteo y la observación', () => {
    servicio.completarConteo(4, { efectivo_contado: '300.00', observacion: 'Contado al día siguiente' }).subscribe();
    const req = http.expectOne(`${BASE}/turnos/4/completar-conteo`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ efectivo_contado: '300.00', observacion: 'Contado al día siguiente' });
    expect(req.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    req.flush(TURNO);
  });
});

describe('caja.models', () => {
  const error = (status: number, cuerpo: unknown) => new HttpErrorResponse({ status, error: cuerpo });

  describe('mensajeErrorCaja', () => {
    it('traduce cada código funcional del cierre de caja a un texto legible', () => {
      const codigos = [
        'turno_ya_abierto',
        'observacion_requerida',
        'turno_cerrado',
        'turno_de_otro_cajero',
        'conteo_no_aplica',
        'conteo_ya_registrado',
        'conteo_fuera_de_plazo',
      ];
      for (const codigo of codigos) {
        const texto = mensajeErrorCaja(error(409, { detail: codigo, codigo, mensaje: 'texto del servidor' }), 'por defecto');
        expect(texto, codigo).not.toBe('por defecto');
        expect(texto, codigo).not.toBe('texto del servidor');
        expect(texto, codigo).not.toContain('_');
      }
      expect(mensajeErrorCaja(error(409, { codigo: 'conteo_fuera_de_plazo' }), 'x')).toContain('72 horas');
    });

    it('un código desconocido usa el mensaje del servidor, luego el detalle y por último el texto por defecto', () => {
      expect(mensajeErrorCaja(error(409, { codigo: 'otro', mensaje: 'Algo pasó' }), 'x')).toBe('Algo pasó');
      expect(mensajeErrorCaja(error(400, { detail: 'Monto inválido' }), 'x')).toBe('Monto inválido');
      expect(mensajeErrorCaja(error(500, null), 'por defecto')).toBe('por defecto');
      expect(mensajeErrorCaja(error(0, null), 'por defecto')).toBe('Sin conexión con el servidor. Inténtalo de nuevo.');
      expect(mensajeErrorCaja(new Error('x'), 'por defecto')).toBe('por defecto');
    });
  });

  describe('montoParaServidor', () => {
    it('da texto con 2 decimales y rechaza vacíos, negativos y no numéricos', () => {
      expect(montoParaServidor(150)).toBe('150.00');
      expect(montoParaServidor(0)).toBe('0.00');
      expect(montoParaServidor('12,5')).toBe('12.50');
      expect(montoParaServidor(-1)).toBeNull();
      expect(montoParaServidor(null)).toBeNull();
      expect(montoParaServidor('')).toBeNull();
      expect(montoParaServidor('abc')).toBeNull();
    });
  });

  describe('diferencia', () => {
    it('verde si cuadra, ámbar si sobra y rojo si falta', () => {
      expect(claseDiferencia('0.00')).toBe('fs-chip--exito');
      expect(claseDiferencia('5.00')).toBe('fs-chip--advertencia');
      expect(claseDiferencia('-5.00')).toBe('fs-chip--error');
      expect(claseDiferencia(null)).toBe('');
      expect(textoDiferencia('0.00')).toBe('Cuadra');
      expect(textoDiferencia('5.5')).toBe('Sobran Bs 5.50');
      expect(textoDiferencia('-5')).toBe('Faltan Bs 5.00');
      expect(textoDiferencia(null)).toBe('—');
    });
  });
});
