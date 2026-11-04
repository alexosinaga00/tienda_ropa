import { PeriodoPlan } from '../utils/precio-plan';

/**
 * Contratación pública de planes (`/public/contratacion/...`, sin sesión). Los nombres son los del backend
 * (`plataforma/schemas.py`). Los montos llegan como TEXTO decimal ("120.00"): para mostrarlos se convierten con
 * `core/utils/precio-plan`. La web NUNCA manda montos, moneda ni fechas: el servidor recalcula todo.
 */

/** El administrador de la empresa nueva. Sin `telefono` si el comprador no lo dio. */
export interface AdministradorContratacion {
  nombre: string;
  apellido: string;
  email: string;
  telefono?: string;
  password: string;
}

/** `POST /contratacion/prueba`. */
export interface PruebaSolicitud {
  nombre: string;
  plan_codigo: string;
  administrador: AdministradorContratacion;
}

/** `POST /contratacion/pedidos`: la misma forma que la prueba más el periodo. */
export interface PedidoSolicitud extends PruebaSolicitud {
  periodo: PeriodoPlan;
}

/** Respuesta de la prueba gratuita. */
export interface PruebaRespuesta {
  empresa_codigo: string;
  empresa_nombre: string;
  plan_codigo: string;
  plan_nombre: string;
  es_prueba: boolean;
  /** "AAAA-MM-DD". */
  fecha_inicio: string;
  fecha_vencimiento: string;
}

/** Respuesta de crear el pedido: a `url_aprobacion` (PayPal) hay que mandar al comprador. */
export interface PedidoCreado {
  token: string;
  url_aprobacion: string;
  plan_codigo: string;
  plan_nombre: string;
  periodo: PeriodoPlan;
  monto_bs: string;
  monto_usd: string;
  tipo_cambio: string;
  /** UTC con zona. */
  expira_en: string;
}

export type EstadoPedido =
  | 'pendiente'
  | 'pagado'
  | 'pagado_sin_empresa'
  | 'completado'
  | 'cancelado'
  | 'vencido'
  | 'fallido';

/** `GET /pedidos/{token}` y `POST /pedidos/{token}/cancelar`. */
export interface PedidoEstado {
  estado: EstadoPedido | string;
  plan_codigo: string;
  plan_nombre: string;
  periodo: PeriodoPlan;
  monto_bs: string;
  monto_usd: string;
  tipo_cambio: string;
  expira_en: string | null;
  empresa_codigo: string | null;
}

/** `POST /pedidos/{token}/capturar`: el pago está cobrado y la empresa creada. */
export interface PedidoPagado {
  estado: EstadoPedido | string;
  empresa_codigo: string;
  empresa_nombre: string;
  plan_codigo: string;
  plan_nombre: string;
  periodo: PeriodoPlan;
  es_prueba: boolean;
  fecha_inicio: string | null;
  fecha_vencimiento: string | null;
  monto_bs: string;
  monto_usd: string;
}
