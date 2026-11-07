import { HttpErrorResponse } from '@angular/common/http';
import { instanteServidor } from '../../core/date-utils';
import { ErrorLeido, leerTextoBlob } from '../../core/utils/http-blob';
import { NombreIcono } from '../../shared/icono/iconos';

// ---- Estados del historial ---------------------------------------------------------------------------------------------

export interface VistaEstadoCopia {
  texto: string;
  /** Clase del chip (`fs-chip--*`); vacía = neutro. */
  clase: string;
  icono: NombreIcono;
}

/** Cada estado se dice con ícono, texto y color (nunca solo color). */
export function vistaEstadoCopia(estado: string): VistaEstadoCopia {
  switch (estado) {
    case 'completada':
      return { texto: 'Completada', clase: 'fs-chip--exito', icono: 'check' };
    case 'fallida':
      return { texto: 'Fallida', clase: 'fs-chip--error', icono: 'alerta' };
    case 'en_proceso':
      return { texto: 'En curso', clase: 'fs-chip--advertencia', icono: 'reloj' };
    default:
      return { texto: estado, clase: '', icono: 'reloj' };
  }
}

const MOTIVOS_FALLO: Record<string, string> = {
  copia_demasiado_grande: 'Los datos superaron el tamaño máximo permitido para una copia.',
  copia_tiempo_agotado: 'Tardó más de lo permitido y se canceló.',
  servidor_ocupado: 'El servidor estaba ocupado en ese momento.',
  abandonada: 'Se interrumpió antes de terminar.',
  error_interno: 'Ocurrió un error en el servidor.',
};

/** El motivo de una copia fallida en lenguaje claro; nunca muestra el código crudo. */
export function textoMotivoFallo(motivo: string | null | undefined): string {
  return (motivo && MOTIVOS_FALLO[motivo]) || 'No se pudo completar la copia.';
}

// ---- Formatos -----------------------------------------------------------------------------------------------------------

