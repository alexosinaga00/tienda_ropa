"""Corazón del paquete `ventas`: registrar_venta() es la regla de negocio
compartida por CU-24 (compra digital) y CU-25 (venta presencial) -- hace
TODO en una sola transacción (una línea sin stock revierte la venta
entera):

1. Valida disponibilidad de cada línea (vía inventario.politicas, antes de
   tocar nada).
2. Crea venta y venta_detalle, congelando `costo_unitario` desde
   `stock.costo_promedio` recién en confirmar_venta() -- nunca se
   recalcula después, aunque cambie el costo promedio real de la variante.
3. Llama a inventario.politicas.actualizar_stock_operacion() tipo 'venta'
   por cada línea (en confirmar_venta, cuando el pago se aprueba).
4. Si la venta viene de una reserva, libera el stock reservado de esa
   línea antes del movimiento y usa las líneas que el cliente ya marcó
   `seleccionada=True` al probarse (CU-20 ya deja la reserva en
   'completada' en ese momento).
5. Aplica promociones vigentes según `promocion_alcance`: si más de una
   promoción matchea la misma línea, se toma la de mayor descuento.
6. Calcula subtotal (bruto, antes de descuento), descuento, costo de
   envío y total.

confirmar_venta()/anular_venta() las dispara `pagos` (CU-29/CU-30/CU-31)
al aprobar o rechazar el pago: ninguna de las dos es un caso de uso propio
del catálogo. El resto de este archivo son consultas que otros paquetes
(`pagos`, `entregas`, `inteligencia`, `reportes`) necesitan sin tocar las
tablas de ventas directamente.
"""

from __future__ import annotations

import datetime as dt
import secrets
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.core.deps import ParametrosPeriodo
from app.core.exceptions import ConflictoError, DomainError, PermisoDenegadoError
from app.core.security import permisos_de_usuario
from app.inventario import politicas as inventario_politicas
from app.inventario.casos_uso.cu13_consultar_disponibilidad_sucursal import ConsultarDisponibilidadSucursal
from app.organizacion import politicas as organizacion_politicas
from app.seguridad.politicas import obtener_perfil_cliente
from app.ventas import repository as ventas_repo
from app.ventas.models import Carrito, CarritoDetalle, EstadoVenta, Venta, VentaDetalle
from app.ventas.repository import CarritoRepository, EstadoVentaRepository, PromocionRepository, VentaRepository

PERMISO_STAFF = "ventas.gestionar_sucursal"

if TYPE_CHECKING:
    from app.catalogo.models import ProductoVariante

estado_repo = EstadoVentaRepository()
venta_repo = VentaRepository()
promocion_repo = PromocionRepository()
carrito_repo = CarritoRepository()
_disponibilidad_cu = ConsultarDisponibilidadSucursal()

_DOS_DECIMALES = Decimal("0.01")


def redondear(valor: Decimal) -> Decimal:
    return valor.quantize(_DOS_DECIMALES, rounding=ROUND_HALF_UP)


def generar_codigo(db: Session, prefijo: str, existe_codigo) -> str:
    for _ in range(5):
        codigo = f"{prefijo}-{secrets.token_hex(4).upper()}"
        if existe_codigo(db, codigo) is None:
            return codigo
    raise DomainError("No se pudo generar un código único, reintentá")


# ---- Cálculo de precio + promoción ------------------------------------------------


def calcular_linea(db: Session, variante: ProductoVariante, cantidad: int, hoy: dt.date) -> tuple[Decimal, Decimal, Decimal]:
    """(precio_unitario, descuento_unitario, subtotal_neto) de una línea.
    La usan CU-23 (previsualizar el carrito) y registrar_venta (CU-24,
    CU-25): no se duplica el cálculo de promoción en los dos lugares."""
    precio_unitario = catalogo_politicas.obtener_precio_efectivo(variante)
    producto_id, categoria_id, temporada_id = catalogo_politicas.obtener_info_promocion(variante)
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

    descuento_unitario = redondear(descuento_unitario)
    subtotal = redondear((precio_unitario - descuento_unitario) * cantidad)
    return precio_unitario, descuento_unitario, subtotal


# ---- Venta: regla central ----------------------------------------------------------


