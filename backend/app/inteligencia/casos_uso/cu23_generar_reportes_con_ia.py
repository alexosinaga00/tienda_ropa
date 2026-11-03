"""CU-23 — Generar reportes con IA

Absorbe el antiguo CU-38 (Generar reporte por comando de voz).

Actor: Administrador, Servicio de inteligencia artificial.
Precondición: sesión con el permiso reportes.ver y un plan con reportes_ia.
Postcondición: se responde en lenguaje natural, o con un reporte de datos reales de la
empresa, la pregunta que el usuario escribió o dictó.

La IA nunca ve la base de datos ni genera SQL. Groq (o, si no responde, un intérprete de reglas
de palabras clave) solo devuelve un JSON con `tipo_reporte` y filtros; ese JSON se valida contra
el registro cerrado (`registro_reportes.py`), los nombres se resuelven contra la empresa del token
y los datos salen de las consultas parametrizadas de `comercial` y `catalogo`. Una solicitud
incompleta, ambigua, inválida o no soportada se responde con un estado y sugerencias, nunca con
datos inventados.

Clases de control:
- GenerarReporteComandoVoz: el reporte por voz de siempre (4 pestañas y un periodo).
  Llama a CU-22, que es de solo lectura.
- InterpretarSolicitudReporte: "entendí esto" sin ejecutar.
- EjecutarReporteGenerativo: interpreta, valida y ejecuta uno de los reportes del registro.
- ExportarReporteGenerativo: lo mismo, pero devuelve el reporte como archivo Excel o PDF (E10).
- ConsultarCatalogoReportes: los reportes que el plan de la empresa permite pedir.

Reportes inteligentes (E12): `prediccion_demanda`, `segmentacion_clientes` y `metricas_modelos` son reportes del
registro como los demás (misma validación, mismo estado, misma exportación), pero sus datos salen del Machine Learning de
la empresa por `ConsultarAnaliticaML` (CU-24); este archivo no toca modelos ni `ml/`. Exigen el plan con `analitica_ml` y
alcance global; sin modelo entrenado o con uno obsoleto el reporte responde "no_disponible" (HTTP 200, sin filas)."""

import datetime as dt
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.comercial import politicas as comercial_politicas
from app.core.auditoria import (
    ACCION_EJECUTAR,
    ACCION_EXPORTAR,
    ACCION_RECHAZAR,
    ENTIDAD_REPORTE_IA,
    ContextoAuditoria,
)
from app.core.config import get_settings
from app.core.deps import DIAS_PERIODO_POR_DEFECTO, ParametrosPeriodo
from app.core.exceptions import DomainError, ErrorFuncional
from app.core.planes import FUNCIONALIDADES, verificar_funcionalidad
from app.core.tiempo import ahora_bolivia, hoy_utc, resolver_periodo_relativo
from app.inteligencia import registro_reportes
from app.inteligencia.casos_uso.cu24_analizar_con_machine_learning import (
    MENSAJE_SIN_MODELO,
    TIPO_ANOMALIAS,
    TIPO_DEMANDA,
    TIPO_SEGMENTOS,
    ConsultarAnaliticaML,
)
from app.inteligencia.exportacion import MAX_FILAS, TIPO_MIME, ArchivoExportado, construir_archivo
from app.inteligencia.groq_cliente import obtener_interprete_reportes, obtener_parser_reporte_voz
from app.inteligencia.interprete_reglas import InterpreteReportesReglas
from app.inteligencia.politicas import (
    a_decimal,
    a_numero,
    agrupar_serie,
    armar_resumen,
    calcular_participacion,
    documento_desde_reporte,
    etiqueta_periodo,
    formato_numero,
    interpretar_anomalias,
    interpretar_demanda,
    interpretar_metricas_demanda,
    interpretar_reposicion,
    redactar_narrativa_reporte,
    redactar_respuesta_reporte,
    solicitud_desde_resuelta,
    ticket_promedio,
)
from app.inteligencia.schemas import (
    TIPOS_REPORTE_VALIDOS,
    ExportarReporteRequest,
    PeriodoResuelto,
    PeriodoSolicitado,
    ReferenciaResuelta,
    ReporteEjecutado,
    ReporteGenerativoRequest,
    ReporteGenerativoRespuesta,
    ReporteVozRespuesta,
    SolicitudReporte,
    SolicitudResuelta,
)
from app.inteligencia.registro_reportes import ReporteNoDisponible
from app.plataforma import politicas as plataforma_politicas
from app.inteligencia.casos_uso.cu22_consultar_reportes_indicadores import (
    ConsultarReportesVentasInventario,
    VisualizarDashboardIndicadores,
)

logger = logging.getLogger(__name__)

MAX_DIAS_PERIODO = 366
MAX_SUGERENCIAS = 8


def _acotar_periodo(desde: dt.date, hasta: dt.date, hoy: dt.date) -> tuple[dt.date, dt.date]:
    """Las fechas que devuelve el modelo no son confiables: `hasta` futuro se
    ajusta a hoy, y un rango que queda vacío o de más de 366 días se descarta
    a favor del período por defecto."""
    hasta = min(hasta, hoy)
    if desde > hasta or (hasta - desde).days > MAX_DIAS_PERIODO:
        return hasta - dt.timedelta(days=DIAS_PERIODO_POR_DEFECTO), hasta
    return desde, hasta


class GenerarReporteComandoVoz:
    def __init__(self) -> None:
        self._reportes = ConsultarReportesVentasInventario()
        self._dashboard = VisualizarDashboardIndicadores()

    def ejecutar(self, db: Session, usuario_id: int, texto: str) -> ReporteVozRespuesta:
        """POST /api/v1/ia/reporte-voz. Requiere `reportes.ver` (verificado
        en el router, no acá)."""
        filtros_voz = obtener_parser_reporte_voz().parsear(texto)

        # Sin interpretación válida (Groq falló, sin API key o tipo desconocido)
        # se muestra el dashboard y la respuesta lo avisa.
        entendida = filtros_voz is not None and filtros_voz.tipo_reporte in TIPOS_REPORTE_VALIDOS
        tipo_reporte = filtros_voz.tipo_reporte if entendida else "dashboard"

        hasta = filtros_voz.hasta if filtros_voz and filtros_voz.hasta else hoy_utc()
        desde = (
            filtros_voz.desde
            if filtros_voz and filtros_voz.desde
            else hasta - dt.timedelta(days=DIAS_PERIODO_POR_DEFECTO)
        )
        if desde > hasta:
            # Groq mandó un rango invertido: se intercambia en vez de romper.
            desde, hasta = hasta, desde
        desde, hasta = _acotar_periodo(desde, hasta, hoy_utc())
        periodo = ParametrosPeriodo(desde=desde, hasta=hasta)

        sucursal_id = plataforma_politicas.resolver_sucursal_por_nombre(db, filtros_voz.sucursal) if filtros_voz else None
        # Un encargado solo puede consultar su sucursal: si dictó otra (o
        # ninguna), se usa la suya en vez de fallar -- este CU nunca termina
        # en error por lo que interpretó Groq.
        propia = plataforma_politicas.sucursal_asignada(db, usuario_id)
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
        # Nombres para la frase: el de la sucursal aplicada (puede ser la propia
        # del encargado, no la que dictó) y la categoría tal como se dictó, solo
        # si se resolvió a un id.
        sucursal_nombre = (
            plataforma_politicas.obtener_sucursal(db, sucursal_id).nombre if sucursal_id is not None else None
        )
        categoria_nombre = filtros_voz.categoria if filtros_voz and categoria_id is not None else None
        respuesta = redactar_respuesta_reporte(
            tipo_reporte=tipo_reporte,
            entendida=entendida,
            desde=periodo.desde,
            hasta=periodo.hasta,
            sucursal=sucursal_nombre,
            categoria=categoria_nombre,
            canal=canal,
            resultado=resultado,
        )
        return ReporteVozRespuesta(
            respuesta=respuesta,
            tipo_reporte=tipo_reporte,
            filtros_aplicados=filtros_aplicados,
            resultado=resultado.model_dump(mode="json"),
        )


