from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_permission, require_service_token
from app.pagos import service
from app.pagos.schemas import (
    PagoCajaRequest,
    PagoCajaRespuesta,
    PagoIniciarRequest,
    PagoIniciarRespuesta,
    PagoRespuesta,
)

PERMISO_GESTIONAR = "pagos.gestionar"
gestionar_requerido = Depends(require_permission(PERMISO_GESTIONAR))


def _pago_respuesta(db: Session, pago) -> PagoRespuesta:
    return service.construir_pago_respuesta(db, pago)


router = APIRouter(prefix="/api/v1/pagos", tags=["pagos"])


@router.post("/iniciar", response_model=PagoIniciarRespuesta, status_code=status.HTTP_201_CREATED)
def iniciar_pago(
    datos: PagoIniciarRequest, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> PagoIniciarRespuesta:
    pago, url = service.iniciar_pago_pasarela(db, usuario.id, datos)
    return PagoIniciarRespuesta(pago=_pago_respuesta(db, pago), url_redireccion=url)


@router.post("/caja", response_model=PagoCajaRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[gestionar_requerido])
def pagar_en_caja(
    datos: PagoCajaRequest, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> PagoCajaRespuesta:
    pago, cambio = service.pagar_en_caja(db, usuario.id, datos)
    return PagoCajaRespuesta(pago=_pago_respuesta(db, pago), cambio=cambio)


@router.get("/{pago_id}/estado", response_model=PagoRespuesta)
def obtener_estado(pago_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> PagoRespuesta:
    pago = service.obtener_estado_pago(db, usuario.id, pago_id)
    return _pago_respuesta(db, pago)


@router.post("/venta/{venta_id}/cancelar")
def cancelar_compra(venta_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    service.cancelar_compra(db, usuario.id, venta_id)
    return {"venta_id": venta_id, "estado": "anulada"}


@router.post("/{pago_id}/anular", response_model=PagoRespuesta, dependencies=[gestionar_requerido])
def anular_pago(pago_id: int, db: Session = Depends(get_db)) -> PagoRespuesta:
    pago = service.anular_pago(db, pago_id)
    return _pago_respuesta(db, pago)


# Sin autenticación JWT: lo llama el servidor de la pasarela, no una
# persona logueada. La seguridad acá es la verificación de firma HMAC
# (service.procesar_webhook -> pasarela.verificar_firma), no un permiso.
@router.post("/webhook/{pasarela}", response_model=PagoRespuesta)
async def recibir_webhook(
    pasarela: str,
    request: Request,
    db: Session = Depends(get_db),
    x_signature: str | None = Header(default=None),
) -> PagoRespuesta:
    payload_crudo = await request.body()
    pago = service.procesar_webhook(db, pasarela, payload_crudo, x_signature)
    return _pago_respuesta(db, pago)


# Protegida por token de servicio, igual que /tareas/expirar-reservas. Además
# la corre sola la tarea periódica de app/main.py (lifespan).
tareas_router = APIRouter(prefix="/api/v1/tareas", tags=["tareas"], dependencies=[Depends(require_service_token)])


@tareas_router.post("/expirar-ventas-pendientes")
def expirar_ventas_pendientes(db: Session = Depends(get_db)) -> dict:
    return service.expirar_ventas_pendientes(db)


routers = [router, tareas_router]
