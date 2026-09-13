CREATE TABLE categoria (
	id SERIAL NOT NULL, 
	categoria_padre_id INTEGER, 
	nombre VARCHAR(60) NOT NULL, 
	descripcion VARCHAR(200), 
	activo BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(categoria_padre_id) REFERENCES categoria (id)
);

CREATE TABLE ciudad (
	id SERIAL NOT NULL, 
	nombre VARCHAR(60) NOT NULL, 
	departamento VARCHAR(60), 
	activo BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_ciudad_nombre_departamento UNIQUE (nombre, departamento)
);

CREATE TABLE color (
	id SERIAL NOT NULL, 
	nombre VARCHAR(40) NOT NULL, 
	codigo_hex VARCHAR(7), 
	PRIMARY KEY (id), 
	UNIQUE (nombre)
);

CREATE TABLE estado_pago (
	id SERIAL NOT NULL, 
	codigo VARCHAR(25) NOT NULL, 
	nombre VARCHAR(60) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (codigo)
);

CREATE TABLE estado_reserva (
	id SERIAL NOT NULL, 
	codigo VARCHAR(25) NOT NULL, 
	nombre VARCHAR(60) NOT NULL, 
	es_final BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (codigo)
);

CREATE TABLE estado_venta (
	id SERIAL NOT NULL, 
	codigo VARCHAR(25) NOT NULL, 
	nombre VARCHAR(60) NOT NULL, 
	es_final BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (codigo)
);

CREATE TABLE material (
	id SERIAL NOT NULL, 
	nombre VARCHAR(40) NOT NULL, 
	descripcion VARCHAR(200), 
	PRIMARY KEY (id), 
	UNIQUE (nombre)
);

CREATE TABLE metodo_pago (
	id SERIAL NOT NULL, 
	codigo VARCHAR(25) NOT NULL, 
	nombre VARCHAR(60) NOT NULL, 
	requiere_pasarela BOOLEAN NOT NULL, 
	disponible_caja BOOLEAN NOT NULL, 
	disponible_online BOOLEAN NOT NULL, 
	activo BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (codigo)
);

CREATE TABLE permiso (
	id SERIAL NOT NULL, 
	codigo VARCHAR(60) NOT NULL, 
	modulo VARCHAR(40) NOT NULL, 
	descripcion VARCHAR(200), 
	PRIMARY KEY (id), 
	UNIQUE (codigo)
);

CREATE TABLE promocion (
	id SERIAL NOT NULL, 
	nombre VARCHAR(80) NOT NULL, 
	tipo VARCHAR(15) NOT NULL, 
	valor NUMERIC(12, 2) NOT NULL, 
	fecha_inicio DATE NOT NULL, 
	fecha_fin DATE NOT NULL, 
	activo BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_promocion_tipo CHECK (tipo IN ('porcentaje','monto')), 
	CONSTRAINT ck_promocion_valor CHECK (valor > 0), 
	CONSTRAINT ck_promocion_fechas CHECK (fecha_fin >= fecha_inicio)
);

CREATE TABLE rol (
	id SERIAL NOT NULL, 
	nombre VARCHAR(40) NOT NULL, 
	descripcion VARCHAR(200), 
	activo BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (nombre)
);

CREATE TABLE talla (
	id SERIAL NOT NULL, 
	codigo VARCHAR(10) NOT NULL, 
	descripcion VARCHAR(40), 
	orden SMALLINT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (codigo)
);

CREATE TABLE temporada (
	id SERIAL NOT NULL, 
	nombre VARCHAR(60) NOT NULL, 
	anio SMALLINT NOT NULL, 
	fecha_inicio DATE, 
	fecha_fin DATE, 
	activo BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_temporada_nombre_anio UNIQUE (nombre, anio)
);

CREATE TABLE tipo_movimiento (
	id SERIAL NOT NULL, 
	codigo VARCHAR(25) NOT NULL, 
	nombre VARCHAR(60) NOT NULL, 
	signo SMALLINT NOT NULL, 
	afecta_costo BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_tipo_movimiento_signo CHECK (signo IN (-1, 1)), 
	UNIQUE (codigo)
);