# ---- Reportes generativos (E09) ---------------------------------------------------------
# Los ejecutores de abajo solo arman las filas con las consultas de `comercial` y `catalogo`
# (aquí no hay SQL). Se conectan al registro una sola vez, al importar este módulo.


@dataclass
class ContextoEjecucion:
    """Lo que ya se validó y resolvió para ejecutar un reporte. Las listas de ids ya son de la
    empresa de la sesión; `None` = sin ese filtro."""

    periodo: ParametrosPeriodo | None
    sucursal_ids: list[int] | None
    categoria_ids: list[int] | None
    producto_ids: list[int] | None
    canal: str | None
    agrupacion: str | None
    orden: str
    limite: int | None
    horizonte_semanas: int | None = None  # solo los reportes de analítica (E12)


@dataclass
class ResultadoEjecucion:
    filas: list[dict]
    resumen: dict = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)
    # Resumen en español ya redactado (los reportes de analítica lo traen de CU-24); sin él se usa la plantilla.
    narrativa: str | None = None


def _ordenado(filas: list[dict], clave: str, orden: str) -> list[dict]:
    return sorted(filas, key=lambda f: f[clave], reverse=orden != "menor_a_mayor")


def _ejecutar_ventas_por_sucursal(db: Session, usuario_id: int, ctx: ContextoEjecucion) -> ResultadoEjecucion:
    filas = comercial_politicas.reporte_ventas_por_sucursal(
        db, ctx.periodo, canal=ctx.canal, sucursal_ids=ctx.sucursal_ids, categoria_ids=ctx.categoria_ids
    )
    montos = [a_decimal(f["total_ventas"]) for f in filas]
    participacion = calcular_participacion(montos)
    salida = [
        {
            "sucursal": f["sucursal"],
            "transacciones": int(f["transacciones"]),
            "total_ventas": a_numero(monto),
            "ticket_promedio": a_numero(ticket_promedio(monto, int(f["transacciones"]))),
            "participacion": porcentaje,
        }
        for f, monto, porcentaje in zip(filas, montos, participacion)
    ]
    salida = _ordenado(salida, "total_ventas", "mayor_a_menor")
    return ResultadoEjecucion(salida, armar_resumen(salida, ["total_ventas", "transacciones"]))


def _ejecutar_productos_mas_vendidos(db: Session, usuario_id: int, ctx: ContextoEjecucion) -> ResultadoEjecucion:
    ascendente = ctx.orden == "menor_a_mayor"
    filas = comercial_politicas.reporte_ventas_top_productos(
        db,
        ctx.periodo,
        canal=ctx.canal,
        limite=ctx.limite,
        sucursal_ids=ctx.sucursal_ids,
        categoria_ids=ctx.categoria_ids,
        ascendente=ascendente,
    )
    del_periodo = comercial_politicas.reporte_ventas_resumen(
        db, ctx.periodo, canal=ctx.canal, sucursal_ids=ctx.sucursal_ids, categoria_ids=ctx.categoria_ids
    )
    total_periodo = a_decimal(del_periodo["total_ventas"])
    montos = [a_decimal(f["total_vendido"]) for f in filas]
    participacion = calcular_participacion(montos, total_periodo)
    salida = [
        {
            "posicion": posicion,
            "producto": f["producto"],
            "unidades": int(f["cantidad_vendida"]),
            "total_vendido": a_numero(monto),
            "participacion": porcentaje,
        }
        for posicion, (f, monto, porcentaje) in enumerate(zip(filas, montos, participacion), start=1)
    ]
    avisos = ["Solo se consideran los productos con ventas en el periodo."] if ascendente else []
    return ResultadoEjecucion(salida, armar_resumen(salida, ["unidades", "total_vendido"]), avisos)


def _serie(db: Session, ctx: ContextoEjecucion, desglose: tuple[str, ...] = ()) -> list[dict]:
    return comercial_politicas.reporte_ventas_serie_diaria(
        db,
        ctx.periodo,
        sucursal_ids=ctx.sucursal_ids,
        categoria_ids=ctx.categoria_ids,
        producto_ids=ctx.producto_ids,
        canal=ctx.canal,
        desglose=desglose,
    )


def _ejecutar_ventas_por_periodo(db: Session, usuario_id: int, ctx: ContextoEjecucion) -> ResultadoEjecucion:
    agrupadas = agrupar_serie(_serie(db, ctx), ctx.agrupacion, ctx.periodo.desde, ctx.periodo.hasta)
    salida = [
        {
            "periodo": f["periodo"],
            "desde": f["desde"].isoformat(),
            "transacciones": f["transacciones"],
            "unidades": f["unidades"],
            "total_ventas": a_numero(f["total_ventas"]),
        }
        for f in agrupadas
    ]
    return ResultadoEjecucion(salida, armar_resumen(salida, ["total_ventas", "transacciones", "unidades"]))


def _ejecutar_comparacion_sucursales(db: Session, usuario_id: int, ctx: ContextoEjecucion) -> ResultadoEjecucion:
    agrupadas = agrupar_serie(
        _serie(db, ctx, ("sucursal",)), ctx.agrupacion, ctx.periodo.desde, ctx.periodo.hasta, serie="sucursal"
    )
    anterior: dict[str, Decimal] = {}
    salida = []
    for f in agrupadas:  # ya vienen por periodo y, dentro de cada uno, por sucursal
        previo = anterior.get(f["sucursal"])
        variacion = None
        if previo is not None and previo > 0:
            variacion = float(((f["total_ventas"] - previo) * 100 / previo).quantize(Decimal("0.1")))
        anterior[f["sucursal"]] = f["total_ventas"]
        salida.append(
            {
                "periodo": f["periodo"],
                "sucursal": f["sucursal"],
                "total_ventas": a_numero(f["total_ventas"]),
                "transacciones": f["transacciones"],
                "variacion_pct": variacion,
            }
        )
    return ResultadoEjecucion(salida, armar_resumen(salida, ["total_ventas", "transacciones"]))


