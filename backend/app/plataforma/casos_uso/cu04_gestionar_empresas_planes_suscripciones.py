"""CU-04 - Gestionar empresas, planes y suscripciones

Actor: Superadministrador de la plataforma (y Administrador de empresa para
consultar su propia empresa, plan y suscripción).
Precondición: sesión de superadministrador con plataforma.gestionar (o de
administrador con empresa.gestionar).
Postcondición: empresa registrada con su suscripción, administrador y catálogos
base; plan y estado de suscripción actualizados y reflejados en el backend
(límites de sucursales, funcionalidades y bloqueo por suscripción).

Caso de uso COMPUESTO: seis clases de control en este archivo.

- GestionarEmpresas: registrar (una sola transacción), actualizar, desactivar,
  resumen, alta de administrador y de sucursal sobre una empresa ajena y la
  lista pública de tiendas.
- GestionarContratacion (actor: visitante sin sesión): la prueba gratuita pública
  y la COMPRA de un plan con PayPal. La prueba crea la empresa, su suscripción de
  prueba, su administrador y el pedido de contratación en UNA transacción, con el
  mismo núcleo que `registrar` (una prueba por correo; sin verificación de correo
  y sin pago). La compra crea un pedido `pendiente` y su orden de PayPal
  (`crear_pedido`) y, cuando el comprador vuelve, consulta DIRECTAMENTE a PayPal,
  captura el dinero y crea la empresa UNA sola vez (`capturar_pedido`).
- GestionarPlanes: planes con límites y funcionalidades configurables.
- GestionarSuscripciones: asignar o cambiar de plan, renovar, suspender,
  reactivar, cancelar y vencer.
- ConsultarMiEmpresa: la empresa, el plan y la suscripción de quien administra.
- GestionarCopiasSeguridad (E22): el administrador de una empresa con plan
  Profesional y suscripción activa crea y descarga una copia de TODOS los datos de
  SU empresa (ZIP con un JSON por tabla y un manifiesto con checksums), consulta
  el historial de copias (solo metadatos: el ZIP no se conserva) y qué incluye la
  copia. El motor vive en core/copias.py.

El superadministrador no tiene empresa en su sesión: para tocar los datos de
una empresa entra con `core.tenant.en_empresa`, que restaura el modo
plataforma al salir y vacía el mapa de identidad de la sesión. Por eso cada
operación guarda los valores que necesita (ids, códigos) y arma su respuesta
DENTRO del bloque. La lógica reutilizable (estados, transiciones, límites) vive
en plataforma/politicas.py."""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import secrets
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import Connection, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import copias, paypal
from app.core.auditoria import (
    ACCION_ACTUALIZAR,
    ACCION_ASIGNAR_PLAN,
    ACCION_CAMBIAR_ESTADO,
    ACCION_CAMBIAR_PLAN,
    ACCION_CAMBIAR_PLAZO_CAMBIO,
    ACCION_CANCELAR,
    ACCION_CAPTURAR,
    ACCION_CREAR,
    ACCION_DESACTIVAR,
    ACCION_DESCARGAR,
    ACCION_ELIMINAR,
    ACCION_FALLAR,
    ACCION_PAGADO_SIN_EMPRESA,
    ACCION_PAGO_NO_COINCIDE,
    ACCION_RENOVAR,
    ACCION_VENCER,
    ENTIDAD_COPIA_SEGURIDAD,
    ENTIDAD_EMPRESA,
    ENTIDAD_PEDIDO_CONTRATACION,
    ENTIDAD_PLAN,
    ENTIDAD_SUCURSAL,
    ENTIDAD_SUSCRIPCION,
    ENTIDAD_USUARIO,
    ContextoAuditoria,
    diff_campos,
)
from app.core.config import get_settings
from app.core.deps import ParametrosPaginacion
from app.core.exceptions import ConflictoError, DomainError, ErrorFuncional, NoEncontradoError
from app.core.permisos import ROL_ADMINISTRADOR
from app.core.planes import FUNC_COPIAS_SEGURIDAD, verificar_funcionalidad, verificar_suscripcion_activa
from app.core.security import hash_password
from app.core.tenant import en_empresa, exigir_empresa, inicializar_empresa
from app.core.tiempo import ahora_bolivia, ahora_utc_naive, hoy_utc
from app.plataforma import politicas
from app.plataforma.models import CopiaSeguridad, Empresa, Plan, Suscripcion, Usuario
from app.plataforma.repository import (
    CopiaSeguridadRepository,
    EmpresaRepository,
    PedidoContratacionRepository,
    PlanRepository,
    SucursalRepository,
    SuscripcionRepository,
    UsuarioRepository,
)
from app.plataforma.schemas import (
    AdministradorRegistrar,
    CopiaPagina,
    CopiaRespuesta,
    CopiaTablasRespuesta,
    EmpresaActualizar,
    EmpresaRegistrar,
    EmpresaRespuesta,
    EmpresaResumenRespuesta,
    MiEmpresaActualizar,
    MiEmpresaRespuesta,
    MiSuscripcionRespuesta,
    PedidoCreadoRespuesta,
    PedidoEstadoRespuesta,
    PedidoPagadoRespuesta,
    PedidoSolicitud,
    PlanActualizar,
    PlanCrear,
    PruebaGratisRespuesta,
    PruebaGratisSolicitud,
    SucursalCrear,
    SucursalRespuesta,
    SuscripcionAsignar,
    SuscripcionEstadoActualizar,
    SuscripcionRenovar,
    SuscripcionRespuesta,
    TiendaPublicaDetalle,
    TiendaPublicaRespuesta,
    UsuarioCrear,
    UsuarioRespuesta,
)

PLAN_POR_DEFECTO = "basico"
CAMPOS_ANULABLES_EMPRESA = ("logo_url", "color_acento")


# ---- Apoyo común de las cuatro clases -------------------------------------------


@contextmanager
def _transaccion(db: Session, conflicto: str = "La operación choca con un registro existente"):
    """Una sola unidad de trabajo: confirma al terminar y revierte TODO si algo
    falla. Una violación de unicidad de la base (carrera entre dos peticiones)
    se responde 409."""
    try:
        yield
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictoError(conflicto) from exc
    except Exception:
        db.rollback()
        raise


def _sin_nulos(datos: BaseModel, destino: type[BaseModel] | None = None, anulables: tuple[str, ...] = ()):
    """Los campos enviados que traen valor. Un `null` explícito en una columna
    NOT NULL (nombre, límites, estado) no la vacía: se ignora. Las columnas de
    `anulables` sí aceptan `null` (borrar el logo)."""
    campos = {
        campo: valor
        for campo, valor in datos.model_dump(exclude_unset=True).items()
        if valor is not None or campo in anulables
    }
    return (destino or type(datos))(**campos)


def _fecha_vencimiento_valida(inicio: dt.date, vencimiento: dt.date, hoy: dt.date) -> None:
    if vencimiento <= hoy:
        raise DomainError("La fecha de vencimiento debe ser posterior a hoy", 422)
    if vencimiento < inicio:
        raise DomainError("La fecha de vencimiento no puede ser anterior a la de inicio", 422)


def _plan_asignable(planes: PlanRepository, db: Session, codigo: str) -> Plan:
    """El plan por su código: 404 si no existe, 409 si está inactivo."""
    plan = planes.obtener_por_codigo(db, codigo.strip().lower())
    if plan is None:
        raise NoEncontradoError("Plan no encontrado")
    if not plan.activo:
        raise ConflictoError("El plan está inactivo")
    return plan


def _respuesta_suscripcion(suscripcion: Suscripcion, plan: Plan) -> SuscripcionRespuesta:
    return SuscripcionRespuesta(
        id=suscripcion.id,
        empresa_id=suscripcion.empresa_id,
        plan_codigo=plan.codigo,
        plan_nombre=plan.nombre,
        estado=suscripcion.estado,
        estado_efectivo=politicas.estado_efectivo(suscripcion),
        fecha_inicio=suscripcion.fecha_inicio,
        fecha_vencimiento=suscripcion.fecha_vencimiento,
        es_prueba=suscripcion.es_prueba,
        creado_en=suscripcion.creado_en,
    )


def _respuesta_empresa(
    empresa: Empresa, ficha: tuple[Suscripcion, Plan] | None = None, administrador_email: str | None = None
) -> EmpresaRespuesta:
    """`ficha` = (suscripción vigente, su plan). Es el estado EFECTIVO el que se
    informa."""
    suscripcion, plan = ficha if ficha is not None else (None, None)
    return EmpresaRespuesta(
        id=empresa.id,
        codigo=empresa.codigo,
        nombre=empresa.nombre,
        logo_url=empresa.logo_url,
        color_acento=empresa.color_acento,
        activo=empresa.activo,
        plan_codigo=plan.codigo if plan is not None else None,
        suscripcion_estado=politicas.estado_efectivo(suscripcion) if suscripcion is not None else None,
        fecha_inicio=suscripcion.fecha_inicio if suscripcion is not None else None,
        fecha_vencimiento=suscripcion.fecha_vencimiento if suscripcion is not None else None,
        administrador_email=administrador_email,
    )


@dataclass(frozen=True)
class _EmpresaCreada:
    """Lo que el alta devuelve ya con valores simples (la sesión suelta los objetos al cambiar de empresa)."""

    empresa_id: int
    codigo: str
    nombre: str
    plan_codigo: str
    plan_nombre: str
    fecha_inicio: dt.date
    fecha_vencimiento: dt.date
    administrador_email: str


