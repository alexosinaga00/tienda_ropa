/// Esquema de la base local (SQLite) del CLIENTE de la tienda: lo que necesita para ver lo que ya cargó, armar un carrito y
/// dejar pedidos en cola cuando no hay conexión.
///
/// Es un ARCHIVO APARTE de la base del personal (`fashionstore_local.db`): nunca comparten tablas, migraciones ni
/// ciclo de vida. Todas las tablas llevan el prefijo `cli_`.
///
/// Reglas del diseño:
/// - Lo de la persona (`cli_meta`, `cli_carrito`, `cli_pedido`) lleva `empresa_id` y `usuario_id` en la llave: dos
///   cuentas en el mismo teléfono no se ven entre sí, y toda consulta filtra por las dos.
/// - Lo público de la tienda (`cli_cache`: prendas, detalles, tallas, colores y sucursales que el cliente ya vio) lleva el
///   código de la tienda, no el de la persona: es el mismo catálogo para cualquiera.
/// - Fechas: texto ISO-8601 en UTC. Dinero: ENTERO en centavos. Booleanos: 0/1.
/// - No se guarda ningún token de PayPal ni dato de tarjeta: solo "tiene PayPal guardado" y el correo enmascarado.
/// - Una migración nueva se agrega en `migraciones_cliente.dart`; NUNCA se edita el DDL de la versión 1.
const versionEsquemaCliente = 1;

const sentenciasEsquemaClienteV1 = <String>[
  // Valores sueltos de la persona: el método de pago recordado, etc. El valor es texto (JSON).
  '''
CREATE TABLE cli_meta (
  empresa_id INTEGER NOT NULL,
  usuario_id INTEGER NOT NULL,
  clave TEXT NOT NULL,
  valor TEXT NOT NULL,
  PRIMARY KEY (empresa_id, usuario_id, clave)
)''',
  // Lo público de la tienda que el cliente ya vio, tal como lo mandó el servidor (JSON). `orden` es la posición en el
  // listado sin filtros (null = no se sabe).
  '''
CREATE TABLE cli_cache (
  tienda TEXT NOT NULL,
  tipo TEXT NOT NULL CHECK (tipo IN ('item', 'detalle', 'talla', 'color', 'sucursal')),
  clave TEXT NOT NULL,
  orden INTEGER,
  json TEXT NOT NULL,
  guardado_en TEXT NOT NULL,
  PRIMARY KEY (tienda, tipo, clave)
)''',
  '''
CREATE TABLE cli_carrito (
  empresa_id INTEGER NOT NULL,
  usuario_id INTEGER NOT NULL,
  variante_id INTEGER NOT NULL,
  producto_id INTEGER NOT NULL,
  cantidad INTEGER NOT NULL CHECK (cantidad > 0),
  producto_nombre TEXT NOT NULL,
  talla TEXT,
  color TEXT,
  precio_centavos INTEGER NOT NULL CHECK (precio_centavos >= 0),
  imagen TEXT,
  sucursal_id INTEGER,
  sucursal_nombre TEXT,
  agregado_en TEXT NOT NULL,
  PRIMARY KEY (empresa_id, usuario_id, variante_id)
)''',
  // `lineas_json`: las prendas del pedido con lo necesario para mostrarlas. Los estados finales (`cobrado`, `rechazado`,
  // `vencido`) no cambian nunca (lo vigila el repositorio).
  '''
CREATE TABLE cli_pedido (
  empresa_id INTEGER NOT NULL,
  usuario_id INTEGER NOT NULL,
  operacion_id TEXT NOT NULL,
  estado TEXT NOT NULL CHECK (estado IN ('pendiente', 'enviando', 'cobrado', 'rechazado', 'vencido')),
  sucursal_id INTEGER NOT NULL,
  sucursal_nombre TEXT NOT NULL,
  costo_envio_centavos INTEGER NOT NULL CHECK (costo_envio_centavos >= 0),
  lineas_json TEXT NOT NULL,
  total_maximo_centavos INTEGER NOT NULL CHECK (total_maximo_centavos >= 0),
  fecha_pedido TEXT NOT NULL,
  creado_en TEXT NOT NULL,
  intentos INTEGER NOT NULL DEFAULT 0,
  ultimo_intento_en TEXT,
  proximo_intento_en TEXT,
  ultimo_error TEXT,
  motivo TEXT,
  mensaje TEXT,
  venta_id INTEGER,
  codigo_venta TEXT,
  total_centavos INTEGER,
  total_usd TEXT,
  resuelto_en TEXT,
  visto INTEGER NOT NULL DEFAULT 0 CHECK (visto IN (0, 1)),
  PRIMARY KEY (empresa_id, usuario_id, operacion_id)
)''',
  'CREATE INDEX ix_cli_cache_orden ON cli_cache (tienda, tipo, orden)',
  'CREATE INDEX ix_cli_pedido_estado ON cli_pedido (empresa_id, usuario_id, estado, creado_en)',
];

/// Los nombres de las tablas (para verificar que el esquema las crea todas).
const tablasEsquemaClienteV1 = <String>['cli_meta', 'cli_cache', 'cli_carrito', 'cli_pedido'];
