"""CU-05 — Gestionar sucursales

Actor: Administrador.
Precondición: sesión de administrador con el permiso organizacion.gestionar.
Postcondición: la sucursal y sus horarios de atención quedan registrados.

Caso de uso COMPUESTO: agrupa la sucursal física y sus horarios de
atención (antes eran dos CU separados en el plan de 79; el catálogo de 43
los funde en uno).
"""

from sqlalchemy.orm import Session

from app.core.deps import ParametrosPaginacion
from app.core.exceptions import ConflictoError
from app.organizacion.models import HorarioSucursal, Sucursal
from app.organizacion.repository import HorarioRepository, SucursalRepository
from app.organizacion.schemas import HorarioActualizar, HorarioCrear, SucursalActualizar, SucursalCrear


class GestionarSucursales:
    def __init__(self) -> None:
        self._sucursales = SucursalRepository()
        self._horarios = HorarioRepository()

    # -- Sucursal ---------------------------------------------------------

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Sucursal]:
        return list(self._sucursales.listar(db, paginacion))

    def obtener(self, db: Session, sucursal_id: int) -> Sucursal:
        return self._sucursales.obtener(db, sucursal_id)

    def crear(self, db: Session, datos: SucursalCrear) -> Sucursal:
        return self._sucursales.crear(db, datos)

    def actualizar(self, db: Session, sucursal_id: int, datos: SucursalActualizar) -> Sucursal:
        return self._sucursales.actualizar(db, sucursal_id, datos)

    def desactivar(self, db: Session, sucursal_id: int) -> Sucursal:
        return self._sucursales.desactivar(db, sucursal_id)

    # -- Horarios de atención ----------------------------------------------

    def listar_horarios(self, db: Session, sucursal_id: int) -> list[HorarioSucursal]:
        self._sucursales.obtener(db, sucursal_id)  # 404 si no existe / está inactiva
        return list(self._horarios.listar_por_sucursal(db, sucursal_id))

    def crear_horario(self, db: Session, sucursal_id: int, datos: HorarioCrear) -> HorarioSucursal:
        self._sucursales.obtener(db, sucursal_id)  # 404 si no existe / está inactiva

        if self._horarios.obtener_por_dia(db, sucursal_id, datos.dia_semana) is not None:
            raise ConflictoError("Ya existe un horario para ese día en esta sucursal")

        horario = HorarioSucursal(
            sucursal_id=sucursal_id,
            dia_semana=datos.dia_semana,
            hora_apertura=datos.hora_apertura,
            hora_cierre=datos.hora_cierre,
        )
        return self._horarios.crear(db, sucursal_id, horario)

    def actualizar_horario(
        self, db: Session, sucursal_id: int, horario_id: int, datos: HorarioActualizar
    ) -> HorarioSucursal:
        horario = self._horarios.obtener(db, sucursal_id, horario_id)
        return self._horarios.actualizar(db, horario, datos.hora_apertura, datos.hora_cierre)

    def eliminar_horario(self, db: Session, sucursal_id: int, horario_id: int) -> None:
        horario = self._horarios.obtener(db, sucursal_id, horario_id)
        self._horarios.eliminar(db, horario)
