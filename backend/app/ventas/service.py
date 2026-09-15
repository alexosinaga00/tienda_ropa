"""Ventas: registrar_venta_presencial()/registrar_venta_digital() son la
regla de negocio central, delegada en `_registrar_venta()`, que hace TODO
en una sola transacción (una línea sin stock revierte la venta entera):

1. Valida disponibilidad de cada línea (vía inventario.service, antes de
   tocar nada).
2. Crea venta y venta_detalle, congelando `costo_unitario` desde
   `stock.costo_promedio` de ese momento -- nunca se recalcula después,
   aunque cambie el costo promedio real de la variante (ver el docstring
   de VentaDetalle.costo_unitario y los tests de "Revisar").
3. Llama a inventario.service.registrar_movimiento() tipo 'venta' por
   cada línea.
4. Si la venta viene de una reserva, libera el stock reservado de esa
   línea antes del movimiento (si no, registrar_movimiento rechazaría
   dejar cantidad_reservada sin respaldo físico) y usa las líneas que el
   cliente ya marcó `seleccionada=True` al probarse (reservas.service ya
   deja la reserva en 'completada' en ese momento; acá no hay una
   transición aparte, solo se valida que ya haya pasado).
5. Aplica promociones vigentes según `promocion_alcance`: si más de una
   promoción matchea la misma línea, se toma la de mayor descuento (el
   enunciado no dice si se acumulan, y acumular sin límite podría dejar
   precios negativos).
6. Calcula subtotal (bruto, antes de descuento), descuento, costo de
   envío y total.
"""

from __future__ import annotations

import datetime as dt
import secrets
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.catalogo import service as catalogo_service
from app.core.deps import ParametrosPaginacion, ParametrosPeriodo
from app.core.exceptions import ConflictoError, DomainError, NoEncontradoError, PermisoDenegadoError
from app.core.security import permisos_de_usuario
from app.inventario import service as inventario_service
from app.organizacion import service as organizacion_service
from app.reservas import service as reservas_service
from app.seguridad import service as seguridad_service
from app.ventas import repository as ventas_repo
from app.ventas.models import (
    Carrito,
    CarritoDetalle,
    Devolucion,
    DevolucionDetalle,
    EstadoVenta,
    Promocion,
    PromocionAlcance,
    Venta,
    VentaDetalle,
)
from app.ventas.repository import (
    CarritoRepository,
    DevolucionRepository,
    EstadoVentaRepository,
    PromocionRepository,
    VentaRepository,
)
from app.ventas.schemas import (
    CarritoDetalleActualizar,
    CarritoDetalleCrear,
    CarritoDetalleRespuesta,
    CarritoResumenLinea,
    CarritoResumenRespuesta,
    CarritoRespuesta,
    DevolucionCrear,
    PromocionActualizar,
    PromocionAlcanceCrear,
    PromocionCrear,
    VentaDigitalCrear,
    VentaPresencialCrear,
)

if TYPE_CHECKING:
    # Solo para el type hint de _calcular_linea/_registrar_venta -- con
    # `from __future__ import annotations` las anotaciones no se evalúan en
    # tiempo de ejecución, así que este import no hace falta como
    # dependencia real de catalogo.models (acoplamiento innecesario, ver
    # auditoría).
    from app.catalogo.models import ProductoVariante

estado_repo = EstadoVentaRepository()
venta_repo = VentaRepository()
promocion_repo = PromocionRepository()
carrito_repo = CarritoRepository()
devolucion_repo = DevolucionRepository()

PERMISO_STAFF = "ventas.gestionar_sucursal"

_DOS_DECIMALES = Decimal("0.01")


def _redondear(valor: Decimal) -> Decimal:
    return valor.quantize(_DOS_DECIMALES, rounding=ROUND_HALF_UP)


def _generar_codigo(db: Session, prefijo: str, existe_codigo) -> str:
    for _ in range(5):
        codigo = f"{prefijo}-{secrets.token_hex(4).upper()}"
        if existe_codigo(db, codigo) is None:
            return codigo
    raise DomainError("No se pudo generar un código único, reintentá")


def _es_staff(db: Session, usuario_id: int) -> bool:
    return PERMISO_STAFF in permisos_de_usuario(db, usuario_id)


# ---- Cálculo de precio + promoción ------------------------------------------------


