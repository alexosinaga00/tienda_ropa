from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.auditoria import ContextoAuditoria, contexto_anonimo, obtener_contexto_auditoria
from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import ParametrosPaginacion, ParametrosPeriodo, parametros_paginacion, periodo_reportes
from app.core.permisos import (
    PERMISO_BITACORA_VER,
    PERMISO_COPIAS,
    PERMISO_EMPRESA,
    PERMISO_ORGANIZACION,
    PERMISO_PLATAFORMA,
    PERMISO_ROLES,
    PERMISO_USUARIOS,
)
from app.core.planes import FUNC_COPIAS_SEGURIDAD, exigir_funcionalidad
from app.core.rate_limit import limiter
from app.core.security import get_current_user, permisos_de_usuario, require_permission, require_service_token
from app.plataforma.casos_uso.cu01_autenticar_registrar_usuarios import (
    IniciarSesion,
    RecuperarContrasena,
    RegistrarCliente,
)
from app.plataforma.casos_uso.cu02_gestionar_usuarios_roles_permisos import (
    GestionarRolesPermisos,
    GestionarUsuarios,
)
from app.plataforma.casos_uso.cu03_gestionar_organizacion import (
    GestionarCiudades,
    GestionarEmpleados,
    GestionarSucursales,
)
from app.plataforma.casos_uso.cu04_gestionar_empresas_planes_suscripciones import (
    ConsultarMiEmpresa,
    GestionarContratacion,
    GestionarCopiasSeguridad,
    GestionarEmpresas,
    GestionarPlanes,
    GestionarSuscripciones,
)
from app.plataforma import politicas
from app.plataforma.politicas import obtener_usuario
from app.plataforma.schemas import (
    AdministradorRegistrar,
    AsignarPermisosRequest,
    AsignarRolesRequest,
    BitacoraPagina,
    BitacoraRespuesta,
    CiudadActualizar,
    CiudadCrear,
    CiudadRespuesta,
    ClientePerfilActualizar,
    ClientePerfilRespuesta,
    CopiaPagina,
    CopiaRespuesta,
    CopiaTablasRespuesta,
    EmpleadoActualizar,
    EmpleadoCrear,
    EmpleadoRespuesta,
    EmpresaActualizar,
    EmpresaRegistrar,
    EmpresaRespuesta,
    EmpresaResumenRespuesta,
    FiltrosBitacora,
    HorarioActualizar,
    HorarioCrear,
    HorarioRespuesta,
    LoginRequest,
    MiEmpresaActualizar,
    MiEmpresaRespuesta,
    MiSuscripcionRespuesta,
    NotificacionRespuesta,
    PedidoCreadoRespuesta,
    PedidoEstadoRespuesta,
    PedidoPagadoRespuesta,
    PedidoSolicitud,
    PermisoRespuesta,
    PlanActualizar,
    PlanCrear,
    PlanPublicoRespuesta,
    PlanRespuesta,
    PruebaGratisRespuesta,
    PruebaGratisSolicitud,
    RecuperarConfirmarRequest,
    RecuperarRequest,
    RecuperarRespuesta,
    RefreshRequest,
    RegistroRequest,
    RolActualizar,
    RolCrear,
    RolRespuesta,
    SucursalActualizar,
    SucursalCrear,
    SucursalRespuesta,
    SuscripcionAsignar,
    SuscripcionEstadoActualizar,
    SuscripcionRenovar,
    SuscripcionRespuesta,
    TiendaPublicaDetalle,
    TiendaPublicaRespuesta,
    TokenRespuesta,
    UsuarioActualizar,
    UsuarioCrear,
    UsuarioRespuesta,
    UsuarioYoRespuesta,
)


# ---- Seguridad ----


cu_registrar_cliente = RegistrarCliente()
cu_iniciar_sesion = IniciarSesion()
cu_gestionar_usuarios = GestionarUsuarios()
cu_gestionar_roles = GestionarRolesPermisos()
cu_recuperar_contrasena = RecuperarContrasena()

# ---- /api/v1/auth -----------------------------------------------------------

auth_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# `registro` (ahora en /public/{codigo}/registro, al final del archivo) y
# `login` son los dos endpoints públicos más atacables del sistema (creación
# masiva de cuentas y fuerza bruta de contraseñas), y el RNF02 pide límite de
# tráfico en los endpoints públicos. Agravante propio de `login`: bcrypt hace
# cada intento caro en CPU, así que sin límite es también un vector de
# agotamiento de recursos.
# `request: Request` no se usa en el cuerpo pero es obligatorio: slowapi lo
# necesita en la firma para resolver la IP del cliente (mismo motivo que en
# `recuperar`, más abajo).
@auth_router.post("/login", response_model=TokenRespuesta)
@limiter.limit("10/minute")
def login(request: Request, datos: LoginRequest, db: Session = Depends(get_db)) -> TokenRespuesta:
    # Sin sesión: el contexto solo trae la IP; el usuario y la empresa de la fila salen del intento.
    return cu_iniciar_sesion.ejecutar(db, datos, contexto_anonimo(request))


