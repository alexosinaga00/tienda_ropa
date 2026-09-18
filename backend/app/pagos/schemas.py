from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EstadoPagoCodigo = Literal["iniciado", "aprobado", "rechazado", "reembolsado"]
MetodoPagoCaja = Literal["efectivo", "qr", "tarjeta", "transferencia"]
MetodoPagoPasarela = Literal["libelula", "paypal", "qr_online"]


class PagoRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    venta_id: int
    monto: Decimal
    referencia_externa: str | None
    fecha: dt.datetime
    metodo_pago: str
    estado: EstadoPagoCodigo


class PagoIniciarRequest(BaseModel):
    venta_id: int
    metodo_pago: MetodoPagoPasarela


class PagoIniciarRespuesta(BaseModel):
    pago: PagoRespuesta
    url_redireccion: str


class PagoCajaRequest(BaseModel):
    venta_id: int
    metodo_pago: MetodoPagoCaja
    # Solo tiene sentido (y es obligatorio) para 'efectivo': con QR,
    # tarjeta o transferencia el monto cobrado es exacto, no hay cambio.
    monto_recibido: Decimal | None = Field(default=None, gt=0)


class PagoCajaRespuesta(BaseModel):
    pago: PagoRespuesta
    cambio: Decimal | None = None
