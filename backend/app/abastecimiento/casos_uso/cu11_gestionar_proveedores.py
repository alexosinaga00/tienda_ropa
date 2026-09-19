"""CU-11 — Gestionar proveedores

Actor: Administrador (Proveedor como actor pasivo).
Precondición: sesión con el permiso abastecimiento.gestionar; los
productos a asociar existen (CU-08).
Postcondición: el proveedor queda activo con sus productos asociados,
disponible para registrar recepciones de mercadería (CU-12).

Caso de uso COMPUESTO: agrupa el proveedor y los productos que abastece
cada uno en una sola clase.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.abastecimiento.models import ProductoProveedor, Proveedor
from app.abastecimiento.repository import ProductoProveedorRepository, ProveedorRepository
from app.abastecimiento.schemas import ProveedorActualizar, ProveedorCrear
from app.catalogo import politicas as catalogo_politicas
from app.core.deps import ParametrosPaginacion


class GestionarProveedores:
    def __init__(self) -> None:
        self._proveedores = ProveedorRepository()
        self._productos_proveedor = ProductoProveedorRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Proveedor]:
        return list(self._proveedores.listar(db, paginacion))

    def obtener(self, db: Session, proveedor_id: int) -> Proveedor:
        return self._proveedores.obtener(db, proveedor_id)

    def crear(self, db: Session, datos: ProveedorCrear) -> Proveedor:
        return self._proveedores.crear(db, datos)

    def actualizar(self, db: Session, proveedor_id: int, datos: ProveedorActualizar) -> Proveedor:
        return self._proveedores.actualizar(db, proveedor_id, datos)

    def desactivar(self, db: Session, proveedor_id: int) -> Proveedor:
        return self._proveedores.desactivar(db, proveedor_id)

    def listar_productos(self, db: Session, proveedor_id: int) -> list[ProductoProveedor]:
        self._proveedores.obtener(db, proveedor_id)  # 404 si no existe / está inactivo
        return list(self._productos_proveedor.listar_por_proveedor(db, proveedor_id))

    def agregar_producto(
        self,
        db: Session,
        proveedor_id: int,
        producto_id: int,
        costo_referencial: Decimal | None,
        dias_entrega: int | None,
    ) -> ProductoProveedor:
        self._proveedores.obtener(db, proveedor_id)  # 404 si no existe / está inactivo
        catalogo_politicas.obtener_producto(db, producto_id)  # 404 si no existe
        return self._productos_proveedor.crear(db, proveedor_id, producto_id, costo_referencial, dias_entrega)

    def quitar_producto(self, db: Session, proveedor_id: int, producto_id: int) -> None:
        self._productos_proveedor.eliminar(db, proveedor_id, producto_id)
