"""CU-18 — Cancelar reserva

Actor: Cliente (también el personal de la sucursal).
Precondición: el cliente tiene sesión y existe una reserva propia en
estado pendiente o preparada.
Postcondición: la reserva queda cancelada y las unidades vuelven a estar
disponibles para otros clientes.
"""

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictoError
from app.inventario.politicas import liberar_stock
from app.reservas.models import Reserva
from app.reservas.politicas import validar_propietario_o_staff, validar_transicion
from app.reservas.repository import EstadoReservaRepository, ReservaRepository


class CancelarReserva:
    def __init__(self) -> None:
        self._reservas = ReservaRepository()
        self._estados = EstadoReservaRepository()

    def ejecutar(self, db: Session, reserva_id: int, usuario_id: int) -> Reserva:
        reserva = self._reservas.obtener(db, reserva_id)
        validar_propietario_o_staff(db, reserva, usuario_id)

        estado_actual = self._estados.obtener(db, reserva.estado_id)
        if estado_actual.codigo not in ("pendiente", "preparada"):
            raise ConflictoError(f"No se puede cancelar una reserva en estado '{estado_actual.codigo}'")

        for linea in reserva.detalle:
            liberar_stock(db, linea.variante_id, reserva.sucursal_id, linea.cantidad, commit=False)

        return validar_transicion(db, reserva, "cancelada", usuario_id, "Cancelada", commit=True)
