from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.deps import ParametrosPaginacion
from app.core.exceptions import ConflictoError, NoEncontradoError

ModeloT = TypeVar("ModeloT", bound=Base)
CrearSchemaT = TypeVar("CrearSchemaT", bound=BaseModel)
ActualizarSchemaT = TypeVar("ActualizarSchemaT", bound=BaseModel)


class CRUDBase(Generic[ModeloT, CrearSchemaT, ActualizarSchemaT]):
    """CRUD genérico. Cada paquete lo hereda en su repository.py.

    Asume que el modelo tiene una columna booleana `activo` para borrado
    lógico. `listar` nunca devuelve registros con `activo = False`.
    """

    def __init__(self, modelo: type[ModeloT]) -> None:
        self.modelo = modelo

    def listar(
        self,
        db: Session,
        paginacion: ParametrosPaginacion,
        filtros: dict[str, Any] | None = None,
    ) -> list[ModeloT]:
        consulta = select(self.modelo).where(self.modelo.activo.is_(True))
        for campo, valor in (filtros or {}).items():
            columna = getattr(self.modelo, campo, None)
            if columna is not None and valor is not None:
                consulta = consulta.where(columna == valor)
        consulta = consulta.offset(paginacion.offset).limit(paginacion.tamanio)
        return list(db.scalars(consulta).all())

    def obtener(self, db: Session, id_: Any) -> ModeloT:
        instancia = db.get(self.modelo, id_)
        if instancia is None or not instancia.activo:
            raise NoEncontradoError(f"{self.modelo.__name__} no encontrado")
        return instancia

    def crear(self, db: Session, datos: CrearSchemaT) -> ModeloT:
        instancia = self.modelo(**datos.model_dump())
        db.add(instancia)
        db.commit()
        db.refresh(instancia)
        return instancia

    def actualizar(self, db: Session, id_: Any, datos: ActualizarSchemaT) -> ModeloT:
        # No usa self.obtener(): ese filtra activo=True, y bloquearía acá
        # la única vía genérica para reactivar una fila (PUT con
        # {"activo": true}) antes de que el propio cambio se aplique.
        instancia = db.get(self.modelo, id_)
        if instancia is None:
            raise NoEncontradoError(f"{self.modelo.__name__} no encontrado")
        for campo, valor in datos.model_dump(exclude_unset=True).items():
            setattr(instancia, campo, valor)
        db.commit()
        db.refresh(instancia)
        return instancia

    def desactivar(self, db: Session, id_: Any) -> ModeloT:
        instancia = self.obtener(db, id_)
        instancia.activo = False
        db.commit()
        db.refresh(instancia)
        return instancia


class CRUDBaseSinActivo(Generic[ModeloT, CrearSchemaT, ActualizarSchemaT]):
    """Variante de CRUDBase para catálogos sin columna `activo` (talla,
    color, material): no existe borrado lógico posible ahí, así que
    `eliminar` es un DELETE físico. Si la fila está referenciada por otra
    tabla (FK sin ON DELETE CASCADE), Postgres lo rechaza con
    IntegrityError; acá se convierte en un error de dominio legible en vez
    de dejar pasar el error crudo de la base.
    """

    def __init__(self, modelo: type[ModeloT]) -> None:
        self.modelo = modelo

    def listar(
        self,
        db: Session,
        paginacion: ParametrosPaginacion,
        filtros: dict[str, Any] | None = None,
    ) -> list[ModeloT]:
        consulta = select(self.modelo)
        for campo, valor in (filtros or {}).items():
            columna = getattr(self.modelo, campo, None)
            if columna is not None and valor is not None:
                consulta = consulta.where(columna == valor)
        consulta = consulta.offset(paginacion.offset).limit(paginacion.tamanio)
        return list(db.scalars(consulta).all())

    def obtener(self, db: Session, id_: Any) -> ModeloT:
        instancia = db.get(self.modelo, id_)
        if instancia is None:
            raise NoEncontradoError(f"{self.modelo.__name__} no encontrado")
        return instancia

    def crear(self, db: Session, datos: CrearSchemaT) -> ModeloT:
        instancia = self.modelo(**datos.model_dump())
        db.add(instancia)
        db.commit()
        db.refresh(instancia)
        return instancia

    def actualizar(self, db: Session, id_: Any, datos: ActualizarSchemaT) -> ModeloT:
        instancia = self.obtener(db, id_)
        for campo, valor in datos.model_dump(exclude_unset=True).items():
            setattr(instancia, campo, valor)
        db.commit()
        db.refresh(instancia)
        return instancia

    def eliminar(self, db: Session, id_: Any) -> None:
        instancia = self.obtener(db, id_)
        db.delete(instancia)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ConflictoError(f"{self.modelo.__name__} está en uso, no se puede eliminar") from exc