CREATE TABLE usuario (
	id SERIAL NOT NULL, 
	nombre VARCHAR(60) NOT NULL, 
	apellido VARCHAR(60) NOT NULL, 
	email VARCHAR(120) NOT NULL, 
	telefono VARCHAR(20), 
	password_hash VARCHAR(255) NOT NULL, 
	ultimo_acceso TIMESTAMP WITHOUT TIME ZONE, 
	activo BOOLEAN NOT NULL, 
	creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	actualizado_en TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (email)
);

CREATE TABLE cliente (
	id SERIAL NOT NULL, 
	usuario_id INTEGER NOT NULL, 
	ci_nit VARCHAR(20), 
	razon_social VARCHAR(120), 
	fecha_nacimiento DATE, 
	estatura_cm INTEGER, 
	preferencia_ajuste VARCHAR(15), 
	acepta_datos_foto BOOLEAN NOT NULL, 
	creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_cliente_estatura CHECK (estatura_cm BETWEEN 100 AND 250), 
	CONSTRAINT ck_cliente_preferencia_ajuste CHECK (preferencia_ajuste IN ('ajustado','regular','holgado')), 
	UNIQUE (usuario_id), 
	FOREIGN KEY(usuario_id) REFERENCES usuario (id)
);

CREATE TABLE coleccion (
	id SERIAL NOT NULL, 
	temporada_id INTEGER, 
	nombre VARCHAR(80) NOT NULL, 
	descripcion VARCHAR(300), 
	activo BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(temporada_id) REFERENCES temporada (id)
);

CREATE TABLE notificacion (
	id SERIAL NOT NULL, 
	usuario_id INTEGER NOT NULL, 
	titulo VARCHAR(120) NOT NULL, 
	mensaje VARCHAR(400), 
	tipo VARCHAR(30), 
	referencia_id INTEGER, 
	leida BOOLEAN NOT NULL, 
	creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(usuario_id) REFERENCES usuario (id)
);

CREATE TABLE proveedor (
	id SERIAL NOT NULL, 
	nombre VARCHAR(120) NOT NULL, 
	nit VARCHAR(20), 
	contacto VARCHAR(80), 
	telefono VARCHAR(20), 
	email VARCHAR(120), 
	direccion VARCHAR(200), 
	usuario_id INTEGER, 
	activo BOOLEAN NOT NULL, 
	creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (nit), 
	FOREIGN KEY(usuario_id) REFERENCES usuario (id)
);

CREATE TABLE rol_permiso (
	rol_id INTEGER NOT NULL, 
	permiso_id INTEGER NOT NULL, 
	PRIMARY KEY (rol_id, permiso_id), 
	FOREIGN KEY(rol_id) REFERENCES rol (id) ON DELETE CASCADE, 
	FOREIGN KEY(permiso_id) REFERENCES permiso (id) ON DELETE CASCADE
);

CREATE TABLE sucursal (
	id SERIAL NOT NULL, 
	ciudad_id INTEGER NOT NULL, 
	codigo VARCHAR(15) NOT NULL, 
	nombre VARCHAR(80) NOT NULL, 
	direccion VARCHAR(200) NOT NULL, 
	telefono VARCHAR(20), 
	latitud NUMERIC(10, 7), 
	longitud NUMERIC(10, 7), 
	es_deposito BOOLEAN NOT NULL, 
	activo BOOLEAN NOT NULL, 
	creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ciudad_id) REFERENCES ciudad (id), 
	UNIQUE (codigo)
);

CREATE TABLE usuario_rol (
	usuario_id INTEGER NOT NULL, 
	rol_id INTEGER NOT NULL, 
	PRIMARY KEY (usuario_id, rol_id), 
	FOREIGN KEY(usuario_id) REFERENCES usuario (id) ON DELETE CASCADE, 
	FOREIGN KEY(rol_id) REFERENCES rol (id)
);

CREATE TABLE zona_envio (
	id SERIAL NOT NULL, 
	ciudad_id INTEGER NOT NULL, 
	nombre VARCHAR(60) NOT NULL, 
	anillo_desde SMALLINT, 
	anillo_hasta SMALLINT, 
	tarifa_base NUMERIC(12, 2) NOT NULL, 
	activo BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_zona_envio_tarifa_base CHECK (tarifa_base >= 0), 
	FOREIGN KEY(ciudad_id) REFERENCES ciudad (id)
);

