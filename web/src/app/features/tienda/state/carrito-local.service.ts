import { Injectable, computed, effect, inject, signal, untracked } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { MAX_UNIDADES_LINEA, META_SUCURSALES } from '../../../core/offline-cliente/cliente-offline.config';
import type {
  LineaCarritoLocal,
  NuevaLineaLocal,
  SucursalRecordada,
} from '../../../core/offline-cliente/cliente-offline.models';
import { ClienteOfflineService } from '../../../core/offline-cliente/cliente-offline.service';
import { textoDinero, totalDeLineas } from '../../../core/offline-cliente/dinero';
import { CarritoService } from '../data/carrito.service';

export interface ResultadoPaso {
  pasadas: number;
  fallidas: number;
}

/**
 * Carrito LOCAL del cliente: solo existe mientras no hay conexión. Cada línea se guarda en IndexedDB (base del cliente,
 * por empresa y usuario) con los datos para mostrarla sin red. Con conexión el carrito y la compra siguen siendo los del
 * servidor (`CarritoService`), sin cambios.
 *
 * Al volver la red NO se mezcla solo con el del servidor: se queda a la vista, avisa, y el cliente decide entre
 * "Pasar a mi carrito" (cada línea se agrega al del servidor y sale de aquí) o descartarlo. Se vacía también al pagarlo
 * con el PayPal guardado (el pedido en cola se lleva las líneas).
 */
@Injectable({ providedIn: 'root' })
export class CarritoLocalService {
  private readonly cliente = inject(ClienteOfflineService);
  private readonly carritoServidor = inject(CarritoService);

  private readonly lineasState = signal<LineaCarritoLocal[]>([]);
  readonly lineas = this.lineasState.asReadonly();
  readonly cantidadLineas = computed(() => this.lineasState().length);
  readonly cantidadPrendas = computed(() => this.lineasState().reduce((suma, l) => suma + l.cantidad, 0));
  /** Subtotal con los precios guardados, en centavos. */
  readonly subtotalCentavos = computed(() => totalDeLineas(this.lineasState()));
  readonly subtotal = computed(() => textoDinero(this.subtotalCentavos()));

  constructor() {
    // Al cambiar la sesión (entrar, salir, otra persona) se recarga lo de esa persona; sin sesión no hay nada.
    effect(() => {
      this.cliente.alcance();
      untracked(() => void this.cargar());
    });
  }

  /** Lee el carrito local de la sesión actual. Nunca lanza. */
  async cargar(): Promise<void> {
    const repo = this.cliente.repositorio();
    if (repo === null) {
      this.lineasState.set([]);
      return;
    }
    try {
      const lineas = await repo.carrito();
      // Si mientras se leía cambió la sesión, estas líneas ya no son de quien mira.
      if (this.cliente.repositorio()?.alcance.usuarioId === repo.alcance.usuarioId) this.lineasState.set(lineas);
    } catch (error) {
      console.warn('No se pudo leer el carrito local.', error);
    }
  }

  /** Guarda la prenda en el carrito local (suma si la variante ya estaba). Devuelve false si no hay sesión o falló. */
  async agregar(nueva: NuevaLineaLocal): Promise<boolean> {
    const repo = this.cliente.repositorio();
    if (repo === null) return false;
    try {
      await repo.agregarLinea(
        { ...nueva, empresa_id: repo.alcance.empresaId, usuario_id: repo.alcance.usuarioId, agregado_en: new Date().toISOString() },
        MAX_UNIDADES_LINEA,
      );
      await this.cargar();
      return true;
    } catch (error) {
      console.warn('No se pudo guardar la prenda en el carrito local.', error);
      return false;
    }
  }

  async cambiarCantidad(varianteId: number, cantidad: number): Promise<void> {
    const repo = this.cliente.repositorio();
    if (repo === null) return;
    try {
      await repo.cambiarCantidad(varianteId, Math.min(cantidad, MAX_UNIDADES_LINEA));
    } catch (error) {
      console.warn('No se pudo cambiar la cantidad en el carrito local.', error);
    }
    await this.cargar();
  }

  async quitar(varianteId: number): Promise<void> {
    await this.cambiarCantidad(varianteId, 0);
  }

  async vaciar(): Promise<void> {
    const repo = this.cliente.repositorio();
    if (repo === null) return;
    try {
      await repo.vaciarCarrito();
    } catch (error) {
      console.warn('No se pudo vaciar el carrito local.', error);
    }
    await this.cargar();
  }

  /**
   * "Pasar a mi carrito": agrega al carrito del servidor cada línea, una por una, y la quita de aquí si el servidor la
   * aceptó. Las que el servidor rechaza (sin stock, ya no existe) se quedan para que el cliente decida.
   */
  async pasarAlServidor(): Promise<ResultadoPaso> {
    let pasadas = 0;
    let fallidas = 0;
    for (const linea of [...this.lineasState()]) {
      try {
        await firstValueFrom(this.carritoServidor.agregar(linea.variante_id, linea.cantidad));
        await this.quitar(linea.variante_id);
        pasadas += 1;
      } catch {
        fallidas += 1;
      }
    }
    return { pasadas, fallidas };
  }

  // ---- Sucursales recordadas (para elegir dónde retirar sin red) -----------------------------------------------------------

  async recordarSucursales(sucursales: SucursalRecordada[]): Promise<void> {
    const repo = this.cliente.repositorio();
    if (repo === null) return;
    try {
      await repo.guardarMeta(META_SUCURSALES, sucursales.map(({ id, nombre, es_deposito }) => ({ id, nombre, es_deposito })));
    } catch (error) {
      console.warn('No se pudieron recordar las sucursales.', error);
    }
  }

  async sucursalesRecordadas(): Promise<SucursalRecordada[]> {
    const repo = this.cliente.repositorio();
    if (repo === null) return [];
    try {
      return (await repo.leerMeta<SucursalRecordada[]>(META_SUCURSALES)) ?? [];
    } catch {
      return [];
    }
  }
}
