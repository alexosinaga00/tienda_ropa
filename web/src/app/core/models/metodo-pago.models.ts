/**
 * Método de pago guardado (PayPal Vault) y pedidos hechos sin conexión del cliente. El servidor es el dueño de estos
 * datos: aquí solo se guarda el estado "tiene PayPal guardado" y el correo ENMASCARADO que el servidor devuelve. Nunca
 * llega ni se guarda un token de PayPal ni un dato de tarjeta en el navegador. El dinero viaja siempre como texto
 * ("129.00").
 */

export type CanalPaypal = 'web' | 'app';

/** `GET /metodos-pago/paypal` y `POST /metodos-pago/paypal/confirmar`. */
export interface MetodoPagoPaypal {
  guardado: boolean;
  /** Enmascarado por el servidor ("j***@gmail.com"); null si PayPal no lo informa. */
  correo_paypal: string | null;
  guardado_en: string | null;
}

/** `POST /metodos-pago/paypal/iniciar`. */
export interface PaypalIniciarRespuesta {
  url_aprobacion: string;
  token_preparacion: string;
}

export type MotivoPedidoDiferido =
  | 'sin_metodo_pago'
  | 'stock_insuficiente'
  | 'total_supera_maximo'
  | 'variante_inactiva'
  | 'pago_rechazado'
  | 'pedido_invalido'
  | 'pedido_vencido'
  | 'suscripcion_no_activa';

export interface PedidoDiferidoLinea {
  variante_id: number;
  cantidad: number;
}

/** Cuerpo de `POST /pedidos-diferidos`. */
export interface PedidoDiferidoCrear {
  /** UUID v4: el MISMO en cada reintento (el servidor no cobra dos veces). */
  operacion_id: string;
  sucursal_id: number;
  costo_envio: string;
  lineas: PedidoDiferidoLinea[];
  /** Lo máximo que el cliente vio y aceptó pagar. */
  total_maximo: string;
  /** ISO 8601 con zona; es informativa. */
  fecha_pedido: string;
}

/** Respuesta 200 de `POST /pedidos-diferidos`: una decisión FINAL del servidor (cobrado o rechazado). */
export interface PedidoDiferidoRespuesta {
  operacion_id: string;
  estado: 'cobrado' | 'rechazado';
  motivo: MotivoPedidoDiferido | null;
  mensaje: string;
  venta_id: number | null;
  codigo_venta: string | null;
  total: string | null;
  total_usd: string | null;
  duplicada: boolean;
}