CREATE TABLE carrito (
	id SERIAL NOT NULL, 
	cliente_id INTEGER NOT NULL, 
	sucursal_id INTEGER, 
	actualizado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (cliente_id), 
	FOREIGN KEY(cliente_id) REFERENCES cliente (id), 
	FOREIGN KEY(sucursal_id) REFERENCES sucursal (id)
);

CREATE TABLE consulta_voz (
	id SERIAL NOT NULL, 
	cliente_id INTEGER, 
	texto_transcrito TEXT NOT NULL, 
	filtros_json JSONB, 
	cantidad_resultados INTEGER, 
	creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(cliente_id) REFERENCES cliente (id)
);

CREATE TABLE direccion_cliente (
	id SERIAL NOT NULL, 
	cliente_id INTEGER NOT NULL, 
	zona_envio_id INTEGER, 
	alias VARCHAR(40), 
	direccion VARCHAR(200) NOT NULL, 
	referencia VARCHAR(200), 
	latitud NUMERIC(10, 7), 
	longitud NUMERIC(10, 7), 
	es_principal BOOLEAN NOT NULL, 
	activo BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(cliente_id) REFERENCES cliente (id) ON DELETE CASCADE, 
	FOREIGN KEY(zona_envio_id) REFERENCES zona_envio (id)
);

CREATE TABLE empleado (
	id SERIAL NOT NULL, 
	usuario_id INTEGER NOT NULL, 
	sucursal_id INTEGER, 
	ci VARCHAR(20), 
	cargo VARCHAR(60), 
	fecha_ingreso DATE, 
	activo BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (usuario_id), 
	FOREIGN KEY(usuario_id) REFERENCES usuario (id), 
	FOREIGN KEY(sucursal_id) REFERENCES sucursal (id)
);

CREATE TABLE horario_sucursal (
	id SERIAL NOT NULL, 
	sucursal_id INTEGER NOT NULL, 
	dia_semana SMALLINT NOT NULL, 
	hora_apertura TIME WITHOUT TIME ZONE NOT NULL, 
	hora_cierre TIME WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_horario_dia_semana CHECK (dia_semana BETWEEN 1 AND 7), 
	CONSTRAINT ck_horario_cierre_despues_apertura CHECK (hora_cierre > hora_apertura), 
	CONSTRAINT uq_horario_sucursal_dia UNIQUE (sucursal_id, dia_semana), 
	FOREIGN KEY(sucursal_id) REFERENCES sucursal (id) ON DELETE CASCADE
);

CREATE TABLE orden_compra (
	id SERIAL NOT NULL, 
	codigo VARCHAR(20) NOT NULL, 
	proveedor_id INTEGER NOT NULL, 
	sucursal_id INTEGER NOT NULL, 
	fecha_emision DATE DEFAULT CURRENT_DATE NOT NULL, 
	fecha_esperada DATE, 
	estado VARCHAR(20) NOT NULL, 
	total NUMERIC(12, 2) NOT NULL, 
	creado_por INTEGER, 
	creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_orden_compra_estado CHECK (estado IN ('borrador','enviada','parcial','recibida','anulada')), 
	UNIQUE (codigo), 
	FOREIGN KEY(proveedor_id) REFERENCES proveedor (id), 
	FOREIGN KEY(sucursal_id) REFERENCES sucursal (id), 
	FOREIGN KEY(creado_por) REFERENCES usuario (id)
);

CREATE TABLE producto (
	id SERIAL NOT NULL, 
	codigo VARCHAR(30) NOT NULL, 
	nombre VARCHAR(120) NOT NULL, 
	descripcion TEXT, 
	categoria_id INTEGER NOT NULL, 
	material_id INTEGER, 
	temporada_id INTEGER, 
	coleccion_id INTEGER, 
	genero VARCHAR(15) NOT NULL, 
	precio_base NUMERIC(12, 2) NOT NULL, 
	admite_probador BOOLEAN NOT NULL, 
	activo BOOLEAN NOT NULL, 
	creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	creado_por INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_producto_genero CHECK (genero IN ('hombre','mujer','unisex','nino')), 
	CONSTRAINT ck_producto_precio_base CHECK (precio_base >= 0), 
	UNIQUE (codigo), 
	FOREIGN KEY(categoria_id) REFERENCES categoria (id), 
	FOREIGN KEY(material_id) REFERENCES material (id), 
	FOREIGN KEY(temporada_id) REFERENCES temporada (id), 
	FOREIGN KEY(coleccion_id) REFERENCES coleccion (id), 
	FOREIGN KEY(creado_por) REFERENCES usuario (id)
);