def _calcular_linea(db: Session, variante: ProductoVariante, cantidad: int, hoy: dt.date) -> tuple[Decimal, Decimal, Decimal]:
    """(precio_unitario, descuento_unitario, subtotal_neto) de una línea."""
    precio_unitario = catalogo_service.obtener_precio_efectivo(variante)
    producto_id, categoria_id, temporada_id = catalogo_service.obtener_info_promocion(variante)
    promociones = promocion_repo.listar_vigentes_para(
        db, producto_id=producto_id, categoria_id=categoria_id, temporada_id=temporada_id, hoy=hoy
    )

    descuento_unitario = Decimal("0")
    for promocion in promociones:
        if promocion.tipo == "porcentaje":
            candidato = precio_unitario * promocion.valor / Decimal("100")
        else:
            candidato = promocion.valor
        candidato = min(candidato, precio_unitario)  # nunca deja el precio negativo
        descuento_unitario = max(descuento_unitario, candidato)

    descuento_unitario = _redondear(descuento_unitario)
    subtotal = _redondear((precio_unitario - descuento_unitario) * cantidad)
    return precio_unitario, descuento_unitario, subtotal


# ---- Venta: regla central ----------------------------------------------------------


def _registrar_venta(
    db: Session,
    *,
    canal: str,
    sucursal_id: int,
    lineas: list[tuple[int, int]],
    cliente_id: int | None,
    cajero_id: int | None,
    reserva_id: int | None,
    costo_envio: Decimal,
    usuario_id: int | None,
    carrito_a_vaciar: Carrito | None = None,
) -> Venta:
    if not lineas:
        raise DomainError("La venta necesita al menos una línea")

    organizacion_service.obtener_sucursal(db, sucursal_id)
    hoy = dt.date.today()

    # 1. Valida disponibilidad de TODAS las líneas antes de tocar nada.
    variantes: dict[int, ProductoVariante] = {}
    for variante_id, cantidad in lineas:
        variante = catalogo_service.obtener_variante(db, variante_id)  # 404 si no existe
        variantes[variante_id] = variante
        disponibilidad = inventario_service.consultar_disponibilidad(db, variante_id, sucursal_id)
        disponible = sum(s.cantidad_disponible for s in disponibilidad)
        if cantidad > disponible:
            raise ConflictoError(f"No hay stock disponible suficiente de la variante {variante_id}")

    estado_inicial = estado_repo.obtener_por_codigo(db, "pendiente_pago")
    venta = Venta(
        codigo=_generar_codigo(db, "VTA", venta_repo.obtener_por_codigo),
        canal=canal,
        cliente_id=cliente_id,
        sucursal_id=sucursal_id,
        cajero_id=cajero_id,
        reserva_id=reserva_id,
        estado_id=estado_inicial.id,
        costo_envio=costo_envio,
    )
    venta_repo.crear(db, venta)  # flush: venta.id ya disponible

    subtotal_bruto = Decimal("0")
    descuento_total = Decimal("0")

    for variante_id, cantidad in lineas:
        variante = variantes[variante_id]
        precio_unitario, descuento_unitario, subtotal_linea = _calcular_linea(db, variante, cantidad, hoy)

        # 2. costo_unitario queda NULL acá a propósito: recién se congela
        # en confirmar_venta(), cuando el pago se aprueba (P5.2) -- hasta
        # entonces el stock ni siquiera se descontó de verdad, así que no
        # hay un costo "real" de esta salida todavía que congelar.
        db.add(
            VentaDetalle(
                venta_id=venta.id,
                variante_id=variante_id,
                cantidad=cantidad,
                precio_unitario=precio_unitario,
                descuento_unitario=descuento_unitario,
                costo_unitario=None,
                subtotal=subtotal_linea,
            )
        )
        subtotal_bruto += precio_unitario * cantidad
        descuento_total += descuento_unitario * cantidad

        # 3./4. Todavía no se toca físicamente el stock (eso es
        # confirmar_venta): acá solo se RESERVA, para que nadie más se
        # lleve el mismo stock mientras el pago está pendiente. Si la
        # venta viene de una reserva, ese stock ya está reservado desde
        # que se creó la reserva -- reservarlo de nuevo lo dejaría
        # reservado el doble.
        if reserva_id is None:
            inventario_service.reservar_stock(db, variante_id, sucursal_id, cantidad, commit=False)

    # 6. Totales.
    venta.subtotal = _redondear(subtotal_bruto)
    venta.descuento = _redondear(descuento_total)
    venta.total = _redondear(venta.subtotal - venta.descuento + venta.costo_envio)

    if carrito_a_vaciar is not None:
        carrito_repo.vaciar(db, carrito_a_vaciar)

    db.commit()
    db.refresh(venta)
    return venta


