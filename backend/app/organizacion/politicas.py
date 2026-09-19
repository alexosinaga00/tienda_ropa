"""Funciones que organizacion expone para otros paquetes, sin ser casos de
uso del catálogo: son consultas y validaciones sobre las tablas de este
paquete (ciudad, sucursal, horario_sucursal, empleado), para que nadie más
tenga que tocarlas directamente."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import DomainError, PermisoDenegadoError
from app.core.security import permisos_de_usuario
from app.organizacion.models import Empleado, HorarioSucursal, Sucursal
from app.organizacion.repository import EmpleadoRepository, HorarioRepository, SucursalRepository

sucursal_repo = SucursalRepository()
horario_repo = HorarioRepository()
empleado_repo = EmpleadoRepository()

# Quien administra sucursales y empleados (hoy solo el administrador) opera
# y consulta todas las sucursales; el resto del personal (encargado, cajero)
# solo la de su ficha de empleado. Es el mismo permiso que ya tiene el
# administrador, así el alcance global no depende de volver a correr seeds.
PERMISO_ALCANCE_GLOBAL = "organizacion.gestionar"


def sucursal_asignada(db: Session, usuario_id: int) -> int | None:
    """Sucursal a la que está limitado el usuario, o None si tiene alcance
    global. Sin alcance global y sin ficha de empleado activa con sucursal,
    no puede operar ninguna (PermisoDenegadoError)."""
    if PERMISO_ALCANCE_GLOBAL in permisos_de_usuario(db, usuario_id):
        return None
    empleado = empleado_repo.obtener_por_usuario(db, usuario_id)
    if empleado is None or not empleado.activo or empleado.sucursal_id is None:
        raise PermisoDenegadoError("No tenés una sucursal asignada")
    return empleado.sucursal_id


def validar_acceso_sucursal(db: Session, usuario_id: int, sucursal_id: int) -> None:
    """Para las operaciones de personal sobre una sucursal concreta (vender,
    cobrar, devolver, atender reservas, mover inventario): lanza
    PermisoDenegadoError si el usuario está limitado a otra sucursal."""
    propia = sucursal_asignada(db, usuario_id)
    if propia is not None and propia != sucursal_id:
        raise PermisoDenegadoError("No tenés acceso a esa sucursal")


def acotar_sucursal(db: Session, usuario_id: int, sucursal_id: int | None) -> int | None:
    """Para consultas de personal con filtro de sucursal opcional
    (inventario, reportes): con alcance global devuelve el filtro pedido
    (None = todas); si no, siempre la sucursal propia (403 si pidió otra)."""
    propia = sucursal_asignada(db, usuario_id)
    if propia is None:
        return sucursal_id
    if sucursal_id is not None and sucursal_id != propia:
        raise PermisoDenegadoError("No tenés acceso a esa sucursal")
    return propia


def obtener_sucursal(db: Session, sucursal_id: int) -> Sucursal:
    """Para que otros paquetes (p. ej. `inventario`) validen una sucursal
    sin consultar la tabla `sucursal` directamente."""
    return sucursal_repo.obtener(db, sucursal_id)


def resolver_sucursal_por_nombre(db: Session, nombre: str | None) -> int | None:
    """Para `inteligencia` (búsqueda por voz): matchea el nombre de sucursal
    que devolvió Groq (case-insensitive, exacto) sin consultar `sucursal`
    directamente. Sin match, devuelve None -- no rompe la búsqueda."""
    if not nombre:
        return None
    return db.scalar(select(Sucursal.id).where(Sucursal.nombre.ilike(nombre), Sucursal.activo.is_(True)))


def atiende_al_publico(db: Session, sucursal_id: int) -> bool:
    """Un depósito (`es_deposito`) es solo almacén: puede despachar envíos
    pero no recibir clientes para retiro ni reservas."""
    return not sucursal_repo.obtener(db, sucursal_id).es_deposito


def obtener_horario_dia(db: Session, sucursal_id: int, dia_semana: int) -> HorarioSucursal | None:
    """Para que `reservas` valide que una franja horaria cae dentro del
    horario de atención de la sucursal, sin consultar horario_sucursal
    directamente."""
    return horario_repo.obtener_por_dia(db, sucursal_id, dia_semana)


def validar_horario_en_atencion(db: Session, sucursal_id: int, fecha, hora_desde, hora_hasta) -> None:
    """Valida que [hora_desde, hora_hasta) caiga dentro del horario de
    atención de la sucursal para el día de `fecha`. Lanza DomainError si la
    sucursal es un depósito, no atiende ese día, o la franja se sale del
    horario. La usan reservas (CU-16) y cualquier otro caso de uso que
    necesite la misma validación, para no duplicarla."""
    if not atiende_al_publico(db, sucursal_id):
        raise DomainError("Esa sucursal es un depósito y no recibe clientes: elegí otra para tu reserva")

    if hora_desde >= hora_hasta:
        raise DomainError("La hora de inicio debe ser anterior a la hora de fin")

    # dia_semana: 1=lunes ... 7=domingo (date.isoweekday()), igual que se
    # pide al crear un horario_sucursal.
    dia_semana = fecha.isoweekday()
    horario = obtener_horario_dia(db, sucursal_id, dia_semana)
    if horario is None:
        raise DomainError("La sucursal no atiende ese día")
    if hora_desde < horario.hora_apertura or hora_hasta > horario.hora_cierre:
        raise DomainError("La franja horaria elegida está fuera del horario de atención de la sucursal")


def listar_empleados_sucursal(db: Session, sucursal_id: int) -> list[Empleado]:
    """Para que `reservas` notifique a los empleados de una sucursal sin
    consultar la tabla `empleado` directamente."""
    return empleado_repo.listar_por_sucursal(db, sucursal_id)


def obtener_empleado_por_usuario(db: Session, usuario_id: int) -> Empleado | None:
    """Para que `ventas` y `pagos` resuelvan el cajero (empleado) a partir
    del usuario logueado, sin consultar `empleado` directamente."""
    return empleado_repo.obtener_por_usuario(db, usuario_id)
