import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../../../environments/environment';
import { EMPRESA, USUARIO, linea, nuevoEntorno } from '../../../core/offline-cliente/ayudas-prueba';
import { MAX_UNIDADES_LINEA } from '../../../core/offline-cliente/cliente-offline.config';
import { ClienteOfflineService } from '../../../core/offline-cliente/cliente-offline.service';
import { CarritoLocalService } from './carrito-local.service';

const API = environment.apiUrl;

// `linea()` trae también la empresa, el usuario y la fecha: el servicio las pone él mismo.
const nueva = (n: number, extra = {}) => {
  const { empresa_id, usuario_id, agregado_en, ...resto } = linea(n);
  void empresa_id; void usuario_id; void agregado_en;
  return { ...resto, ...extra };
};

describe('CarritoLocalService', () => {
  let entorno: ReturnType<typeof nuevoEntorno>;
  let servicio: CarritoLocalService;
  let http: HttpTestingController;

  async function reposo(): Promise<void> {
    for (let i = 0; i < 30; i++) await new Promise<void>((r) => setTimeout(r, 0));
  }

  beforeEach(async () => {
    entorno = nuevoEntorno();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), { provide: ClienteOfflineService, useValue: entorno.cliente }],
    });
    http = TestBed.inject(HttpTestingController);
    servicio = TestBed.inject(CarritoLocalService);
    TestBed.tick();
    await reposo();
  });

  afterEach(async () => {
    TestBed.resetTestingModule();
    await entorno.cerrar();
  });

  it('agrega prendas con sus datos para mostrarlas y calcula el subtotal con los precios guardados', async () => {
    expect(await servicio.agregar(nueva(1, { cantidad: 2 }))).toBe(true);
    expect(await servicio.agregar(nueva(2, { cantidad: 1, precio_unitario: '99.50' }))).toBe(true);

    expect(servicio.cantidadLineas()).toBe(2);
    expect(servicio.cantidadPrendas()).toBe(3);
    expect(servicio.subtotal()).toBe('497.50');
    expect(servicio.lineas()[0]).toMatchObject({ producto_nombre: 'Polera 1', talla: 'M', color: 'Negro', sucursal_nombre: 'Centro', empresa_id: EMPRESA, usuario_id: USUARIO });
    // Quedó en IndexedDB, no solo en memoria.
    expect(await entorno.repo().carrito()).toHaveLength(2);
  });

  it('agregar la misma variante suma, con un tope por línea', async () => {
    await servicio.agregar(nueva(1, { cantidad: MAX_UNIDADES_LINEA - 1 }));
    await servicio.agregar(nueva(1, { cantidad: 5 }));

    expect(servicio.lineas()).toHaveLength(1);
    expect(servicio.lineas()[0].cantidad).toBe(MAX_UNIDADES_LINEA);
  });

  it('cambia la cantidad y quita; vaciar deja el carrito en cero', async () => {
    await servicio.agregar(nueva(1));
    await servicio.agregar(nueva(2));

    await servicio.cambiarCantidad(101, 7);
    expect(servicio.lineas().find((l) => l.variante_id === 101)?.cantidad).toBe(7);
    await servicio.quitar(102);
    expect(servicio.lineas().map((l) => l.variante_id)).toEqual([101]);
    await servicio.vaciar();
    expect(servicio.lineas()).toEqual([]);
  });

  it('sobrevive a recargar (otra instancia lee lo mismo de IndexedDB)', async () => {
    await servicio.agregar(nueva(1));

    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), { provide: ClienteOfflineService, useValue: entorno.cliente }],
    });
    const otra = TestBed.inject(CarritoLocalService);
    TestBed.tick();
    await reposo();

    expect(otra.lineas().map((l) => l.variante_id)).toEqual([101]);
  });

  it('sin sesión no guarda nada, y al entrar otra persona ve su carrito, no el anterior', async () => {
    await servicio.agregar(nueva(1));
    entorno.alcance.set(null);
    TestBed.tick();
    await reposo();
    expect(servicio.lineas()).toEqual([]);
    expect(await servicio.agregar(nueva(2))).toBe(false);

    entorno.alcance.set({ empresaId: EMPRESA, usuarioId: 9 });
    TestBed.tick();
    await reposo();
    expect(servicio.lineas()).toEqual([]);
  });

  it('pasar al servidor: agrega cada línea al carrito del servidor y la quita de la local; las que fallan se quedan', async () => {
    await servicio.agregar(nueva(1, { cantidad: 2 }));
    await servicio.agregar(nueva(2, { cantidad: 1 }));

    const promesa = servicio.pasarAlServidor();
    // Una por una, en orden. La primera la acepta el servidor (y resuelve etiquetas: carrito vacío en la respuesta).
    for (let i = 0; i < 100; i++) {
      const pendientes = http.match((r) => r.method === 'POST' && r.url === `${API}/carrito`);
      for (const p of pendientes) {
        if (p.request.body.variante_id === 101) {
          expect(p.request.body).toEqual({ variante_id: 101, cantidad: 2 });
          p.flush({ id: 1, cliente_id: 1, sucursal_id: null, actualizado_en: '', detalle: [], subtotal: 0 });
        } else {
          p.flush({ detail: 'Sin stock' }, { status: 409, statusText: 'Conflict' });
        }
      }
      await new Promise<void>((r) => setTimeout(r, 0));
    }
    const resultado = await promesa;

    expect(resultado).toEqual({ pasadas: 1, fallidas: 1 });
    expect(servicio.lineas().map((l) => l.variante_id)).toEqual([102]);
  });

  it('recuerda las sucursales para elegir dónde retirar sin red', async () => {
    expect(await servicio.sucursalesRecordadas()).toEqual([]);

    await servicio.recordarSucursales([{ id: 3, nombre: 'Centro', es_deposito: false, ...{ extra: 'x' } } as never]);

    expect(await servicio.sucursalesRecordadas()).toEqual([{ id: 3, nombre: 'Centro', es_deposito: false }]);
  });
});
