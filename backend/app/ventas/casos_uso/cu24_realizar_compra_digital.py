"""CU-24 — Realizar compra digital

Actor: Cliente.
Precondición: el carrito no está vacío.
Postcondición: se crea la venta en estado pendiente_pago; el pago
(CU-29) y, si hay envío, la cotización de entrega (CU-42) se disparan
después.

Envoltorio fino sobre ventas.politicas.registrar_venta: no reimplementa
la lógica común con CU-25.
"""

from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.core.exceptions import ConflictoError, DomainError
from app.organizacion import politicas as organizacion_politicas
from app.seguridad.politicas import obtener_perfil_cliente
from app.ventas.models import Venta
from app.ventas.politicas import registrar_venta
from app.ventas.repository import CarritoRepository
from app.ventas.schemas import VentaDigitalCrear


class RealizarCompraDigital:
    def __init__(self) -> None:
        self._carritos = CarritoRepository()

    def ejecutar(self, db: Session, usuario_id: int, datos: VentaDigitalCrear) -> Venta:
        cliente = obtener_perfil_cliente(db, usuario_id)
        carrito = self._carritos.obtener_por_cliente(db, cliente.id)
        if carrito is None or not carrito.detalle:
            raise DomainError("El carrito está vacío")

        # Una prenda que se dio de baja después de agregarla no se puede
        # comprar: se le pide al cliente que la quite (el carrito se la
        # muestra con disponible=False) en vez de fallar con un 404.
        for linea in carrito.detalle:
            variante = catalogo_politicas.buscar_variante(db, linea.variante_id)
            if variante is None or not variante.activo:
                raise ConflictoError("Hay prendas en tu carrito que ya no están disponibles: quitalas para continuar")

        lineas = [(linea.variante_id, linea.cantidad) for linea in carrito.detalle]

        # Sin costo de envío es retiro en sucursal (el envío a domicilio
        # siempre cobra la tarifa de la zona, CU-42): no se puede retirar
        # en un depósito.
        if datos.costo_envio == 0 and not organizacion_politicas.atiende_al_publico(db, datos.sucursal_id):
            raise DomainError("Esa sucursal no atiende al público: elegí otra para retirar tu pedido")

        return registrar_venta(
            db,
            canal="digital",
            sucursal_id=datos.sucursal_id,
            lineas=lineas,
            cliente_id=cliente.id,
            cajero_id=None,
            reserva_id=None,
            costo_envio=datos.costo_envio,
            usuario_id=usuario_id,
            carrito_a_vaciar=carrito,
        )