CREATE TABLE regla_tarifa_envio (
	id SERIAL NOT NULL, 
	zona_envio_id INTEGER NOT NULL, 
	peso_desde_kg NUMERIC(6, 2) NOT NULL, 
	peso_hasta_kg NUMERIC(6, 2), 
	recargo NUMERIC(12, 2) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(zona_envio_id) REFERENCES zona_envio (id) ON DELETE CASCADE
);

CREATE TABLE reserva (
	id SERIAL NOT NULL, 
	codigo VARCHAR(20) NOT NULL, 
	cliente_id INTEGER NOT NULL, 
	sucursal_id INTEGER NOT NULL, 
	estado_id INTEGER NOT NULL, 
	fecha_visita DATE NOT NULL, 
	hora_visita_desde TIME WITHOUT TIME ZONE NOT NULL, 
	hora_visita_hasta TIME WITHOUT TIME ZONE NOT NULL, 
	fecha_expiracion TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	observacion VARCHAR(300), 
	creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_reserva_horas CHECK (hora_visita_hasta > hora_visita_desde), 
	UNIQUE (codigo), 
	FOREIGN KEY(cliente_id) REFERENCES cliente (id), 
	FOREIGN KEY(sucursal_id) REFERENCES sucursal (id), 
	FOREIGN KEY(estado_id) REFERENCES estado_reserva (id)
);

CREATE TABLE transferencia (
	id SERIAL NOT NULL, 
	codigo VARCHAR(20) NOT NULL, 
	sucursal_origen_id INTEGER NOT NULL, 
	sucursal_destino_id INTEGER NOT NULL, 
	estado VARCHAR(20) NOT NULL, 
	fecha_envio TIMESTAMP WITHOUT TIME ZONE, 
	fecha_recepcion TIMESTAMP WITHOUT TIME ZONE, 
	usuario_id INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_transferencia_sucursales CHECK (sucursal_origen_id <> sucursal_destino_id), 
	CONSTRAINT ck_transferencia_estado CHECK (estado IN ('pendiente','en_transito','recibida','anulada')), 
	UNIQUE (codigo), 
	FOREIGN KEY(sucursal_origen_id) REFERENCES sucursal (id), 
	FOREIGN KEY(sucursal_destino_id) REFERENCES sucursal (id), 
	FOREIGN KEY(usuario_id) REFERENCES usuario (id)
);

CREATE TABLE producto_imagen (
	id SERIAL NOT NULL, 
	producto_id INTEGER NOT NULL, 
	color_id INTEGER, 
	url TEXT NOT NULL, 
	orden SMALLINT NOT NULL, 
	es_principal BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(producto_id) REFERENCES producto (id) ON DELETE CASCADE, 
	FOREIGN KEY(color_id) REFERENCES color (id)
);

CREATE TABLE producto_proveedor (
	proveedor_id INTEGER NOT NULL, 
	producto_id INTEGER NOT NULL, 
	costo_referencial NUMERIC(12, 4), 
	dias_entrega SMALLINT, 
	PRIMARY KEY (proveedor_id, producto_id), 
	FOREIGN KEY(proveedor_id) REFERENCES proveedor (id) ON DELETE CASCADE, 
	FOREIGN KEY(producto_id) REFERENCES producto (id) ON DELETE CASCADE
);

CREATE TABLE producto_variante (
	id SERIAL NOT NULL, 
	producto_id INTEGER NOT NULL, 
	talla_id INTEGER NOT NULL, 
	color_id INTEGER NOT NULL, 
	sku VARCHAR(40) NOT NULL, 
	codigo_barras VARCHAR(40), 
	precio NUMERIC(12, 2), 
	activo BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_variante_precio CHECK (precio IS NULL OR precio >= 0), 
	CONSTRAINT uq_variante_producto_talla_color UNIQUE (producto_id, talla_id, color_id), 
	FOREIGN KEY(producto_id) REFERENCES producto (id) ON DELETE CASCADE, 
	FOREIGN KEY(talla_id) REFERENCES talla (id), 
	FOREIGN KEY(color_id) REFERENCES color (id), 
	UNIQUE (sku), 
	UNIQUE (codigo_barras)
);

