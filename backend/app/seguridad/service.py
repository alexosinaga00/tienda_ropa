import datetime as dt
import logging

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import ParametrosPaginacion
from app.core.exceptions import DomainError
from app.core.security import (
    crear_access_token,
    crear_refresh_token,
    crear_reset_token,
    decodificar_token,
    verificar_password,
)
from app.seguridad.models import Cliente, Permiso, Rol, Usuario, rol_permiso, usuario_rol
from app.seguridad.repository import ClienteRepository, RolRepository, UsuarioRepository
from app.seguridad.schemas import (
    ClientePerfilActualizar,
    LoginRequest,
    RegistroRequest,
    RolActualizar,
    RolCrear,
    TokenRespuesta,
    UsuarioActualizar,
    UsuarioCrear,
)

logger = logging.getLogger(__name__)

rol_repo = RolRepository()
usuario_repo = UsuarioRepository()
cliente_repo = ClienteRepository()

ROL_CLIENTE = "cliente"

# Hash bcrypt fijo (de un password que no le pertenece a nadie) para que
# login() siempre corra verificar_password() con costo real, exista o no el
# email: sin esto, el cortocircuito de `or` se salta bcrypt.checkpw() cuando
# el usuario no existe, y ese ida-y-vuelta más rápido deja adivinar por
# tiempo de respuesta qué emails están registrados.
_HASH_DUMMY = "$2b$12$d1ru1mgPSWsBsc/AHIyMHeWrDeAVeESRlnXjY52JXjnR/XOLoWB22"


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


def registrar_cliente(db: Session, datos: RegistroRequest) -> Usuario:
    usuario = usuario_repo.crear(
        db,
        UsuarioCrear(
            nombre=datos.nombre,
            apellido=datos.apellido,
            email=datos.email,
            telefono=datos.telefono,
            password=datos.password,
        ),
    )
    usuario_repo.asignar_roles(db, usuario, [ROL_CLIENTE])

    # Si el usuario venía reactivado (estaba dado de baja con este mismo
    # email), puede ya tener un perfil de Cliente de antes -- cliente.usuario_id
    # es único, así que insertar uno nuevo rompería con IntegrityError.
    cliente = cliente_repo.buscar_por_usuario(db, usuario.id)
    if cliente is not None:
        cliente.ci_nit = datos.ci_nit
    else:
        cliente = Cliente(usuario_id=usuario.id, ci_nit=datos.ci_nit)
        db.add(cliente)
    db.commit()
    db.refresh(usuario)
    return usuario


def _generar_tokens(usuario_id: int, roles: list[str], permisos: list[str]) -> TokenRespuesta:
    return TokenRespuesta(
        access_token=crear_access_token(usuario_id, roles, permisos),
        refresh_token=crear_refresh_token(usuario_id),
    )


def login(db: Session, datos: LoginRequest) -> TokenRespuesta:
    usuario = usuario_repo.obtener_por_email(db, datos.email)
    # Siempre corre bcrypt (contra el hash real o, si no existe el email,
    # contra uno dummy) para que credenciales inválidas por email
    # inexistente y por password incorrecta tarden lo mismo.
    hash_a_verificar = usuario.password_hash if usuario is not None else _HASH_DUMMY
    password_valida = verificar_password(datos.password, hash_a_verificar)
    credenciales_invalidas = usuario is None or not usuario.activo or not password_valida
    if credenciales_invalidas:
        raise DomainError("Credenciales inválidas", status_code=status.HTTP_401_UNAUTHORIZED)

    usuario.ultimo_acceso = dt.datetime.now(dt.timezone.utc)
    db.commit()

    roles = [r.nombre for r in usuario.roles]
    permisos = permisos_de_usuario(db, usuario.id)
    return _generar_tokens(usuario.id, roles, permisos)


def refrescar_token(db: Session, refresh_token: str) -> TokenRespuesta:
    payload = decodificar_token(refresh_token)
    if payload.get("tipo") != "refresh":
        raise DomainError("Token inválido", status_code=status.HTTP_401_UNAUTHORIZED)

    usuario = obtener_usuario_para_auth(db, int(payload["sub"]))
    if usuario is None:
        raise DomainError("Usuario inválido", status_code=status.HTTP_401_UNAUTHORIZED)

    roles = [r.nombre for r in usuario.roles]
    permisos = permisos_de_usuario(db, usuario.id)
    return _generar_tokens(usuario.id, roles, permisos)


