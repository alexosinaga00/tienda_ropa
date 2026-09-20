from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NoEncontradoError
from app.core.models import Notificacion


class NotificacionRepository:
    """Sin `activo`: una notificación no se desactiva, se marca leída o
    simplemente se acumula."""

    def crear(
        self,
        db: Session,
        usuario_id: int,
        titulo: str,
        mensaje: str | None,
        tipo: str | None,
        referencia_id: int | None,
    ) -> Notificacion:
        notificacion = Notificacion(
            usuario_id=usuario_id, titulo=titulo, mensaje=mensaje, tipo=tipo, referencia_id=referencia_id
        )
        db.add(notificacion)
        db.flush()
        return notificacion

    def listar_por_usuario(self, db: Session, usuario_id: int) -> list[Notificacion]:
        return list(
            db.scalars(
                select(Notificacion)
                .where(Notificacion.usuario_id == usuario_id)
                # `id` desempata: dos avisos creados en el mismo instante (la misma transacción)
                # comparten `creado_en` y sin esto su orden sería indeterminado.
                .order_by(Notificacion.creado_en.desc(), Notificacion.id.desc())
            )
        )

    def marcar_leida(self, db: Session, usuario_id: int, notificacion_id: int) -> Notificacion:
        notificacion = db.get(Notificacion, notificacion_id)
        if notificacion is None or notificacion.usuario_id != usuario_id:
            raise NoEncontradoError("Notificación no encontrada")
        notificacion.leida = True
        db.commit()
        db.refresh(notificacion)
        return notificacion
