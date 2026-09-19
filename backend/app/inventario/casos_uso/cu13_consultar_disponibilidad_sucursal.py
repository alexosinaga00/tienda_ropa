"""CU-13 — Consultar disponibilidad por sucursal

Actor: Cliente.
Precondición: ninguna (accesible sin sesión).
Postcondición: se conoce en qué sucursal hay disponibilidad física de una
variante.
"""

from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.inventario.models import Stock
from app.inventario.repository import StockRepository


class ConsultarDisponibilidadSucursal:
    def __init__(self) -> None:
        self._stock = StockRepository()

    def ejecutar(self, db: Session, variante_id: int, sucursal_id: int | None = None) -> list[Stock]:
        """Sin stock registrado en una sucursal no es un error, es
        simplemente 0 unidades ahí (no se levanta 404)."""
        catalogo_politicas.obtener_variante(db, variante_id)  # 404 si no existe
        stocks = self._stock.listar_por_variante(db, variante_id)
        if sucursal_id is not None:
            stocks = [s for s in stocks if s.sucursal_id == sucursal_id]
        return stocks
