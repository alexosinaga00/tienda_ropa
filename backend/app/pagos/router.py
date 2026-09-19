from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_permission, require_service_token
from app.pagos.casos_uso.cu29_pagar_pasarela_digital import PagarPasarelaDigital
from app.pagos.casos_uso.cu30_procesar_pago_caja import ProcesarPagoCaja
from app.pagos.casos_uso.cu31_confirmar_rechazar_transaccion import ConfirmarRechazarTransaccion
from app.pagos.politicas import construir_pago_respuesta, expirar_ventas_pendientes
from app.pagos.schemas import (
    PagoCajaRequest,
    PagoCajaRespuesta,
    PagoIniciarRequest,
    PagoIniciarRespuesta,
    PagoRespuesta,
)

PERMISO_GESTIONAR = "pagos.gestionar"
gestionar_requerido = Depends(require_permission(PERMISO_GESTIONAR))

cu_pagar_pasarela = PagarPasarelaDigital()
cu_procesar_caja = ProcesarPagoCaja()
cu_confirmar_rechazar = ConfirmarRechazarTransaccion()


def _pago_respuesta(db: Session, pago) -> PagoRespuesta:
    return construir_pago_respuesta(db, pago)


router = APIRouter(prefix="/api/v1/pagos", tags=["pagos"])


@router.post("/iniciar", response_model=PagoIniciarRespuesta, status_code=status.HTTP_201_CREATED)
def iniciar_pago(
    datos: PagoIniciarRequest, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> PagoIniciarRespuesta:
    pago, url = cu_pagar_pasarela.iniciar(db, usuario.id, datos)
    return PagoIniciarRespuesta(pago=_pago_respuesta(db, pago), url_redireccion=url)


@router.post("/caja", response_model=PagoCajaRespuesta, status_code=status.HTTP_201_CREATED, dependencies=[gestionar_requerido])
def pagar_en_caja(
    datos: PagoCajaRequest, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> PagoCajaRespuesta:
    pago, cambio = cu_procesar_caja.ejecutar(db, usuario.id, datos)
    return PagoCajaRespuesta(pago=_pago_respuesta(db, pago), cambio=cambio)


@router.get("/{pago_id}/estado", response_model=PagoRespuesta)
def obtener_estado(pago_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> PagoRespuesta:
    pago = cu_confirmar_rechazar.obtener_estado(db, usuario.id, pago_id)
    return _pago_respuesta(db, pago)


@router.post("/venta/{venta_id}/cancelar")
def cancelar_compra(venta_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    cu_pagar_pasarela.cancelar(db, usuario.id, venta_id)
    return {"venta_id": venta_id, "estado": "anulada"}


@router.post("/{pago_id}/anular", response_model=PagoRespuesta, dependencies=[gestionar_requerido])
def anular_pago(pago_id: int, usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> PagoRespuesta:
    pago = cu_confirmar_rechazar.anular(db, usuario.id, pago_id)
    return _pago_respuesta(db, pago)


# Pantalla pública de la pasarela simulada "qr_online" (ver
# pagos/pasarela.py::QrOnlineGateway). Sin autenticación JWT: la abre un
# WebView/navegador que no tiene por qué estar logueado en la app -- el
# id_transaccion (128 bits) es el único requisito, mismo modelo de
# confianza que un link de pago.
@router.get("/qr/{id_transaccion}", response_class=HTMLResponse)
def pantalla_qr(id_transaccion: str, db: Session = Depends(get_db)) -> HTMLResponse:
    html = cu_confirmar_rechazar.renderizar_pantalla_qr(db, id_transaccion)
    return HTMLResponse(content=html)


@router.post("/qr/{id_transaccion}/confirmar", response_model=PagoRespuesta)
def confirmar_qr(id_transaccion: str, db: Session = Depends(get_db)) -> PagoRespuesta:
    pago = cu_confirmar_rechazar.confirmar_pago_qr(db, id_transaccion)
    return _pago_respuesta(db, pago)


# Sin autenticación JWT: lo llama el servidor de la pasarela, no una
# persona logueada. La seguridad acá es la verificación de firma HMAC
# (CU-31.procesar_webhook -> pasarela.verificar_firma), no un permiso.
@router.post("/webhook/{pasarela}", response_model=PagoRespuesta)
async def recibir_webhook(
    pasarela: str,
    request: Request,
    db: Session = Depends(get_db),
    x_signature: str | None = Header(default=None),
) -> PagoRespuesta:
    payload_crudo = await request.body()
    pago = cu_confirmar_rechazar.procesar_webhook(db, pasarela, payload_crudo, x_signature)
    return _pago_respuesta(db, pago)


# Protegida por token de servicio, igual que /tareas/expirar-reservas. Además
# la corre sola la tarea periódica de app/main.py (lifespan).
# expirar_ventas_pendientes no es un caso de uso del catálogo (no tiene
# actor humano): vive en pagos/politicas.py.
tareas_router = APIRouter(prefix="/api/v1/tareas", tags=["tareas"], dependencies=[Depends(require_service_token)])


@tareas_router.post("/expirar-ventas-pendientes")
def expirar_ventas_pendientes_endpoint(db: Session = Depends(get_db)) -> dict:
    return expirar_ventas_pendientes(db)


routers = [router, tareas_router]