def _crear_empresa_completa(
    db: Session,
    *,
    nombre: str,
    codigo: str,
    plan: Plan,
    fecha_inicio: dt.date,
    fecha_vencimiento: dt.date,
    administrador: BaseModel,
    password_hash: str,
    logo_url: str | None = None,
    color_acento: str | None = None,
    es_prueba: bool = False,
    contexto: ContextoAuditoria | None = None,
) -> _EmpresaCreada:
    """Núcleo ÚNICO del alta de una empresa, SIN confirmar (la transacción es de quien lo llama): la empresa, su
    suscripción activa (`es_prueba` si es gratuita), su administrador (con un hash bcrypt ya calculado; `administrador`
    aporta nombre, apellido, email y teléfono), los catálogos base y la fila de bitácora. Lo usan el alta del
    superadministrador (`GestionarEmpresas.registrar`) y la prueba gratuita pública (`GestionarContratacion`).
    Funciona con la sesión del superadministrador y con una anónima: la empresa nueva va explícita."""
    plan_id, plan_codigo, plan_nombre = plan.id, plan.codigo, plan.nombre
    empresa = EmpresaRepository().insertar(db, nombre, codigo, logo_url, color_acento)
    empresa_id = empresa.id
    # La sesión no tiene empresa: la suscripción lleva la suya explícita.
    SuscripcionRepository().insertar(db, empresa_id, plan_id, fecha_inicio, fecha_vencimiento, es_prueba=es_prueba)
    usuarios = UsuarioRepository()
    with en_empresa(db, empresa_id):
        usuario = usuarios.crear_con_hash(db, administrador, password_hash, commit=False)
        usuario = usuarios.asignar_roles(db, usuario, [ROL_ADMINISTRADOR], commit=False)
        correo = usuario.email
    inicializar_empresa(db, empresa_id)
    # Sin el correo ni el nombre del administrador. Actor: el superadministrador, o nadie (alta pública).
    detalle: dict = {"codigo": codigo, "plan": plan_codigo}
    if es_prueba:
        detalle["es_prueba"] = True
    politicas.registrar_bitacora_de(db, contexto, ENTIDAD_EMPRESA, empresa_id, ACCION_CREAR, detalle, empresa_id=empresa_id)
    return _EmpresaCreada(
        empresa_id=empresa_id,
        codigo=codigo,
        nombre=nombre,
        plan_codigo=plan_codigo,
        plan_nombre=plan_nombre,
        fecha_inicio=fecha_inicio,
        fecha_vencimiento=fecha_vencimiento,
        administrador_email=correo,
    )


# ---- Empresas ---------------------------------------------------------------------


class GestionarEmpresas:
    """Las empresas contratantes de la plataforma. Solo las usa el
    superadministrador, salvo la lista pública de tiendas."""

    def __init__(self) -> None:
        self._repo = EmpresaRepository()
        self._planes = PlanRepository()
        self._suscripciones = SuscripcionRepository()
        self._usuarios = UsuarioRepository()
        self._sucursales = SucursalRepository()

    # -- Consulta ----------------------------------------------------------------

    def _buscar(self, db: Session, empresa_id: int) -> Empresa:
        empresa = self._repo.buscar(db, empresa_id)
        if empresa is None:
            raise NoEncontradoError("Empresa no encontrada")
        return empresa

    def _correo_administrador(self, db: Session, empresa_id: int) -> str | None:
        """Correo del administrador principal (el activo de menor id)."""
        with en_empresa(db, empresa_id):
            administrador = politicas.administrador_principal(db)
            return administrador.email if administrador is not None else None

    def listar(
        self, db: Session, paginacion: ParametrosPaginacion, q: str | None = None, activo: bool | None = None
    ) -> list[EmpresaRespuesta]:
        empresas = self._repo.listar_filtrado(db, paginacion, q, activo)
        fichas = self._suscripciones.vigentes_de(db, [e.id for e in empresas])
        return [_respuesta_empresa(e, fichas.get(e.id)) for e in empresas]

    def obtener(self, db: Session, empresa_id: int) -> EmpresaRespuesta:
        empresa = self._buscar(db, empresa_id)
        ficha = self._suscripciones.vigentes_de(db, [empresa_id]).get(empresa_id)
        respuesta = _respuesta_empresa(empresa, ficha)  # antes de entrar en la empresa: vacía la sesión
        respuesta.administrador_email = self._correo_administrador(db, empresa_id)
        return respuesta

    def resumen(self, db: Session, empresa_id: int) -> EmpresaResumenRespuesta:
        """Usuarios activos, sucursales activas (el depósito cuenta), plan, estado
        efectivo y administrador principal de la empresa."""
        base = self.obtener(db, empresa_id)
        with en_empresa(db, empresa_id):
            usuarios = politicas.contar_usuarios_activos(db)
            sucursales = politicas.contar_sucursales_activas(db)
            plan = politicas.plan_de_la_empresa(db)
            limite = plan.max_sucursales if plan is not None else None
        return EmpresaResumenRespuesta(
            **base.model_dump(), usuarios_activos=usuarios, sucursales_activas=sucursales, max_sucursales=limite
        )

    # -- Registro ----------------------------------------------------------------

    def registrar(
        self, db: Session, datos: EmpresaRegistrar, contexto: ContextoAuditoria | None = None
    ) -> EmpresaRespuesta:
        """Alta de una empresa en UNA transacción: la empresa, su suscripción
        activa, su administrador y los catálogos base (tallas, materiales,
        ciudades). Cualquier error revierte todo y no queda nada a medias. La
        respuesta nunca trae la contraseña."""
        codigo = politicas.normalizar_nombre_empresa(datos.nombre)
        if not codigo:
            raise DomainError("El nombre de la empresa no es válido")
        politicas.validar_codigo_empresa_disponible(codigo)
        if self._repo.obtener_por_codigo(db, codigo) is not None:
            raise ConflictoError("Ya existe una empresa con ese nombre")

        hoy = hoy_utc()
        vencimiento = datos.fecha_vencimiento or hoy + dt.timedelta(days=get_settings().suscripcion_dias_por_defecto)
        _fecha_vencimiento_valida(hoy, vencimiento, hoy)
        plan = _plan_asignable(self._planes, db, datos.plan_codigo or PLAN_POR_DEFECTO)
        password_hash = hash_password(datos.administrador.password)

        with _transaccion(db, "Ya existe una empresa con ese nombre"):
            creada = _crear_empresa_completa(
                db,
                nombre=datos.nombre.strip(),
                codigo=codigo,
                plan=plan,
                fecha_inicio=hoy,
                fecha_vencimiento=vencimiento,
                administrador=datos.administrador,
                password_hash=password_hash,
                logo_url=datos.logo_url,
                color_acento=datos.color_acento,
                contexto=contexto,
            )
        return EmpresaRespuesta(
            id=creada.empresa_id,
            codigo=creada.codigo,
            nombre=creada.nombre,
            logo_url=datos.logo_url,
            color_acento=datos.color_acento,
            activo=True,
            plan_codigo=creada.plan_codigo,
            suscripcion_estado="activa",
            fecha_inicio=creada.fecha_inicio,
            fecha_vencimiento=creada.fecha_vencimiento,
            administrador_email=creada.administrador_email,
        )

    def _crear_administrador(self, db: Session, datos: AdministradorRegistrar) -> Usuario:
        """Dentro de `en_empresa`: el usuario (correo único en la empresa, clave
        con bcrypt) con el rol administrador. Sin confirmar."""
        usuario = self._usuarios.crear(db, UsuarioCrear(**datos.model_dump()), commit=False)
        return self._usuarios.asignar_roles(db, usuario, [ROL_ADMINISTRADOR], commit=False)

    # -- Cambios -----------------------------------------------------------------

    def actualizar(
        self, db: Session, empresa_id: int, datos: EmpresaActualizar, contexto: ContextoAuditoria | None = None
    ) -> EmpresaRespuesta:
        """Nombre comercial, logo, color de acento y estado. El código NO cambia."""
        cambios = _sin_nulos(datos, anulables=CAMPOS_ANULABLES_EMPRESA)
        actual = self._repo.buscar(db, empresa_id)
        detalle = diff_campos(actual, cambios.model_dump(exclude_unset=True), ("activo",)) if actual else {}
        self._repo.actualizar(db, empresa_id, cambios, commit=False)
        politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_EMPRESA, empresa_id, ACCION_ACTUALIZAR, detalle, empresa_id=empresa_id
        )
        db.commit()
        return self.obtener(db, empresa_id)

    def desactivar(
        self, db: Session, empresa_id: int, contexto: ContextoAuditoria | None = None
    ) -> EmpresaRespuesta:
        """Baja lógica: bloquea el login y los tokens ya emitidos de la empresa."""
        self._repo.desactivar(db, empresa_id, commit=False)
        politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_EMPRESA, empresa_id, ACCION_DESACTIVAR, {}, empresa_id=empresa_id
        )
        db.commit()
        return self.obtener(db, empresa_id)

    # -- Asociar usuarios y sucursales a una empresa ajena -----------------------------

    def _exigir_activa(self, db: Session, empresa_id: int) -> None:
        if not self._buscar(db, empresa_id).activo:
            raise ConflictoError("La empresa está inactiva")

    def agregar_administrador(
        self, db: Session, empresa_id: int, datos: AdministradorRegistrar, contexto: ContextoAuditoria | None = None
    ) -> UsuarioRespuesta:
        """Otro administrador para la empresa (solo con el rol administrador)."""
        self._exigir_activa(db, empresa_id)
        with _transaccion(db, "Ya existe un usuario con ese email"):
            with en_empresa(db, empresa_id):
                administrador = self._crear_administrador(db, datos)
                respuesta = UsuarioRespuesta.from_modelo(administrador)
                politicas.registrar_bitacora_de(
                    db, contexto, ENTIDAD_USUARIO, administrador.id, ACCION_CREAR,
                    {"reactivado": False, "rol": ROL_ADMINISTRADOR}, empresa_id=empresa_id,
                )  # fmt: skip
        return respuesta

    def agregar_sucursal(
        self, db: Session, empresa_id: int, datos: SucursalCrear, contexto: ContextoAuditoria | None = None
    ) -> SucursalRespuesta:
        """Una sucursal para la empresa. Pasa por el mismo repositorio que el
        alta de la propia empresa, así que respeta el límite de su plan."""
        self._exigir_activa(db, empresa_id)
        with _transaccion(db, "Ya existe una sucursal con ese código"):
            with en_empresa(db, empresa_id):
                sucursal = self._sucursales.crear(db, datos, commit=False)
                respuesta = SucursalRespuesta.model_validate(sucursal)
                politicas.registrar_bitacora_de(
                    db, contexto, ENTIDAD_SUCURSAL, sucursal.id, ACCION_CREAR,
                    {"codigo": sucursal.codigo}, empresa_id=empresa_id,
                )  # fmt: skip
        return respuesta

    # -- Tiendas públicas ----------------------------------------------------------------

    def listar_tiendas(
        self, db: Session, paginacion: ParametrosPaginacion, q: str | None = None
    ) -> list[TiendaPublicaRespuesta]:
        """Empresas activas con suscripción activa. Solo código, nombre, logo y
        color de acento."""
        return [TiendaPublicaRespuesta.model_validate(e) for e in self._repo.listar_publicas(db, paginacion, q)]

    def obtener_tienda(self, db: Session, codigo: str) -> TiendaPublicaDetalle:
        empresa = self._repo.obtener_por_codigo(db, codigo.strip().lower())
        if empresa is None or not empresa.activo:
            raise NoEncontradoError("Tienda no encontrada")
        tienda = TiendaPublicaDetalle.model_validate(empresa)
        tienda.disponible = self._repo.tiene_suscripcion_activa(db, empresa.id)
        return tienda


