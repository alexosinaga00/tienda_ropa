from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MovimientoCrear(BaseModel):
    variante_id: int
    sucursal_id: int
    tipo_movimiento_codigo: str
    # Siempre positiva: el signo lo aporta el tipo de movimiento.
    cantidad: int = Field(gt=0)
    costo_unitario: Decimal | None = Field(default=None, ge=0)
    referencia_tipo: str | None = Field(default=None, max_length=25)
    referencia_id: int | None = None
    observacion: str | None = Field(default=None, max_length=300)


class MovimientoRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    variante_id: int
    sucursal_id: int
    tipo_movimiento_id: int
    tipo_movimiento_codigo: str
    cantidad: int
    costo_unitario: Decimal | None
    costo_promedio_post: Decimal | None
    saldo_post: int
    referencia_tipo: str | None
    referencia_id: int | None
    usuario_id: int | None
    observacion: str | None
    creado_en: dt.datetime

    @classmethod
    def from_modelo(cls, movimiento, tipo_codigo: str) -> "MovimientoRespuesta":
        return cls(
            id=movimiento.id,
            variante_id=movimiento.variante_id,
            sucursal_id=movimiento.sucursal_id,
            tipo_movimiento_id=movimiento.tipo_movimiento_id,
            tipo_movimiento_codigo=tipo_codigo,
            cantidad=movimiento.cantidad,
            costo_unitario=movimiento.costo_unitario,
            costo_promedio_post=movimiento.costo_promedio_post,
            saldo_post=movimiento.saldo_post,
            referencia_tipo=movimiento.referencia_tipo,
            referencia_id=movimiento.referencia_id,
            usuario_id=movimiento.usuario_id,
            observacion=movimiento.observacion,
            creado_en=movimiento.creado_en,
        )


class StockRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    variante_id: int
    sucursal_id: int
    cantidad_fisica: int
    cantidad_reservada: int
    cantidad_disponible: int
    stock_minimo: int
    stock_maximo: int | None
    costo_promedio: Decimal
    actualizado_en: dt.datetime


class TipoMovimientoRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    nombre: str
    signo: int
    afecta_costo: bool


class LimitesActualizar(BaseModel):
    stock_minimo: int | None = Field(default=None, ge=0)
    stock_maximo: int | None = Field(default=None, ge=0)


class DisponibilidadRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    variante_id: int
    sucursal_id: int
    cantidad_disponible: int


# ---- Vista vw_inventario_consolidado (también usada por /alertas) -----------


class ConsolidadoRespuesta(BaseModel):
    producto_id: int
    producto: str
    variante_id: int
    sku: str
    talla: str
    color: str
    sucursal_id: int
    sucursal: str
    cantidad_fisica: int
    cantidad_reservada: int
    cantidad_disponible: int
    stock_minimo: int
    costo_promedio: Decimal
    valor_inventario: Decimal


class ValuacionRespuesta(BaseModel):
    sucursal_id: int
    sucursal: str
    valor_total: Decimal


# ---- Ajustes ------------------------------------------------------------------


class AjusteCrear(BaseModel):
    variante_id: int
    sucursal_id: int
    # Positivo: sobrante (ajuste_positivo). Negativo: faltante (ajuste_negativo).
    cantidad: int
    observacion: str | None = Field(default=None, max_length=300)

    @field_validator("cantidad")
    @classmethod
    def _cantidad_no_puede_ser_cero(cls, valor: int) -> int:
        if valor == 0:
            raise ValueError("cantidad no puede ser cero")
        return valor


# ---- Transferencias -----------------------------------------------------------


class TransferenciaDetalleCrear(BaseModel):
    variante_id: int
    cantidad: int = Field(gt=0)


class TransferenciaDetalleRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    variante_id: int
    cantidad: int


class TransferenciaCrear(BaseModel):
    codigo: str = Field(max_length=20)
    sucursal_origen_id: int
    sucursal_destino_id: int
    detalle: list[TransferenciaDetalleCrear] = Field(min_length=1)


class TransferenciaRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    sucursal_origen_id: int
    sucursal_destino_id: int
    estado: str
    fecha_envio: dt.datetime | None
    fecha_recepcion: dt.datetime | None
    usuario_id: int | None
    detalle: list[TransferenciaDetalleRespuesta]
