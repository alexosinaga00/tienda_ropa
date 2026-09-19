"""CU-04 — Gestionar ciudades

Actor: Administrador.
Precondición: sesión de administrador con el permiso organizacion.gestionar.
Postcondición: la ciudad queda disponible para asociarle sucursales.
"""

from sqlalchemy.orm import Session

from app.core.deps import ParametrosPaginacion
from app.organizacion.models import Ciudad
from app.organizacion.repository import CiudadRepository
from app.organizacion.schemas import CiudadActualizar, CiudadCrear


class GestionarCiudades:
    def __init__(self) -> None:
        self._repo = CiudadRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Ciudad]:
        return list(self._repo.listar(db, paginacion))

    def obtener(self, db: Session, ciudad_id: int) -> Ciudad:
        return self._repo.obtener(db, ciudad_id)

    def crear(self, db: Session, datos: CiudadCrear) -> Ciudad:
        return self._repo.crear(db, datos)

    def actualizar(self, db: Session, ciudad_id: int, datos: CiudadActualizar) -> Ciudad:
        return self._repo.actualizar(db, ciudad_id, datos)

    def desactivar(self, db: Session, ciudad_id: int) -> Ciudad:
        return self._repo.desactivar(db, ciudad_id)