def solicitar_recuperacion(db: Session, email: str) -> str | None:
    """Genera un token de recuperación si el email existe.

    Todavía no hay un servicio de correo en el proyecto, así que el token se
    deja en el log para pruebas manuales, y se devuelve acá para que el
    router lo incluya en la respuesta solo en entorno local (ver
    `RecuperarRespuesta.token_dev`). La respuesta al cliente es siempre
    genérica en cuanto al mensaje (ver router) para no revelar si el email
    está registrado.
    """
    usuario = usuario_repo.obtener_por_email(db, email)
    if usuario is None or not usuario.activo:
        return None

    token = crear_reset_token(usuario.id)
    logger.info("Token de recuperación para %s: %s", email, token)
    return token


def confirmar_recuperacion(db: Session, token: str, password: str) -> None:
    payload = decodificar_token(token)
    if payload.get("tipo") != "reset":
        raise DomainError("Token inválido", status_code=status.HTTP_401_UNAUTHORIZED)

    usuario = obtener_usuario_para_auth(db, int(payload["sub"]))
    if usuario is None:
        raise DomainError("Token inválido", status_code=status.HTTP_401_UNAUTHORIZED)

    usuario_repo.actualizar_password(db, usuario, password)


def obtener_usuario(db: Session, usuario_id: int) -> Usuario:
    """Punto de entrada para que otros paquetes (p. ej. organizacion, al crear
    un empleado) validen un usuario sin consultar la tabla directamente."""
    return usuario_repo.obtener(db, usuario_id)


# ---- Roles ------------------------------------------------------------------


def listar_roles(db: Session, paginacion: ParametrosPaginacion) -> list[Rol]:
    return list(rol_repo.listar(db, paginacion))


def obtener_rol(db: Session, rol_id: int) -> Rol:
    return rol_repo.obtener(db, rol_id)


def crear_rol(db: Session, datos: RolCrear) -> Rol:
    return rol_repo.crear(db, datos)


def actualizar_rol(db: Session, rol_id: int, datos: RolActualizar) -> Rol:
    return rol_repo.actualizar(db, rol_id, datos)


def desactivar_rol(db: Session, rol_id: int) -> Rol:
    return rol_repo.desactivar(db, rol_id)


def asignar_permisos_rol(db: Session, rol_id: int, codigos_permiso: list[str]) -> Rol:
    rol = rol_repo.obtener(db, rol_id)
    return rol_repo.asignar_permisos(db, rol, codigos_permiso)


# ---- Usuarios -----------------------------------------------------------------


def listar_usuarios(db: Session, paginacion: ParametrosPaginacion) -> list[Usuario]:
    return list(usuario_repo.listar(db, paginacion))


def crear_usuario(db: Session, datos: UsuarioCrear) -> Usuario:
    return usuario_repo.crear(db, datos)


def actualizar_usuario(db: Session, usuario_id: int, datos: UsuarioActualizar) -> Usuario:
    return usuario_repo.actualizar(db, usuario_id, datos)


def desactivar_usuario(db: Session, usuario_id: int) -> Usuario:
    return usuario_repo.desactivar(db, usuario_id)


def asignar_roles_usuario(db: Session, usuario_id: int, nombres_rol: list[str]) -> Usuario:
    usuario = usuario_repo.obtener(db, usuario_id)
    return usuario_repo.asignar_roles(db, usuario, nombres_rol)


def obtener_perfil_cliente(db: Session, usuario_id: int) -> Cliente:
    return cliente_repo.obtener_por_usuario(db, usuario_id)


def obtener_cliente(db: Session, cliente_id: int) -> Cliente:
    """Para que otros paquetes (p. ej. `reservas`, para notificar al dueño
    de una reserva) resuelvan el usuario_id de un cliente sin consultar
    la tabla `cliente` directamente."""
    return cliente_repo.obtener(db, cliente_id)


def actualizar_perfil_cliente(
    db: Session, usuario_id: int, datos: ClientePerfilActualizar
) -> Cliente:
    return cliente_repo.actualizar_perfil(db, usuario_id, datos)