# ---- Confirmación / anulación (dispara `pagos` al aprobar/rechazar) -----------------


def confirmar_venta(db: Session, venta_id: int, *, usuario_id: int | None = None, commit: bool = True) -> Venta:
    """Para que `pagos` confirme la venta cuando su pago pasa a 'aprobado'
    (webhook o caja): es recién acá, y no en `_registrar_venta`, donde se
    descuenta físicamente el stock y se congela costo_unitario -- hasta
    este momento el stock de la venta solo estaba RESERVADO.

    Bloquea la fila de `venta` (obtener_bloqueado) antes de leer su estado:
    evita que dos llamadas concurrentes (dos webhooks del mismo pago, o un
    webhook y un pago en caja) lean 'pendiente_pago' antes de que ninguna
    comitee y terminen descontando el stock DOS veces para la misma venta
    (B-1 de la auditoría)."""
    venta = venta_repo.obtener_bloqueado(db, venta_id)
    estado_actual = estado_repo.obtener(db, venta.estado_id)
    if estado_actual.codigo != "pendiente_pago":
        raise DomainError(f"No se puede confirmar una venta en estado '{estado_actual.codigo}'")

    for linea in venta.detalle:
        # Libera la reserva (la haya hecho _registrar_venta o la reserva
        # original) antes de descontar, si no registrar_movimiento
        # rechazaría dejar cantidad_reservada sin respaldo físico.
        inventario_service.liberar_stock(db, linea.variante_id, venta.sucursal_id, linea.cantidad, commit=False)

        stock_actual = inventario_service.obtener_stock(db, linea.variante_id, venta.sucursal_id)
        linea.costo_unitario = stock_actual.costo_promedio  # congelado recién ahora

        inventario_service.registrar_movimiento(
            db,
            variante_id=linea.variante_id,
            sucursal_id=venta.sucursal_id,
            tipo_movimiento_codigo="venta",
            cantidad=linea.cantidad,
            referencia_tipo="venta",
            referencia_id=venta.id,
            usuario_id=usuario_id,
            commit=False,
        )

    estado_pagada = estado_repo.obtener_por_codigo(db, "pagada")
    venta.estado_id = estado_pagada.id

    if commit:
        db.commit()
        db.refresh(venta)
    else:
        db.flush()
    return venta


def anular_venta(db: Session, venta_id: int, *, commit: bool = True, restaurar_carrito: bool = False) -> Venta:
    """Para que `pagos` anule la venta cuando su pago se rechaza o se
    reembolsa. Se banca los dos casos posibles: si todavía estaba
    'pendiente_pago' (nunca se descontó físicamente), solo libera la
    reserva; si ya estaba 'pagada' (pago aprobado y después reembolsado),
    reingresa el stock como una devolución total. Bloquea la fila de
    `venta` (obtener_bloqueado) por el mismo motivo que confirmar_venta.

    `restaurar_carrito`: solo para una venta digital que nunca se pagó
    (rechazada, cancelada por el cliente o vencida) -- registrar_venta_digital
    vació el carrito, así que se le devuelven las prendas para que pueda
    volver a intentarlo sin armarlo de nuevo."""
    venta = venta_repo.obtener_bloqueado(db, venta_id)
    estado_actual = estado_repo.obtener(db, venta.estado_id)

    if estado_actual.codigo == "anulada":
        return venta  # ya estaba anulada: no-op, no un error

    if estado_actual.codigo == "pendiente_pago":
        for linea in venta.detalle:
            inventario_service.liberar_stock(db, linea.variante_id, venta.sucursal_id, linea.cantidad, commit=False)
        if restaurar_carrito and venta.canal == "digital" and venta.cliente_id is not None:
            _restaurar_carrito(db, venta)
    elif estado_actual.codigo == "pagada":
        for linea in venta.detalle:
            inventario_service.registrar_movimiento(
                db,
                variante_id=linea.variante_id,
                sucursal_id=venta.sucursal_id,
                tipo_movimiento_codigo="devolucion",
                cantidad=linea.cantidad,
                referencia_tipo="venta_anulada",
                referencia_id=venta.id,
                commit=False,
            )
    else:
        raise DomainError(f"No se puede anular una venta en estado '{estado_actual.codigo}'")

    estado_anulada = estado_repo.obtener_por_codigo(db, "anulada")
    venta.estado_id = estado_anulada.id

    if commit:
        db.commit()
        db.refresh(venta)
    else:
        db.flush()
    return venta


