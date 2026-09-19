from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import NoEncontradoError
from app.inventario.models import MovimientoInventario, Stock, Transferencia, TransferenciaDetalle, TipoMovimiento

# La misma vista que documenta docs/fashionstore_esquema.sql. Cruza
# producto/producto_variante/talla/color (catalogo) y sucursal
# (organizacion) con stock (inventario): es una vista de reportes ya
# definida en el esquema, no una consulta cruda del código a tablas de
# otro paquete, así que vive acá igual que la migración que la crea.
VW_INVENTARIO_CONSOLIDADO_SQL = """
CREATE VIEW vw_inventario_consolidado AS
SELECT  p.id                AS producto_id,
        p.nombre            AS producto,
        v.id                AS variante_id,
        v.sku,
        t.codigo            AS talla,
        c.nombre            AS color,
        s.id                AS sucursal_id,
        s.nombre            AS sucursal,
        st.cantidad_fisica,
        st.cantidad_reservada,
        st.cantidad_disponible,
        st.stock_minimo,
        st.costo_promedio,
        (st.cantidad_fisica * st.costo_promedio) AS valor_inventario
FROM stock st
JOIN producto_variante v ON v.id = st.variante_id
JOIN producto p          ON p.id = v.producto_id
JOIN talla t             ON t.id = v.talla_id
JOIN color c             ON c.id = v.color_id
JOIN sucursal s          ON s.id = st.sucursal_id
"""


class StockRepository:
    """No hereda de CRUDBase: `stock` no tiene columna `activo` (una fila
    de stock existe o no existe; no se "desactiva") y su creación necesita
    ir bloqueada junto con el resto de `registrar_movimiento`/`reservar_stock`,
    algo que el CRUD genérico no contempla."""

    def obtener_o_crear_bloqueado(self, db: Session, variante_id: int, sucursal_id: int) -> Stock:
        """Devuelve la fila de stock lista para modificar dentro de la
        transacción actual. En Postgres la trae con SELECT FOR UPDATE para
        evitar condiciones de carrera entre movimientos concurrentes sobre
        la misma variante+sucursal; en SQLite (tests) no existe FOR UPDATE,
        así que se omite ahí."""
        consulta = select(Stock).where(Stock.variante_id == variante_id, Stock.sucursal_id == sucursal_id)
        if db.get_bind().dialect.name == "postgresql":
            consulta = consulta.with_for_update()
        stock = db.scalars(consulta).one_or_none()
        if stock is None:
            stock = Stock(
                variante_id=variante_id,
                sucursal_id=sucursal_id,
                cantidad_fisica=0,
                cantidad_reservada=0,
                costo_promedio=Decimal("0"),
            )
            db.add(stock)
            db.flush()
        return stock

    def obtener(self, db: Session, stock_id: int) -> Stock:
        stock = db.get(Stock, stock_id)
        if stock is None:
            raise NoEncontradoError("Stock no encontrado")
        return stock

    def obtener_por_variante_sucursal(self, db: Session, variante_id: int, sucursal_id: int) -> Stock | None:
        return db.scalar(
            select(Stock).where(Stock.variante_id == variante_id, Stock.sucursal_id == sucursal_id)
        )

    def listar_por_variante(self, db: Session, variante_id: int) -> list[Stock]:
        return list(db.scalars(select(Stock).where(Stock.variante_id == variante_id)))

    def listar_por_sucursal(self, db: Session, sucursal_id: int) -> list[Stock]:
        return list(
            db.scalars(select(Stock).where(Stock.sucursal_id == sucursal_id).order_by(Stock.variante_id))
        )

    def listar_variantes_con_stock(self, db: Session, sucursal_id: int | None = None) -> set[int]:
        """Para `inteligencia` (P6.2) y `catalogo` (CU-10, `solo_disponibles`):
        variantes con stock disponible, en cualquier sucursal si no se pasa
        `sucursal_id`, o en esa sola si se pasa."""
        consulta = select(Stock.variante_id).where(Stock.cantidad_disponible > 0)
        if sucursal_id is not None:
            consulta = consulta.where(Stock.sucursal_id == sucursal_id)
        return set(db.scalars(consulta.distinct()))

    def listar_con_alerta(self, db: Session, sucursal_id: int | None = None) -> list[Stock]:
        consulta = select(Stock).where(Stock.cantidad_disponible <= Stock.stock_minimo)
        if sucursal_id is not None:
            consulta = consulta.where(Stock.sucursal_id == sucursal_id)
        return list(db.scalars(consulta.order_by(Stock.sucursal_id, Stock.variante_id)))

    def actualizar_limites(
        self, db: Session, stock: Stock, stock_minimo: int | None, stock_maximo: int | None
    ) -> Stock:
        if stock_minimo is not None:
            stock.stock_minimo = stock_minimo
        if stock_maximo is not None:
            stock.stock_maximo = stock_maximo
        db.commit()
        db.refresh(stock)
        return stock


