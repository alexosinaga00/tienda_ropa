from __future__ import annotations

import datetime as dt

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from app.core.deps import ParametrosPaginacion
from app.core.exceptions import NoEncontradoError
from app.ventas.models import (
    Carrito,
    CarritoDetalle,
    Devolucion,
    DevolucionDetalle,
    EstadoVenta,
    Promocion,
    PromocionAlcance,
    Venta,
)

# Vista de reportes documentada en docs/fashionstore_esquema.sql, nunca
# creada por una migración hasta P6.3. Extendida con producto_id/
# categoria_id/categoria (el esquema documentado solo trae `producto`,
# pero /reportes/ventas necesita filtrar por categoría) -- vive acá porque
# la vista pertenece conceptualmente a `ventas` (agrega venta_detalle),
# mismo criterio que vw_inventario_consolidado vive en `inventario`.
VW_VENTAS_DETALLE_SQL = """
CREATE VIEW vw_ventas_detalle AS
SELECT  ve.id              AS venta_id,
        ve.codigo,
        ve.canal,
        ve.fecha,
        s.id               AS sucursal_id,
        s.nombre           AS sucursal,
        p.id               AS producto_id,
        p.nombre           AS producto,
        cat.id             AS categoria_id,
        cat.nombre         AS categoria,
        vd.cantidad,
        vd.precio_unitario,
        vd.subtotal,
        vd.costo_unitario,
        (vd.subtotal - (vd.cantidad * COALESCE(vd.costo_unitario, 0))) AS margen
FROM venta_detalle vd
JOIN venta ve            ON ve.id = vd.venta_id
JOIN sucursal s          ON s.id = ve.sucursal_id
JOIN producto_variante v ON v.id = vd.variante_id
JOIN producto p          ON p.id = v.producto_id
JOIN categoria cat       ON cat.id = p.categoria_id
"""


class EstadoVentaRepository:
    def obtener_por_codigo(self, db: Session, codigo: str) -> EstadoVenta:
        estado = db.scalar(select(EstadoVenta).where(EstadoVenta.codigo == codigo))
        if estado is None:
            raise NoEncontradoError(f"Estado de venta '{codigo}' no encontrado")
        return estado

    def obtener(self, db: Session, estado_id: int) -> EstadoVenta:
        estado = db.get(EstadoVenta, estado_id)
        if estado is None:
            raise NoEncontradoError("Estado de venta no encontrado")
        return estado

    def mapa_codigos_por_id(self, db: Session) -> dict[int, str]:
        return {estado.id: estado.codigo for estado in db.scalars(select(EstadoVenta))}


