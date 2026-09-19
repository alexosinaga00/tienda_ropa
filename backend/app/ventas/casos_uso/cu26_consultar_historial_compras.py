"""CU-26 — Consultar historial de compras

Actor: Cliente.
Precondición: el cliente tiene sesión iniciada.
Postcondición: el cliente visualiza su historial de compras y el
comprobante de la compra elegida.

Incluye ver el comprobante de una venta (antes un "extend" del catálogo,
ya no un CU aparte): es la misma consulta con más detalle.
"""

from sqlalchemy.orm import Session

from app.seguridad.politicas import obtener_perfil_cliente
from app.ventas.models import Venta
from app.ventas.politicas import obtener_comprobante
from app.ventas.repository import VentaRepository


class ConsultarHistorialCompras:
    def __init__(self) -> None:
        self._ventas = VentaRepository()

    def obtener_comprobante(self, db: Session, venta_id: int, usuario_id: int) -> Venta:
        return obtener_comprobante(db, venta_id, usuario_id)

    def listar_mis_compras(self, db: Session, usuario_id: int) -> list[Venta]:
        cliente = obtener_perfil_cliente(db, usuario_id)
        return self._ventas.listar_por_cliente(db, cliente.id)
