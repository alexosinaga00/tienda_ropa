"""CU-07 — Gestionar catálogo maestro

Actor: Administrador.
Precondición: sesión de administrador con el permiso catalogo.gestionar.
Postcondición: categorías, tallas, colores, materiales, temporadas y
colecciones quedan disponibles para armar productos.

Caso de uso COMPUESTO: agrupa seis entidades CRUD triviales del mismo
dominio (catálogo maestro) en un solo archivo, una clase pequeña por
entidad.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import ParametrosPaginacion
from app.core.exceptions import ConflictoError, DomainError, NoEncontradoError
from app.catalogo.models import Categoria, Coleccion, Color, Material, Producto, Talla, Temporada
from app.catalogo.repository import (
    CategoriaRepository,
    ColeccionRepository,
    ColorRepository,
    MaterialRepository,
    TallaRepository,
    TemporadaRepository,
)
from app.catalogo.schemas import (
    CategoriaActualizar,
    CategoriaCrear,
    ColeccionActualizar,
    ColeccionCrear,
    ColorActualizar,
    ColorCrear,
    MaterialActualizar,
    MaterialCrear,
    TallaActualizar,
    TallaCrear,
    TemporadaActualizar,
    TemporadaCrear,
)


class GestionarCategorias:
    def __init__(self) -> None:
        self._repo = CategoriaRepository()

    def _crearia_ciclo(self, db: Session, categoria_id: int, nuevo_padre_id: int) -> bool:
        """True si engancharle `nuevo_padre_id` como padre de `categoria_id`
        crea un ciclo (incluye el caso trivial de ser su propio padre)."""
        actual: int | None = nuevo_padre_id
        visitados: set[int] = set()
        while actual is not None:
            if actual == categoria_id:
                return True
            if actual in visitados:
                break
            visitados.add(actual)
            padre = db.get(Categoria, actual)
            actual = padre.categoria_padre_id if padre else None
        return False

    def _validar_padre(self, db: Session, categoria_id: int | None, categoria_padre_id: int | None) -> None:
        if categoria_padre_id is None:
            return
        padre = db.get(Categoria, categoria_padre_id)
        if padre is None or not padre.activo:
            raise NoEncontradoError("Categoría padre no encontrada")
        if categoria_id is not None and self._crearia_ciclo(db, categoria_id, categoria_padre_id):
            raise DomainError("Una categoría no puede ser su propio padre ni crear un ciclo")

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Categoria]:
        return list(self._repo.listar(db, paginacion))

    def obtener(self, db: Session, categoria_id: int) -> Categoria:
        return self._repo.obtener(db, categoria_id)

    def crear(self, db: Session, datos: CategoriaCrear) -> Categoria:
        self._validar_padre(db, None, datos.categoria_padre_id)
        return self._repo.crear(db, datos)

    def actualizar(self, db: Session, categoria_id: int, datos: CategoriaActualizar) -> Categoria:
        if datos.categoria_padre_id is not None:
            self._validar_padre(db, categoria_id, datos.categoria_padre_id)
        return self._repo.actualizar(db, categoria_id, datos)

    def desactivar(self, db: Session, categoria_id: int) -> Categoria:
        if self._repo.listar_hijos(db, categoria_id):
            raise ConflictoError("No se puede desactivar: la categoría tiene subcategorías activas")
        tiene_productos = db.scalar(
            select(Producto).where(Producto.categoria_id == categoria_id, Producto.activo.is_(True))
        )
        if tiene_productos is not None:
            raise ConflictoError("No se puede desactivar: la categoría tiene productos activos")
        return self._repo.desactivar(db, categoria_id)


class GestionarTallas:
    """Sin columna `activo` (CRUDBaseSinActivo): se eliminan físicamente."""

    def __init__(self) -> None:
        self._repo = TallaRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Talla]:
        return list(self._repo.listar(db, paginacion))

    def obtener(self, db: Session, talla_id: int) -> Talla:
        return self._repo.obtener(db, talla_id)

    def crear(self, db: Session, datos: TallaCrear) -> Talla:
        return self._repo.crear(db, datos)

    def actualizar(self, db: Session, talla_id: int, datos: TallaActualizar) -> Talla:
        return self._repo.actualizar(db, talla_id, datos)

    def eliminar(self, db: Session, talla_id: int) -> None:
        self._repo.eliminar(db, talla_id)


class GestionarColores:
    def __init__(self) -> None:
        self._repo = ColorRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Color]:
        return list(self._repo.listar(db, paginacion))

    def obtener(self, db: Session, color_id: int) -> Color:
        return self._repo.obtener(db, color_id)

    def crear(self, db: Session, datos: ColorCrear) -> Color:
        return self._repo.crear(db, datos)

    def actualizar(self, db: Session, color_id: int, datos: ColorActualizar) -> Color:
        return self._repo.actualizar(db, color_id, datos)

    def eliminar(self, db: Session, color_id: int) -> None:
        self._repo.eliminar(db, color_id)


class GestionarMateriales:
    def __init__(self) -> None:
        self._repo = MaterialRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Material]:
        return list(self._repo.listar(db, paginacion))

    def obtener(self, db: Session, material_id: int) -> Material:
        return self._repo.obtener(db, material_id)

    def crear(self, db: Session, datos: MaterialCrear) -> Material:
        return self._repo.crear(db, datos)

    def actualizar(self, db: Session, material_id: int, datos: MaterialActualizar) -> Material:
        return self._repo.actualizar(db, material_id, datos)

    def eliminar(self, db: Session, material_id: int) -> None:
        self._repo.eliminar(db, material_id)


class GestionarTemporadas:
    def __init__(self) -> None:
        self._repo = TemporadaRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Temporada]:
        return list(self._repo.listar(db, paginacion))

    def obtener(self, db: Session, temporada_id: int) -> Temporada:
        return self._repo.obtener(db, temporada_id)

    def crear(self, db: Session, datos: TemporadaCrear) -> Temporada:
        return self._repo.crear(db, datos)

    def actualizar(self, db: Session, temporada_id: int, datos: TemporadaActualizar) -> Temporada:
        temporada = self._repo.obtener(db, temporada_id)
        inicio = datos.fecha_inicio if "fecha_inicio" in datos.model_fields_set else temporada.fecha_inicio
        fin = datos.fecha_fin if "fecha_fin" in datos.model_fields_set else temporada.fecha_fin
        if inicio and fin and fin <= inicio:
            raise DomainError("fecha_fin debe ser posterior a fecha_inicio")
        return self._repo.actualizar(db, temporada_id, datos)

    def desactivar(self, db: Session, temporada_id: int) -> Temporada:
        return self._repo.desactivar(db, temporada_id)


class GestionarColecciones:
    def __init__(self) -> None:
        self._repo = ColeccionRepository()
        self._temporadas = TemporadaRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Coleccion]:
        return list(self._repo.listar(db, paginacion))

    def obtener(self, db: Session, coleccion_id: int) -> Coleccion:
        return self._repo.obtener(db, coleccion_id)

    def crear(self, db: Session, datos: ColeccionCrear) -> Coleccion:
        if datos.temporada_id is not None:
            self._temporadas.obtener(db, datos.temporada_id)
        return self._repo.crear(db, datos)

    def actualizar(self, db: Session, coleccion_id: int, datos: ColeccionActualizar) -> Coleccion:
        if datos.temporada_id is not None:
            self._temporadas.obtener(db, datos.temporada_id)
        return self._repo.actualizar(db, coleccion_id, datos)

    def desactivar(self, db: Session, coleccion_id: int) -> Coleccion:
        return self._repo.desactivar(db, coleccion_id)