# ---- Contratación pública ------------------------------------------------------------------

registro_contratacion = logging.getLogger("app.contratacion")

# Estados de un pedido que ya recibieron el dinero (o lo tienen cobrado y falta la empresa).
ESTADOS_COBRADOS = ("pagado", "pagado_sin_empresa", "completado")
MENSAJE_PAGADO_SIN_EMPRESA = (
    "Recibimos tu pago, pero no pudimos crear la empresa (por ejemplo, otra empresa tomó ese nombre mientras pagabas). "
    "Tu pago quedó registrado: comunícate con soporte para resolverlo o pedir el reembolso."
)


class _AdministradorGuardado(BaseModel):
    """Los datos del administrador tal como quedaron en el pedido (sin contraseña: solo se guarda su hash)."""

    nombre: str
    apellido: str
    email: str
    telefono: str | None = None


@dataclass(frozen=True)
class _DatosPedido:
    """Copia con valores simples de un pedido: crear la empresa cambia de empresa la sesión y suelta los objetos
    cargados antes, así que nada usa el modelo después de ese punto. Contiene el hash de la contraseña y el correo:
    nunca se registra ni se devuelve."""

    id: int
    estado: str
    plan_id: int
    periodo: str
    empresa_nombre: str
    empresa_codigo: str
    admin_nombre: str
    admin_apellido: str
    admin_email: str
    admin_telefono: str | None
    admin_password_hash: str
    monto_bs: Decimal
    monto_usd: Decimal
    tipo_cambio: Decimal
    paypal_order_id: str | None
    empresa_creada_id: int | None
    expira_en: dt.datetime | None

    @classmethod
    def de(cls, pedido) -> "_DatosPedido":
        return cls(
            id=pedido.id,
            estado=pedido.estado,
            plan_id=pedido.plan_id,
            periodo=pedido.periodo,
            empresa_nombre=pedido.empresa_nombre,
            empresa_codigo=pedido.empresa_codigo,
            admin_nombre=pedido.admin_nombre,
            admin_apellido=pedido.admin_apellido,
            admin_email=pedido.admin_email,
            admin_telefono=pedido.admin_telefono,
            admin_password_hash=pedido.admin_password_hash,
            monto_bs=pedido.monto_bs,
            monto_usd=pedido.monto_usd,
            tipo_cambio=pedido.tipo_cambio,
            paypal_order_id=pedido.paypal_order_id,
            empresa_creada_id=pedido.empresa_creada_id,
            expira_en=pedido.expira_en,
        )


def _en_utc(fecha: dt.datetime | None) -> dt.datetime | None:
    """Las fechas de la base son UTC sin zona; hacia el cliente salen con zona para que no las lea como locales."""
    return fecha.replace(tzinfo=dt.timezone.utc) if fecha is not None and fecha.tzinfo is None else fecha


