import { HttpErrorResponse } from '@angular/common/http';
import { codigoFuncional } from '../errores-funcionales';
import type { Reembolso } from './ventas.models';

/**
 * Cierre de caja por turno (backend `/api/v1/caja`). La caja es de la SUCURSAL: a lo sumo un turno abierto por sucursal.
 * Los montos llegan como TEXTO decimal ("150.00") y las fechas como instantes UTC con "Z".
 */

export type EstadoTurno = 'abierta' | 'cerrada' | 'cerrada_auto';

/** Lo que entró y salió de la caja durante el turno. Solo lo ve un supervisor o quien ya cerró el turno. */
export interface ResumenTurno {
  /** Efectivo cobrado en la sucursal durante el turno. */
  ventas_efectivo: string;
  cantidad_ventas: number;
  /** Efectivo devuelto durante el turno (se resta del esperado). */
  reembolsos_efectivo: string;
  /** QR, tarjeta y transferencia: informativo, no entra al cajón. */
  ventas_otros_metodos: string;
  /** Compras online del día: informativo. */
  ventas_online: string;
  cantidad_ventas_online: number;
  monto_esperado: string;
}

export interface Turno {
  id: number;
  sucursal_id: number;
  sucursal_nombre: string;
  estado: EstadoTurno;
  apertura_en: string;
  abierto_por_id: number;
  abierto_por_nombre: string;
  monto_inicial: string;
  observacion_apertura: string | null;
  cierre_en: string | null;
  cerrado_por_id: number | null;
  cerrado_por_nombre: string | null;
  /** El turno se cerró solo al terminar el día, sin que nadie contara el cajón. */
  cierre_automatico: boolean;
  efectivo_contado: string | null;
  /** Contado menos esperado: positivo = sobrante, negativo = faltante. */
  diferencia: string | null;
  pendientes_declarados: number;
  observacion_cierre: string | null;
  conteo_en: string | null;
  conteo_por_nombre: string | null;
  observacion_conteo: string | null;
  /** Hasta cuándo un supervisor puede completar el conteo (solo en `cerrada_auto` sin conteo). */
  conteo_hasta: string | null;
  /** Null para un cajero con el turno abierto (cierre ciego). */
  monto_esperado: string | null;
  resumen: ResumenTurno | null;
}

export interface TurnoDetalle extends Turno {
  /** Esperado recalculado hoy menos el guardado al cerrar: positivo = llegaron ventas sincronizadas tarde. */
  ajuste_posterior: string | null;
  reembolsos: Reembolso[];
}

/** `GET /caja/turnos/actual`. */
export interface TurnoActual {
  sucursal_id: number;
  turno: Turno | null;
  /** El monto con que cerró el último turno de la sucursal, para prellenar el siguiente. */
  monto_inicial_sugerido: string | null;
}

/** Una fila de "Cajas de hoy" (`GET /caja/turnos/estado`). */
export interface EstadoCajaSucursal {
  sucursal_id: number;
  sucursal_nombre: string;
  turno: Turno | null;
}

export interface TurnoAbrir {
  /** Solo el administrador (alcance global) la manda; el cajero usa la suya. */
  sucursal_id?: number;
  monto_inicial: string;
  observacion?: string | null;
}

export interface TurnoCerrar {
  efectivo_contado: string;
  observacion?: string | null;
  /** Operaciones guardadas sin conexión en este equipo que todavía no llegaron al servidor. */
  pendientes_sin_sincronizar?: number;
}

export interface CompletarConteo {
  efectivo_contado: string;
  /** De 3 a 300 caracteres. */
  observacion: string;
}

export interface ConsultaTurnos {
  sucursal_id?: number | null;
  estado?: EstadoTurno | null;
  /** Día de Bolivia, `AAAA-MM-DD`, incluido. */
  desde?: string | null;
  hasta?: string | null;
  pagina?: number;
  tamanio?: number;
}

/** Mensajes para el usuario de los errores funcionales del cierre de caja (los códigos técnicos nunca se muestran). */
const MENSAJES_ERROR_CAJA: Readonly<Record<string, string>> = {
  turno_ya_abierto: 'Esta sucursal ya tiene un turno abierto. Actualiza la pantalla para verlo.',
  observacion_requerida: 'Hay una diferencia entre lo contado y lo esperado: escribe una observación para poder cerrar.',
  turno_cerrado: 'Este turno ya está cerrado. Actualiza la pantalla.',
  turno_de_otro_cajero: 'Este turno lo abrió otra persona y no tienes permiso para cerrarlo.',
  conteo_no_aplica: 'Este turno no necesita conteo: solo se completa en un turno que se cerró solo.',
  conteo_ya_registrado: 'El conteo de este turno ya se registró y no se puede cambiar.',
  conteo_fuera_de_plazo: 'Pasó el plazo de 72 horas para completar el conteo de este turno.',
};

/**
 * El texto que se le muestra a la persona cuando una operación del cierre de caja falla: el mensaje propio del código
 * funcional, si lo hay; si no, el que explicó el servidor (`mensaje` o `detail` en texto) y, por último, uno genérico.
 */
export function mensajeErrorCaja(error: unknown, porDefecto: string): string {
  const codigo = codigoFuncional(error);
  if (codigo !== null && Object.hasOwn(MENSAJES_ERROR_CAJA, codigo)) return MENSAJES_ERROR_CAJA[codigo];
  if (error instanceof HttpErrorResponse) {
    const cuerpo = error.error as { mensaje?: unknown; detail?: unknown } | null;
    if (typeof cuerpo?.mensaje === 'string' && cuerpo.mensaje.trim()) return cuerpo.mensaje;
    if (typeof cuerpo?.detail === 'string' && cuerpo.detail.trim()) return cuerpo.detail;
    if (error.status === 0) return 'Sin conexión con el servidor. Inténtalo de nuevo.';
  }
  return porDefecto;
}

/** Monto escrito por la persona -> texto con 2 decimales para el servidor; null si no es un monto válido (>= 0). */
export function montoParaServidor(valor: number | string | null | undefined): string | null {
  if (valor === null || valor === undefined || valor === '') return null;
  const numero = typeof valor === 'number' ? valor : Number(String(valor).replace(',', '.'));
  if (!Number.isFinite(numero) || numero < 0) return null;
  return numero.toFixed(2);
}

/** Clase del chip según la diferencia: verde 0, ámbar sobrante, rojo faltante. */
export function claseDiferencia(diferencia: string | number | null): string {
  if (diferencia === null) return '';
  const numero = Number(diferencia);
  if (numero === 0) return 'fs-chip--exito';
  return numero > 0 ? 'fs-chip--advertencia' : 'fs-chip--error';
}

/** Texto de la diferencia: "Cuadra", "Sobran Bs 5.00" o "Faltan Bs 5.00". */
export function textoDiferencia(diferencia: string | number | null): string {
  if (diferencia === null) return '—';
  const numero = Number(diferencia);
  if (numero === 0) return 'Cuadra';
  const monto = Math.abs(numero).toFixed(2);
  return numero > 0 ? `Sobran Bs ${monto}` : `Faltan Bs ${monto}`;
}