def _restaurar_carrito(db: Session, venta: Venta) -> None:
    carrito = carrito_repo.obtener_o_crear(db, venta.cliente_id)
    for linea_venta in venta.detalle:
        linea = carrito_repo.obtener_linea(db, carrito.id, linea_venta.variante_id)
        if linea is None:
            db.add(CarritoDetalle(carrito_id=carrito.id, variante_id=linea_venta.variante_id, cantidad=linea_venta.cantidad))
        else:
            # Si el cliente ya la volvió a agregar a mano, no se duplica.
            linea.cantidad = max(linea.cantidad, linea_venta.cantidad)
    db.flush()


def es_venta_pendiente(db: Session, venta_id: int) -> bool:
    """Para que `pagos` sepa si una venta todavía espera su pago."""
    venta = venta_repo.obtener(db, venta_id)
    return estado_repo.obtener(db, venta.estado_id).codigo == "pendiente_pago"


def listar_ventas_pendientes_vencidas(db: Session, minutos: int) -> list[int]:
    """Para `pagos.expirar_ventas_pendientes`: ids de ventas que siguen en
    'pendiente_pago' desde hace más de `minutos`. `venta.fecha` se guarda
    sin zona horaria con el now() de la base (UTC en Railway y en SQLite)."""
    limite = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(minutes=minutos)
    estado = estado_repo.obtener_por_codigo(db, "pendiente_pago")
    return list(
        db.scalars(select(Venta.id).where(Venta.estado_id == estado.id, Venta.fecha < limite).order_by(Venta.id))
    )


def obtener_venta(db: Session, venta_id: int) -> Venta:
    """Para que `pagos` lea una venta (monto, sucursal, etc.) sin
    consultar `venta` directamente."""
    return venta_repo.obtener(db, venta_id)


def obtener_venta_bloqueada(db: Session, venta_id: int) -> Venta:
    """Para que `pagos.iniciar_pago_pasarela` bloquee la venta antes de
    validar que no haya ya un pago activo (B-2): serializa esa validación
    con cualquier confirmar_venta/anular_venta concurrente sobre la misma
    venta, sin que `pagos` tenga que consultar `venta` directamente."""
    return venta_repo.obtener_bloqueado(db, venta_id)


def mapa_codigos_estado(db: Session) -> dict[int, str]:
    """Para que el router arme VentaRespuesta sin consultar `estado_venta`
    directamente."""
    return estado_repo.mapa_codigos_por_id(db)


def obtener_estado_codigo(db: Session, estado_id: int) -> str:
    """Para que `pagos` traduzca el `estado_id` de una venta a su código
    ('pendiente_pago', 'pagada', ...) sin consultar `estado_venta`
    directamente."""
    return estado_repo.obtener(db, estado_id).codigo


def registrar_venta_presencial(db: Session, usuario_id: int, datos: VentaPresencialCrear) -> Venta:
    empleado = organizacion_service.obtener_empleado_por_usuario(db, usuario_id)
    if empleado is None:
        raise PermisoDenegadoError("Este usuario no es un empleado, no puede registrar ventas presenciales")

    if datos.reserva_id is not None:
        reserva = reservas_service.obtener_reserva_para_venta(db, datos.reserva_id)
        lineas = [(linea.variante_id, linea.cantidad) for linea in reserva.detalle if linea.seleccionada]
        if not lineas:
            raise DomainError("La reserva no tiene ninguna línea seleccionada para comprar")
        cliente_id = reserva.cliente_id
    else:
        if not datos.detalle:
            raise DomainError("La venta necesita al menos una línea (o un reserva_id)")
        lineas = [(linea.variante_id, linea.cantidad) for linea in datos.detalle]
        cliente_id = datos.cliente_id
        if cliente_id is not None:
            seguridad_service.obtener_cliente(db, cliente_id)  # 404 si no existe

    return _registrar_venta(
        db,
        canal="presencial",
        sucursal_id=datos.sucursal_id,
        lineas=lineas,
        cliente_id=cliente_id,
        cajero_id=empleado.id,
        reserva_id=datos.reserva_id,
        costo_envio=Decimal("0"),
        usuario_id=usuario_id,
    )


