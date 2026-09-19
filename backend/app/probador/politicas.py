"""Funciones que probador expone para otros paquetes, sin ser casos de uso
del catálogo: son consultas sobre las tablas de este paquete (sesión y
generación), para que nadie más tenga que tocarlas directamente."""

from sqlalchemy.orm import Session

from app.core.deps import ParametrosPeriodo
from app.probador.models import SesionProbador
from app.probador.repository import SesionRepository

sesion_repo = SesionRepository()


def listar_sesiones_recientes_cliente(db: Session, cliente_id: int, limite: int = 50) -> list[SesionProbador]:
    """Para `inteligencia` (capa de reglas del recomendador): usos recientes
    del probador de un cliente, sin consultar `sesion_probador`
    directamente."""
    return sesion_repo.listar_reciente_por_cliente(db, cliente_id, limite)


def reporte_uso_probador(db: Session, periodo: ParametrosPeriodo) -> list[dict]:
    """Para `reportes`: sesiones del probador por modo en el período."""
    return sesion_repo.contar_por_periodo(db, periodo.desde, periodo.hasta)
