from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.security import get_current_user, get_current_user_opcional, require_permission
from app.inteligencia.casos_uso.cu32_recomendar_productos import RecomendarProductos
from app.inteligencia.casos_uso.cu37_buscar_comando_voz import BuscarComandoVoz
from app.inteligencia.casos_uso.cu38_generar_reporte_comando_voz import GenerarReporteComandoVoz
from app.inteligencia.politicas import registrar_evento
from app.inteligencia.schemas import (
    EventoCrear,
    RecomendacionesRespuesta,
    ReporteVozRequest,
    ReporteVozRespuesta,
    VozRequest,
    VozRespuesta,
)

cu_recomendar_productos = RecomendarProductos()
cu_buscar_voz = BuscarComandoVoz()
cu_reporte_voz = GenerarReporteComandoVoz()

router = APIRouter(prefix="/api/v1/ia", tags=["inteligencia"])


@router.post("/voz", response_model=VozRespuesta)
@limiter.limit("15/minute")
def buscar_por_voz(
    request: Request,
    datos: VozRequest,
    usuario=Depends(get_current_user_opcional),
    db: Session = Depends(get_db),
) -> VozRespuesta:
    return cu_buscar_voz.ejecutar(db, datos.texto, usuario)


@router.post("/recomendaciones", response_model=RecomendacionesRespuesta)
@limiter.limit("20/minute")
def obtener_recomendaciones(
    request: Request,
    excluir_producto_id: int | None = None,
    usuario=Depends(get_current_user_opcional),
    db: Session = Depends(get_db),
) -> RecomendacionesRespuesta:
    return cu_recomendar_productos.ejecutar(db, usuario, excluir_producto_id)


@router.post("/eventos", status_code=status.HTTP_201_CREATED)
@limiter.limit("60/minute")
def registrar_evento_endpoint(
    request: Request,
    datos: EventoCrear,
    usuario=Depends(get_current_user_opcional),
    db: Session = Depends(get_db),
) -> dict:
    registrar_evento(db, datos, usuario)
    return {"registrado": True}


@router.post(
    "/reporte-voz", response_model=ReporteVozRespuesta, dependencies=[Depends(require_permission("reportes.ver"))]
)
@limiter.limit("15/minute")
def generar_reporte_por_voz(
    request: Request, datos: ReporteVozRequest, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ReporteVozRespuesta:
    return cu_reporte_voz.ejecutar(db, usuario.id, datos.texto)


routers = [router]
