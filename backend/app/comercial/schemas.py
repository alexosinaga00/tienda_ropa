from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.tipos import FechaUTC


# ---- Reservas ----


EstadoReservaCodigo = Literal["pendiente", "preparada", "en_prueba", "completada", "cancelada", "expirada"]

# ---- Crear -------------------------------------------------------------------


class ReservaDetalleCrear(BaseModel):
    variante_id: int
    cantidad: int = Field(default=1, gt=0)


class ReservaCrear(BaseModel):
    sucursal_id: int
    fecha_visita: dt.date
    hora_visita_desde: dt.time
    hora_visita_hasta: dt.time
    observacion: str | None = Field(default=None, max_length=300)
    detalle: list[ReservaDetalleCrear] = Field(min_length=1)


# ---- Selección -----------------------------------------------------------------


class SeleccionLinea(BaseModel):
    variante_id: int
    seleccionada: bool


class SeleccionActualizar(BaseModel):
    lineas: list[SeleccionLinea] = Field(min_length=1)


# ---- Respuestas ----------------------------------------------------------------


class ReservaDetalleRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    variante_id: int
    cantidad: int
    seleccionada: bool | None
    preparada: bool


class ReservaHistorialRespuesta(BaseModel):
    id: int
    estado: str
    usuario_id: int | None
    comentario: str | None
    creado_en: dt.datetime


class ReservaRespuesta(BaseModel):
    id: int
    codigo: str
    cliente_id: int
    sucursal_id: int
    estado: EstadoReservaCodigo
    fecha_visita: dt.date
    hora_visita_desde: dt.time
    hora_visita_hasta: dt.time
    fecha_expiracion: dt.datetime
    observacion: str | None
    creado_en: dt.datetime
    detalle: list[ReservaDetalleRespuesta]
    historial: list[ReservaHistorialRespuesta]

    @classmethod
    def from_modelo(cls, reserva, estados_por_id: dict[int, str]) -> "ReservaRespuesta":
        return cls(
            id=reserva.id,
            codigo=reserva.codigo,
            cliente_id=reserva.cliente_id,
            sucursal_id=reserva.sucursal_id,
            estado=estados_por_id[reserva.estado_id],
            fecha_visita=reserva.fecha_visita,
            hora_visita_desde=reserva.hora_visita_desde,
            hora_visita_hasta=reserva.hora_visita_hasta,
            fecha_expiracion=reserva.fecha_expiracion,
            observacion=reserva.observacion,
            creado_en=reserva.creado_en,
            detalle=[ReservaDetalleRespuesta.model_validate(d) for d in reserva.detalle],
            historial=[
                ReservaHistorialRespuesta(
                    id=h.id,
                    estado=estados_por_id[h.estado_id],
                    usuario_id=h.usuario_id,
                    comentario=h.comentario,
                    creado_en=h.creado_en,
                )
                for h in reserva.historial
            ],
        )


# ---- Ventas ----


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


# ---- Venta y comprobante --------------------------------------------------------


class VentaDetalleLinea(BaseModel):
    variante_id: int
    cantidad: int = Field(gt=0)


class VentaPresencialCrear(BaseModel):
    sucursal_id: int
    # Si viene reserva_id, el detalle se ignora: las líneas son las de la
    # reserva marcadas seleccionada=True (ver comercial.politicas.registrar_venta).
    detalle: list[VentaDetalleLinea] = Field(default_factory=list)
    reserva_id: int | None = None
    cliente_id: int | None = None