def registrar_venta_digital(db: Session, usuario_id: int, datos: VentaDigitalCrear) -> Venta:
    cliente = seguridad_service.obtener_perfil_cliente(db, usuario_id)
    carrito = carrito_repo.obtener_por_cliente(db, cliente.id)
    if carrito is None or not carrito.detalle:
        raise DomainError("El carrito está vacío")

    lineas = [(linea.variante_id, linea.cantidad) for linea in carrito.detalle]

    # Sin costo de envío es retiro en sucursal (el envío a domicilio siempre
    # cobra la tarifa de la zona): no se puede retirar en un depósito.
    if datos.costo_envio == 0 and not organizacion_service.atiende_al_publico(db, datos.sucursal_id):
        raise DomainError("Esa sucursal no atiende al público: elegí otra para retirar tu pedido")

    return _registrar_venta(
        db,
        canal="digital",
        sucursal_id=datos.sucursal_id,
        lineas=lineas,
        cliente_id=cliente.id,
        cajero_id=None,
        reserva_id=None,
        costo_envio=datos.costo_envio,
        usuario_id=usuario_id,
        carrito_a_vaciar=carrito,
    )


# ---- Consultas de ventas ------------------------------------------------------------


def _validar_acceso_venta(db: Session, venta: Venta, usuario_id: int) -> None:
    if _es_staff(db, usuario_id):
        return
    cliente = seguridad_service.obtener_perfil_cliente(db, usuario_id)
    if cliente is None or venta.cliente_id != cliente.id:
        raise PermisoDenegadoError("No tenés acceso a esta venta")


def obtener_comprobante(db: Session, venta_id: int, usuario_id: int) -> Venta:
    venta = venta_repo.obtener(db, venta_id)
    _validar_acceso_venta(db, venta, usuario_id)
    return venta


def listar_mis_compras(db: Session, usuario_id: int) -> list[Venta]:
    cliente = seguridad_service.obtener_perfil_cliente(db, usuario_id)
    return venta_repo.listar_por_cliente(db, cliente.id)


def listar_ventas_sucursal(db: Session, sucursal_id: int) -> list[Venta]:
    organizacion_service.obtener_sucursal(db, sucursal_id)
    return venta_repo.listar_por_sucursal(db, sucursal_id)


# ---- Punto de entrada para otros paquetes ------------------------------------


def listar_variantes_compradas(db: Session, cliente_id: int) -> set[int]:
    """Para `inteligencia` (P6.2, capa de reglas): variantes que un cliente
    ya compró, para excluirlas del recomendador. Cuenta cualquier venta que
    no haya sido anulada (pendiente_pago/pagada/entregada sí cuentan)."""
    filas = db.scalars(
        select(VentaDetalle.variante_id)
        .join(Venta, Venta.id == VentaDetalle.venta_id)
        .join(EstadoVenta, EstadoVenta.id == Venta.estado_id)
        .where(Venta.cliente_id == cliente_id, EstadoVenta.codigo != "anulada")
        .distinct()
    )
    return set(filas)


def reporte_ventas_detalle(
    db: Session,
    periodo: ParametrosPeriodo,
    sucursal_id: int | None = None,
    categoria_id: int | None = None,
    canal: str | None = None,
) -> list[dict]:
    """Para `reportes` (P6.3): filas crudas de vw_ventas_detalle."""
    return ventas_repo.detalle(db, periodo.desde, periodo.hasta, sucursal_id, categoria_id, canal)


def reporte_ventas_resumen(
    db: Session,
    periodo: ParametrosPeriodo,
    sucursal_id: int | None = None,
    categoria_id: int | None = None,
    canal: str | None = None,
) -> dict:
    """Para `reportes` (P6.3): total vendido, transacciones y margen bruto
    del período (el ticket promedio lo calcula quien llama, dividiendo)."""
    return ventas_repo.resumen(db, periodo.desde, periodo.hasta, sucursal_id, categoria_id, canal)


