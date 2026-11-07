/**
 * Almacenamiento sin conexión del CLIENTE de la tienda. Es una base SEPARADA de la del personal
 * (`fashionstore_offline`): nunca comparten tablas ni se mezclan, y la del cliente se limpia al cerrar sesión.
 */
export const NOMBRE_BASE_CLIENTE = 'fashionstore_cliente_offline';

/** Claves de la tabla `meta` (por empresa y usuario). */
export const META_PERFIL_CLIENTE = 'perfil';
export const META_METODO_PAGO = 'metodo_pago';
export const META_SUCURSALES = 'sucursales';

/** Máximos de un pedido sin conexión (el servidor también aplica los suyos). */
export const MAX_LINEAS_PEDIDO = 30;
export const MAX_UNIDADES_LINEA = 20;

/**
 * Cuántos días puede esperar un pedido hecho sin conexión. Pasado este plazo, desde su creación local, NO se envía:
 * queda "vencido". El servidor aplica el mismo plazo a `fecha_pedido` (motivo `pedido_vencido`). Un solo lugar.
 */
export const PEDIDO_CADUCA_DIAS = 7;
export const PEDIDO_CADUCA_MS = PEDIDO_CADUCA_DIAS * 24 * 60 * 60 * 1000;
export const MENSAJE_PEDIDO_VENCIDO = `Venció: pasaron más de ${PEDIDO_CADUCA_DIAS} días sin conexión`;
/** Lo que se le dice al cliente cuando el servidor rechaza con `pedido_vencido`. */
export const MENSAJE_PEDIDO_VENCIDO_SERVIDOR = `Tu pedido venció: pasaron más de ${PEDIDO_CADUCA_DIAS} días sin conexión. No se cobró nada.`;

/** Una petición `enviando` con más de este tiempo quedó a medias (se cerró la pestaña): vuelve a salir. */
export const HUERFANO_ENVIANDO_MS = 120_000;
/** Cuánto espera la respuesta antes de darla por perdida (el pedido vuelve a la cola con la misma operacion_id). */
export const TIMEOUT_PEDIDO_MS = 30_000;
/** Cada cuánto revisa la cola, con la pestaña abierta y con red. */
export const INTERVALO_COLA_CLIENTE_MS = 60_000;
/** Fallos seguidos tras los cuales deja de reintentar sola. */
export const FALLOS_AUTOMATICOS_MAX = 8;
/** Nombre del candado entre pestañas (Web Locks). */
export const NOMBRE_CANDADO_PEDIDOS = 'fs-pedidos-sin-conexion';
