from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Proveedor(Base):
    __tablename__ = "proveedor"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    nit: Mapped[str | None] = mapped_column(String(20), unique=True)
    contacto: Mapped[str | None] = mapped_column(String(80))
    telefono: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(120))
    direccion: Mapped[str | None] = mapped_column(String(200))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())


class ProductoProveedor(Base):
    """Sin `activo`: es una relación de referencia (qué proveedor surte qué
    producto y a qué costo referencial), se quita con DELETE físico."""

    __tablename__ = "producto_proveedor"

    proveedor_id: Mapped[int] = mapped_column(
        ForeignKey("proveedor.id", ondelete="CASCADE"), primary_key=True
    )
    producto_id: Mapped[int] = mapped_column(ForeignKey("producto.id", ondelete="CASCADE"), primary_key=True)
    costo_referencial: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    dias_entrega: Mapped[int | None] = mapped_column(SmallInteger)


class OrdenCompra(Base):
    __tablename__ = "orden_compra"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('borrador','enviada','parcial','recibida','anulada')", name="ck_orden_compra_estado"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
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


class OrdenCompraDetalle(Base):
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
# (ver abastecimiento.casos_uso.cu12_registrar_recepcion_mercaderia
# .RegistrarRecepcionMercaderia.registrar, que llama a
# inventario.politicas.actualizar_stock_operacion por cada línea).
class Recepcion(Base):
    __tablename__ = "recepcion"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    orden_compra_id: Mapped[int | None] = mapped_column(ForeignKey("orden_compra.id"))
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedor.id"), nullable=False)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursal.id"), nullable=False)
    empleado_id: Mapped[int | None] = mapped_column(ForeignKey("empleado.id"))
    fecha: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    observacion: Mapped[str | None] = mapped_column(String(300))

    detalle: Mapped[list["RecepcionDetalle"]] = relationship(
        back_populates="recepcion", order_by="RecepcionDetalle.id", cascade="all, delete-orphan"
    )


class RecepcionDetalle(Base):
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
