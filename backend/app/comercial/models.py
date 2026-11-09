from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.tenant import EmpresaMixin


# ---- Reservas ----


class EstadoReserva(Base):
    __tablename__ = "estado_reserva"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(25), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    es_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Reserva(EmpresaMixin, Base):
    __tablename__ = "reserva"
    __table_args__ = (
        UniqueConstraint("empresa_id", "codigo", name="uq_reserva_empresa_codigo"),
        Index("ix_reserva_empresa_estado_expiracion", "empresa_id", "estado_id", "fecha_expiracion"),
        # Reservas de una sucursal en un día (pantalla de inicio y bandeja de la sucursal).
        Index("ix_reserva_empresa_sucursal_visita", "empresa_id", "sucursal_id", "fecha_visita"),
        CheckConstraint("hora_visita_hasta > hora_visita_desde", name="ck_reserva_horas"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("cliente.id"), nullable=False)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursal.id"), nullable=False)
    estado_id: Mapped[int] = mapped_column(ForeignKey("estado_reserva.id"), nullable=False)
    fecha_visita: Mapped[dt.date] = mapped_column(Date, nullable=False)
    hora_visita_desde: Mapped[dt.time] = mapped_column(Time, nullable=False)
    hora_visita_hasta: Mapped[dt.time] = mapped_column(Time, nullable=False)
    fecha_expiracion: Mapped[dt.datetime] = mapped_column(nullable=False)
    observacion: Mapped[str | None] = mapped_column(String(300))
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())

    detalle: Mapped[list["ReservaDetalle"]] = relationship(
        back_populates="reserva", order_by="ReservaDetalle.id", cascade="all, delete-orphan"
    )
    historial: Mapped[list["ReservaHistorial"]] = relationship(
        back_populates="reserva", order_by="ReservaHistorial.id", cascade="all, delete-orphan"
    )


