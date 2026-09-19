"""CU-19 — Consultar reservas de la sucursal

Actor: Encargado de sucursal.
Precondición: sesión con el permiso reservas.gestionar_sucursal; solo la
sucursal propia (salvo alcance global, ver organizacion.politicas).
Postcondición: el encargado conoce las reservas pendientes, preparadas y
en prueba de su sucursal, para organizar su preparación y atención
(CU-20).
"""

from sqlalchemy.orm import Session

from app.organizacion import politicas as organizacion_politicas
from app.reservas.models import Reserva
from app.reservas.repository import ReservaRepository


class ConsultarReservasSucursal:
    def __init__(self) -> None:
        self._reservas = ReservaRepository()

    def ejecutar(self, db: Session, sucursal_id: int, usuario_id: int) -> list[Reserva]:
        organizacion_politicas.obtener_sucursal(db, sucursal_id)
        organizacion_politicas.validar_acceso_sucursal(db, usuario_id, sucursal_id)
        return self._reservas.listar_por_sucursal(db, sucursal_id)
