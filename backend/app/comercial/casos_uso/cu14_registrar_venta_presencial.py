"""CU-14 — Registrar venta presencial

Absorbe el antiguo CU-25 (Registrar venta presencial).

Actor: Cajero.
Precondición: el usuario logueado es un empleado de la sucursal de la
venta; si viene de una reserva, esta ya está en estado completada (CU-12
ya hizo esa transición), es de esa misma sucursal y no tiene otra venta
vigente.
Postcondición: se crea la venta en estado pendiente_pago, lista para
cobrar en caja (CU-18).

Envoltorio fino sobre comercial.politicas.registrar_venta: no reimplementa
la lógica común con CU-13. Si la venta parte de una reserva, usa las
líneas que el cliente ya marcó `seleccionada=True` al probarse.

Incluye el turno de caja (aporte propio, D24): `AbrirTurnoCaja` y `CerrarTurnoCaja` (el cajero abre el turno de su
sucursal con un monto inicial, vende y cobra, y lo cierra contando el efectivo; un supervisor puede cerrar el de otra
persona) y `CompletarConteoTurno` (un supervisor cuenta el cajón de un turno que se cerró solo al terminar el día). La
caja es de la SUCURSAL: a lo sumo un turno abierto a la vez. Vender sin turno abierto sigue permitido (no entra a
ninguna caja). El cálculo del esperado vive en `comercial.politicas` (bloque "Caja")."""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.comercial.models import Venta
from app.comercial.politicas import (
    abrir_turno,
    cerrar_turno,
    completar_conteo_de_turno,
    construir_turno_respuesta,
    es_supervisor_de_caja,
    obtener_reserva_para_venta,
    registrar_venta,
)
from app.comercial.repository import VentaRepository
from app.comercial.schemas import TurnoAbrir, TurnoCerrar, TurnoCompletarConteo, TurnoRespuesta, VentaPresencialCrear
from app.core.auditoria import ContextoAuditoria
from app.core.exceptions import ConflictoError, DomainError, PermisoDenegadoError
from app.plataforma import politicas as plataforma_politicas
from app.plataforma.politicas import obtener_cliente

class RegistrarVentaPresencial:
    def __init__(self) -> None:
        self._ventas = VentaRepository()

    def ejecutar(self, db: Session, usuario_id: int, datos: VentaPresencialCrear) -> Venta:
        empleado = plataforma_politicas.obtener_empleado_por_usuario(db, usuario_id)
        if empleado is None:
            raise PermisoDenegadoError("Este usuario no es un empleado, no puede registrar ventas presenciales")
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, datos.sucursal_id)

        if datos.reserva_id is not None:
            # Bloquea la reserva hasta el commit de registrar_venta: dos cobros
            # simultáneos de la misma reserva quedan en fila.
            reserva = obtener_reserva_para_venta(db, datos.reserva_id)
            if reserva.sucursal_id != datos.sucursal_id:
                # El stock apartado está en la sucursal de la reserva: venderla
                # en otra descontaría stock ajeno y dejaría el suyo reservado.
                raise DomainError("La reserva es de otra sucursal: cobrala en la sucursal donde se atendió")
            if self._ventas.existe_venta_vigente_de_reserva(db, reserva.id):
                raise ConflictoError("Esta reserva ya tiene una venta registrada")
            lineas = [(linea.variante_id, linea.cantidad) for linea in reserva.detalle if linea.seleccionada]
            if not lineas:
                raise DomainError("La reserva no tiene ninguna línea seleccionada para comprar")
            cliente_id = reserva.cliente_id
        else:
            if not datos.detalle:
                raise DomainError("La venta necesita al menos una línea (o un reserva_id)")
            lineas = [(linea.variante_id, linea.cantidad) for linea in datos.detalle]
            cliente_id = datos.cliente_id
            if cliente_id is not None:
                obtener_cliente(db, cliente_id)  # 404 si no existe

        return registrar_venta(
            db,
            canal="presencial",
            sucursal_id=datos.sucursal_id,
            lineas=lineas,
            cliente_id=cliente_id,
            cajero_id=empleado.id,
            reserva_id=datos.reserva_id,
            costo_envio=Decimal("0"),
            usuario_id=usuario_id,
        )


# ---- Turno de caja (aporte propio, D24) ----


class AbrirTurnoCaja:
    """Abre el turno del cajón de la sucursal con el monto inicial. 409 `turno_ya_abierto` si ya hay uno. Un turno que
    se olvidó abierto de un día anterior se cierra solo antes de abrir el nuevo."""

    def ejecutar(
        self, db: Session, usuario_id: int, datos: TurnoAbrir, contexto: ContextoAuditoria | None = None
    ) -> TurnoRespuesta:
        turno = abrir_turno(db, usuario_id, datos, contexto)
        return construir_turno_respuesta(db, turno, ver_esperado=es_supervisor_de_caja(db, usuario_id))


class CerrarTurnoCaja:
    """Cierra el turno contando el efectivo (cierre ciego: el cajero cuenta primero y recién entonces ve la diferencia).
    Lo cierra quien lo abrió o un supervisor de la sucursal."""

    def ejecutar(
        self,
        db: Session,
        usuario_id: int,
        turno_id: int,
        datos: TurnoCerrar,
        contexto: ContextoAuditoria | None = None,
    ) -> TurnoRespuesta:
        turno = cerrar_turno(db, usuario_id, turno_id, datos, contexto)
        return construir_turno_respuesta(db, turno, ver_esperado=True)  # quien cerró ya contó: ve el esperado


class CompletarConteoTurno:
    """Un supervisor cuenta el cajón de un turno cerrado automáticamente (una vez, dentro del plazo)."""

    def ejecutar(
        self,
        db: Session,
        usuario_id: int,
        turno_id: int,
        datos: TurnoCompletarConteo,
        contexto: ContextoAuditoria | None = None,
    ) -> TurnoRespuesta:
        turno = completar_conteo_de_turno(db, usuario_id, turno_id, datos, contexto)
        return construir_turno_respuesta(db, turno, ver_esperado=True)