CREATE TABLE promocion_alcance (
	id SERIAL NOT NULL, 
	promocion_id INTEGER NOT NULL, 
	producto_id INTEGER, 
	categoria_id INTEGER, 
	temporada_id INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(promocion_id) REFERENCES promocion (id) ON DELETE CASCADE, 
	FOREIGN KEY(producto_id) REFERENCES producto (id), 
	FOREIGN KEY(categoria_id) REFERENCES categoria (id), 
	FOREIGN KEY(temporada_id) REFERENCES temporada (id)
);

CREATE TABLE recepcion (
	id SERIAL NOT NULL, 
	codigo VARCHAR(20) NOT NULL, 
	orden_compra_id INTEGER, 
	proveedor_id INTEGER NOT NULL, 
	sucursal_id INTEGER NOT NULL, 
	empleado_id INTEGER, 
	fecha TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	observacion VARCHAR(300), 
	PRIMARY KEY (id), 
	UNIQUE (codigo), 
	FOREIGN KEY(orden_compra_id) REFERENCES orden_compra (id), 
	FOREIGN KEY(proveedor_id) REFERENCES proveedor (id), 
	FOREIGN KEY(sucursal_id) REFERENCES sucursal (id), 
	FOREIGN KEY(empleado_id) REFERENCES empleado (id)
);

CREATE TABLE reserva_historial (
	id SERIAL NOT NULL, 
	reserva_id INTEGER NOT NULL, 
	estado_id INTEGER NOT NULL, 
	usuario_id INTEGER, 
	comentario VARCHAR(300), 
	creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(reserva_id) REFERENCES reserva (id) ON DELETE CASCADE, 
	FOREIGN KEY(estado_id) REFERENCES estado_reserva (id), 
	FOREIGN KEY(usuario_id) REFERENCES usuario (id)
);

CREATE TABLE tabla_medida (
	id SERIAL NOT NULL, 
	producto_id INTEGER, 
	categoria_id INTEGER, 
	talla_id INTEGER NOT NULL, 
	pecho_min_cm NUMERIC(5, 1), 
	pecho_max_cm NUMERIC(5, 1), 
	cintura_min_cm NUMERIC(5, 1), 
	cintura_max_cm NUMERIC(5, 1), 
	hombros_cm NUMERIC(5, 1), 
	largo_cm NUMERIC(5, 1), 
	PRIMARY KEY (id), 
	CONSTRAINT ck_tabla_medida_producto_o_categoria CHECK (producto_id IS NOT NULL OR categoria_id IS NOT NULL), 
	FOREIGN KEY(producto_id) REFERENCES producto (id) ON DELETE CASCADE, 
	FOREIGN KEY(categoria_id) REFERENCES categoria (id), 
	FOREIGN KEY(talla_id) REFERENCES talla (id)
);

CREATE TABLE venta (
	id SERIAL NOT NULL, 
	codigo VARCHAR(20) NOT NULL, 
	canal VARCHAR(15) NOT NULL, 
	cliente_id INTEGER, 
	sucursal_id INTEGER NOT NULL, 
	cajero_id INTEGER, 
	reserva_id INTEGER, 
	estado_id INTEGER NOT NULL, 
	fecha TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	subtotal NUMERIC(12, 2) NOT NULL, 
	descuento NUMERIC(12, 2) NOT NULL, 
	costo_envio NUMERIC(12, 2) NOT NULL, 
	total NUMERIC(12, 2) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_venta_canal CHECK (canal IN ('digital','presencial')), 
	CONSTRAINT ck_venta_cajero_presencial CHECK (canal <> 'presencial' OR cajero_id IS NOT NULL), 
	UNIQUE (codigo), 
	FOREIGN KEY(cliente_id) REFERENCES cliente (id), 
	FOREIGN KEY(sucursal_id) REFERENCES sucursal (id), 
	FOREIGN KEY(cajero_id) REFERENCES empleado (id), 
	FOREIGN KEY(reserva_id) REFERENCES reserva (id), 
	FOREIGN KEY(estado_id) REFERENCES estado_venta (id)
);

