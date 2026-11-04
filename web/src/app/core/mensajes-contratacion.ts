import { HttpErrorResponse } from '@angular/common/http';
import { codigoFuncional } from './errores-funcionales';

/** Un error de la contratación ya traducido para mostrarlo en la propia pantalla (sin toast, sin códigos técnicos). */
export interface ErrorContratacion {
  /** Código estable (del backend o propio: `sin_conexion`, `nombre_repetido`, `datos_invalidos`...). */
  codigo: string;
  mensaje: string;
  status: number;
  /** Repetir la misma petición puede funcionar (sin red, PayPal caído, demasiados intentos). */
  reintentable: boolean;
}

const MENSAJES: Readonly<Record<string, string>> = {
  sin_conexion: 'No pudimos conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.',
  demasiados_intentos: 'Hiciste demasiados intentos. Espera unos minutos e inténtalo de nuevo.',
  plan_sin_precio: 'Este plan todavía no tiene precio publicado, así que no se puede contratar. Elige otro plan.',
  nombre_empresa_reservado: 'Ese nombre de empresa no se puede usar. Elige otro.',
  nombre_repetido: 'Ya existe una empresa con ese nombre. Elige otro.',
  prueba_ya_usada: 'Este correo ya usó su prueba gratuita. Puedes contratar el plan con el botón "Contratar ahora".',
  plan_no_encontrado: 'Ese plan ya no está disponible. Elige otro.',
  plan_inactivo: 'Ese plan ya no está disponible. Elige otro.',
  paypal_no_disponible: 'PayPal no responde en este momento. No se cobró nada: inténtalo de nuevo en unos minutos.',
  tipo_cambio_no_configurado: 'No pudimos calcular el cobro en este momento. Inténtalo más tarde.',
  pago_no_aprobado:
    'Todavía no vemos tu pago aprobado en PayPal. Si ya lo aprobaste, espera unos segundos y comprueba de nuevo.',
  pago_no_coincide: 'El pago que recibimos no coincide con tu pedido, así que no lo cobramos. Empieza de nuevo.',
  pagado_sin_empresa:
    'Recibimos tu pago, pero no pudimos terminar de crear tu empresa. No tienes que pagar otra vez: escríbenos a soporte y lo resolvemos o te reembolsamos.',
  pedido_cancelado: 'Este pedido fue cancelado. Empieza uno nuevo.',
  pedido_vencido: 'Este pedido venció sin pagarse. Empieza uno nuevo.',
  pedido_fallido: 'Este pedido no se pudo completar. Empieza uno nuevo.',
  pedido_ya_pagado: 'Este pedido ya fue pagado, así que no se puede cancelar.',
  pedido_no_encontrado: 'No encontramos este pedido. Puede haber vencido: empieza uno nuevo.',
  datos_invalidos: 'Revisa los datos del formulario: alguno no es válido.',
  error_inesperado: 'Algo salió mal. Inténtalo de nuevo en unos minutos.',
};

const REINTENTABLES: ReadonlySet<string> = new Set([
  'sin_conexion',
  'demasiados_intentos',
  'paypal_no_disponible',
  'tipo_cambio_no_configurado',
  'error_inesperado',
]);

/** Texto del código propio o del backend; null si no hay uno conocido. */
export function mensajeDeContratacion(codigo: string): string | null {
  return Object.hasOwn(MENSAJES, codigo) ? MENSAJES[codigo] : null;
}

function detalleTexto(error: HttpErrorResponse): string {
  const detalle = (error.error as { detail?: unknown } | null)?.detail;
  return typeof detalle === 'string' ? detalle : '';
}

/**
 * Convierte la falla de una petición de contratación en algo mostrable. El backend responde errores funcionales
 * `{detail, codigo, mensaje}`; el 409 de "nombre repetido" y el 404 de un plan o pedido vienen solo con `detail`.
 */
export function errorDeContratacion(error: unknown): ErrorContratacion {
  if (!(error instanceof HttpErrorResponse)) return construir('error_inesperado', 0);
  const status = error.status;
  if (status === 0) return construir('sin_conexion', 0);
  if (status === 429) return construir('demasiados_intentos', 429);

  const codigo = codigoFuncional(error);
  if (codigo !== null) {
    const conocido = mensajeDeContratacion(codigo);
    const delServidor = (error.error as { mensaje?: unknown } | null)?.mensaje;
    return {
      codigo,
      status,
      mensaje: conocido ?? (typeof delServidor === 'string' && delServidor !== '' ? delServidor : MENSAJES['error_inesperado']),
      reintentable: REINTENTABLES.has(codigo),
    };
  }

  if (status === 409 && /nombre/i.test(detalleTexto(error))) return construir('nombre_repetido', status);
  if (status === 404) {
    return construir(/plan/i.test(detalleTexto(error)) ? 'plan_no_encontrado' : 'pedido_no_encontrado', status);
  }
  if (status === 422) return construir('datos_invalidos', status);
  if (status === 503 || status === 502 || status === 504) return construir('sin_conexion', status);
  return construir('error_inesperado', status);
}

function construir(codigo: string, status: number): ErrorContratacion {
  return { codigo, status, mensaje: MENSAJES[codigo], reintentable: REINTENTABLES.has(codigo) };
}
