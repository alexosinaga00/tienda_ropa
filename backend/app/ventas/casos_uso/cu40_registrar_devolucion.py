"""CU-40 — Registrar devolución

Actor: Cajero, Encargado de sucursal.
Precondición: la venta existe, está pagada o entregada y es de la
sucursal del empleado (salvo alcance global).
Postcondición: la devolución queda registrada y el stock reingresa a la
sucursal.

Nota: esta etapa no dispara ningún reembolso en `pagos` (no hay un flujo
de aprobación de devolución en el alcance actual) -- solo reingresa stock
y dejó constancia. Si en el futuro se agrega reembolso, va acá, como
llamada a pagos, sin duplicar la lógica de devolución.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import DomainError, NoEncontradoError
from app.inventario.politicas import actualizar_stock_operacion
from app.organizacion import politicas as organizacion_politicas
from app.ventas.models import Devolucion, DevolucionDetalle
from app.ventas.politicas import generar_codigo
from app.ventas.repository import DevolucionRepository, EstadoVentaRepository, VentaRepository
from app.ventas.schemas import DevolucionCrear


class RegistrarDevolucion:
    def __init__(self) -> None:
        self._ventas = VentaRepository()
        self._estados = EstadoVentaRepository()
        self._devoluciones = DevolucionRepository()

    def _obtener_devolucion_por_codigo(self, db: Session, codigo: str) -> Devolucion | None:
        return db.scalar(select(Devolucion).where(Devolucion.codigo == codigo))

    def ejecutar(self, db: Session, usuario_id: int, datos: DevolucionCrear) -> Devolucion:
        venta = self._ventas.obtener(db, datos.venta_id)
        # El stock reingresa a la sucursal de la venta: solo su personal.
        organizacion_politicas.validar_acceso_sucursal(db, usuario_id, venta.sucursal_id)

        # Con el pago gateado, una venta 'pendiente_pago' nunca descontó
        # stock físico -- no hay nada real que devolver todavía.
        estado_venta = self._estados.obtener(db, venta.estado_id)
        if estado_venta.codigo not in ("pagada", "entregada"):
            raise DomainError(f"No se puede devolver una venta en estado '{estado_venta.codigo}'")

        detalle_por_id = {linea.id: linea for linea in venta.detalle}

        devolucion = Devolucion(
            codigo=generar_codigo(db, "DEV", self._obtener_devolucion_por_codigo),
            venta_id=venta.id,
            motivo=datos.motivo,
            estado="aprobada",  # esta etapa no tiene un flujo de aprobación aparte
            usuario_id=usuario_id,
        )
        db.add(devolucion)
        db.flush()

        for linea in datos.detalle:
            detalle = detalle_por_id.get(linea.venta_detalle_id)
            if detalle is None:
                raise NoEncontradoError(f"La línea {linea.venta_detalle_id} no pertenece a la venta {venta.id}")

            ya_devuelto = self._devoluciones.cantidad_devuelta(db, linea.venta_detalle_id)
            if ya_devuelto + linea.cantidad > detalle.cantidad:
                raise DomainError(
                    f"No se puede devolver más de lo vendido en la línea {linea.venta_detalle_id} "
                    f"({ya_devuelto} ya devuelto de {detalle.cantidad})"
                )

            db.add(DevolucionDetalle(devolucion_id=devolucion.id, venta_detalle_id=detalle.id, cantidad=linea.cantidad))

            # La devolución reingresa stock (movimiento tipo 'devolucion');
            # no reabre la venta ni cambia su estado -- esta etapa no toca
            # pagos.
            actualizar_stock_operacion(
                db,
                variante_id=detalle.variante_id,
                sucursal_id=venta.sucursal_id,
                tipo_movimiento_codigo="devolucion",
                cantidad=linea.cantidad,
                referencia_tipo="devolucion",
                referencia_id=devolucion.id,
                usuario_id=usuario_id,
                commit=False,
            )

        db.commit()
        db.refresh(devolucion)
        return devolucion