def _ejecutar_productos_menor_existencia(db: Session, usuario_id: int, ctx: ContextoEjecucion) -> ResultadoEjecucion:
    filas = catalogo_politicas.reporte_existencias_por_producto(
        db, ctx.sucursal_ids, ctx.categoria_ids, ctx.producto_ids, ctx.limite
    )
    salida = [
        {
            "producto": f["producto"],
            "categoria": f["categoria"],
            "disponible": f["disponible"],
            "stock_minimo": f["stock_minimo"],
            "bajo_minimo": f["bajo_minimo"],
        }
        for f in filas
    ]
    resumen = {
        "disponible": sum(f["disponible"] for f in salida),
        "productos_bajo_minimo": sum(1 for f in salida if f["bajo_minimo"]),
    }
    return ResultadoEjecucion(salida, resumen)


def _ejecutar_ingresos_por_categoria(db: Session, usuario_id: int, ctx: ContextoEjecucion) -> ResultadoEjecucion:
    filas = comercial_politicas.reporte_ventas_por_categoria(
        db, ctx.periodo, sucursal_ids=ctx.sucursal_ids, canal=ctx.canal
    )
    montos = [f["total_vendido"] for f in filas]  # ya son Decimal de 2 decimales
    participacion = calcular_participacion(montos)
    todas = [
        {
            "categoria": f["categoria"],
            "unidades": f["unidades"],
            "total_vendido": a_numero(f["total_vendido"]),
            "margen_bruto": a_numero(f["margen_bruto"]),
            "participacion": porcentaje,
        }
        for f, porcentaje in zip(filas, participacion)
    ]
    mostradas = _ordenado(todas, "total_vendido", ctx.orden)[: ctx.limite]
    return ResultadoEjecucion(mostradas, armar_resumen(mostradas, ["unidades", "total_vendido", "margen_bruto"]))


registro_reportes.conectar_ejecutor("ventas_por_sucursal", _ejecutar_ventas_por_sucursal)
registro_reportes.conectar_ejecutor("productos_mas_vendidos", _ejecutar_productos_mas_vendidos)
registro_reportes.conectar_ejecutor("ventas_por_periodo", _ejecutar_ventas_por_periodo)
registro_reportes.conectar_ejecutor("comparacion_sucursales", _ejecutar_comparacion_sucursales)
registro_reportes.conectar_ejecutor("productos_menor_existencia", _ejecutar_productos_menor_existencia)
registro_reportes.conectar_ejecutor("ingresos_por_categoria", _ejecutar_ingresos_por_categoria)


# ---- Reportes inteligentes (E12): los datos salen de ConsultarAnaliticaML --------------------------------------------
# Aquí no hay SQL ni acceso a los modelos: se llama a la consulta del CU-24 (que exige suscripción, plan y alcance global
# y carga el modelo vigente de la empresa de la sesión) y se reacomodan sus cifras en filas. Las cifras son las mismas que
# devuelven las rutas de `/api/v1/analitica`.

SUGERENCIA_ENTRENAR = "Pídele a un administrador que entrene el modelo en Analítica."
SUGERENCIA_REENTRENAR = "Pídele a un administrador que reentrene el modelo en Analítica."


def _con_modelo(consulta):
    """Corre una consulta de `ConsultarAnaliticaML`. Sin modelo entrenado o con uno obsoleto el reporte no se puede
    producir: se lanza `ReporteNoDisponible` (estado "no_disponible"), nunca se rellena con cifras inventadas."""
    try:
        return consulta()
    except ErrorFuncional as error:
        if error.codigo == "modelo_no_entrenado":
            raise ReporteNoDisponible(error.mensaje, [SUGERENCIA_ENTRENAR]) from error
        if error.codigo == "modelo_obsoleto":
            raise ReporteNoDisponible(error.mensaje, [SUGERENCIA_REENTRENAR]) from error
        raise


def _ejecutar_prediccion_demanda(db: Session, usuario_id: int, ctx: ContextoEjecucion) -> ResultadoEjecucion:
    semanas = ctx.horizonte_semanas or registro_reportes.HORIZONTE_POR_DEFECTO
    respuesta = _con_modelo(lambda: ConsultarAnaliticaML().demanda(db, usuario_id, semanas))
    pedidas = None if ctx.categoria_ids is None else set(ctx.categoria_ids)
    elegidas = [c for c in respuesta.categorias if pedidas is None or c.categoria_id in pedidas]
    avisos = list(respuesta.avisos)
    if pedidas is not None:
        if not elegidas:
            raise ReporteNoDisponible(
                "El modelo no tiene predicción para las categorías que pediste: no tenían ventas suficientes cuando se entrenó.",
                ["Pide otra categoría o la predicción de toda la empresa."],
            )
        faltan = pedidas - {c.categoria_id for c in elegidas}
        if faltan:
            avisos.append(
                f"{len(faltan)} de las categorías que pediste no están en el modelo (no tenían ventas suficientes "
                "cuando se entrenó) y no aparecen."
            )
    avisos.append("El mínimo y el máximo son un rango estimado (± el error típico del modelo), no un intervalo de confianza.")
    filas = [
        {
            "categoria": c.categoria,
            "semana": p.etiqueta,
            "unidades_predichas": int(p.valor),
            "minimo": int(p.minimo),
            "maximo": int(p.maximo),
        }
        for c in elegidas
        for p in c.prediccion
    ]
    resumen = {**armar_resumen(filas, ["unidades_predichas"]), "horizonte_semanas": semanas, "categorias": len(elegidas)}
    narrativa = " ".join(
        interpretar_demanda(
            [
                {"categoria": c.categoria, "total_predicho": c.total_predicho, "variacion_pct": c.variacion_pct_vs_ultimas_semanas}
                for c in elegidas
            ],
            semanas,
        )
    )
    return ResultadoEjecucion(filas, resumen, avisos, narrativa or None)


def _ejecutar_segmentacion_clientes(db: Session, usuario_id: int, ctx: ContextoEjecucion) -> ResultadoEjecucion:
    respuesta = _con_modelo(lambda: ConsultarAnaliticaML().segmentos(db, usuario_id))
    filas = [
        {
            "segmento": s.nombre,
            "clientes": s.clientes,
            "porcentaje_clientes": s.porcentaje_clientes,
            "recencia_media_dias": s.recencia_media_dias,
            "frecuencia_media": s.frecuencia_media,
            "monto_medio": s.monto_medio,
            "porcentaje_monto": s.porcentaje_monto,
        }
        for s in respuesta.segmentos
    ]
    resumen = {"clientes": respuesta.clientes_segmentados, "segmentos": len(filas)}
    return ResultadoEjecucion(filas, resumen, list(respuesta.avisos), " ".join(respuesta.interpretacion) or None)


