from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_permission
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


@router.post("/{pago_id}/anular", response_model=PagoRespuesta, dependencies=[gestionar_requerido])
def anular_pago(pago_id: int, db: Session = Depends(get_db)) -> PagoRespuesta:
    pago = service.anular_pago(db, pago_id)
    return _pago_respuesta(db, pago)


# Pantalla pública de la pasarela simulada "qr_online" (ver
# pagos/pasarela.py::QrOnlineGateway). Sin autenticación JWT: la abre un
# WebView/navegador que no tiene por qué estar logueado en la app -- el
# id_transaccion (128 bits) es el único requisito, mismo modelo de
# confianza que un link de pago.
@router.get("/qr/{id_transaccion}", response_class=HTMLResponse)
def pantalla_qr(id_transaccion: str, db: Session = Depends(get_db)) -> HTMLResponse:
    html = service.renderizar_pantalla_qr(db, id_transaccion)
    return HTMLResponse(content=html)


@router.post("/qr/{id_transaccion}/confirmar", response_model=PagoRespuesta)
def confirmar_qr(id_transaccion: str, db: Session = Depends(get_db)) -> PagoRespuesta:
    pago = service.confirmar_pago_qr(db, id_transaccion)
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


routers = [router]
