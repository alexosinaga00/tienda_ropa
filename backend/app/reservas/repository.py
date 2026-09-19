import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import NoEncontradoError
from app.reservas.models import EstadoReserva, Reserva


class EstadoReservaRepository:
    def obtener_por_codigo(self, db: Session, codigo: str) -> EstadoReserva:
        estado = db.scalar(select(EstadoReserva).where(EstadoReserva.codigo == codigo))
        if estado is None:
            raise NoEncontradoError(f"Estado de reserva '{codigo}' no encontrado")
        return estado

    def obtener(self, db: Session, estado_id: int) -> EstadoReserva:
        estado = db.get(EstadoReserva, estado_id)
        if estado is None:
            raise NoEncontradoError("Estado de reserva no encontrado")
        return estado

    def mapa_codigos_por_id(self, db: Session) -> dict[int, str]:
        return {estado.id: estado.codigo for estado in db.scalars(select(EstadoReserva))}


class ReservaRepository:
    """No hereda de CRUDBase: `reserva` no tiene columna `activo`, su ciclo
    de vida es la máquina de estados de reservas.politicas, y crear() maneja
    detalle + historial como parte de la misma operación."""

    def _consulta_base(self):
        return select(Reserva).options(selectinload(Reserva.detalle), selectinload(Reserva.historial))

    def obtener_por_codigo(self, db: Session, codigo: str) -> Reserva | None:
        return db.scalar(self._consulta_base().where(Reserva.codigo == codigo))

    def obtener(self, db: Session, reserva_id: int) -> Reserva:
        reserva = db.scalar(self._consulta_base().where(Reserva.id == reserva_id))
        if reserva is None:
            raise NoEncontradoError("Reserva no encontrada")
        return reserva

    def obtener_bloqueado(self, db: Session, reserva_id: int) -> Reserva:
        """Igual que obtener(), pero con SELECT FOR UPDATE (Postgres) y
        populate_existing=True: serializa las operaciones que leen el estado
        de la reserva y después mueven stock (facturarla, expirarla). Mismo
        patrón que ventas.repository.VentaRepository.obtener_bloqueado."""
        consulta = self._consulta_base().where(Reserva.id == reserva_id)
        if db.get_bind().dialect.name == "postgresql":
            consulta = consulta.with_for_update()
        reserva = db.scalars(consulta.execution_options(populate_existing=True)).one_or_none()
        if reserva is None:
            raise NoEncontradoError("Reserva no encontrada")
        return reserva

    def listar_por_cliente(self, db: Session, cliente_id: int) -> list[Reserva]:
        return list(
            db.scalars(
                self._consulta_base().where(Reserva.cliente_id == cliente_id).order_by(Reserva.creado_en.desc())
            )
        )

    def listar_por_sucursal(self, db: Session, sucursal_id: int) -> list[Reserva]:
        return list(
            db.scalars(
                self._consulta_base().where(Reserva.sucursal_id == sucursal_id).order_by(Reserva.creado_en.desc())
            )
        )

    def listar_vencidas(self, db: Session, ahora: dt.datetime, estados_ids: list[int]) -> list[Reserva]:
        return list(
            db.scalars(
                self._consulta_base().where(
                    Reserva.fecha_expiracion < ahora,
                    Reserva.estado_id.in_(estados_ids),
                )
            )
        )

    def crear(self, db: Session, reserva: Reserva) -> Reserva:
        db.add(reserva)
        db.flush()
        return reserva

    def contar_por_estado(
        self, db: Session, desde: dt.date, hasta: dt.date, sucursal_id: int | None = None
    ) -> list[dict]:
        """Para `reportes` (P6.3): cantidad de reservas por estado en el
        período, filtradas por `fecha_visita`."""
        condiciones = [Reserva.fecha_visita >= desde, Reserva.fecha_visita <= hasta]
        if sucursal_id is not None:
            condiciones.append(Reserva.sucursal_id == sucursal_id)
        consulta = (
            select(EstadoReserva.codigo, EstadoReserva.nombre, func.count(Reserva.id).label("cantidad"))
            .join(Reserva, Reserva.estado_id == EstadoReserva.id)
            .where(*condiciones)
            .group_by(EstadoReserva.codigo, EstadoReserva.nombre)
            .order_by(EstadoReserva.codigo)
        )
        return [dict(fila) for fila in db.execute(consulta).mappings().all()]