/** 1536 -> "1,5 KB"; 1572864 -> "1,5 MB". Sin dato -> "—". */
export function formatearTamano(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const decimal = (n: number) => n.toLocaleString('es-BO', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  if (bytes < 1024 * 1024) return `${decimal(bytes / 1024)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${decimal(bytes / (1024 * 1024))} MB`;
  return `${decimal(bytes / (1024 * 1024 * 1024))} GB`;
}

/** Las fechas del servidor son UTC ("Z"); el `date` pipe las muestra en la hora local de quien mira. Ver `instanteServidor`. */
export const fechaDeUtc = instanteServidor;

export const LARGO_CHECKSUM_CORTO = 12;

export function checksumCorto(checksum: string | null | undefined): string {
  return checksum ? checksum.slice(0, LARGO_CHECKSUM_CORTO) : '—';
}

/** `orden_compra` -> "Orden compra": los nombres de tabla se dicen sin guiones bajos. */
export function nombreLegible(identificador: string): string {
  const texto = identificador.replace(/_/g, ' ').trim();
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

// ---- Errores al crear o consultar --------------------------------------------------------------------------------------

export type ClaseErrorCopia =
  | 'plan' // 403 plan_no_incluye_funcionalidad
  | 'suscripcion' // 403 suscripcion_no_activa
  | 'rol' // 403 sin permiso
  | 'en_curso' // 409 copia_en_curso
  | 'demasiado_grande' // 413
  | 'limite' // 429
  | 'tiempo' // 504
  | 'ocupado' // 503
  | 'fallida' // 500
  | 'sin_conexion' // status 0
  | 'otro';

export interface ErrorCopia {
  clase: ClaseErrorCopia;
  status: number;
  mensaje: string;
  /** Estado de la suscripción cuando el servidor lo informa (`suscripcion_no_activa`). */
  estadoSuscripcion: string | null;
  /** Verdadero si tiene sentido ofrecer [Reintentar]. */
  reintentable: boolean;
}

export const MENSAJE_EN_CURSO = 'Ya hay una copia en curso; espera a que termine.';
export const MENSAJE_LIMITE = 'Pediste demasiadas copias seguidas; espera un momento e inténtalo de nuevo.';
export const MENSAJE_OCUPADO = 'El servidor está ocupado en este momento. Inténtalo de nuevo en unos minutos.';
export const MENSAJE_TIEMPO = 'La copia tardó más de lo permitido y se canceló. Inténtalo de nuevo.';
export const MENSAJE_FALLIDA = 'No se pudo crear la copia por un error del servidor. Inténtalo de nuevo.';
export const MENSAJE_SIN_CONEXION = 'No se pudo conectar con el servidor. Revisa tu conexión.';
export const MENSAJE_SOLO_ADMINISTRADOR = 'Solo el administrador de la empresa puede crear copias.';

/** Mensaje del 413, con el límite si el servidor lo informó. */
export function mensajeDemasiadoGrande(limiteBytes: number | null): string {
  const limite = limiteBytes !== null ? ` (el límite es ${formatearTamano(limiteBytes)})` : '';
  return `Los datos de tu empresa superan el tamaño máximo de una copia${limite}.`;
}

/** Convierte un error ya leído (`leerErrorBlob`) en la categoría que la pantalla sabe explicar. Síncrona y sin efectos. */
export function clasificarErrorCopia(leido: ErrorLeido, limiteBytes: number | null = null, estado: string | null = null): ErrorCopia {
  const hacer = (clase: ClaseErrorCopia, mensaje: string, reintentable = false): ErrorCopia => ({
    clase,
    status: leido.status,
    mensaje,
    estadoSuscripcion: estado,
    reintentable,
  });

  if (leido.status === 0) return hacer('sin_conexion', MENSAJE_SIN_CONEXION, true);
  if (leido.status === 429) return hacer('limite', MENSAJE_LIMITE);
  if (leido.status === 403) {
    if (leido.codigo === 'plan_no_incluye_funcionalidad') return hacer('plan', 'Tu plan no incluye copias de seguridad.');
    if (leido.codigo === 'suscripcion_no_activa') return hacer('suscripcion', 'Tu suscripción no está activa.');
    return hacer('rol', MENSAJE_SOLO_ADMINISTRADOR);
  }
  if (leido.status === 409 && leido.codigo === 'copia_en_curso') return hacer('en_curso', MENSAJE_EN_CURSO);
  if (leido.status === 413) return hacer('demasiado_grande', mensajeDemasiadoGrande(limiteBytes));
  if (leido.status === 503) return hacer('ocupado', MENSAJE_OCUPADO, true);
  if (leido.status === 504) return hacer('tiempo', MENSAJE_TIEMPO, true);
  if (leido.status === 500) return hacer('fallida', MENSAJE_FALLIDA, true);
  return hacer('otro', leido.mensaje, true);
}

/** `limite_bytes` del cuerpo de un 413 (que llega como Blob); null si no viene o no se puede leer. Nunca lanza. */
export async function limiteBytesDeError(error: unknown): Promise<number | null> {
  const cuerpo: unknown = error instanceof HttpErrorResponse ? error.error : error;
  try {
    const objeto: unknown = cuerpo instanceof Blob ? JSON.parse(await leerTextoBlob(cuerpo)) : cuerpo;
    const valor = (objeto as { limite_bytes?: unknown } | null)?.limite_bytes;
    return typeof valor === 'number' && Number.isFinite(valor) && valor > 0 ? valor : null;
  } catch {
    return null;
  }
}

// ---- Portapapeles -------------------------------------------------------------------------------------------------------

/** Copia el texto con la API del navegador o, si no está o la rechazan, con un campo temporal. No guarda nada. */
export async function copiarAlPortapapeles(texto: string): Promise<boolean> {
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(texto);
      return true;
    }
  } catch {
    // Cae al respaldo.
  }
  try {
    if (typeof document === 'undefined' || typeof document.execCommand !== 'function') return false;
    const campo = document.createElement('textarea');
    campo.value = texto;
    campo.setAttribute('readonly', '');
    campo.style.position = 'fixed';
    campo.style.opacity = '0';
    document.body.appendChild(campo);
    campo.select();
    const copiado = document.execCommand('copy');
    campo.remove();
    return copiado;
  } catch {
    return false;
  }
}
