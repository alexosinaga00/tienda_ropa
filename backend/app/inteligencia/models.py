from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import JSON, BigInteger, CheckConstraint, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# JSON en general (compatible con sqlite, usado en tests); JSONB solo en
# Postgres, que es lo que pide el esquema (ver probador/models.py, mismo
# patrón).
_TipoJson = JSON().with_variant(JSONB, "postgresql")


class ConsultaVoz(Base):
    """Log de cada búsqueda por voz (P6.1): qué se transcribió, qué filtros
    se aplicaron (los haya resuelto Groq o el fallback de texto plano) y
    cuántos resultados dio. `cliente_id` es nullable a propósito: la
    búsqueda por voz admite uso anónimo, igual que /catalogo/buscar."""

    __tablename__ = "consulta_voz"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("cliente.id"))
    texto_transcrito: Mapped[str] = mapped_column(Text, nullable=False)
    filtros_json: Mapped[dict | None] = mapped_column(_TipoJson)
    cantidad_resultados: Mapped[int | None]
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())


class HistorialNavegacion(Base):
    """Log de eventos de navegación (P6.2): vista, búsqueda, carrito, uso
    del probador o favorito. Alimenta la capa 2 (ponderación por historial)
    del recomendador. `cliente_id` es nullable a propósito -- el registro
    de eventos admite uso anónimo, igual que `ConsultaVoz`."""

    __tablename__ = "historial_navegacion"
    __table_args__ = (
        CheckConstraint(
            "tipo_evento IN ('vista','busqueda','carrito','probador','favorito')",
            name="ck_historial_navegacion_tipo_evento",
        ),
    )

    # BIGSERIAL en Postgres; en sqlite (tests) solo un INTEGER PRIMARY KEY
    # se autoincrementa, BIGINT no.
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("cliente.id"))
    sesion_anonima: Mapped[str | None] = mapped_column(String(64))
    producto_id: Mapped[int | None] = mapped_column(ForeignKey("producto.id"))
    variante_id: Mapped[int | None] = mapped_column(ForeignKey("producto_variante.id"))
    tipo_evento: Mapped[str] = mapped_column(String(25), nullable=False)
    creado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())


class Recomendacion(Base):
    """Log histórico de las recomendaciones finales que arma el
    recomendador (P6.2): qué variante, con qué motivo, para qué cliente.
    A diferencia de `ConsultaVoz`/`HistorialNavegacion`, `cliente_id` es
    obligatorio -- una recomendación anónima se calcula pero no se
    persiste, no hay a quién asociarla."""

    __tablename__ = "recomendacion"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("cliente.id"), nullable=False)
    variante_id: Mapped[int] = mapped_column(ForeignKey("producto_variante.id"), nullable=False)
    puntaje: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    motivo: Mapped[str | None] = mapped_column(String(200))
    generado_en: Mapped[dt.datetime] = mapped_column(server_default=func.now())
