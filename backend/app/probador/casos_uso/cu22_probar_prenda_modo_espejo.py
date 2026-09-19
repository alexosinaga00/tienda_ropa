"""CU-22 — Probar prenda en modo espejo

Actor: Cliente.
Precondición: sesión de cliente; la variante existe y tiene un overlay
validado.
Postcondición: el cliente ve la prenda superpuesta en tiempo real
(renderizado en Flutter); el backend solo entrega el asset validado con
sus anclajes y registra la sesión de uso.
"""

from sqlalchemy.orm import Session

from app.core import storage
from app.core.exceptions import DomainError
from app.catalogo import politicas as catalogo_politicas
from app.probador.models import ActivoProbador, SesionProbador
from app.probador.repository import ActivoRepository, SesionRepository
from app.probador.schemas import SesionCrear
from app.seguridad.politicas import obtener_perfil_cliente


class ProbarPrendaModoEspejo:
    def __init__(self) -> None:
        self._activos = ActivoRepository()
        self._sesiones = SesionRepository()

    def obtener_assets(
        self, db: Session, variante_id: int
    ) -> tuple[ActivoProbador, str, ActivoProbador | None, str | None]:
        """GET /probador/variante/{id}/assets: el overlay validado
        (obligatorio para el modo espejo, y también la referencia visual
        que usa el modo generativo) y el flat-lay validado, si algún admin
        lo subió."""
        catalogo_politicas.obtener_variante(db, variante_id)  # 404 si no existe
        activos = self._activos.listar_por_variante(db, variante_id)
        overlay = next((a for a in activos if a.tipo == "overlay_2d" and a.estado == "validado"), None)
        if overlay is None:
            raise DomainError("Esta prenda todavía no tiene un overlay validado para el probador", status_code=404)
        flatlay = next((a for a in activos if a.tipo == "flatlay_ia" and a.estado == "validado"), None)
        overlay_url = storage.url_probador(overlay.url)
        flatlay_url = storage.url_probador(flatlay.url) if flatlay else None
        return overlay, overlay_url, flatlay, flatlay_url

    def registrar_sesion(self, db: Session, usuario_id: int, datos: SesionCrear) -> SesionProbador:
        cliente = obtener_perfil_cliente(db, usuario_id)
        catalogo_politicas.obtener_variante(db, datos.variante_id)  # 404 si no existe
        return self._sesiones.crear(db, cliente.id, datos.variante_id, datos.modo, datos.duracion_seg)
