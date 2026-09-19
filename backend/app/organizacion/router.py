from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import ParametrosPaginacion, parametros_paginacion
from app.core.security import get_current_user, require_permission
from app.organizacion.casos_uso.cu04_gestionar_ciudades import GestionarCiudades
from app.organizacion.casos_uso.cu05_gestionar_sucursales import GestionarSucursales
from app.organizacion.casos_uso.cu06_gestionar_empleados import GestionarEmpleados
from app.organizacion.schemas import (
    CiudadActualizar,
    CiudadCrear,
    CiudadRespuesta,
    EmpleadoActualizar,
    EmpleadoCrear,
    EmpleadoRespuesta,
    HorarioActualizar,
    HorarioCrear,
    HorarioRespuesta,
    SucursalActualizar,
    SucursalCrear,
    SucursalRespuesta,
)

PERMISO_ORGANIZACION = "organizacion.gestionar"
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
def crear_sucursal(datos: SucursalCrear, db: Session = Depends(get_db)) -> SucursalRespuesta:
    return cu_gestionar_sucursales.crear(db, datos)


@sucursales_router.put(
    "/{sucursal_id}", response_model=SucursalRespuesta, dependencies=[admin_requerido]
)
def actualizar_sucursal(
    sucursal_id: int, datos: SucursalActualizar, db: Session = Depends(get_db)
) -> SucursalRespuesta:
    return cu_gestionar_sucursales.actualizar(db, sucursal_id, datos)


@sucursales_router.delete(
    "/{sucursal_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[admin_requerido]
)
def desactivar_sucursal(sucursal_id: int, db: Session = Depends(get_db)) -> None:
    cu_gestionar_sucursales.desactivar(db, sucursal_id)


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
def crear_empleado(datos: EmpleadoCrear, db: Session = Depends(get_db)) -> EmpleadoRespuesta:
    return cu_gestionar_empleados.crear(db, datos)


@empleados_router.put("/{empleado_id}", response_model=EmpleadoRespuesta, dependencies=[admin_requerido])
def actualizar_empleado(
    empleado_id: int, datos: EmpleadoActualizar, db: Session = Depends(get_db)
) -> EmpleadoRespuesta:
    return cu_gestionar_empleados.actualizar(db, empleado_id, datos)


@empleados_router.delete("/{empleado_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[admin_requerido])
def desactivar_empleado(empleado_id: int, db: Session = Depends(get_db)) -> None:
    cu_gestionar_empleados.desactivar(db, empleado_id)


routers = [ciudades_router, sucursales_router, horarios_router, empleados_router]