def _ejecutar_metricas_modelos(db: Session, usuario_id: int, ctx: ContextoEjecucion) -> ResultadoEjecucion:
    """Lee las métricas guardadas con cada modelo (`estado`): no predice ni segmenta, solo informa. Un modelo sin
    entrenar u obsoleto no tumba el reporte si el otro sí sirve: su motivo va en los avisos."""
    # Solo los modelos que este reporte sabe presentar (otros tipos de modelo se suman aquí cuando tengan sus métricas).
    modelos = [m for m in ConsultarAnaliticaML().estado(db, usuario_id).modelos if m.tipo in (TIPO_DEMANDA, TIPO_SEGMENTOS, TIPO_ANOMALIAS)]
    usables = [m for m in modelos if m.entrenado and m.estado != "obsoleto"]
    if not usables:
        obsoleto = next((m for m in modelos if m.estado == "obsoleto"), None)
        if obsoleto is not None:
            raise ReporteNoDisponible(obsoleto.mensaje, [SUGERENCIA_REENTRENAR])
        raise ReporteNoDisponible(MENSAJE_SIN_MODELO, [SUGERENCIA_ENTRENAR])

    filas: list[dict] = []
    avisos: list[str] = []
    frases: list[str] = []
    for modelo in modelos:
        if modelo not in usables:
            avisos.append(f"{modelo.titulo}: {modelo.mensaje}")
            continue
        if modelo.estado == "desactualizado":
            avisos.append(f"{modelo.titulo}: {modelo.mensaje}")
        metricas = modelo.metricas
        if modelo.tipo == TIPO_DEMANDA:
            for clave, nombre in (("mae", "MAE"), ("rmse", "RMSE"), ("r2", "R2")):
                if metricas.get(clave) is not None:
                    filas.append(
                        {
                            "modelo": modelo.titulo,
                            "metrica": nombre,
                            "valor": metricas[clave],
                            "linea_base": metricas.get(f"{clave}_base"),
                        }
                    )
            frases.extend(interpretar_metricas_demanda(metricas))
        elif modelo.tipo == TIPO_SEGMENTOS and metricas.get("silhouette") is not None:
            filas.append({"modelo": modelo.titulo, "metrica": "Silhouette", "valor": metricas["silhouette"], "linea_base": None})
            frases.append(
                f"La separación de los segmentos de clientes (silhouette) es {formato_numero(metricas['silhouette'], 2)}; "
                "cuanto más cerca de 1, más diferenciados están los grupos."
            )
        elif modelo.tipo == TIPO_ANOMALIAS and metricas.get("pct_marcados") is not None:
            filas.append({"modelo": modelo.titulo, "metrica": "% de días marcados como inusuales", "valor": metricas["pct_marcados"], "linea_base": None})
            frases.append(
                f"El detector de días inusuales marca el {formato_numero(metricas['pct_marcados'], 1)}% de los días de cada sucursal; "
                "es un porcentaje que el propio detector fija, no una medida de acierto."
            )
    avisos.append("MAE y RMSE se miden en unidades por categoría y semana; la línea base es el promedio móvil de 4 semanas.")
    resumen = {"modelos": len(usables), "metricas": len(filas)}
    return ResultadoEjecucion(filas, resumen, avisos, " ".join(frases) or None)


def _ejecutar_anomalias_ventas(db: Session, usuario_id: int, ctx: ContextoEjecucion) -> ResultadoEjecucion:
    """Los días inusuales del periodo pedido (por defecto, los últimos 90 días). El modelo mira hasta ayer: el periodo
    solo recorta las fechas que se muestran."""
    periodo = ctx.periodo
    dias = ANOMALIAS_DIAS_POR_DEFECTO if periodo is None else min(max((hoy_utc() - periodo.desde).days, 7), 365)
    respuesta = _con_modelo(lambda: ConsultarAnaliticaML().anomalias(db, usuario_id, dias))
    elegidas = [a for a in respuesta.anomalias if periodo is None or periodo.desde <= a.fecha <= periodo.hasta]
    filas = [
        {
            "fecha": a.fecha.isoformat(),
            "sucursal": a.sucursal,
            "total_ventas": a.total_ventas,
            "esperado": a.esperado,
            "desviacion_pct": f"{a.desviacion_pct:+.1f}%",
            "severidad": a.severidad,
        }
        for a in elegidas
    ]
    avisos = list(respuesta.avisos)
    avisos.append("Un día inusual no es necesariamente un error: puede ser una promoción, un feriado o un cierre.")
    resumen = {"dias_inusuales": len(filas), "fuertes": sum(1 for a in elegidas if a.severidad == "fuerte")}
    frases = interpretar_anomalias(
        [{"sucursal": a.sucursal, "desviacion_pct": a.desviacion_pct, "severidad": a.severidad} for a in elegidas], dias
    )
    return ResultadoEjecucion(filas, resumen, avisos, " ".join(frases) or None)


def _ejecutar_reposicion_sugerida(db: Session, usuario_id: int, ctx: ContextoEjecucion) -> ResultadoEjecucion:
    semanas = ctx.horizonte_semanas or registro_reportes.HORIZONTE_POR_DEFECTO
    respuesta = _con_modelo(lambda: ConsultarAnaliticaML().reposicion(db, usuario_id, semanas))
    pedidas = None if ctx.categoria_ids is None else set(ctx.categoria_ids)
    elegidas = [i for i in respuesta.items if pedidas is None or i.categoria_id in pedidas]
    avisos = list(respuesta.avisos)
    if pedidas is not None:
        if not elegidas:
            raise ReporteNoDisponible(
                "El modelo no tiene demanda prevista para las categorías que pediste: no tenían ventas suficientes cuando se entrenó.",
                ["Pide otra categoría o la reposición de toda la empresa."],
            )
        faltan = pedidas - {i.categoria_id for i in elegidas}
        if faltan:
            avisos.append(f"{len(faltan)} de las categorías que pediste no están en el modelo y no aparecen.")
    avisos.append("La reposición es orientativa: no descuenta órdenes de compra en camino ni transferencias, y es por categoría.")
    filas = [
        {
            "categoria": i.categoria,
            "disponible": i.disponible,
            "demanda_semanal_promedio": i.demanda_semanal_promedio,
            "semanas_cobertura": i.semanas_cobertura,
            "estado": i.estado,
            "sugerencia_unidades": i.sugerencia_unidades,
        }
        for i in elegidas
    ]
    resumen = {"categorias": len(filas), "criticas": sum(1 for i in elegidas if i.estado == "critico"), "horizonte_semanas": semanas}
    frases = interpretar_reposicion(
        [
            {"categoria": i.categoria, "estado": i.estado, "agotado_en_semana": i.agotado_en_semana, "sugerencia_unidades": i.sugerencia_unidades}
            for i in elegidas
        ],
        semanas,
    )
    return ResultadoEjecucion(filas, resumen, avisos, " ".join(frases) or None)