CREATE TABLE activo_probador (
	id SERIAL NOT NULL, 
	variante_id INTEGER NOT NULL, 
	tipo VARCHAR(20) NOT NULL, 
	url TEXT NOT NULL, 
	anclajes JSONB, 
	ancho_px INTEGER, 
	alto_px INTEGER, 
	estado VARCHAR(15) NOT NULL, 
	creado_por INTEGER, 
	creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_activo_probador_tipo CHECK (tipo IN ('overlay_2d','flatlay_ia','thumb')), 
	CONSTRAINT ck_activo_probador_estado CHECK (estado IN ('pendiente','validado','rechazado')), 
	FOREIGN KEY(variante_id) REFERENCES producto_variante (id) ON DELETE CASCADE, 
	FOREIGN KEY(creado_por) REFERENCES usuario (id)
);

CREATE TABLE carrito_detalle (
	id SERIAL NOT NULL, 
	carrito_id INTEGER NOT NULL, 
	variante_id INTEGER NOT NULL, 
	cantidad INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_carrito_detalle_cantidad CHECK (cantidad > 0), 
	CONSTRAINT uq_carrito_detalle_variante UNIQUE (carrito_id, variante_id), 
	FOREIGN KEY(carrito_id) REFERENCES carrito (id) ON DELETE CASCADE, 
	FOREIGN KEY(variante_id) REFERENCES producto_variante (id)
);

CREATE TABLE devolucion (
	id SERIAL NOT NULL, 
	codigo VARCHAR(20) NOT NULL, 
	venta_id INTEGER NOT NULL, 
	fecha TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	motivo VARCHAR(300), 
	estado VARCHAR(20) NOT NULL, 
	usuario_id INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_devolucion_estado CHECK (estado IN ('pendiente','aprobada','rechazada')), 
	UNIQUE (codigo), 
	FOREIGN KEY(venta_id) REFERENCES venta (id), 
	FOREIGN KEY(usuario_id) REFERENCES usuario (id)
);

CREATE TABLE envio (
	id SERIAL NOT NULL, 
	venta_id INTEGER NOT NULL, 
	direccion_id INTEGER NOT NULL, 
	zona_envio_id INTEGER NOT NULL, 
	costo NUMERIC(12, 2) NOT NULL, 
	peso_kg NUMERIC(6, 2), 
	estado VARCHAR(20) NOT NULL, 
	fecha_programada TIMESTAMP WITHOUT TIME ZONE, 
	fecha_entrega TIMESTAMP WITHOUT TIME ZONE, 
	repartidor VARCHAR(80), 
	PRIMARY KEY (id), 
	CONSTRAINT ck_envio_estado CHECK (estado IN ('programado','en_ruta','entregado','fallido')), 
	UNIQUE (venta_id), 
	FOREIGN KEY(venta_id) REFERENCES venta (id), 
	FOREIGN KEY(direccion_id) REFERENCES direccion_cliente (id), 
	FOREIGN KEY(zona_envio_id) REFERENCES zona_envio (id)
);

CREATE TABLE favorito (
	cliente_id INTEGER NOT NULL, 
	variante_id INTEGER NOT NULL, 
	creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (cliente_id, variante_id), 
	FOREIGN KEY(cliente_id) REFERENCES cliente (id) ON DELETE CASCADE, 
	FOREIGN KEY(variante_id) REFERENCES producto_variante (id) ON DELETE CASCADE
);

CREATE TABLE historial_navegacion (
	id BIGSERIAL NOT NULL, 
	cliente_id INTEGER, 
	sesion_anonima VARCHAR(64), 
	producto_id INTEGER, 
	variante_id INTEGER, 
	tipo_evento VARCHAR(25) NOT NULL, 
	creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_historial_navegacion_tipo_evento CHECK (tipo_evento IN ('vista','busqueda','carrito','probador','favorito')), 
	FOREIGN KEY(cliente_id) REFERENCES cliente (id), 
	FOREIGN KEY(producto_id) REFERENCES producto (id), 
	FOREIGN KEY(variante_id) REFERENCES producto_variante (id)
);

