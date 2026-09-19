"""Funciones que seguridad expone para otros paquetes (y para core.security),
sin ser casos de uso del catálogo: son consultas simples sobre las tablas de
este paquete, para que nadie más tenga que tocarlas directamente."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.seguridad.models import Cliente, Permiso, Rol, Usuario, rol_permiso, usuario_rol
from app.seguridad.repository import ClienteRepository, UsuarioRepository

usuario_repo = UsuarioRepository()
cliente_repo = ClienteRepository()


def permisos_de_usuario(db: Session, usuario_id: int) -> list[str]:
    """Códigos de permiso reales del usuario, vía sus roles activos. Vive
    acá (no en core.security) porque es una consulta de negocio sobre las
    tablas propias de este paquete; core.security la reexpone con el mismo
    nombre para el resto de los paquetes, que siguen sin tener que
    consultar rol_permiso/usuario_rol/permiso directamente."""
    filas = db.execute(
        select(Permiso.codigo)
        .join(rol_permiso, rol_permiso.c.permiso_id == Permiso.id)
        .join(Rol, Rol.id == rol_permiso.c.rol_id)
        .join(usuario_rol, usuario_rol.c.rol_id == Rol.id)
        .where(usuario_rol.c.usuario_id == usuario_id, Rol.activo.is_(True))
        .distinct()
    ).scalars()
    return list(filas)


def obtener_usuario_para_auth(db: Session, usuario_id: int) -> Usuario | None:
    """Para core.security (get_current_user/get_current_user_opcional):
    resuelve el usuario del JWT sin que core tenga que hacer `db.get(Usuario,
    ...)` directamente. Devuelve None (no una excepción) si no existe o está
    inactivo -- decidir si eso es un 401 le corresponde a quien llama."""
    usuario = db.get(Usuario, usuario_id)
    if usuario is None or not usuario.activo:
        return None
    return usuario


def obtener_usuario(db: Session, usuario_id: int) -> Usuario:
    """Punto de entrada para que otros paquetes (p. ej. organizacion, al crear
    un empleado) validen un usuario sin consultar la tabla directamente."""
    return usuario_repo.obtener(db, usuario_id)


def obtener_usuarios_por_ids(db: Session, ids: list[int]) -> dict[int, Usuario]:
    """Para que otros paquetes (p. ej. organizacion, al listar empleados)
    resuelvan nombres de usuario en lote sin consultar la tabla
    directamente."""
    return {u.id: u for u in usuario_repo.listar_por_ids(db, ids)}


def obtener_perfil_cliente(db: Session, usuario_id: int) -> Cliente:
    """Para que otros paquetes (catalogo, entregas, inteligencia, probador,
    reservas, ventas) resuelvan el Cliente de un usuario logueado sin
    consultar la tabla `cliente` directamente."""
    return cliente_repo.obtener_por_usuario(db, usuario_id)


def obtener_cliente(db: Session, cliente_id: int) -> Cliente:
    """Para que otros paquetes (p. ej. `reservas`, para notificar al dueño
    de una reserva) resuelvan el usuario_id de un cliente sin consultar
    la tabla `cliente` directamente."""
    return cliente_repo.obtener(db, cliente_id)