ANOMALIAS_DIAS_POR_DEFECTO = 90
registro_reportes.conectar_ejecutor("anomalias_ventas", _ejecutar_anomalias_ventas)
registro_reportes.conectar_ejecutor("reposicion_sugerida", _ejecutar_reposicion_sugerida)
registro_reportes.conectar_ejecutor("prediccion_demanda", _ejecutar_prediccion_demanda)
registro_reportes.conectar_ejecutor("segmentacion_clientes", _ejecutar_segmentacion_clientes)
registro_reportes.conectar_ejecutor("metricas_modelos", _ejecutar_metricas_modelos)


# ---- Validación de la solicitud ---------------------------------------------------------


def _limpiar_texto(texto: str) -> str:
    """Quita caracteres de control y colapsa los espacios."""
    sin_control = "".join(" " if unicodedata.category(c)[0] == "C" else c for c in texto)
    return re.sub(r"\s+", " ", sin_control).strip()


def _funcionalidades_del_plan(db: Session) -> set[str]:
    plan = plataforma_politicas.situacion_de_la_empresa(db).plan
    if plan is None:
        return set()
    return {f for f in FUNCIONALIDADES if getattr(plan, f, False)}


def _con_alcance_global(db: Session, usuario_id: int) -> bool:
    """Si quien pide puede usar los reportes de toda la empresa (la misma regla de `exigir_alcance_global`)."""
    return plataforma_politicas.tiene_alcance_global(db, usuario_id)


def _ejemplos(funcionalidades: set[str], con_alcance_global: bool = True) -> list[str]:
    """Una frase de ejemplo por cada reporte disponible para el plan y para quien pide."""
    return [
        d.ejemplos[0] for d in registro_reportes.disponibles_para(funcionalidades, con_alcance_global) if d.ejemplos
    ]


def _respuesta(
    estado: str,
    mensaje: str,
    *,
    sugerencias: list[str] | None = None,
    avisos: list[str] | None = None,
    interprete: str | None = None,
) -> ReporteGenerativoRespuesta:
    return ReporteGenerativoRespuesta(
        estado=estado,
        mensaje=mensaje,
        sugerencias=sugerencias or [],
        avisos=avisos or [],
        interprete=interprete,
    )


@dataclass
class _Preparada:
    """Una solicitud que pasó todas las validaciones y ya está lista para ejecutarse."""

    definicion: registro_reportes.DefinicionReporte
    resuelta: SolicitudResuelta
    contexto: ContextoEjecucion
    avisos: list[str]
    interprete: str | None
    filtros_para_bitacora: dict


