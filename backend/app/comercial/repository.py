from __future__ import annotations

import datetime as dt

from sqlalchemy import Select, bindparam, func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from app.comercial.models import (
    Carrito,
    CarritoDetalle,
    Devolucion,
    DevolucionDetalle,
    DireccionCliente,
    Envio,
    EstadoPago,
    EstadoReserva,
    EstadoVenta,
    MetodoPago,
    Pago,
    Promocion,
    PromocionAlcance,
    ReglaTarifaEnvio,
    Reserva,
    TransaccionPasarela,
    Venta,
    ZonaEnvio,
)
from app.comercial.schemas import (
    DireccionClienteActualizar,
    DireccionClienteCrear,
    ZonaEnvioActualizar,
    ZonaEnvioCrear,
)
from app.core.crud_base import CRUDBase
from app.core.deps import ParametrosPaginacion
from app.core.exceptions import NoEncontradoError
from app.core.repository import confirmar, obtener_por_clave
from app.core.tenant import condicion_empresa


# ---- Reservas ----


class EstadoReservaRepository:
    def obtener_por_codigo(self, db: Session, codigo: str) -> EstadoReserva:
        estado = db.scalar(select(EstadoReserva).where(EstadoReserva.codigo == codigo))
        if estado is None:
            raise NoEncontradoError(f"Estado de reserva '{codigo}' no encontrado")
        return estado

    def obtener(self, db: Session, estado_id: int) -> EstadoReserva:
        estado = db.get(EstadoReserva, estado_id)
        if estado is None:
            raise NoEncontradoError("Estado de reserva no encontrado")
        return estado

    def mapa_codigos_por_id(self, db: Session) -> dict[int, str]:
        return {estado.id: estado.codigo for estado in db.scalars(select(EstadoReserva))}


class ReservaRepository:
    """No hereda de CRUDBase: `reserva` no tiene columna `activo`, su ciclo
    de vida es la máquina de estados de comercial.politicas (bloque Reservas), y crear() maneja
    detalle + historial como parte de la misma operación."""

    def _consulta_base(self):
        return select(Reserva).options(selectinload(Reserva.detalle), selectinload(Reserva.historial))

    def obtener_por_codigo(self, db: Session, codigo: str) -> Reserva | None:
        return db.scalar(self._consulta_base().where(Reserva.codigo == codigo))

    def obtener(self, db: Session, reserva_id: int) -> Reserva:
        reserva = db.scalar(self._consulta_base().where(Reserva.id == reserva_id))
        if reserva is None:
            raise NoEncontradoError("Reserva no encontrada")
        return reserva

    def obtener_bloqueado(self, db: Session, reserva_id: int) -> Reserva:
        """Igual que obtener(), pero con SELECT FOR UPDATE (Postgres) y
        populate_existing=True: serializa las operaciones que leen el estado
        de la reserva y después mueven stock (facturarla, expirarla). Mismo
        patrón que comercial.repository.VentaRepository.obtener_bloqueado."""
        consulta = self._consulta_base().where(Reserva.id == reserva_id)
        if db.get_bind().dialect.name == "postgresql":
            consulta = consulta.with_for_update()
        reserva = db.scalars(consulta.execution_options(populate_existing=True)).one_or_none()
        if reserva is None:
            raise NoEncontradoError("Reserva no encontrada")
        return reserva

    def listar_por_cliente(self, db: Session, cliente_id: int) -> list[Reserva]:
        return list(
            db.scalars(
                self._consulta_base().where(Reserva.cliente_id == cliente_id).order_by(Reserva.creado_en.desc())
            )
        )

    def listar_por_sucursal(self, db: Session, sucursal_id: int) -> list[Reserva]:
        return list(
            db.scalars(
                self._consulta_base().where(Reserva.sucursal_id == sucursal_id).order_by(Reserva.creado_en.desc())
            )
        )

    def listar_vencidas(self, db: Session, ahora: dt.datetime, estados_ids: list[int]) -> list[Reserva]:
        return list(
            db.scalars(
                self._consulta_base().where(
                    Reserva.fecha_expiracion < ahora,
                    Reserva.estado_id.in_(estados_ids),
                )
            )
        )

    def crear(self, db: Session, reserva: Reserva) -> Reserva:
        db.add(reserva)
        db.flush()
        return reserva

    def contar_por_estado(
        self, db: Session, desde: dt.date, hasta: dt.date, sucursal_id: int | None = None
    ) -> list[dict]:
        """Para `inteligencia` (reportes, P6.3): cantidad de reservas por estado en el
        período, filtradas por `fecha_visita`."""
        condiciones = [Reserva.fecha_visita >= desde, Reserva.fecha_visita <= hasta]
        if sucursal_id is not None:
            condiciones.append(Reserva.sucursal_id == sucursal_id)
        consulta = (
            select(EstadoReserva.codigo, EstadoReserva.nombre, func.count(Reserva.id).label("cantidad"))
            .join(Reserva, Reserva.estado_id == EstadoReserva.id)
            .where(*condiciones)
            .group_by(EstadoReserva.codigo, EstadoReserva.nombre)
            .order_by(EstadoReserva.codigo)
        )
        return [dict(fila) for fila in db.execute(consulta).mappings().all()]


