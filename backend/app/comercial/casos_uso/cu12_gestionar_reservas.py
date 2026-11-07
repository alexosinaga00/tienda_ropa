"""CU-12 — Gestionar reservas

Absorbe los antiguos CU-16 (Reservar varias prendas), CU-17 (Consultar
estado de reserva), CU-18 (Cancelar reserva), CU-19 (Consultar reservas de
la sucursal) y CU-20 (Atender prueba de reserva en sucursal).

Actor: Cliente, Encargado de sucursal.
Precondición: sesión iniciada. El cliente reserva, consulta y cancela sus
reservas; el encargado (con el permiso reservas.gestionar_sucursal, solo de
su sucursal salvo alcance global, ver plataforma.politicas) atiende las de
su sucursal. Para cancelar, la reserva propia está en estado pendiente o
preparada.
Postcondición: la reserva queda registrada con el stock de cada línea
reservado y la sucursal recibe la notificación; avanza por su ciclo de
atención (preparada → en_prueba → completada), liberando el stock de lo que
el cliente no se llevó, o queda cancelada y las unidades vuelven a estar
disponibles para otros clientes.

Caso de uso COMPUESTO: agrupa reservar varias prendas, consultar el estado
de la reserva, cancelarla, consultar las reservas de la sucursal y atender
la prueba en sucursal (preparar las prendas, confirmar la llegada del
cliente y registrar la selección final)."""

from sqlalchemy.orm import Session

from app.catalogo.politicas import bloquear_stock_en_orden, liberar_stock
from app.comercial.models import Reserva
from app.comercial.politicas import (
    crear_reserva,
    validar_propietario_o_staff,
    validar_topes_de_reserva_del_cliente,
    validar_transicion,
)
from app.comercial.repository import EstadoReservaRepository, ReservaRepository
from app.comercial.schemas import ReservaCrear, SeleccionActualizar
from app.core.exceptions import ConflictoError, NoEncontradoError
from app.plataforma import politicas as plataforma_politicas
from app.plataforma.politicas import obtener_cliente, obtener_perfil_cliente


# ---- Reservar varias prendas (antiguo CU-16) ----

class ReservarPrendas:
    def ejecutar(self, db: Session, usuario_id: int, datos: ReservaCrear) -> Reserva:
        # La lógica vive en comercial.politicas.crear_reserva, para que la
        # sincronización offline (CU-25) reserve dentro de su propia unidad de trabajo.
        # Los topes (fecha cercana, pocas unidades, pocas reservas abiertas) valen para el CLIENTE que reserva en línea.
        validar_topes_de_reserva_del_cliente(db, usuario_id, datos)
        return crear_reserva(db, usuario_id, datos, commit=True)


# ---- Consultar estado de reserva (antiguo CU-17) ----

class ConsultarEstadoReserva:
    def __init__(self) -> None:
        self._reservas = ReservaRepository()

    def obtener(self, db: Session, reserva_id: int, usuario_id: int) -> Reserva:
        reserva = self._reservas.obtener(db, reserva_id)
        validar_propietario_o_staff(db, reserva, usuario_id)
        return reserva

    def listar_mias(self, db: Session, usuario_id: int) -> list[Reserva]:
        cliente = obtener_perfil_cliente(db, usuario_id)
        return self._reservas.listar_por_cliente(db, cliente.id)


# ---- Cancelar reserva (antiguo CU-18) ----

class CancelarReserva:
    def __init__(self) -> None:
        self._reservas = ReservaRepository()
        self._estados = EstadoReservaRepository()

    def ejecutar(self, db: Session, reserva_id: int, usuario_id: int) -> Reserva:
        # Bloqueada: no compite con expirar_reservas_vencidas (libera el stock una sola vez).
        reserva = self._reservas.obtener_bloqueado(db, reserva_id)
        validar_propietario_o_staff(db, reserva, usuario_id)

        estado_actual = self._estados.obtener(db, reserva.estado_id)
        if estado_actual.codigo not in ("pendiente", "preparada"):
            raise ConflictoError(f"No se puede cancelar una reserva en estado '{estado_actual.codigo}'")

        bloquear_stock_en_orden(db, [(linea.variante_id, reserva.sucursal_id) for linea in reserva.detalle])
        for linea in reserva.detalle:
            liberar_stock(db, linea.variante_id, reserva.sucursal_id, linea.cantidad, commit=False)

        return validar_transicion(db, reserva, "cancelada", usuario_id, "Cancelada", commit=True)


# ---- Consultar reservas de la sucursal (antiguo CU-19) ----

class ConsultarReservasSucursal:
    def __init__(self) -> None:
        self._reservas = ReservaRepository()

    def ejecutar(self, db: Session, sucursal_id: int, usuario_id: int) -> list[Reserva]:
        plataforma_politicas.obtener_sucursal(db, sucursal_id)
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, sucursal_id)
        return self._reservas.listar_por_sucursal(db, sucursal_id)


# ---- Atender prueba de reserva en sucursal (antiguo CU-20) ----

class AtenderPruebaReservaSucursal:
    def __init__(self) -> None:
        self._reservas = ReservaRepository()
        self._estados = EstadoReservaRepository()

    def _obtener_de_mi_sucursal(self, db: Session, reserva_id: int, usuario_id: int) -> Reserva:
        # Bloqueada: las transiciones del personal no compiten con la expiración ni con la cancelación.
        reserva = self._reservas.obtener_bloqueado(db, reserva_id)
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, reserva.sucursal_id)
        return reserva

    def preparar(self, db: Session, reserva_id: int, usuario_id: int) -> Reserva:
        reserva = self._obtener_de_mi_sucursal(db, reserva_id, usuario_id)
        validar_transicion(db, reserva, "preparada", usuario_id, "Prendas preparadas", commit=False)
        for linea in reserva.detalle:
            linea.preparada = True

        cliente = obtener_cliente(db, reserva.cliente_id)
        plataforma_politicas.crear_notificacion(
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

        bloquear_stock_en_orden(
            db,
            [
                (entrada.variante_id, reserva.sucursal_id)
                for entrada in datos.lineas
                if not entrada.seleccionada and entrada.variante_id in detalle_por_variante
            ],
        )
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
