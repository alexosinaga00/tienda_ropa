from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crud_base import CRUDBase
from app.core.exceptions import ConflictoError, NoEncontradoError
from app.organizacion.models import Ciudad, Empleado, HorarioSucursal, Sucursal
from app.organizacion.schemas import (
    CiudadActualizar,
    CiudadCrear,
    EmpleadoActualizar,
    EmpleadoCrear,
    SucursalActualizar,
    SucursalCrear,
)


class CiudadRepository(CRUDBase[Ciudad, CiudadCrear, CiudadActualizar]):
    def __init__(self) -> None:
        super().__init__(Ciudad)

    def crear(self, db: Session, datos: CiudadCrear) -> Ciudad:
        existe = db.scalar(
            select(Ciudad).where(
                Ciudad.nombre == datos.nombre, Ciudad.departamento == datos.departamento
            )
        )
        if existe is not None:
            raise ConflictoError("Ya existe una ciudad con ese nombre y departamento")
        return super().crear(db, datos)


class SucursalRepository(CRUDBase[Sucursal, SucursalCrear, SucursalActualizar]):
    def __init__(self) -> None:
        super().__init__(Sucursal)

    def obtener_por_codigo(self, db: Session, codigo: str) -> Sucursal | None:
        return db.scalar(select(Sucursal).where(Sucursal.codigo == codigo))

    def crear(self, db: Session, datos: SucursalCrear) -> Sucursal:
        if self.obtener_por_codigo(db, datos.codigo) is not None:
            raise ConflictoError("Ya existe una sucursal con ese código")
        ciudad = db.get(Ciudad, datos.ciudad_id)
        if ciudad is None or not ciudad.activo:
            raise NoEncontradoError("Ciudad no encontrada")
        return super().crear(db, datos)


class HorarioRepository:
    """No hereda de CRUDBase: horario_sucursal no tiene columna `activo`,
    las filas se eliminan físicamente."""

    def listar_por_sucursal(self, db: Session, sucursal_id: int) -> list[HorarioSucursal]:
        return list(
            db.scalars(
                select(HorarioSucursal)
                .where(HorarioSucursal.sucursal_id == sucursal_id)
                .order_by(HorarioSucursal.dia_semana)
            )
        )

    def obtener(self, db: Session, sucursal_id: int, horario_id: int) -> HorarioSucursal:
        horario = db.scalar(
            select(HorarioSucursal).where(
                HorarioSucursal.id == horario_id, HorarioSucursal.sucursal_id == sucursal_id
            )
        )
        if horario is None:
            raise NoEncontradoError("Horario no encontrado")
        return horario

    def obtener_por_dia(self, db: Session, sucursal_id: int, dia_semana: int) -> HorarioSucursal | None:
        return db.scalar(
            select(HorarioSucursal).where(
                HorarioSucursal.sucursal_id == sucursal_id,
                HorarioSucursal.dia_semana == dia_semana,
            )
        )

    def crear(self, db: Session, sucursal_id: int, horario: HorarioSucursal) -> HorarioSucursal:
        db.add(horario)
        db.commit()
        db.refresh(horario)
        return horario

    def actualizar(self, db: Session, horario: HorarioSucursal, hora_apertura, hora_cierre) -> HorarioSucursal:
        if hora_apertura is not None:
            horario.hora_apertura = hora_apertura
        if hora_cierre is not None:
            horario.hora_cierre = hora_cierre
        db.commit()
        db.refresh(horario)
        return horario

    def eliminar(self, db: Session, horario: HorarioSucursal) -> None:
        db.delete(horario)
        db.commit()


class EmpleadoRepository(CRUDBase[Empleado, EmpleadoCrear, EmpleadoActualizar]):
    def __init__(self) -> None:
        super().__init__(Empleado)

    def obtener_por_usuario(self, db: Session, usuario_id: int) -> Empleado | None:
        return db.scalar(select(Empleado).where(Empleado.usuario_id == usuario_id))

    def reactivar(self, db: Session, empleado: Empleado, datos: EmpleadoCrear) -> Empleado:
        """Reusa la fila de un empleado dado de baja en vez de dejar un
        duplicado: `obtener_por_usuario` no filtra por `activo`, así que un
        usuario solo puede tener una fila de empleado en toda su historia."""
        empleado.activo = True
        empleado.sucursal_id = datos.sucursal_id
        empleado.cargo = datos.cargo
        empleado.ci = datos.ci
        empleado.fecha_ingreso = datos.fecha_ingreso
        db.commit()
        db.refresh(empleado)
        return empleado

    def listar_por_sucursal(self, db: Session, sucursal_id: int) -> list[Empleado]:
        return list(
            db.scalars(
                select(Empleado).where(
                    Empleado.sucursal_id == sucursal_id, Empleado.activo.is_(True)
                )
            )
        )
