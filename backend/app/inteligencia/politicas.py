"""Registrar el historial de navegación no es un caso de uso del catálogo
(no tiene un actor que lo "haga" con un objetivo propio: es una traza que
queda como efecto secundario de navegar, probar o comprar). Vive acá,
como soporte para CU-32 (recomendar productos)."""

from sqlalchemy.orm import Session

from app.inteligencia.repository import HistorialNavegacionRepository
from app.inteligencia.schemas import EventoCrear
from app.seguridad.politicas import obtener_perfil_cliente

historial_repo = HistorialNavegacionRepository()


def registrar_evento(db: Session, datos: EventoCrear, usuario) -> None:
    """POST /api/v1/ia/eventos. `usuario` es `None` en navegación anónima."""
    cliente_id = obtener_perfil_cliente(db, usuario.id).id if usuario else None
    historial_repo.crear(db, cliente_id, None, datos.producto_id, datos.variante_id, datos.tipo_evento)
