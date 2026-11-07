import { HttpClient, HttpContext, HttpErrorResponse } from '@angular/common/http';
import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ConectividadService } from '../conectividad.service';
import { instanteServidor } from '../date-utils';
import { codigoFuncional } from '../errores-funcionales';
import { SIN_TOAST_ERROR } from '../http-contexts';
import { PlanService } from '../plan.service';
import {
  MAX_PAGINAS_DESCARGA,
  PAGINA_CATALOGO,
  PAGINA_CLIENTES,
  PAGINA_STOCK,
  UMBRAL_DESACTUALIZADO_HORAS,
} from './offline.config';
import type {
  AlcanceOffline,
  ClientePaquete,
  PaqueteCatalogo,
  PaqueteClientes,
  PaqueteLocal,
  PaqueteManifiesto,
  PaqueteStock,
  ProductoPaquete,
  StockPaquete,
} from './offline.models';
import { SesionOfflineService } from './sesion-offline.service';

export type EstadoDatosOffline = 'sin_datos' | 'vigentes' | 'desactualizados';
export type ErrorDescargaOffline = 'sin_conexion' | 'plan_sin_offline' | 'suscripcion' | 'error';

/** Cada cuánto se recalcula si los datos ya están desactualizados (no hace falta más fino: el umbral es de horas). */
export const INTERVALO_ESTADO_DATOS_MS = 60_000;

const MS_POR_HORA = 3_600_000;

/** El servidor respondió, pero lo recibido no es un paquete completo y coherente: no se reemplaza nada. */
class PaqueteIncompletoError extends Error {}

/**
 * Descarga del paquete para operar sin conexión (E14a). Pide al servidor el manifiesto, el catálogo, el stock de CADA
 * sucursal y los clientes (todo paginado), lo junta en memoria y recién entonces lo guarda con UNA llamada atómica al
 * repositorio: si algo falla a la mitad, queda el paquete anterior intacto.
 *
 * Todas las peticiones llevan `SIN_TOAST_ERROR`: el estado de la descarga se muestra con `errorDescarga`, no con un
 * aviso rojo cada vez que no hay red.
 */
@Injectable({ providedIn: 'root' })
export class PaqueteOfflineService {
  private readonly http = inject(HttpClient);
  private readonly sesion = inject(SesionOfflineService);
  private readonly conectividad = inject(ConectividadService);
  private readonly plan = inject(PlanService);

  private readonly _ultimaDescarga = signal<string | null>(null);
  private readonly _umbralHoras = signal<number | null>(null);
  private readonly _descargando = signal(false);
  private readonly _errorDescarga = signal<ErrorDescargaOffline | null>(null);
  /** "Ahora" como signal: así `estadoDatos` se recalcula con el tiempo sin que nadie lo pida. */
  private readonly ahora = signal(Date.now());

  private enCurso: Promise<boolean> | null = null;

  /** `generado_en` (ISO) del servidor en la última descarga completa de esta empresa, o null si nunca hubo. */
  readonly ultimaDescarga = this._ultimaDescarga.asReadonly();
  readonly descargando = this._descargando.asReadonly();
  readonly errorDescarga = this._errorDescarga.asReadonly();
  /** Horas tras las cuales los datos se consideran desactualizados (las del servidor, o las de `offline.config`). */
  readonly umbralHoras = computed(() => this._umbralHoras() ?? UMBRAL_DESACTUALIZADO_HORAS);
  readonly estadoDatos = computed<EstadoDatosOffline>(() => {
    const ultima = this._ultimaDescarga();
    if (ultima === null) return 'sin_datos';
    const instante = instanteServidor(ultima).getTime();
    if (Number.isNaN(instante)) return 'desactualizados';
    return this.ahora() - instante > this.umbralHoras() * MS_POR_HORA ? 'desactualizados' : 'vigentes';
  });

  constructor() {
    if (typeof setInterval === 'function') {
      const intervalo = setInterval(() => this.recalcular(), INTERVALO_ESTADO_DATOS_MS);
      inject(DestroyRef).onDestroy(() => clearInterval(intervalo));
    }
  }

