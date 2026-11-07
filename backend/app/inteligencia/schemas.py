from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated, Any, Literal, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.catalogo.schemas import (
    CatalogoItemRespuesta,
    ConsolidadoRespuesta,
    FiltrosCatalogo,
    ValuacionRespuesta,
)
from app.core.tipos import FechaUTC

# ---- Inteligencia ----

# Los únicos valores que catalogo.schemas.Genero acepta. FiltrosVoz recibe el
# género tal cual lo devuelve Groq (str libre, no el Literal), porque un
# valor fuera de esta lista no debe tirar abajo la validación de todo el
# JSON -- se descarta ese campo puntual en el caso de uso, no la respuesta entera.
GENEROS_VALIDOS = {"hombre", "mujer", "unisex", "nino"}


class VozRequest(BaseModel):
    texto: str = Field(min_length=1, max_length=300)


class FiltrosVoz(BaseModel):
    """Contrato exacto que debe devolver Groq (P6.1): un JSON con estas
    ocho claves, sin texto adicional ni markdown. Todo opcional -- Groq
    manda `null` en lo que la frase no menciona."""

    categoria: str | None = None
    temporada: str | None = None
    material: str | None = None
    color: str | None = None
    talla: str | None = None
    genero: str | None = None
    precio_max: Decimal | None = None
    sucursal: str | None = None


class VozRespuesta(BaseModel):
    resultados: list[CatalogoItemRespuesta]
    filtros: FiltrosCatalogo
    etiquetas: dict[str, str]
    cantidad: int


# ---- Recomendador ------------------------------------------------------


class EventoCrear(BaseModel):
    """Body de POST /ia/eventos. El mobile manda también `texto` en los
    eventos de búsqueda, pero `historial_navegacion` no tiene columna para
    texto libre (el esquema documentado no la tiene); Pydantic v2 ignora
    ese campo extra por default, no hace falta declararlo.

    `tipo` se acepta en lugar de `tipo_evento`: las versiones de la app
    anteriores a la corrección del contrato mandaban `tipo` y recibían 422
    en todos los eventos."""

    tipo_evento: Literal["vista", "busqueda", "carrito", "probador", "favorito"]
    producto_id: int | None = None
    variante_id: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _aceptar_tipo_de_apps_viejas(cls, datos):
        if isinstance(datos, dict) and "tipo_evento" not in datos and "tipo" in datos:
            datos = {**datos, "tipo_evento": datos["tipo"]}
        return datos


class CandidatoRecomendacion(BaseModel):
    """Uno de los ≤20 candidatos que se le pasan a Groq para rankear."""

    variante_id: int
    nombre: str
    categoria_id: int
    precio_base: Decimal


class PerfilClienteRecomendacion(BaseModel):
    """Contexto breve para el prompt de Groq: si hay historial real
    ponderado detrás de estos candidatos, o si son el fallback de
    popularidad (cliente nuevo/anónimo) -- para que el motivo que arma
    Groq sea coherente con el origen real de la lista."""

    hay_historial: bool


class RecomendacionGroq(BaseModel):
    """Una fila de lo que devuelve Groq al rankear candidatos."""

    variante_id: int
    motivo: str = Field(max_length=200)


class RecomendacionItemRespuesta(BaseModel):
    variante_id: int
    producto: CatalogoItemRespuesta
    motivo: str


class RecomendacionesRespuesta(BaseModel):
    recomendaciones: list[RecomendacionItemRespuesta]


# ---- Reporte por voz ----------------------------------------------------

TIPOS_REPORTE_VALIDOS = {"ventas", "inventario", "reservas", "dashboard"}


class ReporteVozRequest(BaseModel):
    texto: str = Field(min_length=1, max_length=300)


class FiltrosReporteVoz(BaseModel):
    """Contrato exacto que debe devolver Groq: qué reporte y con qué
    filtros -- nunca SQL, nunca texto libre que se ejecute. `tipo_reporte`
    es uno de los 4 valores fijos; los filtros son nombres/fechas que
    `inteligencia.casos_uso.cu23_generar_reportes_con_ia` resuelve a id
    antes de llamar a los reportes (CU-22)."""

    tipo_reporte: str
    desde: dt.date | None = None
    hasta: dt.date | None = None
    sucursal: str | None = None
    categoria: str | None = None
    canal: str | None = None


class ReporteVozRespuesta(BaseModel):
    # La pregunta contestada en español, con las cifras del reporte.
    respuesta: str
    tipo_reporte: str
    filtros_aplicados: dict
    resultado: dict