class _PreparadorSolicitud:
    """Pasos 1 a 9 del archivo de la etapa: de lo que escribió el usuario a una solicitud resuelta,
    o a una respuesta con estado (incompleta, ambigua, invalida, no_soportada)."""

    def preparar(
        self, db: Session, usuario_id: int, datos: ReporteGenerativoRequest
    ) -> _Preparada | ReporteGenerativoRespuesta:
        funcionalidades = _funcionalidades_del_plan(db)
        con_global = _con_alcance_global(db, usuario_id)
        avisos: list[str] = []
        interprete: str | None = None

        if datos.texto is not None:
            texto = _limpiar_texto(datos.texto)
            if not texto:
                return _respuesta(
                    "incompleta",
                    "Escribe qué reporte necesitas.",
                    sugerencias=_ejemplos(funcionalidades, con_global),
                )
            resultado, avisos_interprete = self._interpretar(db, texto, funcionalidades, con_global)
            avisos.extend(avisos_interprete)
            if resultado.solicitud is None:
                return _respuesta(
                    "incompleta",
                    "No pude entender qué reporte necesitas. Prueba con una de estas frases.",
                    sugerencias=_ejemplos(funcionalidades, con_global),
                    avisos=avisos,
                )
            solicitud = resultado.solicitud
            interprete = resultado.origen
        else:
            solicitud = datos.solicitud

        if solicitud.solicitud_multiple:
            avisos.append("Pediste varios reportes a la vez; muestro uno solo. Pide los demás por separado.")

        # 3. Tipo de reporte.
        codigo = (solicitud.tipo_reporte or "").strip().lower() or None
        if codigo is None:
            return _respuesta(
                "incompleta",
                "Dime qué reporte necesitas.",
                sugerencias=_ejemplos(funcionalidades, con_global),
                avisos=avisos,
                interprete=interprete,
            )
        definicion = registro_reportes.obtener(codigo)
        if definicion is None:
            titulos = ", ".join(d.titulo for d in registro_reportes.disponibles_para(funcionalidades, con_global))
            return _respuesta(
                "no_soportada",
                f"No puedo generar ese reporte. Puedo preparar: {titulos}. Las reservas y el resumen general "
                "están en Reportes convencionales.",
                sugerencias=_ejemplos(funcionalidades, con_global),
                avisos=avisos,
                interprete=interprete,
            )

        # 4. Plan: la funcionalidad del reporte (403 plan_no_incluye_funcionalidad si no la tiene).
        verificar_funcionalidad(db, definicion.funcionalidad_plan)
        # Los reportes de toda la empresa (analítica) no los ve quien tiene una sucursal asignada: el mismo 403 que las
        # rutas de /analitica, ahora también en /interpretar (no solo al ejecutar).
        if definicion.requiere_alcance_global:
            ConsultarAnaliticaML.exigir_alcance_global(db, usuario_id)

        # 5. Filtros: los que el reporte no usa se ignoran, pero se avisa.
        avisos.extend(self._avisar_filtros_ignorados(definicion, solicitud))

        # 6. Periodo.
        periodo, resuelto_periodo, avisos_periodo = None, None, []
        if "periodo" in definicion.filtros:
            periodo, resuelto_periodo, avisos_periodo, rechazo = self._resolver_periodo(definicion, solicitud)
            if rechazo is not None:
                return _respuesta(
                    "invalida",
                    rechazo,
                    sugerencias=["Prueba con «este mes», «los últimos 7 días» o «septiembre»."],
                    avisos=avisos,
                    interprete=interprete,
                )
            avisos.extend(avisos_periodo)

        # 9 (antes de resolver nombres: es más barato). Límite, agrupación y orden.
        rechazo, limite, agrupacion, orden = self._resolver_limites(definicion, solicitud)
        if rechazo is not None:
            return _respuesta("invalida", rechazo, avisos=avisos, interprete=interprete)
        rechazo, horizonte = self._resolver_horizonte(definicion, solicitud)
        if rechazo is not None:
            return _respuesta(
                "invalida",
                rechazo,
                sugerencias=["Prueba con «la próxima semana», «el próximo mes» o «las próximas 8 semanas»."],
                avisos=avisos,
                interprete=interprete,
            )
        if horizonte is not None and solicitud.horizonte_semanas is None:
            avisos.append(f"No indicaste cuántas semanas predecir; usé las próximas {horizonte}.")

        # 8. Alcance de sucursal: quien no tiene alcance global solo ve la suya.
        propia = plataforma_politicas.sucursal_asignada(db, usuario_id)

        # 7. Nombres contra la empresa de la sesión.
        sucursal_ids: list[int] | None = None
        sucursales_resueltas: list[ReferenciaResuelta] = []
        if "sucursales" in definicion.filtros:
            if propia is not None:
                sucursal_ids = [propia]
                nombre = plataforma_politicas.obtener_sucursal(db, propia).nombre
                sucursales_resueltas = [ReferenciaResuelta(id=propia, nombre=nombre)]
                avisos.append("Solo se muestran datos de tu sucursal.")
            elif solicitud.sucursales:
                ids, sin_coincidencia = plataforma_politicas.resolver_sucursales_por_nombres(db, solicitud.sucursales)
                if sin_coincidencia:
                    return _respuesta(
                        "ambigua",
                        f"No encontré la sucursal {self._comillas(sin_coincidencia)}. Elige una de las existentes.",
                        sugerencias=plataforma_politicas.listar_nombres_sucursales_activas(db)[:MAX_SUGERENCIAS],
                        avisos=avisos,
                        interprete=interprete,
                    )
                sucursal_ids = ids
                sucursales_resueltas = [
                    ReferenciaResuelta(id=i, nombre=plataforma_politicas.obtener_sucursal(db, i).nombre) for i in ids
                ]

        categoria_ids: list[int] | None = None
        categorias_resueltas: list[ReferenciaResuelta] = []
        if "categorias" in definicion.filtros and solicitud.categorias:
            ids, sin_coincidencia = catalogo_politicas.resolver_categorias_por_nombres(db, solicitud.categorias)
            if sin_coincidencia:
                return _respuesta(
                    "ambigua",
                    f"No encontré la categoría {self._comillas(sin_coincidencia)}. Elige una de las existentes.",
                    sugerencias=catalogo_politicas.listar_nombres_categorias_activas(db)[:MAX_SUGERENCIAS],
                    avisos=avisos,
                    interprete=interprete,
                )
            categoria_ids = ids
            categorias_resueltas = [
                ReferenciaResuelta(id=i, nombre=catalogo_politicas.obtener_categoria(db, i).nombre) for i in ids
            ]

        producto_ids: list[int] | None = None
        productos_resueltos: list[ReferenciaResuelta] = []
        if "productos" in definicion.filtros and solicitud.productos:
            ids, ambiguos, sin_coincidencia = catalogo_politicas.resolver_productos_por_nombres(db, solicitud.productos)
            if ambiguos:
                return _respuesta(
                    "ambigua",
                    f"El producto {self._comillas(ambiguos)} coincide con demasiados artículos. Escribe un nombre más específico.",
                    avisos=avisos,
                    interprete=interprete,
                )
            if sin_coincidencia:
                return _respuesta(
                    "ambigua",
                    f"No encontré el producto {self._comillas(sin_coincidencia)}. Revisa el nombre.",
                    avisos=avisos,
                    interprete=interprete,
                )
            producto_ids = ids
            productos_resueltos = [
                ReferenciaResuelta(id=i, nombre=catalogo_politicas.obtener_producto(db, i).nombre) for i in ids
            ]

        canal = solicitud.canal if "canal" in definicion.filtros else None
        contexto = ContextoEjecucion(
            periodo=periodo,
            sucursal_ids=sucursal_ids,
            categoria_ids=categoria_ids,
            producto_ids=producto_ids,
            canal=canal,
            agrupacion=agrupacion,
            orden=orden,
            limite=limite,
            horizonte_semanas=horizonte,
        )
        resuelta = SolicitudResuelta(
            tipo_reporte=definicion.codigo,
            periodo=resuelto_periodo,
            sucursales=sucursales_resueltas,
            categorias=categorias_resueltas,
            productos=productos_resueltos,
            canal=canal,
            agrupacion=agrupacion,
            orden=orden if "orden" in definicion.filtros else None,
            limite=limite,
            horizonte_semanas=horizonte,
        )
        para_bitacora = {
            "tipo_reporte": definicion.codigo,
            "periodo": (
                {"desde": periodo.desde.isoformat(), "hasta": periodo.hasta.isoformat()} if periodo else None
            ),
            "sucursal_ids": sucursal_ids,
            "categoria_ids": categoria_ids,
            "producto_ids": producto_ids,
            "canal": canal,
            "agrupacion": agrupacion,
            "orden": orden if "orden" in definicion.filtros else None,
            "limite": limite,
            "horizonte_semanas": horizonte,
        }
        return _Preparada(definicion, resuelta, contexto, avisos, interprete, para_bitacora)

    # -- pasos --

    @staticmethod
    def _comillas(nombres: list[str]) -> str:
        return ", ".join(f"«{n}»" for n in nombres)

    @staticmethod
    def _interpretar(db: Session, texto: str, funcionalidades: set[str], con_alcance_global: bool = True):
        """Groq primero; si no responde o devuelve algo que no valida, el intérprete de reglas."""
        sucursales = plataforma_politicas.listar_nombres_sucursales_activas(db)
        categorias = catalogo_politicas.listar_nombres_categorias_activas(db)
        avisos: list[str] = []
        resultado = obtener_interprete_reportes().interpretar(
            texto,
            funcionalidades,
            nombres_sucursales=sucursales,
            nombres_categorias=categorias,
            con_alcance_global=con_alcance_global,
        )
        if resultado.solicitud is None:
            logger.warning("Interprete de reportes sin solicitud (origen=%s, error=%s)", resultado.origen, resultado.error)
            avisos.append("El asistente de IA no respondió; usé una interpretación básica de tu pedido.")
            resultado = InterpreteReportesReglas().interpretar(
                texto,
                funcionalidades,
                nombres_sucursales=sucursales,
                nombres_categorias=categorias,
                con_alcance_global=con_alcance_global,
            )
        return resultado, avisos

    @staticmethod
    def _avisar_filtros_ignorados(definicion, solicitud: SolicitudReporte) -> list[str]:
        pedidos = {
            "periodo": solicitud.periodo is not None,
            "sucursales": bool(solicitud.sucursales),
            "categorias": bool(solicitud.categorias),
            "productos": bool(solicitud.productos),
            "canal": solicitud.canal is not None,
            "agrupacion": solicitud.agrupacion is not None,
            "orden": solicitud.orden is not None,
            "limite": solicitud.limite is not None,
            "horizonte_semanas": solicitud.horizonte_semanas is not None,
        }
        # La analítica es de toda la empresa: lo que acota por sucursal o canal no se ignora en silencio.
        de_toda_la_empresa = {"sucursales": "sucursal", "canal": "canal"}
        avisos = []
        for filtro, presente in pedidos.items():
            if not presente or filtro in definicion.filtros:
                continue
            if definicion.requiere_alcance_global and filtro in de_toda_la_empresa:
                avisos.append(f"La analítica es de toda la empresa; ignoré el filtro de {de_toda_la_empresa[filtro]}.")
            else:
                avisos.append(f"El reporte «{definicion.titulo}» no usa el filtro «{filtro}»; lo ignoré.")
        return avisos

    @staticmethod
    def _resolver_periodo(definicion, solicitud: SolicitudReporte):
        """(ParametrosPeriodo, PeriodoResuelto, avisos, rechazo). `rechazo` es el mensaje de
        "invalida" si el periodo pedido no se puede resolver."""
        avisos: list[str] = []
        pedido = solicitud.periodo
        por_defecto = pedido is None
        if por_defecto:
            pedido = PeriodoSolicitado.model_validate(definicion.filtros["periodo"].defecto)
        try:
            desde, hasta = resolver_periodo_relativo(
                pedido.tipo, n=pedido.n, mes=pedido.mes, anio=pedido.anio, desde=pedido.desde, hasta=pedido.hasta
            )
        except DomainError as error:
            return None, None, avisos, error.mensaje
        etiqueta = etiqueta_periodo(desde, hasta)
        if por_defecto:
            avisos.append(f"No indicaste el periodo; usé {etiqueta}.")
        if pedido.tipo == "ultimos_meses":
            avisos.append(
                f"«Últimos {pedido.n} meses» incluye {pedido.n - 1} meses completos y lo que va del actual "
                f"(desde el {desde:%d/%m/%Y})."
            )
        return (
            ParametrosPeriodo(desde=desde, hasta=hasta),
            PeriodoResuelto(desde=desde, hasta=hasta, etiqueta=etiqueta),
            avisos,
            None,
        )

    @staticmethod
    def _resolver_horizonte(definicion, solicitud: SolicitudReporte):
        """(rechazo, horizonte): las semanas a predecir, con el defecto del registro; `rechazo` es el mensaje de
        "invalida" si están fuera de rango. Un reporte sin ese filtro no tiene horizonte (None)."""
        filtro = definicion.filtros.get("horizonte_semanas")
        if filtro is None:
            return None, None
        horizonte = solicitud.horizonte_semanas if solicitud.horizonte_semanas is not None else filtro.defecto
        if not filtro.minimo <= horizonte <= filtro.maximo:
            return (
                f"El horizonte debe estar entre {filtro.minimo} y {filtro.maximo} semanas (pediste {horizonte}).",
                None,
            )
        return None, horizonte

    @staticmethod
    def _resolver_limites(definicion, solicitud: SolicitudReporte):
        """(rechazo, limite, agrupacion, orden)."""
        limite = None
        if "limite" in definicion.filtros:
            filtro = definicion.filtros["limite"]
            limite = solicitud.limite if solicitud.limite is not None else filtro.defecto
            if not filtro.minimo <= limite <= filtro.maximo:
                return (
                    f"El límite debe estar entre {filtro.minimo} y {filtro.maximo} filas (pediste {limite}).",
                    None,
                    None,
                    None,
                )
        agrupacion = None
        if "agrupacion" in definicion.filtros:
            filtro = definicion.filtros["agrupacion"]
            agrupacion = solicitud.agrupacion or filtro.defecto
            if agrupacion not in filtro.valores:
                permitidas = ", ".join(filtro.valores)
                return (
                    f"Para «{definicion.titulo}» puedes agrupar por: {permitidas}.",
                    None,
                    None,
                    None,
                )
        orden = solicitud.orden or "mayor_a_menor"
        return None, limite, agrupacion, orden


