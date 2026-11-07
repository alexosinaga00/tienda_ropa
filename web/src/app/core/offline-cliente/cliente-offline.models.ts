import type { MotivoPedidoDiferido } from '../models/metodo-pago.models';

/** Con quién se guarda todo: la empresa (tienda) y la persona de la sesión. Nada de otra empresa u otra persona se ve. */
export interface AlcanceCliente {
  empresaId: number;
  usuarioId: number;
}

/** Una línea del carrito local, con todo lo necesario para mostrarla sin red. */
export interface LineaCarritoLocal {
  empresa_id: number;
  usuario_id: number;
  variante_id: number;
  producto_id: number;
  cantidad: number;
  producto_nombre: string;
  talla: string | null;
  color: string | null;
  /** Texto con 2 decimales ("199.00"): el precio que el cliente vio al agregarla. */
  precio_unitario: string;
  imagen: string | null;
  /** Sucursal donde se sabía que había stock al agregarla (null = no se sabía). */
  sucursal_id: number | null;
  sucursal_nombre: string | null;
  agregado_en: string;
}

/** Lo que pide agregar el detalle de producto (el alcance y la fecha los pone el servicio). */
export type NuevaLineaLocal = Omit<LineaCarritoLocal, 'empresa_id' | 'usuario_id' | 'agregado_en'>;

/**
 * `pendiente`: esperando salir; `enviando`: la petición está en el aire; `cobrado` y `rechazado`: decisión final del
 * servidor; `vencido`: pasaron más de 7 días sin enviarse (decisión local, no se envía nunca).
 */
export type EstadoPedidoLocal = 'pendiente' | 'enviando' | 'cobrado' | 'rechazado' | 'vencido';

export interface LineaPedidoLocal {
  variante_id: number;
  cantidad: number;
  producto_nombre: string;
  talla: string | null;
  color: string | null;
  precio_unitario: string;
  imagen: string | null;
}

/** Un pedido hecho sin conexión que se paga con el PayPal guardado al volver la red. */
export interface PedidoSinConexion {
  empresa_id: number;
  usuario_id: number;
  /** UUID v4: se manda igual en cada reintento. */
  operacion_id: string;
  estado: EstadoPedidoLocal;
  sucursal_id: number;
  sucursal_nombre: string;
  costo_envio: string;
  lineas: LineaPedidoLocal[];
  /** El tope que el cliente aceptó ("Se cobrará hasta Bs X"). */
  total_maximo: string;
  fecha_pedido: string;
  creado_en: string;
  intentos: number;
  ultimo_intento_en: string | null;
  proximo_intento_en: string | null;
  ultimo_error: string | null;
  motivo: MotivoPedidoDiferido | null;
  mensaje: string | null;
  venta_id: number | null;
  codigo_venta: string | null;
  total: string | null;
  total_usd: string | null;
  resuelto_en: string | null;
  /** Falso mientras el cliente no haya visto el resultado (cobrado o rechazado). */
  visto: boolean;
}

/** Los únicos campos de un pedido que se pueden cambiar después de registrarlo. */
export type CambiosPedido = Partial<
  Pick<
    PedidoSinConexion,
    | 'estado'
    | 'intentos'
    | 'ultimo_intento_en'
    | 'proximo_intento_en'
    | 'ultimo_error'
    | 'motivo'
    | 'mensaje'
    | 'venta_id'
    | 'codigo_venta'
    | 'total'
    | 'total_usd'
    | 'resuelto_en'
    | 'visto'
  >
>;

export interface FilaMetaCliente {
  empresa_id: number;
  usuario_id: number;
  clave: string;
  valor: unknown;
}

/** Lo que se recuerda del método de pago para decidir sin red. Solo el estado y el correo enmascarado. */
export interface MetodoPagoRecordado {
  guardado: boolean;
  correo_paypal: string | null;
  guardado_en: string | null;
  /** Cuándo (ISO) se confirmó con el servidor. */
  verificado_en: string;
}

/** Una sucursal tal como se recuerda para elegir dónde retirar sin red. */
export interface SucursalRecordada {
  id: number;
  nombre: string;
  es_deposito: boolean;
}