  /** Vuelve a leer el reloj: lo llama el intervalo; también sirve cuando la pantalla vuelve a primer plano. */
  recalcular(): void {
    this.ahora.set(Date.now());
  }

  /**
   * Lee de IndexedDB cuándo se descargó por última vez el paquete de la empresa de la sesión (y con qué umbral).
   * Nunca lanza: si no hay sesión o la base no se puede abrir, queda en "sin datos".
   */
  async cargarEstado(): Promise<void> {
    const alcance = this.sesion.alcance();
    const repo = this.sesion.repositorio();
    let ultima: string | null = null;
    let umbral: number | null = null;
    if (repo !== null) {
      try {
        ultima = (await repo.ultimaDescarga()) ?? null;
        umbral = (await repo.umbralHoras()) ?? null;
      } catch {
        ultima = null;
        umbral = null;
      }
    }
    // Si mientras se leía cambió la sesión (otro usuario), esta lectura ya no vale.
    if (!this.mismoAlcance(alcance)) return;
    this._ultimaDescarga.set(ultima);
    this._umbralHoras.set(umbral !== null && Number.isFinite(umbral) && umbral > 0 ? umbral : null);
    this._errorDescarga.set(null);
    this.recalcular();
  }

  /**
   * Descarga el paquete y reemplaza el anterior. Nunca lanza: devuelve `true` solo si reemplazó. Dos llamadas a la vez
   * comparten la misma descarga.
   */
  descargar(): Promise<boolean> {
    this.enCurso ??= this.descargarUnaVez().finally(() => {
      this.enCurso = null;
      this._descargando.set(false);
    });
    return this.enCurso;
  }

  /** Descarga solo si no hay datos o están desactualizados, hay conexión y el plan lo permite. */
  async descargarSiHaceFalta(): Promise<boolean> {
    if (this.sesion.alcance() === null) return false;
    if (this.conectividad.estado() !== 'en_linea') return false;
    if (!this.plan.estadoActivo() || !this.plan.incluye('operacion_offline')) return false;
    if (this.estadoDatos() === 'vigentes') return false;
    return this.descargar();
  }

  // ---- Interno --------------------------------------------------------------------------------------------------------------

  private async descargarUnaVez(): Promise<boolean> {
    this._descargando.set(true);
    this._errorDescarga.set(null);
    const alcance = this.sesion.alcance();
    const repo = this.sesion.repositorio();
    if (alcance === null || repo === null) {
      this._errorDescarga.set('error');
      return false;
    }
    try {
      const paquete = await this.pedirPaquete();
      await repo.reemplazarReferencia(paquete);
      if (this.mismoAlcance(alcance)) {
        this._ultimaDescarga.set(paquete.generadoEn);
        this._umbralHoras.set(umbralValido(paquete.avisoDesactualizadoHoras));
        this.recalcular();
      }
      return true;
    } catch (error) {
      if (this.mismoAlcance(alcance)) this._errorDescarga.set(clasificarError(error));
      return false;
    }
  }

  private mismoAlcance(alcance: AlcanceOffline | null): boolean {
    const actual = this.sesion.alcance();
    return actual?.empresaId === alcance?.empresaId && actual?.usuarioId === alcance?.usuarioId;
  }

