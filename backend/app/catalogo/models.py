from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.tenant import EmpresaMixin


# ---- Catálogo ----


class Categoria(EmpresaMixin, Base):
    __tablename__ = "categoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    categoria_padre_id: Mapped[int | None] = mapped_column(ForeignKey("categoria.id"))
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(200))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Talla(EmpresaMixin, Base):
    __tablename__ = "talla"
    __table_args__ = (UniqueConstraint("empresa_id", "codigo", name="uq_talla_empresa_codigo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(10), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(40))
    orden: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class Color(EmpresaMixin, Base):
    __tablename__ = "color"
    __table_args__ = (UniqueConstraint("empresa_id", "nombre", name="uq_color_empresa_nombre"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(40), nullable=False)
    codigo_hex: Mapped[str | None] = mapped_column(String(7))


class Material(EmpresaMixin, Base):
    __tablename__ = "material"
    __table_args__ = (UniqueConstraint("empresa_id", "nombre", name="uq_material_empresa_nombre"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(40), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(200))


class Temporada(EmpresaMixin, Base):
    __tablename__ = "temporada"
    __table_args__ = (
        UniqueConstraint("empresa_id", "nombre", "anio", name="uq_temporada_empresa_nombre_anio"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    anio: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    fecha_inicio: Mapped[dt.date | None]
    fecha_fin: Mapped[dt.date | None]
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Coleccion(EmpresaMixin, Base):
    __tablename__ = "coleccion"

    id: Mapped[int] = mapped_column(primary_key=True)
    temporada_id: Mapped[int | None] = mapped_column(ForeignKey("temporada.id"))
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(300))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Producto(EmpresaMixin, Base):
    __tablename__ = "producto"
    __table_args__ = (
        UniqueConstraint("empresa_id", "codigo", name="uq_producto_empresa_codigo"),
        CheckConstraint("genero IN ('hombre','mujer','unisex','nino')", name="ck_producto_genero"),
        CheckConstraint("precio_base >= 0", name="ck_producto_precio_base"),
        Index("ix_producto_categoria", "categoria_id", postgresql_where=text("activo")),
        Index("ix_producto_temporada", "temporada_id", postgresql_where=text("activo")),
        Index("ix_producto_genero", "genero", "categoria_id", postgresql_where=text("activo")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(30), nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text)
    categoria_id: Mapped[int] = mapped_column(ForeignKey("categoria.id"), nullable=False)
    material_id: Mapped[int | None] = mapped_column(ForeignKey("material.id"))
    temporada_id: Mapped[int | None] = mapped_column(ForeignKey("temporada.id"))
    coleccion_id: Mapped[int | None] = mapped_column(ForeignKey("coleccion.id"))
    genero: Mapped[str] = mapped_column(String(15), nullable=False, default="unisex")
    precio_base: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Marca si la categoría admite probador virtual (torso superior).
    admite_probador: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))

    variantes: Mapped[list["ProductoVariante"]] = relationship(
        back_populates="producto", order_by="ProductoVariante.id"
    )
    imagenes: Mapped[list["ProductoImagen"]] = relationship(order_by="ProductoImagen.orden")


# La variante es la unidad real de negocio: el stock, el precio final, la
# reserva y la venta cuelgan de acá, nunca del producto.
class ProductoVariante(EmpresaMixin, Base):
    __tablename__ = "producto_variante"
    __table_args__ = (
        CheckConstraint("precio IS NULL OR precio >= 0", name="ck_variante_precio"),
        UniqueConstraint("producto_id", "talla_id", "color_id", name="uq_variante_producto_talla_color"),
        UniqueConstraint("empresa_id", "sku", name="uq_variante_empresa_sku"),
        UniqueConstraint("empresa_id", "codigo_barras", name="uq_variante_empresa_codigo_barras"),
        Index("ix_variante_producto", "producto_id", postgresql_where=text("activo")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("producto.id", ondelete="CASCADE"), nullable=False)
    talla_id: Mapped[int] = mapped_column(ForeignKey("talla.id"), nullable=False)
    color_id: Mapped[int] = mapped_column(ForeignKey("color.id"), nullable=False)
    sku: Mapped[str] = mapped_column(String(40), nullable=False)
    codigo_barras: Mapped[str | None] = mapped_column(String(40))
    precio: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    producto: Mapped[Producto] = relationship(back_populates="variantes")


class ProductoImagen(EmpresaMixin, Base):
    __tablename__ = "producto_imagen"
    __table_args__ = (Index("ix_producto_imagen_producto", "producto_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("producto.id", ondelete="CASCADE"), nullable=False)
    color_id: Mapped[int | None] = mapped_column(ForeignKey("color.id"))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    orden: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    es_principal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


# Rangos corporales por talla. Base de la recomendación de talla (CU-11).
class TablaMedida(EmpresaMixin, Base):
    __tablename__ = "tabla_medida"
    __table_args__ = (
        CheckConstraint(
            "producto_id IS NOT NULL OR categoria_id IS NOT NULL", name="ck_tabla_medida_producto_o_categoria"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    producto_id: Mapped[int | None] = mapped_column(ForeignKey("producto.id", ondelete="CASCADE"))
    categoria_id: Mapped[int | None] = mapped_column(ForeignKey("categoria.id"))
    talla_id: Mapped[int] = mapped_column(ForeignKey("talla.id"), nullable=False)
    pecho_min_cm: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    pecho_max_cm: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    cintura_min_cm: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    cintura_max_cm: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    hombros_cm: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    largo_cm: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))


class Favorito(EmpresaMixin, Base):
    __tablename__ = "favorito"

    cliente_id: Mapped[int] = mapped_column(ForeignKey("cliente.id", ondelete="CASCADE"), primary_key=True)
    variante_id: Mapped[int] = mapped_column(
        ForeignKey("producto_variante.id", ondelete="CASCADE"), primary_key=True
    )
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())

    variante: Mapped[ProductoVariante] = relationship()


# ---- Inventario ----


class Stock(EmpresaMixin, Base):
    __tablename__ = "stock"
    __table_args__ = (
        UniqueConstraint("variante_id", "sucursal_id", name="uq_stock_variante_sucursal"),
        Index("ix_stock_empresa_sucursal", "empresa_id", "sucursal_id"),
        CheckConstraint("cantidad_fisica >= 0", name="ck_stock_cantidad_fisica"),
        CheckConstraint("cantidad_reservada >= 0", name="ck_stock_cantidad_reservada"),
        CheckConstraint("cantidad_reservada <= cantidad_fisica", name="ck_stock_reservada_no_supera_fisica"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    variante_id: Mapped[int] = mapped_column(ForeignKey("producto_variante.id"), nullable=False)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursal.id"), nullable=False)
    # Los tres estados de una prenda salen de estas columnas: lo físico en
    # sucursal, lo apartado por reservas activas (no vendido todavía) y lo
    # disponible para reservar/comprar. "Vendido" no es una cuarta columna:
    # una venta descuenta de cantidad_fisica y libera cantidad_reservada
    # (queda registrado en movimiento_inventario, más abajo).
    cantidad_fisica: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cantidad_reservada: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Columna generada por la base: nunca se escribe desde el código.
    cantidad_disponible: Mapped[int] = mapped_column(
        Integer, Computed("cantidad_fisica - cantidad_reservada", persisted=True)
    )
    stock_minimo: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stock_maximo: Mapped[int | None] = mapped_column(Integer)
    costo_promedio: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    actualizado_en: Mapped[dt.datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


class TipoMovimiento(Base):
    __tablename__ = "tipo_movimiento"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(25), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    signo: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    afecta_costo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (CheckConstraint("signo IN (-1, 1)", name="ck_tipo_movimiento_signo"),)


# Libro inmutable: nunca se edita ni se borra desde el código. El stock es
# la suma de sus movimientos (ver catalogo.politicas.actualizar_stock_operacion).
class MovimientoInventario(EmpresaMixin, Base):
    __tablename__ = "movimiento_inventario"
    __table_args__ = (
        CheckConstraint("cantidad <> 0", name="ck_movimiento_cantidad"),
        Index("ix_movimiento_inventario_variante_sucursal", "variante_id", "sucursal_id"),
    )

    # BigInteger en Postgres (BIGSERIAL, como pide el esquema); en SQLite
    # (tests) se compila a INTEGER, el único tipo que ahí se autoincrementa
    # como alias del rowid al ser primary key.
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    variante_id: Mapped[int] = mapped_column(ForeignKey("producto_variante.id"), nullable=False)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursal.id"), nullable=False)
    tipo_movimiento_id: Mapped[int] = mapped_column(ForeignKey("tipo_movimiento.id"), nullable=False)
    # Ya incluye el signo del tipo de movimiento (positivo entrada, negativo
    # salida): saldo_post de cada fila es la suma acumulada de esta columna.
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    costo_unitario: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    costo_promedio_post: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    saldo_post: Mapped[int] = mapped_column(Integer, nullable=False)
    referencia_tipo: Mapped[str | None] = mapped_column(String(25))
    referencia_id: Mapped[int | None]
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    observacion: Mapped[str | None] = mapped_column(String(300))
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())


class Transferencia(EmpresaMixin, Base):
    __tablename__ = "transferencia"
    __table_args__ = (
        UniqueConstraint("empresa_id", "codigo", name="uq_transferencia_empresa_codigo"),
        CheckConstraint("sucursal_origen_id <> sucursal_destino_id", name="ck_transferencia_sucursales"),
        CheckConstraint(
            "estado IN ('pendiente','en_transito','recibida','anulada')", name="ck_transferencia_estado"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    sucursal_origen_id: Mapped[int] = mapped_column(ForeignKey("sucursal.id"), nullable=False)
    sucursal_destino_id: Mapped[int] = mapped_column(ForeignKey("sucursal.id"), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    fecha_envio: Mapped[dt.datetime | None]
    fecha_recepcion: Mapped[dt.datetime | None]
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))

    detalle: Mapped[list["TransferenciaDetalle"]] = relationship(
        back_populates="transferencia", order_by="TransferenciaDetalle.id"
    )


class TransferenciaDetalle(EmpresaMixin, Base):
    __tablename__ = "transferencia_detalle"
    __table_args__ = (CheckConstraint("cantidad > 0", name="ck_transferencia_detalle_cantidad"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    transferencia_id: Mapped[int] = mapped_column(
        ForeignKey("transferencia.id", ondelete="CASCADE"), nullable=False
    )
    variante_id: Mapped[int] = mapped_column(ForeignKey("producto_variante.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)

    transferencia: Mapped[Transferencia] = relationship(back_populates="detalle")


# ---- Abastecimiento ----


class Proveedor(EmpresaMixin, Base):
    __tablename__ = "proveedor"
    __table_args__ = (UniqueConstraint("empresa_id", "nit", name="uq_proveedor_empresa_nit"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    nit: Mapped[str | None] = mapped_column(String(20))
    contacto: Mapped[str | None] = mapped_column(String(80))
    telefono: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(120))
    direccion: Mapped[str | None] = mapped_column(String(200))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())


class ProductoProveedor(EmpresaMixin, Base):
    """Sin `activo`: es una relación de referencia (qué proveedor surte qué
    producto y a qué costo referencial), se quita con DELETE físico."""

    __tablename__ = "producto_proveedor"

    proveedor_id: Mapped[int] = mapped_column(
        ForeignKey("proveedor.id", ondelete="CASCADE"), primary_key=True
    )
    producto_id: Mapped[int] = mapped_column(ForeignKey("producto.id", ondelete="CASCADE"), primary_key=True)
    costo_referencial: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    dias_entrega: Mapped[int | None] = mapped_column(SmallInteger)


class OrdenCompra(EmpresaMixin, Base):
    __tablename__ = "orden_compra"
    __table_args__ = (
        UniqueConstraint("empresa_id", "codigo", name="uq_orden_compra_empresa_codigo"),
        CheckConstraint(
            "estado IN ('borrador','enviada','parcial','recibida','anulada')", name="ck_orden_compra_estado"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedor.id"), nullable=False)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursal.id"), nullable=False)
    fecha_emision: Mapped[dt.date] = mapped_column(Date, server_default=func.current_date())
    fecha_esperada: Mapped[dt.date | None] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="borrador")
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())

    detalle: Mapped[list["OrdenCompraDetalle"]] = relationship(
        back_populates="orden_compra", order_by="OrdenCompraDetalle.id", cascade="all, delete-orphan"
    )


class OrdenCompraDetalle(EmpresaMixin, Base):
    __tablename__ = "orden_compra_detalle"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="ck_orden_compra_detalle_cantidad"),
        CheckConstraint("costo_unitario >= 0", name="ck_orden_compra_detalle_costo"),
        UniqueConstraint("orden_compra_id", "variante_id", name="uq_orden_compra_detalle_variante"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    orden_compra_id: Mapped[int] = mapped_column(
        ForeignKey("orden_compra.id", ondelete="CASCADE"), nullable=False
    )
    variante_id: Mapped[int] = mapped_column(ForeignKey("producto_variante.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(nullable=False)
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)

    orden_compra: Mapped[OrdenCompra] = relationship(back_populates="detalle")


# Única entrada de mercadería con costo. Sin esto no hay promedio ponderado
# (ver catalogo.casos_uso.cu08_gestionar_abastecimiento
# .RegistrarRecepcionMercaderia.registrar, que llama a
# catalogo.politicas.actualizar_stock_operacion por cada línea).
class Recepcion(EmpresaMixin, Base):
    __tablename__ = "recepcion"
    __table_args__ = (UniqueConstraint("empresa_id", "codigo", name="uq_recepcion_empresa_codigo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    orden_compra_id: Mapped[int | None] = mapped_column(ForeignKey("orden_compra.id"))
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedor.id"), nullable=False)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursal.id"), nullable=False)
    empleado_id: Mapped[int | None] = mapped_column(ForeignKey("empleado.id"))
    fecha: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    observacion: Mapped[str | None] = mapped_column(String(300))

    detalle: Mapped[list["RecepcionDetalle"]] = relationship(
        back_populates="recepcion", order_by="RecepcionDetalle.id", cascade="all, delete-orphan"
    )


class RecepcionDetalle(EmpresaMixin, Base):
    __tablename__ = "recepcion_detalle"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="ck_recepcion_detalle_cantidad"),
        CheckConstraint("costo_unitario >= 0", name="ck_recepcion_detalle_costo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recepcion_id: Mapped[int] = mapped_column(ForeignKey("recepcion.id", ondelete="CASCADE"), nullable=False)
    variante_id: Mapped[int] = mapped_column(ForeignKey("producto_variante.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(nullable=False)
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)

    recepcion: Mapped[Recepcion] = relationship(back_populates="detalle")


# ---- Probador ----


class ActivoProbador(EmpresaMixin, Base):
    __tablename__ = "activo_probador"
    __table_args__ = (
        CheckConstraint("tipo IN ('overlay_2d','flatlay_ia','thumb')", name="ck_activo_probador_tipo"),
        CheckConstraint(
            "estado IN ('pendiente','validado','rechazado')", name="ck_activo_probador_estado"
        ),
        Index(
            "ux_activo_variante_tipo",
            "variante_id",
            "tipo",
            unique=True,
            postgresql_where=text("estado <> 'rechazado'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    variante_id: Mapped[int] = mapped_column(
        ForeignKey("producto_variante.id", ondelete="CASCADE"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    # Igual que producto_imagen.url: acá se guarda el public_id de
    # Cloudinary, no la URL completa (ver core/storage.py).
    url: Mapped[str] = mapped_column(Text, nullable=False)
    ancho_px: Mapped[int | None]
    alto_px: Mapped[int | None]
    estado: Mapped[str] = mapped_column(String(15), nullable=False, default="pendiente")
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())


class ProbadorGeneracion(EmpresaMixin, Base):
    """Caché del modo generativo: evita pagar dos veces la misma
    combinación foto+prenda. La foto original del cliente NUNCA se
    guarda acá ni en ningún otro lado — solo su hash y, si la
    generación tuvo éxito, la URL del resultado en Cloudinary."""

    __tablename__ = "probador_generacion"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('en_proceso','completado','fallido')", name="ck_probador_generacion_estado"
        ),
        Index("ix_generacion_cache", "hash_foto", "variante_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("cliente.id"))
    variante_id: Mapped[int] = mapped_column(ForeignKey("producto_variante.id"), nullable=False)
    hash_foto: Mapped[str] = mapped_column(String(64), nullable=False)
    url_resultado: Mapped[str | None] = mapped_column(Text)
    proveedor: Mapped[str | None] = mapped_column(String(30))
    estado: Mapped[str] = mapped_column(String(15), nullable=False, default="en_proceso")
    mensaje_error: Mapped[str | None] = mapped_column(String(300))
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())
