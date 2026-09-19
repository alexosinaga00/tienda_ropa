"""CU-25 — Registrar venta presencial

Actor: Cajero.
Precondición: el usuario logueado es un empleado de la sucursal de la
venta; si viene de una reserva, esta ya está en estado completada (CU-20
ya hizo esa transición), es de esa misma sucursal y no tiene otra venta
vigente.
Postcondición: se crea la venta en estado pendiente_pago, lista para
cobrar en caja (CU-30).

Envoltorio fino sobre ventas.politicas.registrar_venta: no reimplementa
la lógica común con CU-24. Si la venta parte de una reserva, usa las
líneas que el cliente ya marcó `seleccionada=True` al probarse.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictoError, DomainError, PermisoDenegadoError
from app.organizacion import politicas as organizacion_politicas
from app.reservas.politicas import obtener_reserva_para_venta
from app.seguridad.politicas import obtener_cliente
from app.ventas.models import Venta
from app.ventas.politicas import registrar_venta
from app.ventas.repository import VentaRepository
from app.ventas.schemas import VentaPresencialCrear


class RegistrarVentaPresencial:
    def __init__(self) -> None:
        self._ventas = VentaRepository()

    def ejecutar(self, db: Session, usuario_id: int, datos: VentaPresencialCrear) -> Venta:
        empleado = organizacion_politicas.obtener_empleado_por_usuario(db, usuario_id)
        if empleado is None:
            raise PermisoDenegadoError("Este usuario no es un empleado, no puede registrar ventas presenciales")
        organizacion_politicas.validar_acceso_sucursal(db, usuario_id, datos.sucursal_id)

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
