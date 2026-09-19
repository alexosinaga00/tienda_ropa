"""CU-36 — Gestionar favoritos

Actor: Cliente.
Precondición: el cliente tiene sesión iniciada.
Postcondición: la prenda queda guardada (o quitada) de los favoritos del
cliente.
"""

from sqlalchemy.orm import Session

from app.catalogo.repository import FavoritoRepository, VarianteRepository
from app.catalogo.schemas import FavoritoRespuesta
from app.seguridad.politicas import obtener_perfil_cliente


class GestionarFavoritos:
    def __init__(self) -> None:
        self._favoritos = FavoritoRepository()
        self._variantes = VarianteRepository()

    def listar(self, db: Session, usuario_id: int) -> list[FavoritoRespuesta]:
        cliente = obtener_perfil_cliente(db, usuario_id)
        favoritos = self._favoritos.listar_por_cliente(db, cliente.id)
        return [FavoritoRespuesta.from_modelo(f) for f in favoritos]

    def agregar(self, db: Session, usuario_id: int, variante_id: int) -> FavoritoRespuesta:
        cliente = obtener_perfil_cliente(db, usuario_id)
        self._variantes.obtener(db, variante_id)  # 404 si no existe o está inactiva
        favorito = self._favoritos.agregar(db, cliente.id, variante_id)
        return FavoritoRespuesta.from_modelo(favorito)

    def quitar(self, db: Session, usuario_id: int, variante_id: int) -> None:
        cliente = obtener_perfil_cliente(db, usuario_id)
        self._favoritos.quitar(db, cliente.id, variante_id)
