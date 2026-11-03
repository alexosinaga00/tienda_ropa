"""CU-23 (E09) — Intérprete de reportes por reglas de palabras clave.

Determinístico y sin red: es el respaldo cuando Groq no responde (sin clave, timeout,
JSON inválido) y lo que mantiene viva la demo. Normaliza el texto (minúsculas, sin tildes,
sin signos) y lo mapea a una `SolicitudReporte` del mismo esquema que usa Groq: nunca
produce campos fuera de él ni ids.

Reglas de prioridad (la primera que aplica gana):
  1. texto hostil (inyección, SQL, datos de otros, credenciales)      -> sin tipo
  2. "que tan bueno es el modelo", "metricas del modelo", ...           -> metricas_modelos       (E12)
  3. "segment", "clientes valiosos", "rfm", "tipos de clientes", ...   -> segmentacion_clientes  (E12)
  4. "reposicion", "reponer", "van a agotar", "me quedo sin", ...      -> reposicion_sugerida    (E12)
  5. "anomalia", "atipico", "inusual", "dias raros", ...               -> anomalias_ventas       (E12)
  6. "predic", "pronostic", "proyecc", "cuanto voy a vender", ...      -> prediccion_demanda     (E12)
  7. "compar"                                                          -> comparacion_sucursales
  8. existencia / poco stock                                           -> productos_menor_existencia
  9. "categoria" + ingresos / ventas                                   -> ingresos_por_categoria
 10. más/menos vendidos, top, mejores                                  -> productos_mas_vendidos
 11. "por semana", "diario", "mensual", "por mes", ...                 -> ventas_por_periodo
 12. "sucursal" (o nombre de una sucursal) + ventas                    -> ventas_por_sucursal
 13. "grafico de ventas" / evolución                                   -> ventas_por_periodo
Las cinco reglas de analítica van primero porque sus frases suelen nombrar también "ventas", "demanda" o "modelo"
("que tan bueno es el modelo de prediccion" debe ser métricas, no predicción), y las métricas antes que la predicción.
"evaluacion", "precision" o "metricas" solos NO bastan (chocarían con frases de ventas): deben ir con "modelo",
"prediccion", "algoritmo" o "segmentacion".
Si nada aplica o hay dudas, los campos quedan en null/vacío y la validación posterior del
caso de uso pide aclarar. El tipo detectado NO se filtra por plan: eso lo decide el caso de uso.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import ValidationError

from app.core.texto import normalizar_texto
from app.inteligencia.groq_cliente import InterpreteReportesBase, ResultadoInterpretacion
from app.inteligencia.schemas import (
    MAX_NOMBRES_POR_FILTRO,
    PeriodoSolicitado,
    SolicitudReporte,
)

ORIGEN = "reglas"
_MAX_LARGO_NOMBRE = 80

_NUMEROS_PALABRA = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13,
    "catorce": 14, "quince": 15, "veinte": 20, "treinta": 30,
}  # fmt: skip
_NUM = r"(\d{1,6}|" + "|".join(sorted(_NUMEROS_PALABRA, key=len, reverse=True)) + r")"

_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
}  # fmt: skip

# Palabras que, justo después de un número, indican "cuántas filas" (y no un periodo).
_SUSTANTIVOS_LIMITE = (
    r"(?:productos?|prendas?|articulos?|items?|referencias?|categorias?|sucursales|"
    r"mejores|peores|primeros|primeras|mas)"
)

_HOSTIL = re.compile(
    r"\b(ignora\w*|ignore|olvida\w*|instruccion\w*|prompt|system|sistema operativo|"
    r"contrasena\w*|password|clave\w*|token|credencial\w*|api key|apikey|usuarios?|"
    r"empresa id|otras? empresas?|todas las empresas|todos los tenants?)\b"
    r"|\b(select|insert|update|delete|drop|truncate|alter|union)\b.*\b(from|table|into|set|where|select)\b"
    r"|\bdrop\s+table\b|\bor\s+1\s*=\s*1\b",
)
_HOSTIL_CRUDO = re.compile(r"--|/\*|\*/|<script|\$\{|\{\{")

# Analítica (E12). Ver el orden de prioridad en el docstring del módulo.
_SUJETO_DEL_MODELO = r"(?:modelos?|prediccion\w*|predicciones|algoritmos?|pronostico\w*|segmentacion)"
_RE_METRICAS = re.compile(
    rf"\bque tan (?:bueno|buena|preciso|precisa|confiable|acertad[oa])\w*\b.{{0,40}}\b{_SUJETO_DEL_MODELO}\b"
    rf"|\bmetricas?\b.{{0,30}}\b{_SUJETO_DEL_MODELO}\b"
    rf"|\b(?:precision|evaluacion|confiabilidad|calidad|exactitud|acierto|error)\s+(?:de|del|de los|de la|de las)\s+"
    rf"(?:(?:los|la|las)\s+)?{_SUJETO_DEL_MODELO}\b"
    rf"|\bevaluar\b.{{0,20}}\b{_SUJETO_DEL_MODELO}\b"
)
_RE_SEGMENTACION = re.compile(
    r"\bsegment\w*|\bclientes? valios\w*|\brfm\b|\btipos? de clientes\b|\bclientes? vip\b|\bgrupos? de clientes\b"
)
_RE_PREDICCION = re.compile(r"\bpredic\w*|\bpronostic\w*|\bproyecc\w*|\bdemanda futura\b|\bcuanto voy a vender\b")
_RE_ANOMALIAS = re.compile(
    r"\banomali\w*|\batipic\w*|\binusual\w*|\bdias? (?:raros?|extranos?)\b|\bventas? (?:raras?|extranas?)\b"
)
# Reposición: solo el futuro ("se me van a agotar"); "por agotarse" / "agotado" son del reporte de existencias.
_RE_REPOSICION = re.compile(
    r"\breposicion\b|\brepon\w+|\bme quedo sin\b|\bvan a agotar\w*|\bse agotar\w+|\bvoy a quedar\w* sin\b"
)

_RE_HORIZONTE_SEMANAS = re.compile(rf"\b(?:proxim[oa]s?|siguientes?)\s+{_NUM}\s+semanas?\b")
_RE_HORIZONTE_MESES = re.compile(rf"\b(?:proxim[oa]s?|siguientes?)\s+{_NUM}\s+mes(?:es)?\b")
_RE_PROXIMA_SEMANA = re.compile(r"\b(?:proxima|siguiente) semana\b|\bsemana (?:que viene|siguiente|proxima)\b")
_RE_PROXIMO_MES = re.compile(r"\b(?:proximo|siguiente) mes\b|\bmes (?:que viene|siguiente|proximo)\b")

_RE_COMPARAR = re.compile(r"\bcompar\w*")
_RE_EXISTENCIA = re.compile(
    r"menor(?:es)? existencia\w*|\bexistencias?\b|poco stock|pocas? unidades|stock bajo|bajo stock|"
    r"menos stock|stock minimo|sin stock|agotad\w+|por agotarse|inventario bajo"
)
_RE_CATEGORIA = re.compile(r"\bcategori\w+")
_RE_DINERO = re.compile(r"ingres\w*|\bvent\w*|vend\w*|factur\w*|recaud\w*")
_RE_TOP = re.compile(r"(?:mas|menos) vendid\w+|\btop\b|\bmejores\b|\bpeores\b|ranking")
_RE_PRODUCTO = re.compile(r"\b(?:producto|prenda|articulo|item|polera|camisa|chamarra)\w*")
_RE_PERIODO_FUERTE = re.compile(
    r"por semana|semanal\w*|por dia\b|diari\w+|\bmensual\w*|por mes\b|cada (?:dia|semana|mes)\b|"
    r"evolucion|tendencia|a lo largo"
)
_RE_SUCURSAL = re.compile(r"\bsucursal\w*")
_RE_VENTAS = re.compile(r"\bvent\w*|\bvend\w*|factur\w*|ingres\w*|recaud\w*")
_RE_GRAFICO_VENTAS = re.compile(r"grafic\w* (?:de )?(?:las )?ventas|ventas en grafico")

_RE_ORDEN_MENOR = re.compile(
    r"menos vend\w*|menos ingres\w*|\bmenor(?:es)?\b|\bpeor(?:es)?\b|\bmas bajos?\b|\bde menor a mayor\b"
)
_RE_ORDEN_MAYOR = re.compile(r"\bmayor(?:es)?\b|mas vendid\w+|\bmejor(?:es)?\b|\btop\b|\bde mayor a menor\b")

_RE_CANAL_DIGITAL = re.compile(r"\bdigital(?:es)?\b|\bonline\b|en linea|\becommerce\b|e commerce|\bvirtual(?:es)?\b")
_RE_CANAL_PRESENCIAL = re.compile(r"\bpresencial(?:es)?\b|en tienda|en mostrador|\bfisic[oa]s?\b")

_RE_AGRUPACION = (
    ("dia", re.compile(r"por dia\b|diari\w+|cada dia\b")),
    ("semana", re.compile(r"por semana|semanal\w*|cada semana\b")),
    ("mes", re.compile(r"por mes\b|\bmensual\w*|cada mes\b")),
)

_RE_ULTIMOS = re.compile(
    rf"\bultim[oa]s?\s+(?:{_NUM}\s+)?(dias?|semanas?|mes(?:es)?|anos?|anios?)\b"
)
_RE_TOP_N = re.compile(rf"\btop\s+{_NUM}\b")
_RE_NUM_SUSTANTIVO = re.compile(rf"\b{_NUM}\s+{_SUSTANTIVOS_LIMITE}\b")
_RE_ANIO = re.compile(r"\b(20\d{2})\b")


def _valor_numero(token: str) -> int:
    return int(token) if token.isdigit() else _NUMEROS_PALABRA[token]


def _preparar(texto: str) -> str:
    """Normaliza y deja solo letras, dígitos y espacios simples, con un espacio a cada
    extremo no: las expresiones usan \\b, no hace falta."""
    return re.sub(r"[^a-z0-9]+", " ", normalizar_texto(texto)).strip()


def _es_hostil(crudo: str, limpio: str) -> bool:
    return bool(_HOSTIL.search(limpio) or _HOSTIL_CRUDO.search(crudo))


def _detectar_tipo(t: str, hay_sucursal_nombrada: bool) -> str | None:
    if _RE_METRICAS.search(t):
        return "metricas_modelos"
    if _RE_SEGMENTACION.search(t):
        return "segmentacion_clientes"
    if _RE_REPOSICION.search(t):
        return "reposicion_sugerida"
    if _RE_ANOMALIAS.search(t):
        return "anomalias_ventas"
    if _RE_PREDICCION.search(t):
        return "prediccion_demanda"
    if _RE_COMPARAR.search(t):
        return "comparacion_sucursales"
    if _RE_EXISTENCIA.search(t):
        return "productos_menor_existencia"
    if _RE_CATEGORIA.search(t) and _RE_DINERO.search(t):
        return "ingresos_por_categoria"
    if _RE_TOP.search(t):
        # "mejores sucursales" / "sucursal con mas ventas": ranking de sucursales, no de productos.
        if not (_RE_SUCURSAL.search(t) and not _RE_PRODUCTO.search(t)):
            return "productos_mas_vendidos"
    if _RE_PERIODO_FUERTE.search(t):
        return "ventas_por_periodo"
    if (_RE_SUCURSAL.search(t) or hay_sucursal_nombrada) and _RE_VENTAS.search(t):
        return "ventas_por_sucursal"
    if _RE_GRAFICO_VENTAS.search(t):
        return "ventas_por_periodo"
    return None


def _detectar_periodo(t: str) -> PeriodoSolicitado | None:
    m = _RE_ULTIMOS.search(t)
    if m:
        numero, unidad = m.group(1), m.group(2)
        if numero is not None:
            n = _valor_numero(numero)
            if unidad.startswith("dia"):
                return PeriodoSolicitado(tipo="ultimos_dias", n=n)
            if unidad.startswith("semana"):
                return PeriodoSolicitado(tipo="ultimas_semanas", n=n)
            if unidad.startswith("mes"):
                return PeriodoSolicitado(tipo="ultimos_meses", n=n)
            return PeriodoSolicitado(tipo="ultimos_dias", n=n * 365)
        # Sin número y en singular ("el ultimo mes"): ventana móvil equivalente. En plural
        # sin número ("los ultimos meses") no hay forma de saber cuántos: sin periodo.
        if unidad == "semana":
            return PeriodoSolicitado(tipo="ultimos_dias", n=7)
        if unidad == "mes":
            return PeriodoSolicitado(tipo="ultimos_dias", n=30)
        if unidad in ("ano", "anio"):
            return PeriodoSolicitado(tipo="ultimos_dias", n=365)
        return None
    if re.search(r"\bmes (?:pasado|anterior)\b", t):
        return PeriodoSolicitado(tipo="mes_pasado")
    if re.search(r"\bsemana (?:pasada|anterior)\b", t):
        return PeriodoSolicitado(tipo="semana_pasada")
    if re.search(r"\b(?:ano|anio) (?:pasado|anterior)\b", t):
        return PeriodoSolicitado(tipo="anio_pasado")
    if re.search(r"\b(?:esta semana|semana actual)\b", t):
        return PeriodoSolicitado(tipo="esta_semana")
    if re.search(r"\b(?:este mes|mes actual|del mes)\b", t):
        return PeriodoSolicitado(tipo="este_mes")
    if re.search(r"\b(?:este (?:ano|anio)|(?:ano|anio) actual|en lo que va del (?:ano|anio))\b", t):
        return PeriodoSolicitado(tipo="este_anio")
    if re.search(r"\bayer\b", t):
        return PeriodoSolicitado(tipo="ayer")
    if re.search(r"\bhoy\b", t):
        return PeriodoSolicitado(tipo="hoy")
    for nombre, numero in _MESES.items():
        m = re.search(rf"\b{nombre}\b(?:\s+(?:de|del)?\s*(20\d{{2}}))?", t)
        if m:
            anio = int(m.group(1)) if m.group(1) else None
            return PeriodoSolicitado(tipo="mes_calendario", mes=numero, anio=anio)
    return None


def _detectar_limite(t: str) -> int | None:
    m = _RE_TOP_N.search(t) or _RE_NUM_SUSTANTIVO.search(t)
    return _valor_numero(m.group(1)) if m else None


def _detectar_horizonte(t: str) -> int | None:
    """Semanas hacia adelante: "las proximas 8 semanas" -> 8, "los proximos 2 meses" -> 8 (N*4), "la proxima semana"
    -> 1 y "el proximo mes" -> 4. Sin número ("las proximas semanas") no adivina. El rango 1..12 lo valida el caso
    de uso (un valor de más es "invalida", no se recorta en silencio)."""
    m = _RE_HORIZONTE_SEMANAS.search(t)
    if m:
        return _valor_numero(m.group(1))
    m = _RE_HORIZONTE_MESES.search(t)
    if m:
        return _valor_numero(m.group(1)) * 4
    if _RE_PROXIMA_SEMANA.search(t):
        return 1
    if _RE_PROXIMO_MES.search(t):
        return 4
    return None


def _detectar_agrupacion(t: str) -> str | None:
    for valor, patron in _RE_AGRUPACION:
        if patron.search(t):
            return valor
    return None


def _detectar_canal(t: str) -> str | None:
    digital = bool(_RE_CANAL_DIGITAL.search(t))
    presencial = bool(_RE_CANAL_PRESENCIAL.search(t))
    if digital == presencial:  # ninguno o los dos: sin canal
        return None
    return "digital" if digital else "presencial"


def _buscar_nombres(t: str, nombres: Iterable[str], ocupado: list[tuple[int, int]]) -> list[str]:
    """Nombres de `nombres` que aparecen completos en el texto ya preparado `t` (como
    palabra o frase). Gana el más largo: 'Centro' no cuenta si el texto dice 'Centro Norte'
    y 'Centro Norte' es otro nombre de la lista. Conserva el nombre original de la lista."""
    candidatos: list[tuple[str, str]] = []
    for original in nombres:
        if not isinstance(original, str) or not original.strip() or len(original) > _MAX_LARGO_NOMBRE:
            continue
        limpio = _preparar(original)
        if limpio:
            candidatos.append((original, limpio))
    candidatos.sort(key=lambda par: len(par[1]), reverse=True)

    encontrados: list[str] = []
    for original, limpio in candidatos:
        m = re.search(rf"(?<![a-z0-9]){re.escape(limpio)}(?![a-z0-9])", t)
        if not m:
            continue
        inicio, fin = m.span()
        if any(inicio < f and i < fin for i, f in ocupado):
            continue
        ocupado.append((inicio, fin))
        if original not in encontrados:
            encontrados.append(original)
    return encontrados[:MAX_NOMBRES_POR_FILTRO]


_RE_SUCURSAL_NOMBRADA = re.compile(r"(?<![a-z0-9])sucursal\s+([a-z0-9]+)(?![a-z0-9])")
# Palabras que pueden seguir a "sucursal" sin ser el nombre de una ("ventas por sucursal este mes").
_NO_ES_NOMBRE = frozenset(
    "a al con cada de del durante en es este esta estos estas hoy ayer la las lo los mas menos mes meses semana semanas "
    "dia dias anio anios ano anos o para pasado pasada por que se sea sin su sus todas todos un una un y ultimo ultima "
    "ultimos ultimas vendio vendida vendidas vendidos ventas venta total mayor menor mejor mejores peor agrupada agrupadas "
    "semanal mensual diaria diario grafico enero febrero marzo abril mayo junio julio agosto septiembre setiembre "
    "octubre noviembre diciembre".split()
)


def _sucursal_no_listada(t: str) -> list[str]:
    """Un nombre dicho después de "sucursal" que no está en la lista de la empresa ("ventas de la sucursal
    Marte"): se devuelve tal cual para que el caso de uso responda "ambigua" con las sucursales reales, en
    vez de mostrar las ventas de todas sin avisar."""
    for m in _RE_SUCURSAL_NOMBRADA.finditer(t):
        if m.group(1) not in _NO_ES_NOMBRE:
            return [m.group(1)]
    return []


class InterpreteReportesReglas(InterpreteReportesBase):
    nombre = "reglas"

    def interpretar(
        self,
        texto: str,
        funcionalidades: Iterable[str] = (),
        *,
        nombres_sucursales: Iterable[str] = (),
        nombres_categorias: Iterable[str] = (),
        con_alcance_global: bool = True,
    ) -> ResultadoInterpretacion:
        """`funcionalidades` y `con_alcance_global` se aceptan por compatibilidad con la base y no se usan: el tipo
        detectado no se filtra por plan (lo decide el caso de uso, con su 403)."""
        try:
            return ResultadoInterpretacion(
                self._armar(texto or "", nombres_sucursales, nombres_categorias), ORIGEN, None
            )
        except (ValidationError, ValueError, TypeError):  # defensivo: no debería ocurrir
            return ResultadoInterpretacion(None, ORIGEN, "esquema_invalido")

    @staticmethod
    def _armar(texto: str, nombres_sucursales: Iterable[str], nombres_categorias: Iterable[str]) -> SolicitudReporte:
        t = _preparar(texto)
        if not t or _es_hostil(texto, t):
            return SolicitudReporte()

        ocupado: list[tuple[int, int]] = []
        sucursales = _buscar_nombres(t, nombres_sucursales, ocupado) or _sucursal_no_listada(t)
        categorias = _buscar_nombres(t, nombres_categorias, ocupado)

        tipo = _detectar_tipo(t, hay_sucursal_nombrada=bool(sucursales))
        if tipo is None:
            return SolicitudReporte()

        orden = None
        if _RE_ORDEN_MENOR.search(t):
            orden = "menor_a_mayor"
        elif _RE_ORDEN_MAYOR.search(t):
            orden = "mayor_a_menor"
        # El orden solo tiene sentido en los rankings; en el resto sería un filtro de más.
        if tipo not in ("productos_mas_vendidos", "ingresos_por_categoria"):
            orden = None

        return SolicitudReporte(
            tipo_reporte=tipo,
            periodo=_detectar_periodo(t),
            sucursales=sucursales,
            categorias=categorias,
            canal=_detectar_canal(t),
            agrupacion=_detectar_agrupacion(t),
            orden=orden,
            limite=_detectar_limite(t),
            horizonte_semanas=_detectar_horizonte(t),
        )


def obtener_interprete_reglas() -> InterpreteReportesBase:
    return InterpreteReportesReglas()
