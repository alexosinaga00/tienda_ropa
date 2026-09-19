from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import ParametrosPaginacion, parametros_paginacion
from app.core.rate_limit import limiter
from app.core.security import get_current_user, permisos_de_usuario, require_permission
from app.seguridad.casos_uso.cu01_registrar_cliente import RegistrarCliente
from app.seguridad.casos_uso.cu02_iniciar_sesion import IniciarSesion
from app.seguridad.casos_uso.cu03_gestionar_usuarios_roles_permisos import (
    GestionarRolesPermisos,
    GestionarUsuarios,
)
from app.seguridad.casos_uso.cu35_recuperar_contrasena import RecuperarContrasena
from app.seguridad.politicas import obtener_usuario
from app.seguridad.schemas import (
    AsignarPermisosRequest,
    AsignarRolesRequest,
    ClientePerfilActualizar,
    ClientePerfilRespuesta,
    LoginRequest,
    RecuperarConfirmarRequest,
    RecuperarRequest,
    RecuperarRespuesta,
    RefreshRequest,
    RegistroRequest,
    RolActualizar,
    RolCrear,
    RolRespuesta,
    TokenRespuesta,
    UsuarioActualizar,
    UsuarioCrear,
    UsuarioRespuesta,
    UsuarioYoRespuesta,
)

PERMISO_ROLES = "roles.gestionar"
PERMISO_USUARIOS = "usuarios.gestionar"

cu_registrar_cliente = RegistrarCliente()
cu_iniciar_sesion = IniciarSesion()
cu_gestionar_usuarios = GestionarUsuarios()
cu_gestionar_roles = GestionarRolesPermisos()
cu_recuperar_contrasena = RecuperarContrasena()

# ---- /api/v1/auth -----------------------------------------------------------

auth_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@auth_router.post("/registro", response_model=UsuarioRespuesta, status_code=status.HTTP_201_CREATED)
def registro(datos: RegistroRequest, db: Session = Depends(get_db)) -> UsuarioRespuesta:
    usuario = cu_registrar_cliente.registrar(db, datos)
    return UsuarioRespuesta.from_modelo(usuario)


@auth_router.post("/login", response_model=TokenRespuesta)
def login(datos: LoginRequest, db: Session = Depends(get_db)) -> TokenRespuesta:
    return cu_iniciar_sesion.ejecutar(db, datos)


@auth_router.post("/refresh", response_model=TokenRespuesta)
def refresh(datos: RefreshRequest, db: Session = Depends(get_db)) -> TokenRespuesta:
    return cu_iniciar_sesion.refrescar(db, datos.refresh_token)


@auth_router.get("/yo", response_model=UsuarioYoRespuesta)
def yo(usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> UsuarioYoRespuesta:
    base = UsuarioRespuesta.from_modelo(usuario)
    return UsuarioYoRespuesta(**base.model_dump(), permisos=permisos_de_usuario(db, usuario.id))


@auth_router.post("/recuperar", response_model=RecuperarRespuesta, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute")
def recuperar(request: Request, datos: RecuperarRequest, db: Session = Depends(get_db)) -> RecuperarRespuesta:
    token = cu_recuperar_contrasena.solicitar(db, datos.email)
    token_dev = token if get_settings().environment == "local" else None
    return RecuperarRespuesta(
        detail="Si el correo está registrado, se enviarán instrucciones de recuperación.",
        token_dev=token_dev,
    )


@auth_router.post("/recuperar/confirmar", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
def recuperar_confirmar(
    request: Request, datos: RecuperarConfirmarRequest, db: Session = Depends(get_db)
) -> dict[str, str]:
    cu_recuperar_contrasena.confirmar(db, datos.token, datos.password)
    return {"detail": "Contraseña actualizada."}


# ---- /api/v1/roles -----------------------------------------------------------

roles_router = APIRouter(prefix="/api/v1/roles", tags=["roles"])


@roles_router.get("", response_model=list[RolRespuesta], dependencies=[Depends(require_permission(PERMISO_ROLES))])
def listar_roles(
    db: Session = Depends(get_db),
    paginacion: ParametrosPaginacion = Depends(parametros_paginacion),
) -> list[RolRespuesta]:
    return cu_gestionar_roles.listar(db, paginacion)


@roles_router.get("/{rol_id}", response_model=RolRespuesta, dependencies=[Depends(require_permission(PERMISO_ROLES))])
def obtener_rol(rol_id: int, db: Session = Depends(get_db)) -> RolRespuesta:
    return cu_gestionar_roles.obtener(db, rol_id)


@roles_router.post(
    "", response_model=RolRespuesta, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(PERMISO_ROLES))],
)
def crear_rol(datos: RolCrear, db: Session = Depends(get_db)) -> RolRespuesta:
    return cu_gestionar_roles.crear(db, datos)


@roles_router.put("/{rol_id}", response_model=RolRespuesta, dependencies=[Depends(require_permission(PERMISO_ROLES))])
def actualizar_rol(rol_id: int, datos: RolActualizar, db: Session = Depends(get_db)) -> RolRespuesta:
    return cu_gestionar_roles.actualizar(db, rol_id, datos)


@roles_router.delete(
    "/{rol_id}", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(PERMISO_ROLES))],
)
def desactivar_rol(rol_id: int, db: Session = Depends(get_db)) -> None:
    cu_gestionar_roles.desactivar(db, rol_id)