class GestionarContratacion:
    """Contratación desde la portada pública, sin sesión (CU-04; no es un caso de uso nuevo): la PRUEBA GRATUITA y la
    COMPRA de un plan con PayPal.

    PRUEBA. El visitante elige CUALQUIER plan activo y recibe una empresa ya activa durante `prueba_dias` días completos,
    con su administrador y los datos base. Una prueba por correo del administrador (índice único parcial
    `ux_pedido_prueba_correo`); no hay verificación de correo ni pago. Al vencer, la suscripción queda vencida (la tienda
    pasa a "no disponible") y no se borra nada. Comparte con el alta del superadministrador el núcleo
    `_crear_empresa_completa`; la empresa sale del servidor, nunca del cliente.

    COMPRA (`crear_pedido`, `consultar_pedido`, `cancelar_pedido`, `capturar_pedido`). La empresa NO existe hasta que el
    pago se confirma. El servidor recalcula el monto (Bs, USD y tipo de cambio) y lo guarda en el pedido; el navegador
    solo conserva el `token`. `capturar_pedido` es idempotente y no confía en el navegador: pregunta a PayPal. Si
    PayPal cobró y la empresa ya no se puede crear, el pedido queda `pagado_sin_empresa` (reembolso manual)."""

    def __init__(self) -> None:
        self._empresas = EmpresaRepository()
        self._planes = PlanRepository()
        self._pedidos = PedidoContratacionRepository()
        self._suscripciones = SuscripcionRepository()

    @staticmethod
    def _prueba_ya_usada() -> ErrorFuncional:
        return ErrorFuncional("prueba_ya_usada", "Este correo ya usó su prueba gratuita", 409)

    def iniciar_prueba(
        self, db: Session, datos: PruebaGratisSolicitud, contexto: ContextoAuditoria | None = None
    ) -> PruebaGratisRespuesta:
        """Crea la empresa de prueba y su pedido (tipo `prueba`, estado final `completado`) en UNA transacción: si algo
        falla, incluida la carrera por el mismo correo, no queda nada a medias. 404/409 plan inexistente/inactivo, 422
        `nombre_empresa_reservado`, 409 nombre duplicado y 409 `prueba_ya_usada`. La IP viene del `contexto`."""
        administrador = datos.administrador
        correo = administrador.email  # ya en minúsculas (CorreoNormalizado)
        nombre = datos.nombre.strip()
        plan = _plan_asignable(self._planes, db, datos.plan_codigo)
        plan_id = plan.id
        codigo = politicas.normalizar_nombre_empresa(nombre)
        if not codigo:
            raise DomainError("El nombre de la empresa no es válido")
        politicas.validar_codigo_empresa_disponible(codigo)
        if self._empresas.obtener_por_codigo(db, codigo) is not None:
            raise ConflictoError("Ya existe una empresa con ese nombre")
        if self._pedidos.prueba_que_ocupa_el_correo(db, correo) is not None:
            raise self._prueba_ya_usada()

        hoy = hoy_utc()
        # El vencimiento es inclusivo: hoy + (N - 1) deja N días completos de uso.
        vencimiento = hoy + dt.timedelta(days=max(get_settings().prueba_dias, 1) - 1)
        password_hash = hash_password(administrador.password)
        ip = contexto.ip[:45] if contexto is not None and contexto.ip else None

        try:
            with _transaccion(db, "Ya existe una empresa con ese nombre"):
                # El pedido va PRIMERO: si otra petición simultánea ocupa el mismo correo, el índice único salta
                # antes de crear nada pesado y el rollback lo deshace todo.
                pedido = self._pedidos.insertar(
                    db,
                    token=secrets.token_urlsafe(32),
                    tipo="prueba",
                    plan_id=plan_id,
                    empresa_nombre=nombre,
                    empresa_codigo=codigo,
                    admin_nombre=administrador.nombre,
                    admin_apellido=administrador.apellido,
                    admin_email=correo,
                    admin_telefono=administrador.telefono,
                    admin_password_hash=password_hash,
                    estado="completado",
                    ip=ip,
                )
                pedido_id = pedido.id
                creada = _crear_empresa_completa(
                    db,
                    nombre=nombre,
                    codigo=codigo,
                    plan=plan,
                    fecha_inicio=hoy,
                    fecha_vencimiento=vencimiento,
                    administrador=administrador,
                    password_hash=password_hash,
                    es_prueba=True,
                    contexto=contexto,
                )
                self._pedidos.enlazar_empresa(db, pedido_id, creada.empresa_id)
        except ConflictoError as exc:
            # Una carrera por el correo se ve como violación de unicidad; el pedido ganador ya está confirmado.
            if isinstance(exc.__cause__, IntegrityError) and self._pedidos.prueba_que_ocupa_el_correo(db, correo):
                raise self._prueba_ya_usada() from exc
            raise
        return PruebaGratisRespuesta(
            empresa_codigo=creada.codigo,
            empresa_nombre=creada.nombre,
            plan_codigo=creada.plan_codigo,
            plan_nombre=creada.plan_nombre,
            es_prueba=True,
            fecha_inicio=creada.fecha_inicio,
            fecha_vencimiento=creada.fecha_vencimiento,
        )

    # -- Compra con PayPal -------------------------------------------------------------------

    @staticmethod
    def _paypal_no_disponible() -> ErrorFuncional:
        return ErrorFuncional(
            "paypal_no_disponible", "No pudimos comunicarnos con PayPal. Inténtalo de nuevo en unos minutos", 503
        )

    @staticmethod
    def _pago_no_aprobado(mensaje: str = "Todavía no aprobaste el pago en PayPal") -> ErrorFuncional:
        return ErrorFuncional("pago_no_aprobado", mensaje, 409)

    @staticmethod
    def _error_de_estado(estado: str) -> ErrorFuncional:
        """El 409 de un pedido que ya no admite la operación pedida, con el `codigo` de su estado."""
        if estado == "cancelado":
            return ErrorFuncional("pedido_cancelado", "Este pedido fue cancelado. Crea uno nuevo", 409)
        if estado == "vencido":
            return ErrorFuncional("pedido_vencido", "Este pedido venció sin pagarse. Crea uno nuevo", 409)
        if estado == "fallido":
            return ErrorFuncional(
                "pedido_fallido", "El pago de este pedido no coincidió con lo esperado y no se cobró. Crea uno nuevo", 409
            )
        return ErrorFuncional("pedido_ya_pagado", "Este pedido ya fue pagado", 409)

    @staticmethod
    def _request_id_de(token: str) -> str:
        """Clave de idempotencia de la captura (`PayPal-Request-Id`): siempre la misma para el mismo pedido, y sin
        revelar el token a PayPal."""
        return hashlib.sha256(f"fashionstore-captura:{token}".encode("utf-8")).hexdigest()

    def _estado_publico(self, db: Session, d: _DatosPedido) -> PedidoEstadoRespuesta:
        plan = self._pedidos.obtener_plan(db, d.plan_id)
        empresa_codigo = None
        if d.estado == "completado" and d.empresa_creada_id is not None:
            empresa = self._pedidos.obtener_empresa(db, d.empresa_creada_id)
            empresa_codigo = empresa.codigo if empresa is not None else None
        return PedidoEstadoRespuesta(
            estado=d.estado,
            plan_codigo=plan.codigo,
            plan_nombre=plan.nombre,
            periodo=d.periodo,
            monto_bs=d.monto_bs,
            monto_usd=d.monto_usd,
            tipo_cambio=d.tipo_cambio,
            expira_en=_en_utc(d.expira_en),
            empresa_codigo=empresa_codigo,
        )

    def crear_pedido(
        self, db: Session, datos: PedidoSolicitud, contexto: ContextoAuditoria | None = None
    ) -> PedidoCreadoRespuesta:
        """Crea el pedido `pendiente` y su orden de PayPal; devuelve el token y la URL a la que mandar al comprador.

        TODO O NADA: el pedido y la orden se crean en la misma unidad de trabajo; si PayPal falla, 503
        `paypal_no_disponible` y no queda ningún pedido. Valida lo mismo que la prueba (plan activo, nombre válido,
        no reservado y libre) más `plan_sin_precio` (409). El correo NO se restringe: la misma persona puede comprar
        varias veces. El servidor recalcula montos y tipo de cambio; la contraseña se guarda solo como hash bcrypt."""
        administrador = datos.administrador
        nombre = datos.nombre.strip()
        plan = _plan_asignable(self._planes, db, datos.plan_codigo)
        plan_id, plan_codigo, plan_nombre = plan.id, plan.codigo, plan.nombre
        precio = politicas.calcular_precio_contratacion(plan, datos.periodo)
        codigo = politicas.normalizar_nombre_empresa(nombre)
        if not codigo:
            raise DomainError("El nombre de la empresa no es válido")
        politicas.validar_codigo_empresa_disponible(codigo)
        if self._empresas.obtener_por_codigo(db, codigo) is not None:
            raise ConflictoError("Ya existe una empresa con ese nombre")

        ajustes = get_settings()
        token = secrets.token_urlsafe(32)
        expira_en = ahora_utc_naive() + dt.timedelta(minutes=max(ajustes.pedido_expira_minutos, 1))
        password_hash = hash_password(administrador.password)
        ip = contexto.ip[:45] if contexto is not None and contexto.ip else None
        retorno = f"{ajustes.frontend_public_url.rstrip('/')}/contratar/retorno?pedido={token}"

        with _transaccion(db):
            pedido = self._pedidos.insertar(
                db,
                token=token,
                tipo="pago",
                periodo=datos.periodo,
                plan_id=plan_id,
                empresa_nombre=nombre,
                empresa_codigo=codigo,
                admin_nombre=administrador.nombre,
                admin_apellido=administrador.apellido,
                admin_email=administrador.email,
                admin_telefono=administrador.telefono,
                admin_password_hash=password_hash,
                estado="pendiente",
                monto_bs=precio.monto_bs,
                monto_usd=precio.monto_usd,
                tipo_cambio=precio.tipo_cambio,
                expira_en=expira_en,
                ip=ip,
            )
            pedido_id = pedido.id
            try:
                orden = paypal.crear_orden(
                    monto=precio.monto_usd,
                    moneda="USD",
                    referencia=f"PED-{pedido_id}",
                    descripcion=f"FashionStore - plan {plan_nombre} ({datos.periodo})",
                    return_url=retorno,
                    cancel_url=f"{retorno}&cancelado=1",
                    request_id=self._request_id_de(f"crear:{token}"),
                )
                if not orden.url_aprobacion:
                    raise paypal.PayPalError("PayPal no devolvió la URL de aprobación")
            except paypal.PayPalError as exc:
                # Sin datos del pedido ni del comprador en el registro; el rollback de `_transaccion` borra el pedido.
                registro_contratacion.warning("pedido_paypal_no_crea_orden motivo=%s", type(exc.causa or exc).__name__)
                raise self._paypal_no_disponible() from exc
            self._pedidos.actualizar(db, pedido_id, paypal_order_id=orden.id)
            politicas.registrar_bitacora_de(
                db, contexto, ENTIDAD_PEDIDO_CONTRATACION, pedido_id, ACCION_CREAR,
                {"plan": plan_codigo, "periodo": datos.periodo, "monto_bs": str(precio.monto_bs), "monto_usd": str(precio.monto_usd)},
            )  # fmt: skip
        return PedidoCreadoRespuesta(
            token=token,
            url_aprobacion=orden.url_aprobacion,
            plan_codigo=plan_codigo,
            plan_nombre=plan_nombre,
            periodo=datos.periodo,
            monto_bs=precio.monto_bs,
            monto_usd=precio.monto_usd,
            tipo_cambio=precio.tipo_cambio,
            expira_en=_en_utc(expira_en),
        )

    def consultar_pedido(self, db: Session, token: str) -> PedidoEstadoRespuesta:
        """El estado público del pedido. Sin correo ni datos personales. 404 igual para un token inexistente (o de una
        prueba gratuita)."""
        pedido = self._pedidos.obtener_de_pago(db, token)
        if pedido is None:
            raise NoEncontradoError("Pedido no encontrado")
        return self._estado_publico(db, _DatosPedido.de(pedido))

    def cancelar_pedido(
        self, db: Session, token: str, contexto: ContextoAuditoria | None = None
    ) -> PedidoEstadoRespuesta:
        """`pendiente` -> `cancelado` (el comprador cerró PayPal sin pagar). Idempotente si ya está cancelado; 409 si
        ya se pagó (o venció o falló). No hay nada que anular en PayPal: una orden sin aprobar nunca cobra."""
        with _transaccion(db):
            pedido = self._pedidos.obtener_de_pago(db, token, bloquear=True)
            if pedido is None:
                raise NoEncontradoError("Pedido no encontrado")
            d = _DatosPedido.de(pedido)
            if d.estado == "cancelado":
                return self._estado_publico(db, d)
            if d.estado != "pendiente":
                raise self._error_de_estado(d.estado)
            self._pedidos.actualizar(db, d.id, estado="cancelado")
            politicas.registrar_bitacora_de(db, contexto, ENTIDAD_PEDIDO_CONTRATACION, d.id, ACCION_CANCELAR, {})
            return self._estado_publico(db, replace(d, estado="cancelado"))

    def capturar_pedido(
        self, db: Session, token: str, contexto: ContextoAuditoria | None = None
    ) -> PedidoPagadoRespuesta:
        """Cobra el pedido (si PayPal confirma la aprobación) y crea la empresa. IDEMPOTENTE y SEGURO.

        La fila del pedido se bloquea (FOR UPDATE en PostgreSQL) durante todo el proceso: dos capturas simultáneas se
        serializan y la segunda ve el pedido ya `completado` y devuelve la misma empresa sin cobrar ni crear nada.
        - `completado`: devuelve la empresa creada. `cancelado`/`vencido`/`fallido`: 409 con su `codigo`.
        - `pendiente`: consulta la orden DIRECTAMENTE a PayPal (no confía en el navegador). Sin aprobar: 409
          `pago_no_aprobado` (o `pedido_vencido` si ya expiró). Moneda o monto distintos de los guardados: NO captura,
          `fallido`, 409 `pago_no_coincide`. Aprobada: captura con una clave de idempotencia derivada del token.
        - Cobrado: en la MISMA transacción se crea la empresa (plan del pedido, `es_prueba=False`, vencimiento hoy + 30
          o + 365 días) y el pedido pasa a `completado`. Si la empresa no se puede crear, el pedido queda
          `pagado_sin_empresa` (confirmado aparte, dentro de un SAVEPOINT que descarta lo a medias) y responde 409
          `pagado_sin_empresa`; un nuevo intento NO vuelve a cobrar: solo reintenta crear la empresa.
        - PayPal caído: 503 `paypal_no_disponible`, el pedido sigue `pendiente` y se puede reintentar. Si el proceso
          muriera DESPUÉS de capturar y ANTES de confirmar, el reintento ve la orden ya `COMPLETED` en PayPal y solo crea
          la empresa: el dinero no se cobra dos veces ni se pierde."""
        try:
            pedido = self._pedidos.obtener_de_pago(db, token, bloquear=True)
            if pedido is None:
                raise NoEncontradoError("Pedido no encontrado")
            d = _DatosPedido.de(pedido)
            if d.estado == "completado":
                respuesta = self._respuesta_pagada(db, d)
                db.rollback()  # solo lectura: suelta el bloqueo de la fila
                return respuesta
            if d.estado in ("cancelado", "vencido", "fallido"):
                raise self._error_de_estado(d.estado)
            if d.estado == "pendiente":
                self._cobrar(db, d, token, contexto)
        except Exception:
            db.rollback()  # libera el bloqueo; lo ya confirmado (fallido, vencido) no se pierde
            raise

        # Desde aquí el dinero está cobrado (o ya lo estaba): lo único que falta es crear la empresa.
        plan = self._pedidos.obtener_plan(db, d.plan_id)
        hoy = hoy_utc()
        vencimiento = hoy + dt.timedelta(days=politicas.DIAS_POR_PERIODO[d.periodo])
        try:
            with db.begin_nested():
                creada = _crear_empresa_completa(
                    db,
                    nombre=d.empresa_nombre,
                    codigo=d.empresa_codigo,
                    plan=plan,
                    fecha_inicio=hoy,
                    fecha_vencimiento=vencimiento,
                    administrador=_AdministradorGuardado(
                        nombre=d.admin_nombre, apellido=d.admin_apellido, email=d.admin_email, telefono=d.admin_telefono
                    ),
                    password_hash=d.admin_password_hash,
                    es_prueba=False,
                    contexto=contexto,
                )
                self._pedidos.enlazar_empresa(db, d.id, creada.empresa_id)
                self._pedidos.actualizar(db, d.id, estado="completado")
                politicas.registrar_bitacora_de(
                    db, contexto, ENTIDAD_PEDIDO_CONTRATACION, d.id, ACCION_CAPTURAR,
                    {"plan": creada.plan_codigo, "periodo": d.periodo, "reintento": d.estado != "pendiente"},
                    empresa_id=creada.empresa_id,
                )  # fmt: skip
        except Exception as exc:
            self._dejar_pagado_sin_empresa(db, d, contexto, exc)  # confirma y lanza 409
            raise  # (inalcanzable: lo anterior siempre lanza)
        try:
            db.commit()
        except Exception:
            db.rollback()
            registro_contratacion.error(
                "pedido_pagado_sin_confirmar pedido=%s: el cobro existe en PayPal; reintentar la captura lo completa", d.id
            )
            raise
        return PedidoPagadoRespuesta(
            estado="completado",
            empresa_codigo=creada.codigo,
            empresa_nombre=creada.nombre,
            plan_codigo=creada.plan_codigo,
            plan_nombre=creada.plan_nombre,
            periodo=d.periodo,
            es_prueba=False,
            fecha_inicio=creada.fecha_inicio,
            fecha_vencimiento=creada.fecha_vencimiento,
            monto_bs=d.monto_bs,
            monto_usd=d.monto_usd,
        )

    def _cobrar(self, db: Session, d: _DatosPedido, token: str, contexto: ContextoAuditoria | None) -> None:
        """Pedido `pendiente`: pregunta a PayPal, verifica moneda y monto y captura. Vuelve sin error solo cuando el
        dinero está cobrado. No cambia el estado del pedido salvo para `vencido` y `fallido` (que confirma)."""
        if not d.paypal_order_id:
            raise self._pago_no_aprobado()
        try:
            orden = paypal.obtener_orden(d.paypal_order_id)
        except paypal.PayPalError as exc:
            registro_contratacion.warning("pedido_paypal_no_consulta pedido=%s motivo=%s", d.id, type(exc.causa or exc).__name__)
            raise self._paypal_no_disponible() from exc

        if orden.estado not in (paypal.ESTADO_APROBADA, paypal.ESTADO_COMPLETADA):
            if d.expira_en is not None and d.expira_en < ahora_utc_naive():
                self._pedidos.actualizar(db, d.id, estado="vencido")
                politicas.registrar_bitacora_de(db, contexto, ENTIDAD_PEDIDO_CONTRATACION, d.id, ACCION_VENCER, {})
                db.commit()
                raise self._error_de_estado("vencido")
            raise self._pago_no_aprobado()

        if orden.estado == paypal.ESTADO_APROBADA:
            if not self._coincide(orden, d):
                self._rechazar_por_monto(db, d, orden, contexto, cobrado=False)
            try:
                orden = paypal.capturar_orden(d.paypal_order_id, request_id=self._request_id_de(token))
            except paypal.PayPalError as exc:
                registro_contratacion.warning("pedido_paypal_no_captura pedido=%s motivo=%s", d.id, type(exc.causa or exc).__name__)
                raise self._paypal_no_disponible() from exc

        # Orden ya completada (la captura de recién, o un cobro anterior cuya confirmación no se guardó).
        if orden.estado != paypal.ESTADO_COMPLETADA or orden.estado_captura != paypal.ESTADO_COMPLETADA:
            raise self._pago_no_aprobado("PayPal todavía no confirmó el cobro. Inténtalo de nuevo en unos minutos")
        if not self._coincide(orden, d):
            self._rechazar_por_monto(db, d, orden, contexto, cobrado=True)

    @staticmethod
    def _coincide(orden: paypal.EstadoOrden, d: _DatosPedido) -> bool:
        return orden.moneda == "USD" and orden.monto is not None and orden.monto == d.monto_usd

    def _rechazar_por_monto(
        self, db: Session, d: _DatosPedido, orden: paypal.EstadoOrden, contexto: ContextoAuditoria | None, *, cobrado: bool
    ) -> None:
        """La moneda o el monto de PayPal no son los del pedido: `fallido` (confirmado) y 409 `pago_no_coincide`."""
        self._pedidos.actualizar(db, d.id, estado="fallido")
        politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_PEDIDO_CONTRATACION, d.id, ACCION_PAGO_NO_COINCIDE,
            {"moneda": orden.moneda, "monto": str(orden.monto), "esperado": str(d.monto_usd), "cobrado": cobrado},
        )  # fmt: skip
        db.commit()
        if cobrado:  # no debería ocurrir (la orden se creó con el monto exacto): exige revisión manual
            registro_contratacion.error("pedido_pago_no_coincide_cobrado pedido=%s: revisar el cobro en PayPal", d.id)
        raise ErrorFuncional(
            "pago_no_coincide", "El pago no coincide con lo esperado para este pedido. No se creó la empresa", 409
        )

    def _dejar_pagado_sin_empresa(
        self, db: Session, d: _DatosPedido, contexto: ContextoAuditoria | None, error: Exception
    ) -> None:
        """El dinero está cobrado pero la empresa no se pudo crear (el SAVEPOINT ya descartó lo a medias): el pedido
        queda `pagado_sin_empresa` y SE CONFIRMA, con lo que el cobro no se pierde. Siempre lanza 409. El motivo es un
        código estable: ni el texto de la excepción ni datos del comprador van al registro."""
        if isinstance(error, ErrorFuncional):
            motivo = error.codigo
        elif isinstance(error, (ConflictoError, IntegrityError)):
            motivo = "nombre_en_uso"
        else:
            motivo = "error_interno"
        if d.estado != "pagado_sin_empresa":
            self._pedidos.actualizar(db, d.id, estado="pagado_sin_empresa")
            politicas.registrar_bitacora_de(
                db, contexto, ENTIDAD_PEDIDO_CONTRATACION, d.id, ACCION_PAGADO_SIN_EMPRESA,
                {"motivo": motivo, "monto_usd": str(d.monto_usd), "paypal_order_id": d.paypal_order_id},
            )  # fmt: skip
        db.commit()
        registro_contratacion.error(
            "pedido_pagado_sin_empresa pedido=%s motivo=%s tipo_error=%s: reembolso manual en PayPal",
            d.id, motivo, type(error).__name__,
        )  # fmt: skip
        raise ErrorFuncional("pagado_sin_empresa", MENSAJE_PAGADO_SIN_EMPRESA, 409, estado="pagado_sin_empresa")

    def _respuesta_pagada(self, db: Session, d: _DatosPedido) -> PedidoPagadoRespuesta:
        """La empresa que creó un pedido ya `completado` (para repetir la captura sin hacer nada más)."""
        empresa = self._pedidos.obtener_empresa(db, d.empresa_creada_id) if d.empresa_creada_id else None
        if empresa is None:
            raise NoEncontradoError("Pedido no encontrado")
        plan = self._pedidos.obtener_plan(db, d.plan_id)
        ficha = self._suscripciones.vigentes_de(db, [empresa.id]).get(empresa.id)
        suscripcion = ficha[0] if ficha is not None else None
        return PedidoPagadoRespuesta(
            estado="completado",
            empresa_codigo=empresa.codigo,
            empresa_nombre=empresa.nombre,
            plan_codigo=plan.codigo,
            plan_nombre=plan.nombre,
            periodo=d.periodo,
            es_prueba=False,
            fecha_inicio=suscripcion.fecha_inicio if suscripcion is not None else None,
            fecha_vencimiento=suscripcion.fecha_vencimiento if suscripcion is not None else None,
            monto_bs=d.monto_bs,
            monto_usd=d.monto_usd,
        )


