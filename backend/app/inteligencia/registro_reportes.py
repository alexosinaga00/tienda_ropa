"""CU-23 (E09) — Registro cerrado de reportes generativos.

Es lo ÚNICO que dice qué se puede pedir: cada reporte con sus filtros permitidos
(tipo, rango, valores), sus columnas y el gráfico sugerido. Lo que devuelve el
intérprete (Groq o reglas) se valida contra este registro; nada fuera de él se
ejecuta. El prompt de Groq y el intérprete de reglas se GENERAN desde aquí
(`descripcion_para_prompt`), de modo que agregar un reporte (E12) no cambia el
código de los intérpretes.

Este módulo no tiene SQL ni toca la base: no importa `comercial` ni `catalogo`.

Cómo se conecta el ejecutor
---------------------------
Cada definición nace con `ejecutor=None`. El ejecutor es un callable
`(db, usuario_id, contexto) -> resultado` que llama a las funciones de consulta de
`comercial` / `catalogo` (p. ej. `reporte_ventas_por_sucursal`). El caso de uso
(`casos_uso/cu23_generar_reportes_con_ia.py`) los conecta una sola vez, al importarse:

    from app.inteligencia.registro_reportes import conectar_ejecutor
    conectar_ejecutor("ventas_por_sucursal", _ejecutar_ventas_por_sucursal)

`conectar_ejecutor` reemplaza la definición (son inmutables) dentro del registro
interno; `REGISTRO` es una vista de solo lectura sobre él, así que ve el cambio.
Solo acepta códigos que ya existen: no se pueden agregar reportes en caliente.
`ContextoEjecucion` y `ResultadoEjecucion` los define el caso de uso, no este módulo.

Reportes de analítica (E12)
---------------------------
Los reportes con `funcionalidad_plan="analitica_ml"` (predicción de demanda, segmentación de clientes y métricas de
los modelos) salen del Machine Learning de la empresa. Su ejecutor llama SIEMPRE a `ConsultarAnaliticaML` (nunca a los
modelos ni a `ml/`) y, si el modelo no está entrenado o es obsoleto, lanza `ReporteNoDisponible`: el caso de uso la
convierte en el estado "no_disponible" (HTTP 200, sin filas). Son de toda la empresa (`requiere_alcance_global`): quien
tiene una sucursal asignada recibe el mismo 403 que las rutas de `/analitica`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Literal

from app.core.planes import FUNC_ANALITICA_ML, FUNC_REPORTES_IA
from app.inteligencia.schemas import (
    AGRUPACIONES_REPORTE,
    CANALES_REPORTE,
    LIMITE_MAXIMO,
    LIMITE_MINIMO,
    MAX_NOMBRES_POR_FILTRO,
    ORDENES_REPORTE,
    TIPOS_PERIODO,
    ColumnaReporte,
    GraficoSugerido,
)

TipoFiltro = Literal["periodo", "lista_nombres", "enum", "entero"]

# callable(db, usuario_id, contexto) -> resultado. Firma documentada en el módulo.
Ejecutor = Callable[..., Any]

# Semanas que se pueden predecir (las mismas que `ml.demanda.MAX_SEMANAS_PREDICCION`; una prueba vigila que coincidan).
HORIZONTE_MINIMO = 1
HORIZONTE_MAXIMO = 12
HORIZONTE_POR_DEFECTO = 4


class ReporteNoDisponible(Exception):
    """El reporte es válido pero no se puede producir ahora (el modelo de ML no está entrenado, es obsoleto o no
    cubre lo pedido). El caso de uso la convierte en el estado "no_disponible" (HTTP 200) con `mensaje` y
    `sugerencias`; nunca se inventan cifras para llenar el hueco."""

    def __init__(self, mensaje: str, sugerencias: Iterable[str] = ()) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.sugerencias = list(sugerencias)


@dataclass(frozen=True)
class DefinicionFiltro:
    """Un filtro permitido para un reporte.

    - periodo: `defecto` es un dict con la forma de PeriodoSolicitado
      (p. ej. {"tipo": "ultimos_dias", "n": 30}); las fechas las resuelve core/tiempo.
    - lista_nombres: nombres que se resuelven contra la empresa; `maximo` = cuántos.
    - enum: uno de `valores`.
    - entero: entre `minimo` y `maximo`.
    """

    tipo: TipoFiltro
    descripcion: str
    obligatorio: bool = False
    defecto: Any = None
    minimo: int | None = None
    maximo: int | None = None
    valores: tuple[str, ...] = ()


@dataclass(frozen=True)
class DefinicionReporte:
    codigo: str
    titulo: str
    descripcion: str
    ejemplos: tuple[str, ...]
    filtros: Mapping[str, DefinicionFiltro]
    columnas: tuple[ColumnaReporte, ...]
    grafico: GraficoSugerido
    funcionalidad_plan: str = FUNC_REPORTES_IA  # los de analítica (E12) usan "analitica_ml"
    # True = es de toda la empresa: quien tiene una sucursal asignada (encargado, cajero) recibe 403.
    requiere_alcance_global: bool = False
    ejecutor: Ejecutor | None = field(default=None, compare=False, repr=False)


# ---- Filtros reutilizables ----------------------------------------------------------


def _periodo(defecto: dict[str, Any]) -> DefinicionFiltro:
    return DefinicionFiltro(
        "periodo",
        "Periodo del reporte, en términos relativos (el backend calcula las fechas).",
        defecto=defecto,
    )


def _nombres(que: str) -> DefinicionFiltro:
    return DefinicionFiltro(
        "lista_nombres",
        f"Nombres de {que} para filtrar (se validan contra tu empresa).",
        maximo=MAX_NOMBRES_POR_FILTRO,
    )


def _canal() -> DefinicionFiltro:
    return DefinicionFiltro(
        "enum", "Canal de venta: digital o presencial.", valores=tuple(CANALES_REPORTE)
    )


def _limite(defecto: int = 10) -> DefinicionFiltro:
    return DefinicionFiltro(
        "entero",
        "Cuántas filas mostrar.",
        defecto=defecto,
        minimo=LIMITE_MINIMO,
        maximo=LIMITE_MAXIMO,
    )


def _orden() -> DefinicionFiltro:
    return DefinicionFiltro(
        "enum",
        "Orden del ranking: de mayor a menor o de menor a mayor.",
        defecto="mayor_a_menor",
        valores=tuple(ORDENES_REPORTE),
    )


def _agrupacion(valores: tuple[str, ...], defecto: str) -> DefinicionFiltro:
    return DefinicionFiltro(
        "enum", "Cómo agrupar el tiempo.", defecto=defecto, valores=valores
    )


def _horizonte() -> DefinicionFiltro:
    return DefinicionFiltro(
        "entero",
        "Cuántas semanas hacia adelante predecir (la próxima semana = 1, el próximo mes = 4).",
        defecto=HORIZONTE_POR_DEFECTO,
        minimo=HORIZONTE_MINIMO,
        maximo=HORIZONTE_MAXIMO,
    )


# ---- Definiciones -------------------------------------------------------------------

_DEFINICIONES: tuple[DefinicionReporte, ...] = (
    DefinicionReporte(
        codigo="ventas_por_sucursal",
        titulo="Ventas por sucursal",
        descripcion="Total vendido, transacciones y ticket promedio de cada sucursal en un periodo.",
        ejemplos=(
            "Mostrame las ventas de septiembre agrupadas por sucursal",
            "ventas por sucursal de los últimos 30 días",
            "¿cuánto vendió cada sucursal esta semana?",
        ),
        filtros=MappingProxyType(
            {
                "periodo": _periodo({"tipo": "ultimos_dias", "n": 30}),
                "sucursales": _nombres("sucursales"),
                "categorias": _nombres("categorías"),
                "canal": _canal(),
            }
        ),
        columnas=(
            ColumnaReporte(clave="sucursal", titulo="Sucursal", tipo="texto"),
            ColumnaReporte(clave="transacciones", titulo="Transacciones", tipo="entero"),
            ColumnaReporte(clave="total_ventas", titulo="Total vendido", tipo="moneda"),
            ColumnaReporte(clave="ticket_promedio", titulo="Ticket promedio", tipo="moneda"),
            ColumnaReporte(clave="participacion", titulo="Participación", tipo="porcentaje"),
        ),
        grafico=GraficoSugerido(tipo="barras", eje_x="sucursal", eje_y="total_ventas"),
    ),
    DefinicionReporte(
        codigo="productos_mas_vendidos",
        titulo="Productos más vendidos",
        descripcion="Ranking de productos por ventas en un periodo, con unidades y total vendido.",
        ejemplos=(
            "cuales fueron los diez productos mas vendidos este mes",
            "top 5 de prendas más vendidas el mes pasado",
            "productos más vendidos por el canal digital en los últimos 7 días",
        ),
        filtros=MappingProxyType(
            {
                "periodo": _periodo({"tipo": "ultimos_dias", "n": 30}),
                "sucursales": _nombres("sucursales"),
                "categorias": _nombres("categorías"),
                "canal": _canal(),
                "limite": _limite(10),
                "orden": _orden(),
            }
        ),
        columnas=(
            ColumnaReporte(clave="posicion", titulo="Posición", tipo="entero"),
            ColumnaReporte(clave="producto", titulo="Producto", tipo="texto"),
            ColumnaReporte(clave="unidades", titulo="Unidades", tipo="entero"),
            ColumnaReporte(clave="total_vendido", titulo="Total vendido", tipo="moneda"),
            ColumnaReporte(clave="participacion", titulo="Participación", tipo="porcentaje"),
        ),
        grafico=GraficoSugerido(
            tipo="barras_horizontales", eje_x="producto", eje_y="total_vendido"
        ),
    ),
    DefinicionReporte(
        codigo="ventas_por_periodo",
        titulo="Ventas por periodo",
        descripcion="Evolución de las ventas agrupadas por día, semana o mes.",
        ejemplos=(
            "genera un grafico de ventas por semana",
            "ventas por día de los últimos 15 días",
            "ventas mensuales de este año",
        ),
        filtros=MappingProxyType(
            {
                "periodo": _periodo({"tipo": "ultimas_semanas", "n": 8}),
                "sucursales": _nombres("sucursales"),
                "categorias": _nombres("categorías"),
                "productos": _nombres("productos"),
                "canal": _canal(),
                "agrupacion": _agrupacion(tuple(AGRUPACIONES_REPORTE), "semana"),
            }
        ),
        columnas=(
            ColumnaReporte(clave="periodo", titulo="Periodo", tipo="texto"),
            ColumnaReporte(clave="desde", titulo="Desde", tipo="fecha"),
            ColumnaReporte(clave="transacciones", titulo="Transacciones", tipo="entero"),
            ColumnaReporte(clave="unidades", titulo="Unidades", tipo="entero"),
            ColumnaReporte(clave="total_ventas", titulo="Total vendido", tipo="moneda"),
        ),
        grafico=GraficoSugerido(tipo="linea", eje_x="periodo", eje_y="total_ventas"),
    ),
    DefinicionReporte(
        codigo="comparacion_sucursales",
        titulo="Comparación de sucursales",
        descripcion=(
            "Compara el total vendido de las sucursales a lo largo del tiempo, "
            "con la variación contra el periodo anterior de cada una."
        ),
        ejemplos=(
            "compara las ventas de las sucursales durante los ultimos tres meses",
            "compara las sucursales por semana en el último mes",
            "comparación de sucursales de este año por mes",
        ),
        filtros=MappingProxyType(
            {
                "periodo": _periodo({"tipo": "ultimos_meses", "n": 3}),
                "sucursales": _nombres("sucursales"),
                "categorias": _nombres("categorías"),
                "canal": _canal(),
                "agrupacion": _agrupacion(("mes", "semana"), "mes"),
            }
        ),
        columnas=(
            ColumnaReporte(clave="periodo", titulo="Periodo", tipo="texto"),
            ColumnaReporte(clave="sucursal", titulo="Sucursal", tipo="texto"),
            ColumnaReporte(clave="total_ventas", titulo="Total vendido", tipo="moneda"),
            ColumnaReporte(clave="transacciones", titulo="Transacciones", tipo="entero"),
            ColumnaReporte(clave="variacion_pct", titulo="Variación", tipo="porcentaje"),
        ),
        grafico=GraficoSugerido(
            tipo="barras_agrupadas", eje_x="periodo", eje_y="total_ventas", serie="sucursal"
        ),
    ),
    DefinicionReporte(
        codigo="productos_menor_existencia",
        titulo="Productos con menor existencia",
        descripcion="Productos con menos unidades disponibles, indicando cuáles están bajo el mínimo.",
        ejemplos=(
            "mostrame los productos con menor existencia",
            "los 5 productos con menos stock",
            "qué productos tienen poco stock",
        ),
        filtros=MappingProxyType(
            {
                "sucursales": _nombres("sucursales"),
                "categorias": _nombres("categorías"),
                "productos": _nombres("productos"),
                "limite": _limite(10),
            }
        ),
        columnas=(
            ColumnaReporte(clave="producto", titulo="Producto", tipo="texto"),
            ColumnaReporte(clave="categoria", titulo="Categoría", tipo="texto"),
            ColumnaReporte(clave="disponible", titulo="Disponible", tipo="entero"),
            ColumnaReporte(clave="stock_minimo", titulo="Stock mínimo", tipo="entero"),
            ColumnaReporte(clave="bajo_minimo", titulo="Bajo el mínimo", tipo="booleano"),
        ),
        grafico=GraficoSugerido(
            tipo="barras_horizontales", eje_x="producto", eje_y="disponible"
        ),
    ),
    DefinicionReporte(
        codigo="ingresos_por_categoria",
        titulo="Ingresos por categoría",
        descripcion="Cuánto ingresó cada categoría de productos en un periodo, con su margen bruto.",
        ejemplos=(
            "que categorias generaron mayores ingresos durante este periodo",
            "ingresos por categoría del mes pasado",
            "las 5 categorías que menos vendieron este año",
        ),
        filtros=MappingProxyType(
            {
                "periodo": _periodo({"tipo": "ultimos_dias", "n": 30}),
                "sucursales": _nombres("sucursales"),
                "canal": _canal(),
                "limite": _limite(10),
                "orden": _orden(),
            }
        ),
        columnas=(
            ColumnaReporte(clave="categoria", titulo="Categoría", tipo="texto"),
            ColumnaReporte(clave="unidades", titulo="Unidades", tipo="entero"),
            ColumnaReporte(clave="total_vendido", titulo="Total vendido", tipo="moneda"),
            ColumnaReporte(clave="margen_bruto", titulo="Margen bruto", tipo="moneda"),
            ColumnaReporte(clave="participacion", titulo="Participación", tipo="porcentaje"),
        ),
        grafico=GraficoSugerido(tipo="torta", eje_x="categoria", eje_y="total_vendido"),
    ),
    # ---- Analítica (E12): salen del Machine Learning de la empresa; solo el plan con analitica_ml ----
    DefinicionReporte(
        codigo="prediccion_demanda",
        titulo="Predicción de demanda",
        descripcion=(
            "Unidades que se prevé vender cada semana en las próximas semanas, por categoría, con un rango estimado. "
            "Es una predicción del modelo de Machine Learning de la empresa, no ventas pasadas."
        ),
        ejemplos=(
            "predice la demanda de camisas para el proximo mes",
            "pronostico de ventas para las proximas 8 semanas",
            "cuanto voy a vender la proxima semana",
        ),
        filtros=MappingProxyType(
            {
                "categorias": _nombres("categorías"),
                "horizonte_semanas": _horizonte(),
            }
        ),
        columnas=(
            ColumnaReporte(clave="categoria", titulo="Categoría", tipo="texto"),
            ColumnaReporte(clave="semana", titulo="Semana (lunes)", tipo="fecha"),
            ColumnaReporte(clave="unidades_predichas", titulo="Unidades previstas", tipo="entero"),
            ColumnaReporte(clave="minimo", titulo="Mínimo estimado", tipo="entero"),
            ColumnaReporte(clave="maximo", titulo="Máximo estimado", tipo="entero"),
        ),
        grafico=GraficoSugerido(
            tipo="linea", eje_x="semana", eje_y="unidades_predichas", serie="categoria"
        ),
        funcionalidad_plan=FUNC_ANALITICA_ML,
        requiere_alcance_global=True,
    ),
    DefinicionReporte(
        codigo="segmentacion_clientes",
        titulo="Segmentación de clientes",
        descripcion=(
            "Grupos de clientes según cuánto, cuántas veces y qué tan recientemente compran (RFM), con el tamaño y el "
            "aporte a las ventas de cada grupo. Es el resultado del modelo de segmentación de la empresa."
        ),
        ejemplos=(
            "segmenta mis clientes",
            "quienes son mis clientes valiosos",
            "muestrame los tipos de clientes que tengo",
        ),
        filtros=MappingProxyType({}),
        columnas=(
            ColumnaReporte(clave="segmento", titulo="Segmento", tipo="texto"),
            ColumnaReporte(clave="clientes", titulo="Clientes", tipo="entero"),
            ColumnaReporte(clave="porcentaje_clientes", titulo="% de clientes", tipo="porcentaje"),
            ColumnaReporte(clave="recencia_media_dias", titulo="Días desde la última compra", tipo="texto"),
            ColumnaReporte(clave="frecuencia_media", titulo="Compras por cliente", tipo="texto"),
            ColumnaReporte(clave="monto_medio", titulo="Monto medio por cliente", tipo="moneda"),
            ColumnaReporte(clave="porcentaje_monto", titulo="% de las ventas", tipo="porcentaje"),
        ),
        grafico=GraficoSugerido(tipo="torta", eje_x="segmento", eje_y="clientes"),
        funcionalidad_plan=FUNC_ANALITICA_ML,
        requiere_alcance_global=True,
    ),
    DefinicionReporte(
        codigo="metricas_modelos",
        titulo="Métricas de los modelos",
        descripcion=(
            "Qué tan acertados son los modelos de Machine Learning de la empresa: el error de la predicción de demanda "
            "frente a su línea base (promedio móvil) y la calidad de la separación de los segmentos de clientes."
        ),
        ejemplos=(
            "que tan bueno es el modelo de prediccion",
            "metricas del modelo",
            "precision del modelo de demanda",
        ),
        filtros=MappingProxyType({}),
        columnas=(
            ColumnaReporte(clave="modelo", titulo="Modelo", tipo="texto"),
            ColumnaReporte(clave="metrica", titulo="Métrica", tipo="texto"),
            ColumnaReporte(clave="valor", titulo="Valor", tipo="texto"),
            ColumnaReporte(clave="linea_base", titulo="Línea base", tipo="texto"),
        ),
        grafico=GraficoSugerido(tipo="tabla"),
        funcionalidad_plan=FUNC_ANALITICA_ML,
        requiere_alcance_global=True,
    ),
    DefinicionReporte(
        codigo="anomalias_ventas",
        titulo="Días de ventas inusuales",
        descripcion=(
            "Días en que una sucursal vendió mucho más o mucho menos de lo esperado según su comportamiento habitual. "
            "Es el resultado del modelo de detección de anomalías de la empresa; un día inusual no es necesariamente un error."
        ),
        ejemplos=(
            "dias raros en mis ventas",
            "hubo anomalias en las ventas del ultimo mes",
            "que dias vendimos algo inusual",
        ),
        filtros=MappingProxyType({"periodo": _periodo({"tipo": "ultimos_dias", "n": 90})}),
        columnas=(
            ColumnaReporte(clave="fecha", titulo="Fecha", tipo="fecha"),
            ColumnaReporte(clave="sucursal", titulo="Sucursal", tipo="texto"),
            ColumnaReporte(clave="total_ventas", titulo="Ventas del día (Bs)", tipo="moneda"),
            ColumnaReporte(clave="esperado", titulo="Esperado (Bs)", tipo="moneda"),
            ColumnaReporte(clave="desviacion_pct", titulo="Desviación", tipo="texto"),
            ColumnaReporte(clave="severidad", titulo="Severidad", tipo="texto"),
        ),
        grafico=GraficoSugerido(tipo="tabla"),
        funcionalidad_plan=FUNC_ANALITICA_ML,
        requiere_alcance_global=True,
    ),
    DefinicionReporte(
        codigo="reposicion_sugerida",
        titulo="Reposición sugerida",
        descripcion=(
            "Qué categorías se pueden agotar según la demanda prevista y el stock disponible hoy, con una cantidad "
            "orientativa a reponer. Es por categoría, no por variante ni por sucursal."
        ),
        ejemplos=(
            "que categorias se me van a agotar",
            "que debo reponer el proximo mes",
            "reposicion sugerida para las proximas 4 semanas",
        ),
        filtros=MappingProxyType(
            {
                "categorias": _nombres("categorías"),
                "horizonte_semanas": _horizonte(),
            }
        ),
        columnas=(
            ColumnaReporte(clave="categoria", titulo="Categoría", tipo="texto"),
            ColumnaReporte(clave="disponible", titulo="Disponible hoy", tipo="entero"),
            ColumnaReporte(clave="demanda_semanal_promedio", titulo="Demanda semanal prevista", tipo="texto"),
            ColumnaReporte(clave="semanas_cobertura", titulo="Semanas de cobertura", tipo="texto"),
            ColumnaReporte(clave="estado", titulo="Estado", tipo="texto"),
            ColumnaReporte(clave="sugerencia_unidades", titulo="Reponer (orientativo)", tipo="entero"),
        ),
        grafico=GraficoSugerido(tipo="tabla"),
        funcionalidad_plan=FUNC_ANALITICA_ML,
        requiere_alcance_global=True,
    ),
)

# Construido una vez al importar. REGISTRO es de solo lectura; lo único que cambia
# después es el ejecutor de cada definición, vía conectar_ejecutor.
_REGISTRO_INTERNO: dict[str, DefinicionReporte] = {d.codigo: d for d in _DEFINICIONES}
REGISTRO: Mapping[str, DefinicionReporte] = MappingProxyType(_REGISTRO_INTERNO)


# ---- Consulta del registro ---------------------------------------------------------


def obtener(codigo: str | None) -> DefinicionReporte | None:
    """La definición del reporte, o None si el código no está en el registro."""
    if not isinstance(codigo, str):
        return None
    return REGISTRO.get(codigo)


def disponibles_para(funcionalidades: Iterable[str], con_alcance_global: bool = True) -> list[DefinicionReporte]:
    """Reportes cuya funcionalidad de plan está entre las dadas (orden del registro). Con `con_alcance_global=False`
    (quien tiene una sucursal asignada) se omiten los de toda la empresa (`requiere_alcance_global`): solo es para no
    ofrecerlos; el 403 de /interpretar y /ejecutar sigue siendo la barrera real."""
    permitidas = set(funcionalidades)
    return [
        d
        for d in REGISTRO.values()
        if d.funcionalidad_plan in permitidas and (con_alcance_global or not d.requiere_alcance_global)
    ]


def conectar_ejecutor(codigo: str, ejecutor: Ejecutor) -> None:
    """Asocia el ejecutor de un reporte que ya existe en el registro."""
    actual = REGISTRO.get(codigo)
    if actual is None:
        raise KeyError(f"El reporte '{codigo}' no está en el registro.")
    _REGISTRO_INTERNO[codigo] = replace(actual, ejecutor=ejecutor)


def _describir_filtro(nombre: str, f: DefinicionFiltro) -> str:
    if f.tipo == "periodo":
        return f"{nombre} (periodo)"
    if f.tipo == "lista_nombres":
        return f"{nombre} (lista de nombres, máximo {f.maximo})"
    if f.tipo == "enum":
        return f"{nombre} ({'|'.join(f.valores)})"
    return f"{nombre} (entero {f.minimo}..{f.maximo})"


def descripcion_para_prompt(
    funcionalidades: Iterable[str] | None = None, con_alcance_global: bool = True
) -> str:
    """Texto del catálogo para el prompt de sistema del intérprete: códigos, filtros y
    enums. No lleva datos del negocio (ni nombres de sucursales, categorías o productos).
    Sin `funcionalidades` describe todos los reportes del registro."""
    definiciones = (
        list(REGISTRO.values())
        if funcionalidades is None
        else disponibles_para(funcionalidades, con_alcance_global)
    )
    lineas = ["Tipos de reporte (usa exactamente uno de estos códigos en tipo_reporte):"]
    for d in definiciones:
        filtros = ", ".join(_describir_filtro(n, f) for n, f in d.filtros.items()) or "ninguno"
        lineas.append(f"- {d.codigo}: {d.descripcion}")
        lineas.append(f"  filtros permitidos: {filtros}")
    lineas.append("")
    lineas.append("Valores de periodo.tipo: " + ", ".join(TIPOS_PERIODO))
    lineas.append(
        "ultimos_dias, ultimas_semanas y ultimos_meses llevan n; mes_calendario lleva mes (1..12) "
        "y opcionalmente anio; rango_fechas lleva desde y hasta con dia, mes y anio opcional. "
        "Nunca calcules fechas."
    )
    return "\n".join(lineas)


def catalogo_para(funcionalidades: Iterable[str], con_alcance_global: bool = True) -> list[dict[str, Any]]:
    """Catálogo público de los reportes disponibles para un plan (GET /reportes-ia/catalogo):
    código, título, descripción, filtros con tipo y rango, columnas, gráfico y ejemplos.
    No incluye el ejecutor."""
    salida: list[dict[str, Any]] = []
    for d in disponibles_para(funcionalidades, con_alcance_global):
        salida.append(
            {
                "codigo": d.codigo,
                "titulo": d.titulo,
                "descripcion": d.descripcion,
                "ejemplos": list(d.ejemplos),
                "filtros": {
                    n: {
                        "tipo": f.tipo,
                        "descripcion": f.descripcion,
                        "obligatorio": f.obligatorio,
                        "defecto": f.defecto,
                        "minimo": f.minimo,
                        "maximo": f.maximo,
                        "valores": list(f.valores),
                    }
                    for n, f in d.filtros.items()
                },
                "columnas": [c.model_dump() for c in d.columnas],
                "grafico": d.grafico.model_dump(),
            }
        )
    return salida
