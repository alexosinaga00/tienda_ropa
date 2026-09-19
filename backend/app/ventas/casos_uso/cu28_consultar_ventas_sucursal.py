"""CU-28 — Consultar ventas de la sucursal

Actor: Encargado de sucursal, Cajero.
Precondición: sesión con el permiso ventas.gestionar_sucursal; solo la
sucursal propia (salvo alcance global, ver organizacion.politicas).
Postcondición: el usuario conoce las ventas y los ingresos de su
sucursal.
"""

from sqlalchemy.orm import Session

from app.organizacion import politicas as organizacion_politicas
from app.ventas.models import Venta
from app.ventas.repository import VentaRepository


class ConsultarVentasSucursal:
    def __init__(self) -> None:
        self._ventas = VentaRepository()

    def ejecutar(self, db: Session, sucursal_id: int, usuario_id: int) -> list[Venta]:
        organizacion_politicas.obtener_sucursal(db, sucursal_id)
        organizacion_politicas.validar_acceso_sucursal(db, usuario_id, sucursal_id)
        return self._ventas.listar_por_sucursal(db, sucursal_id)