class VentaRepository:
    """No hereda de CRUDBase: `venta` no tiene columna `activo` y crear()
    maneja cabecera + detalle como parte de la misma operación (ver
    ventas.politicas.registrar_venta)."""

    def _consulta_base(self):
        return select(Venta).options(selectinload(Venta.detalle))

    def obtener(self, db: Session, venta_id: int) -> Venta:
        venta = db.scalar(self._consulta_base().where(Venta.id == venta_id))
        if venta is None:
            raise NoEncontradoError("Venta no encontrada")
        return venta

    def obtener_bloqueado(self, db: Session, venta_id: int) -> Venta:
        """Igual que obtener(), pero con SELECT FOR UPDATE (Postgres) y
        populate_existing=True para refrescar el `estado_id` en memoria si
        otra transacción concurrente ya confirmó/anuló esta venta y
        comiteó mientras esta esperaba el lock. Mismo patrón que
        inventario.repository.StockRepository.obtener_o_crear_bloqueado y
        pagos.repository.PagoRepository.obtener_bloqueado."""
        consulta = self._consulta_base().where(Venta.id == venta_id)
        if db.get_bind().dialect.name == "postgresql":
            consulta = consulta.with_for_update()
        venta = db.scalars(consulta.execution_options(populate_existing=True)).one_or_none()
        if venta is None:
            raise NoEncontradoError("Venta no encontrada")
        return venta

    def obtener_por_codigo(self, db: Session, codigo: str) -> Venta | None:
        return db.scalar(self._consulta_base().where(Venta.codigo == codigo))

    def listar_por_cliente(self, db: Session, cliente_id: int) -> list[Venta]:
        return list(
            db.scalars(self._consulta_base().where(Venta.cliente_id == cliente_id).order_by(Venta.fecha.desc()))
        )

    def listar_por_sucursal(self, db: Session, sucursal_id: int) -> list[Venta]:
        return list(
            db.scalars(self._consulta_base().where(Venta.sucursal_id == sucursal_id).order_by(Venta.fecha.desc()))
        )

    def existe_venta_vigente_de_reserva(self, db: Session, reserva_id: int) -> bool:
        """True si la reserva ya tiene una venta que no está anulada
        (pendiente de pago, pagada o entregada): una reserva se factura una
        sola vez. Si esa venta se anuló, se puede volver a facturar."""
        venta_id = db.scalar(
            select(Venta.id)
            .join(EstadoVenta, EstadoVenta.id == Venta.estado_id)
            .where(Venta.reserva_id == reserva_id, EstadoVenta.codigo != "anulada")
            .limit(1)
        )
        return venta_id is not None

    def crear(self, db: Session, venta: Venta) -> Venta:
        db.add(venta)
        db.flush()
        return venta


class PromocionRepository:
    def _consulta_base(self):
        return select(Promocion).options(selectinload(Promocion.alcances))

    def obtener(self, db: Session, promocion_id: int) -> Promocion:
        promocion = db.scalar(self._consulta_base().where(Promocion.id == promocion_id))
        if promocion is None:
            raise NoEncontradoError("Promoción no encontrada")
        return promocion

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Promocion]:
        consulta = self._consulta_base().order_by(Promocion.id.desc()).offset(paginacion.offset).limit(
            paginacion.tamanio
        )
        return list(db.scalars(consulta))

    def crear(self, db: Session, promocion: Promocion) -> Promocion:
        db.add(promocion)
        db.flush()
        return promocion

    def listar_vigentes_para(
        self, db: Session, *, producto_id: int, categoria_id: int, temporada_id: int | None, hoy: dt.date
    ) -> list[Promocion]:
        """Promociones activas y vigentes hoy cuyo `promocion_alcance` matchea
        este producto (por producto_id, categoria_id o temporada_id)."""
        condiciones = [PromocionAlcance.producto_id == producto_id, PromocionAlcance.categoria_id == categoria_id]
        if temporada_id is not None:
            condiciones.append(PromocionAlcance.temporada_id == temporada_id)

        consulta = (
            select(Promocion)
            .join(PromocionAlcance, PromocionAlcance.promocion_id == Promocion.id)
            .where(
                Promocion.activo.is_(True),
                Promocion.fecha_inicio <= hoy,
                Promocion.fecha_fin >= hoy,
                or_(*condiciones),
            )
            .distinct()
        )
        return list(db.scalars(consulta))


class CarritoRepository:
    def _consulta_base(self):
        return select(Carrito).options(selectinload(Carrito.detalle))

    def obtener_por_cliente(self, db: Session, cliente_id: int) -> Carrito | None:
        return db.scalar(self._consulta_base().where(Carrito.cliente_id == cliente_id))

    def obtener_o_crear(self, db: Session, cliente_id: int) -> Carrito:
        carrito = self.obtener_por_cliente(db, cliente_id)
        if carrito is None:
            carrito = Carrito(cliente_id=cliente_id)
            db.add(carrito)
            db.flush()
        return carrito

    def obtener_linea(self, db: Session, carrito_id: int, variante_id: int) -> CarritoDetalle | None:
        return db.scalar(
            select(CarritoDetalle).where(
                CarritoDetalle.carrito_id == carrito_id, CarritoDetalle.variante_id == variante_id
            )
        )

    def vaciar(self, db: Session, carrito: Carrito) -> None:
        for linea in list(carrito.detalle):
            db.delete(linea)
        db.flush()


