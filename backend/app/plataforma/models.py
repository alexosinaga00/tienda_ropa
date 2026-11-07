from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Table,
    Time,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy import event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.tenant import EmpresaMixin, EmpresaOpcionalMixin
from app.core.tipos import TipoJson


# ---- Seguridad ----


rol_permiso = Table(
    "rol_permiso",
    Base.metadata,
    Column("rol_id", ForeignKey("rol.id", ondelete="CASCADE"), primary_key=True),
    Column("permiso_id", ForeignKey("permiso.id", ondelete="CASCADE"), primary_key=True),
)

usuario_rol = Table(
    "usuario_rol",
    Base.metadata,
    Column("usuario_id", ForeignKey("usuario.id", ondelete="CASCADE"), primary_key=True),
    Column("rol_id", ForeignKey("rol.id"), primary_key=True),
)


class Rol(Base):
    __tablename__ = "rol"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(200))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    permisos: Mapped[list["Permiso"]] = relationship(secondary=rol_permiso, back_populates="roles")


class Permiso(Base):
    __tablename__ = "permiso"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    modulo: Mapped[str] = mapped_column(String(40), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(200))

    roles: Mapped[list[Rol]] = relationship(secondary=rol_permiso, back_populates="permisos")


class Usuario(EmpresaOpcionalMixin, Base):
    __tablename__ = "usuario"
    __table_args__ = (
        UniqueConstraint("empresa_id", "email", name="uq_usuario_empresa_email"),
        # Superadministradores (empresa_id NULL): NULL no choca en una UNIQUE
        # compuesta, por eso su correo se protege con este indice parcial.
        Index(
            "ux_usuario_email_plataforma",
            "email",
            unique=True,
            postgresql_where=text("empresa_id IS NULL"),
            sqlite_where=text("empresa_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    apellido: Mapped[str] = mapped_column(String(60), nullable=False)
    email: Mapped[str] = mapped_column(String(120), nullable=False)
    telefono: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    ultimo_acceso: Mapped[dt.datetime | None]
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    actualizado_en: Mapped[dt.datetime | None]

    roles: Mapped[list[Rol]] = relationship(secondary=usuario_rol)
    cliente: Mapped["Cliente | None"] = relationship(back_populates="usuario", uselist=False)


class Cliente(EmpresaMixin, Base):
    __tablename__ = "cliente"
    __table_args__ = (
        CheckConstraint("estatura_cm BETWEEN 100 AND 250", name="ck_cliente_estatura"),
        CheckConstraint(
            "preferencia_ajuste IN ('ajustado','regular','holgado')",
            name="ck_cliente_preferencia_ajuste",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), unique=True, nullable=False)
    ci_nit: Mapped[str | None] = mapped_column(String(20))
    razon_social: Mapped[str | None] = mapped_column(String(120))
    fecha_nacimiento: Mapped[dt.date | None]
    estatura_cm: Mapped[int | None]
    preferencia_ajuste: Mapped[str | None] = mapped_column(String(15))
    acepta_datos_foto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())

    usuario: Mapped[Usuario] = relationship(back_populates="cliente")


# ---- Notificaciones ----


class Notificacion(EmpresaMixin, Base):
    __tablename__ = "notificacion"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), nullable=False)
    titulo: Mapped[str] = mapped_column(String(120), nullable=False)
    mensaje: Mapped[str | None] = mapped_column(String(400))
    tipo: Mapped[str | None] = mapped_column(String(30))
    referencia_id: Mapped[int | None]
    leida: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())


