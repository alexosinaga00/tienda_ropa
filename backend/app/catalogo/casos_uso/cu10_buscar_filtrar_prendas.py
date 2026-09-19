"""CU-10 — Buscar y filtrar prendas

Actor: Cliente.
Precondición: ninguna (accesible sin sesión).
Postcondición: el cliente visualiza las prendas que cumplen su búsqueda.

Incluye también la búsqueda de variantes para venta que usa la caja (POS):
es la misma operación de "buscar", con otro consumidor.
"""

from sqlalchemy.orm import Session

from app.core.deps import ParametrosPaginacion
from app.catalogo.politicas import a_item_catalogo
from app.catalogo.repository import ProductoRepository, VarianteRepository
from app.catalogo.schemas import CatalogoItemRespuesta, FiltrosCatalogo


class BuscarFiltrarPrendas:
    def __init__(self) -> None:
        self._productos = ProductoRepository()
        self._variantes = VarianteRepository()

    def buscar(
        self, db: Session, paginacion: ParametrosPaginacion, filtros: FiltrosCatalogo
    ) -> list[CatalogoItemRespuesta]:
        productos = self._productos.buscar_publico(db, paginacion, filtros)
        return [a_item_catalogo(p) for p in productos]

    def buscar_para_venta(self, db: Session, texto: str):
        """Para la caja (POS): resuelve una variante por código de barras
        exacto (lector físico) o texto libre sobre sku/nombre/código de
        producto."""
        return self._variantes.buscar_para_venta(db, texto)