CREATE TABLE movimiento_inventario (
	id BIGSERIAL NOT NULL, 
	variante_id INTEGER NOT NULL, 
	sucursal_id INTEGER NOT NULL, 
	tipo_movimiento_id INTEGER NOT NULL, 
	cantidad INTEGER NOT NULL, 
	costo_unitario NUMERIC(12, 4), 
	costo_promedio_post NUMERIC(12, 4), 
	saldo_post INTEGER NOT NULL, 
	referencia_tipo VARCHAR(25), 
	referencia_id INTEGER, 
	usuario_id INTEGER, 
	observacion VARCHAR(300), 
	creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_movimiento_cantidad CHECK (cantidad <> 0), 
	FOREIGN KEY(variante_id) REFERENCES producto_variante (id), 
	FOREIGN KEY(sucursal_id) REFERENCES sucursal (id), 
	FOREIGN KEY(tipo_movimiento_id) REFERENCES tipo_movimiento (id), 
	FOREIGN KEY(usuario_id) REFERENCES usuario (id)
);

CREATE TABLE orden_compra_detalle (
	id SERIAL NOT NULL, 
	orden_compra_id INTEGER NOT NULL, 
	variante_id INTEGER NOT NULL, 
	cantidad INTEGER NOT NULL, 
	costo_unitario NUMERIC(12, 4) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_orden_compra_detalle_cantidad CHECK (cantidad > 0), 
	CONSTRAINT ck_orden_compra_detalle_costo CHECK (costo_unitario >= 0), 
	CONSTRAINT uq_orden_compra_detalle_variante UNIQUE (orden_compra_id, variante_id), 
	FOREIGN KEY(orden_compra_id) REFERENCES orden_compra (id) ON DELETE CASCADE, 
	FOREIGN KEY(variante_id) REFERENCES producto_variante (id)
);

CREATE TABLE pago (
	id SERIAL NOT NULL, 
	venta_id INTEGER NOT NULL, 
	metodo_pago_id INTEGER NOT NULL, 
	estado_id INTEGER NOT NULL, 
	monto NUMERIC(12, 2) NOT NULL, 
	referencia_externa VARCHAR(120), 
	fecha TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_pago_monto CHECK (monto > 0), 
	FOREIGN KEY(venta_id) REFERENCES venta (id), 
	FOREIGN KEY(metodo_pago_id) REFERENCES metodo_pago (id), 
	FOREIGN KEY(estado_id) REFERENCES estado_pago (id)
);

CREATE TABLE probador_generacion (
	id SERIAL NOT NULL, 
	cliente_id INTEGER, 
	variante_id INTEGER NOT NULL, 
	hash_foto VARCHAR(64) NOT NULL, 
	url_resultado TEXT, 
	proveedor VARCHAR(30), 
	estado VARCHAR(15) NOT NULL, 
	mensaje_error VARCHAR(300), 
	creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_probador_generacion_estado CHECK (estado IN ('en_proceso','completado','fallido')), 
	FOREIGN KEY(cliente_id) REFERENCES cliente (id), 
	FOREIGN KEY(variante_id) REFERENCES producto_variante (id)
);

CREATE TABLE recepcion_detalle (
	id SERIAL NOT NULL, 
	recepcion_id INTEGER NOT NULL, 
	variante_id INTEGER NOT NULL, 
	cantidad INTEGER NOT NULL, 
	costo_unitario NUMERIC(12, 4) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_recepcion_detalle_cantidad CHECK (cantidad > 0), 
	CONSTRAINT ck_recepcion_detalle_costo CHECK (costo_unitario >= 0), 
	FOREIGN KEY(recepcion_id) REFERENCES recepcion (id) ON DELETE CASCADE, 
	FOREIGN KEY(variante_id) REFERENCES producto_variante (id)
);

CREATE TABLE recomendacion (
	id SERIAL NOT NULL, 
	cliente_id INTEGER NOT NULL, 
	variante_id INTEGER NOT NULL, 
	puntaje NUMERIC(6, 4), 
	motivo VARCHAR(200), 
	generado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(cliente_id) REFERENCES cliente (id), 
	FOREIGN KEY(variante_id) REFERENCES producto_variante (id)
);