# ---- Reportes ----

# ---- Ventas ---------------------------------------------------------------------


class FilaVentasDetalle(BaseModel):
    """Una fila de vw_ventas_detalle (comercial/repository.py)."""

    venta_id: int
    codigo: str
    canal: str
    fecha: FechaUTC
    sucursal_id: int
    sucursal: str
    producto_id: int
    producto: str
    categoria_id: int
    categoria: str
    cantidad: int
    precio_unitario: Decimal
    subtotal: Decimal
    costo_unitario: Decimal | None
    margen: Decimal


class ResumenVentas(BaseModel):
    transacciones: int
    total_ventas: Decimal
    ticket_promedio: Decimal
    margen_bruto: Decimal


class FilaTopProducto(BaseModel):
    producto_id: int
    producto: str
    cantidad_vendida: int
    total_vendido: Decimal


class FilaVentasPorCanal(BaseModel):
    canal: str
    transacciones: int
    total_ventas: Decimal


class FilaVentasPorSucursal(BaseModel):
    sucursal_id: int
    sucursal: str
    transacciones: int
    total_ventas: Decimal


class ReporteVentasRespuesta(BaseModel):
    resumen: ResumenVentas
    top_productos: list[FilaTopProducto]
    por_canal: list[FilaVentasPorCanal]
    por_sucursal: list[FilaVentasPorSucursal]
    detalle: list[FilaVentasDetalle]


# ---- Inventario -------------------------------------------------------------------


class ReporteInventarioRespuesta(BaseModel):
    consolidado: list[ConsolidadoRespuesta]
    alertas: list[ConsolidadoRespuesta]
    valuacion: list[ValuacionRespuesta]


# ---- Reservas ---------------------------------------------------------------------


class FilaReservasPorEstado(BaseModel):
    codigo: str
    nombre: str
    cantidad: int


class ReporteReservasRespuesta(BaseModel):
    por_estado: list[FilaReservasPorEstado]
    tasa_conversion: float


# ---- Probador -----------------------------------------------------------------------


class FilaUsoProbador(BaseModel):
    estado: str
    cantidad: int


# ---- Dashboard ---------------------------------------------------------------------


class DashboardRespuesta(BaseModel):
    """Los 12 indicadores del enunciado, livianos (sin el detalle fila por
    fila de ventas -- eso es solo para /reportes/ventas)."""

    desde: dt.date
    hasta: dt.date
    ventas_del_periodo: Decimal
    transacciones: int
    ticket_promedio: Decimal
    margen_bruto: Decimal
    top_productos: list[FilaTopProducto]
    ventas_por_canal: list[FilaVentasPorCanal]
    ventas_por_sucursal: list[FilaVentasPorSucursal]
    valor_inventario_total: Decimal
    variantes_bajo_minimo: int
    reservas_por_estado: list[FilaReservasPorEstado]
    tasa_conversion_reservas: float
    uso_probador: list[FilaUsoProbador]


# ---- Resumen de la pantalla de inicio del personal ---------------------------------------
# Una sola respuesta con lo de HOY (día de Bolivia). Cada sección es null cuando el usuario no tiene el permiso de esa
# parte o el plan de la empresa no la incluye: la pantalla simplemente no la dibuja.


class PrendaVendidaInicio(BaseModel):
    variante_id: int
    nombre: str
    cantidad: int


class VentaRecienteInicio(BaseModel):
    id: int
    codigo: str
    fecha: FechaUTC
    total: Decimal
    estado: str
    unidades_vendidas: int
    unidades_devueltas: int = 0


class ResumenVentasInicio(BaseModel):
    tickets: int
    total_ventas: Decimal
    por_cobrar_cantidad: int
    por_cobrar_total: Decimal
    mas_vendidas: list[PrendaVendidaInicio]
    recientes: list[VentaRecienteInicio]


class AlertaStockInicio(BaseModel):
    producto_id: int
    variante_id: int
    producto: str
    stock_minimo: int
    cantidad_disponible: int
    imagen: str | None = None


class ResumenStockInicio(BaseModel):
    total_alertas: int
    alertas: list[AlertaStockInicio]


class ResumenReservasInicio(BaseModel):
    total: int
    por_estado: list[FilaReservasPorEstado]


class ResumenInicioRespuesta(BaseModel):
    fecha: dt.date
    sucursal_id: int | None  # null = todas las sucursales (administrador)
    sucursal_nombre: str
    ventas: ResumenVentasInicio | None = None
    stock: ResumenStockInicio | None = None
    reservas: ResumenReservasInicio | None = None


