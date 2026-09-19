"""CU-30 — Procesar pago en caja

Actor: Cajero.
Precondición: sesión de cajero registrado como empleado; existe una venta
en estado pendiente de pago (CU-25).
Postcondición: el pago queda aprobado, la venta pagada y el inventario de
la sucursal actualizado.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import DomainError, PermisoDenegadoError
from app.organizacion import politicas as organizacion_politicas
from app.pagos.models import Pago
from app.pagos.repository import EstadoPagoRepository, MetodoPagoRepository, PagoRepository
from app.pagos.schemas import PagoCajaRequest
from app.ventas.politicas import confirmar_venta, obtener_venta


class ProcesarPagoCaja:
    def __init__(self) -> None:
        self._metodos = MetodoPagoRepository()
        self._estados = EstadoPagoRepository()
        self._pagos = PagoRepository()

    def ejecutar(self, db: Session, usuario_id: int, datos: PagoCajaRequest) -> tuple[Pago, Decimal | None]:
        empleado = organizacion_politicas.obtener_empleado_por_usuario(db, usuario_id)
        if empleado is None:
            raise PermisoDenegadoError("Este usuario no es un empleado, no puede cobrar en caja")

        venta = obtener_venta(db, datos.venta_id)
        # Cobrar confirma la venta y descuenta stock de SU sucursal: solo se
        # cobra en caja lo de la sucursal propia.
        organizacion_politicas.validar_acceso_sucursal(db, usuario_id, venta.sucursal_id)
        metodo = self._metodos.obtener_por_codigo(db, datos.metodo_pago)
        if not metodo.disponible_caja:
            raise DomainError(f"'{metodo.codigo}' no está disponible en caja")

        cambio: Decimal | None = None
        if metodo.codigo == "efectivo":
            if datos.monto_recibido is None:
                raise DomainError("El pago en efectivo necesita monto_recibido")
            if datos.monto_recibido < venta.total:
                raise DomainError(f"El monto recibido ({datos.monto_recibido}) no cubre el total ({venta.total})")
            cambio = datos.monto_recibido - venta.total

        estado_aprobado = self._estados.obtener_por_codigo(db, "aprobado")
        pago = Pago(venta_id=venta.id, metodo_pago_id=metodo.id, estado_id=estado_aprobado.id, monto=venta.total)
        self._pagos.crear(db, pago)  # flush

        # El pago en caja se aprueba en el momento: no hay pasarela ni
        # webhook, así que acá mismo se dispara la confirmación de la venta.
        confirmar_venta(db, venta.id, usuario_id=usuario_id, commit=False)

        db.commit()
        db.refresh(pago)
        return pago, cambio
