"""CU-20 — Atender prueba de reserva en sucursal

Actor: Encargado de sucursal.
Precondición: la reserva existe y está en el estado que corresponde a
cada paso.
Postcondición: la reserva avanza por su ciclo de atención (preparada →
en_prueba → completada), liberando el stock de lo que el cliente no se
llevó.

Caso de uso COMPUESTO: agrupa preparar las prendas, confirmar la llegada
del cliente y registrar la selección final (antes eran tres CU separados
en el plan de 79; el catálogo de 43 los funde en el ciclo completo de
atención).
"""

from sqlalchemy.orm import Session

from app.core import service as core_service
from app.core.exceptions import ConflictoError, NoEncontradoError
from app.inventario.politicas import liberar_stock
from app.organizacion import politicas as organizacion_politicas
from app.reservas.models import Reserva
from app.reservas.politicas import validar_transicion
from app.reservas.repository import EstadoReservaRepository, ReservaRepository
from app.reservas.schemas import SeleccionActualizar
from app.seguridad.politicas import obtener_cliente


class AtenderPruebaReservaSucursal:
    def __init__(self) -> None:
        self._reservas = ReservaRepository()
        self._estados = EstadoReservaRepository()

    def _obtener_de_mi_sucursal(self, db: Session, reserva_id: int, usuario_id: int) -> Reserva:
        reserva = self._reservas.obtener(db, reserva_id)
        organizacion_politicas.validar_acceso_sucursal(db, usuario_id, reserva.sucursal_id)
        return reserva

    def preparar(self, db: Session, reserva_id: int, usuario_id: int) -> Reserva:
        reserva = self._obtener_de_mi_sucursal(db, reserva_id, usuario_id)
        validar_transicion(db, reserva, "preparada", usuario_id, "Prendas preparadas", commit=False)
        for linea in reserva.detalle:
            linea.preparada = True

        cliente = obtener_cliente(db, reserva.cliente_id)
        core_service.crear_notificacion(
            db,
            cliente.usuario_id,
            titulo="Tu reserva está lista",
            mensaje=f"La reserva {reserva.codigo} ya tiene las prendas preparadas, te esperamos.",
            tipo="reserva_preparada",
            referencia_id=reserva.id,
            commit=False,
        )

        db.commit()
        db.refresh(reserva)
        return reserva

    def confirmar_llegada(self, db: Session, reserva_id: int, usuario_id: int) -> Reserva:
        reserva = self._obtener_de_mi_sucursal(db, reserva_id, usuario_id)
        return validar_transicion(db, reserva, "en_prueba", usuario_id, "Cliente llegó a la sucursal")

    def registrar_seleccion(
        self, db: Session, reserva_id: int, usuario_id: int, datos: SeleccionActualizar
    ) -> Reserva:
        """El enunciado no dice qué pasa si en una misma llamada solo se
        decide parte de las líneas. Acá una línea ya decidida (seleccionada
        IS NOT NULL) nunca se vuelve a tocar, y la reserva solo pasa a
        'completada' cuando TODAS las líneas ya tienen una decisión -- una
        selección parcial dentro de una llamada, o repartida en varias
        llamadas, deja el resto tal cual sin liberar de más ni completar
        antes de tiempo."""
        reserva = self._obtener_de_mi_sucursal(db, reserva_id, usuario_id)
        estado_actual = self._estados.obtener(db, reserva.estado_id)
        if estado_actual.codigo != "en_prueba":
            raise ConflictoError(
                f"La reserva está en estado '{estado_actual.codigo}', no se puede registrar selección"
            )

        detalle_por_variante = {linea.variante_id: linea for linea in reserva.detalle}

        for entrada in datos.lineas:
            linea = detalle_por_variante.get(entrada.variante_id)
            if linea is None:
                raise NoEncontradoError(f"La variante {entrada.variante_id} no está en esta reserva")
            if linea.seleccionada is not None:
                # Ya decidida antes (esta llamada u otra anterior): no se
                # vuelve a tocar, para no liberar/reservar dos veces.
                raise ConflictoError(f"La variante {entrada.variante_id} ya tiene una selección registrada")

            linea.seleccionada = entrada.seleccionada
            if not entrada.seleccionada:
                liberar_stock(db, linea.variante_id, reserva.sucursal_id, linea.cantidad, commit=False)

        db.flush()

        # Solo pasa a 'completada' si TODAS las líneas ya tienen decisión;
        # una selección parcial dentro de esta llamada (o repartida en
        # varias) deja la reserva en 'en_prueba'.
        if all(linea.seleccionada is not None for linea in reserva.detalle):
            validar_transicion(db, reserva, "completada", usuario_id, "Selección completa", commit=False)

        db.commit()
        db.refresh(reserva)
        return reserva