CREATE TABLE reserva_detalle (
	id SERIAL NOT NULL, 
	reserva_id INTEGER NOT NULL, 
	variante_id INTEGER NOT NULL, 
	cantidad INTEGER NOT NULL, 
	seleccionada BOOLEAN, 
	preparada BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_reserva_detalle_cantidad CHECK (cantidad > 0), 
	CONSTRAINT uq_reserva_detalle_variante UNIQUE (reserva_id, variante_id), 
	FOREIGN KEY(reserva_id) REFERENCES reserva (id) ON DELETE CASCADE, 
	FOREIGN KEY(variante_id) REFERENCES producto_variante (id)
);

CREATE TABLE sesion_probador (
	id SERIAL NOT NULL, 
	cliente_id INTEGER, 
	variante_id INTEGER NOT NULL, 
	modo VARCHAR(15) NOT NULL, 
	duracion_seg INTEGER, 
	creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_sesion_probador_modo CHECK (modo IN ('espejo','generativo')), 
	FOREIGN KEY(cliente_id) REFERENCES cliente (id), 
	FOREIGN KEY(variante_id) REFERENCES producto_variante (id)
);

CREATE TABLE stock (
	id SERIAL NOT NULL, 
	variante_id INTEGER NOT NULL, 
	sucursal_id INTEGER NOT NULL, 
	cantidad_fisica INTEGER NOT NULL, 
	cantidad_reservada INTEGER NOT NULL, 
	cantidad_disponible INTEGER GENERATED ALWAYS AS (cantidad_fisica - cantidad_reservada) STORED NOT NULL, 
	stock_minimo INTEGER NOT NULL, 
	stock_maximo INTEGER, 
	costo_promedio NUMERIC(12, 4) NOT NULL, 
	actualizado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_stock_variante_sucursal UNIQUE (variante_id, sucursal_id), 
	CONSTRAINT ck_stock_cantidad_fisica CHECK (cantidad_fisica >= 0), 
	CONSTRAINT ck_stock_cantidad_reservada CHECK (cantidad_reservada >= 0), 
	CONSTRAINT ck_stock_reservada_no_supera_fisica CHECK (cantidad_reservada <= cantidad_fisica), 
	FOREIGN KEY(variante_id) REFERENCES producto_variante (id), 
	FOREIGN KEY(sucursal_id) REFERENCES sucursal (id)
);

CREATE TABLE transferencia_detalle (
	id SERIAL NOT NULL, 
	transferencia_id INTEGER NOT NULL, 
	variante_id INTEGER NOT NULL, 
	cantidad INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_transferencia_detalle_cantidad CHECK (cantidad > 0), 
	FOREIGN KEY(transferencia_id) REFERENCES transferencia (id) ON DELETE CASCADE, 
	FOREIGN KEY(variante_id) REFERENCES producto_variante (id)
);

CREATE TABLE venta_detalle (
	id SERIAL NOT NULL, 
	venta_id INTEGER NOT NULL, 
	variante_id INTEGER NOT NULL, 
	cantidad INTEGER NOT NULL, 
	precio_unitario NUMERIC(12, 2) NOT NULL, 
	descuento_unitario NUMERIC(12, 2) NOT NULL, 
	costo_unitario NUMERIC(12, 4), 
	subtotal NUMERIC(12, 2) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_venta_detalle_cantidad CHECK (cantidad > 0), 
	FOREIGN KEY(venta_id) REFERENCES venta (id) ON DELETE CASCADE, 
	FOREIGN KEY(variante_id) REFERENCES producto_variante (id)
);

CREATE TABLE devolucion_detalle (
	id SERIAL NOT NULL, 
	devolucion_id INTEGER NOT NULL, 
	venta_detalle_id INTEGER NOT NULL, 
	cantidad INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_devolucion_detalle_cantidad CHECK (cantidad > 0), 
	FOREIGN KEY(devolucion_id) REFERENCES devolucion (id) ON DELETE CASCADE, 
	FOREIGN KEY(venta_detalle_id) REFERENCES venta_detalle (id)
);

CREATE TABLE transaccion_pasarela (
	id SERIAL NOT NULL, 
	pago_id INTEGER NOT NULL, 
	pasarela VARCHAR(30) NOT NULL, 
	id_transaccion VARCHAR(120), 
	payload_envio JSONB, 
	payload_respuesta JSONB, 
	estado VARCHAR(25) NOT NULL, 
	creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(pago_id) REFERENCES pago (id) ON DELETE CASCADE
);
