// Constantes del modo sin conexión del CLIENTE de la tienda (PayPal guardado y pedidos en cola). Cada valor vive aquí y en
// ningún otro lugar. Las reglas son las mismas que las de la tienda web.

/// Claves de `cli_meta` (por empresa y usuario).
const metaMetodoPago = 'metodo_pago';

/// Tipos de lo que se guarda de la tienda en `cli_cache`.
const cacheItem = 'item';
const cacheDetalle = 'detalle';
const cacheTalla = 'talla';
const cacheColor = 'color';
const cacheSucursal = 'sucursal';

/// Cuántas prendas y detalles como máximo se recuerdan para verlos sin conexión (se borran los más viejos).
const maxItemsEnCache = 300;
const maxDetallesEnCache = 150;

/// Máximos de un pedido sin conexión (el servidor también aplica los suyos).
const maxLineasPedido = 30;
const maxUnidadesLinea = 20;

/// Cuántos días puede esperar un pedido hecho sin conexión. Pasado este plazo, contado desde su creación local, NO se
/// envía: queda "vencido". El servidor aplica el mismo plazo a `fecha_pedido` (motivo `pedido_vencido`). Un solo lugar.
const pedidoCaducaDias = 7;
const pedidoCaduca = Duration(days: pedidoCaducaDias);
const mensajePedidoVencido = 'Venció: pasaron más de $pedidoCaducaDias días sin conexión';

/// Lo que se le dice al cliente cuando el servidor rechaza con `pedido_vencido`.
const mensajePedidoVencidoServidor =
    'Tu pedido venció: pasaron más de $pedidoCaducaDias días sin conexión. No se cobró nada.';

/// Un pedido `enviando` con más de este tiempo quedó a medias (se cerró la app): vuelve a salir. Es seguro porque el
/// servidor es idempotente por `operacion_id`.
const huerfanoEnviando = Duration(seconds: 120);

/// Cuánto espera la respuesta antes de darla por perdida (el pedido vuelve a la cola con la misma `operacion_id`).
const tiempoLimitePedido = Duration(seconds: 30);

/// Cada cuánto revisa la cola, con la app abierta y con red.
const intervaloColaCliente = Duration(seconds: 60);

/// Cuánto se espera tras volver la conexión antes de enviar (la red recién vuelta suele ser inestable).
const esperaTrasVolverConexionCliente = Duration(seconds: 3);

/// Fallos seguidos tras los cuales la cola deja de reintentar sola y espera el botón "Reintentar".
const fallosAutomaticosMax = 8;

const motivoDetenidaPorFallos = 'No se pudo enviar tu pedido. Sigue guardado: reinténtalo cuando quieras.';
const motivoPausadaPorSesion = 'Inicia sesión para enviar tu pedido. Sigue guardado.';
const mensajePedidoInvalido =
    'No pudimos procesar tu pedido porque sus datos ya no son válidos. No se cobró nada: descártalo y arma uno nuevo.';

/// El aviso de la franja de arriba cuando no hay red.
const avisoSinConexionCliente = 'Sin conexión: ves lo que ya tenías cargado';
const textoPaypalSinGuardar = 'Guarda tu PayPal con conexión para pagar sin internet';