def reporte_ventas_top_productos(
    db: Session,
    periodo: ParametrosPeriodo,
    sucursal_id: int | None = None,
    categoria_id: int | None = None,
    canal: str | None = None,
    limite: int = 10,
) -> list[dict]:
    """Para `reportes` (P6.3): productos más vendidos del período."""
    return ventas_repo.top_productos(db, periodo.desde, periodo.hasta, sucursal_id, categoria_id, canal, limite)


def reporte_ventas_por_canal(
    db: Session, periodo: ParametrosPeriodo, sucursal_id: int | None = None, categoria_id: int | None = None
) -> list[dict]:
    """Para `reportes` (P6.3): ventas agrupadas por canal (digital/presencial)."""
    return ventas_repo.por_canal(db, periodo.desde, periodo.hasta, sucursal_id, categoria_id)


def reporte_ventas_por_sucursal(
    db: Session, periodo: ParametrosPeriodo, categoria_id: int | None = None, canal: str | None = None
) -> list[dict]:
    """Para `reportes` (P6.3): ventas agrupadas por sucursal."""
    return ventas_repo.por_sucursal(db, periodo.desde, periodo.hasta, categoria_id, canal)


def contar_ventas_con_reserva(db: Session, periodo: ParametrosPeriodo, sucursal_id: int | None = None) -> int:
    """Para `reportes` (P6.3, tasa de conversión de reservas a ventas):
    ventas del período que se originaron en una reserva."""
    return ventas_repo.contar_ventas_con_reserva(db, periodo.desde, periodo.hasta, sucursal_id)


def contar_ventas_por_variante(db: Session, variante_ids: list[int]) -> dict[int, int]:
    """Para `inteligencia` (P6.2, fallback de popularidad para clientes
    nuevos/anónimos sin historial): cantidad total vendida de cada
    variante, contando solo ventas no anuladas."""
    if not variante_ids:
        return {}
    filas = db.execute(
        select(VentaDetalle.variante_id, func.sum(VentaDetalle.cantidad))
        .join(Venta, Venta.id == VentaDetalle.venta_id)
        .join(EstadoVenta, EstadoVenta.id == Venta.estado_id)
        .where(VentaDetalle.variante_id.in_(variante_ids), EstadoVenta.codigo != "anulada")
        .group_by(VentaDetalle.variante_id)
    ).all()
    return {variante_id: int(total) for variante_id, total in filas}


# ---- Carrito --------------------------------------------------------------------


def _carrito_respuesta(db: Session, carrito: Carrito) -> CarritoRespuesta:
    detalle_resp = []
    subtotal = Decimal("0")
    for linea in carrito.detalle:
        variante = catalogo_service.obtener_variante(db, linea.variante_id)
        precio_unitario = catalogo_service.obtener_precio_efectivo(variante)
        subtotal_linea = _redondear(precio_unitario * linea.cantidad)
        detalle_resp.append(
            CarritoDetalleRespuesta(
                id=linea.id,
                variante_id=linea.variante_id,
                cantidad=linea.cantidad,
                precio_unitario=precio_unitario,
                subtotal=subtotal_linea,
            )
        )
        subtotal += subtotal_linea

    return CarritoRespuesta(
        id=carrito.id,
        cliente_id=carrito.cliente_id,
        sucursal_id=carrito.sucursal_id,
        actualizado_en=carrito.actualizado_en,
        detalle=detalle_resp,
        subtotal=_redondear(subtotal),
    )


def _validar_stock_para_carrito(db: Session, variante_id: int, cantidad: int) -> None:
    """El carrito todavía no elige sucursal: se valida contra el disponible
    total de la variante. La sucursal concreta se vuelve a validar al
    registrar la venta (_registrar_venta)."""
    disponible = sum(s.cantidad_disponible for s in inventario_service.consultar_disponibilidad(db, variante_id))
    if cantidad > disponible:
        if disponible <= 0:
            raise ConflictoError("Esta prenda está agotada")
        raise ConflictoError(f"Solo quedan {disponible} unidades disponibles")


def obtener_mi_carrito(db: Session, usuario_id: int) -> CarritoRespuesta:
    cliente = seguridad_service.obtener_perfil_cliente(db, usuario_id)
    carrito = carrito_repo.obtener_o_crear(db, cliente.id)
    db.commit()  # persiste el carrito si obtener_o_crear tuvo que crearlo
    return _carrito_respuesta(db, carrito)