# ---- Reportes generativos ---------------------------------------------------------
# CU-23 (E09). Un solo modelo, SolicitudReporte, sirve para dos usos: es lo que debe
# devolver el intérprete (Groq o reglas) y lo que puede mandar el cliente ya armado.
# Por eso es estricto: extra="forbid" y SIN ningún campo de id ni de empresa. Los
# nombres de sucursales, categorías y productos se resuelven después, siempre contra
# la empresa de la sesión.

TipoPeriodo = Literal[
    "hoy",
    "ayer",
    "esta_semana",
    "semana_pasada",
    "este_mes",
    "mes_pasado",
    "este_anio",
    "anio_pasado",
    "ultimos_dias",
    "ultimas_semanas",
    "ultimos_meses",
    "mes_calendario",
    "rango_fechas",
]
CanalReporte = Literal["digital", "presencial"]
AgrupacionReporte = Literal["dia", "semana", "mes"]
OrdenReporte = Literal["mayor_a_menor", "menor_a_mayor"]
OrigenSolicitud = Literal["texto", "voz"]
TipoColumna = Literal["texto", "entero", "moneda", "porcentaje", "fecha", "booleano"]
TipoGrafico = Literal[
    "barras", "barras_horizontales", "barras_agrupadas", "linea", "torta", "tabla"
]
EstadoReporte = Literal[
    "ok", "incompleta", "ambigua", "invalida", "no_soportada", "no_disponible"
]
InterpreteUsado = Literal["groq", "reglas"]

TIPOS_PERIODO = get_args(TipoPeriodo)
CANALES_REPORTE = get_args(CanalReporte)
AGRUPACIONES_REPORTE = get_args(AgrupacionReporte)
ORDENES_REPORTE = get_args(OrdenReporte)

MAX_NOMBRES_POR_FILTRO = 5
MAX_LARGO_NOMBRE = 80
LIMITE_MINIMO = 1
LIMITE_MAXIMO = 50
MAX_LARGO_TEXTO_REPORTE = 300

NombreFiltro = Annotated[str, StringConstraints(max_length=MAX_LARGO_NOMBRE)]


class FechaParcial(BaseModel):
    """Una fecha escrita a medias ("el 5 de septiembre"). Sin año se toma el más
    reciente que no sea futuro: lo resuelve core/tiempo, nunca la IA."""

    model_config = ConfigDict(extra="forbid")

    dia: int = Field(ge=1, le=31)
    mes: int = Field(ge=1, le=12)
    anio: int | None = Field(default=None, ge=2000, le=2100)


class PeriodoSolicitado(BaseModel):
    """Periodo pedido, en términos relativos. La IA solo nombra el tipo ("este_mes",
    "mes_calendario" con mes=9, "ultimos_meses" con n=3); las fechas las calcula el
    backend. Los rangos de n y mes se validan en core/tiempo (estado "invalida"),
    no aquí, para que un valor absurdo no se confunda con un JSON mal formado."""

    model_config = ConfigDict(extra="forbid")

    tipo: TipoPeriodo
    n: int | None = None
    mes: int | None = None
    anio: int | None = None
    desde: FechaParcial | None = None
    hasta: FechaParcial | None = None


class SolicitudReporte(BaseModel):
    """Lo que el intérprete devuelve y lo que el cliente puede mandar ya armado.
    Sin ids ni empresa_id: extra="forbid" rechaza cualquier campo que no esté aquí.
    `tipo_reporte` es str libre a propósito: un código fuera del registro no es un
    error de forma sino el estado "no_soportada" (lo decide el caso de uso).
    La IA manda `null` en las listas que la frase no menciona: se toman como []."""

    model_config = ConfigDict(extra="forbid")

    tipo_reporte: str | None = Field(default=None, max_length=80)
    periodo: PeriodoSolicitado | None = None
    sucursales: list[NombreFiltro] = Field(default_factory=list, max_length=MAX_NOMBRES_POR_FILTRO)
    categorias: list[NombreFiltro] = Field(default_factory=list, max_length=MAX_NOMBRES_POR_FILTRO)
    productos: list[NombreFiltro] = Field(default_factory=list, max_length=MAX_NOMBRES_POR_FILTRO)
    canal: CanalReporte | None = None
    agrupacion: AgrupacionReporte | None = None
    orden: OrdenReporte | None = None
    limite: int | None = None  # el rango 1..50 lo valida el caso de uso (estado "invalida", no 422)
    # E12: semanas a predecir (solo los reportes de analítica). Como `limite`, el rango 1..12 lo valida el caso de
    # uso (estado "invalida"), de modo que un valor absurdo no se confunda con un JSON mal formado.
    horizonte_semanas: int | None = None
    solicitud_multiple: bool = False

    @field_validator("sucursales", "categorias", "productos", mode="before")
    @classmethod
    def _null_es_lista_vacia(cls, valor):
        return [] if valor is None else valor


