import { Injectable } from '@angular/core';

/** Tipos de notificación cuya `referencia_id` es el id de una venta: para el cliente, todos hablan del mismo hecho. */
export const TIPOS_DE_VENTA = ['compra_confirmada', 'pedido_diferido'] as const;

/** El aviso de un hecho que le pasó a una compra (el pago, el cobro de un pedido sin conexión...). */
export function claveDeVenta(ventaId: number): string {
  return `venta:${ventaId}`;
}

/**
 * La clave con que se reconoce un aviso: `venta:{id}` si habla de una compra (así `compra_confirmada` y
 * `pedido_diferido` de la misma venta cuentan como UN solo aviso) y `notif:{id}` si es una notificación suelta.
 * `null` si no hay nada con qué reconocerlo.
 */
export function claveDeAviso(tipo: string | null | undefined, referenciaId: number | null, notificacionId?: number | null): string | null {
  if (tipo && (TIPOS_DE_VENTA as readonly string[]).includes(tipo) && referenciaId !== null && Number.isFinite(referenciaId)) {
    return claveDeVenta(referenciaId);
  }
  if (notificacionId !== null && notificacionId !== undefined && Number.isFinite(notificacionId)) return `notif:${notificacionId}`;
  return null;
}

/**
 * Lo que ya se le avisó a la persona en esta sesión, para que un mismo hecho no salga dos veces en pantalla: el toast
 * del pedido sin conexión cobrado, el aviso push en primer plano y el panel "¡Pago aprobado!" pueden llegar por
 * caminos distintos para la misma compra, y gana el primero. Vive en memoria y se vacía al cerrar la sesión.
 */
@Injectable({ providedIn: 'root' })
export class AvisosMostradosService {
  private static readonly MAXIMO = 200;
  private readonly claves = new Set<string>();

  /** Anota el aviso. Devuelve `true` si es la primera vez (hay que mostrarlo) y `false` si ya se había avisado. */
  registrar(clave: string | null): boolean {
    // Sin clave no hay cómo reconocerlo: se muestra siempre, como antes.
    if (clave === null) return true;
    if (this.claves.has(clave)) return false;
    if (this.claves.size >= AvisosMostradosService.MAXIMO) {
      const masViejo = this.claves.values().next().value;
      if (masViejo !== undefined) this.claves.delete(masViejo);
    }
    this.claves.add(clave);
    return true;
  }

  /** ¿Ya se avisó? No anota nada. */
  yaAvisado(clave: string): boolean {
    return this.claves.has(clave);
  }

  /** Cambió la sesión: lo avisado a la persona anterior no cuenta para la nueva. */
  limpiar(): void {
    this.claves.clear();
  }
}
