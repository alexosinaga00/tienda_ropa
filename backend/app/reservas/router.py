from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_permission, require_service_token
from app.reservas.casos_uso.cu16_reservar_prendas import ReservarPrendas
from app.reservas.casos_uso.cu17_consultar_estado_reserva import ConsultarEstadoReserva
from app.reservas.casos_uso.cu18_cancelar_reserva import CancelarReserva
from app.reservas.casos_uso.cu19_consultar_reservas_sucursal import ConsultarReservasSucursal
from app.reservas.casos_uso.cu20_atender_prueba_reserva_sucursal import AtenderPruebaReservaSucursal
from app.reservas.politicas import expirar_reservas_vencidas, mapa_codigos_estado
from app.reservas.schemas import ReservaCrear, ReservaRespuesta, SeleccionActualizar

PERMISO_CREAR = "reservas.crear"
PERMISO_STAFF = "reservas.gestionar_sucursal"
crear_requerido = Depends(require_permission(PERMISO_CREAR))
staff_requerido = Depends(require_permission(PERMISO_STAFF))

cu_reservar_prendas = ReservarPrendas()
cu_consultar_estado = ConsultarEstadoReserva()
cu_cancelar_reserva = CancelarReserva()
cu_consultar_sucursal = ConsultarReservasSucursal()
cu_atender_prueba = AtenderPruebaReservaSucursal()


def _respuesta(db: Session, reserva) -> ReservaRespuesta:
    return ReservaRespuesta.from_modelo(reserva, mapa_codigos_estado(db))


router = APIRouter(prefix="/api/v1/reservas", tags=["reservas"])


@router.post("", response_model=ReservaRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[crear_requerido])
def crear_reserva(
    datos: ReservaCrear, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ReservaRespuesta:
    reserva = cu_reservar_prendas.ejecutar(db, usuario.id, datos)
    return _respuesta(db, reserva)


@router.get("/mis-reservas", response_model=list[ReservaRespuesta], dependencies=[crear_requerido])
def listar_mis_reservas(usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> list[ReservaRespuesta]:
    estados = mapa_codigos_estado(db)
    return [ReservaRespuesta.from_modelo(r, estados) for r in cu_consultar_estado.listar_mias(db, usuario.id)]


@router.get("/sucursal/{sucursal_id}", response_model=list[ReservaRespuesta], dependencies=[staff_requerido])
def listar_reservas_sucursal(
    sucursal_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ReservaRespuesta]:
    estados = mapa_codigos_estado(db)
    reservas = cu_consultar_sucursal.ejecutar(db, sucursal_id, usuario.id)
    return [ReservaRespuesta.from_modelo(r, estados) for r in reservas]


@router.get("/{reserva_id}", response_model=ReservaRespuesta)
def obtener_reserva(
    reserva_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ReservaRespuesta:
    reserva = cu_consultar_estado.obtener(db, reserva_id, usuario.id)
    return _respuesta(db, reserva)


@router.delete("/{reserva_id}", response_model=ReservaRespuesta)
def cancelar_reserva(
    reserva_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ReservaRespuesta:
    reserva = cu_cancelar_reserva.ejecutar(db, reserva_id, usuario.id)
    return _respuesta(db, reserva)


@router.put("/{reserva_id}/preparar", response_model=ReservaRespuesta, dependencies=[staff_requerido])
def preparar_reserva(
    reserva_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ReservaRespuesta:
    reserva = cu_atender_prueba.preparar(db, reserva_id, usuario.id)
    return _respuesta(db, reserva)


@router.put("/{reserva_id}/confirmar-llegada", response_model=ReservaRespuesta, dependencies=[staff_requerido])
def confirmar_llegada(
    reserva_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ReservaRespuesta:
    reserva = cu_atender_prueba.confirmar_llegada(db, reserva_id, usuario.id)
    return _respuesta(db, reserva)


@router.put("/{reserva_id}/seleccion", response_model=ReservaRespuesta, dependencies=[staff_requerido])
def registrar_seleccion(
    reserva_id: int, datos: SeleccionActualizar, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ReservaRespuesta:
    reserva = cu_atender_prueba.registrar_seleccion(db, reserva_id, usuario.id, datos)
    return _respuesta(db, reserva)


# ---- /api/v1/tareas ---------------------------------------------------------------
# Protegida por token de servicio (no por JWT): la dispara un cron/scheduler,
# no una persona logueada. expirar_reservas_vencidas no es un caso de uso
# del catálogo (no tiene actor humano): vive en reservas/politicas.py.

tareas_router = APIRouter(prefix="/api/v1/tareas", tags=["tareas"], dependencies=[Depends(require_service_token)])


@tareas_router.post("/expirar-reservas")
def expirar_reservas(db: Session = Depends(get_db)) -> dict:
    cantidad = expirar_reservas_vencidas(db)
    return {"expiradas": cantidad}


routers = [router, tareas_router]