class ReporteGenerativoRequest(BaseModel):
    """Cuerpo de POST /reportes-ia/ejecutar: o `texto` (escrito, o voz ya transcrita
    por el cliente) o `solicitud` ya estructurada; exactamente uno de los dos."""

    model_config = ConfigDict(extra="forbid")

    texto: str | None = Field(default=None, min_length=1, max_length=MAX_LARGO_TEXTO_REPORTE)
    solicitud: SolicitudReporte | None = None
    origen: OrigenSolicitud = "texto"

    @model_validator(mode="after")
    def _exactamente_uno(self):
        if (self.texto is None) == (self.solicitud is None):
            raise ValueError("Envía exactamente uno de 'texto' o 'solicitud'.")
        return self


class ColumnaReporte(BaseModel):
    clave: str
    titulo: str
    tipo: TipoColumna


class GraficoSugerido(BaseModel):
    """Sugerencia para el cliente: qué dibujar y con qué columnas. `tabla` = no
    graficar. Los ejes son claves de ColumnaReporte."""

    tipo: TipoGrafico
    eje_x: str | None = None
    eje_y: str | None = None
    serie: str | None = None


class ReporteEjecutado(BaseModel):
    """Resultado de un reporte. Los valores monetarios van como número JSON (float
    con 2 decimales) dentro de `filas` y `resumen`: sirven para mostrar, no para
    calcular (los totales se calculan en Decimal antes de convertir)."""

    codigo: str
    titulo: str
    columnas: list[ColumnaReporte]
    filas: list[dict[str, Any]]
    resumen: dict[str, Any] = Field(default_factory=dict)
    grafico_sugerido: GraficoSugerido
    truncado: bool = False
    generado_en: FechaUTC


class PeriodoResuelto(BaseModel):
    desde: dt.date
    hasta: dt.date
    etiqueta: str


class ReferenciaResuelta(BaseModel):
    """Un nombre ya resuelto contra la empresa de la sesión. Es de SALIDA: el id
    nunca entra por SolicitudReporte."""

    id: int
    nombre: str


class SolicitudResuelta(BaseModel):
    """La solicitud validada y con fechas e ids resueltos ("entendí esto: ..."). Es lo
    que E10 reenvía para exportar. `periodo` es None en los reportes sin periodo."""

    tipo_reporte: str
    periodo: PeriodoResuelto | None = None
    sucursales: list[ReferenciaResuelta] = Field(default_factory=list)
    categorias: list[ReferenciaResuelta] = Field(default_factory=list)
    productos: list[ReferenciaResuelta] = Field(default_factory=list)
    canal: CanalReporte | None = None
    agrupacion: AgrupacionReporte | None = None
    orden: OrdenReporte | None = None
    limite: int | None = None
    horizonte_semanas: int | None = None


class ReporteGenerativoRespuesta(BaseModel):
    """Respuesta de /interpretar y /ejecutar. Todo estado de negocio sale con HTTP 200;
    solo plan, permiso, suscripción (403), cuerpo mal formado (422) y rate limit (429)
    son errores HTTP. Con estado distinto de "ok" nunca hay `reporte`."""

    estado: EstadoReporte
    mensaje: str
    sugerencias: list[str] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)
    interprete: InterpreteUsado | None = None
    solicitud: SolicitudResuelta | None = None
    reporte: ReporteEjecutado | None = None
    narrativa: str | None = None


# ---- Exportación ----------------------------------------------------------------------------
# E10. El constructor de archivos (`exportacion.py`) solo conoce DocumentoReporte: no sabe de
# reportes generativos, de CU-22 ni de la base. Cualquier reporte (E09, los convencionales y,
# luego, los de ML) se convierte a este modelo con un adaptador y se descarga igual.

FormatoExportacion = Literal["xlsx", "pdf"]


