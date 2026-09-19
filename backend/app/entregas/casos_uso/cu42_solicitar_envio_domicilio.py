"""CU-42 — Solicitar envío a domicilio

Actor: Cliente.
Precondición: el cliente tiene sesión iniciada; la venta y la dirección
existen y le pertenecen.
Postcondición: se cotiza el costo del envío y, al confirmar la compra
(CU-24), queda registrado junto con ella. El envío solo se crea si el
costo de envío de la venta coincide con la tarifa real de la zona.

Caso de uso COMPUESTO: agrupa gestionar las direcciones de entrega del
cliente, cotizar el envío (cálculo puro) y crear el envío efectivo. La
fórmula de tarifa (`_calcular_costo`) es interna de este archivo: solo
CU-42 la necesita (cotizar y crear_envio), no hace falta promoverla a
politicas.py.
"""

import datetime as dt
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictoError, DomainError, NoEncontradoError
from app.entregas.models import DireccionCliente, Envio, ZonaEnvio
from app.entregas.repository import DireccionClienteRepository, EnvioRepository, ZonaEnvioRepository
from app.entregas.schemas import (
    CotizarEnvioRequest,
    CotizarEnvioRespuesta,
    DireccionClienteActualizar,
    DireccionClienteCrear,
    EnvioCrear,
)
from app.seguridad.politicas import obtener_perfil_cliente
from app.ventas.politicas import obtener_comprobante


class SolicitarEnvioDomicilio:
    def __init__(self) -> None:
        self._zonas = ZonaEnvioRepository()
        self._direcciones = DireccionClienteRepository()
        self._envios = EnvioRepository()

    def _peso_pedido(self, cantidad_prendas: int) -> Decimal:
        return get_settings().peso_promedio_prenda_kg * cantidad_prendas

    def _calcular_costo(self, db: Session, zona: ZonaEnvio, peso_kg: Decimal) -> tuple[Decimal, Decimal]:
        """(recargo_por_peso, costo_total). El recargo es el de la regla de
        la zona cuyo rango [peso_desde_kg, peso_hasta_kg] contiene el peso
        del pedido; sin regla que lo cubra, no hay recargo por peso."""
        recargo = Decimal("0")
        for regla in self._zonas.listar_reglas(db, zona.id):
            if peso_kg >= regla.peso_desde_kg and (regla.peso_hasta_kg is None or peso_kg <= regla.peso_hasta_kg):
                recargo = regla.recargo
                break
        return recargo, zona.tarifa_base + recargo

    def _direccion_con_zona(self, db: Session, direccion_id: int) -> tuple[DireccionCliente, ZonaEnvio]:
        direccion = self._direcciones.obtener(db, direccion_id)
        if direccion.zona_envio_id is None:
            raise DomainError("Esta dirección no tiene una zona de envío asignada")
        zona = self._zonas.obtener(db, direccion.zona_envio_id)
        return direccion, zona

    def cotizar(self, db: Session, datos: CotizarEnvioRequest) -> CotizarEnvioRespuesta:
        _direccion, zona = self._direccion_con_zona(db, datos.direccion_id)
        peso = self._peso_pedido(datos.cantidad_prendas)
        recargo, costo = self._calcular_costo(db, zona, peso)
        return CotizarEnvioRespuesta(
            zona_envio_id=zona.id,
            zona_nombre=zona.nombre,
            peso_kg=peso,
            tarifa_base=zona.tarifa_base,
            recargo_peso=recargo,
            costo=costo,
        )

    # -- Direcciones de cliente (recurso propio del cliente logueado) ------

    def listar_mis_direcciones(self, db: Session, usuario_id: int) -> list[DireccionCliente]:
        cliente = obtener_perfil_cliente(db, usuario_id)
        return self._direcciones.listar_por_cliente(db, cliente.id)

    def crear_mi_direccion(self, db: Session, usuario_id: int, datos: DireccionClienteCrear) -> DireccionCliente:
        cliente = obtener_perfil_cliente(db, usuario_id)
        if datos.zona_envio_id is not None:
            self._zonas.obtener(db, datos.zona_envio_id)  # 404 si no existe o está inactiva
        return self._direcciones.crear(db, cliente.id, datos)

    def _validar_acceso_direccion(self, db: Session, direccion: DireccionCliente, usuario_id: int) -> None:
        cliente = obtener_perfil_cliente(db, usuario_id)
        if cliente is None or direccion.cliente_id != cliente.id:
            # 404, no 403: no confirma a otro cliente que el id existe.
            raise NoEncontradoError("Dirección no encontrada")

    def actualizar_mi_direccion(
        self, db: Session, usuario_id: int, direccion_id: int, datos: DireccionClienteActualizar
    ) -> DireccionCliente:
        direccion = self._direcciones.obtener(db, direccion_id)
        self._validar_acceso_direccion(db, direccion, usuario_id)
        if datos.zona_envio_id is not None:
            self._zonas.obtener(db, datos.zona_envio_id)
        return self._direcciones.actualizar(db, direccion_id, datos)

    def desactivar_mi_direccion(self, db: Session, usuario_id: int, direccion_id: int) -> DireccionCliente:
        direccion = self._direcciones.obtener(db, direccion_id)
        self._validar_acceso_direccion(db, direccion, usuario_id)
        return self._direcciones.desactivar(db, direccion_id)

    # -- Envíos -------------------------------------------------------------

    def crear_envio(self, db: Session, usuario_id: int, datos: EnvioCrear) -> Envio:
        venta = obtener_comprobante(db, datos.venta_id, usuario_id)  # valida dueño o staff
        if self._envios.obtener_por_venta(db, venta.id) is not None:
            raise ConflictoError("Esta venta ya tiene un envío registrado")

        direccion, zona = self._direccion_con_zona(db, datos.direccion_id)
        if venta.cliente_id is None or direccion.cliente_id != venta.cliente_id:
            raise DomainError("La dirección no pertenece al cliente de esta venta")

        cantidad_prendas = sum(linea.cantidad for linea in venta.detalle)
        peso = self._peso_pedido(cantidad_prendas)
        # venta.costo_envio lo mandó el cliente al comprar (CU-24, lo que le
        # devolvió cotizar() en el checkout): no es confiable. Se recalcula
        # con la tarifa real de la zona y solo se acepta si coincide -- si
        # no, cualquiera conseguiría un envío pagando menos de lo que cuesta.
        # DomainError (400), no ConflictoError: web y mobile toman un 409 en
        # este endpoint como "el envío ya existía" y seguirían al pago.
        _recargo, costo_real = self._calcular_costo(db, zona, peso)
        if venta.costo_envio != costo_real:
            raise DomainError(
                f"El costo de envío de la compra (Bs {venta.costo_envio}) no coincide con la tarifa de la zona "
                f"(Bs {costo_real}). Volvé a cotizar el envío."
            )

        envio = Envio(
            venta_id=venta.id,
            direccion_id=direccion.id,
            zona_envio_id=zona.id,
            costo=costo_real,
            peso_kg=peso,
            estado="programado",
        )
        return self._envios.crear(db, envio)
