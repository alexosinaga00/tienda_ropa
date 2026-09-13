from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.abastecimiento.models import (
    OrdenCompra,
    OrdenCompraDetalle,
    ProductoProveedor,
    Proveedor,
    Recepcion,
    RecepcionDetalle,
)
from app.abastecimiento.schemas import ProveedorActualizar, ProveedorCrear
from app.core.crud_base import CRUDBase
from app.core.exceptions import ConflictoError, NoEncontradoError


class ProveedorRepository(CRUDBase[Proveedor, ProveedorCrear, ProveedorActualizar]):
    def __init__(self) -> None:
        super().__init__(Proveedor)

    def obtener_por_nit(self, db: Session, nit: str) -> Proveedor | None:
        return db.scalar(select(Proveedor).where(Proveedor.nit == nit))

    def crear(self, db: Session, datos: ProveedorCrear) -> Proveedor:
        existente = self.obtener_por_nit(db, datos.nit) if datos.nit is not None else None
        if existente is not None:
            if existente.activo:
                raise ConflictoError("Ya existe un proveedor con ese NIT")
            for campo, valor in datos.model_dump().items():
                setattr(existente, campo, valor)
            existente.activo = True
            db.commit()
            db.refresh(existente)
            return existente
        return super().crear(db, datos)

    def actualizar(self, db: Session, id_: int, datos: ProveedorActualizar) -> Proveedor:
        if datos.nit is not None:
            existente = self.obtener_por_nit(db, datos.nit)
            if existente is not None and existente.id != id_:
                raise ConflictoError("Ya existe un proveedor con ese NIT")
        return super().actualizar(db, id_, datos)


class ProductoProveedorRepository:
    """PK compuesta (proveedor_id, producto_id), sin `activo`: se quita con
    DELETE físico (igual que favorito)."""

    def listar_por_proveedor(self, db: Session, proveedor_id: int) -> list[ProductoProveedor]:
        return list(
            db.scalars(select(ProductoProveedor).where(ProductoProveedor.proveedor_id == proveedor_id))
        )

    def obtener(self, db: Session, proveedor_id: int, producto_id: int) -> ProductoProveedor | None:
        return db.get(ProductoProveedor, (proveedor_id, producto_id))

    def crear(
        self,
        db: Session,
        proveedor_id: int,
        producto_id: int,
        costo_referencial: Decimal | None,
        dias_entrega: int | None,
    ) -> ProductoProveedor:
        existente = self.obtener(db, proveedor_id, producto_id)
        if existente is not None:
            raise ConflictoError("Ese proveedor ya está asociado a ese producto")
        relacion = ProductoProveedor(
            proveedor_id=proveedor_id,
            producto_id=producto_id,
            costo_referencial=costo_referencial,
            dias_entrega=dias_entrega,
        )
        db.add(relacion)
        db.commit()
        db.refresh(relacion)
        return relacion

    def eliminar(self, db: Session, proveedor_id: int, producto_id: int) -> None:
        relacion = self.obtener(db, proveedor_id, producto_id)
        if relacion is None:
            raise NoEncontradoError("Ese proveedor no está asociado a ese producto")
        db.delete(relacion)
        db.commit()


class OrdenCompraRepository:
    """No hereda de CRUDBase: `orden_compra` no tiene columna `activo`, su
    ciclo de vida es la máquina de estados `estado` (borrador -> enviada ->
    parcial/recibida, o anulada), y crear/actualizar manejan también las
    líneas de `detalle` como parte de la misma operación."""

    def obtener_por_codigo(self, db: Session, codigo: str) -> OrdenCompra | None:
        return db.scalar(select(OrdenCompra).where(OrdenCompra.codigo == codigo))

    def obtener(self, db: Session, orden_id: int) -> OrdenCompra:
        orden = db.scalar(
            select(OrdenCompra).where(OrdenCompra.id == orden_id).options(selectinload(OrdenCompra.detalle))
        )
        if orden is None:
            raise NoEncontradoError("Orden de compra no encontrada")
        return orden

    def listar(self, db: Session, proveedor_id: int | None = None, sucursal_id: int | None = None) -> list[OrdenCompra]:
        consulta = select(OrdenCompra).options(selectinload(OrdenCompra.detalle)).order_by(OrdenCompra.id.desc())
        if proveedor_id is not None:
            consulta = consulta.where(OrdenCompra.proveedor_id == proveedor_id)
        if sucursal_id is not None:
            consulta = consulta.where(OrdenCompra.sucursal_id == sucursal_id)
        return list(db.scalars(consulta))

    def crear(self, db: Session, orden: OrdenCompra) -> OrdenCompra:
        db.add(orden)
        db.commit()
        db.refresh(orden)
        return orden

    def reemplazar_detalle(self, db: Session, orden: OrdenCompra, lineas: list[OrdenCompraDetalle]) -> OrdenCompra:
        orden.detalle = lineas
        orden.total = sum((linea.cantidad * linea.costo_unitario for linea in lineas), Decimal("0"))
        db.commit()
        db.refresh(orden)
        return orden

    def guardar(self, db: Session, orden: OrdenCompra) -> OrdenCompra:
        db.commit()
        db.refresh(orden)
        return orden


class RecepcionRepository:
    """Igual que movimiento_inventario: una vez creada, la recepción no se
    edita ni se borra (es el respaldo de los movimientos que generó)."""

    def obtener_por_codigo(self, db: Session, codigo: str) -> Recepcion | None:
        return db.scalar(select(Recepcion).where(Recepcion.codigo == codigo))

    def obtener(self, db: Session, recepcion_id: int) -> Recepcion:
        recepcion = db.scalar(
            select(Recepcion).where(Recepcion.id == recepcion_id).options(selectinload(Recepcion.detalle))
        )
        if recepcion is None:
            raise NoEncontradoError("Recepción no encontrada")
        return recepcion

    def listar(self, db: Session, orden_compra_id: int | None = None) -> list[Recepcion]:
        consulta = select(Recepcion).options(selectinload(Recepcion.detalle)).order_by(Recepcion.id.desc())
        if orden_compra_id is not None:
            consulta = consulta.where(Recepcion.orden_compra_id == orden_compra_id)
        return list(db.scalars(consulta))

    def crear(self, db: Session, recepcion: Recepcion) -> Recepcion:
        db.add(recepcion)
        db.flush()
        return recepcion

    def total_recibido_por_variante(self, db: Session, orden_compra_id: int) -> dict[int, int]:
        """Suma de cantidad_recepcion_detalle por variante_id, entre todas
        las recepciones vinculadas a esta orden. Se usa para decidir si la
        orden pasa a 'parcial' o 'recibida'."""
        filas = db.execute(
            select(RecepcionDetalle.variante_id, RecepcionDetalle.cantidad)
            .join(Recepcion, Recepcion.id == RecepcionDetalle.recepcion_id)
            .where(Recepcion.orden_compra_id == orden_compra_id)
        ).all()
        totales: dict[int, int] = {}
        for variante_id, cantidad in filas:
            totales[variante_id] = totales.get(variante_id, 0) + cantidad
        return totales