class SeccionReporte(BaseModel):
    """Una tabla del documento (en Excel, una hoja; en PDF, una sección con su título).
    `totales` lleva solo las columnas que se suman, ya calculadas con Decimal; las que no
    aparecen se dejan vacías. `grafico` usa claves de `columnas`."""

    titulo: str
    columnas: list[ColumnaReporte]
    filas: list[dict[str, Any]]
    totales: dict[str, Any] | None = None
    grafico: GraficoSugerido | None = None
    nota: str | None = None


class DocumentoReporte(BaseModel):
    """Lo que se imprime: encabezado (título, empresa, filtros, fecha en hora de Bolivia) y
    una o más secciones. `filtros` son líneas ya redactadas ("Periodo: 01/09/2026 al 20/09/2026")."""

    titulo: str
    subtitulo: str | None = None
    empresa_nombre: str
    filtros: list[str] = Field(default_factory=list)
    generado_en: dt.datetime
    secciones: list[SeccionReporte]
    truncado: bool = False
    avisos: list[str] = Field(default_factory=list)


class ExportarReporteRequest(BaseModel):
    """Cuerpo de POST /reportes-ia/exportar: el formato y exactamente una de tres formas de
    pedir el reporte. `texto` y `solicitud` son los de /ejecutar. `resuelta` es la
    `solicitud` que devolvió /ejecutar ("entendí esto"): se reenvía tal cual y no vuelve a
    pasar por el intérprete; sus ids se ignoran (se vuelven a resolver los nombres contra la
    empresa de la sesión)."""

    model_config = ConfigDict(extra="forbid")

    formato: FormatoExportacion
    texto: str | None = Field(default=None, min_length=1, max_length=MAX_LARGO_TEXTO_REPORTE)
    solicitud: SolicitudReporte | None = None
    resuelta: SolicitudResuelta | None = None
    incluir_grafico: bool = True

    @model_validator(mode="after")
    def _exactamente_uno(self):
        if sum(valor is not None for valor in (self.texto, self.solicitud, self.resuelta)) != 1:
            raise ValueError("Envía exactamente uno de 'texto', 'solicitud' o 'resuelta'.")
        return self


# ---- Analítica ML (CU-24, E12) -----------------------------------------------------------------
# Pensados para que la pantalla dibuje sin transformar nada. Todas las cifras son números JSON; nunca salen el
# artefacto del modelo, sus bytes ni ids de clientes. La `interpretacion` son frases en español por plantilla.

TipoModeloAnalitico = Literal["demanda_semanal", "segmentos_rfm", "anomalias_ventas"]
EstadoVigenciaModelo = Literal["sin_entrenar", "vigente", "desactualizado", "obsoleto"]
EstadoEntrenamiento = Literal["entrenado", "datos_insuficientes"]


class PuntoSerie(BaseModel):
    """Un punto de una serie para graficar. `etiqueta` es la fecha ISO del lunes de la semana (o el valor de k en las
    curvas). `minimo` y `maximo` forman la banda de la predicción: es un rango estimado (±RMSE), NO un intervalo de
    confianza."""

    etiqueta: str
    valor: float
    minimo: float | None = None
    maximo: float | None = None
    es_prediccion: bool = False


class KpiAnalitico(BaseModel):
    clave: str
    titulo: str
    valor: float | str | None
    unidad: str | None = None
    interpretacion: str | None = None


class EstadoModelo(BaseModel):
    tipo: TipoModeloAnalitico
    titulo: str
    entrenado: bool
    estado: EstadoVigenciaModelo
    version: int | None = None
    entrenado_en: FechaUTC | None = None
    filas_entrenamiento: int | None = None
    datos_desde: dt.date | None = None
    datos_hasta: dt.date | None = None
    metricas: dict[str, Any] = Field(default_factory=dict)
    mensaje: str


class DatosDisponibles(BaseModel):
    semanas_con_ventas: int
    categorias_con_ventas: int
    clientes_con_compras: int


class EstadoAnalitica(BaseModel):
    modelos: list[EstadoModelo]
    datos: DatosDisponibles
    puede_entrenar: dict[str, bool]
    interpretacion: list[str] = Field(default_factory=list)


class EntrenarRequest(BaseModel):
    """`tipos` ausente o vacío = todos los que hay. Un tipo desconocido se rechaza con 422."""

    model_config = ConfigDict(extra="forbid")

    tipos: list[TipoModeloAnalitico] | None = Field(default=None, max_length=3)