def _resolver_resultado(
    preparada: _Preparada, ejecucion: ResultadoEjecucion | None, max_filas: int, narrativa: str | None
) -> ReporteGenerativoRespuesta:
    definicion = preparada.definicion
    avisos = list(preparada.avisos)
    reporte = None
    if ejecucion is not None:
        filas = ejecucion.filas
        truncado = len(filas) > max_filas
        if truncado:
            filas = filas[:max_filas]
            avisos.append(
                f"El reporte tiene más de {max_filas} filas; muestro las primeras {max_filas}. "
                "Agrupa por semana o por mes para verlo completo."
            )
        avisos.extend(ejecucion.avisos)
        reporte = ReporteEjecutado(
            codigo=definicion.codigo,
            titulo=definicion.titulo,
            columnas=list(definicion.columnas),
            filas=filas,
            resumen=ejecucion.resumen,
            grafico_sugerido=definicion.grafico,
            truncado=truncado,
            generado_en=dt.datetime.now(dt.timezone.utc),
        )
    periodo = preparada.resuelta.periodo
    horizonte = preparada.resuelta.horizonte_semanas
    de_cuando = f" de {periodo.etiqueta}" if periodo else ""
    if not periodo and horizonte is not None:
        de_cuando = " de la próxima semana" if horizonte == 1 else f" de las próximas {horizonte} semanas"
    if reporte is None:
        mensaje = f"Entendí que quieres «{definicion.titulo}»{de_cuando}."
    else:
        mensaje = f"Listo: «{definicion.titulo}»{de_cuando} ({len(reporte.filas)} filas)."
    return ReporteGenerativoRespuesta(
        estado="ok",
        mensaje=mensaje,
        avisos=avisos,
        interprete=preparada.interprete,
        solicitud=preparada.resuelta,
        reporte=reporte,
        narrativa=narrativa,
    )


def _ejecutar_preparada(
    db: Session, usuario_id: int, preparada: _Preparada, max_filas: int
) -> ReporteGenerativoRespuesta:
    """Corre el ejecutor del reporte y arma la respuesta con a lo más `max_filas` filas. Lo
    comparten /ejecutar (tope de pantalla) y /exportar (tope del archivo)."""
    definicion = preparada.definicion
    ejecucion = definicion.ejecutor(db, usuario_id, preparada.contexto)
    periodo = preparada.resuelta.periodo
    narrativa = ejecucion.narrativa or redactar_narrativa_reporte(
        definicion.codigo, periodo.etiqueta if periodo else None, ejecucion.filas, ejecucion.resumen
    )
    return _resolver_resultado(preparada, ejecucion, max_filas, narrativa)


