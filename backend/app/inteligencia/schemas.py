from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.catalogo.schemas import CatalogoItemRespuesta, FiltrosCatalogo

# Los únicos valores que catalogo.schemas.Genero acepta. FiltrosVoz recibe el
# género tal cual lo devuelve Groq (str libre, no el Literal), porque un
# valor fuera de esta lista no debe tirar abajo la validación de todo el
# JSON -- se descarta ese campo puntual en el service, no la respuesta entera.
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


# ---- Recomendador (P6.2) ------------------------------------------------------


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


# ---- Reporte por voz (P6.3) ----------------------------------------------------

TIPOS_REPORTE_VALIDOS = {"ventas", "inventario", "reservas", "dashboard"}


class ReporteVozRequest(BaseModel):
    texto: str = Field(min_length=1, max_length=300)


class FiltrosReporteVoz(BaseModel):
    """Contrato exacto que debe devolver Groq: qué reporte y con qué
    filtros -- nunca SQL, nunca texto libre que se ejecute. `tipo_reporte`
    es uno de los 4 valores fijos; los filtros son nombres/fechas que
    `inteligencia.casos_uso.cu38_generar_reporte_comando_voz` resuelve a id
    antes de llamar a `reportes`."""

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