class ResultadoEntrenamiento(BaseModel):
    tipo: TipoModeloAnalitico
    estado: EstadoEntrenamiento
    version: int | None = None
    metricas: dict[str, Any] = Field(default_factory=dict)
    avisos: list[str] = Field(default_factory=list)
    motivo: str | None = None
    duracion_ms: int


class EntrenarRespuesta(BaseModel):
    resultados: list[ResultadoEntrenamiento]


class DemandaCategoria(BaseModel):
    categoria_id: int | None  # None = el total de la empresa
    categoria: str
    historico: list[PuntoSerie]  # las últimas 12 semanas reales
    prediccion: list[PuntoSerie]
    total_predicho: int
    variacion_pct_vs_ultimas_semanas: float | None = None


class MetricasDemanda(BaseModel):
    mae: float | None = None
    rmse: float | None = None
    r2: float | None = None
    mae_base: float | None = None
    rmse_base: float | None = None
    r2_base: float | None = None
    mejora_mae_pct: float | None = None
    modelo_elegido: str | None = None


class DemandaRespuesta(BaseModel):
    horizonte_semanas: int
    modelo: EstadoModelo
    categorias: list[DemandaCategoria]
    total_empresa: DemandaCategoria
    metricas: MetricasDemanda
    supuestos: list[str]
    interpretacion: list[str]
    grafico_sugerido: GraficoSugerido
    avisos: list[str] = Field(default_factory=list)


class SegmentoCliente(BaseModel):
    id: int
    nombre: str
    descripcion: str
    accion_sugerida: str
    clientes: int
    porcentaje_clientes: float
    recencia_media_dias: float
    frecuencia_media: float
    monto_medio: float
    monto_total: float
    porcentaje_monto: float


class PuntoDispersion(BaseModel):
    """Un cliente anónimo en el gráfico de dispersión: nunca lleva su id."""

    segmento_id: int
    frecuencia: int
    monto: float


class SegmentosRespuesta(BaseModel):
    modelo: EstadoModelo
    k: int
    silhouette: float | None
    clientes_segmentados: int
    segmentos: list[SegmentoCliente]
    dispersion: list[PuntoDispersion]  # muestra determinista de a lo sumo 300 puntos
    curva_silhouette: list[PuntoSerie]
    curva_codo: list[PuntoSerie]
    supuestos: list[str]
    interpretacion: list[str]
    grafico_sugerido: GraficoSugerido
    avisos: list[str] = Field(default_factory=list)


SeveridadAnomalia = Literal["leve", "fuerte"]
EstadoReposicion = Literal["critico", "atencion", "ok"]


class AnomaliaVenta(BaseModel):
    """Un día de una sucursal con ventas inusuales respecto a lo esperado. `desviacion_pct` es positiva si vendió más
    de lo esperado y negativa si vendió menos."""

    fecha: dt.date
    sucursal_id: int
    sucursal: str
    total_ventas: float
    esperado: float
    desviacion_pct: float
    severidad: SeveridadAnomalia


class AnomaliasRespuesta(BaseModel):
    modelo: EstadoModelo
    dias: int
    desde: dt.date
    hasta: dt.date
    anomalias: list[AnomaliaVenta]
    total: int
    fuertes: int
    supuestos: list[str]
    interpretacion: list[str]
    grafico_sugerido: GraficoSugerido
    avisos: list[str] = Field(default_factory=list)


class ItemReposicion(BaseModel):
    categoria_id: int
    categoria: str
    disponible: int
    demanda_semanal_promedio: float
    semanas_cobertura: float | None  # None = sin demanda prevista (cobertura infinita)
    agotado_en_semana: int | None
    estado: EstadoReposicion
    sugerencia_unidades: int  # orientativa, con 10% de colchón


class ReposicionRespuesta(BaseModel):
    modelo: EstadoModelo
    semanas: int
    items: list[ItemReposicion]
    criticos: int
    supuestos: list[str]
    interpretacion: list[str]
    grafico_sugerido: GraficoSugerido
    avisos: list[str] = Field(default_factory=list)


class PanelAnalitico(BaseModel):
    """Todo junto para el dashboard. Un bloque es None si ese modelo aún no está entrenado (su aviso va en `avisos`)."""

    estado: EstadoAnalitica
    kpis: list[KpiAnalitico]
    demanda: DemandaRespuesta | None = None
    segmentos: SegmentosRespuesta | None = None
    anomalias: AnomaliasRespuesta | None = None
    reposicion: ReposicionRespuesta | None = None
    avisos: list[str] = Field(default_factory=list)