# ---- Planes -------------------------------------------------------------------------------


class GestionarPlanes:
    """Catálogo global de planes. Los límites y las funcionalidades viven en la
    tabla `plan`: editarlos cambia el comportamiento sin tocar el código."""

    def __init__(self) -> None:
        self._repo = PlanRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Plan]:
        return self._repo.listar_todos(db, paginacion)

    def listar_publicos(self, db: Session) -> list[Plan]:
        """Sin sesión: los planes activos para la portada pública (los lee de la
        tabla, así que un plan editado se refleja solo)."""
        return self._repo.listar_publicos(db)

    def obtener(self, db: Session, plan_id: int) -> Plan:
        plan = self._repo.buscar(db, plan_id)
        if plan is None:
            raise NoEncontradoError("Plan no encontrado")
        return plan

    # El plan es global (sin empresa): sus filas de bitácora quedan sin empresa y
    # solo las ve el superadministrador.

    def crear(self, db: Session, datos: PlanCrear, contexto: ContextoAuditoria | None = None) -> Plan:
        if self._repo.obtener_por_codigo(db, datos.codigo) is not None:
            raise ConflictoError("Ya existe un plan con ese código")
        plan = self._repo.crear(db, datos, commit=False)
        politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_PLAN, plan.id, ACCION_CREAR,
            {"codigo": plan.codigo, "max_sucursales": plan.max_sucursales},
        )  # fmt: skip
        db.commit()
        db.refresh(plan)
        return plan

    def actualizar(
        self, db: Session, plan_id: int, datos: PlanActualizar, contexto: ContextoAuditoria | None = None
    ) -> Plan:
        """Límites y funcionalidades. Bajar `max_sucursales` por debajo del uso de
        una empresa NO desactiva nada: solo impide crear o reactivar sucursales
        hasta quedar dentro del límite."""
        actual = self.obtener(db, plan_id)
        cambios = _sin_nulos(datos, anulables=("precio_mensual_bs",))
        if cambios.activo is False:
            self._exigir_sin_uso(db, plan_id)
        campos = diff_campos(actual, cambios.model_dump(exclude_unset=True), ("activo", "precio_mensual_bs"))
        plan = self._repo.actualizar(db, plan_id, cambios, commit=False)
        politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_PLAN, plan.id, ACCION_ACTUALIZAR,
            {"codigo": plan.codigo, **campos, "max_sucursales": plan.max_sucursales},
        )  # fmt: skip
        db.commit()
        db.refresh(plan)
        return plan

    def desactivar(self, db: Session, plan_id: int, contexto: ContextoAuditoria | None = None) -> Plan:
        self._exigir_sin_uso(db, plan_id)
        plan = self._repo.desactivar(db, plan_id, commit=False)
        politicas.registrar_bitacora_de(db, contexto, ENTIDAD_PLAN, plan.id, ACCION_DESACTIVAR, {"codigo": plan.codigo})
        db.commit()
        db.refresh(plan)
        return plan

    def _exigir_sin_uso(self, db: Session, plan_id: int) -> None:
        if self._repo.en_uso(db, plan_id):
            raise ConflictoError("El plan está en uso por una suscripción vigente")