def _respuesta_no_disponible(preparada: _Preparada, error: ReporteNoDisponible) -> ReporteGenerativoRespuesta:
    """El reporte es válido pero no se puede producir (modelo sin entrenar u obsoleto): estado "no_disponible",
    HTTP 200, sin filas y con la sugerencia de qué hacer."""
    return _respuesta(
        "no_disponible",
        error.mensaje,
        sugerencias=error.sugerencias,
        avisos=preparada.avisos,
        interprete=preparada.interprete,
    )


class InterpretarSolicitudReporte:
    def ejecutar(self, db: Session, usuario_id: int, datos: ReporteGenerativoRequest) -> ReporteGenerativoRespuesta:
        """POST /api/v1/reportes-ia/interpretar: valida y resuelve la solicitud ("entendí
        esto") sin ejecutarla. Requiere `reportes.ver` y el plan con `reportes_ia`
        (verificado en el router)."""
        preparada = _PreparadorSolicitud().preparar(db, usuario_id, datos)
        if isinstance(preparada, ReporteGenerativoRespuesta):
            return preparada
        return _resolver_resultado(preparada, None, get_settings().reportes_ia_max_filas, None)


class EjecutarReporteGenerativo:
    def ejecutar(
        self,
        db: Session,
        usuario_id: int,
        datos: ReporteGenerativoRequest,
        contexto: ContextoAuditoria | None = None,
    ) -> ReporteGenerativoRespuesta:
        """POST /api/v1/reportes-ia/ejecutar: interpreta (si vino texto), valida y ejecuta uno
        de los reportes del registro. Deja una fila de bitácora sin el texto del usuario."""
        inicio = time.perf_counter()
        preparada = _PreparadorSolicitud().preparar(db, usuario_id, datos)
        if isinstance(preparada, ReporteGenerativoRespuesta):
            self._auditar(db, contexto, ACCION_RECHAZAR, {"estado": preparada.estado, "origen": datos.origen}, inicio)
            return preparada

        try:
            respuesta = _ejecutar_preparada(db, usuario_id, preparada, get_settings().reportes_ia_max_filas)
        except ReporteNoDisponible as error:
            respuesta = _respuesta_no_disponible(preparada, error)
            self._auditar(
                db,
                contexto,
                ACCION_RECHAZAR,
                {
                    **preparada.filtros_para_bitacora,
                    "estado": respuesta.estado,
                    "interprete": preparada.interprete,
                    "origen": datos.origen,
                },
                inicio,
            )
            return respuesta
        self._auditar(
            db,
            contexto,
            ACCION_EJECUTAR,
            {
                **preparada.filtros_para_bitacora,
                "estado": respuesta.estado,
                "interprete": preparada.interprete,
                "origen": datos.origen,
                "filas": len(respuesta.reporte.filas),
                "truncado": respuesta.reporte.truncado,
            },
            inicio,
        )
        return respuesta

    @staticmethod
    def _auditar(db: Session, contexto: ContextoAuditoria | None, accion: str, datos: dict, inicio: float) -> None:
        """Una fila por consulta, en la misma transacción. NO guarda el texto del usuario ni los
        nombres que escribió: solo el tipo, los filtros ya normalizados (ids) y las cifras."""
        if contexto is None:
            return
        datos = {**datos, "duracion_ms": int((time.perf_counter() - inicio) * 1000)}
        plataforma_politicas.registrar_bitacora_de(db, contexto, ENTIDAD_REPORTE_IA, None, accion, datos)
        db.commit()


class ExportarReporteGenerativo:
    def ejecutar(
        self,
        db: Session,
        usuario_id: int,
        datos: ExportarReporteRequest,
        contexto: ContextoAuditoria | None = None,
    ) -> ArchivoExportado:
        """POST /api/v1/reportes-ia/exportar: ejecuta el reporte (las mismas validaciones y el
        mismo alcance que /ejecutar) y lo devuelve como .xlsx o .pdf, todo en memoria.

        Con `resuelta` o `solicitud` NO pasa por el intérprete; con `texto` interpreta igual que
        /ejecutar. Si el estado no es "ok" (ambigua, invalida, no_soportada...) no hay archivo:
        422 `reporte_no_exportable` con el mensaje y las sugerencias. Deja una fila de bitácora
        `reporte_ia/exportar` sin el texto del usuario."""
        inicio = time.perf_counter()
        if datos.resuelta is not None:
            pedido = ReporteGenerativoRequest(solicitud=solicitud_desde_resuelta(datos.resuelta))
        else:
            pedido = ReporteGenerativoRequest(texto=datos.texto, solicitud=datos.solicitud)
        preparada = _PreparadorSolicitud().preparar(db, usuario_id, pedido)
        if isinstance(preparada, ReporteGenerativoRespuesta):
            raise ErrorFuncional(
                "reporte_no_exportable",
                preparada.mensaje,
                422,
                estado=preparada.estado,
                sugerencias=preparada.sugerencias,
            )

        try:
            respuesta = _ejecutar_preparada(db, usuario_id, preparada, MAX_FILAS[datos.formato])
        except ReporteNoDisponible as error:
            raise ErrorFuncional(
                "reporte_no_exportable",
                error.mensaje,
                422,
                estado="no_disponible",
                sugerencias=error.sugerencias,
            ) from error
        empresa =plataforma_politicas.obtener_empresa_de_la_sesion(db)
        ahora = ahora_bolivia()
        documento = documento_desde_reporte(respuesta, empresa.nombre, ahora)
        contenido = construir_archivo(documento, datos.formato, datos.incluir_grafico)
        # El nombre sale de datos propios (código del reporte y de la empresa): nunca del texto
        # del usuario.
        nombre = f"reporte-{preparada.definicion.codigo}-{empresa.codigo}-{ahora:%Y%m%d-%H%M}.{datos.formato}"
        EjecutarReporteGenerativo._auditar(
            db,
            contexto,
            ACCION_EXPORTAR,
            {
                **preparada.filtros_para_bitacora,
                "formato": datos.formato,
                "interprete": preparada.interprete,
                "filas": len(respuesta.reporte.filas),
                "truncado": respuesta.reporte.truncado,
                "bytes": len(contenido),
            },
            inicio,
        )
        return ArchivoExportado(contenido, TIPO_MIME[datos.formato], nombre)


class ConsultarCatalogoReportes:
    def ejecutar(self, db: Session, usuario_id: int) -> list[dict]:
        """GET /api/v1/reportes-ia/catalogo: los reportes que el plan de la empresa permite y que el usuario puede
        usar (sin alcance global no se ofrecen los de toda la empresa), con sus filtros, columnas, gráfico y frases
        de ejemplo."""
        return registro_reportes.catalogo_para(_funcionalidades_del_plan(db), _con_alcance_global(db, usuario_id))