class VentaDigitalCrear(BaseModel):
    """Sin `detalle`: la venta digital sale del carrito persistente del
    cliente logueado, no de líneas sueltas en el body."""

    sucursal_id: int
    # Lo que devolvió POST /envios/cotizar en el checkout. No es confiable
    # (lo manda el cliente): CU-19 lo recalcula al crear el envío y lo
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
    # Unidades devueltas de esta venta (0 = ninguna). La devolución no cambia el estado: las pantallas lo muestran
    # junto al estado ("Con devolución (1 de 4)"). Las vendidas son la suma de `detalle[].cantidad`.
    unidades_devueltas: int = 0

    @classmethod
    def from_modelo(cls, venta, estados_por_id: dict[int, str], unidades_devueltas: int = 0) -> "VentaRespuesta":
        return cls(
            unidades_devueltas=unidades_devueltas,
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
    # Cambio de talla o color: la variante (del MISMO producto y del mismo precio) que se entrega en su lugar. Sale
    # del stock de la sucursal de la venta, en la misma transacción que el reingreso de lo devuelto. Sin esto, la
    # línea es una devolución simple.
    variante_nueva_id: int | None = None


class DevolucionCrear(BaseModel):
    venta_id: int
    motivo: str | None = Field(default=None, max_length=300)
    detalle: list[DevolucionDetalleCrear] = Field(min_length=1)


class DevolucionDetalleRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    venta_detalle_id: int
    cantidad: int
    variante_nueva_id: int | None = None


class ReposicionCambioRespuesta(BaseModel):
    """Una prenda entregada en lugar de otra en un cambio (solo en la respuesta del registro)."""

    venta_detalle_id: int
    variante_devuelta_id: int
    variante_nueva_id: int
    cantidad: int


class DevolucionRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    venta_id: int
    fecha: dt.datetime
    motivo: str | None
    estado: Literal["pendiente", "aprobada", "rechazada", "cancelada", "vencida"]
    usuario_id: int | None
    detalle: list[DevolucionDetalleRespuesta]
    # Lo que salió del stock en un cambio; vacío en una devolución simple. No se guarda en la devolución (el kardex
    # lo registra con la referencia de la devolución): lo arma el registro y solo viaja en esa respuesta.
    reposiciones: list[ReposicionCambioRespuesta] = Field(default_factory=list)
    # Verdadero si el comprobante quedó programado por correo (el comprador tiene correo y el envío está
    # configurado). No garantiza que Brevo lo entregue: el envío es en segundo plano.
    correo_programado: bool = False


# ---- Solicitud de cambio de talla o color (Etapa 2 de CU-17) ----------------------------------


EstadoSolicitudCambio = Literal["pendiente", "aprobada", "rechazada", "cancelada", "vencida"]


class SolicitudCambioLineaCrear(BaseModel):
    venta_detalle_id: int
    cantidad: int = Field(gt=0)
    # La talla o el color que el cliente quiere en su lugar (del MISMO producto y precio).
    variante_nueva_id: int


class SolicitudCambioCrear(BaseModel):
    venta_id: int
    motivo: str | None = Field(default=None, max_length=300)
    detalle: list[SolicitudCambioLineaCrear] = Field(min_length=1, max_length=20)


class SolicitudCambioRechazar(BaseModel):
    motivo: str = Field(min_length=3, max_length=300)


class SolicitudCambioLineaRespuesta(BaseModel):
    venta_detalle_id: int
    cantidad: int
    variante_devuelta_id: int
    prenda_devuelta: str
    variante_nueva_id: int | None
    prenda_nueva: str | None
    # Unidades de la prenda nueva disponibles hoy en la sucursal de la venta (informativo: no se reservan al solicitar).
    disponible_nueva: int | None = None


class SolicitudCambioRespuesta(BaseModel):
    id: int
    codigo: str
    venta_id: int
    venta_codigo: str
    sucursal_id: int
    cliente_nombre: str | None
    fecha: FechaUTC
    estado: EstadoSolicitudCambio
    motivo: str | None
    motivo_rechazo: str | None
    resuelta_en: FechaUTC | None
    # Hasta cuándo se puede aprobar: fin del plazo de cambio de la venta más la tolerancia. Pasado ese instante una
    # solicitud pendiente vence sola.
    atender_hasta: FechaUTC
    detalle: list[SolicitudCambioLineaRespuesta]
    # Verdadero si el correo (recibida, comprobante o rechazo) quedó programado; no garantiza que Brevo lo entregue.
    correo_programado: bool = False


class PlazoCambioRespuesta(BaseModel):
    """Cuánto le queda a una venta para devolver o cambiar prendas (D19). Las
    marcas van en UTC con "Z"; `vigente` es falso pasado `vence_en`."""

    venta_id: int
    fecha_venta: FechaUTC
    plazo_horas: int
    vence_en: FechaUTC
    vigente: bool
    estado_venta: str


# ---- Pagos ----


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


# ---- Entregas ----


EstadoEnvio = Literal["programado", "en_ruta", "entregado", "fallido"]


# ---- Zonas de envío ---------------------------------------------------------


class ZonaEnvioCrear(BaseModel):
    ciudad_id: int
    nombre: str = Field(max_length=60)
    anillo_desde: int | None = Field(default=None, ge=1)
    anillo_hasta: int | None = Field(default=None, ge=1)
    tarifa_base: Decimal = Field(ge=0)


class ZonaEnvioActualizar(BaseModel):
    nombre: str | None = Field(default=None, max_length=60)
    anillo_desde: int | None = Field(default=None, ge=1)
    anillo_hasta: int | None = Field(default=None, ge=1)
    tarifa_base: Decimal | None = Field(default=None, ge=0)
    activo: bool | None = None


class ZonaEnvioRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ciudad_id: int
    nombre: str
    anillo_desde: int | None = None
    anillo_hasta: int | None = None
    tarifa_base: Decimal
    activo: bool


# ---- Direcciones de cliente ---------------------------------------------------
# Sin cliente_id en el Crear: se resuelve del usuario autenticado en el
# caso de uso, igual que carrito (nunca se confía en un cliente_id del body).


class DireccionClienteCrear(BaseModel):
    zona_envio_id: int | None = None
    alias: str | None = Field(default=None, max_length=40)
    direccion: str = Field(max_length=200)
    referencia: str | None = Field(default=None, max_length=200)
    latitud: Decimal | None = None
    longitud: Decimal | None = None
    es_principal: bool = False


class DireccionClienteActualizar(BaseModel):
    zona_envio_id: int | None = None
    alias: str | None = Field(default=None, max_length=40)
    direccion: str | None = Field(default=None, max_length=200)
    referencia: str | None = Field(default=None, max_length=200)
    latitud: Decimal | None = None
    longitud: Decimal | None = None
    es_principal: bool | None = None
    activo: bool | None = None


class DireccionClienteRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cliente_id: int
    zona_envio_id: int | None = None
    alias: str | None = None
    direccion: str
    referencia: str | None = None
    latitud: Decimal | None = None
    longitud: Decimal | None = None
    es_principal: bool
    activo: bool


# ---- Cotización (no persiste) y envíos -----------------------------------------


class CotizarEnvioRequest(BaseModel):
    direccion_id: int
    cantidad_prendas: int = Field(gt=0)


class CotizarEnvioRespuesta(BaseModel):
    zona_envio_id: int
    zona_nombre: str
    peso_kg: Decimal
    tarifa_base: Decimal
    recargo_peso: Decimal
    costo: Decimal


class EnvioCrear(BaseModel):
    venta_id: int
    direccion_id: int


class EnvioRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    venta_id: int
    direccion_id: int
    zona_envio_id: int
    costo: Decimal
    peso_kg: Decimal | None = None
    estado: EstadoEnvio
    fecha_programada: dt.datetime | None = None
    fecha_entrega: dt.datetime | None = None
    repartidor: str | None = None


class EnvioEstadoActualizar(BaseModel):
    estado: EstadoEnvio
    repartidor: str | None = Field(default=None, max_length=80)
