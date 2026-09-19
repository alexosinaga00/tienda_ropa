"""CU-16 — Reservar varias prendas

Actor: Cliente.
Precondición: el cliente tiene sesión iniciada; las variantes existen.
Postcondición: la reserva queda registrada, el stock de cada línea queda
reservado y la sucursal recibe la notificación (paso interno, ya no es un
CU aparte).
"""

import datetime as dt
import secrets

from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.core import service as core_service
from app.core.exceptions import DomainError
from app.inventario.politicas import reservar_stock
from app.organizacion import politicas as organizacion_politicas
from app.reservas.models import Reserva, ReservaDetalle, ReservaHistorial
from app.reservas.repository import EstadoReservaRepository, ReservaRepository
from app.reservas.schemas import ReservaCrear
from app.seguridad.politicas import obtener_perfil_cliente


class ReservarPrendas:
    def __init__(self) -> None:
        self._estados = EstadoReservaRepository()
        self._reservas = ReservaRepository()

    def _generar_codigo(self, db: Session) -> str:
        for _ in range(5):
            codigo = f"RES-{secrets.token_hex(4).upper()}"
            if self._reservas.obtener_por_codigo(db, codigo) is None:
                return codigo
        raise DomainError("No se pudo generar un código único para la reserva, reintentá")

    def ejecutar(self, db: Session, usuario_id: int, datos: ReservaCrear) -> Reserva:
        cliente = obtener_perfil_cliente(db, usuario_id)
        organizacion_politicas.obtener_sucursal(db, datos.sucursal_id)  # 404 si no existe
        organizacion_politicas.validar_horario_en_atencion(
            db, datos.sucursal_id, datos.fecha_visita, datos.hora_visita_desde, datos.hora_visita_hasta
        )

        for linea in datos.detalle:
            catalogo_politicas.obtener_variante(db, linea.variante_id)  # 404 si no existe

        estado_pendiente = self._estados.obtener_por_codigo(db, "pendiente")
        fecha_hasta = dt.datetime.combine(datos.fecha_visita, datos.hora_visita_hasta, tzinfo=dt.timezone.utc)
        fecha_expiracion = fecha_hasta + dt.timedelta(hours=24)

        reserva = Reserva(
            codigo=self._generar_codigo(db),
            cliente_id=cliente.id,
            sucursal_id=datos.sucursal_id,
            estado_id=estado_pendiente.id,
            fecha_visita=datos.fecha_visita,
            hora_visita_desde=datos.hora_visita_desde,
            hora_visita_hasta=datos.hora_visita_hasta,
            fecha_expiracion=fecha_expiracion,
            observacion=datos.observacion,
        )
        reserva.detalle = [
            ReservaDetalle(variante_id=linea.variante_id, cantidad=linea.cantidad) for linea in datos.detalle
        ]
        self._reservas.crear(db, reserva)  # flush: reserva.id ya queda disponible

        # Reserva el stock de cada línea. Si una no tiene disponibilidad
        # suficiente, ninguna de las anteriores queda aplicada (commit=False:
        # toda la creación es una sola transacción).
        for linea in reserva.detalle:
            reservar_stock(db, linea.variante_id, datos.sucursal_id, linea.cantidad, commit=False)

        db.add(
            ReservaHistorial(
                reserva_id=reserva.id, estado_id=estado_pendiente.id, usuario_id=usuario_id, comentario="Reserva creada"
            )
        )

        for empleado in organizacion_politicas.listar_empleados_sucursal(db, datos.sucursal_id):
            core_service.crear_notificacion(
                db,
                empleado.usuario_id,
                titulo="Nueva reserva",
                mensaje=f"Reserva {reserva.codigo} para el {datos.fecha_visita.isoformat()}",
                tipo="reserva",
                referencia_id=reserva.id,
                commit=False,
            )

        db.commit()
        db.refresh(reserva)
        return reserva