@auth_router.post("/refresh", response_model=TokenRespuesta)
@limiter.limit("30/minute")
def refresh(request: Request, datos: RefreshRequest, db: Session = Depends(get_db)) -> TokenRespuesta:
    return cu_iniciar_sesion.refrescar(db, datos.refresh_token)


@auth_router.get("/yo", response_model=UsuarioYoRespuesta)
def yo(usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> UsuarioYoRespuesta:
    base = UsuarioRespuesta.from_modelo(usuario)
    # El superadministrador no pertenece a ninguna empresa: los tres campos van en None.
    empresa = politicas.obtener_empresa(db, usuario.empresa_id) if usuario.empresa_id is not None else None
    return UsuarioYoRespuesta(
        **base.model_dump(),
        permisos=permisos_de_usuario(db, usuario.id),
        empresa_id=usuario.empresa_id,
        empresa_codigo=empresa.codigo if empresa is not None else None,
        empresa_nombre=empresa.nombre if empresa is not None else None,
    )


@auth_router.post("/recuperar", response_model=RecuperarRespuesta, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute")
def recuperar(request: Request, datos: RecuperarRequest, db: Session = Depends(get_db)) -> RecuperarRespuesta:
    token = cu_recuperar_contrasena.solicitar(db, datos.empresa, datos.email)
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
    cu_recuperar_contrasena.confirmar(db, datos.token, datos.password, contexto_anonimo(request))
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
    dependencies=[Depends(require_permission(PERMISO_PLATAFORMA))],
)
def crear_rol(
    datos: RolCrear, db: Session = Depends(get_db), contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria)
) -> RolRespuesta:
    return cu_gestionar_roles.crear(db, datos, contexto)


@roles_router.put("/{rol_id}", response_model=RolRespuesta, dependencies=[Depends(require_permission(PERMISO_PLATAFORMA))])
def actualizar_rol(
    rol_id: int,
    datos: RolActualizar,
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> RolRespuesta:
    return cu_gestionar_roles.actualizar(db, rol_id, datos, contexto)


@roles_router.delete(
    "/{rol_id}", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(PERMISO_PLATAFORMA))],
)
def desactivar_rol(
    rol_id: int, db: Session = Depends(get_db), contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria)
) -> None:
    cu_gestionar_roles.desactivar(db, rol_id, contexto)


@roles_router.put(
    "/{rol_id}/permisos", response_model=RolRespuesta,
    dependencies=[Depends(require_permission(PERMISO_PLATAFORMA))],
)
def asignar_permisos(
    rol_id: int,
    datos: AsignarPermisosRequest,
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> RolRespuesta:
    return cu_gestionar_roles.asignar_permisos(db, rol_id, datos.codigos_permiso, contexto)


# ---- /api/v1/permisos --------------------------------------------------------
# Router propio y no GET /roles/permisos: ese path chocaría con
# /roles/{rol_id}, que ya existe, y quedaría dependiendo del orden en que se
# declaran las rutas.

permisos_router = APIRouter(prefix="/api/v1/permisos", tags=["permisos"])


@permisos_router.get(
    "", response_model=list[PermisoRespuesta],
    dependencies=[Depends(require_permission(PERMISO_ROLES))],
)
def listar_permisos(db: Session = Depends(get_db)) -> list[PermisoRespuesta]:
    """El catálogo de permisos que se pueden asignar a un rol. Lo consume la
    pantalla de roles para pintar las casillas (RF03). Mismo permiso que
    exige asignar_permisos: quien no puede asignarlos tampoco necesita verlos."""
    return [PermisoRespuesta.model_validate(p) for p in cu_gestionar_roles.listar_permisos(db)]


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
def crear_usuario(
    datos: UsuarioCrear, db: Session = Depends(get_db), contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria)
) -> UsuarioRespuesta:
    return UsuarioRespuesta.from_modelo(cu_gestionar_usuarios.crear(db, datos, contexto))


@usuarios_router.put(
    "/{usuario_id}", response_model=UsuarioRespuesta,
    dependencies=[Depends(require_permission(PERMISO_USUARIOS))],
)
def actualizar_usuario(
    usuario_id: int,
    datos: UsuarioActualizar,
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> UsuarioRespuesta:
    return UsuarioRespuesta.from_modelo(cu_gestionar_usuarios.actualizar(db, usuario_id, datos, contexto))


@usuarios_router.delete(
    "/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(PERMISO_USUARIOS))],
)
def desactivar_usuario(
    usuario_id: int, db: Session = Depends(get_db), contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria)
) -> None:
    cu_gestionar_usuarios.desactivar(db, usuario_id, contexto)


