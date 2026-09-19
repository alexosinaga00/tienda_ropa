"""CU-27 — Gestionar promociones

Actor: Administrador.
Precondición: sesión de administrador con el permiso ventas.gestionar.
Postcondición: la promoción queda registrada y se aplica automáticamente
a las prendas de su alcance durante su vigencia.
"""

from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.core.deps import ParametrosPaginacion
from app.core.exceptions import DomainError
from app.ventas.models import Promocion, PromocionAlcance
from app.ventas.repository import PromocionRepository
from app.ventas.schemas import PromocionActualizar, PromocionAlcanceCrear, PromocionCrear


class GestionarPromociones:
    def __init__(self) -> None:
        self._promociones = PromocionRepository()

    def _validar_alcance(self, alcance: PromocionAlcanceCrear) -> None:
        # El schema (PromocionAlcanceCrear) ya valida esto con
        # @model_validator, pero se revalida acá porque este caso de uso
        # es quien realmente decide las reglas de negocio, no el schema.
        cantidad = sum(x is not None for x in (alcance.producto_id, alcance.categoria_id, alcance.temporada_id))
        if cantidad != 1:
            raise DomainError("Cada alcance necesita exactamente uno de producto_id, categoria_id o temporada_id")

    def crear(self, db: Session, datos: PromocionCrear) -> Promocion:
        for alcance in datos.alcances:
            self._validar_alcance(alcance)
            if alcance.producto_id is not None:
                catalogo_politicas.obtener_producto(db, alcance.producto_id)  # 404 si no existe

        promocion = Promocion(
            nombre=datos.nombre,
            tipo=datos.tipo,
            valor=datos.valor,
            fecha_inicio=datos.fecha_inicio,
            fecha_fin=datos.fecha_fin,
        )
        promocion.alcances = [
            PromocionAlcance(
                producto_id=alcance.producto_id, categoria_id=alcance.categoria_id, temporada_id=alcance.temporada_id
            )
            for alcance in datos.alcances
        ]
        self._promociones.crear(db, promocion)  # flush
        db.commit()
        db.refresh(promocion)
        return promocion

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Promocion]:
        return self._promociones.listar(db, paginacion)

    def obtener(self, db: Session, promocion_id: int) -> Promocion:
        return self._promociones.obtener(db, promocion_id)

    def actualizar(self, db: Session, promocion_id: int, datos: PromocionActualizar) -> Promocion:
        promocion = self._promociones.obtener(db, promocion_id)
        for campo, valor in datos.model_dump(exclude_unset=True).items():
            setattr(promocion, campo, valor)
        if promocion.fecha_fin < promocion.fecha_inicio:
            raise DomainError("fecha_fin no puede ser anterior a fecha_inicio")
        db.commit()
        db.refresh(promocion)
        return promocion

    def desactivar(self, db: Session, promocion_id: int) -> Promocion:
        promocion = self._promociones.obtener(db, promocion_id)
        promocion.activo = False
        db.commit()
        db.refresh(promocion)
        return promocion
