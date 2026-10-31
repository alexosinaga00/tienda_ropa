/// Esquema de la base local (SQLite) del personal: la copia de trabajo para operar sin conexión.
///
/// Reglas del diseño:
/// - Los ids del catálogo son los del servidor (una sola base PostgreSQL: son únicos), así que no se remapean.
/// - Cada dato de primer nivel lleva `empresa_id`; las tablas hijas lo heredan de su padre. Las consultas siempre filtran por
///   empresa, de modo que dos tiendas en el mismo teléfono no se mezclan.
/// - Fechas: texto ISO-8601 en UTC. Dinero: ENTERO en centavos. Booleanos: 0/1 con CHECK.
/// - Nada del catálogo se borra: lo que el servidor da de baja pasa a `activo = 0`. Así una venta pendiente nunca apunta a una
///   variante inexistente (las llaves foráneas son RESTRICT).
/// - Una migración nueva se agrega en `migraciones_locales.dart`; NUNCA se edita el DDL de la versión 1.
const versionEsquemaLocal = 1;

/// Las 19 tablas, la vista de existencias estimadas y los índices de la versión 1, en el orden en que se crean.
const sentenciasEsquemaV1 = <String>[
  '''
CREATE TABLE empresa (
  id INTEGER PRIMARY KEY,
  codigo TEXT NOT NULL UNIQUE,
  nombre TEXT NOT NULL
)''',
  '''
CREATE TABLE sucursal (
  id INTEGER PRIMARY KEY,
  empresa_id INTEGER NOT NULL REFERENCES empresa(id),
  codigo TEXT NOT NULL,
  nombre TEXT NOT NULL,
  direccion TEXT NOT NULL DEFAULT '',
  es_deposito INTEGER NOT NULL DEFAULT 0 CHECK (es_deposito IN (0, 1)),
  activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
)''',
  '''
CREATE TABLE sucursal_horario (
  sucursal_id INTEGER NOT NULL REFERENCES sucursal(id) ON DELETE CASCADE,
  dia_semana INTEGER NOT NULL CHECK (dia_semana BETWEEN 1 AND 7),
  hora_apertura TEXT NOT NULL,
  hora_cierre TEXT NOT NULL,
  PRIMARY KEY (sucursal_id, dia_semana, hora_apertura)
)''',
  // Qué sucursales puede usar cada usuario (las que devuelve el manifiesto para su token).
  '''
CREATE TABLE sucursal_autorizada (
  usuario_id INTEGER NOT NULL,
  sucursal_id INTEGER NOT NULL REFERENCES sucursal(id) ON DELETE CASCADE,
  PRIMARY KEY (usuario_id, sucursal_id)
)''',
  // El padre puede llegar después del hijo dentro de una misma descarga: la llave se valida al terminar la transacción.
  '''
CREATE TABLE categoria (
  id INTEGER PRIMARY KEY,
  empresa_id INTEGER NOT NULL REFERENCES empresa(id),
  nombre TEXT NOT NULL,
  categoria_padre_id INTEGER REFERENCES categoria(id) DEFERRABLE INITIALLY DEFERRED
)''',
  '''
CREATE TABLE talla (
  id INTEGER PRIMARY KEY,
  empresa_id INTEGER NOT NULL REFERENCES empresa(id),
  codigo TEXT NOT NULL,
  orden INTEGER NOT NULL DEFAULT 0
)''',
  '''
CREATE TABLE color (
  id INTEGER PRIMARY KEY,
  empresa_id INTEGER NOT NULL REFERENCES empresa(id),
  nombre TEXT NOT NULL,
  codigo_hex TEXT
)''',
  // `nombre_busqueda`: el nombre en minúsculas y sin tildes, para que "camisa" encuentre "Camisa" y "CAMISÁ".
  '''
CREATE TABLE producto (
  id INTEGER PRIMARY KEY,
  empresa_id INTEGER NOT NULL REFERENCES empresa(id),
  codigo TEXT NOT NULL,
  nombre TEXT NOT NULL,
  nombre_busqueda TEXT NOT NULL,
  categoria_id INTEGER NOT NULL REFERENCES categoria(id) DEFERRABLE INITIALLY DEFERRED,
  genero TEXT NOT NULL DEFAULT 'unisex',
  imagen_principal_url TEXT,
  activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
  UNIQUE (empresa_id, codigo)
)''',
  // El precio efectivo (el de la variante o, si no tiene, el del producto) y el mayor descuento vigente al descargar.
  '''
CREATE TABLE variante (
  id INTEGER PRIMARY KEY,
  producto_id INTEGER NOT NULL REFERENCES producto(id),
  talla_id INTEGER NOT NULL REFERENCES talla(id),
  color_id INTEGER NOT NULL REFERENCES color(id),
  sku TEXT NOT NULL,
  codigo_barras TEXT,
  precio_centavos INTEGER NOT NULL CHECK (precio_centavos >= 0),
  descuento_centavos INTEGER NOT NULL DEFAULT 0 CHECK (descuento_centavos >= 0),
  activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
  UNIQUE (producto_id, talla_id, color_id)
)''',
  // `cantidad` = disponible (física menos reservada) al momento `generado_en`, hora del SERVIDOR.
  '''
CREATE TABLE stock_conocido (
  variante_id INTEGER NOT NULL REFERENCES variante(id),
  sucursal_id INTEGER NOT NULL REFERENCES sucursal(id),
  cantidad INTEGER NOT NULL CHECK (cantidad >= 0),
  generado_en TEXT NOT NULL,
  PRIMARY KEY (variante_id, sucursal_id)
)''',
  // Los clientes que bajan del servidor llevan `servidor_id`; los que se crean en el teléfono, no.
  '''
CREATE TABLE cliente_minimo (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  empresa_id INTEGER NOT NULL REFERENCES empresa(id),
  servidor_id INTEGER,
  nombre TEXT NOT NULL,
  apellido TEXT,
  ci_nit TEXT,
  telefono TEXT,
  creado_en TEXT NOT NULL
)''',
  '''
CREATE TABLE operacion_pendiente (
  operacion_id TEXT PRIMARY KEY,
  empresa_id INTEGER NOT NULL REFERENCES empresa(id),
  sucursal_id INTEGER NOT NULL REFERENCES sucursal(id),
  usuario_id INTEGER NOT NULL,
  tipo TEXT NOT NULL CHECK (tipo IN ('venta_contado', 'reserva')),
  estado TEXT NOT NULL DEFAULT 'registrada'
    CHECK (estado IN ('registrada', 'enviada', 'confirmada', 'rechazada', 'en_conflicto')),
  payload TEXT NOT NULL,
  version_contrato INTEGER NOT NULL,
  intentos INTEGER NOT NULL DEFAULT 0,
  ultimo_error TEXT,
  proximo_reintento_en TEXT,
  fecha_operacion TEXT NOT NULL,
  creada_en TEXT NOT NULL,
  resuelta_en TEXT
)''',
  '''
CREATE TABLE venta (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  operacion_id TEXT NOT NULL UNIQUE REFERENCES operacion_pendiente(operacion_id),
  empresa_id INTEGER NOT NULL REFERENCES empresa(id),
  sucursal_id INTEGER NOT NULL REFERENCES sucursal(id),
  usuario_id INTEGER NOT NULL,
  cliente_minimo_id INTEGER REFERENCES cliente_minimo(id),
  fecha_operacion TEXT NOT NULL,
  forma_pago TEXT NOT NULL CHECK (forma_pago = 'efectivo'),
  efectivo_confirmado INTEGER NOT NULL DEFAULT 0 CHECK (efectivo_confirmado IN (0, 1)),
  total_centavos INTEGER NOT NULL CHECK (total_centavos >= 0)
)''',
  // El subtotal no se guarda: se calcula (cantidad x precio unitario).
  '''
CREATE TABLE venta_detalle (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  venta_id INTEGER NOT NULL REFERENCES venta(id) ON DELETE CASCADE,
  variante_id INTEGER NOT NULL REFERENCES variante(id),
  cantidad INTEGER NOT NULL CHECK (cantidad > 0),
  precio_unitario_centavos INTEGER NOT NULL CHECK (precio_unitario_centavos >= 0)
)''',
  '''
CREATE TABLE reserva (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  operacion_id TEXT NOT NULL UNIQUE REFERENCES operacion_pendiente(operacion_id),
  empresa_id INTEGER NOT NULL REFERENCES empresa(id),
  sucursal_id INTEGER NOT NULL REFERENCES sucursal(id),
  usuario_id INTEGER NOT NULL,
  cliente_minimo_id INTEGER NOT NULL REFERENCES cliente_minimo(id),
  fecha_operacion TEXT NOT NULL,
  fecha_visita TEXT NOT NULL,
  hora_visita_desde TEXT NOT NULL,
  hora_visita_hasta TEXT NOT NULL,
  observacion TEXT
)''',
  '''
CREATE TABLE reserva_detalle (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  reserva_id INTEGER NOT NULL REFERENCES reserva(id) ON DELETE CASCADE,
  variante_id INTEGER NOT NULL REFERENCES variante(id),
  cantidad INTEGER NOT NULL CHECK (cantidad > 0)
)''',
  // Historial de las respuestas del servidor a cada operación (cada reenvío agrega una fila).
  '''
CREATE TABLE resultado_sync (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  operacion_id TEXT NOT NULL REFERENCES operacion_pendiente(operacion_id),
  recibido_en TEXT NOT NULL,
  estado_resultado TEXT NOT NULL,
  codigo_motivo TEXT,
  motivo TEXT,
  entidad_servidor_id INTEGER,
  detalle_json TEXT
)''',
  // La vigencia es POR sucursal: `descargado_en` es la hora del teléfono; `generado_en`, la del servidor (para el delta).
  '''
CREATE TABLE descarga (
  empresa_id INTEGER NOT NULL REFERENCES empresa(id),
  sucursal_id INTEGER NOT NULL REFERENCES sucursal(id),
  descargado_en TEXT NOT NULL,
  generado_en TEXT NOT NULL,
  completo INTEGER NOT NULL CHECK (completo IN (0, 1)),
  PRIMARY KEY (empresa_id, sucursal_id)
)''',
  // Valores sueltos: versión del esquema, sucursal activa por usuario, última descarga del catálogo, etc.
  '''
CREATE TABLE meta (
  clave TEXT PRIMARY KEY,
  valor TEXT NOT NULL
)''',
  // Índices.
  'CREATE INDEX ix_sucursal_empresa ON sucursal (empresa_id)',
  'CREATE INDEX ix_producto_busqueda ON producto (empresa_id, nombre_busqueda)',
  'CREATE INDEX ix_producto_categoria ON producto (categoria_id)',
  'CREATE INDEX ix_variante_producto ON variante (producto_id)',
  // El SKU NO es único aquí: lo es solo dentro de una empresa y en esta base puede haber varias.
  'CREATE INDEX ix_variante_sku ON variante (sku)',
  'CREATE INDEX ix_stock_sucursal ON stock_conocido (sucursal_id)',
  'CREATE UNIQUE INDEX ux_cliente_ci ON cliente_minimo (empresa_id, ci_nit) WHERE ci_nit IS NOT NULL',
  'CREATE UNIQUE INDEX ux_cliente_servidor ON cliente_minimo (empresa_id, servidor_id) WHERE servidor_id IS NOT NULL',
  'CREATE INDEX ix_operacion_estado ON operacion_pendiente (empresa_id, estado)',
  'CREATE INDEX ix_operacion_fecha ON operacion_pendiente (empresa_id, fecha_operacion)',
  'CREATE INDEX ix_venta_sucursal ON venta (sucursal_id)',
  'CREATE INDEX ix_reserva_sucursal ON reserva (sucursal_id)',
  // Existencias estimadas = lo conocido menos lo que el servidor todavía no reflejó en ese stock. Se resta una operación
  // 'registrada' o 'enviada' (el servidor no la aplicó o no sabemos), o 'confirmada' DESPUÉS de la fecha del stock conocido
  // (su efecto aún no está en esos números). 'rechazada' y 'en_conflicto' no restan: el servidor no las aplicó.
  // Ambas horas (resuelta_en y generado_en) son del servidor: el reloj del teléfono no influye. Nunca baja de 0.
  '''
CREATE VIEW v_stock_local AS
SELECT
  s.variante_id AS variante_id,
  s.sucursal_id AS sucursal_id,
  s.cantidad AS cantidad_conocida,
  s.generado_en AS generado_en,
  MAX(0, s.cantidad - COALESCE((
    SELECT SUM(m.cantidad)
    FROM (
      SELECT vd.variante_id AS variante_id, v.sucursal_id AS sucursal_id, vd.cantidad AS cantidad,
             o.estado AS estado, o.resuelta_en AS resuelta_en
      FROM venta_detalle vd
      JOIN venta v ON v.id = vd.venta_id
      JOIN operacion_pendiente o ON o.operacion_id = v.operacion_id
      UNION ALL
      SELECT rd.variante_id, r.sucursal_id, rd.cantidad, o.estado, o.resuelta_en
      FROM reserva_detalle rd
      JOIN reserva r ON r.id = rd.reserva_id
      JOIN operacion_pendiente o ON o.operacion_id = r.operacion_id
    ) m
    WHERE m.variante_id = s.variante_id
      AND m.sucursal_id = s.sucursal_id
      AND (m.estado IN ('registrada', 'enviada') OR (m.estado = 'confirmada' AND m.resuelta_en > s.generado_en))
  ), 0)) AS cantidad_estimada
FROM stock_conocido s''',
];

/// Los nombres de las 19 tablas (para verificar que el esquema las crea todas).
const tablasEsquemaV1 = <String>[
  'empresa',
  'sucursal',
  'sucursal_horario',
  'sucursal_autorizada',
  'categoria',
  'talla',
  'color',
  'producto',
  'variante',
  'stock_conocido',
  'cliente_minimo',
  'operacion_pendiente',
  'venta',
  'venta_detalle',
  'reserva',
  'reserva_detalle',
  'resultado_sync',
  'descarga',
  'meta',
];
