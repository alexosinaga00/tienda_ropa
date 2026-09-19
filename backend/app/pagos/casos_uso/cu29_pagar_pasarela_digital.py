"""CU-29 — Pagar mediante pasarela digital

Actor: Cliente.
Precondición: sesión de cliente; existe una venta digital pendiente de
pago (CU-24).
Postcondición: se inicia el pago en la pasarela y queda a la espera de la
confirmación (CU-31).

Incluye cancelar una compra que todavía no se pagó (el cliente la
abandona): libera el stock reservado y le devuelve las prendas al
carrito.
"""

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictoError, DomainError
from app.pagos.models import Pago
from app.pagos.pasarela import obtener_pasarela
from app.pagos.politicas import cancelar_venta_pendiente, cerrar_pagos_iniciados
from app.pagos.repository import EstadoPagoRepository, MetodoPagoRepository, PagoRepository, TransaccionPasarelaRepository
from app.pagos.models import TransaccionPasarela
from app.pagos.schemas import PagoIniciarRequest
from app.ventas.politicas import obtener_comprobante, obtener_estado_codigo, obtener_venta_bloqueada


class PagarPasarelaDigital:
    def __init__(self) -> None:
        self._metodos = MetodoPagoRepository()
        self._estados = EstadoPagoRepository()
        self._pagos = PagoRepository()
        self._transacciones = TransaccionPasarelaRepository()

    def iniciar(self, db: Session, usuario_id: int, datos: PagoIniciarRequest) -> tuple[Pago, str]:
        obtener_comprobante(db, datos.venta_id, usuario_id)  # valida dueño o staff, 404 si no existe

        # Bloquea la fila de la venta ANTES de decidir si se puede iniciar
        # un pago nuevo: serializa esta validación con cualquier otro
        # iniciar/confirmar_venta/anular_venta concurrente sobre la misma
        # venta (mismo patrón de lock que inventario usa para stock). Sin
        # esto, dos requests casi simultáneas (doble click, retry con otro
        # método de pago) pueden pasar la validación de "sin pago activo"
        # antes de que ninguna comitee, y terminar cobrando DOS veces de
        # verdad en la pasarela externa.
        venta = obtener_venta_bloqueada(db, datos.venta_id)
        estado_venta_actual = obtener_estado_codigo(db, venta.estado_id)
        if estado_venta_actual != "pendiente_pago":
            raise ConflictoError(f"La venta está '{estado_venta_actual}', no se puede iniciar un pago")

        metodo = self._metodos.obtener_por_codigo(db, datos.metodo_pago)
        if not metodo.requiere_pasarela:
            raise DomainError(f"'{metodo.codigo}' no es un método por pasarela, usá /pagos/caja")

        # Un pago 'iniciado' que nunca se completó (la pasarela lo denegó,
        # el cliente cerró la ventana) bloqueaba la venta para siempre: se
        # reemplaza, salvo que en realidad ya se haya cobrado.
        if cerrar_pagos_iniciados(db, venta.id, motivo="reemplazado_por_reintento"):
            raise ConflictoError("Esta venta ya fue pagada")

        estado_iniciado = self._estados.obtener_por_codigo(db, "iniciado")
        pago = Pago(venta_id=venta.id, metodo_pago_id=metodo.id, estado_id=estado_iniciado.id, monto=venta.total)
        self._pagos.crear(db, pago)  # flush: pago.id ya disponible

        pasarela = obtener_pasarela(metodo.codigo)
        try:
            resultado = pasarela.iniciar_pago(monto=venta.total, referencia=venta.codigo)
        except RuntimeError as exc:
            # No deja el pago en 'iniciado' colgado si la pasarela real (p.
            # ej. PayPal) no respondió: no tiene una transacción real detrás.
            db.rollback()
            raise DomainError(str(exc)) from exc
        pago.referencia_externa = resultado.id_transaccion

        payload_envio = {"monto": str(venta.total), "referencia": venta.codigo}
        payload_respuesta = {"id_transaccion": resultado.id_transaccion, "url_redireccion": resultado.url_redireccion}
        self._transacciones.crear(
            db,
            TransaccionPasarela(
                pago_id=pago.id,
                pasarela=metodo.codigo,
                id_transaccion=resultado.id_transaccion,
                payload_envio=payload_envio,
                payload_respuesta=payload_respuesta,
                estado="iniciado",
            ),
        )

        db.commit()
        db.refresh(pago)
        return pago, resultado.url_redireccion

    def cancelar(self, db: Session, usuario_id: int, venta_id: int) -> None:
        """El cliente abandona una compra que todavía no pagó: libera el
        stock reservado y le devuelve las prendas al carrito."""
        obtener_comprobante(db, venta_id, usuario_id)  # valida dueño o staff, 404 si no existe
        cancelar_venta_pendiente(db, venta_id, motivo="cancelado_por_cliente")