class MovimientoRepository:
    """Libro inmutable: solo `crear` y consultas de lectura. No hay
    `actualizar` ni `eliminar` a propósito (ver models.MovimientoInventario)."""

    def crear(self, db: Session, movimiento: MovimientoInventario) -> MovimientoInventario:
        db.add(movimiento)
        db.flush()
        return movimiento

    def listar_por_variante_sucursal(
        self, db: Session, variante_id: int, sucursal_id: int
    ) -> list[MovimientoInventario]:
        return list(
            db.scalars(
                select(MovimientoInventario)
                .where(
                    MovimientoInventario.variante_id == variante_id,
                    MovimientoInventario.sucursal_id == sucursal_id,
                )
                .order_by(MovimientoInventario.id)
            )
        )


class TipoMovimientoRepository:
    def obtener_por_codigo(self, db: Session, codigo: str) -> TipoMovimiento:
        tipo = db.scalar(select(TipoMovimiento).where(TipoMovimiento.codigo == codigo))
        if tipo is None:
            raise NoEncontradoError(f"Tipo de movimiento '{codigo}' no encontrado")
        return tipo

    def listar(self, db: Session) -> list[TipoMovimiento]:
        return list(db.scalars(select(TipoMovimiento).order_by(TipoMovimiento.id)))


class TransferenciaRepository:
    """No hereda de CRUDBase: `transferencia` no tiene columna `activo`,
    su ciclo de vida es la máquina de estados `estado` (pendiente ->
    en_transito -> recibida, o anulada), no un borrado lógico."""

    def crear(self, db: Session, transferencia: Transferencia) -> Transferencia:
        db.add(transferencia)
        db.commit()
        db.refresh(transferencia)
        return transferencia

    def obtener_por_codigo(self, db: Session, codigo: str) -> Transferencia | None:
        return db.scalar(select(Transferencia).where(Transferencia.codigo == codigo))

    def obtener(self, db: Session, transferencia_id: int) -> Transferencia:
        transferencia = db.scalar(
            select(Transferencia)
            .where(Transferencia.id == transferencia_id)
            .options(selectinload(Transferencia.detalle))
        )
        if transferencia is None:
            raise NoEncontradoError("Transferencia no encontrada")
        return transferencia

    def listar(self, db: Session, sucursal_id: int | None = None) -> list[Transferencia]:
        consulta = select(Transferencia).options(selectinload(Transferencia.detalle)).order_by(
            Transferencia.id.desc()
        )
        if sucursal_id is not None:
            consulta = consulta.where(
                (Transferencia.sucursal_origen_id == sucursal_id)
                | (Transferencia.sucursal_destino_id == sucursal_id)
            )
        return list(db.scalars(consulta))


def _filas_a_dicts(db: Session, consulta: str, parametros: dict) -> list[dict]:
    filas = db.execute(text(consulta), parametros).mappings().all()
    return [dict(fila) for fila in filas]


def consolidado(db: Session, sucursal_id: int | None = None, producto_id: int | None = None) -> list[dict]:
    condiciones = []
    parametros: dict = {}
    if sucursal_id is not None:
        condiciones.append("sucursal_id = :sucursal_id")
        parametros["sucursal_id"] = sucursal_id
    if producto_id is not None:
        condiciones.append("producto_id = :producto_id")
        parametros["producto_id"] = producto_id
    consulta = "SELECT * FROM vw_inventario_consolidado"
    if condiciones:
        consulta += " WHERE " + " AND ".join(condiciones)
    consulta += " ORDER BY producto_id, variante_id, sucursal_id"
    return _filas_a_dicts(db, consulta, parametros)


def alertas(db: Session, sucursal_id: int | None = None) -> list[dict]:
    condiciones = ["cantidad_disponible <= stock_minimo"]
    parametros: dict = {}
    if sucursal_id is not None:
        condiciones.append("sucursal_id = :sucursal_id")
        parametros["sucursal_id"] = sucursal_id
    consulta = "SELECT * FROM vw_inventario_consolidado WHERE " + " AND ".join(condiciones)
    consulta += " ORDER BY producto_id, variante_id, sucursal_id"
    return _filas_a_dicts(db, consulta, parametros)


def valuacion(db: Session, sucursal_id: int | None = None) -> list[dict]:
    parametros: dict = {}
    consulta = (
        "SELECT sucursal_id, sucursal, SUM(valor_inventario) AS valor_total "
        "FROM vw_inventario_consolidado"
    )
    if sucursal_id is not None:
        consulta += " WHERE sucursal_id = :sucursal_id"
        parametros["sucursal_id"] = sucursal_id
    consulta += " GROUP BY sucursal_id, sucursal ORDER BY sucursal_id"
    return _filas_a_dicts(db, consulta, parametros)
