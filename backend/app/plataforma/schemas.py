from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, model_validator

# El correo se guarda y se busca en minusculas (el correo de un usuario es unico
# por empresa sin distinguir mayusculas).
CorreoNormalizado = Annotated[EmailStr, AfterValidator(lambda correo: correo.lower())]


# ---- Seguridad ----


# ---- Roles ----------------------------------------------------------------


class RolCrear(BaseModel):
    nombre: str = Field(max_length=40)
    descripcion: str | None = Field(default=None, max_length=200)


class RolActualizar(BaseModel):
    nombre: str | None = Field(default=None, max_length=40)
    descripcion: str | None = Field(default=None, max_length=200)


class PermisoRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    modulo: str
    descripcion: str | None = None


class RolRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    descripcion: str | None = None
    activo: bool
    permisos: list[PermisoRespuesta] = []


class AsignarPermisosRequest(BaseModel):
    codigos_permiso: list[str]


# ---- Usuarios ---------------------------------------------------------------


class UsuarioCrear(BaseModel):
    nombre: str = Field(max_length=60)
    apellido: str = Field(max_length=60)
    email: CorreoNormalizado
    telefono: str | None = Field(default=None, max_length=20)
    password: str = Field(min_length=8, max_length=72)


class UsuarioActualizar(BaseModel):
    nombre: str | None = Field(default=None, max_length=60)
    apellido: str | None = Field(default=None, max_length=60)
    telefono: str | None = Field(default=None, max_length=20)
    activo: bool | None = None


class AsignarRolesRequest(BaseModel):
    nombres_rol: list[str]


class UsuarioRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    apellido: str
    email: str
    telefono: str | None = None
    activo: bool
    roles: list[str] = []

    @classmethod
    def from_modelo(cls, usuario) -> "UsuarioRespuesta":
        return cls(
            id=usuario.id,
            nombre=usuario.nombre,
            apellido=usuario.apellido,
            email=usuario.email,
            telefono=usuario.telefono,
            activo=usuario.activo,
            roles=[r.nombre for r in usuario.roles],
        )


class UsuarioYoRespuesta(UsuarioRespuesta):
    permisos: list[str] = []
    # None para el superadministrador (no pertenece a ninguna empresa).
    empresa_id: int | None = None
    empresa_codigo: str | None = None
    empresa_nombre: str | None = None


# ---- Autenticación ----------------------------------------------------------


class RegistroRequest(BaseModel):
    nombre: str = Field(max_length=60)
    apellido: str = Field(max_length=60)
    email: CorreoNormalizado
    telefono: str | None = Field(default=None, max_length=20)
    password: str = Field(min_length=8, max_length=72)
    ci_nit: str | None = Field(default=None, max_length=20)


class LoginRequest(BaseModel):
    # Nombre (o codigo) de la empresa; omitido = intento de superadministrador.
    empresa: str | None = Field(default=None, max_length=120)
    email: CorreoNormalizado
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class RecuperarRequest(BaseModel):
    empresa: str | None = Field(default=None, max_length=120)
    email: CorreoNormalizado


class RecuperarConfirmarRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=72)


class RecuperarRespuesta(BaseModel):
    detail: str
    token_dev: str | None = None


