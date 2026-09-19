from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import ParametrosPeriodo, periodo_reportes
from app.core.security import get_current_user, require_permission
from app.reportes.casos_uso.cu33_consultar_reportes_ventas_inventario import ConsultarReportesVentasInventario
from app.reportes.casos_uso.cu34_visualizar_dashboard_indicadores import VisualizarDashboardIndicadores
from app.reportes.schemas import DashboardRespuesta, ReporteInventarioRespuesta, ReporteReservasRespuesta, ReporteVentasRespuesta

PERMISO_VER = "reportes.ver"
ver_requerido = Depends(require_permission(PERMISO_VER))

cu_consultar_reportes = ConsultarReportesVentasInventario()
cu_dashboard = VisualizarDashboardIndicadores()

router = APIRouter(prefix="/api/v1/reportes", tags=["reportes"], dependencies=[ver_requerido])


@router.get("/ventas", response_model=ReporteVentasRespuesta)
def reporte_ventas(
    periodo: ParametrosPeriodo = Depends(periodo_reportes),
    sucursal_id: int | None = Query(default=None),
    categoria_id: int | None = Query(default=None),
    canal: str | None = Query(default=None),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReporteVentasRespuesta:
    return cu_consultar_reportes.ventas(db, usuario.id, periodo, sucursal_id, categoria_id, canal)


@router.get("/inventario", response_model=ReporteInventarioRespuesta)
def reporte_inventario(
    sucursal_id: int | None = Query(default=None), usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ReporteInventarioRespuesta:
    return cu_consultar_reportes.inventario(db, usuario.id, sucursal_id)


@router.get("/reservas", response_model=ReporteReservasRespuesta)
def reporte_reservas(
    periodo: ParametrosPeriodo = Depends(periodo_reportes),
    sucursal_id: int | None = Query(default=None),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReporteReservasRespuesta:
    return cu_consultar_reportes.reservas(db, usuario.id, periodo, sucursal_id)


@router.get("/dashboard", response_model=DashboardRespuesta)
def reporte_dashboard(
    periodo: ParametrosPeriodo = Depends(periodo_reportes),
    sucursal_id: int | None = Query(default=None),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DashboardRespuesta:
    return cu_dashboard.ejecutar(db, usuario.id, periodo, sucursal_id)


routers = [router]
