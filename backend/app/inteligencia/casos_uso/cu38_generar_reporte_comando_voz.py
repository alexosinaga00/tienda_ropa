"""CU-38 — Generar reporte por comando de voz

Actor: Administrador, Servicio de inteligencia artificial.
Precondición: sesión con el permiso reportes.ver.
Postcondición: se responde en lenguaje natural una pregunta sobre los
reportes del negocio.

Groq solo elige `tipo_reporte` (uno de 4 valores fijos) y filtros ya
conocidos (fechas, nombres) -- nunca genera SQL ni texto que se ejecute;
si falla o no valida, cae al dashboard con el período por defecto, nunca
a un error. Llama a los casos de uso CU-33 y CU-34 del paquete reportes,
que son de solo lectura.
"""

import datetime as dt

from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.core.deps import DIAS_PERIODO_POR_DEFECTO, ParametrosPeriodo
from app.inteligencia.groq_cliente import obtener_parser_reporte_voz
from app.inteligencia.schemas import TIPOS_REPORTE_VALIDOS, ReporteVozRespuesta
from app.organizacion import politicas as organizacion_politicas
from app.reportes.casos_uso.cu33_consultar_reportes_ventas_inventario import ConsultarReportesVentasInventario
from app.reportes.casos_uso.cu34_visualizar_dashboard_indicadores import VisualizarDashboardIndicadores


class GenerarReporteComandoVoz:
    def __init__(self) -> None:
        self._reportes = ConsultarReportesVentasInventario()
        self._dashboard = VisualizarDashboardIndicadores()

    def ejecutar(self, db: Session, usuario_id: int, texto: str) -> ReporteVozRespuesta:
        """POST /api/v1/ia/reporte-voz. Requiere `reportes.ver` (verificado
        en el router, no acá)."""
        filtros_voz = obtener_parser_reporte_voz().parsear(texto)

        tipo_reporte = "dashboard"
        if filtros_voz is not None and filtros_voz.tipo_reporte in TIPOS_REPORTE_VALIDOS:
            tipo_reporte = filtros_voz.tipo_reporte

        hasta = filtros_voz.hasta if filtros_voz and filtros_voz.hasta else dt.date.today()
        desde = (
            filtros_voz.desde
            if filtros_voz and filtros_voz.desde
            else hasta - dt.timedelta(days=DIAS_PERIODO_POR_DEFECTO)
        )
        if desde > hasta:
            # Groq mandó un rango invertido: se intercambia en vez de romper.
            desde, hasta = hasta, desde
        periodo = ParametrosPeriodo(desde=desde, hasta=hasta)

        sucursal_id = organizacion_politicas.resolver_sucursal_por_nombre(db, filtros_voz.sucursal) if filtros_voz else None
        # Un encargado solo puede consultar su sucursal: si dictó otra (o
        # ninguna), se usa la suya en vez de fallar -- este CU nunca termina
        # en error por lo que interpretó Groq.
        propia = organizacion_politicas.sucursal_asignada(db, usuario_id)
        if propia is not None:
            sucursal_id = propia
        categoria_id = catalogo_politicas.resolver_categoria_por_nombre(db, filtros_voz.categoria) if filtros_voz else None
        canal = filtros_voz.canal if filtros_voz and filtros_voz.canal in {"digital", "presencial"} else None

        if tipo_reporte == "ventas":
            resultado = self._reportes.ventas(db, usuario_id, periodo, sucursal_id, categoria_id, canal)
        elif tipo_reporte == "inventario":
            resultado = self._reportes.inventario(db, usuario_id, sucursal_id)
        elif tipo_reporte == "reservas":
            resultado = self._reportes.reservas(db, usuario_id, periodo, sucursal_id)
        else:
            resultado = self._dashboard.ejecutar(db, usuario_id, periodo, sucursal_id)

        filtros_aplicados = {
            "desde": str(periodo.desde),
            "hasta": str(periodo.hasta),
            "sucursal_id": sucursal_id,
            "categoria_id": categoria_id,
            "canal": canal,
        }
        return ReporteVozRespuesta(
            tipo_reporte=tipo_reporte,
            filtros_aplicados=filtros_aplicados,
            resultado=resultado.model_dump(mode="json"),
        )
