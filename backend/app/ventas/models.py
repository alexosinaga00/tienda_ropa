from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EstadoVenta(Base):
    __tablename__ = "estado_venta"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(25), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    es_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Promocion(Base):
    __tablename__ = "promocion"
    __table_args__ = (
        CheckConstraint("tipo IN ('porcentaje','monto')", name="ck_promocion_tipo"),
        CheckConstraint("valor > 0", name="ck_promocion_valor"),
        CheckConstraint("fecha_fin >= fecha_inicio", name="ck_promocion_fechas"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    tipo: Mapped[str] = mapped_column(String(15), nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    fecha_inicio: Mapped[dt.date] = mapped_column(Date, nullable=False)
    fecha_fin: Mapped[dt.date] = mapped_column(Date, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    alcances: Mapped[list["PromocionAlcance"]] = relationship(
        back_populates="promocion", cascade="all, delete-orphan"
    )


class PromocionAlcance(Base):
    __tablename__ = "promocion_alcance"
    # La regla "exactamente uno de producto_id/categoria_id/temporada_id"
    # (num_nonnulls(...) = 1 en docs/fashionstore_esquema.sql) se agrega a
    # mano en la migración solo para Postgres -- num_nonnulls no existe en
    # SQLite, que es lo que usan los tests. Acá también se valida en
    # ventas.casos_uso.cu27_gestionar_promociones antes de insertar.

    id: Mapped[int] = mapped_column(primary_key=True)
    promocion_id: Mapped[int] = mapped_column(ForeignKey("promocion.id", ondelete="CASCADE"), nullable=False)
    producto_id: Mapped[int | None] = mapped_column(ForeignKey("producto.id"))
    categoria_id: Mapped[int | None] = mapped_column(ForeignKey("categoria.id"))
    temporada_id: Mapped[int | None] = mapped_column(ForeignKey("temporada.id"))

    promocion: Mapped[Promocion] = relationship(back_populates="alcances")


# Una sola tabla para venta digital y presencial: cambia el canal, no la entidad.
class Venta(Base):
    __tablename__ = "venta"
    __table_args__ = (
        CheckConstraint("canal IN ('digital','presencial')", name="ck_venta_canal"),
        # En venta presencial el cajero es obligatorio.
        CheckConstraint("canal <> 'presencial' OR cajero_id IS NOT NULL", name="ck_venta_cajero_presencial"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    canal: Mapped[str] = mapped_column(String(15), nullable=False)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("cliente.id"))
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursal.id"), nullable=False)
    cajero_id: Mapped[int | None] = mapped_column(ForeignKey("empleado.id"))
    reserva_id: Mapped[int | None] = mapped_column(ForeignKey("reserva.id"))
    estado_id: Mapped[int] = mapped_column(ForeignKey("estado_venta.id"), nullable=False)
    fecha: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    descuento: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    costo_envio: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    detalle: Mapped[list["VentaDetalle"]] = relationship(
        back_populates="venta", order_by="VentaDetalle.id", cascade="all, delete-orphan"
    )


class VentaDetalle(Base):
    __tablename__ = "venta_detalle"
    __table_args__ = (CheckConstraint("cantidad > 0", name="ck_venta_detalle_cantidad"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("venta.id", ondelete="CASCADE"), nullable=False)
    variante_id: Mapped[int] = mapped_column(ForeignKey("producto_variante.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    precio_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    descuento_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    # Costo congelado al momento de la venta (copiado de stock.costo_promedio
    # en ese instante), para calcular margen real: nunca se recalcula
    # después aunque cambie el costo promedio de la variante.
    costo_unitario: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    venta: Mapped[Venta] = relationship(back_populates="detalle")


class Carrito(Base):
    __tablename__ = "carrito"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("cliente.id"), unique=True, nullable=False)
    sucursal_id: Mapped[int | None] = mapped_column(ForeignKey("sucursal.id"))
    actualizado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    detalle: Mapped[list["CarritoDetalle"]] = relationship(
        back_populates="carrito", order_by="CarritoDetalle.id", cascade="all, delete-orphan"
    )


class CarritoDetalle(Base):
    __tablename__ = "carrito_detalle"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="ck_carrito_detalle_cantidad"),
        UniqueConstraint("carrito_id", "variante_id", name="uq_carrito_detalle_variante"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    carrito_id: Mapped[int] = mapped_column(ForeignKey("carrito.id", ondelete="CASCADE"), nullable=False)
    variante_id: Mapped[int] = mapped_column(ForeignKey("producto_variante.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    carrito: Mapped[Carrito] = relationship(back_populates="detalle")


class Devolucion(Base):
    __tablename__ = "devolucion"
    __table_args__ = (CheckConstraint("estado IN ('pendiente','aprobada','rechazada')", name="ck_devolucion_estado"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    venta_id: Mapped[int] = mapped_column(ForeignKey("venta.id"), nullable=False)
    fecha: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    motivo: Mapped[str | None] = mapped_column(String(300))
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))

    detalle: Mapped[list["DevolucionDetalle"]] = relationship(
        back_populates="devolucion", order_by="DevolucionDetalle.id", cascade="all, delete-orphan"
    )


class DevolucionDetalle(Base):
    __tablename__ = "devolucion_detalle"
    __table_args__ = (CheckConstraint("cantidad > 0", name="ck_devolucion_detalle_cantidad"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    devolucion_id: Mapped[int] = mapped_column(ForeignKey("devolucion.id", ondelete="CASCADE"), nullable=False)
    venta_detalle_id: Mapped[int] = mapped_column(ForeignKey("venta_detalle.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)

    devolucion: Mapped[Devolucion] = relationship(back_populates="detalle")