class DevolucionRepository:
    def _consulta_base(self):
        return select(Devolucion).options(selectinload(Devolucion.detalle))

    def obtener(self, db: Session, devolucion_id: int) -> Devolucion:
        devolucion = db.scalar(self._consulta_base().where(Devolucion.id == devolucion_id))
        if devolucion is None:
            raise NoEncontradoError("Devolución no encontrada")
        return devolucion

    def crear(self, db: Session, devolucion: Devolucion) -> Devolucion:
        db.add(devolucion)
        db.flush()
        return devolucion

    def cantidad_devuelta(self, db: Session, venta_detalle_id: int) -> int:
        """Suma de todo lo ya devuelto de esa línea, en TODAS las
        devoluciones anteriores (no solo la que se está creando ahora):
        evita devolver más de lo que se vendió a través de varias
        devoluciones parciales."""
        total = db.scalar(
            select(func.coalesce(func.sum(DevolucionDetalle.cantidad), 0)).where(
                DevolucionDetalle.venta_detalle_id == venta_detalle_id
            )
        )
        return int(total or 0)


# ---- Reportes (P6.3) ---------------------------------------------------------
# Funciones módulo, no de clase -- mismo criterio que consolidado()/alertas()/
# valuacion() en inventario/repository.py: consultas de solo lectura contra
# una vista de reportes, no CRUD.


def _filas_a_dicts(db: Session, consulta: str, parametros: dict) -> list[dict]:
    filas = db.execute(text(consulta), parametros).mappings().all()
    return [dict(fila) for fila in filas]


# Lo único que cuenta como vendido en los reportes: una venta
# 'pendiente_pago' todavía no se cobró (ni tiene costo congelado, así que
# sumaría margen 100 %) y una 'anulada' nunca se concretó o se reembolsó.
# vw_ventas_detalle no trae el estado (es la vista documentada en el
# esquema), así que se filtra acá, contra las tablas propias de `ventas`.
ESTADOS_VENTA_EFECTIVA = ("pagada", "entregada")

_CONDICION_VENTA_EFECTIVA = (
    "venta_id IN (SELECT ve.id FROM venta ve JOIN estado_venta ev ON ev.id = ve.estado_id "
    "WHERE ev.codigo IN (" + ", ".join(f"'{codigo}'" for codigo in ESTADOS_VENTA_EFECTIVA) + "))"
)


def _condiciones_ventas(
    desde: dt.date,
    hasta: dt.date,
    sucursal_id: int | None,
    categoria_id: int | None,
    canal: str | None,
) -> tuple[list[str], dict]:
    # hasta_exclusiva: `fecha` es timestamp, desde/hasta son solo fecha --
    # sin esto, las ventas del día `hasta` (con hora > 00:00) quedarían
    # afuera del rango.
    condiciones = ["fecha >= :desde", "fecha < :hasta_exclusiva", _CONDICION_VENTA_EFECTIVA]
    parametros: dict = {"desde": desde, "hasta_exclusiva": hasta + dt.timedelta(days=1)}
    if sucursal_id is not None:
        condiciones.append("sucursal_id = :sucursal_id")
        parametros["sucursal_id"] = sucursal_id
    if categoria_id is not None:
        condiciones.append("categoria_id = :categoria_id")
        parametros["categoria_id"] = categoria_id
    if canal is not None:
        condiciones.append("canal = :canal")
        parametros["canal"] = canal
    return condiciones, parametros


