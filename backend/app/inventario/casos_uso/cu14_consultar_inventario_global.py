"""CU-14 — Consultar inventario global

Actor: Administrador, Encargado de sucursal.
Precondición: sesión con el permiso inventario.ver. El encargado solo ve
su sucursal; el alcance global es del administrador (ver
organizacion.politicas.acotar_sucursal).
Postcondición: se conocen las existencias consolidadas (física, reservada,
disponible), las alertas de reposición y la valuación a costo promedio.

Caso de uso COMPUESTO: agrupa consolidado, alertas, valuación y la edición
de los límites de stock mínimo/máximo (decisión: se edita desde la misma
pantalla/CU en vez de tener un caso de uso propio).
"""

from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.core.exceptions import DomainError
from app.inventario import repository as inventario_repo
from app.inventario.models import Stock
from app.inventario.politicas import obtener_stock as _obtener_stock
from app.inventario.repository import StockRepository
from app.organizacion import politicas as organizacion_politicas


class ConsultarInventarioGlobal:
    def __init__(self) -> None:
        self._stock = StockRepository()

    # Sin sucursal_id, el administrador ve todas y el encargado la suya (la
    # misma regla para consolidado, alertas y valuación, que también usa
    # `reportes`).

    def listar_consolidado(
        self, db: Session, usuario_id: int, sucursal_id: int | None = None, producto_id: int | None = None
    ) -> list[dict]:
        sucursal_id = organizacion_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        return inventario_repo.consolidado(db, sucursal_id, producto_id)

    def listar_alertas(self, db: Session, usuario_id: int, sucursal_id: int | None = None) -> list[dict]:
        sucursal_id = organizacion_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        return inventario_repo.alertas(db, sucursal_id)

    def listar_valuacion(self, db: Session, usuario_id: int, sucursal_id: int | None = None) -> list[dict]:
        sucursal_id = organizacion_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        return inventario_repo.valuacion(db, sucursal_id)

    def listar_stock_por_sucursal(self, db: Session, usuario_id: int, sucursal_id: int) -> list[Stock]:
        organizacion_politicas.obtener_sucursal(db, sucursal_id)  # 404 si no existe
        organizacion_politicas.validar_acceso_sucursal(db, usuario_id, sucursal_id)
        return self._stock.listar_por_sucursal(db, sucursal_id)

    def listar_stock_por_variante(self, db: Session, usuario_id: int, variante_id: int) -> list[Stock]:
        catalogo_politicas.obtener_variante(db, variante_id)
        stocks = self._stock.listar_por_variante(db, variante_id)
        propia = organizacion_politicas.sucursal_asignada(db, usuario_id)
        return stocks if propia is None else [s for s in stocks if s.sucursal_id == propia]

    def obtener_stock(self, db: Session, usuario_id: int, variante_id: int, sucursal_id: int) -> Stock:
        organizacion_politicas.validar_acceso_sucursal(db, usuario_id, sucursal_id)
        return _obtener_stock(db, variante_id, sucursal_id)

    def actualizar_limites(
        self, db: Session, usuario_id: int, stock_id: int, stock_minimo: int | None, stock_maximo: int | None
    ) -> Stock:
        stock = self._stock.obtener(db, stock_id)
        organizacion_politicas.validar_acceso_sucursal(db, usuario_id, stock.sucursal_id)
        minimo_final = stock_minimo if stock_minimo is not None else stock.stock_minimo
        maximo_final = stock_maximo if stock_maximo is not None else stock.stock_maximo
        if maximo_final is not None and maximo_final < minimo_final:
            raise DomainError("stock_maximo no puede ser menor que stock_minimo")
        return self._stock.actualizar_limites(db, stock, stock_minimo, stock_maximo)
