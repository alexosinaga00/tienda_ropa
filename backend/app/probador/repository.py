import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NoEncontradoError
from app.probador.models import ActivoProbador, ProbadorGeneracion, SesionProbador


class ActivoRepository:
    """No hereda de CRUDBase: activo_probador no tiene borrado lógico (no
    hay endpoint de borrado en el enunciado; un asset rechazado se
    conserva como historial y se puede subir otro para la misma
    variante+tipo, gracias al índice único parcial `WHERE estado <> 'rechazado'`)."""

    def listar_por_variante(self, db: Session, variante_id: int) -> list[ActivoProbador]:
        return list(
            db.scalars(
                select(ActivoProbador)
                .where(ActivoProbador.variante_id == variante_id)
                .order_by(ActivoProbador.creado_en.desc())
            )
        )

    def obtener(self, db: Session, activo_id: int) -> ActivoProbador:
        activo = db.get(ActivoProbador, activo_id)
        if activo is None:
            raise NoEncontradoError("Asset de probador no encontrado")
        return activo

    def crear(
        self,
        db: Session,
        variante_id: int,
        tipo: str,
        public_id: str,
        ancho_px: int,
        alto_px: int,
        creado_por: int | None,
    ) -> ActivoProbador:
        activo = ActivoProbador(
            variante_id=variante_id,
            tipo=tipo,
            url=public_id,
            ancho_px=ancho_px,
            alto_px=alto_px,
            estado="pendiente",
            creado_por=creado_por,
        )
        db.add(activo)
        db.commit()
        db.refresh(activo)
        return activo

    def guardar_anclajes(self, db: Session, activo: ActivoProbador, anclajes: dict) -> ActivoProbador:
        activo.anclajes = anclajes
        db.commit()
        db.refresh(activo)
        return activo

    def marcar_validado(self, db: Session, activo: ActivoProbador) -> ActivoProbador:
        activo.estado = "validado"
        db.commit()
        db.refresh(activo)
        return activo


class GeneracionRepository:
    """No hereda de CRUDBase: probador_generacion no tiene borrado lógico
    (es un caché de resultados, no un catálogo administrable)."""

    def buscar_completado(self, db: Session, hash_foto: str, variante_id: int) -> ProbadorGeneracion | None:
        return db.scalar(
            select(ProbadorGeneracion).where(
                ProbadorGeneracion.hash_foto == hash_foto,
                ProbadorGeneracion.variante_id == variante_id,
                ProbadorGeneracion.estado == "completado",
            )
        )

    def contar_desde(self, db: Session, cliente_id: int, desde: dt.datetime) -> int:
        return db.scalar(
            select(func.count())
            .select_from(ProbadorGeneracion)
            .where(
                ProbadorGeneracion.cliente_id == cliente_id,
                ProbadorGeneracion.creado_en >= desde,
                # Un intento fallido (proveedor caído, timeout) no gasta cupo.
                ProbadorGeneracion.estado != "fallido",
            )
        )

    def obtener(self, db: Session, generacion_id: int) -> ProbadorGeneracion:
        generacion = db.get(ProbadorGeneracion, generacion_id)
        if generacion is None:
            raise NoEncontradoError("Generación no encontrada")
        return generacion

    def crear(self, db: Session, cliente_id: int, variante_id: int, hash_foto: str) -> ProbadorGeneracion:
        generacion = ProbadorGeneracion(
            cliente_id=cliente_id, variante_id=variante_id, hash_foto=hash_foto, estado="en_proceso"
        )
        db.add(generacion)
        db.commit()
        db.refresh(generacion)
        return generacion

    def marcar_completado(
        self, db: Session, generacion_id: int, url_resultado: str, proveedor: str
    ) -> ProbadorGeneracion:
        generacion = self.obtener(db, generacion_id)
        generacion.estado = "completado"
        generacion.url_resultado = url_resultado
        generacion.proveedor = proveedor
        db.commit()
        db.refresh(generacion)
        return generacion

    def marcar_fallido(self, db: Session, generacion_id: int, mensaje_error: str) -> ProbadorGeneracion:
        generacion = self.obtener(db, generacion_id)
        generacion.estado = "fallido"
        generacion.mensaje_error = mensaje_error[:300]
        db.commit()
        db.refresh(generacion)
        return generacion


class SesionRepository:
    """No hereda de CRUDBase: sesion_probador es una métrica de uso que se
    inserta una sola vez, nunca se edita ni se borra lógicamente."""

    def crear(
        self, db: Session, cliente_id: int | None, variante_id: int, modo: str, duracion_seg: int | None
    ) -> SesionProbador:
        sesion = SesionProbador(cliente_id=cliente_id, variante_id=variante_id, modo=modo, duracion_seg=duracion_seg)
        db.add(sesion)
        db.commit()
        db.refresh(sesion)
        return sesion

    def listar_reciente_por_cliente(self, db: Session, cliente_id: int, limite: int) -> list[SesionProbador]:
        consulta = (
            select(SesionProbador)
            .where(SesionProbador.cliente_id == cliente_id)
            .order_by(SesionProbador.creado_en.desc())
            .limit(limite)
        )
        return list(db.scalars(consulta))

    def contar_por_periodo(self, db: Session, desde: dt.date, hasta: dt.date) -> list[dict]:
        """Para `reportes` (P6.3): sesiones por modo en el período.
        `sesion_probador` no tiene `sucursal_id` -- sin filtro posible por
        sucursal, es una limitación real del esquema, no un descuido."""
        hasta_exclusiva = hasta + dt.timedelta(days=1)
        consulta = (
            select(SesionProbador.modo, func.count(SesionProbador.id).label("cantidad"))
            .where(SesionProbador.creado_en >= desde, SesionProbador.creado_en < hasta_exclusiva)
            .group_by(SesionProbador.modo)
            .order_by(SesionProbador.modo)
        )
        return [dict(fila) for fila in db.execute(consulta).mappings().all()]