def detalle(
    db: Session,
    desde: dt.date,
    hasta: dt.date,
    sucursal_id: int | None = None,
    categoria_id: int | None = None,
    canal: str | None = None,
) -> list[dict]:
    condiciones, parametros = _condiciones_ventas(desde, hasta, sucursal_id, categoria_id, canal)
    consulta = "SELECT * FROM vw_ventas_detalle WHERE " + " AND ".join(condiciones) + " ORDER BY fecha DESC"
    return _filas_a_dicts(db, consulta, parametros)


def resumen(
    db: Session,
    desde: dt.date,
    hasta: dt.date,
    sucursal_id: int | None = None,
    categoria_id: int | None = None,
    canal: str | None = None,
) -> dict:
    condiciones, parametros = _condiciones_ventas(desde, hasta, sucursal_id, categoria_id, canal)
    consulta = (
        "SELECT COUNT(DISTINCT venta_id) AS transacciones, "
        "COALESCE(SUM(subtotal), 0) AS total_ventas, "
        "COALESCE(SUM(margen), 0) AS margen_bruto "
        "FROM vw_ventas_detalle WHERE " + " AND ".join(condiciones)
    )
    fila = db.execute(text(consulta), parametros).mappings().one()
    return dict(fila)


def top_productos(
    db: Session,
    desde: dt.date,
    hasta: dt.date,
    sucursal_id: int | None = None,
    categoria_id: int | None = None,
    canal: str | None = None,
    limite: int = 10,
) -> list[dict]:
    condiciones, parametros = _condiciones_ventas(desde, hasta, sucursal_id, categoria_id, canal)
    parametros["limite"] = limite
    consulta = (
        "SELECT producto_id, producto, SUM(cantidad) AS cantidad_vendida, SUM(subtotal) AS total_vendido "
        "FROM vw_ventas_detalle WHERE "
        + " AND ".join(condiciones)
        + " GROUP BY producto_id, producto ORDER BY cantidad_vendida DESC LIMIT :limite"
    )
    return _filas_a_dicts(db, consulta, parametros)


def por_canal(
    db: Session, desde: dt.date, hasta: dt.date, sucursal_id: int | None = None, categoria_id: int | None = None
) -> list[dict]:
    condiciones, parametros = _condiciones_ventas(desde, hasta, sucursal_id, categoria_id, None)
    consulta = (
        "SELECT canal, COUNT(DISTINCT venta_id) AS transacciones, SUM(subtotal) AS total_ventas "
        "FROM vw_ventas_detalle WHERE " + " AND ".join(condiciones) + " GROUP BY canal ORDER BY canal"
    )
    return _filas_a_dicts(db, consulta, parametros)


def por_sucursal(
    db: Session,
    desde: dt.date,
    hasta: dt.date,
    categoria_id: int | None = None,
    canal: str | None = None,
    sucursal_id: int | None = None,
) -> list[dict]:
    condiciones, parametros = _condiciones_ventas(desde, hasta, sucursal_id, categoria_id, canal)
    consulta = (
        "SELECT sucursal_id, sucursal, COUNT(DISTINCT venta_id) AS transacciones, SUM(subtotal) AS total_ventas "
        "FROM vw_ventas_detalle WHERE " + " AND ".join(condiciones) + " GROUP BY sucursal_id, sucursal ORDER BY sucursal_id"
    )
    return _filas_a_dicts(db, consulta, parametros)


def contar_ventas_con_reserva(db: Session, desde: dt.date, hasta: dt.date, sucursal_id: int | None = None) -> int:
    condiciones = [
        Venta.reserva_id.is_not(None),
        Venta.fecha >= desde,
        Venta.fecha < hasta + dt.timedelta(days=1),
        EstadoVenta.codigo.in_(ESTADOS_VENTA_EFECTIVA),
    ]
    if sucursal_id is not None:
        condiciones.append(Venta.sucursal_id == sucursal_id)
    total = db.scalar(
        select(func.count(Venta.id)).join(EstadoVenta, EstadoVenta.id == Venta.estado_id).where(*condiciones)
    )
    return int(total or 0)