# ---- Suscripciones ---------------------------------------------------------------------------


class GestionarSuscripciones:
    """Una empresa tiene a lo sumo una suscripción vigente (no cancelada). Cambiar
    de plan cierra la vigente y crea otra: queda el historial."""

    def __init__(self) -> None:
        self._repo = SuscripcionRepository()
        self._empresas = EmpresaRepository()
        self._planes = PlanRepository()

    # -- Consulta ----------------------------------------------------------------

    def listar(
        self,
        db: Session,
        paginacion: ParametrosPaginacion,
        empresa_id: int | None = None,
        estado: str | None = None,
    ) -> list[SuscripcionRespuesta]:
        """`estado` es el efectivo (una activa con la fecha pasada cuenta como vencida)."""
        suscripciones = self._repo.listar_filtrado(db, paginacion, empresa_id, estado)
        planes = self._planes.por_ids(db, [s.plan_id for s in suscripciones])
        return [_respuesta_suscripcion(s, planes[s.plan_id]) for s in suscripciones]

    def obtener(self, db: Session, suscripcion_id: int) -> SuscripcionRespuesta:
        suscripcion = self._repo.buscar(db, suscripcion_id)
        if suscripcion is None:
            raise NoEncontradoError("Suscripción no encontrada")
        return _respuesta_suscripcion(suscripcion, self._planes.buscar(db, suscripcion.plan_id))

    # -- Asignar o cambiar de plan ------------------------------------------------------

    def asignar_o_cambiar_plan(
        self, db: Session, datos: SuscripcionAsignar, contexto: ContextoAuditoria | None = None
    ) -> SuscripcionRespuesta:
        """Asigna un plan a una empresa sin suscripción o LO CAMBIA: la vigente
        pasa a `cancelada` (con su vencimiento recortado a hoy) y se crea otra
        activa (nunca de prueba). Mismo plan: 409, SALVO que la vigente sea una
        prueba gratuita: ahí "cambiar" al mismo plan es pasar de prueba a pago.
        Un plan cuyo límite de sucursales es menor que el
        uso actual se rechaza (409 `limite_plan_excedido`); subir de plan siempre
        se puede."""
        if self._empresas.buscar(db, datos.empresa_id) is None:
            raise NoEncontradoError("Empresa no encontrada")
        plan = _plan_asignable(self._planes, db, datos.plan_codigo)
        hoy = hoy_utc()
        inicio = datos.fecha_inicio or hoy
        vencimiento = datos.fecha_vencimiento or inicio + dt.timedelta(days=get_settings().suscripcion_dias_por_defecto)
        _fecha_vencimiento_valida(inicio, vencimiento, hoy)

        with _transaccion(db, "La empresa ya tiene una suscripción vigente: reintente"):
            with en_empresa(db, datos.empresa_id):
                vigente = politicas.obtener_suscripcion_vigente(db, bloquear=True)
                era_prueba = vigente is not None and vigente.es_prueba
                if vigente is not None and vigente.plan_id == plan.id and not era_prueba:
                    raise ConflictoError("La empresa ya tiene ese plan: para extender la vigencia use renovar")
                actual = politicas.contar_sucursales_activas(db)
                if actual > plan.max_sucursales:
                    raise politicas.error_limite_sucursales(plan, actual)
                plan_antes = None
                if vigente is not None:
                    plan_antes = self._planes.buscar(db, vigente.plan_id).codigo
                    politicas.cerrar_suscripcion(vigente, hoy)
                    db.flush()  # libera el índice de la vigente antes de insertar la nueva
                nueva = self._repo.insertar(db, datos.empresa_id, plan.id, inicio, vencimiento)
                db.refresh(nueva)
                respuesta = _respuesta_suscripcion(nueva, plan)
                # Actor: el superadministrador. La empresa afectada va explícita
                # (dentro de `en_empresa` coincide con la de la sesión).
                if vigente is None:
                    politicas.registrar_bitacora_de(
                        db, contexto, ENTIDAD_SUSCRIPCION, nueva.id, ACCION_ASIGNAR_PLAN,
                        {"plan_despues": plan.codigo, "suscripcion_nueva_id": nueva.id},
                        empresa_id=datos.empresa_id,
                    )  # fmt: skip
                else:
                    detalle = {"plan_antes": plan_antes, "plan_despues": plan.codigo, "suscripcion_nueva_id": nueva.id}
                    if era_prueba:
                        detalle["era_prueba"] = True
                    politicas.registrar_bitacora_de(
                        db, contexto, ENTIDAD_SUSCRIPCION, nueva.id, ACCION_CAMBIAR_PLAN, detalle,
                        empresa_id=datos.empresa_id,
                    )  # fmt: skip
        return respuesta

    # -- Renovar ------------------------------------------------------------------------------

    def renovar(
        self, db: Session, suscripcion_id: int, datos: SuscripcionRenovar, contexto: ContextoAuditoria | None = None
    ) -> SuscripcionRespuesta:
        """Fija un nuevo vencimiento (futuro). Si la suscripción estaba vencida
        vuelve a `activa`; si estaba suspendida solo cambia la fecha; una
        cancelada no se renueva. Renovar una PRUEBA gratuita la convierte en una
        suscripción normal (`es_prueba` pasa a falso)."""
        hoy = hoy_utc()
        if datos.fecha_vencimiento <= hoy:
            raise DomainError("La nueva fecha de vencimiento debe ser posterior a hoy", 422)
        empresa_id = self._repo.empresa_de_suscripcion(db, suscripcion_id)
        with _transaccion(db):
            with en_empresa(db, empresa_id):
                suscripcion = politicas.obtener_suscripcion_de_la_empresa(db, suscripcion_id, bloquear=True)
                if suscripcion.estado == "cancelada":
                    raise ConflictoError("Una suscripción cancelada no se puede renovar")
                if datos.fecha_vencimiento < suscripcion.fecha_inicio:
                    raise DomainError("La fecha de vencimiento no puede ser anterior a la de inicio", 422)
                if politicas.estado_efectivo(suscripcion, hoy) == "vencida":
                    politicas.validar_transicion("vencida", "activa")
                    suscripcion.estado = "activa"
                vencimiento_antes = suscripcion.fecha_vencimiento
                suscripcion.fecha_vencimiento = datos.fecha_vencimiento
                detalle = {"vencimiento_antes": vencimiento_antes, "vencimiento_despues": datos.fecha_vencimiento}
                if suscripcion.es_prueba:
                    suscripcion.es_prueba = False
                    detalle["era_prueba"] = True
                db.flush()
                respuesta = _respuesta_suscripcion(suscripcion, self._planes.buscar(db, suscripcion.plan_id))
                politicas.registrar_bitacora_de(
                    db, contexto, ENTIDAD_SUSCRIPCION, suscripcion_id, ACCION_RENOVAR, detalle,
                    empresa_id=empresa_id,
                )  # fmt: skip
        return respuesta

    # -- Suspender, reactivar, cancelar --------------------------------------------------------

    def cambiar_estado(
        self,
        db: Session,
        suscripcion_id: int,
        datos: SuscripcionEstadoActualizar,
        contexto: ContextoAuditoria | None = None,
    ) -> SuscripcionRespuesta:
        """Suspender, reactivar o cancelar. La transición se valida contra el
        estado EFECTIVO. Reactivar solo vale si la fecha de vencimiento no pasó
        (si pasó, primero se renueva); `vencida` solo se sale renovando."""
        hoy = hoy_utc()
        empresa_id = self._repo.empresa_de_suscripcion(db, suscripcion_id)
        with _transaccion(db):
            with en_empresa(db, empresa_id):
                suscripcion = politicas.obtener_suscripcion_de_la_empresa(db, suscripcion_id, bloquear=True)
                origen = politicas.estado_efectivo(suscripcion, hoy)
                politicas.validar_transicion(origen, datos.estado)
                if datos.estado == "activa" and (origen == "vencida" or suscripcion.fecha_vencimiento < hoy):
                    raise ConflictoError("La suscripción está vencida: renuévela primero")
                suscripcion.estado = datos.estado
                db.flush()
                respuesta = _respuesta_suscripcion(suscripcion, self._planes.buscar(db, suscripcion.plan_id))
                politicas.registrar_bitacora_de(
                    db, contexto, ENTIDAD_SUSCRIPCION, suscripcion_id, ACCION_CAMBIAR_ESTADO,
                    {"estado_antes": origen, "estado_despues": datos.estado},
                    empresa_id=empresa_id,
                )  # fmt: skip
        return respuesta

    # -- Tarea periódica --------------------------------------------------------------------------

    def vencer_pendientes(self, db: Session) -> int:
        """Persiste `vencida` en las suscripciones activas con la fecha pasada, de
        todas las empresas. Idempotente. Devuelve cuántas cambió."""
        return politicas.vencer_suscripciones(db)


