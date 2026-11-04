import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../environments/environment';
import { SIN_TOAST_ERROR } from './http-contexts';
import { PlanPublico } from './models/plan.models';
import { PlanesPublicosService } from './planes-publicos.service';

const URL_PLANES = `${environment.apiUrl}/public/planes`;

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

describe('PlanesPublicosService', () => {
  let servicio: PlanesPublicosService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    servicio = TestBed.inject(PlanesPublicosService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('arranca sin planes, sin cargar y sin error', () => {
    expect(servicio.planes()).toEqual([]);
    expect(servicio.cargando()).toBe(false);
    expect(servicio.error()).toBe(false);
  });

  it('pide GET /public/planes sin toast de error y guarda lo recibido', () => {
    servicio.cargar();
    expect(servicio.cargando()).toBe(true);

    const peticion = http.expectOne(URL_PLANES);
    expect(peticion.request.method).toBe('GET');
    expect(peticion.request.context.get(SIN_TOAST_ERROR)).toBe(true);
    peticion.flush([BASICO]);

    expect(servicio.planes()).toEqual([BASICO]);
    expect(servicio.cargando()).toBe(false);
    expect(servicio.error()).toBe(false);
  });

  it('si falla, marca el error y deja la lista vacía', () => {
    servicio.cargar();
    http.expectOne(URL_PLANES).flush('boom', { status: 500, statusText: 'Server Error' });

    expect(servicio.error()).toBe(true);
    expect(servicio.cargando()).toBe(false);
    expect(servicio.planes()).toEqual([]);
  });

  it('reintentar limpia el error y vuelve a pedir', () => {
    servicio.cargar();
    http.expectOne(URL_PLANES).flush('boom', { status: 500, statusText: 'Server Error' });
    expect(servicio.error()).toBe(true);

    servicio.cargar();
    expect(servicio.error()).toBe(false);
    expect(servicio.cargando()).toBe(true);
    http.expectOne(URL_PLANES).flush([BASICO]);

    expect(servicio.planes().length).toBe(1);
    expect(servicio.error()).toBe(false);
  });

  it('una petición nueva cancela la anterior que seguía en vuelo', () => {
    servicio.cargar();
    const primera = http.expectOne(URL_PLANES);
    servicio.cargar();

    expect(primera.cancelled).toBe(true);
    http.expectOne(URL_PLANES).flush([BASICO]);
    expect(servicio.planes().length).toBe(1);
  });
});
