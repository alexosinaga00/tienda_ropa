"""CU-41 — Gestionar zonas de envío

Actor: Administrador.
Precondición: sesión de administrador con el permiso entregas.gestionar.
Postcondición: la zona (y sus reglas de recargo por peso) queda
disponible para cotizar y crear envíos (CU-42).
"""

from sqlalchemy.orm import Session

from app.core.deps import ParametrosPaginacion
from app.entregas.models import ZonaEnvio
from app.entregas.repository import ZonaEnvioRepository
from app.entregas.schemas import ZonaEnvioActualizar, ZonaEnvioCrear


class GestionarZonasTarifas:
    def __init__(self) -> None:
        self._zonas = ZonaEnvioRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[ZonaEnvio]:
        return list(self._zonas.listar(db, paginacion))

    def obtener(self, db: Session, zona_id: int) -> ZonaEnvio:
        return self._zonas.obtener(db, zona_id)

    def crear(self, db: Session, datos: ZonaEnvioCrear) -> ZonaEnvio:
        return self._zonas.crear(db, datos)

    def actualizar(self, db: Session, zona_id: int, datos: ZonaEnvioActualizar) -> ZonaEnvio:
        return self._zonas.actualizar(db, zona_id, datos)

    def desactivar(self, db: Session, zona_id: int) -> ZonaEnvio:
        return self._zonas.desactivar(db, zona_id)