# ---- Ventas ----


# Vista de reportes documentada en docs/fashionstore_esquema.sql, nunca
# creada por una migración hasta P6.3. Extendida con producto_id/
# categoria_id/categoria (el esquema documentado solo trae `producto`,
# pero /reportes/ventas necesita filtrar por categoría) -- vive acá porque
# la vista pertenece conceptualmente a la sección Ventas (agrega venta_detalle),
# mismo criterio que vw_inventario_consolidado vive en la sección Inventario
# de `catalogo`.
# NO EDITAR: la usa la migración 6f4501e2abc6 (congelada como V1). La vista
# con empresa_id es VW_VENTAS_DETALLE_V2_SQL.
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

# V2 (multitenant, E01): igual que V1 más `empresa_id` AL FINAL de la lista de
# columnas y cada JOIN exige la misma empresa (una fila con referencias
# cruzadas entre empresas no aparece). La crea la migración
# multitenant_empresa_plan_suscripcion, que lleva este SQL copiado (embebido);
# tests/plataforma/test_vistas_empresa.py comprueba que ambos coinciden.
VW_VENTAS_DETALLE_V2_SQL = """
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
        (vd.subtotal - (vd.cantidad * COALESCE(vd.costo_unitario, 0))) AS margen,
        ve.empresa_id      AS empresa_id
FROM venta_detalle vd
JOIN venta ve            ON ve.id = vd.venta_id AND ve.empresa_id = vd.empresa_id
JOIN sucursal s          ON s.id = ve.sucursal_id AND s.empresa_id = ve.empresa_id
JOIN producto_variante v ON v.id = vd.variante_id AND v.empresa_id = ve.empresa_id
JOIN producto p          ON p.id = v.producto_id AND p.empresa_id = ve.empresa_id
JOIN categoria cat       ON cat.id = p.categoria_id AND cat.empresa_id = ve.empresa_id
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
    comercial.politicas.registrar_venta)."""

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
        catalogo.repository.StockRepository.obtener_o_crear_bloqueado y
        comercial.repository.PagoRepository.obtener_bloqueado."""
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

    def existe_venta_previa_de_reserva(self, db: Session, reserva_id: int) -> bool:
        """True si la reserva ya dio origen a alguna venta, en el estado que
        sea. Esa venta ya consumió el stock apartado de la reserva (si se
        pagó) o lo liberó (si se anuló), así que una nueva venta de la misma
        reserva ya no tiene apartado propio."""
        venta_id = db.scalar(select(Venta.id).where(Venta.reserva_id == reserva_id).limit(1))
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

    def listar_vigentes(self, db: Session, hoy: dt.date) -> list[Promocion]:
        """Todas las promociones activas y vigentes hoy, con sus alcances (2 consultas en total,
        sin importar cuántas sean)."""
        consulta = (
            self._consulta_base()
            .where(Promocion.activo.is_(True), Promocion.fecha_inicio <= hoy, Promocion.fecha_fin >= hoy)
            .order_by(Promocion.id)
        )
        return list(db.scalars(consulta))

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

    def quitar_linea(self, db: Session, linea: CarritoDetalle) -> None:
        db.delete(linea)

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

    def obtener_por_codigo(self, db: Session, codigo: str) -> Devolucion | None:
        return db.scalar(select(Devolucion).where(Devolucion.codigo == codigo))

    def crear(self, db: Session, devolucion: Devolucion) -> Devolucion:
        db.add(devolucion)
        db.flush()
        return devolucion

    def unidades_devueltas_por_venta(self, db: Session, venta_ids: list[int]) -> dict[int, int]:
        """Unidades ya devueltas (devoluciones aprobadas) de cada venta, en UNA consulta: `venta_id` -> unidades.
        Las ventas sin devoluciones no aparecen. Para mostrar "con devolución" en las listas sin tocar el estado."""
        if not venta_ids:
            return {}
        filas = db.execute(
            select(Devolucion.venta_id, func.coalesce(func.sum(DevolucionDetalle.cantidad), 0))
            .join(DevolucionDetalle, DevolucionDetalle.devolucion_id == Devolucion.id)
            .where(Devolucion.venta_id.in_(venta_ids), Devolucion.estado == "aprobada")
            .group_by(Devolucion.venta_id)
        ).all()
        return {int(venta_id): int(total) for venta_id, total in filas}

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


# ---- Consultas para reportes ---------------------------------------------------------
# Funciones módulo, no de clase -- mismo criterio que consolidado()/alertas()/
# valuacion() en catalogo/repository.py: consultas de solo lectura contra
# una vista de reportes, no CRUD.


def _consulta_en_texto(consulta: str, parametros: dict):
    """El `text()` de la consulta. Un parámetro cuyo valor es una lista o tupla se declara
    `expanding` (`campo IN :campo` se abre en un marcador por elemento): así las listas de
    sucursales, categorías y productos viajan siempre como parámetros, nunca pegadas al SQL.
    Una lista vacía no coincide con nada (SQLAlchemy la expande a un conjunto vacío)."""
    listas = [
        bindparam(nombre, expanding=True) for nombre, valor in parametros.items() if isinstance(valor, (list, tuple))
    ]
    sentencia = text(consulta)
    return sentencia.bindparams(*listas) if listas else sentencia


def _filas_a_dicts(db: Session, consulta: str, parametros: dict) -> list[dict]:
    filas = db.execute(_consulta_en_texto(consulta, parametros), parametros).mappings().all()
    return [dict(fila) for fila in filas]


# Lo único que cuenta como vendido en los reportes: una venta
# 'pendiente_pago' todavía no se cobró (ni tiene costo congelado, así que
# sumaría margen 100 %) y una 'anulada' nunca se concretó o se reembolsó.
# vw_ventas_detalle no trae el estado (es la vista documentada en el
# esquema), así que se filtra acá, contra las tablas propias de la sección Ventas.
ESTADOS_VENTA_EFECTIVA = ("pagada", "entregada")

_CONDICION_VENTA_EFECTIVA = (
    "venta_id IN (SELECT ve.id FROM venta ve JOIN estado_venta ev ON ev.id = ve.estado_id "
    "WHERE ev.codigo IN (" + ", ".join(f"'{codigo}'" for codigo in ESTADOS_VENTA_EFECTIVA) + "))"
)


def _condiciones_ventas(
    db: Session,
    desde: dt.date,
    hasta: dt.date,
    sucursal_id: int | None,
    categoria_id: int | None,
    canal: str | None,
    *,
    sucursal_ids: list[int] | None = None,
    categoria_ids: list[int] | None = None,
    producto_ids: list[int] | None = None,
) -> tuple[list[str], dict]:
    # Los parámetros singulares y las listas (reportes generativos, E09) se suman con AND.
    # None = sin filtro; una lista vacía no coincide con nada.
    # hasta_exclusiva: `fecha` es timestamp, desde/hasta son solo fecha --
    # sin esto, las ventas del día `hasta` (con hora > 00:00) quedarían
    # afuera del rango.
    condicion_tenant, parametros_tenant = condicion_empresa(db)
    condiciones = [condicion_tenant, "fecha >= :desde", "fecha < :hasta_exclusiva", _CONDICION_VENTA_EFECTIVA]
    parametros: dict = {
        **parametros_tenant,
        "desde": desde,
        "hasta_exclusiva": hasta + dt.timedelta(days=1),
    }
    if sucursal_id is not None:
        condiciones.append("sucursal_id = :sucursal_id")
        parametros["sucursal_id"] = sucursal_id
    if categoria_id is not None:
        condiciones.append("categoria_id = :categoria_id")
        parametros["categoria_id"] = categoria_id
    if canal is not None:
        condiciones.append("canal = :canal")
        parametros["canal"] = canal
    for columna, valores in (
        ("sucursal_id", sucursal_ids),
        ("categoria_id", categoria_ids),
        ("producto_id", producto_ids),
    ):
        if valores is not None:
            condiciones.append(f"{columna} IN :{columna}s")
            parametros[f"{columna}s"] = [int(valor) for valor in valores]
    return condiciones, parametros


def detalle(
    db: Session,
    desde: dt.date,
    hasta: dt.date,
    sucursal_id: int | None = None,
    categoria_id: int | None = None,
    canal: str | None = None,
) -> list[dict]:
    condiciones, parametros = _condiciones_ventas(db, desde, hasta, sucursal_id, categoria_id, canal)
    consulta = "SELECT * FROM vw_ventas_detalle WHERE " + " AND ".join(condiciones) + " ORDER BY fecha DESC"
    return _filas_a_dicts(db, consulta, parametros)


def resumen(
    db: Session,
    desde: dt.date,
    hasta: dt.date,
    sucursal_id: int | None = None,
    categoria_id: int | None = None,
    canal: str | None = None,
    *,
    sucursal_ids: list[int] | None = None,
    categoria_ids: list[int] | None = None,
) -> dict:
    condiciones, parametros = _condiciones_ventas(
        db, desde, hasta, sucursal_id, categoria_id, canal, sucursal_ids=sucursal_ids, categoria_ids=categoria_ids
    )
    consulta = (
        "SELECT COUNT(DISTINCT venta_id) AS transacciones, "
        "COALESCE(SUM(subtotal), 0) AS total_ventas, "
        "COALESCE(SUM(margen), 0) AS margen_bruto "
        "FROM vw_ventas_detalle WHERE " + " AND ".join(condiciones)
    )
    fila = db.execute(_consulta_en_texto(consulta, parametros), parametros).mappings().one()
    return dict(fila)


def top_productos(
    db: Session,
    desde: dt.date,
    hasta: dt.date,
    sucursal_id: int | None = None,
    categoria_id: int | None = None,
    canal: str | None = None,
    limite: int = 10,
    *,
    sucursal_ids: list[int] | None = None,
    categoria_ids: list[int] | None = None,
    producto_ids: list[int] | None = None,
    ascendente: bool = False,
) -> list[dict]:
    condiciones, parametros = _condiciones_ventas(
        db,
        desde,
        hasta,
        sucursal_id,
        categoria_id,
        canal,
        sucursal_ids=sucursal_ids,
        categoria_ids=categoria_ids,
        producto_ids=producto_ids,
    )
    parametros["limite"] = limite
    # Solo entran productos con ventas en el período; con `ascendente` salen los que menos
    # vendieron DE ESOS. El desempate por id deja el orden estable.
    sentido = "ASC" if ascendente else "DESC"
    consulta = (
        "SELECT producto_id, producto, SUM(cantidad) AS cantidad_vendida, SUM(subtotal) AS total_vendido "
        "FROM vw_ventas_detalle WHERE "
        + " AND ".join(condiciones)
        + f" GROUP BY producto_id, producto ORDER BY cantidad_vendida {sentido}, producto_id LIMIT :limite"
    )
    return _filas_a_dicts(db, consulta, parametros)


def por_canal(
    db: Session, desde: dt.date, hasta: dt.date, sucursal_id: int | None = None, categoria_id: int | None = None
) -> list[dict]:
    condiciones, parametros = _condiciones_ventas(db, desde, hasta, sucursal_id, categoria_id, None)
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
    *,
    sucursal_ids: list[int] | None = None,
    categoria_ids: list[int] | None = None,
) -> list[dict]:
    condiciones, parametros = _condiciones_ventas(
        db, desde, hasta, sucursal_id, categoria_id, canal, sucursal_ids=sucursal_ids, categoria_ids=categoria_ids
    )
    consulta = (
        "SELECT sucursal_id, sucursal, COUNT(DISTINCT venta_id) AS transacciones, SUM(subtotal) AS total_ventas "
        "FROM vw_ventas_detalle WHERE " + " AND ".join(condiciones) + " GROUP BY sucursal_id, sucursal ORDER BY sucursal_id"
    )
    return _filas_a_dicts(db, consulta, parametros)


def serie_diaria(
    db: Session,
    desde: dt.date,
    hasta: dt.date,
    *,
    sucursal_ids: list[int] | None = None,
    categoria_ids: list[int] | None = None,
    producto_ids: list[int] | None = None,
    canal: str | None = None,
    desglose: tuple[str, ...] = (),
) -> list[dict]:
    """Ventas por día (`date(fecha)`, portable SQLite/PostgreSQL), opcionalmente desglosadas por
    sucursal y/o categoría. `dia` llega como texto en SQLite y como date en PostgreSQL: lo
    normaliza quien llama. Solo salen los días con ventas."""
    condiciones, parametros = _condiciones_ventas(
        db,
        desde,
        hasta,
        None,
        None,
        canal,
        sucursal_ids=sucursal_ids,
        categoria_ids=categoria_ids,
        producto_ids=producto_ids,
    )
    columnas = ["date(fecha) AS dia"]
    agrupar = ["date(fecha)"]
    ordenar = ["dia"]
    if "sucursal" in desglose:
        columnas += ["sucursal_id", "sucursal"]
        agrupar += ["sucursal_id", "sucursal"]
        ordenar.append("sucursal_id")
    if "categoria" in desglose:
        columnas += ["categoria_id", "categoria"]
        agrupar += ["categoria_id", "categoria"]
        ordenar.append("categoria_id")
    columnas += [
        "COUNT(DISTINCT venta_id) AS transacciones",
        "SUM(cantidad) AS unidades",
        "SUM(subtotal) AS total_ventas",
        # E11: lo vendido a precio de lista (antes del descuento). La vista ya trae el precio
        # unitario, así que no hace falta otra consulta ni otra migración; el descuento del día
        # es `ventas_brutas - total_ventas`.
        "SUM(precio_unitario * cantidad) AS ventas_brutas",
    ]
    consulta = (
        "SELECT "
        + ", ".join(columnas)
        + " FROM vw_ventas_detalle WHERE "
        + " AND ".join(condiciones)
        + " GROUP BY "
        + ", ".join(agrupar)
        + " ORDER BY "
        + ", ".join(ordenar)
    )
    return _filas_a_dicts(db, consulta, parametros)


def por_categoria(
    db: Session,
    desde: dt.date,
    hasta: dt.date,
    *,
    sucursal_ids: list[int] | None = None,
    canal: str | None = None,
) -> list[dict]:
    condiciones, parametros = _condiciones_ventas(db, desde, hasta, None, None, canal, sucursal_ids=sucursal_ids)
    consulta = (
        "SELECT categoria_id, categoria, SUM(cantidad) AS unidades, SUM(subtotal) AS total_vendido, "
        "SUM(margen) AS margen_bruto, COUNT(DISTINCT venta_id) AS transacciones "
        "FROM vw_ventas_detalle WHERE "
        + " AND ".join(condiciones)
        + " GROUP BY categoria_id, categoria ORDER BY total_vendido DESC, categoria_id"
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


def rfm_clientes(db: Session, desde: dt.date, hasta: dt.date, tope: int) -> list[dict]:
    """Recencia, frecuencia y monto por cliente (E11): una fila por cliente con ventas efectivas
    (pagada o entregada) entre `desde` y `hasta`, ambos días incluidos. Las ventas anónimas
    (`cliente_id` nulo) no entran. Consulta del ORM: el alcance de empresa lo agrega solo
    `core/tenant`, aquí nadie filtra a mano. Orden por `cliente_id` y corte en `tope` filas,
    para que dos corridas sobre los mismos datos entreguen exactamente lo mismo."""
    consulta = (
        select(
            Venta.cliente_id,
            func.max(Venta.fecha).label("ultima_compra"),
            func.count(Venta.id).label("frecuencia"),
            func.coalesce(func.sum(Venta.total), 0).label("monto_total"),
        )
        .join(EstadoVenta, EstadoVenta.id == Venta.estado_id)
        .where(
            Venta.cliente_id.is_not(None),
            EstadoVenta.codigo.in_(ESTADOS_VENTA_EFECTIVA),
            # `fecha` es timestamp: el día `hasta` entero entra, por eso el límite es exclusivo.
            Venta.fecha >= desde,
            Venta.fecha < hasta + dt.timedelta(days=1),
        )
        .group_by(Venta.cliente_id)
        .order_by(Venta.cliente_id)
        .limit(tope)
    )
    return [dict(fila) for fila in db.execute(consulta).mappings().all()]


# ---- Pagos ----


class MetodoPagoRepository:
    def obtener_por_codigo(self, db: Session, codigo: str) -> MetodoPago:
        metodo = db.scalar(select(MetodoPago).where(MetodoPago.codigo == codigo))
        if metodo is None or not metodo.activo:
            raise NoEncontradoError(f"Método de pago '{codigo}' no encontrado")
        return metodo


class EstadoPagoRepository:
    def obtener_por_codigo(self, db: Session, codigo: str) -> EstadoPago:
        estado = db.scalar(select(EstadoPago).where(EstadoPago.codigo == codigo))
        if estado is None:
            raise NoEncontradoError(f"Estado de pago '{codigo}' no encontrado")
        return estado

    def obtener(self, db: Session, estado_id: int) -> EstadoPago:
        estado = db.get(EstadoPago, estado_id)
        if estado is None:
            raise NoEncontradoError("Estado de pago no encontrado")
        return estado

    def mapa_codigos_por_id(self, db: Session) -> dict[int, str]:
        return {estado.id: estado.codigo for estado in db.scalars(select(EstadoPago))}


class PagoRepository:
    def obtener(self, db: Session, pago_id: int) -> Pago:
        pago = obtener_por_clave(db, Pago, pago_id)
        if pago is None:
            raise NoEncontradoError("Pago no encontrado")
        return pago

    def obtener_bloqueado(self, db: Session, pago_id: int) -> Pago:
        """Igual que obtener(), pero con SELECT FOR UPDATE (Postgres) y
        populate_existing=True: si otra transacción concurrente ya resolvió
        este pago y comiteó mientras esta esperaba el lock, refresca el
        `estado_id` en memoria en vez de operar sobre el valor viejo leído
        antes del lock. Mismo patrón que
        catalogo.repository.StockRepository.obtener_o_crear_bloqueado."""
        consulta = select(Pago).where(Pago.id == pago_id)
        if db.get_bind().dialect.name == "postgresql":
            consulta = consulta.with_for_update()
        pago = db.scalars(consulta.execution_options(populate_existing=True)).one_or_none()
        if pago is None:
            raise NoEncontradoError("Pago no encontrado")
        return pago

    def listar_por_venta(self, db: Session, venta_id: int) -> list[Pago]:
        return list(db.scalars(select(Pago).where(Pago.venta_id == venta_id).order_by(Pago.fecha.desc())))

    def crear(self, db: Session, pago: Pago) -> Pago:
        db.add(pago)
        db.flush()
        return pago


class TransaccionPasarelaRepository:
    def crear(self, db: Session, transaccion: TransaccionPasarela) -> TransaccionPasarela:
        db.add(transaccion)
        db.flush()
        return transaccion

    def obtener_por_id_transaccion(self, db: Session, pasarela: str, id_transaccion: str) -> TransaccionPasarela | None:
        """Busca la transacción MÁS VIEJA con este id (la que
        `iniciar_pago` dejó como registro original): así el webhook
        encuentra a qué `pago` corresponde, sin importar cuántas filas de
        evidencia ya se hayan acumulado para esa misma transacción."""
        return db.scalar(
            select(TransaccionPasarela)
            .where(TransaccionPasarela.pasarela == pasarela, TransaccionPasarela.id_transaccion == id_transaccion)
            .order_by(TransaccionPasarela.creado_en.asc())
            .limit(1)
        )


# ---- Entregas ----


class ZonaEnvioRepository(CRUDBase[ZonaEnvio, ZonaEnvioCrear, ZonaEnvioActualizar]):
    def __init__(self) -> None:
        super().__init__(ZonaEnvio)

    def listar_reglas(self, db: Session, zona_envio_id: int) -> list[ReglaTarifaEnvio]:
        return list(
            db.scalars(
                select(ReglaTarifaEnvio)
                .where(ReglaTarifaEnvio.zona_envio_id == zona_envio_id)
                .order_by(ReglaTarifaEnvio.peso_desde_kg)
            )
        )


class DireccionClienteRepository(CRUDBase[DireccionCliente, DireccionClienteCrear, DireccionClienteActualizar]):
    def __init__(self) -> None:
        super().__init__(DireccionCliente)

    def listar_por_cliente(self, db: Session, cliente_id: int) -> list[DireccionCliente]:
        return list(
            db.scalars(
                select(DireccionCliente).where(
                    DireccionCliente.cliente_id == cliente_id, DireccionCliente.activo.is_(True)
                )
            )
        )

    # Override deliberado: `cliente_id` no viene del schema (se resuelve
    # del usuario autenticado en el caso de uso), así que no se puede armar la
    # instancia solo con `datos.model_dump()` como hace CRUDBase.crear.
    def crear(
        self, db: Session, cliente_id: int, datos: DireccionClienteCrear, commit: bool = True
    ) -> DireccionCliente:
        instancia = DireccionCliente(cliente_id=cliente_id, **datos.model_dump())
        db.add(instancia)
        confirmar(db, commit)
        db.refresh(instancia)
        return instancia


class EnvioRepository:
    def obtener(self, db: Session, envio_id: int) -> Envio:
        envio = obtener_por_clave(db, Envio, envio_id)
        if envio is None:
            raise NoEncontradoError("Envío no encontrado")
        return envio

    def obtener_bloqueado(self, db: Session, envio_id: int) -> Envio:
        """Con la fila bloqueada: dos actualizaciones de estado simultáneas
        del mismo envío se serializan en vez de pisarse."""
        envio = db.scalar(select(Envio).where(Envio.id == envio_id).with_for_update())
        if envio is None:
            raise NoEncontradoError("Envío no encontrado")
        return envio

    def listar(
        self,
        db: Session,
        paginacion: ParametrosPaginacion,
        *,
        estado: str | None = None,
        ventas_de_sucursal: Select[tuple[int]] | None = None,
    ) -> list[Envio]:
        consulta = select(Envio)
        if estado is not None:
            consulta = consulta.where(Envio.estado == estado)
        if ventas_de_sucursal is not None:
            consulta = consulta.where(Envio.venta_id.in_(ventas_de_sucursal))
        consulta = consulta.order_by(Envio.id.desc()).offset(paginacion.offset).limit(paginacion.tamanio)
        return list(db.scalars(consulta))

    def obtener_por_venta(self, db: Session, venta_id: int) -> Envio | None:
        return db.scalar(select(Envio).where(Envio.venta_id == venta_id))

    def crear(self, db: Session, envio: Envio, commit: bool = True) -> Envio:
        db.add(envio)
        confirmar(db, commit)
        db.refresh(envio)
        return envio