def registrar_venta(
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

    organizacion_politicas.obtener_sucursal(db, sucursal_id)
    hoy = dt.date.today()

    # 1. Valida disponibilidad de TODAS las líneas antes de tocar nada.
    variantes: dict[int, ProductoVariante] = {}
    for variante_id, cantidad in lineas:
        variante = catalogo_politicas.obtener_variante(db, variante_id)  # 404 si no existe
        variantes[variante_id] = variante
        if reserva_id is None:
            disponibilidad = _disponibilidad_cu.ejecutar(db, variante_id, sucursal_id)
            disponible = sum(s.cantidad_disponible for s in disponibilidad)
            if cantidad > disponible:
                raise ConflictoError(f"No hay stock disponible suficiente de la variante {variante_id}")
        else:
            # Venta de una reserva (CU-25): esas unidades ya están dentro de
            # cantidad_reservada desde CU-16, no compiten con el disponible
            # (si la reserva se llevó las últimas, el disponible es 0 y
            # compararlo acá impedía cobrarla). Solo se verifica que lo
            # reservado siga respaldando la línea.
            stock = inventario_politicas.obtener_stock(db, variante_id, sucursal_id)
            if cantidad > stock.cantidad_reservada:
                raise ConflictoError(f"La reserva ya no tiene stock apartado de la variante {variante_id}")

    estado_inicial = estado_repo.obtener_por_codigo(db, "pendiente_pago")
    venta = Venta(
        codigo=generar_codigo(db, "VTA", venta_repo.obtener_por_codigo),
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
        precio_unitario, descuento_unitario, subtotal_linea = calcular_linea(db, variante, cantidad, hoy)

        # 2. costo_unitario queda NULL acá a propósito: recién se congela
        # en confirmar_venta(), cuando el pago se aprueba -- hasta
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
            inventario_politicas.reservar_stock(db, variante_id, sucursal_id, cantidad, commit=False)

    # 6. Totales.
    venta.subtotal = redondear(subtotal_bruto)
    venta.descuento = redondear(descuento_total)
    venta.total = redondear(venta.subtotal - venta.descuento + venta.costo_envio)

    if carrito_a_vaciar is not None:
        carrito_repo.vaciar(db, carrito_a_vaciar)

    db.commit()
    db.refresh(venta)
    return venta


# ---- Confirmación / anulación (dispara `pagos` al aprobar/rechazar) -----------------


def confirmar_venta(db: Session, venta_id: int, *, usuario_id: int | None = None, commit: bool = True) -> Venta:
    """Para que `pagos` confirme la venta cuando su pago pasa a 'aprobado'
    (webhook o caja): es recién acá, y no en `registrar_venta`, donde se
    descuenta físicamente el stock y se congela costo_unitario -- hasta
    este momento el stock de la venta solo estaba RESERVADO.

    Bloquea la fila de `venta` (obtener_bloqueado) antes de leer su estado:
    evita que dos llamadas concurrentes (dos webhooks del mismo pago, o un
    webhook y un pago en caja) lean 'pendiente_pago' antes de que ninguna
    comitee y terminen descontando el stock DOS veces para la misma venta."""
    venta = venta_repo.obtener_bloqueado(db, venta_id)
    estado_actual = estado_repo.obtener(db, venta.estado_id)
    if estado_actual.codigo != "pendiente_pago":
        raise DomainError(f"No se puede confirmar una venta en estado '{estado_actual.codigo}'")

    for linea in venta.detalle:
        # Libera la reserva (la haya hecho registrar_venta o la reserva
        # original) antes de descontar, si no actualizar_stock_operacion
        # rechazaría dejar cantidad_reservada sin respaldo físico.
        inventario_politicas.liberar_stock(db, linea.variante_id, venta.sucursal_id, linea.cantidad, commit=False)

        stock_actual = inventario_politicas.obtener_stock(db, linea.variante_id, venta.sucursal_id)
        linea.costo_unitario = stock_actual.costo_promedio  # congelado recién ahora

        inventario_politicas.actualizar_stock_operacion(
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
    reingresa el stock como una devolución total.

    `restaurar_carrito`: solo para una venta digital que nunca se pagó
    (rechazada, cancelada por el cliente o vencida) -- registrar_venta
    (canal digital) vació el carrito, así que se le devuelven las prendas
    para que pueda volver a intentarlo sin armarlo de nuevo."""
    venta = venta_repo.obtener_bloqueado(db, venta_id)
    estado_actual = estado_repo.obtener(db, venta.estado_id)

    if estado_actual.codigo == "anulada":
        return venta  # ya estaba anulada: no-op, no un error

    if estado_actual.codigo == "pendiente_pago":
        for linea in venta.detalle:
            inventario_politicas.liberar_stock(db, linea.variante_id, venta.sucursal_id, linea.cantidad, commit=False)
        if restaurar_carrito and venta.canal == "digital" and venta.cliente_id is not None:
            _restaurar_carrito(db, venta)
    elif estado_actual.codigo == "pagada":
        for linea in venta.detalle:
            inventario_politicas.actualizar_stock_operacion(
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
    """Para `pagos` (expiración de ventas pendientes): ids de ventas que
    siguen en 'pendiente_pago' desde hace más de `minutos`. `venta.fecha`
    se guarda sin zona horaria con el now() de la base (UTC en Railway y en
    SQLite)."""
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
    """Para que `pagos` (al iniciar un pago por pasarela) bloquee la venta
    antes de validar que no haya ya un pago activo: serializa esa
    validación con cualquier confirmar_venta/anular_venta concurrente
    sobre la misma venta, sin que `pagos` tenga que consultar `venta`
    directamente."""
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


def obtener_comprobante(db: Session, venta_id: int, usuario_id: int) -> Venta:
    """Valida que quien pide el comprobante sea el dueño de la venta o
    personal de sucursal, y lo devuelve. La usa CU-26 directamente, y
    también `pagos` (CU-29, CU-31) y `entregas` (CU-42) como chequeo de
    acceso antes de operar sobre la venta: no se duplica la regla en cada
    paquete. El personal solo accede a las ventas de su propia sucursal."""
    venta = venta_repo.obtener(db, venta_id)
    if PERMISO_STAFF in permisos_de_usuario(db, usuario_id):
        organizacion_politicas.validar_acceso_sucursal(db, usuario_id, venta.sucursal_id)
    else:
        cliente = obtener_perfil_cliente(db, usuario_id)
        if cliente is None or venta.cliente_id != cliente.id:
            raise PermisoDenegadoError("No tenés acceso a esta venta")
    return venta


# ---- Punto de entrada para otros paquetes ------------------------------------


def listar_variantes_compradas(db: Session, cliente_id: int) -> set[int]:
    """Para `inteligencia` (capa de reglas del recomendador): variantes que
    un cliente ya compró, para excluirlas del recomendador. Cuenta
    cualquier venta que no haya sido anulada (pendiente_pago/pagada/
    entregada sí cuentan)."""
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
    """Para `reportes`: filas crudas de vw_ventas_detalle."""
    return ventas_repo.detalle(db, periodo.desde, periodo.hasta, sucursal_id, categoria_id, canal)


def reporte_ventas_resumen(
    db: Session,
    periodo: ParametrosPeriodo,
    sucursal_id: int | None = None,
    categoria_id: int | None = None,
    canal: str | None = None,
) -> dict:
    """Para `reportes`: total vendido, transacciones y margen bruto del
    período (el ticket promedio lo calcula quien llama, dividiendo)."""
    return ventas_repo.resumen(db, periodo.desde, periodo.hasta, sucursal_id, categoria_id, canal)


def reporte_ventas_top_productos(
    db: Session,
    periodo: ParametrosPeriodo,
    sucursal_id: int | None = None,
    categoria_id: int | None = None,
    canal: str | None = None,
    limite: int = 10,
) -> list[dict]:
    """Para `reportes`: productos más vendidos del período."""
    return ventas_repo.top_productos(db, periodo.desde, periodo.hasta, sucursal_id, categoria_id, canal, limite)


def reporte_ventas_por_canal(
    db: Session, periodo: ParametrosPeriodo, sucursal_id: int | None = None, categoria_id: int | None = None
) -> list[dict]:
    """Para `reportes`: ventas agrupadas por canal (digital/presencial)."""
    return ventas_repo.por_canal(db, periodo.desde, periodo.hasta, sucursal_id, categoria_id)


def reporte_ventas_por_sucursal(
    db: Session,
    periodo: ParametrosPeriodo,
    categoria_id: int | None = None,
    canal: str | None = None,
    sucursal_id: int | None = None,
) -> list[dict]:
    """Para `reportes`: ventas agrupadas por sucursal (con `sucursal_id`,
    solo la fila de esa sucursal: lo que ve un encargado)."""
    return ventas_repo.por_sucursal(db, periodo.desde, periodo.hasta, categoria_id, canal, sucursal_id)


def contar_ventas_con_reserva(db: Session, periodo: ParametrosPeriodo, sucursal_id: int | None = None) -> int:
    """Para `reportes` (tasa de conversión de reservas a ventas): ventas
    del período que se originaron en una reserva."""
    return ventas_repo.contar_ventas_con_reserva(db, periodo.desde, periodo.hasta, sucursal_id)


def contar_ventas_por_variante(db: Session, variante_ids: list[int]) -> dict[int, int]:
    """Para `inteligencia` (fallback de popularidad para clientes nuevos/
    anónimos sin historial): cantidad total vendida de cada variante,
    contando solo ventas no anuladas."""
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
