from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.crud_base import CRUDBase
from app.core.deps import ParametrosPaginacion
from app.core.exceptions import NoEncontradoError
from app.entregas.models import DireccionCliente, Envio, ReglaTarifaEnvio, ZonaEnvio
from app.entregas.schemas import (
    DireccionClienteActualizar,
    DireccionClienteCrear,
    ZonaEnvioActualizar,
    ZonaEnvioCrear,
)


class ZonaEnvioRepository(CRUDBase[ZonaEnvio, ZonaEnvioCrear, ZonaEnvioActualizar]):
    def __init__(self) -> None:
        super().__init__(ZonaEnvio)

    def listar_reglas(self, db: Session, zona_envio_id: int) -> list[ReglaTarifaEnvio]:
        return list(
            db.scalars(
                select(ReglaTarifaEnvio)
                .where(ReglaTarifaEnvio.zona_envio_id == zona_envio_id)
                .order_by(ReglaTarifaEnvio.peso_desde_kg)
            )
        )


class DireccionClienteRepository(CRUDBase[DireccionCliente, DireccionClienteCrear, DireccionClienteActualizar]):
    def __init__(self) -> None:
        super().__init__(DireccionCliente)

    def listar_por_cliente(self, db: Session, cliente_id: int) -> list[DireccionCliente]:
        return list(
            db.scalars(
                select(DireccionCliente).where(
                    DireccionCliente.cliente_id == cliente_id, DireccionCliente.activo.is_(True)
                )
            )
        )

    # Override deliberado: `cliente_id` no viene del schema (se resuelve
    # del usuario autenticado en el service), así que no se puede armar la
    # instancia solo con `datos.model_dump()` como hace CRUDBase.crear.
    def crear(self, db: Session, cliente_id: int, datos: DireccionClienteCrear) -> DireccionCliente:
        instancia = DireccionCliente(cliente_id=cliente_id, **datos.model_dump())
        db.add(instancia)
        db.commit()
        db.refresh(instancia)
        return instancia


class EnvioRepository:
    def obtener(self, db: Session, envio_id: int) -> Envio:
        envio = db.get(Envio, envio_id)
        if envio is None:
            raise NoEncontradoError("Envío no encontrado")
        return envio

    def obtener_bloqueado(self, db: Session, envio_id: int) -> Envio:
        """Con la fila bloqueada: dos actualizaciones de estado simultáneas
        del mismo envío se serializan en vez de pisarse."""
        envio = db.scalar(select(Envio).where(Envio.id == envio_id).with_for_update())
        if envio is None:
            raise NoEncontradoError("Envío no encontrado")
        return envio

    def listar(
        self,
        db: Session,
        paginacion: ParametrosPaginacion,
        *,
        estado: str | None = None,
        ventas_de_sucursal: Select[tuple[int]] | None = None,
    ) -> list[Envio]:
        consulta = select(Envio)
        if estado is not None:
            consulta = consulta.where(Envio.estado == estado)
        if ventas_de_sucursal is not None:
            consulta = consulta.where(Envio.venta_id.in_(ventas_de_sucursal))
        consulta = consulta.order_by(Envio.id.desc()).offset(paginacion.offset).limit(paginacion.tamanio)
        return list(db.scalars(consulta))

    def obtener_por_venta(self, db: Session, venta_id: int) -> Envio | None:
        return db.scalar(select(Envio).where(Envio.venta_id == venta_id))

    def crear(self, db: Session, envio: Envio) -> Envio:
        db.add(envio)
        db.commit()
        db.refresh(envio)
        return envio
