from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import ParametrosPeriodo, periodo_reportes
from app.core.permisos import PERMISO_REPORTES_VER
from app.core.planes import FUNC_ANALITICA_ML, FUNC_REPORTES_CONVENCIONALES, FUNC_REPORTES_IA, exigir_funcionalidad
from app.core.rate_limit import limiter
from app.core.security import get_current_user, get_current_user_opcional, require_permission
from app.inteligencia.casos_uso.cu20_recomendar_productos import RecomendarProductos
from app.inteligencia.casos_uso.cu21_buscar_prendas_por_voz import BuscarComandoVoz
from app.inteligencia.casos_uso.cu22_consultar_reportes_indicadores import (
    ConsultarReportesVentasInventario,
    ConsultarResumenInicio,
    ExportarReportesVentasInventario,
    VisualizarDashboardIndicadores,
)
from app.inteligencia.exportacion import ArchivoExportado
from app.core.auditoria import ContextoAuditoria, obtener_contexto_auditoria
from app.inteligencia.casos_uso.cu23_generar_reportes_con_ia import (
    ConsultarCatalogoReportes,
    EjecutarReporteGenerativo,
    ExportarReporteGenerativo,
    GenerarReporteComandoVoz,
    InterpretarSolicitudReporte,
)
from app.inteligencia.casos_uso.cu24_analizar_con_machine_learning import ConsultarAnaliticaML
from app.inteligencia.politicas import registrar_evento
from app.inteligencia.schemas import (
    AnomaliasRespuesta,
    DashboardRespuesta,
    ResumenInicioRespuesta,
    DemandaRespuesta,
    EntrenarRequest,
    EntrenarRespuesta,
    EstadoAnalitica,
    EventoCrear,
    ExportarReporteRequest,
    FormatoExportacion,
    PanelAnalitico,
    RecomendacionesRespuesta,
    ReporteGenerativoRequest,
    ReporteGenerativoRespuesta,
    ReporteInventarioRespuesta,
    ReporteReservasRespuesta,
    ReporteVentasRespuesta,
    ReporteVozRequest,
    ReporteVozRespuesta,
    ReposicionRespuesta,
    SegmentosRespuesta,
    VozRequest,
    VozRespuesta,
)

# ---- Inteligencia ----

cu_recomendar_productos = RecomendarProductos()
cu_buscar_voz = BuscarComandoVoz()
cu_reporte_voz = GenerarReporteComandoVoz()

inteligencia_router = APIRouter(prefix="/api/v1/ia", tags=["inteligencia"])


@inteligencia_router.post("/voz", response_model=VozRespuesta)
@limiter.limit("15/minute")
def buscar_por_voz(
    request: Request,
    datos: VozRequest,
    usuario=Depends(get_current_user_opcional),
    db: Session = Depends(get_db),
) -> VozRespuesta:
    return cu_buscar_voz.ejecutar(db, datos.texto, usuario)


@inteligencia_router.post("/recomendaciones", response_model=RecomendacionesRespuesta)
@limiter.limit("20/minute")
def obtener_recomendaciones(
    request: Request,
    excluir_producto_id: int | None = None,
    usuario=Depends(get_current_user_opcional),
    db: Session = Depends(get_db),
) -> RecomendacionesRespuesta:
    return cu_recomendar_productos.ejecutar(db, usuario, excluir_producto_id)


@inteligencia_router.post("/eventos", status_code=status.HTTP_201_CREATED)
@limiter.limit("60/minute")
def registrar_evento_endpoint(
    request: Request,
    datos: EventoCrear,
    usuario=Depends(get_current_user_opcional),
    db: Session = Depends(get_db),
) -> dict:
    registrar_evento(db, datos, usuario)
    return {"registrado": True}