class TokenRespuesta(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# ---- Perfil de cliente --------------------------------------------------------


class ClientePerfilRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nombre: str
    apellido: str
    email: str
    telefono: str | None = None
    ci_nit: str | None = None
    razon_social: str | None = None
    fecha_nacimiento: dt.date | None = None
    estatura_cm: int | None = None
    preferencia_ajuste: str | None = None
    acepta_datos_foto: bool

    @classmethod
    def from_modelo(cls, cliente) -> "ClientePerfilRespuesta":
        return cls(
            nombre=cliente.usuario.nombre,
            apellido=cliente.usuario.apellido,
            email=cliente.usuario.email,
            telefono=cliente.usuario.telefono,
            ci_nit=cliente.ci_nit,
            razon_social=cliente.razon_social,
            fecha_nacimiento=cliente.fecha_nacimiento,
            estatura_cm=cliente.estatura_cm,
            preferencia_ajuste=cliente.preferencia_ajuste,
            acepta_datos_foto=cliente.acepta_datos_foto,
        )


class ClientePerfilActualizar(BaseModel):
    telefono: str | None = Field(default=None, max_length=20)
    ci_nit: str | None = Field(default=None, max_length=20)
    razon_social: str | None = Field(default=None, max_length=120)
    fecha_nacimiento: dt.date | None = None
    estatura_cm: int | None = Field(default=None, ge=100, le=250)
    # Mismos valores que el CHECK de la tabla `cliente`: un valor distinto
    # tiene que ser un 422 claro, no un error de la base.
    preferencia_ajuste: Literal["ajustado", "regular", "holgado"] | None = None
    acepta_datos_foto: bool | None = None


# ---- Notificaciones ----


class NotificacionRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    titulo: str
    mensaje: str | None
    tipo: str | None
    referencia_id: int | None
    leida: bool
    creado_en: dt.datetime


# ---- Dispositivos de notificaciones push ----


class DispositivoPushRegistrar(BaseModel):
    # Un token de FCM mide ~160 caracteres y no lleva espacios; el piso de 20 descarta basura obvia.
    token: str = Field(min_length=20, max_length=512, pattern=r"^\S+$")
    plataforma: Literal["android"]


class DispositivoPushQuitar(BaseModel):
    token: str = Field(min_length=1, max_length=512)


# ---- Organización ----


# ---- Ciudades -----------------------------------------------------------


class CiudadCrear(BaseModel):
    nombre: str = Field(max_length=60)
    departamento: str | None = Field(default=None, max_length=60)


class CiudadActualizar(BaseModel):
    nombre: str | None = Field(default=None, max_length=60)
    departamento: str | None = Field(default=None, max_length=60)


class CiudadRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    departamento: str | None = None
    activo: bool


# ---- Sucursales -----------------------------------------------------------
# SucursalRespuesta es la que se expone públicamente (GET /sucursales):
# no incluye datos de empleados, ni los va a incluir nunca. No se agrega
# una relación con Empleado al modelo por esa misma razón.


class SucursalCrear(BaseModel):
    ciudad_id: int
    codigo: str = Field(max_length=15)
    nombre: str = Field(max_length=80)
    direccion: str = Field(max_length=200)
    telefono: str | None = Field(default=None, max_length=20)
    latitud: Decimal | None = None
    longitud: Decimal | None = None
    es_deposito: bool = False


class SucursalActualizar(BaseModel):
    ciudad_id: int | None = None
    codigo: str | None = Field(default=None, max_length=15)
    nombre: str | None = Field(default=None, max_length=80)
    direccion: str | None = Field(default=None, max_length=200)
    telefono: str | None = Field(default=None, max_length=20)
    latitud: Decimal | None = None
    longitud: Decimal | None = None
    es_deposito: bool | None = None
    activo: bool | None = None


class SucursalRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ciudad_id: int
    codigo: str
    nombre: str
    direccion: str
    telefono: str | None = None
    latitud: Decimal | None = None
    longitud: Decimal | None = None
    es_deposito: bool
    activo: bool
    creado_en: dt.datetime


# ---- Horarios de sucursal --------------------------------------------------


class HorarioCrear(BaseModel):
    dia_semana: int = Field(ge=1, le=7)
    hora_apertura: dt.time
    hora_cierre: dt.time

    @model_validator(mode="after")
    def _validar_rango(self) -> "HorarioCrear":
        if self.hora_cierre <= self.hora_apertura:
            raise ValueError("hora_cierre debe ser posterior a hora_apertura")
        return self


class HorarioActualizar(BaseModel):
    hora_apertura: dt.time | None = None
    hora_cierre: dt.time | None = None

    @model_validator(mode="after")
    def _validar_rango(self) -> "HorarioActualizar":
        if (
            self.hora_apertura is not None
            and self.hora_cierre is not None
            and self.hora_cierre <= self.hora_apertura
        ):
            raise ValueError("hora_cierre debe ser posterior a hora_apertura")
        return self


class HorarioRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sucursal_id: int
    dia_semana: int
    hora_apertura: dt.time
    hora_cierre: dt.time


# ---- Empleados ----------------------------------------------------------


class EmpleadoCrear(BaseModel):
    usuario_id: int
    sucursal_id: int | None = None
    ci: str | None = Field(default=None, max_length=20)
    cargo: str | None = Field(default=None, max_length=60)
    fecha_ingreso: dt.date | None = None


class EmpleadoActualizar(BaseModel):
    sucursal_id: int | None = None
    ci: str | None = Field(default=None, max_length=20)
    cargo: str | None = Field(default=None, max_length=60)
    fecha_ingreso: dt.date | None = None
    activo: bool | None = None


class EmpleadoRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    usuario_id: int
    usuario_nombre: str | None = None
    usuario_apellido: str | None = None
    sucursal_id: int | None = None
    sucursal_nombre: str | None = None
    ci: str | None = None
    cargo: str | None = None
    fecha_ingreso: dt.date | None = None
    activo: bool


# ---- Empresas, planes y suscripciones (CU-04) ---------------------------------

COLOR_ACENTO_PATRON = r"^#[0-9A-Fa-f]{6}$"

# Precio mensual de un plan en bolivianos: no negativo, 2 decimales. El anual (20 % menos) se calcula, no se guarda.
PrecioMensualBs = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]