@usuarios_router.put(
    "/{usuario_id}/roles", response_model=UsuarioRespuesta,
    dependencies=[Depends(require_permission(PERMISO_USUARIOS))],
)
def asignar_roles(
    usuario_id: int,
    datos: AsignarRolesRequest,
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> UsuarioRespuesta:
    return UsuarioRespuesta.from_modelo(
        cu_gestionar_usuarios.asignar_roles(db, usuario_id, datos.nombres_rol, contexto)
    )


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


# ---- /api/v1/notificaciones ---------------------------------------------------

notificaciones_router = APIRouter(prefix="/api/v1/notificaciones", tags=["notificaciones"])


@notificaciones_router.get("", response_model=list[NotificacionRespuesta])
def listar_notificaciones(
    usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> list[NotificacionRespuesta]:
    return list(politicas.listar_notificaciones(db, usuario.id))


@notificaciones_router.put("/{notificacion_id}/leida", response_model=NotificacionRespuesta)
def marcar_leida(
    notificacion_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> NotificacionRespuesta:
    return politicas.marcar_leida(db, usuario.id, notificacion_id)


# ---- Organización ----


admin_requerido = Depends(require_permission(PERMISO_ORGANIZACION))

cu_gestionar_ciudades = GestionarCiudades()
cu_gestionar_sucursales = GestionarSucursales()
cu_gestionar_empleados = GestionarEmpleados()

# ---- /api/v1/ciudades ---------------------------------------------------

ciudades_router = APIRouter(prefix="/api/v1/ciudades", tags=["ciudades"], dependencies=[admin_requerido])


@ciudades_router.get("", response_model=list[CiudadRespuesta])
def listar_ciudades(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[CiudadRespuesta]:
    return cu_gestionar_ciudades.listar(db, paginacion)


@ciudades_router.get("/{ciudad_id}", response_model=CiudadRespuesta)
def obtener_ciudad(ciudad_id: int, db: Session = Depends(get_db)) -> CiudadRespuesta:
    return cu_gestionar_ciudades.obtener(db, ciudad_id)


@ciudades_router.post("", response_model=CiudadRespuesta, status_code=status.HTTP_201_CREATED)
def crear_ciudad(datos: CiudadCrear, db: Session = Depends(get_db)) -> CiudadRespuesta:
    return cu_gestionar_ciudades.crear(db, datos)


@ciudades_router.put("/{ciudad_id}", response_model=CiudadRespuesta)
def actualizar_ciudad(ciudad_id: int, datos: CiudadActualizar, db: Session = Depends(get_db)) -> CiudadRespuesta:
    return cu_gestionar_ciudades.actualizar(db, ciudad_id, datos)


@ciudades_router.delete("/{ciudad_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar_ciudad(ciudad_id: int, db: Session = Depends(get_db)) -> None:
    cu_gestionar_ciudades.desactivar(db, ciudad_id)


# ---- /api/v1/sucursales ---------------------------------------------------
# GET es público (lo consume el catálogo). SucursalRespuesta nunca incluye
# datos de empleados: no existe ese campo en el schema ni una relación en
# el modelo que lo permita.

sucursales_router = APIRouter(prefix="/api/v1/sucursales", tags=["sucursales"])


@sucursales_router.get("", response_model=list[SucursalRespuesta])
def listar_sucursales(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[SucursalRespuesta]:
    return cu_gestionar_sucursales.listar(db, paginacion)


@sucursales_router.get("/{sucursal_id}", response_model=SucursalRespuesta)
def obtener_sucursal(sucursal_id: int, db: Session = Depends(get_db)) -> SucursalRespuesta:
    return cu_gestionar_sucursales.obtener(db, sucursal_id)


@sucursales_router.post(
    "", response_model=SucursalRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[admin_requerido]
)
def crear_sucursal(
    datos: SucursalCrear, db: Session = Depends(get_db), contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria)
) -> SucursalRespuesta:
    return cu_gestionar_sucursales.crear(db, datos, contexto)


@sucursales_router.put(
    "/{sucursal_id}", response_model=SucursalRespuesta, dependencies=[admin_requerido]
)
def actualizar_sucursal(
    sucursal_id: int,
    datos: SucursalActualizar,
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> SucursalRespuesta:
    return cu_gestionar_sucursales.actualizar(db, sucursal_id, datos, contexto)


@sucursales_router.delete(
    "/{sucursal_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[admin_requerido]
)
def desactivar_sucursal(
    sucursal_id: int, db: Session = Depends(get_db), contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria)
) -> None:
    cu_gestionar_sucursales.desactivar(db, sucursal_id, contexto)


# ---- /api/v1/sucursales/{id}/horarios --------------------------------------
# GET es público: el horario de atención lo necesita el cliente (Flutter,
# al elegir franja para una reserva) tanto como el back office. Escribir
# horarios sigue siendo solo de administración.

horarios_router = APIRouter(prefix="/api/v1/sucursales/{sucursal_id}/horarios", tags=["horarios"])


@horarios_router.get("", response_model=list[HorarioRespuesta])
def listar_horarios(sucursal_id: int, db: Session = Depends(get_db)) -> list[HorarioRespuesta]:
    return cu_gestionar_sucursales.listar_horarios(db, sucursal_id)


@horarios_router.post(
    "", response_model=HorarioRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[admin_requerido]
)
def crear_horario(sucursal_id: int, datos: HorarioCrear, db: Session = Depends(get_db)) -> HorarioRespuesta:
    return cu_gestionar_sucursales.crear_horario(db, sucursal_id, datos)


@horarios_router.put("/{horario_id}", response_model=HorarioRespuesta, dependencies=[admin_requerido])
def actualizar_horario(
    sucursal_id: int, horario_id: int, datos: HorarioActualizar, db: Session = Depends(get_db)
) -> HorarioRespuesta:
    return cu_gestionar_sucursales.actualizar_horario(db, sucursal_id, horario_id, datos)


@horarios_router.delete("/{horario_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[admin_requerido])
def eliminar_horario(sucursal_id: int, horario_id: int, db: Session = Depends(get_db)) -> None:
    cu_gestionar_sucursales.eliminar_horario(db, sucursal_id, horario_id)


# ---- /api/v1/empleados ---------------------------------------------------
# Sin dependencies=[admin_requerido] a nivel de router (a diferencia de los
# otros): /empleados/yo lo llama cualquier empleado logueado (p. ej. la caja
# en Angular, para saber su propia sucursal), el resto sigue siendo de
# administración.

empleados_router = APIRouter(prefix="/api/v1/empleados", tags=["empleados"])


@empleados_router.get("/yo", response_model=EmpleadoRespuesta)
def obtener_mi_empleado(usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> EmpleadoRespuesta:
    return cu_gestionar_empleados.obtener_mi_empleado(db, usuario.id)


@empleados_router.get("", response_model=list[EmpleadoRespuesta], dependencies=[admin_requerido])
def listar_empleados(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[EmpleadoRespuesta]:
    return cu_gestionar_empleados.listar(db, paginacion)


@empleados_router.get("/{empleado_id}", response_model=EmpleadoRespuesta, dependencies=[admin_requerido])
def obtener_empleado(empleado_id: int, db: Session = Depends(get_db)) -> EmpleadoRespuesta:
    return cu_gestionar_empleados.obtener(db, empleado_id)


@empleados_router.post("", response_model=EmpleadoRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[admin_requerido])
def crear_empleado(
    datos: EmpleadoCrear, db: Session = Depends(get_db), contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria)
) -> EmpleadoRespuesta:
    return cu_gestionar_empleados.crear(db, datos, contexto)


@empleados_router.put("/{empleado_id}", response_model=EmpleadoRespuesta, dependencies=[admin_requerido])
def actualizar_empleado(
    empleado_id: int,
    datos: EmpleadoActualizar,
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> EmpleadoRespuesta:
    return cu_gestionar_empleados.actualizar(db, empleado_id, datos, contexto)


@empleados_router.delete("/{empleado_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[admin_requerido])
def desactivar_empleado(
    empleado_id: int, db: Session = Depends(get_db), contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria)
) -> None:
    cu_gestionar_empleados.desactivar(db, empleado_id, contexto)


# ---- /api/v1/public/{codigo} (tienda pública por empresa) --------------------------
# Los MISMOS handlers públicos de sucursales y horarios, bajo el código de la
# tienda (D02, D10). La empresa la fija `contexto_empresa` (core/tenant.py) desde
# el código de la ruta; `_codigo_tienda` solo documenta el parámetro en OpenAPI.
# No se copian handlers. El registro del cliente (E03) es el único handler propio
# de este router: la empresa es la de la ruta y ya viene fijada en la sesión.


def _codigo_tienda(codigo: str) -> str:
    return codigo


publico_tienda_router = APIRouter(
    prefix="/api/v1/public/{codigo}", tags=["tienda-publica"], dependencies=[Depends(_codigo_tienda)]
)

# `request: Request` es obligatorio para que slowapi resuelva la IP del cliente.
@publico_tienda_router.post("/registro", response_model=UsuarioRespuesta, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def registro(request: Request, datos: RegistroRequest, db: Session = Depends(get_db)) -> UsuarioRespuesta:
    usuario = cu_registrar_cliente.registrar(db, datos)
    return UsuarioRespuesta.from_modelo(usuario)


# Los datos públicos de la tienda (4 campos). Exenta de la suscripción (ver
# RUTAS_SIN_SUSCRIPCION): la pantalla puede mostrar "Tienda no disponible" con
# el nombre de la tienda aunque la suscripción no esté activa.
@publico_tienda_router.get("/tienda", response_model=TiendaPublicaDetalle, tags=["publico"])
@limiter.limit("60/minute")
def tienda_publica(request: Request, codigo: str, db: Session = Depends(get_db)) -> TiendaPublicaDetalle:
    return cu_gestionar_empresas.obtener_tienda(db, codigo)


for _ruta, _handler, _modelo in (
    ("/sucursales", listar_sucursales, list[SucursalRespuesta]),
    ("/sucursales/{sucursal_id}", obtener_sucursal, SucursalRespuesta),
    ("/sucursales/{sucursal_id}/horarios", listar_horarios, list[HorarioRespuesta]),
):
    publico_tienda_router.add_api_route(_ruta, _handler, methods=["GET"], response_model=_modelo)


# ---- CU-04: empresas, planes y suscripciones --------------------------------------
# El router solo instancia el caso de uso y lo llama (regla 5).

cu_gestionar_empresas = GestionarEmpresas()
cu_gestionar_planes = GestionarPlanes()
cu_gestionar_suscripciones = GestionarSuscripciones()
cu_mi_empresa = ConsultarMiEmpresa()
cu_contratacion = GestionarContratacion()

# ---- /api/v1/plataforma (superadministrador) ----------------------------------------

plataforma_router = APIRouter(
    prefix="/api/v1/plataforma",
    tags=["plataforma"],
    dependencies=[Depends(require_permission(PERMISO_PLATAFORMA))],
)


@plataforma_router.get("/planes", response_model=list[PlanRespuesta])
def listar_planes(
    db: Session = Depends(get_db), paginacion: ParametrosPaginacion = Depends(parametros_paginacion)
) -> list[PlanRespuesta]:
    return cu_gestionar_planes.listar(db, paginacion)


@plataforma_router.get("/planes/{plan_id}", response_model=PlanRespuesta)
def obtener_plan(plan_id: int, db: Session = Depends(get_db)) -> PlanRespuesta:
    return cu_gestionar_planes.obtener(db, plan_id)


@plataforma_router.post("/planes", response_model=PlanRespuesta, status_code=status.HTTP_201_CREATED)
def crear_plan(
    datos: PlanCrear, db: Session = Depends(get_db), contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria)
) -> PlanRespuesta:
    return cu_gestionar_planes.crear(db, datos, contexto)


@plataforma_router.put("/planes/{plan_id}", response_model=PlanRespuesta)
def actualizar_plan(
    plan_id: int,
    datos: PlanActualizar,
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> PlanRespuesta:
    return cu_gestionar_planes.actualizar(db, plan_id, datos, contexto)


@plataforma_router.delete("/planes/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar_plan(
    plan_id: int, db: Session = Depends(get_db), contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria)
) -> None:
    cu_gestionar_planes.desactivar(db, plan_id, contexto)


@plataforma_router.get("/empresas", response_model=list[EmpresaRespuesta])
def listar_empresas(
    q: str | None = Query(default=None, max_length=120),
    activo: bool | None = None,
    db: Session = Depends(get_db),
    paginacion: ParametrosPaginacion = Depends(parametros_paginacion),
) -> list[EmpresaRespuesta]:
    return cu_gestionar_empresas.listar(db, paginacion, q, activo)


@plataforma_router.get("/empresas/{empresa_id}", response_model=EmpresaRespuesta)
def obtener_empresa(empresa_id: int, db: Session = Depends(get_db)) -> EmpresaRespuesta:
    return cu_gestionar_empresas.obtener(db, empresa_id)


@plataforma_router.post("/empresas", response_model=EmpresaRespuesta, status_code=status.HTTP_201_CREATED)
def registrar_empresa(
    datos: EmpresaRegistrar, db: Session = Depends(get_db), contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria)
) -> EmpresaRespuesta:
    return cu_gestionar_empresas.registrar(db, datos, contexto)


@plataforma_router.put("/empresas/{empresa_id}", response_model=EmpresaRespuesta)
def actualizar_empresa(
    empresa_id: int,
    datos: EmpresaActualizar,
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> EmpresaRespuesta:
    return cu_gestionar_empresas.actualizar(db, empresa_id, datos, contexto)


@plataforma_router.delete("/empresas/{empresa_id}", status_code=status.HTTP_204_NO_CONTENT)
def desactivar_empresa(
    empresa_id: int, db: Session = Depends(get_db), contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria)
) -> None:
    cu_gestionar_empresas.desactivar(db, empresa_id, contexto)


@plataforma_router.get("/empresas/{empresa_id}/resumen", response_model=EmpresaResumenRespuesta)
def resumen_empresa(empresa_id: int, db: Session = Depends(get_db)) -> EmpresaResumenRespuesta:
    return cu_gestionar_empresas.resumen(db, empresa_id)


@plataforma_router.post(
    "/empresas/{empresa_id}/usuarios", response_model=UsuarioRespuesta, status_code=status.HTTP_201_CREATED
)
def agregar_administrador(
    empresa_id: int,
    datos: AdministradorRegistrar,
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> UsuarioRespuesta:
    return cu_gestionar_empresas.agregar_administrador(db, empresa_id, datos, contexto)


@plataforma_router.post(
    "/empresas/{empresa_id}/sucursales", response_model=SucursalRespuesta, status_code=status.HTTP_201_CREATED
)
def agregar_sucursal(
    empresa_id: int,
    datos: SucursalCrear,
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> SucursalRespuesta:
    return cu_gestionar_empresas.agregar_sucursal(db, empresa_id, datos, contexto)


@plataforma_router.get("/suscripciones", response_model=list[SuscripcionRespuesta])
def listar_suscripciones(
    empresa_id: int | None = None,
    estado: Literal["activa", "suspendida", "vencida", "cancelada"] | None = None,
    db: Session = Depends(get_db),
    paginacion: ParametrosPaginacion = Depends(parametros_paginacion),
) -> list[SuscripcionRespuesta]:
    return cu_gestionar_suscripciones.listar(db, paginacion, empresa_id, estado)


@plataforma_router.get("/suscripciones/{suscripcion_id}", response_model=SuscripcionRespuesta)
def obtener_suscripcion(suscripcion_id: int, db: Session = Depends(get_db)) -> SuscripcionRespuesta:
    return cu_gestionar_suscripciones.obtener(db, suscripcion_id)


@plataforma_router.post("/suscripciones", response_model=SuscripcionRespuesta, status_code=status.HTTP_201_CREATED)
def asignar_plan(
    datos: SuscripcionAsignar, db: Session = Depends(get_db), contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria)
) -> SuscripcionRespuesta:
    return cu_gestionar_suscripciones.asignar_o_cambiar_plan(db, datos, contexto)


@plataforma_router.put("/suscripciones/{suscripcion_id}/renovar", response_model=SuscripcionRespuesta)
def renovar_suscripcion(
    suscripcion_id: int,
    datos: SuscripcionRenovar,
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> SuscripcionRespuesta:
    return cu_gestionar_suscripciones.renovar(db, suscripcion_id, datos, contexto)


@plataforma_router.put("/suscripciones/{suscripcion_id}/estado", response_model=SuscripcionRespuesta)
def cambiar_estado_suscripcion(
    suscripcion_id: int,
    datos: SuscripcionEstadoActualizar,
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> SuscripcionRespuesta:
    return cu_gestionar_suscripciones.cambiar_estado(db, suscripcion_id, datos, contexto)


# ---- Bitácora de auditoría ----
# El router solo lee los filtros y llama a `politicas` (la bitácora no es un CU).


def filtros_bitacora(
    periodo: ParametrosPeriodo = Depends(periodo_reportes),
    entidad: str | None = Query(default=None, max_length=60),
    accion: str | None = Query(default=None, max_length=40),
    usuario_id: int | None = None,
) -> FiltrosBitacora:
    return FiltrosBitacora(
        desde=periodo.desde, hasta=periodo.hasta, entidad=entidad, accion=accion, usuario_id=usuario_id
    )


def filtros_bitacora_plataforma(
    filtros: FiltrosBitacora = Depends(filtros_bitacora),
    empresa_id: int | None = None,
    sin_empresa: bool = False,
) -> FiltrosBitacora:
    return filtros.model_copy(update={"empresa_id": empresa_id, "sin_empresa": sin_empresa})


@plataforma_router.get("/bitacora", response_model=BitacoraPagina)
def listar_bitacora_plataforma(
    filtros: FiltrosBitacora = Depends(filtros_bitacora_plataforma),
    paginacion: ParametrosPaginacion = Depends(parametros_paginacion),
    db: Session = Depends(get_db),
) -> BitacoraPagina:
    return politicas.listar_bitacora_plataforma(db, filtros, paginacion)


# ---- /api/v1/bitacora (administrador de la empresa) ----------------------------------------

bitacora_router = APIRouter(
    prefix="/api/v1/bitacora",
    tags=["bitacora"],
    dependencies=[Depends(require_permission(PERMISO_BITACORA_VER))],
)


@bitacora_router.get("", response_model=BitacoraPagina)
def listar_bitacora(
    filtros: FiltrosBitacora = Depends(filtros_bitacora),
    paginacion: ParametrosPaginacion = Depends(parametros_paginacion),
    db: Session = Depends(get_db),
) -> BitacoraPagina:
    return politicas.listar_bitacora(db, filtros, paginacion)


@bitacora_router.get("/{bitacora_id}", response_model=BitacoraRespuesta)
def obtener_bitacora(bitacora_id: int, db: Session = Depends(get_db)) -> BitacoraRespuesta:
    return politicas.obtener_bitacora(db, bitacora_id)


# ---- /api/v1/copias-seguridad (administrador de la empresa, plan con copias) ----------------
# Orden de errores: 401, suscripción, plan (exigir_funcionalidad), permiso y recién entonces las reglas. La
# empresa sale SIEMPRE del token. El ZIP no se guarda: se entrega en la misma respuesta que lo crea.

cu_copias = GestionarCopiasSeguridad()

copias_router = APIRouter(
    prefix="/api/v1/copias-seguridad",
    tags=["copias-seguridad"],
    dependencies=[Depends(exigir_funcionalidad(FUNC_COPIAS_SEGURIDAD)), Depends(require_permission(PERMISO_COPIAS))],
)


@copias_router.post(
    "",
    response_class=Response,
    responses={
        200: {"description": "El ZIP de la copia", "content": {"application/zip": {}}},
        409: {"description": "copia_en_curso: ya hay una copia de esta empresa en proceso"},
        413: {"description": "copia_demasiado_grande"},
        503: {"description": "servidor_ocupado"},
        504: {"description": "copia_tiempo_agotado"},
    },
)
@limiter.limit("10/hour")
def crear_copia_seguridad(
    request: Request,
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> Response:
    generada = cu_copias.crear(db, usuario.id, contexto)
    return Response(
        content=generada.contenido,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{generada.nombre_archivo}"',
            "X-Copia-Id": str(generada.copia.id),
            "X-Checksum-SHA256": generada.copia.checksum or "",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


# `/tablas` se declara ANTES de `/{copia_id}` para que no la capture.
@copias_router.get("/tablas", response_model=CopiaTablasRespuesta)
def tablas_de_la_copia(db: Session = Depends(get_db)) -> CopiaTablasRespuesta:
    return cu_copias.tablas(db)


@copias_router.get("", response_model=CopiaPagina)
def listar_copias_seguridad(
    paginacion: ParametrosPaginacion = Depends(parametros_paginacion), db: Session = Depends(get_db)
) -> CopiaPagina:
    return cu_copias.listar(db, paginacion)


@copias_router.get("/{copia_id}", response_model=CopiaRespuesta)
def obtener_copia_seguridad(copia_id: int, db: Session = Depends(get_db)) -> CopiaRespuesta:
    return cu_copias.obtener(db, copia_id)


# ---- /api/v1/mi-empresa (administrador de la empresa) ------------------------------------
# Exenta de la suscripción: el administrador ve su estado y pide la renovación
# aunque la suscripción esté vencida o suspendida.

mi_empresa_router = APIRouter(
    prefix="/api/v1/mi-empresa",
    tags=["mi-empresa"],
    dependencies=[Depends(require_permission(PERMISO_EMPRESA))],
)


@mi_empresa_router.get("", response_model=MiEmpresaRespuesta)
def obtener_mi_empresa(db: Session = Depends(get_db)) -> MiEmpresaRespuesta:
    return cu_mi_empresa.obtener(db)


@mi_empresa_router.put("", response_model=MiEmpresaRespuesta)
def actualizar_mi_empresa(
    datos: MiEmpresaActualizar,
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> MiEmpresaRespuesta:
    return cu_mi_empresa.actualizar(db, datos, contexto)


@mi_empresa_router.get("/suscripcion", response_model=MiSuscripcionRespuesta)
def obtener_mi_suscripcion(db: Session = Depends(get_db)) -> MiSuscripcionRespuesta:
    return cu_mi_empresa.obtener_suscripcion(db)


# ---- /api/v1/public/tiendas (sin sesión) ---------------------------------------------------
# Lista de tiendas para elegir (web "/" y "Elige tu tienda" del móvil). No choca
# con /public/{codigo}/...: aquel siempre lleva un segmento más.


def _paginacion_tiendas(
    pagina: int = Query(default=1, ge=1), tamanio: int = Query(default=20, ge=1, le=50)
) -> ParametrosPaginacion:
    return ParametrosPaginacion(pagina=pagina, tamanio=tamanio)


publico_tiendas_router = APIRouter(prefix="/api/v1/public", tags=["publico"])


# `request: Request` es obligatorio para que slowapi resuelva la IP del cliente.
@publico_tiendas_router.get("/tiendas", response_model=list[TiendaPublicaRespuesta])
@limiter.limit("60/minute")
def listar_tiendas(
    request: Request,
    q: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db),
    paginacion: ParametrosPaginacion = Depends(_paginacion_tiendas),
) -> list[TiendaPublicaRespuesta]:
    return cu_gestionar_empresas.listar_tiendas(db, paginacion, q)


# Los planes activos para la portada pública. Tampoco choca con /public/{codigo}/...
@publico_tiendas_router.get("/planes", response_model=list[PlanPublicoRespuesta])
@limiter.limit("60/minute")
def listar_planes_publicos(request: Request, db: Session = Depends(get_db)) -> list[PlanPublicoRespuesta]:
    return cu_gestionar_planes.listar_publicos(db)


# Prueba gratuita pública: crea una EMPRESA (bcrypt, catálogos base), así que el límite por IP es estricto. Solo cuentan
# las peticiones válidas (la validación del cuerpo ocurre antes del límite). La ruta NO lleva `{codigo}`: no es una tienda,
# `contexto_empresa` no fija ninguna empresa y no exige suscripción (ver `RUTAS_SIN_SUSCRIPCION`).
@publico_tiendas_router.post(
    "/contratacion/prueba", response_model=PruebaGratisRespuesta, status_code=status.HTTP_201_CREATED
)
@limiter.limit("5/hour")
def iniciar_prueba_gratis(
    request: Request, datos: PruebaGratisSolicitud, db: Session = Depends(get_db)
) -> PruebaGratisRespuesta:
    return cu_contratacion.iniciar_prueba(db, datos, contexto_anonimo(request))


# Compra de un plan con PayPal. Mismas reglas que la prueba: rutas anónimas bajo /contratacion/ (sin `{codigo}`, sin
# empresa en la sesión y exentas de la suscripción). El único secreto del comprador es el `token` del pedido (opaco,
# 43 caracteres): un token inexistente da siempre el mismo 404. Crear un pedido cuesta un bcrypt y una llamada a PayPal,
# así que su límite por IP es estricto; consultar es barato (la web consulta con frecuencia al volver de PayPal).
_TokenDePedido = Path(min_length=1, max_length=64)


@publico_tiendas_router.post(
    "/contratacion/pedidos", response_model=PedidoCreadoRespuesta, status_code=status.HTTP_201_CREATED
)
@limiter.limit("5/hour")
def crear_pedido_de_contratacion(
    request: Request, datos: PedidoSolicitud, db: Session = Depends(get_db)
) -> PedidoCreadoRespuesta:
    return cu_contratacion.crear_pedido(db, datos, contexto_anonimo(request))


@publico_tiendas_router.get("/contratacion/pedidos/{token}", response_model=PedidoEstadoRespuesta)
@limiter.limit("60/minute")
def consultar_pedido_de_contratacion(
    request: Request, token: str = _TokenDePedido, db: Session = Depends(get_db)
) -> PedidoEstadoRespuesta:
    return cu_contratacion.consultar_pedido(db, token)


@publico_tiendas_router.post("/contratacion/pedidos/{token}/capturar", response_model=PedidoPagadoRespuesta)
@limiter.limit("10/minute")
def capturar_pedido_de_contratacion(
    request: Request, token: str = _TokenDePedido, db: Session = Depends(get_db)
) -> PedidoPagadoRespuesta:
    return cu_contratacion.capturar_pedido(db, token, contexto_anonimo(request))


@publico_tiendas_router.post("/contratacion/pedidos/{token}/cancelar", response_model=PedidoEstadoRespuesta)
@limiter.limit("10/minute")
def cancelar_pedido_de_contratacion(
    request: Request, token: str = _TokenDePedido, db: Session = Depends(get_db)
) -> PedidoEstadoRespuesta:
    return cu_contratacion.cancelar_pedido(db, token, contexto_anonimo(request))


# ---- /api/v1/tareas (token de servicio) ------------------------------------------------------
# La dispara un cron/scheduler (la tarea periódica del backend corre sola
# también). Una sola pasada sobre todas las empresas.

tareas_plataforma_router = APIRouter(
    prefix="/api/v1/tareas", tags=["tareas"], dependencies=[Depends(require_service_token)]
)


@tareas_plataforma_router.post("/vencer-suscripciones")
def vencer_suscripciones(db: Session = Depends(get_db)) -> dict:
    return {"vencidas": cu_gestionar_suscripciones.vencer_pendientes(db)}


@tareas_plataforma_router.post("/purgar-bitacora")
def purgar_bitacora(db: Session = Depends(get_db)) -> dict:
    return {"eliminadas": politicas.purgar_bitacora(db)}


routers = [
    auth_router,
    roles_router,
    permisos_router,
    usuarios_router,
    clientes_router,
    notificaciones_router,
    ciudades_router,
    sucursales_router,
    horarios_router,
    empleados_router,
    plataforma_router,
    bitacora_router,
    copias_router,
    mi_empresa_router,
    publico_tiendas_router,
    tareas_plataforma_router,
    publico_tienda_router,
]