def agregar_al_carrito(db: Session, usuario_id: int, datos: CarritoDetalleCrear) -> CarritoRespuesta:
    cliente = seguridad_service.obtener_perfil_cliente(db, usuario_id)
    catalogo_service.obtener_variante(db, datos.variante_id)  # 404 si no existe
    carrito = carrito_repo.obtener_o_crear(db, cliente.id)

    linea = carrito_repo.obtener_linea(db, carrito.id, datos.variante_id)
    _validar_stock_para_carrito(db, datos.variante_id, datos.cantidad + (linea.cantidad if linea else 0))
    if linea is None:
        db.add(CarritoDetalle(carrito_id=carrito.id, variante_id=datos.variante_id, cantidad=datos.cantidad))
    else:
        linea.cantidad += datos.cantidad

    db.commit()
    db.refresh(carrito)
    return _carrito_respuesta(db, carrito)


def actualizar_linea_carrito(
    db: Session, usuario_id: int, variante_id: int, datos: CarritoDetalleActualizar
) -> CarritoRespuesta:
    cliente = seguridad_service.obtener_perfil_cliente(db, usuario_id)
    carrito = carrito_repo.obtener_o_crear(db, cliente.id)
    linea = carrito_repo.obtener_linea(db, carrito.id, variante_id)
    if linea is None:
        raise NoEncontradoError("Esa variante no está en el carrito")

    if datos.cantidad > linea.cantidad:  # bajar la cantidad nunca se bloquea
        _validar_stock_para_carrito(db, variante_id, datos.cantidad)
    linea.cantidad = datos.cantidad
    db.commit()
    db.refresh(carrito)
    return _carrito_respuesta(db, carrito)


def quitar_del_carrito(db: Session, usuario_id: int, variante_id: int) -> CarritoRespuesta:
    cliente = seguridad_service.obtener_perfil_cliente(db, usuario_id)
    carrito = carrito_repo.obtener_o_crear(db, cliente.id)
    linea = carrito_repo.obtener_linea(db, carrito.id, variante_id)
    if linea is None:
        raise NoEncontradoError("Esa variante no está en el carrito")

    db.delete(linea)
    db.commit()
    db.refresh(carrito)
    return _carrito_respuesta(db, carrito)


def previsualizar_carrito(db: Session, usuario_id: int) -> CarritoResumenRespuesta:
    """POST /carrito/aplicar-promocion: no hay código de cupón que canjear
    (`promocion` no tiene esa columna) -- esto recalcula el carrito con las
    promociones vigentes ya aplicadas solas, según `promocion_alcance`."""
    cliente = seguridad_service.obtener_perfil_cliente(db, usuario_id)
    carrito = carrito_repo.obtener_o_crear(db, cliente.id)
    db.commit()
    hoy = dt.date.today()

    lineas: list[CarritoResumenLinea] = []
    subtotal = Decimal("0")
    descuento = Decimal("0")
    for linea in carrito.detalle:
        variante = catalogo_service.obtener_variante(db, linea.variante_id)
        precio_unitario, descuento_unitario, subtotal_linea = _calcular_linea(db, variante, linea.cantidad, hoy)
        lineas.append(
            CarritoResumenLinea(
                variante_id=linea.variante_id,
                cantidad=linea.cantidad,
                precio_unitario=precio_unitario,
                descuento_unitario=descuento_unitario,
                subtotal=subtotal_linea,
            )
        )
        subtotal += precio_unitario * linea.cantidad
        descuento += descuento_unitario * linea.cantidad

    subtotal = _redondear(subtotal)
    descuento = _redondear(descuento)
    return CarritoResumenRespuesta(lineas=lineas, subtotal=subtotal, descuento=descuento, total=subtotal - descuento)


# ---- Promociones ----------------------------------------------------------------


def _validar_alcance(alcance: PromocionAlcanceCrear) -> None:
    # El schema (PromocionAlcanceCrear) ya valida esto con @model_validator,
    # pero se revalida acá porque service.py es quien realmente decide las
    # reglas de negocio, no el schema (el schema podría llegar a cambiar
    # sin que nadie note que esta regla dependía de él).
    cantidad = sum(x is not None for x in (alcance.producto_id, alcance.categoria_id, alcance.temporada_id))
    if cantidad != 1:
        raise DomainError("Cada alcance necesita exactamente uno de producto_id, categoria_id o temporada_id")