  /** Pide todo al servidor y lo junta en memoria. No escribe nada en IndexedDB. */
  private async pedirPaquete(): Promise<PaqueteLocal> {
    const manifiesto = await this.get<PaqueteManifiesto>('/sincronizacion/paquete');

    const catalogo = await this.paginar<PaqueteCatalogo, ProductoPaquete>(
      '/sincronizacion/paquete/catalogo',
      'desde_id',
      PAGINA_CATALOGO,
      {},
      (pagina) => pagina.siguiente_desde_id,
    );
    if (catalogo.paginas[0].total !== catalogo.items.length) {
      throw new PaqueteIncompletoError(
        `El catálogo anunció ${catalogo.paginas[0].total} productos y llegaron ${catalogo.items.length}.`,
      );
    }

    // El personal puede consultar el stock de cualquier sucursal (incluidos los depósitos): se baja el de todas.
    const stock: PaqueteLocal['stock'] = [];
    for (const sucursal of manifiesto.sucursales) {
      const porSucursal = await this.paginar<PaqueteStock, StockPaquete>(
        '/sincronizacion/paquete/stock',
        'desde_variante_id',
        PAGINA_STOCK,
        { sucursal_id: sucursal.id },
        (pagina) => pagina.siguiente_desde_variante_id,
      );
      if (porSucursal.paginas.some((p) => p.incremental)) {
        throw new PaqueteIncompletoError('El servidor mandó un stock incremental en una descarga completa.');
      }
      stock.push({
        sucursalId: sucursal.id,
        generadoEn: porSucursal.paginas[0].generado_en,
        items: porSucursal.items,
      });
    }

    const clientes = await this.paginar<PaqueteClientes, ClientePaquete>(
      '/sincronizacion/paquete/clientes',
      'desde_id',
      PAGINA_CLIENTES,
      {},
      (pagina) => pagina.siguiente_desde_id,
    );
    if (clientes.paginas[0].total !== clientes.items.length) {
      throw new PaqueteIncompletoError(
        `La lista de clientes anunció ${clientes.paginas[0].total} y llegaron ${clientes.items.length}.`,
      );
    }

    return {
      empresa: manifiesto.empresa,
      generadoEn: catalogo.paginas[0].generado_en,
      avisoDesactualizadoHoras: manifiesto.aviso_desactualizado_horas,
      sucursales: manifiesto.sucursales,
      categorias: manifiesto.referencia.categorias,
      tallas: manifiesto.referencia.tallas,
      colores: manifiesto.referencia.colores,
      productos: catalogo.items,
      stock,
      clientes: clientes.items,
      reglas: manifiesto.reglas,
    };
  }

  /**
   * Recorre un recurso paginado por clave (`siguiente_*` = null en la última página). El cursor tiene que avanzar y hay
   * un tope de páginas: un servidor que nunca dijera "última" no deja la descarga en un bucle.
   */
  private async paginar<P extends { items: I[] }, I>(
    ruta: string,
    nombreCursor: string,
    limite: number,
    fijos: Record<string, number>,
    siguiente: (pagina: P) => number | null,
  ): Promise<{ paginas: P[]; items: I[] }> {
    const paginas: P[] = [];
    const items: I[] = [];
    let cursor: number | null = null;
    for (let n = 0; n < MAX_PAGINAS_DESCARGA; n++) {
      const params: Record<string, number> = { ...fijos, limite };
      if (cursor !== null) params[nombreCursor] = cursor;
      const pagina: P = await this.get<P>(ruta, params);
      paginas.push(pagina);
      items.push(...pagina.items);
      const proximo = siguiente(pagina);
      if (proximo === null) return { paginas, items };
      if (cursor !== null && proximo <= cursor) {
        throw new PaqueteIncompletoError(`El servidor repitió la página de ${ruta}.`);
      }
      cursor = proximo;
    }
    throw new PaqueteIncompletoError(`Demasiadas páginas en ${ruta} (más de ${MAX_PAGINAS_DESCARGA}).`);
  }

  private get<T>(ruta: string, params?: Record<string, number>): Promise<T> {
    const context = new HttpContext().set(SIN_TOAST_ERROR, true);
    return firstValueFrom(this.http.get<T>(`${environment.apiUrl}${ruta}`, { context, params }));
  }
}

function umbralValido(horas: number | undefined): number | null {
  return typeof horas === 'number' && Number.isFinite(horas) && horas > 0 ? horas : null;
}

function clasificarError(error: unknown): ErrorDescargaOffline {
  if (error instanceof HttpErrorResponse) {
    if (error.status === 0) return 'sin_conexion';
    if (error.status === 403) {
      const codigo = codigoFuncional(error);
      if (codigo === 'plan_no_incluye_funcionalidad') return 'plan_sin_offline';
      if (codigo === 'suscripcion_no_activa') return 'suscripcion';
    }
  }
  return 'error';
}