# ---- Mi empresa ---------------------------------------------------------------------------------


class ConsultarMiEmpresa:
    """La empresa de quien administra (la del token, con los filtros normales).
    Sus rutas están exentas de la suscripción: funcionan con ella vencida o
    suspendida, para poder ver el estado y pedir la renovación."""

    def __init__(self) -> None:
        self._repo = EmpresaRepository()

    def _empresa(self, db: Session) -> Empresa:
        empresa = self._repo.buscar(db, exigir_empresa(db))
        if empresa is None:
            raise NoEncontradoError("Empresa no encontrada")
        return empresa

    @staticmethod
    def _respuesta(db: Session, empresa: Empresa) -> MiEmpresaRespuesta:
        return MiEmpresaRespuesta(
            id=empresa.id,
            codigo=empresa.codigo,
            nombre=empresa.nombre,
            logo_url=empresa.logo_url,
            color_acento=empresa.color_acento,
            activo=empresa.activo,
            plazo_cambio_horas=empresa.plazo_cambio_horas,
            plazo_cambio_horas_efectivo=politicas.obtener_plazo_cambio_horas(db),
        )

    def obtener(self, db: Session) -> MiEmpresaRespuesta:
        return self._respuesta(db, self._empresa(db))

    def actualizar(
        self, db: Session, datos: MiEmpresaActualizar, contexto: ContextoAuditoria | None = None
    ) -> MiEmpresaRespuesta:
        """Nombre comercial, logo, color de acento y plazo de cambio de prendas
        (`null` = el del plan). Plan, estado y código no se tocan desde aquí."""
        empresa = self._empresa(db)
        empresa_id = empresa.id
        plazo_enviado = "plazo_cambio_horas" in datos.model_fields_set
        plazo_antes = empresa.plazo_cambio_horas
        cambios = _sin_nulos(datos, EmpresaActualizar, CAMPOS_ANULABLES_EMPRESA)
        detalle = diff_campos(empresa, cambios.model_dump(exclude_unset=True), ("activo",))
        actualizada = self._repo.actualizar(db, empresa_id, cambios, commit=False)
        # La empresa es la de la sesión (el administrador que la edita). Si solo se
        # tocó el plazo, el único evento es el del plazo.
        if detalle["campos"] or not plazo_enviado:
            politicas.registrar_bitacora_de(db, contexto, ENTIDAD_EMPRESA, empresa_id, ACCION_ACTUALIZAR, detalle)
        if plazo_enviado and datos.plazo_cambio_horas != plazo_antes:
            actualizada.plazo_cambio_horas = datos.plazo_cambio_horas
            politicas.registrar_bitacora_de(
                db,
                contexto,
                ENTIDAD_EMPRESA,
                empresa_id,
                ACCION_CAMBIAR_PLAZO_CAMBIO,
                {"antes": plazo_antes, "despues": datos.plazo_cambio_horas},
            )
        db.commit()
        db.refresh(actualizada)
        return self._respuesta(db, actualizada)

    def obtener_suscripcion(self, db: Session) -> MiSuscripcionRespuesta:
        """Plan, estado efectivo, fechas, límite y uso de sucursales, y las
        funcionalidades que incluye el plan."""
        situacion = politicas.situacion_de_la_empresa(db)
        suscripcion, plan = situacion.suscripcion, situacion.plan
        return MiSuscripcionRespuesta(
            plan_codigo=plan.codigo if plan is not None else None,
            plan_nombre=plan.nombre if plan is not None else None,
            estado=situacion.estado,
            fecha_inicio=suscripcion.fecha_inicio if suscripcion is not None else None,
            fecha_vencimiento=suscripcion.fecha_vencimiento if suscripcion is not None else None,
            es_prueba=suscripcion.es_prueba if suscripcion is not None else False,
            max_sucursales=plan.max_sucursales if plan is not None else None,
            sucursales_activas=politicas.contar_sucursales_activas(db),
            funcionalidades=politicas.funcionalidades_habilitadas(db),
        )


# ---- Copias de seguridad (E22) ---------------------------------------------------------------------

logger = logging.getLogger("app.copias")

# Una copia `en_proceso` más vieja que esto (veces el tiempo máximo) es de un proceso que murió.
FACTOR_ABANDONO = 2
# Mínimo de copias que se conservan en el historial aunque el plan declare 0.
HISTORIAL_MINIMO = 1


@dataclass(frozen=True)
class CopiaGenerada:
    """Lo que `crear` entrega al router: el ZIP en memoria, el nombre sugerido y los metadatos que quedaron en el historial."""

    contenido: bytes
    nombre_archivo: str
    copia: CopiaRespuesta


@contextmanager
def _conexion_de_lectura(db: Session) -> Iterator[Connection]:
    """Una conexión de solo lectura coherente. En PostgreSQL, una conexión DEDICADA con aislamiento REPEATABLE READ:
    todas las tablas reflejan el mismo instante (una venta que entra durante la copia no deja venta sin detalle). En
    SQLite (las pruebas) se usa la conexión de la sesión."""
    bind = db.get_bind()
    if isinstance(bind, Engine) and bind.dialect.name == "postgresql":
        with bind.connect().execution_options(isolation_level="REPEATABLE READ") as conexion:
            yield conexion
    else:
        yield db.connection()