class PlanCrear(BaseModel):
    codigo: str = Field(pattern=r"^[a-z0-9_-]{2,30}$")
    nombre: str = Field(min_length=1, max_length=60)
    max_sucursales: int = Field(ge=1, le=1000)
    reportes_convencionales: bool = True
    reportes_ia: bool = False
    operacion_offline: bool = False
    analitica_ml: bool = False
    copias_seguridad: bool = False
    gestion_productos: bool = True
    gestion_ventas: bool = True
    reservas: bool = True
    max_copias_historial: int = Field(default=0, ge=0, le=1000)
    plazo_cambio_horas_defecto: int = Field(default=24, ge=0, le=8760)
    precio_mensual_bs: PrecioMensualBs | None = None


class PlanActualizar(BaseModel):
    """El `codigo` de un plan no cambia."""

    nombre: str | None = Field(default=None, min_length=1, max_length=60)
    max_sucursales: int | None = Field(default=None, ge=1, le=1000)
    reportes_convencionales: bool | None = None
    reportes_ia: bool | None = None
    operacion_offline: bool | None = None
    analitica_ml: bool | None = None
    copias_seguridad: bool | None = None
    gestion_productos: bool | None = None
    gestion_ventas: bool | None = None
    reservas: bool | None = None
    max_copias_historial: int | None = Field(default=None, ge=0, le=1000)
    plazo_cambio_horas_defecto: int | None = Field(default=None, ge=0, le=8760)
    # `null` explícito borra el precio (el plan queda "a consultar").
    precio_mensual_bs: PrecioMensualBs | None = None
    activo: bool | None = None


class PlanRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    nombre: str
    max_sucursales: int
    reportes_convencionales: bool
    reportes_ia: bool
    operacion_offline: bool
    analitica_ml: bool
    copias_seguridad: bool
    gestion_productos: bool
    gestion_ventas: bool
    reservas: bool
    max_copias_historial: int
    plazo_cambio_horas_defecto: int
    precio_mensual_bs: Decimal | None = None
    activo: bool


class PlanPublicoRespuesta(BaseModel):
    """Lo que la portada pública muestra de un plan (sin `id` ni `activo`)."""

    model_config = ConfigDict(from_attributes=True)

    codigo: str
    nombre: str
    max_sucursales: int
    max_copias_historial: int
    plazo_cambio_horas_defecto: int
    precio_mensual_bs: Decimal | None = None
    gestion_productos: bool
    gestion_ventas: bool
    reservas: bool
    reportes_convencionales: bool
    reportes_ia: bool
    operacion_offline: bool
    analitica_ml: bool
    copias_seguridad: bool


class AdministradorRegistrar(BaseModel):
    nombre: str = Field(min_length=1, max_length=60)
    apellido: str = Field(min_length=1, max_length=60)
    email: CorreoNormalizado
    telefono: str | None = Field(default=None, max_length=20)
    password: str = Field(min_length=8, max_length=72)


class EmpresaRegistrar(BaseModel):
    """Alta de una empresa con su suscripción inicial y su administrador. El
    `codigo` sale del nombre (no se pide)."""

    nombre: str = Field(min_length=2, max_length=120)
    plan_codigo: str | None = Field(default=None, max_length=30)
    fecha_vencimiento: dt.date | None = None
    color_acento: str | None = Field(default=None, pattern=COLOR_ACENTO_PATRON)
    logo_url: str | None = None
    administrador: AdministradorRegistrar


class AdministradorPrueba(AdministradorRegistrar):
    """El administrador de una prueba gratuita pública: los mismos campos, pero un campo desconocido se rechaza."""

    model_config = ConfigDict(extra="forbid")


