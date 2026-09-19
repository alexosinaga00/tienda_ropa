from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EstadoVentaCodigo = Literal["pendiente_pago", "pagada", "entregada", "anulada"]
CanalVenta = Literal["digital", "presencial"]
TipoPromocion = Literal["porcentaje", "monto"]

# ---- Carrito -------------------------------------------------------------------


class CarritoDetalleCrear(BaseModel):
    variante_id: int
    cantidad: int = Field(default=1, gt=0)


class CarritoDetalleActualizar(BaseModel):
    cantidad: int = Field(gt=0)


class CarritoDetalleRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    variante_id: int
    cantidad: int
    precio_unitario: Decimal
    subtotal: Decimal
    # False si la variante se dio de baja después de agregarla: la línea se
    # sigue mostrando (para que el cliente la quite) pero no suma al
    # subtotal del carrito ni se puede comprar.
    disponible: bool = True


class CarritoRespuesta(BaseModel):
    id: int
    cliente_id: int
    sucursal_id: int | None
    actualizado_en: dt.datetime
    detalle: list[CarritoDetalleRespuesta]
    subtotal: Decimal


class CarritoResumenLinea(BaseModel):
    variante_id: int
    cantidad: int
    precio_unitario: Decimal
    descuento_unitario: Decimal
    subtotal: Decimal


class CarritoResumenRespuesta(BaseModel):
    """Vista previa de lo que costaría el carrito si se convirtiera en
    venta ahora mismo, con las promociones vigentes ya aplicadas. No hay
    código de cupón: la promoción se aplica sola según `promocion_alcance`
    (producto/categoría/temporada), así que esto es un recálculo, no un
    canje."""

    lineas: list[CarritoResumenLinea]
    subtotal: Decimal
    descuento: Decimal
    total: Decimal


# ---- Promociones ----------------------------------------------------------------


class PromocionAlcanceCrear(BaseModel):
    producto_id: int | None = None
    categoria_id: int | None = None
    temporada_id: int | None = None

    @model_validator(mode="after")
    def _un_solo_alcance(self) -> "PromocionAlcanceCrear":
        cantidad = sum(x is not None for x in (self.producto_id, self.categoria_id, self.temporada_id))
        if cantidad != 1:
            raise ValueError("Cada alcance necesita exactamente uno de producto_id, categoria_id o temporada_id")
        return self


class PromocionCrear(BaseModel):
    nombre: str = Field(max_length=80)
    tipo: TipoPromocion
    valor: Decimal = Field(gt=0)
    fecha_inicio: dt.date
    fecha_fin: dt.date
    alcances: list[PromocionAlcanceCrear] = Field(min_length=1)

    @model_validator(mode="after")
    def _fechas_validas(self) -> "PromocionCrear":
        if self.fecha_fin < self.fecha_inicio:
            raise ValueError("fecha_fin no puede ser anterior a fecha_inicio")
        if self.tipo == "porcentaje" and self.valor > 100:
            raise ValueError("Una promoción por porcentaje no puede superar 100")
        return self


class PromocionActualizar(BaseModel):
    nombre: str | None = Field(default=None, max_length=80)
    valor: Decimal | None = Field(default=None, gt=0)
    fecha_inicio: dt.date | None = None
    fecha_fin: dt.date | None = None
    activo: bool | None = None


class PromocionAlcanceRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    producto_id: int | None
    categoria_id: int | None
    temporada_id: int | None


class PromocionRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    tipo: TipoPromocion
    valor: Decimal
    fecha_inicio: dt.date
    fecha_fin: dt.date
    activo: bool
    alcances: list[PromocionAlcanceRespuesta]


# ---- Ventas ---------------------------------------------------------------------


class VentaDetalleLinea(BaseModel):
    variante_id: int
    cantidad: int = Field(gt=0)


class VentaPresencialCrear(BaseModel):
    sucursal_id: int
    # Si viene reserva_id, el detalle se ignora: las líneas son las de la
    # reserva marcadas seleccionada=True (ver ventas.politicas.registrar_venta).
    detalle: list[VentaDetalleLinea] = Field(default_factory=list)
    reserva_id: int | None = None
    cliente_id: int | None = None


class VentaDigitalCrear(BaseModel):
    """Sin `detalle`: la venta digital sale del carrito persistente del
    cliente logueado, no de líneas sueltas en el body."""

    sucursal_id: int
    # Lo que devolvió POST /envios/cotizar en el checkout. No es confiable
    # (lo manda el cliente): CU-42 lo recalcula al crear el envío y lo
    # rechaza si no coincide con la tarifa real de la zona.
    costo_envio: Decimal = Field(default=Decimal("0"), ge=0)
    reserva_id: int | None = None


class VentaDetalleRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    variante_id: int
    cantidad: int
    precio_unitario: Decimal
    descuento_unitario: Decimal
    costo_unitario: Decimal | None
    subtotal: Decimal


class VentaRespuesta(BaseModel):
    id: int
    codigo: str
    canal: CanalVenta
    cliente_id: int | None
    sucursal_id: int
    cajero_id: int | None
    reserva_id: int | None
    estado: EstadoVentaCodigo
    fecha: dt.datetime
    subtotal: Decimal
    descuento: Decimal
    costo_envio: Decimal
    total: Decimal
    detalle: list[VentaDetalleRespuesta]

    @classmethod
    def from_modelo(cls, venta, estados_por_id: dict[int, str]) -> "VentaRespuesta":
        return cls(
            id=venta.id,
            codigo=venta.codigo,
            canal=venta.canal,
            cliente_id=venta.cliente_id,
            sucursal_id=venta.sucursal_id,
            cajero_id=venta.cajero_id,
            reserva_id=venta.reserva_id,
            estado=estados_por_id[venta.estado_id],
            fecha=venta.fecha,
            subtotal=venta.subtotal,
            descuento=venta.descuento,
            costo_envio=venta.costo_envio,
            total=venta.total,
            detalle=[VentaDetalleRespuesta.model_validate(d) for d in venta.detalle],
        )


# ---- Devoluciones ----------------------------------------------------------------


class DevolucionDetalleCrear(BaseModel):
    venta_detalle_id: int
    cantidad: int = Field(gt=0)


class DevolucionCrear(BaseModel):
    venta_id: int
    motivo: str | None = Field(default=None, max_length=300)
    detalle: list[DevolucionDetalleCrear] = Field(min_length=1)


class DevolucionDetalleRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    venta_detalle_id: int
    cantidad: int


class DevolucionRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    venta_id: int
    fecha: dt.datetime
    motivo: str | None
    estado: Literal["pendiente", "aprobada", "rechazada"]
    usuario_id: int | None
    detalle: list[DevolucionDetalleRespuesta]