class GestionarCopiasSeguridad:
    """Copias de seguridad de la empresa de la sesión. Solo el administrador (`copias.gestionar`), con un plan que
    incluya `copias_seguridad` y suscripción activa. La empresa sale SIEMPRE del token. El ZIP no se guarda en el
    servidor (el disco de Railway es efímero): se entrega una vez, en la misma respuesta que lo crea; el historial
    guarda solo los metadatos y el checksum para auditar y comprobar un archivo ya descargado."""

    def __init__(self) -> None:
        self._repo = CopiaSeguridadRepository()
        self._empresas = EmpresaRepository()

    # -- crear -------------------------------------------------------------------------------------

    def crear(self, db: Session, usuario_id: int, contexto: ContextoAuditoria | None = None) -> CopiaGenerada:
        empresa_id = exigir_empresa(db)  # sin empresa (o en modo plataforma) no hay copia
        verificar_suscripcion_activa(db)
        verificar_funcionalidad(db, FUNC_COPIAS_SEGURIDAD)
        ajustes = get_settings()
        plan = politicas.situacion_de_la_empresa(db).plan
        empresa = self._empresas.buscar(db, empresa_id)
        if empresa is None:
            raise NoEncontradoError("Empresa no encontrada")
        datos_empresa = {"codigo": empresa.codigo, "nombre": empresa.nombre}
        plan_codigo, historial_maximo = plan.codigo, plan.max_copias_historial

        # El candado: una sola copia en proceso por empresa. Primero se libera la de un proceso que murió.
        abandono = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(
            seconds=FACTOR_ABANDONO * ajustes.copias_max_segundos
        )
        if self._repo.marcar_abandonadas(db, abandono):
            db.commit()
        try:
            copia_id = self._repo.crear_en_proceso(db, usuario_id).id
            db.commit()
        except IntegrityError:
            db.rollback()
            raise ErrorFuncional(
                "copia_en_curso",
                "Ya hay una copia en curso para tu empresa. Espera a que termine.",
                409,
            ) from None

        inicio = time.monotonic()
        try:
            with copias.plaza_de_copia(ajustes.copias_max_simultaneas):
                with _conexion_de_lectura(db) as conexion:
                    resultado = copias.generar_copia(
                        conexion,
                        empresa_id,
                        empresa=datos_empresa,
                        plan_codigo=plan_codigo,
                        version_esquema=copias.leer_version_esquema(conexion),
                        max_bytes=ajustes.copias_max_bytes,
                        max_segundos=ajustes.copias_max_segundos,
                    )
        except copias.CopiaError as error:
            self._registrar_fallo(db, copia_id, error.codigo, contexto, inicio, empresa_id)
            raise self._error_funcional(error, ajustes.copias_max_bytes) from None
        except Exception:
            # Nunca la excepción cruda al cliente. Solo ids en el log: la copia no lleva datos de la empresa.
            logger.exception("copia_error empresa=%s copia=%s", empresa_id, copia_id)
            self._registrar_fallo(db, copia_id, "error_interno", contexto, inicio, empresa_id)
            raise ErrorFuncional(
                "copia_fallida", "No se pudo crear la copia de seguridad. Inténtalo de nuevo.", 500
            ) from None

        duracion_ms = int((time.monotonic() - inicio) * 1000)
        copia = self._repo.cargar(db, copia_id)
        self._repo.completar(
            db,
            copia,
            tamano_bytes=len(resultado.contenido),
            tablas=resultado.tablas,
            version_esquema=resultado.manifiesto["version_esquema"],
            checksum=resultado.checksum,
        )
        total_filas = sum(resultado.tablas.values())
        politicas.registrar_bitacora_de(
            db,
            contexto,
            ENTIDAD_COPIA_SEGURIDAD,
            copia_id,
            ACCION_DESCARGAR,
            {"filas": total_filas, "bytes": len(resultado.contenido), "tablas": len(resultado.tablas), "duracion_ms": duracion_ms},
        )
        salieron = self._repo.purgar_antiguas(db, max(historial_maximo, HISTORIAL_MINIMO))
        if salieron:
            politicas.registrar_bitacora_de(
                db,
                contexto,
                ENTIDAD_COPIA_SEGURIDAD,
                None,
                ACCION_ELIMINAR,
                {"copias": salieron, "motivo": "limite_historial", "limite": max(historial_maximo, HISTORIAL_MINIMO)},
            )
        db.commit()
        logger.info(
            "copia_fin empresa=%s copia=%s estado=completada filas=%s bytes=%s ms=%s",
            empresa_id, copia_id, total_filas, len(resultado.contenido), duracion_ms,
        )  # fmt: skip

        copia = self._repo.cargar(db, copia_id)
        nombre = f"fashionstore-{datos_empresa['codigo']}-{ahora_bolivia().strftime('%Y%m%d-%H%M')}.zip"
        return CopiaGenerada(contenido=resultado.contenido, nombre_archivo=nombre, copia=self._respuesta(db, copia))

    def _registrar_fallo(
        self, db: Session, copia_id: int, motivo: str, contexto: ContextoAuditoria | None, inicio: float, empresa_id: int
    ) -> None:
        """Marca la copia como fallida y deja la bitácora, en una transacción propia. Si esto también falla se
        registra en el log y el candado lo libera `marcar_abandonadas` más adelante."""
        try:
            db.rollback()
            copia = self._repo.cargar(db, copia_id)
            if copia is not None and copia.estado == "en_proceso":
                self._repo.fallar(db, copia, motivo)
            politicas.registrar_bitacora_de(
                db,
                contexto,
                ENTIDAD_COPIA_SEGURIDAD,
                copia_id,
                ACCION_FALLAR,
                {"motivo": motivo, "duracion_ms": int((time.monotonic() - inicio) * 1000)},
            )
            db.commit()
            logger.warning("copia_fin empresa=%s copia=%s estado=fallida motivo=%s", empresa_id, copia_id, motivo)
        except Exception:
            db.rollback()
            logger.exception("copia_fallo_sin_registrar empresa=%s copia=%s", empresa_id, copia_id)

    @staticmethod
    def _error_funcional(error: copias.CopiaError, max_bytes: int) -> ErrorFuncional:
        if isinstance(error, copias.CopiaDemasiadoGrandeError):
            return ErrorFuncional(
                error.codigo,
                f"La copia supera el tamaño máximo permitido ({max_bytes // (1024 * 1024)} MB).",
                413,
                limite_bytes=max_bytes,
            )
        if isinstance(error, copias.CopiaTiempoAgotadoError):
            return ErrorFuncional(error.codigo, "La copia tardó más de lo permitido. Inténtalo más tarde.", 504)
        if isinstance(error, copias.ServidorOcupadoError):
            return ErrorFuncional(
                error.codigo, "El servidor está ocupado con otras copias. Inténtalo en unos minutos.", 503
            )
        return ErrorFuncional("copia_fallida", "No se pudo crear la copia de seguridad. Inténtalo de nuevo.", 500)

    # -- consultar ---------------------------------------------------------------------------------

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> CopiaPagina:
        self._exigir_acceso(db)
        copias_, total = self._repo.listar(db, paginacion)
        nombres = self._repo.nombres_de_usuarios(db, [c.usuario_id for c in copias_])
        return CopiaPagina(
            total=total,
            pagina=paginacion.pagina,
            tamanio=paginacion.tamanio,
            items=[self._respuesta(db, c, nombres) for c in copias_],
        )

    def obtener(self, db: Session, copia_id: int) -> CopiaRespuesta:
        self._exigir_acceso(db)
        copia = self._repo.obtener(db, copia_id)
        if copia is None:
            raise NoEncontradoError("Copia no encontrada")
        return self._respuesta(db, copia)

    def tablas(self, db: Session) -> CopiaTablasRespuesta:
        """Qué incluye y qué no la copia: lista fija del sistema, igual para todas las empresas."""
        self._exigir_acceso(db)
        return CopiaTablasRespuesta(**copias.descripcion_de_tablas())

    @staticmethod
    def _exigir_acceso(db: Session) -> None:
        exigir_empresa(db)
        verificar_suscripcion_activa(db)
        verificar_funcionalidad(db, FUNC_COPIAS_SEGURIDAD)

    def _respuesta(self, db: Session, copia: CopiaSeguridad, nombres: dict[int, str] | None = None) -> CopiaRespuesta:
        if nombres is None:
            nombres = self._repo.nombres_de_usuarios(db, [copia.usuario_id])
        tablas = copia.tablas_incluidas
        return CopiaRespuesta(
            id=copia.id,
            estado=copia.estado,
            usuario_id=copia.usuario_id,
            usuario_nombre=nombres.get(copia.usuario_id),
            tamano_bytes=copia.tamano_bytes,
            total_filas=sum(tablas.values()) if tablas else None,
            tablas_incluidas=tablas,
            version_esquema=copia.version_esquema,
            checksum=copia.checksum,
            motivo_fallo=copia.motivo_fallo,
            creado_en=copia.creado_en,
            terminado_en=copia.terminado_en,
        )