class ReservaDetalle(EmpresaMixin, Base):
    __tablename__ = "reserva_detalle"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="ck_reserva_detalle_cantidad"),
        UniqueConstraint("reserva_id", "variante_id", name="uq_reserva_detalle_variante"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reserva_id: Mapped[int] = mapped_column(ForeignKey("reserva.id", ondelete="CASCADE"), nullable=False)
    variante_id: Mapped[int] = mapped_column(ForeignKey("producto_variante.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # NULL = aún no probada. TRUE = el cliente la compra. FALSE = se libera al stock.
    seleccionada: Mapped[bool | None] = mapped_column(Boolean)
    preparada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    reserva: Mapped[Reserva] = relationship(back_populates="detalle")


class ReservaHistorial(EmpresaMixin, Base):
    __tablename__ = "reserva_historial"

    id: Mapped[int] = mapped_column(primary_key=True)
    reserva_id: Mapped[int] = mapped_column(ForeignKey("reserva.id", ondelete="CASCADE"), nullable=False)
    estado_id: Mapped[int] = mapped_column(ForeignKey("estado_reserva.id"), nullable=False)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    comentario: Mapped[str | None] = mapped_column(String(300))
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())

    reserva: Mapped[Reserva] = relationship(back_populates="historial")


# ---- Ventas ----


class EstadoVenta(Base):
    __tablename__ = "estado_venta"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(25), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    es_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Promocion(EmpresaMixin, Base):
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


class PromocionAlcance(EmpresaMixin, Base):
    __tablename__ = "promocion_alcance"
    # La regla "exactamente uno de producto_id/categoria_id/temporada_id"
    # (num_nonnulls(...) = 1 en docs/fashionstore_esquema.sql) se agrega a
    # mano en la migración solo para Postgres -- num_nonnulls no existe en
    # SQLite, que es lo que usan los tests. Acá también se valida en
    # comercial.casos_uso.cu16_gestionar_promociones antes de insertar.

    id: Mapped[int] = mapped_column(primary_key=True)
    promocion_id: Mapped[int] = mapped_column(ForeignKey("promocion.id", ondelete="CASCADE"), nullable=False)
    producto_id: Mapped[int | None] = mapped_column(ForeignKey("producto.id"))
    categoria_id: Mapped[int | None] = mapped_column(ForeignKey("categoria.id"))
    temporada_id: Mapped[int | None] = mapped_column(ForeignKey("temporada.id"))

    promocion: Mapped[Promocion] = relationship(back_populates="alcances")


# Una sola tabla para venta digital y presencial: cambia el canal, no la entidad.
class Venta(EmpresaMixin, Base):
    __tablename__ = "venta"
    __table_args__ = (
        UniqueConstraint("empresa_id", "codigo", name="uq_venta_empresa_codigo"),
        CheckConstraint("canal IN ('digital','presencial')", name="ck_venta_canal"),
        # En venta presencial el cajero es obligatorio.
        CheckConstraint("canal <> 'presencial' OR cajero_id IS NOT NULL", name="ck_venta_cajero_presencial"),
        Index("ix_venta_empresa_fecha", "empresa_id", "fecha"),
        # Ventas de una sucursal en un rango de fechas (pantalla de inicio del personal, Caja) y compras de un cliente.
        Index("ix_venta_empresa_sucursal_fecha", "empresa_id", "sucursal_id", "fecha"),
        Index("ix_venta_cliente", "cliente_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
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


class VentaDetalle(EmpresaMixin, Base):
    __tablename__ = "venta_detalle"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="ck_venta_detalle_cantidad"),
        Index("ix_venta_detalle_venta", "venta_id"),
    )

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


class Carrito(EmpresaMixin, Base):
    __tablename__ = "carrito"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("cliente.id"), unique=True, nullable=False)
    sucursal_id: Mapped[int | None] = mapped_column(ForeignKey("sucursal.id"))
    actualizado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    detalle: Mapped[list["CarritoDetalle"]] = relationship(
        back_populates="carrito", order_by="CarritoDetalle.id", cascade="all, delete-orphan"
    )


class CarritoDetalle(EmpresaMixin, Base):
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


class Devolucion(EmpresaMixin, Base):
    __tablename__ = "devolucion"
    __table_args__ = (
        UniqueConstraint("empresa_id", "codigo", name="uq_devolucion_empresa_codigo"),
        CheckConstraint(
            "estado IN ('pendiente','aprobada','rechazada','cancelada','vencida')", name="ck_devolucion_estado"
        ),
        Index("ix_devolucion_venta", "venta_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    venta_id: Mapped[int] = mapped_column(ForeignKey("venta.id"), nullable=False)
    fecha: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    motivo: Mapped[str | None] = mapped_column(String(300))
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    # Quien la registró (el cajero) o, en una SOLICITUD de cambio, el cliente que la pidió.
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    # Solo en una solicitud de cambio (Etapa 2): quién la aprobó o rechazó, cuándo y por qué. Una solicitud que vence
    # sola o que cancela el cliente deja `resuelta_en` y ningún `resuelta_por_id` (el cliente cancela: queda su id).
    resuelta_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    resuelta_en: Mapped[dt.datetime | None] = mapped_column()
    motivo_rechazo: Mapped[str | None] = mapped_column(String(300))

    detalle: Mapped[list["DevolucionDetalle"]] = relationship(
        back_populates="devolucion", order_by="DevolucionDetalle.id", cascade="all, delete-orphan"
    )


class DevolucionDetalle(EmpresaMixin, Base):
    __tablename__ = "devolucion_detalle"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="ck_devolucion_detalle_cantidad"),
        Index("ix_devolucion_detalle_devolucion", "devolucion_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    devolucion_id: Mapped[int] = mapped_column(ForeignKey("devolucion.id", ondelete="CASCADE"), nullable=False)
    venta_detalle_id: Mapped[int] = mapped_column(ForeignKey("venta_detalle.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    # Cambio de talla o color: la variante que se entrega en lugar de la devuelta (NULL = devolución simple).
    variante_nueva_id: Mapped[int | None] = mapped_column(ForeignKey("producto_variante.id"))

    devolucion: Mapped[Devolucion] = relationship(back_populates="detalle")


# ---- Pagos ----


# JSON en general (compatible con SQLite, usado en tests); JSONB solo en
# Postgres. Mismo patrón que `inteligencia.models` (columnas JSON).
_TipoJson = JSON().with_variant(JSONB, "postgresql")


class MetodoPago(Base):
    __tablename__ = "metodo_pago"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(25), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    requiere_pasarela: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    disponible_caja: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    disponible_online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class EstadoPago(Base):
    __tablename__ = "estado_pago"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(25), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)


class Pago(EmpresaMixin, Base):
    __tablename__ = "pago"
    __table_args__ = (CheckConstraint("monto > 0", name="ck_pago_monto"), Index("ix_pago_venta", "venta_id"))

    id: Mapped[int] = mapped_column(primary_key=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("venta.id"), nullable=False)
    metodo_pago_id: Mapped[int] = mapped_column(ForeignKey("metodo_pago.id"), nullable=False)
    estado_id: Mapped[int] = mapped_column(ForeignKey("estado_pago.id"), nullable=False)
    monto: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    referencia_externa: Mapped[str | None] = mapped_column(String(120))
    fecha: Mapped[dt.datetime] = mapped_column(server_default=func.now())


# Libro de evidencia de cada ida y vuelta con la pasarela: nunca se edita
# ni se borra desde el código (igual que movimiento_inventario). Un
# webhook duplicado agrega una fila más acá, no reemplaza la anterior --
# es justamente lo que permite auditar que llegó dos veces.
class TransaccionPasarela(EmpresaMixin, Base):
    __tablename__ = "transaccion_pasarela"
    # El webhook y la pantalla QR buscan la transacción SOLO por (pasarela, id_transaccion), sin conocer la empresa.
    __table_args__ = (Index("ix_transaccion_pasarela_referencia", "pasarela", "id_transaccion"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pago_id: Mapped[int] = mapped_column(ForeignKey("pago.id", ondelete="CASCADE"), nullable=False)
    pasarela: Mapped[str] = mapped_column(String(30), nullable=False)
    id_transaccion: Mapped[str | None] = mapped_column(String(120))
    payload_envio: Mapped[dict | None] = mapped_column(_TipoJson)
    payload_respuesta: Mapped[dict | None] = mapped_column(_TipoJson)
    estado: Mapped[str] = mapped_column(String(25), nullable=False)
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())


# ---- PayPal guardado y pedido sin conexión (CU-18 y CU-13) ----


class MetodoPagoGuardado(EmpresaMixin, Base):
    """El PayPal que un cliente autorizó UNA vez, con conexión, para que el servidor le cobre después (Vault v3). Guarda
    solo lo que PayPal devuelve (el token), nunca datos de tarjeta, y el correo ya ENMASCARADO. Es una tabla EXCLUIDA de
    las copias de seguridad: guarda un token de pago.

    Estados: `pendiente` (el cliente todavía no aprobó en PayPal; solo tiene el setup token), `activo` (hay payment
    token; a lo sumo UNO por usuario) y `revocado` (quitado por el cliente o reemplazado). No se borra: es evidencia."""

    __tablename__ = "metodo_pago_guardado"
    __table_args__ = (
        CheckConstraint("proveedor IN ('paypal')", name="ck_metodo_pago_guardado_proveedor"),
        CheckConstraint("estado IN ('pendiente','activo','revocado')", name="ck_metodo_pago_guardado_estado"),
        Index("ix_metodo_pago_guardado_usuario", "usuario_id", "estado"),
        # (El índice único parcial "un solo activo por usuario" se declara debajo de la clase.)
        # El setup token es único (PayPal lo genera): así confirmar encuentra UNA sola fila.
        Index("ux_metodo_pago_guardado_setup", "empresa_id", "setup_token_id", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), nullable=False)
    proveedor: Mapped[str] = mapped_column(String(20), nullable=False, default="paypal")
    estado: Mapped[str] = mapped_column(String(15), nullable=False, default="pendiente")
    setup_token_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payment_token_id: Mapped[str | None] = mapped_column(String(255))  # el "vault_id" con el que se cobra
    correo_paypal: Mapped[str | None] = mapped_column(String(120))  # enmascarado: "j***@gmail.com"
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    confirmado_en: Mapped[dt.datetime | None]
    revocado_en: Mapped[dt.datetime | None]


# Un solo método ACTIVO por usuario; los pendientes y los revocados se acumulan. Se declara con la expresión de la
# columna (no con SQL en texto: una prueba prohíbe `text(` fuera de los sitios conocidos).
Index(
    "ux_metodo_pago_guardado_activo",
    MetodoPagoGuardado.usuario_id,
    unique=True,
    postgresql_where=MetodoPagoGuardado.estado == "activo",
    sqlite_where=MetodoPagoGuardado.estado == "activo",
)


class PedidoDiferido(EmpresaMixin, Base):
    """Un pedido que el cliente armó SIN conexión y el servidor cobró (o rechazó) al reconectar, con su resultado FINAL:
    es lo que hace idempotente el reenvío (UNIQUE empresa + operación). `en_proceso` es interno: solo existe dentro de la
    transacción mientras se procesa (el commit ya lleva `cobrado` o `rechazado`).

    `incierto` es la excepción a "un fallo temporal no deja fila": PayPal pudo haber COBRADO pero no se supo (la respuesta
    se perdió, la captura quedó pendiente o el cobro no se pudo registrar). Guarda el monto (`total`, `total_usd`) para que
    el reintento le PREGUNTE a PayPal (misma clave de idempotencia) antes de decidir nada: así un cobro hecho no se pierde
    ni se le dice al cliente "no se cobró". Nunca sale por la API: el cliente sigue viendo un 503 reintentable."""

    __tablename__ = "pedido_diferido"
    __table_args__ = (
        UniqueConstraint("empresa_id", "operacion_id", name="uq_pedido_diferido_empresa_operacion"),
        CheckConstraint("estado IN ('en_proceso','incierto','cobrado','rechazado')", name="ck_pedido_diferido_estado"),
        Index("ix_pedido_diferido_usuario", "usuario_id", "creado_en"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    operacion_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)  # lo genera el cliente
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), nullable=False)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursal.id"), nullable=False)
    estado: Mapped[str] = mapped_column(String(15), nullable=False)
    motivo: Mapped[str | None] = mapped_column(String(40))
    mensaje: Mapped[str | None] = mapped_column(String(300))
    venta_id: Mapped[int | None] = mapped_column(ForeignKey("venta.id"))
    total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    total_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())


# ---- Reembolsos ----


class Reembolso(EmpresaMixin, Base):
    """Dinero que se le devuelve a quien compró: de una devolución sin cambio (CU-17) o de anular un pago (CU-18).
    Libro de SOLO anexar en la práctica: no se borra ni se edita su monto; solo cambia de estado.

    Estados: `pendiente` (la pasarela todavía no confirmó; solo PayPal), `reembolsado` (el dinero salió: en efectivo desde
    el cajón, por el método manual de la tienda o por la pasarela) y `fallido` (la pasarela lo rechazó; se puede reintentar).
    `metodo` es el código del método del pago original (efectivo, qr, tarjeta, transferencia, paypal, qr_online...).
    `monto_usd` solo existe cuando la pasarela cobró en dólares. `completado_en` es el instante en que el dinero salió: lo
    que el cierre de caja resta del efectivo del turno. `motivo_fallo` es un código corto, nunca el cuerpo de la pasarela."""

    __tablename__ = "reembolso"
    __table_args__ = (
        CheckConstraint("monto > 0", name="ck_reembolso_monto"),
        CheckConstraint("estado IN ('pendiente','reembolsado','fallido')", name="ck_reembolso_estado"),
        Index("ix_reembolso_pago", "pago_id"),
        Index("ix_reembolso_venta", "venta_id"),
        # El cierre de caja suma los reembolsos en efectivo de una sucursal dentro de la ventana de un turno.
        Index("ix_reembolso_caja", "empresa_id", "sucursal_id", "metodo", "completado_en"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    devolucion_id: Mapped[int | None] = mapped_column(ForeignKey("devolucion.id"))
    pago_id: Mapped[int] = mapped_column(ForeignKey("pago.id"), nullable=False)
    venta_id: Mapped[int] = mapped_column(ForeignKey("venta.id"), nullable=False)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursal.id"), nullable=False)
    metodo: Mapped[str] = mapped_column(String(25), nullable=False)
    monto: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    monto_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    estado: Mapped[str] = mapped_column(String(15), nullable=False, default="pendiente")
    referencia_externa: Mapped[str | None] = mapped_column(String(120))
    motivo_fallo: Mapped[str | None] = mapped_column(String(60))
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), nullable=False)
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    completado_en: Mapped[dt.datetime | None] = mapped_column()


# ---- Caja ----


class CajaTurno(EmpresaMixin, Base):
    """Un turno del cajón de una sucursal: se abre con un monto inicial, se vende y cobra durante el turno y se cierra
    contando el efectivo. La caja es de la SUCURSAL (a lo sumo un turno abierto por sucursal a la vez); `abierto_por_id` y
    `cerrado_por_id` dicen quién. Solo cuenta el efectivo que pasa por el cajón: lo cobrado con QR, tarjeta o transferencia
    en la tienda y las ventas online son informativas.

    Estados: `abierta`; `cerrada` (alguien contó el efectivo y quedó la diferencia); `cerrada_auto` (el sistema lo cerró al
    terminar el día en hora de Bolivia, SIN conteo: `efectivo_contado` y `diferencia` quedan NULL hasta que un supervisor
    complete el conteo, una vez y dentro del plazo). Los montos de "foto al cerrar" (`ventas_efectivo`,
    `reembolsos_efectivo`, `monto_esperado`...) se guardan para que un cierre pasado no cambie si después llega una venta
    sincronizada tarde; el detalle muestra esa diferencia como `ajuste_posterior`. No se borra ni se edita un cierre."""

    __tablename__ = "caja_turno"
    __table_args__ = (
        CheckConstraint("estado IN ('abierta','cerrada','cerrada_auto')", name="ck_caja_turno_estado"),
        CheckConstraint("monto_inicial >= 0", name="ck_caja_turno_monto_inicial"),
        CheckConstraint("efectivo_contado IS NULL OR efectivo_contado >= 0", name="ck_caja_turno_contado"),
        CheckConstraint("pendientes_declarados >= 0", name="ck_caja_turno_pendientes"),
        # Coherencia por estado: abierta no tiene cierre ni conteo; las cerradas tienen su cierre; una cerrada con conteo
        # tiene su esperado y su diferencia.
        CheckConstraint(
            "(estado = 'abierta' AND cierre_en IS NULL AND efectivo_contado IS NULL) "
            "OR (estado <> 'abierta' AND cierre_en IS NOT NULL AND monto_esperado IS NOT NULL)",
            name="ck_caja_turno_coherencia",
        ),
        CheckConstraint(
            "estado <> 'cerrada' OR (efectivo_contado IS NOT NULL AND diferencia IS NOT NULL)",
            name="ck_caja_turno_cerrada_con_conteo",
        ),
        Index("ix_caja_turno_sucursal", "empresa_id", "sucursal_id", "apertura_en"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursal.id"), nullable=False)
    abierto_por_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), nullable=False)
    estado: Mapped[str] = mapped_column(String(15), nullable=False, default="abierta")
    apertura_en: Mapped[dt.datetime] = mapped_column(nullable=False)
    monto_inicial: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    observacion_apertura: Mapped[str | None] = mapped_column(String(300))
    cierre_en: Mapped[dt.datetime | None] = mapped_column()
    cerrado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))  # NULL = cierre automático
    efectivo_contado: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # La "foto" al cerrar (NULL mientras el turno está abierto).
    ventas_efectivo: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    reembolsos_efectivo: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    monto_esperado: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    diferencia: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))  # contado - esperado
    cantidad_ventas: Mapped[int | None] = mapped_column(Integer)
    ventas_otros_metodos: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    pendientes_declarados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observacion_cierre: Mapped[str | None] = mapped_column(String(300))
    # El conteo que un supervisor completa en un turno `cerrada_auto`.
    conteo_en: Mapped[dt.datetime | None] = mapped_column()
    conteo_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    observacion_conteo: Mapped[str | None] = mapped_column(String(300))


