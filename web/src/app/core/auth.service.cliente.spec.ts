import 'fake-indexeddb/auto';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { Subject, firstValueFrom } from 'rxjs';
import { environment } from '../../environments/environment';
import { AuthService } from './auth.service';
import { ConectividadService } from './conectividad.service';
import type { UsuarioYo } from './models/seguridad.models';
import { AlmacenOfflineService } from './offline/almacen-offline.service';
import { BaseOffline } from './offline/db-offline';
import { AlmacenClienteOfflineService } from './offline-cliente/almacen-cliente-offline.service';
import { linea, pedido } from './offline-cliente/ayudas-prueba';
import { BaseCliente } from './offline-cliente/db-cliente-offline';
import { ClienteOfflineService } from './offline-cliente/cliente-offline.service';

const API = environment.apiUrl;
const TOKENS = { access_token: 'a', refresh_token: 'r', token_type: 'bearer' };

let contador = 0;

function comprador(id = 5, roles: string[] = ['cliente']): UsuarioYo {
  return {
    id,
    nombre: 'Ana',
    apellido: 'Paz',
    email: 'ana@b.com',
    telefono: null,
    activo: true,
    roles,
    permisos: ['ventas.digital'],
    empresa_id: 7,
    empresa_codigo: 'acme',
    empresa_nombre: 'Acme',
  };
}

describe('AuthService con un comprador de la tienda (modo sin conexión del cliente)', () => {
  let auth: AuthService;
  let http: HttpTestingController;
  let baseCliente: BaseCliente;
  let basePersonal: BaseOffline;
  let volvio: Subject<void>;

  function configurar(): void {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AlmacenOfflineService, useValue: Object.assign(new AlmacenOfflineService(), { base: basePersonal }) },
        { provide: AlmacenClienteOfflineService, useValue: Object.assign(new AlmacenClienteOfflineService(), { base: baseCliente }) },
        { provide: ConectividadService, useValue: { volvioConexion$: volvio.asObservable() } },
      ],
    });
    auth = TestBed.inject(AuthService);
    http = TestBed.inject(HttpTestingController);
  }

  async function iniciarSesion(usuario: UsuarioYo): Promise<void> {
    auth.guardarTokens(TOKENS);
    auth.cargarUsuarioActual().subscribe();
    http.expectOne(`${API}/auth/yo`).flush(usuario);
    await vi.waitFor(async () => {
      expect((await baseCliente.meta.count()) + (await basePersonal.meta.count())).toBeGreaterThan(0);
    });
  }

  beforeEach(() => {
    localStorage.clear();
    const n = ++contador;
    baseCliente = new BaseCliente(`prueba-auth-cliente-${n}`);
    basePersonal = new BaseOffline(`prueba-auth-personal-${n}`);
    volvio = new Subject<void>();
    configurar();
  });

  afterEach(async () => {
    vi.restoreAllMocks();
    localStorage.clear();
    TestBed.resetTestingModule();
    await baseCliente.delete();
    await basePersonal.delete();
  });

  it('guarda el perfil del comprador en SU base (la del cliente) y no en la del personal', async () => {
    await iniciarSesion(comprador());

    expect(await baseCliente.meta.count()).toBe(1);
    expect(await basePersonal.meta.count()).toBe(0);
    expect(await TestBed.inject(ClienteOfflineService).perfilGuardado(7, 5)).toEqual(comprador());
  });

  it('el personal sigue guardando su perfil en la base del personal, no en la del cliente', async () => {
    await iniciarSesion(comprador(6, ['cajero']));

    expect(await basePersonal.meta.count()).toBe(1);
    expect(await baseCliente.meta.count()).toBe(0);
  });

  it('sin red, al reabrir la tienda restaura al comprador desde su perfil guardado y lo marca sin verificar', async () => {
    await iniciarSesion(comprador());
    TestBed.resetTestingModule();
    configurar();
    expect(auth.usuario()).toBeNull();

    const flujo = auth.restaurarSesion();
    expect(flujo).not.toBeNull();
    const resultado = firstValueFrom(flujo!);
    http.expectOne(`${API}/auth/yo`).error(new ProgressEvent('error'), { status: 0, statusText: 'Unknown Error' });
    const usuario = await resultado;

    expect(usuario).toEqual(comprador());
    expect(auth.esSoloCliente()).toBe(true);
    expect(auth.sesionSinVerificar()).toBe(true);
  });

  it('al cerrar sesión borra el perfil y el carrito del comprador, pero conserva sus pedidos aún sin cobrar', async () => {
    await iniciarSesion(comprador());
    const repo = TestBed.inject(ClienteOfflineService).repositorio()!;
    await repo.agregarLinea(linea(1, { empresa_id: 7 }), 5);
    await repo.registrarPedido(pedido(1, { empresa_id: 7 }));
    await repo.registrarPedido(pedido(2, { empresa_id: 7, estado: 'cobrado' }));

    vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    auth.logout();
    await vi.waitFor(async () => expect(await baseCliente.meta.count()).toBe(0));

    expect(await baseCliente.carrito.count()).toBe(0);
    const quedan = await baseCliente.pedidos.toArray();
    expect(quedan.map((p) => p.estado)).toEqual(['pendiente']);
  });
});
