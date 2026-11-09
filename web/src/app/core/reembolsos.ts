import type { EstadoReembolso, Reembolso } from './models/ventas.models';

/** A quién le habla el texto: la persona que compró ("a tu PayPal") o el personal de la tienda ("al PayPal del cliente"). */
export type VistaReembolso = 'cliente' | 'personal';

/** Cómo se devolvió el dinero, según el método del pago original. */
export function comoSeDevolvio(metodo: string, vista: VistaReembolso = 'cliente'): string {
  const personal = vista === 'personal';
  switch (metodo) {
    case 'efectivo':
      return 'en efectivo, en la tienda';
    case 'paypal':
      return personal ? 'al PayPal del cliente' : 'a tu PayPal';
    case 'qr':
    case 'qr_online':
      return 'por QR';
    case 'tarjeta':
      return personal ? 'a la tarjeta del cliente' : 'a tu tarjeta';
    case 'transferencia':
      return 'por transferencia';
    default:
      return personal ? 'por el mismo medio con que pagó el cliente' : 'por el mismo medio con que pagaste';
  }
}

export interface EstadoReembolsoVista {
  texto: string;
  /** Clase del chip (`fs-chip--*`); vacía = neutro. */
  clase: string;
}

/**
 * El estado en palabras. El cliente nunca ve un fallo: un reembolso fallido se le muestra "En proceso" (el personal lo
 * reintenta). El personal sí lo ve, con la causa corta si el servidor la manda.
 */
export function estadoReembolso(estado: EstadoReembolso, vista: VistaReembolso = 'cliente'): EstadoReembolsoVista {
  if (estado === 'reembolsado') return { texto: 'Reembolsado', clase: 'fs-chip--exito' };
  if (estado === 'fallido' && vista === 'personal') return { texto: 'No se pudo reembolsar', clase: 'fs-chip--error' };
  return { texto: 'En proceso', clase: 'fs-chip--advertencia' };
}

/** Un reembolso que aún no salió y que el personal puede volver a intentar. */
export function sePuedeReintentar(reembolso: Pick<Reembolso, 'estado'>): boolean {
  return reembolso.estado === 'pendiente' || reembolso.estado === 'fallido';
}

/** El mismo reembolso, sin duplicados, con el nuevo (por id) en lugar del viejo. */
export function reemplazarReembolso(lista: readonly Reembolso[], nuevo: Reembolso): Reembolso[] {
  return lista.some((r) => r.id === nuevo.id) ? lista.map((r) => (r.id === nuevo.id ? nuevo : r)) : [...lista, nuevo];
}