# A lo sumo UN turno abierto por sucursal. Se declara con la expresión de la columna (no con SQL en texto: una prueba
# prohíbe `text(` fuera de los sitios conocidos).
Index(
    "ux_caja_turno_abierta",
    CajaTurno.empresa_id,
    CajaTurno.sucursal_id,
    unique=True,
    postgresql_where=CajaTurno.estado == "abierta",
    sqlite_where=CajaTurno.estado == "abierta",
)


# ---- Entregas ----


class ZonaEnvio(EmpresaMixin, Base):
    __tablename__ = "zona_envio"
    __table_args__ = (CheckConstraint("tarifa_base >= 0", name="ck_zona_envio_tarifa_base"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ciudad_id: Mapped[int] = mapped_column(ForeignKey("ciudad.id"), nullable=False)
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    anillo_desde: Mapped[int | None] = mapped_column(SmallInteger)
    anillo_hasta: Mapped[int | None] = mapped_column(SmallInteger)
    tarifa_base: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ReglaTarifaEnvio(EmpresaMixin, Base):
    __tablename__ = "regla_tarifa_envio"

    id: Mapped[int] = mapped_column(primary_key=True)
    zona_envio_id: Mapped[int] = mapped_column(ForeignKey("zona_envio.id", ondelete="CASCADE"), nullable=False)
    peso_desde_kg: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    peso_hasta_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    recargo: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)


class DireccionCliente(EmpresaMixin, Base):
    __tablename__ = "direccion_cliente"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("cliente.id", ondelete="CASCADE"), nullable=False)
    zona_envio_id: Mapped[int | None] = mapped_column(ForeignKey("zona_envio.id"))
    alias: Mapped[str | None] = mapped_column(String(40))
    direccion: Mapped[str] = mapped_column(String(200), nullable=False)
    referencia: Mapped[str | None] = mapped_column(String(200))
    latitud: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitud: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    es_principal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Envio(EmpresaMixin, Base):
    __tablename__ = "envio"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('programado','en_ruta','entregado','fallido')", name="ck_envio_estado"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("venta.id"), unique=True, nullable=False)
    direccion_id: Mapped[int] = mapped_column(ForeignKey("direccion_cliente.id"), nullable=False)
    zona_envio_id: Mapped[int] = mapped_column(ForeignKey("zona_envio.id"), nullable=False)
    costo: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    peso_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="programado")
    fecha_programada: Mapped[dt.datetime | None]
    fecha_entrega: Mapped[dt.datetime | None]
    repartidor: Mapped[str | None] = mapped_column(String(80))