class PruebaGratisSolicitud(BaseModel):
    """Prueba gratuita pública (sin sesión, sin pago): la empresa nace activa con el plan elegido. El visitante no
    elige fechas, logo ni color: esos los fija el servidor o se editan después desde `PUT /mi-empresa`."""

    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(min_length=2, max_length=120)
    plan_codigo: str = Field(min_length=1, max_length=30)
    administrador: AdministradorPrueba


class PruebaGratisRespuesta(BaseModel):
    """Lo mínimo para que la pantalla lleve al visitante a su tienda: nunca trae hashes, tokens ni contraseña."""

    empresa_codigo: str
    empresa_nombre: str
    plan_codigo: str
    plan_nombre: str
    es_prueba: bool
    fecha_inicio: dt.date
    fecha_vencimiento: dt.date


PeriodoContratacion = Literal["mensual", "anual"]


class PedidoSolicitud(PruebaGratisSolicitud):
    """Compra de un plan con PayPal (sin sesión): la misma forma que la prueba gratuita más el `periodo`. El cliente
    NUNCA manda montos, moneda ni fechas: el servidor recalcula todo desde el precio del plan."""

    periodo: PeriodoContratacion


class PedidoCreadoRespuesta(BaseModel):
    """El pedido recién creado: a `url_aprobacion` (PayPal) hay que mandar al comprador. `token` identifica el pedido
    en las demás rutas. Montos en texto decimal; `expira_en` en UTC. Nunca trae correo, hash ni contraseña."""

    token: str
    url_aprobacion: str
    plan_codigo: str
    plan_nombre: str
    periodo: PeriodoContratacion
    monto_bs: Decimal
    monto_usd: Decimal
    tipo_cambio: Decimal
    expira_en: dt.datetime


class PedidoEstadoRespuesta(BaseModel):
    """Estado público de un pedido. Sin correo ni datos personales; `empresa_codigo` solo si ya está completado."""

    estado: str
    plan_codigo: str
    plan_nombre: str
    periodo: PeriodoContratacion
    monto_bs: Decimal
    monto_usd: Decimal
    tipo_cambio: Decimal
    expira_en: dt.datetime | None = None
    empresa_codigo: str | None = None


class PedidoPagadoRespuesta(BaseModel):
    """El pago está cobrado y la empresa creada (también al repetir la captura de un pedido ya completado)."""

    estado: str
    empresa_codigo: str
    empresa_nombre: str
    plan_codigo: str
    plan_nombre: str
    periodo: PeriodoContratacion
    es_prueba: bool
    fecha_inicio: dt.date | None = None
    fecha_vencimiento: dt.date | None = None
    monto_bs: Decimal
    monto_usd: Decimal


class EmpresaActualizar(BaseModel):
    """El `codigo` no cambia aunque cambie el nombre comercial."""

    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    logo_url: str | None = None
    color_acento: str | None = Field(default=None, pattern=COLOR_ACENTO_PATRON)
    activo: bool | None = None


class EmpresaRespuesta(BaseModel):
    id: int
    codigo: str
    nombre: str
    logo_url: str | None = None
    color_acento: str | None = None
    activo: bool
    plan_codigo: str | None = None
    suscripcion_estado: str | None = None
    fecha_inicio: dt.date | None = None
    fecha_vencimiento: dt.date | None = None
    administrador_email: str | None = None


class EmpresaResumenRespuesta(EmpresaRespuesta):
    usuarios_activos: int
    sucursales_activas: int
    max_sucursales: int | None = None


class SuscripcionAsignar(BaseModel):
    """Asigna un plan a una empresa o lo CAMBIA (cierra la suscripción vigente)."""

    empresa_id: int
    plan_codigo: str = Field(max_length=30)
    fecha_inicio: dt.date | None = None
    fecha_vencimiento: dt.date | None = None


class SuscripcionRenovar(BaseModel):
    fecha_vencimiento: dt.date


class SuscripcionEstadoActualizar(BaseModel):
    """`vencida` no se pide: la fija el cálculo por fecha y la tarea periódica."""

    estado: Literal["activa", "suspendida", "cancelada"]