@inteligencia_router.post(
    "/reporte-voz",
    response_model=ReporteVozRespuesta,
    dependencies=[
        Depends(exigir_funcionalidad(FUNC_REPORTES_IA)),  # antes del permiso: orden de errores de 4.6
        Depends(require_permission(PERMISO_REPORTES_VER)),
    ],
)
@limiter.limit("15/minute")
def generar_reporte_por_voz(
    request: Request, datos: ReporteVozRequest, usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ReporteVozRespuesta:
    return cu_reporte_voz.ejecutar(db, usuario.id, datos.texto)


_routers_inteligencia = [inteligencia_router]


# ---- Reportes ----

ver_requerido = Depends(require_permission(PERMISO_REPORTES_VER))

cu_consultar_reportes = ConsultarReportesVentasInventario()
cu_dashboard = VisualizarDashboardIndicadores()

reportes_router = APIRouter(
    prefix="/api/v1/reportes",
    tags=["reportes"],
    dependencies=[Depends(exigir_funcionalidad(FUNC_REPORTES_CONVENCIONALES)), ver_requerido],
)


@reportes_router.get("/ventas", response_model=ReporteVentasRespuesta)
def reporte_ventas(
    periodo: ParametrosPeriodo = Depends(periodo_reportes),
    sucursal_id: int | None = Query(default=None),
    categoria_id: int | None = Query(default=None),
    canal: str | None = Query(default=None),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReporteVentasRespuesta:
    return cu_consultar_reportes.ventas(db, usuario.id, periodo, sucursal_id, categoria_id, canal)


@reportes_router.get("/inventario", response_model=ReporteInventarioRespuesta)
def reporte_inventario(
    sucursal_id: int | None = Query(default=None), usuario=Depends(get_current_user), db: Session = Depends(get_db)
) -> ReporteInventarioRespuesta:
    return cu_consultar_reportes.inventario(db, usuario.id, sucursal_id)


@reportes_router.get("/reservas", response_model=ReporteReservasRespuesta)
def reporte_reservas(
    periodo: ParametrosPeriodo = Depends(periodo_reportes),
    sucursal_id: int | None = Query(default=None),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReporteReservasRespuesta:
    return cu_consultar_reportes.reservas(db, usuario.id, periodo, sucursal_id)


@reportes_router.get("/dashboard", response_model=DashboardRespuesta)
def reporte_dashboard(
    periodo: ParametrosPeriodo = Depends(periodo_reportes),
    sucursal_id: int | None = Query(default=None),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DashboardRespuesta:
    return cu_dashboard.ejecutar(db, usuario.id, periodo, sucursal_id)


# Descarga en Excel o PDF de los mismos reportes (E10, paso 8). Mismo plan (reportes_convencionales:
# ambos planes) y mismo permiso que las rutas JSON de arriba.
cu_exportar_convencionales = ExportarReportesVentasInventario()
FormatoDescarga = Annotated[FormatoExportacion, Query(description="xlsx o pdf")]


def _descarga(archivo: ArchivoExportado) -> Response:
    """La respuesta de un archivo exportado. El nombre solo lleva ASCII (tipo de reporte, código de
    la empresa, fecha y hora); `Content-Disposition` lo expone CORS (app/main.py)."""
    return Response(
        content=archivo.contenido,
        media_type=archivo.tipo_mime,
        headers={
            "Content-Disposition": f'attachment; filename="{archivo.nombre_archivo}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@reportes_router.get("/ventas/exportar", response_class=Response)
@limiter.limit("10/minute")
def exportar_reporte_ventas(
    request: Request,
    formato: FormatoDescarga,
    incluir_grafico: bool = True,
    periodo: ParametrosPeriodo = Depends(periodo_reportes),
    sucursal_id: int | None = Query(default=None),
    categoria_id: int | None = Query(default=None),
    canal: str | None = Query(default=None),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> Response:
    return _descarga(
        cu_exportar_convencionales.ventas(
            db, usuario.id, periodo, sucursal_id, categoria_id, canal, formato, incluir_grafico, contexto
        )
    )


@reportes_router.get("/inventario/exportar", response_class=Response)
@limiter.limit("10/minute")
def exportar_reporte_inventario(
    request: Request,
    formato: FormatoDescarga,
    incluir_grafico: bool = True,
    sucursal_id: int | None = Query(default=None),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> Response:
    return _descarga(
        cu_exportar_convencionales.inventario(db, usuario.id, sucursal_id, formato, incluir_grafico, contexto)
    )


@reportes_router.get("/reservas/exportar", response_class=Response)
@limiter.limit("10/minute")
def exportar_reporte_reservas(
    request: Request,
    formato: FormatoDescarga,
    incluir_grafico: bool = True,
    periodo: ParametrosPeriodo = Depends(periodo_reportes),
    sucursal_id: int | None = Query(default=None),
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> Response:
    return _descarga(
        cu_exportar_convencionales.reservas(db, usuario.id, periodo, sucursal_id, formato, incluir_grafico, contexto)
    )


_routers_reportes = [reportes_router]


# ---- Pantalla de inicio del personal ----
# Sin `reportes.ver` ni plan de reportes: lo ve todo el personal. Cada sección se omite si falta su permiso o su plan
# (ver `ConsultarResumenInicio`), así que la ruta solo exige sesión y suscripción activa (como `/empleados/yo`).

cu_resumen_inicio = ConsultarResumenInicio()

inicio_router = APIRouter(prefix="/api/v1/inicio", tags=["inicio"])


@inicio_router.get("/resumen", response_model=ResumenInicioRespuesta)
def resumen_inicio(usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> ResumenInicioRespuesta:
    return cu_resumen_inicio.ejecutar(db, usuario.id)


_routers_inicio = [inicio_router]


# ---- Reportes generativos con IA (CU-23, E09) ----------------------------------------
# Orden de errores: 401, suscripción, plan (exigir_funcionalidad), permiso, y recién entonces las
# reglas de negocio, que responden 200 con un estado (incompleta, ambigua, invalida...).

cu_catalogo_reportes = ConsultarCatalogoReportes()
cu_interpretar_reporte = InterpretarSolicitudReporte()
cu_ejecutar_reporte = EjecutarReporteGenerativo()
cu_exportar_reporte = ExportarReporteGenerativo()

reportes_ia_router = APIRouter(
    prefix="/api/v1/reportes-ia",
    tags=["reportes-ia"],
    dependencies=[Depends(exigir_funcionalidad(FUNC_REPORTES_IA)), ver_requerido],
)


@reportes_ia_router.get("/catalogo")
def catalogo_reportes_ia(usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    return cu_catalogo_reportes.ejecutar(db, usuario.id)


@reportes_ia_router.post("/interpretar", response_model=ReporteGenerativoRespuesta)
@limiter.limit("15/minute")
def interpretar_reporte_ia(
    request: Request,
    datos: ReporteGenerativoRequest,
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReporteGenerativoRespuesta:
    return cu_interpretar_reporte.ejecutar(db, usuario.id, datos)


@reportes_ia_router.post("/ejecutar", response_model=ReporteGenerativoRespuesta)
@limiter.limit("15/minute")
def ejecutar_reporte_ia(
    request: Request,
    datos: ReporteGenerativoRequest,
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> ReporteGenerativoRespuesta:
    return cu_ejecutar_reporte.ejecutar(db, usuario.id, datos, contexto)


@reportes_ia_router.post(
    "/exportar",
    response_class=Response,
    responses={
        200: {"description": "El archivo (.xlsx o .pdf)", "content": {"application/octet-stream": {}}},
        422: {"description": "reporte_no_exportable: el estado del reporte no es ok (mensaje y sugerencias)"},
    },
)
@limiter.limit("10/minute")
def exportar_reporte_ia(
    request: Request,
    datos: ExportarReporteRequest,
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> Response:
    return _descarga(cu_exportar_reporte.ejecutar(db, usuario.id, datos, contexto))


_routers_reportes_ia = [reportes_ia_router]


# ---- Analítica con Machine Learning (CU-24, E12) -------------------------------------------------
# Solo el plan con `analitica_ml` (el Profesional) y solo alcance global (administrador de la empresa; lo comprueba el
# caso de uso). Orden de errores: 401, suscripción, plan, permiso y recién entonces las reglas de negocio. El
# `empresa_id` NUNCA se lee del cliente: la empresa es la del token.

cu_analitica = ConsultarAnaliticaML()


def alcance_global_requerido(usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    """403 si el usuario tiene una sucursal asignada: la analítica es de toda la empresa (D28). Va como dependencia,
    después del plan y del permiso, para que corra ANTES de validar los parámetros (un encargado con `semanas=99`
    recibe 403, no 422). El caso de uso lo vuelve a comprobar por su cuenta."""
    cu_analitica.exigir_alcance_global(db, usuario.id)


analitica_router = APIRouter(
    prefix="/api/v1/analitica",
    tags=["analitica"],
    dependencies=[Depends(exigir_funcionalidad(FUNC_ANALITICA_ML)), ver_requerido, Depends(alcance_global_requerido)],
)


@analitica_router.get("/estado", response_model=EstadoAnalitica)
@limiter.limit("30/minute")
def analitica_estado(request: Request, usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> EstadoAnalitica:
    return cu_analitica.estado(db, usuario.id)


@analitica_router.post("/entrenar", response_model=EntrenarRespuesta)
@limiter.limit("3/minute")
def analitica_entrenar(
    request: Request,
    datos: EntrenarRequest | None = None,
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
    contexto: ContextoAuditoria = Depends(obtener_contexto_auditoria),
) -> EntrenarRespuesta:
    return cu_analitica.entrenar(db, usuario.id, datos.tipos if datos else None, contexto)


@analitica_router.get("/demanda", response_model=DemandaRespuesta)
@limiter.limit("30/minute")
def analitica_demanda(
    request: Request,
    semanas: Annotated[int, Query(ge=1, le=12)] = 4,
    categoria_id: Annotated[int | None, Query(ge=1)] = None,
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DemandaRespuesta:
    return cu_analitica.demanda(db, usuario.id, semanas, categoria_id)


@analitica_router.get("/segmentos", response_model=SegmentosRespuesta)
@limiter.limit("30/minute")
def analitica_segmentos(request: Request, usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> SegmentosRespuesta:
    return cu_analitica.segmentos(db, usuario.id)


@analitica_router.get("/anomalias", response_model=AnomaliasRespuesta)
@limiter.limit("30/minute")
def analitica_anomalias(
    request: Request,
    dias: Annotated[int, Query(ge=7, le=365)] = 90,
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnomaliasRespuesta:
    return cu_analitica.anomalias(db, usuario.id, dias)


@analitica_router.get("/reposicion", response_model=ReposicionRespuesta)
@limiter.limit("30/minute")
def analitica_reposicion(
    request: Request,
    semanas: Annotated[int, Query(ge=1, le=12)] = 4,
    usuario=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReposicionRespuesta:
    return cu_analitica.reposicion(db, usuario.id, semanas)


@analitica_router.get("/panel", response_model=PanelAnalitico)
@limiter.limit("30/minute")
def analitica_panel(request: Request, usuario=Depends(get_current_user), db: Session = Depends(get_db)) -> PanelAnalitico:
    return cu_analitica.panel(db, usuario.id)


_routers_analitica = [analitica_router]

# ---- /api/v1/public/{codigo} (tienda pública por empresa) --------------------------
# Los MISMOS handlers públicos de /ia (voz, recomendaciones, eventos) bajo el
# código de la tienda (D02, D10). La empresa la fija `contexto_empresa`
# (core/tenant.py) desde el código de la ruta; `_codigo_tienda` solo documenta el
# parámetro en OpenAPI. No se copian handlers: los `@limiter.limit` viajan con la
# función.


def _codigo_tienda(codigo: str) -> str:
    return codigo


publico_tienda_router = APIRouter(
    prefix="/api/v1/public/{codigo}", tags=["tienda-publica"], dependencies=[Depends(_codigo_tienda)]
)
publico_tienda_router.add_api_route(
    "/ia/voz", buscar_por_voz, methods=["POST"], response_model=VozRespuesta
)
publico_tienda_router.add_api_route(
    "/ia/recomendaciones", obtener_recomendaciones, methods=["POST"], response_model=RecomendacionesRespuesta
)
publico_tienda_router.add_api_route(
    "/ia/eventos", registrar_evento_endpoint, methods=["POST"], status_code=status.HTTP_201_CREATED
)


routers = (
    _routers_inteligencia
    + _routers_reportes
    + _routers_inicio
    + _routers_reportes_ia
    + _routers_analitica
    + [publico_tienda_router]
)
