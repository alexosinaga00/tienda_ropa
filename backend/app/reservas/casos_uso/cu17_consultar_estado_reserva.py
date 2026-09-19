"""CU-17 — Consultar estado de reserva

Actor: Cliente.
Precondición: el cliente tiene sesión iniciada.
Postcondición: el cliente conoce el estado de su reserva y el detalle de
las prendas reservadas.
"""

from sqlalchemy.orm import Session

from app.reservas.models import Reserva
from app.reservas.politicas import validar_propietario_o_staff
from app.reservas.repository import ReservaRepository
from app.seguridad.politicas import obtener_perfil_cliente


class ConsultarEstadoReserva:
    def __init__(self) -> None:
        self._reservas = ReservaRepository()

    def obtener(self, db: Session, reserva_id: int, usuario_id: int) -> Reserva:
        reserva = self._reservas.obtener(db, reserva_id)
        validar_propietario_o_staff(db, reserva, usuario_id)
        return reserva

    def listar_mias(self, db: Session, usuario_id: int) -> list[Reserva]:
        cliente = obtener_perfil_cliente(db, usuario_id)
        return self._reservas.listar_por_cliente(db, cliente.id)