class SuscripcionRespuesta(BaseModel):
    id: int
    empresa_id: int
    plan_codigo: str
    plan_nombre: str
    estado: str
    estado_efectivo: str
    fecha_inicio: dt.date
    fecha_vencimiento: dt.date
    es_prueba: bool = False
    creado_en: dt.datetime | None = None


class MiEmpresaRespuesta(BaseModel):
    id: int
    codigo: str
    nombre: str
    logo_url: str | None = None
    color_acento: str | None = None
    activo: bool
    # Plazo propio para devolver o cambiar prendas (None = usa el del plan) y el que
    # rige hoy (D19, E08).
    plazo_cambio_horas: int | None = None
    plazo_cambio_horas_efectivo: int


class MiEmpresaActualizar(BaseModel):
    """La identidad visual y el plazo de cambio. Un plan, un estado o el código
    enviados aquí se ignoran. `plazo_cambio_horas`: 1 a 720, o `null` para volver
    al plazo del plan."""

    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    logo_url: str | None = None
    color_acento: str | None = Field(default=None, pattern=COLOR_ACENTO_PATRON)
    plazo_cambio_horas: int | None = Field(default=None, ge=1, le=720)


class MiSuscripcionRespuesta(BaseModel):
    plan_codigo: str | None = None
    plan_nombre: str | None = None
    estado: str
    fecha_inicio: dt.date | None = None
    fecha_vencimiento: dt.date | None = None
    es_prueba: bool = False
    max_sucursales: int | None = None
    sucursales_activas: int
    funcionalidades: list[str] = []


class TiendaPublicaRespuesta(BaseModel):
    """Lo único que se publica de una empresa."""

    model_config = ConfigDict(from_attributes=True)

    codigo: str
    nombre: str
    logo_url: str | None = None
    color_acento: str | None = None


class TiendaPublicaDetalle(TiendaPublicaRespuesta):
    """Los datos de UNA tienda (`GET /public/{codigo}/tienda`): suma `disponible`,
    que es falso cuando la suscripción de la empresa no está activa. La lista
    de tiendas no lleva el campo (solo muestra las disponibles)."""

    disponible: bool = True


# ---- Bitácora ----


class BitacoraRespuesta(BaseModel):
    """Una fila de la bitácora. `empresa_id` solo se informa al superadministrador;
    al administrador de una empresa, una acción de la plataforma le llega con el
    actor enmascarado y sin IP."""

    id: int
    empresa_id: int | None = None
    usuario_id: int | None = None
    usuario_nombre: str | None = None
    entidad: str
    entidad_id: int | None = None
    accion: str
    datos: dict | None = None
    ip: str | None = None
    creado_en: dt.datetime


class BitacoraPagina(BaseModel):
    total: int
    pagina: int
    tamanio: int
    items: list[BitacoraRespuesta]


# ---- Copias de seguridad (E22) -------------------------------------------------------------------------------------


class CopiaRespuesta(BaseModel):
    """Los metadatos de una copia (el ZIP no se conserva). `checksum` es el SHA-256 del archivo: sirve para comprobar
    uno ya descargado. `motivo_fallo` es un código estable, nunca el detalle técnico."""

    id: int
    estado: str
    usuario_id: int
    usuario_nombre: str | None = None
    tamano_bytes: int | None = None
    total_filas: int | None = None
    tablas_incluidas: dict[str, int] | None = None
    version_esquema: str | None = None
    checksum: str | None = None
    motivo_fallo: str | None = None
    creado_en: dt.datetime
    terminado_en: dt.datetime | None = None


class CopiaPagina(BaseModel):
    total: int
    pagina: int
    tamanio: int
    items: list[CopiaRespuesta]


class TablaExcluidaRespuesta(BaseModel):
    tabla: str
    motivo: str


class CopiaTablasRespuesta(BaseModel):
    """Qué incluye la copia y qué no (alimenta el panel "Qué incluye y qué no" de la pantalla)."""

    incluidas: list[str]
    referencias: list[str]
    excluidas: list[TablaExcluidaRespuesta]
    columnas_excluidas: dict[str, list[str]]


class FiltrosBitacora(BaseModel):
    """Filtros de la consulta. `empresa_id` y `sin_empresa` solo los usa el
    superadministrador: en la consulta de una empresa se ignoran."""

    desde: dt.date
    hasta: dt.date
    entidad: str | None = None
    accion: str | None = None
    usuario_id: int | None = None
    empresa_id: int | None = None
    sin_empresa: bool = False