def crear_promocion(db: Session, datos: PromocionCrear):
    for alcance in datos.alcances:
        _validar_alcance(alcance)
        if alcance.producto_id is not None:
            catalogo_service.obtener_producto(db, alcance.producto_id)  # 404 si no existe

    promocion = Promocion(
        nombre=datos.nombre,
        tipo=datos.tipo,
        valor=datos.valor,
        fecha_inicio=datos.fecha_inicio,
        fecha_fin=datos.fecha_fin,
    )
    promocion.alcances = [
        PromocionAlcance(
            producto_id=alcance.producto_id, categoria_id=alcance.categoria_id, temporada_id=alcance.temporada_id
        )
        for alcance in datos.alcances
    ]
    promocion_repo.crear(db, promocion)  # flush
    db.commit()
    db.refresh(promocion)
    return promocion


def listar_promociones(db: Session, paginacion: ParametrosPaginacion):
    return promocion_repo.listar(db, paginacion)


def obtener_promocion(db: Session, promocion_id: int):
    return promocion_repo.obtener(db, promocion_id)


def actualizar_promocion(db: Session, promocion_id: int, datos: PromocionActualizar):
    promocion = promocion_repo.obtener(db, promocion_id)
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(promocion, campo, valor)
    if promocion.fecha_fin < promocion.fecha_inicio:
        raise DomainError("fecha_fin no puede ser anterior a fecha_inicio")
    db.commit()
    db.refresh(promocion)
    return promocion


def desactivar_promocion(db: Session, promocion_id: int):
    promocion = promocion_repo.obtener(db, promocion_id)
    promocion.activo = False
    db.commit()
    db.refresh(promocion)
    return promocion


# ---- Devoluciones ----------------------------------------------------------------


def registrar_devolucion(db: Session, usuario_id: int, datos: DevolucionCrear) -> Devolucion:
    venta = venta_repo.obtener(db, datos.venta_id)

    # Con el pago gateado (P5.2), una venta 'pendiente_pago' nunca
    # descontó stock físico -- no hay nada real que devolver todavía.
    estado_venta = estado_repo.obtener(db, venta.estado_id)
    if estado_venta.codigo not in ("pagada", "entregada"):
        raise DomainError(f"No se puede devolver una venta en estado '{estado_venta.codigo}'")

    detalle_por_id = {linea.id: linea for linea in venta.detalle}

    devolucion = Devolucion(
        codigo=_generar_codigo(db, "DEV", _obtener_devolucion_por_codigo),
        venta_id=venta.id,
        motivo=datos.motivo,
        estado="aprobada",  # esta etapa no tiene un flujo de aprobación aparte
        usuario_id=usuario_id,
    )
    db.add(devolucion)
    db.flush()

    for linea in datos.detalle:
        detalle = detalle_por_id.get(linea.venta_detalle_id)
        if detalle is None:
            raise NoEncontradoError(f"La línea {linea.venta_detalle_id} no pertenece a la venta {venta.id}")

        ya_devuelto = devolucion_repo.cantidad_devuelta(db, linea.venta_detalle_id)
        if ya_devuelto + linea.cantidad > detalle.cantidad:
            raise DomainError(
                f"No se puede devolver más de lo vendido en la línea {linea.venta_detalle_id} "
                f"({ya_devuelto} ya devuelto de {detalle.cantidad})"
            )

        db.add(DevolucionDetalle(devolucion_id=devolucion.id, venta_detalle_id=detalle.id, cantidad=linea.cantidad))

        # La devolución reingresa stock (movimiento tipo 'devolucion'); no
        # reabre la venta ni cambia su estado -- esta etapa no toca pagos.
        inventario_service.registrar_movimiento(
            db,
            variante_id=detalle.variante_id,
            sucursal_id=venta.sucursal_id,
            tipo_movimiento_codigo="devolucion",
            cantidad=linea.cantidad,
            referencia_tipo="devolucion",
            referencia_id=devolucion.id,
            usuario_id=usuario_id,
            commit=False,
        )

    db.commit()
    db.refresh(devolucion)
    return devolucion


def _obtener_devolucion_por_codigo(db: Session, codigo: str) -> Devolucion | None:
    return db.scalar(select(Devolucion).where(Devolucion.codigo == codigo))