@roles_router.put(
    "/{rol_id}/permisos", response_model=RolRespuesta,
    dependencies=[Depends(require_permission(PERMISO_ROLES))],
)
def asignar_permisos(
    rol_id: int, datos: AsignarPermisosRequest, db: Session = Depends(get_db)
) -> RolRespuesta:
    return cu_gestionar_roles.asignar_permisos(db, rol_id, datos.codigos_permiso)


# ---- /api/v1/usuarios --------------------------------------------------------

usuarios_router = APIRouter(prefix="/api/v1/usuarios", tags=["usuarios"])


@usuarios_router.get(
    "", response_model=list[UsuarioRespuesta],
    dependencies=[Depends(require_permission(PERMISO_USUARIOS))],
)
def listar_usuarios(
    db: Session = Depends(get_db),
    paginacion: ParametrosPaginacion = Depends(parametros_paginacion),
) -> list[UsuarioRespuesta]:
    usuarios = cu_gestionar_usuarios.listar(db, paginacion)
    return [UsuarioRespuesta.from_modelo(u) for u in usuarios]


@usuarios_router.get(
    "/{usuario_id}", response_model=UsuarioRespuesta,
    dependencies=[Depends(require_permission(PERMISO_USUARIOS))],
)
def obtener_usuario_endpoint(usuario_id: int, db: Session = Depends(get_db)) -> UsuarioRespuesta:
    return UsuarioRespuesta.from_modelo(obtener_usuario(db, usuario_id))


@usuarios_router.post(
    "", response_model=UsuarioRespuesta, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(PERMISO_USUARIOS))],
)
def crear_usuario(datos: UsuarioCrear, db: Session = Depends(get_db)) -> UsuarioRespuesta:
    return UsuarioRespuesta.from_modelo(cu_gestionar_usuarios.crear(db, datos))


@usuarios_router.put(
    "/{usuario_id}", response_model=UsuarioRespuesta,
    dependencies=[Depends(require_permission(PERMISO_USUARIOS))],
)
def actualizar_usuario(
    usuario_id: int, datos: UsuarioActualizar, db: Session = Depends(get_db)
) -> UsuarioRespuesta:
    return UsuarioRespuesta.from_modelo(cu_gestionar_usuarios.actualizar(db, usuario_id, datos))


@usuarios_router.delete(
    "/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(PERMISO_USUARIOS))],
)
def desactivar_usuario(usuario_id: int, db: Session = Depends(get_db)) -> None:
    cu_gestionar_usuarios.desactivar(db, usuario_id)


@usuarios_router.put(
    "/{usuario_id}/roles", response_model=UsuarioRespuesta,
    dependencies=[Depends(require_permission(PERMISO_USUARIOS))],
)
def asignar_roles(
    usuario_id: int, datos: AsignarRolesRequest, db: Session = Depends(get_db)
) -> UsuarioRespuesta:
    return UsuarioRespuesta.from_modelo(cu_gestionar_usuarios.asignar_roles(db, usuario_id, datos.nombres_rol))


# ---- /api/v1/clientes/perfil --------------------------------------------------

clientes_router = APIRouter(prefix="/api/v1/clientes", tags=["clientes"])


@clientes_router.get("/perfil", response_model=ClientePerfilRespuesta)
def obtener_perfil(usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> ClientePerfilRespuesta:
    cliente = cu_registrar_cliente.obtener_perfil(db, usuario.id)
    return ClientePerfilRespuesta.from_modelo(cliente)


@clientes_router.put("/perfil", response_model=ClientePerfilRespuesta)
def actualizar_perfil(
    datos: ClientePerfilActualizar, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ClientePerfilRespuesta:
    cliente = cu_registrar_cliente.actualizar_perfil(db, usuario.id, datos)
    return ClientePerfilRespuesta.from_modelo(cliente)


routers = [auth_router, roles_router, usuarios_router, clientes_router]