class DispositivoPush(EmpresaMixin, Base):
    """Un teléfono (token de FCM) que recibe las notificaciones push de UN usuario. El token pertenece a un solo
    usuario: si otro inicia sesión en el mismo teléfono, el registro se reasigna. `activo` aquí no es borrado lógico de
    negocio: marca los que reciben push (un token que FCM da por muerto, o que el usuario quita, queda `activo = false`)."""

    __tablename__ = "dispositivo_push"
    __table_args__ = (
        UniqueConstraint("empresa_id", "token", name="uq_dispositivo_push_empresa_token"),
        CheckConstraint("plataforma IN ('android','web')", name="ck_dispositivo_push_plataforma"),
        Index("ix_dispositivo_push_usuario", "usuario_id", "activo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), nullable=False)
    token: Mapped[str] = mapped_column(String(512), nullable=False)
    plataforma: Mapped[str] = mapped_column(String(15), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    actualizado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())


# ---- Organización ----


class Ciudad(EmpresaMixin, Base):
    __tablename__ = "ciudad"
    __table_args__ = (
        UniqueConstraint("empresa_id", "nombre", "departamento", name="uq_ciudad_empresa_nombre_departamento"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    departamento: Mapped[str | None] = mapped_column(String(60))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Sucursal(EmpresaMixin, Base):
    __tablename__ = "sucursal"
    __table_args__ = (UniqueConstraint("empresa_id", "codigo", name="uq_sucursal_empresa_codigo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ciudad_id: Mapped[int] = mapped_column(ForeignKey("ciudad.id"), nullable=False)
    codigo: Mapped[str] = mapped_column(String(15), nullable=False)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    direccion: Mapped[str] = mapped_column(String(200), nullable=False)
    telefono: Mapped[str | None] = mapped_column(String(20))
    latitud: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    longitud: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    es_deposito: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())


class HorarioSucursal(EmpresaMixin, Base):
    __tablename__ = "horario_sucursal"
    __table_args__ = (
        CheckConstraint("dia_semana BETWEEN 1 AND 7", name="ck_horario_dia_semana"),
        CheckConstraint("hora_cierre > hora_apertura", name="ck_horario_cierre_despues_apertura"),
        UniqueConstraint("sucursal_id", "dia_semana", name="uq_horario_sucursal_dia"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursal.id", ondelete="CASCADE"), nullable=False)
    dia_semana: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    hora_apertura: Mapped[dt.time] = mapped_column(Time, nullable=False)
    hora_cierre: Mapped[dt.time] = mapped_column(Time, nullable=False)


class Empleado(EmpresaMixin, Base):
    __tablename__ = "empleado"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), unique=True, nullable=False)
    sucursal_id: Mapped[int | None] = mapped_column(ForeignKey("sucursal.id"))
    ci: Mapped[str | None] = mapped_column(String(20))
    cargo: Mapped[str | None] = mapped_column(String(60))
    fecha_ingreso: Mapped[dt.date | None]
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# ---- Empresa y suscripción ----


class Empresa(Base):
    """El tenant. Raíz del aislamiento: no lleva `empresa_id`. `codigo` sale
    del nombre al crearla, es único y NO cambia aunque cambie el nombre
    comercial (es lo que identifica a la empresa en el login y en la URL)."""

    __tablename__ = "empresa"
    __table_args__ = (
        CheckConstraint(
            "plazo_cambio_horas IS NULL OR plazo_cambio_horas BETWEEN 1 AND 720", name="ck_empresa_plazo_cambio"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    codigo: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    logo_url: Mapped[str | None] = mapped_column(Text)
    color_acento: Mapped[str | None] = mapped_column(String(7))
    # Plazo propio para devolver o cambiar prendas (E08, D19). NULL = el del plan.
    plazo_cambio_horas: Mapped[int | None] = mapped_column(SmallInteger)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())


class Plan(Base):
    """Catálogo global de planes (lo configura el superadministrador). Los
    límites y las funcionalidades viven acá y no en el código."""

    __tablename__ = "plan"
    __table_args__ = (
        CheckConstraint("precio_mensual_bs IS NULL OR precio_mensual_bs >= 0", name="ck_plan_precio_mensual"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    max_sucursales: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reportes_convencionales: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reportes_ia: Mapped[bool] = mapped_column(Boolean, nullable=False)
    operacion_offline: Mapped[bool] = mapped_column(Boolean, nullable=False)
    analitica_ml: Mapped[bool] = mapped_column(Boolean, nullable=False)
    copias_seguridad: Mapped[bool] = mapped_column(Boolean, nullable=False)
    gestion_productos: Mapped[bool] = mapped_column(Boolean, nullable=False)
    gestion_ventas: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reservas: Mapped[bool] = mapped_column(Boolean, nullable=False)
    max_copias_historial: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    plazo_cambio_horas_defecto: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=24)
    # Precio por mes en bolivianos (NULL = sin precio publicado). El anual (20 % menos) se calcula, no se guarda.
    precio_mensual_bs: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Suscripcion(EmpresaMixin, Base):
    """Plan contratado por una empresa. Hay una sola NO cancelada por empresa;
    cambiar de plan cancela la actual y crea otra (queda el historial)."""

    __tablename__ = "suscripcion"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('activa','vencida','suspendida','cancelada')", name="ck_suscripcion_estado"
        ),
        CheckConstraint("fecha_vencimiento >= fecha_inicio", name="ck_suscripcion_fechas"),
        Index(
            "ux_suscripcion_vigente",
            "empresa_id",
            unique=True,
            postgresql_where=text("estado <> 'cancelada'"),
            sqlite_where=text("estado <> 'cancelada'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plan.id"), nullable=False)
    estado: Mapped[str] = mapped_column(String(15), nullable=False, default="activa")
    fecha_inicio: Mapped[dt.date] = mapped_column(Date, nullable=False)
    fecha_vencimiento: Mapped[dt.date] = mapped_column(Date, nullable=False)
    # Prueba gratuita (la crea la contratación sin pago); el estado y las fechas siguen las mismas reglas.
    es_prueba: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())


# ---- Contratación de planes ----

ESTADOS_PEDIDO_CONTRATACION = (
    "pendiente", "pagado", "pagado_sin_empresa", "completado", "cancelado", "vencido", "fallido",
)  # fmt: skip
# Estados en que un pedido de prueba YA NO ocupa el correo del solicitante.
ESTADOS_PEDIDO_LIBERAN_CORREO = ("cancelado", "vencido", "fallido")


class PedidoContratacion(Base):
    """Compra o prueba gratuita de un plan hecha desde la portada pública, ANTES de que exista la empresa.

    Es una tabla global: NO lleva `empresa_id` ni el mixin (quien compra aún no tiene empresa), así el filtro
    automático por empresa no la afecta y no entra en las copias de seguridad. La empresa que se crea al
    completarse se enlaza en `empresa_creada_id`. Guarda el hash bcrypt de la contraseña del administrador
    (nunca la contraseña en claro) hasta crear su usuario. `token` identifica el pedido ante el cliente."""

    __tablename__ = "pedido_contratacion"
    __table_args__ = (
        CheckConstraint("tipo IN ('pago','prueba')", name="ck_pedido_contratacion_tipo"),
        CheckConstraint("periodo IS NULL OR periodo IN ('mensual','anual')", name="ck_pedido_contratacion_periodo"),
        CheckConstraint(
            "estado IN ('pendiente','pagado','pagado_sin_empresa','completado','cancelado','vencido','fallido')",
            name="ck_pedido_contratacion_estado",
        ),
        # Una sola prueba gratuita por correo: solo la liberan los pedidos que no prosperaron.
        Index(
            "ux_pedido_prueba_correo",
            "admin_email",
            unique=True,
            postgresql_where=text("tipo = 'prueba' AND estado NOT IN ('cancelado','vencido','fallido')"),
            sqlite_where=text("tipo = 'prueba' AND estado NOT IN ('cancelado','vencido','fallido')"),
        ),
        Index("ix_pedido_contratacion_estado_creado", "estado", "creado_en"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)
    periodo: Mapped[str | None] = mapped_column(String(10))
    plan_id: Mapped[int] = mapped_column(ForeignKey("plan.id"), nullable=False)
    empresa_nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    empresa_codigo: Mapped[str] = mapped_column(String(60), nullable=False)
    admin_nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    admin_apellido: Mapped[str] = mapped_column(String(60), nullable=False)
    admin_email: Mapped[str] = mapped_column(String(120), nullable=False)
    admin_telefono: Mapped[str | None] = mapped_column(String(20))
    admin_password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente", server_default="pendiente")
    monto_bs: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    monto_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    tipo_cambio: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    paypal_order_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    empresa_creada_id: Mapped[int | None] = mapped_column(ForeignKey("empresa.id"))
    ip: Mapped[str | None] = mapped_column(String(45))
    expira_en: Mapped[dt.datetime | None]
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    actualizado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


# ---- Bitácora ----


class Bitacora(Base):
    """Registro de solo anexar de las acciones sensibles. `empresa_id` admite
    NULL a propósito (acciones de la plataforma sin empresa, como un login
    fallido con una empresa inexistente), por eso NO usa el mixin de empresa:
    el filtro automático la cerraría al superadministrador. Todas sus consultas
    filtran por empresa de forma explícita en `BitacoraRepository`.

    `creado_en` es naive en UTC, como el resto de los modelos."""

    __tablename__ = "bitacora"
    __table_args__ = (
        Index("ix_bitacora_empresa_fecha", "empresa_id", "creado_en"),
        Index("ix_bitacora_empresa_entidad", "empresa_id", "entidad", "entidad_id"),
        Index("ix_bitacora_usuario_fecha", "usuario_id", "creado_en"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    empresa_id: Mapped[int | None] = mapped_column(ForeignKey("empresa.id"))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    entidad: Mapped[str] = mapped_column(String(60), nullable=False)
    entidad_id: Mapped[int | None] = mapped_column(BigInteger)
    accion: Mapped[str] = mapped_column(String(40), nullable=False)
    datos: Mapped[dict | None] = mapped_column(TipoJson)
    ip: Mapped[str | None] = mapped_column(String(45))
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())


@event.listens_for(Bitacora, "before_update")
@event.listens_for(Bitacora, "before_delete")
def _bitacora_solo_anexar(mapper, connection, fila) -> None:
    """La bitácora no se edita ni se borra desde el código. La única salida es
    la purga por retención, que borra con DELETE de SQL y no pasa por aquí."""
    raise RuntimeError("La bitácora es de solo anexar")


# ---- Copias de seguridad ----

ESTADOS_COPIA = ("en_proceso", "completada", "fallida")


class CopiaSeguridad(EmpresaMixin, Base):
    """Historial de las copias de seguridad de una empresa (E22). Guarda SOLO metadatos: el ZIP no se conserva
    (se entrega una vez, en la misma respuesta que lo crea), así que sirve para auditar quién la pidió y cuándo y
    para comprobar el checksum de un archivo ya descargado.

    La fila en estado `en_proceso` es el candado: un índice único parcial deja a lo sumo UNA por empresa, en
    SQLite y en PostgreSQL. `activo` NO es el borrado lógico de un negocio: marca las copias que siguen en el
    historial visible; al pasar el límite del plan (`plan.max_copias_historial`) las más antiguas quedan en falso."""

    __tablename__ = "copia_seguridad"
    __table_args__ = (
        CheckConstraint("estado IN ('en_proceso','completada','fallida')", name="ck_copia_seguridad_estado"),
        Index(
            "ux_copia_en_proceso",
            "empresa_id",
            unique=True,
            postgresql_where=text("estado = 'en_proceso'"),
            sqlite_where=text("estado = 'en_proceso'"),
        ),
        Index("ix_copia_empresa_creado", "empresa_id", "creado_en"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), nullable=False)
    estado: Mapped[str] = mapped_column(String(15), nullable=False, default="en_proceso")
    tamano_bytes: Mapped[int | None] = mapped_column(BigInteger)
    # Filas por tabla: {"producto": 120, "venta": 530, ...}
    tablas_incluidas: Mapped[dict | None] = mapped_column(TipoJson)
    version_esquema: Mapped[str | None] = mapped_column(String(40))
    checksum: Mapped[str | None] = mapped_column(String(64))
    # Un código estable (copia_demasiado_grande, copia_tiempo_agotado, error_interno...), nunca la excepción.
    motivo_fallo: Mapped[str | None] = mapped_column(String(60))
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    terminado_en: Mapped[dt.datetime | None]
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
