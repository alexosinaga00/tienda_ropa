"""CU-19 — Gestionar envíos y tarifas

Absorbe los antiguos CU-41 (Gestionar zonas de envío), CU-42 (Solicitar
envío a domicilio) y CU-43 (Actualizar estado del envío).

Actor: Administrador, Encargado de sucursal, Cliente.
Precondición: el administrador (permiso entregas.gestionar) gestiona las
zonas de envío; el cliente, con sesión, administra sus direcciones, cotiza y
crea el envío de una venta propia; el personal actualiza el estado de los
envíos de su sucursal (salvo alcance global) y, para despacharlos o
entregarlos, la venta tiene que estar pagada.
Postcondición: la zona (y sus reglas de recargo por peso) queda disponible
para cotizar y crear envíos; se cotiza el costo y, al confirmar la compra
(CU-13), el envío queda registrado junto con ella, solo si el costo de
envío de la venta coincide con la tarifa real de la zona; el envío avanza
desde programado hasta entregado o fallido. Al entregarse, la venta pasa a
'entregada' en la misma transacción; si falla, la venta no cambia. Al pasar
a en ruta, entregado o fallido se le avisa al cliente con una notificación
(tipo 'envio') en esa misma transacción.

Caso de uso COMPUESTO: agrupa gestionar las zonas y tarifas, las
direcciones de entrega del cliente, cotizar y crear el envío (la fórmula de
tarifa `_calcular_costo` es interna de este archivo) y actualizar el estado
del envío, con las consultas que el personal y el cliente necesitan para
encontrarlo y seguirlo."""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.comercial import politicas as comercial_politicas
from app.comercial.models import DireccionCliente, Envio, ZonaEnvio
from app.comercial.politicas import obtener_comprobante
from app.comercial.repository import DireccionClienteRepository, EnvioRepository, ZonaEnvioRepository
from app.comercial.schemas import (
    CotizarEnvioRequest,
    CotizarEnvioRespuesta,
    DireccionClienteActualizar,
    DireccionClienteCrear,
    EnvioCrear,
    EnvioEstadoActualizar,
    ZonaEnvioActualizar,
    ZonaEnvioCrear,
)
from app.core.config import get_settings
from app.core.deps import ParametrosPaginacion
from app.core.exceptions import ConflictoError, DomainError, NoEncontradoError
from app.core.tiempo import ahora_utc_naive
from app.plataforma import politicas as plataforma_politicas
from app.plataforma.politicas import obtener_perfil_cliente


# ---- Gestionar zonas de envío (antiguo CU-41) ----

class GestionarZonasTarifas:
    def __init__(self) -> None:
        self._zonas = ZonaEnvioRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[ZonaEnvio]:
        return list(self._zonas.listar(db, paginacion))

    def obtener(self, db: Session, zona_id: int) -> ZonaEnvio:
        return self._zonas.obtener(db, zona_id)

    def crear(self, db: Session, datos: ZonaEnvioCrear) -> ZonaEnvio:
        plataforma_politicas.obtener_ciudad(db, datos.ciudad_id)  # 404 si no existe o es de otra empresa
        return self._zonas.crear(db, datos)

    def actualizar(self, db: Session, zona_id: int, datos: ZonaEnvioActualizar) -> ZonaEnvio:
        return self._zonas.actualizar(db, zona_id, datos)

    def desactivar(self, db: Session, zona_id: int) -> ZonaEnvio:
        return self._zonas.desactivar(db, zona_id)


# ---- Solicitar envío a domicilio (antiguo CU-42) ----

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
        # venta.costo_envio lo mandó el cliente al comprar (CU-13, lo que le
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


# programado -> en_ruta -> entregado | fallido. 'entregado' y 'fallido' son
# terminales: un envío que ya llegó (o falló) no vuelve a moverse de ahí.
_TRANSICIONES: dict[str, set[str]] = {
    "programado": {"en_ruta", "fallido"},
    "en_ruta": {"entregado", "fallido"},
    "entregado": set(),
    "fallido": set(),
}

# Estados que mueven mercadería: solo con la venta pagada. 'fallido' se
# permite siempre, para poder cerrar el envío de una venta anulada.
_ESTADOS_QUE_EXIGEN_VENTA_PAGADA = {"en_ruta", "entregado"}

# Lo que se le avisa al cliente al cambiar el estado (título, mensaje con el código de la compra).
_AVISOS_AL_CLIENTE: dict[str, tuple[str, str]] = {
    "en_ruta": ("Tu pedido está en camino", "Tu compra {codigo} salió a reparto."),
    "entregado": ("Tu pedido fue entregado", "Tu compra {codigo} ya llegó. ¡Gracias por comprar!"),
    "fallido": (
        "No pudimos entregar tu pedido",
        "No se pudo entregar tu compra {codigo}. Comunicate con la sucursal.",
    ),
}


# ---- Actualizar estado del envío (antiguo CU-43) ----

class ActualizarEstadoEnvio:
    def __init__(self) -> None:
        self._envios = EnvioRepository()

    def actualizar_estado(self, db: Session, usuario_id: int, envio_id: int, datos: EnvioEstadoActualizar) -> Envio:
        # Fila bloqueada: dos actualizaciones simultáneas del mismo envío se
        # serializan, la segunda ve el estado que dejó la primera.
        envio = self._envios.obtener_bloqueado(db, envio_id)
        venta = comercial_politicas.obtener_venta(db, envio.venta_id)
        # El envío sale de la sucursal de la venta: lo mueve su personal.
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, venta.sucursal_id)

        permitidos = _TRANSICIONES.get(envio.estado, set())
        if datos.estado not in permitidos:
            raise ConflictoError(f"No se puede pasar de '{envio.estado}' a '{datos.estado}'")

        if datos.estado in _ESTADOS_QUE_EXIGEN_VENTA_PAGADA:
            estado_venta = comercial_politicas.obtener_estado_codigo(db, venta.estado_id)
            if estado_venta != "pagada":
                raise ConflictoError(
                    f"No se puede pasar el envío a '{datos.estado}': la venta está '{estado_venta}', debe estar 'pagada'"
                )

        envio.estado = datos.estado
        if datos.repartidor is not None:
            envio.repartidor = datos.repartidor
        if datos.estado == "en_ruta" and envio.fecha_programada is None:
            envio.fecha_programada = ahora_utc_naive()
        elif datos.estado == "entregado":
            envio.fecha_entrega = ahora_utc_naive()
            # Sin commit propio: envío y venta cambian en una sola transacción.
            comercial_politicas.marcar_venta_entregada(db, envio.venta_id, commit=False)

        self._avisar_al_cliente(db, venta, datos.estado)

        db.commit()
        db.refresh(envio)
        return envio

    def _avisar_al_cliente(self, db: Session, venta, estado: str) -> None:
        """Notificación para el dueño de la compra, dentro de la misma transacción del cambio de
        estado (`commit=False`): si algo falla, no queda ni el cambio ni el aviso."""
        aviso = _AVISOS_AL_CLIENTE.get(estado)
        if aviso is None or venta.cliente_id is None:
            return  # las ventas presenciales no tienen cliente al que avisar
        cliente = plataforma_politicas.obtener_cliente(db, venta.cliente_id)
        titulo, mensaje = aviso
        plataforma_politicas.crear_notificacion(
            db,
            cliente.usuario_id,
            titulo,
            mensaje.format(codigo=venta.codigo),
            tipo="envio",
            referencia_id=venta.id,
            commit=False,
        )

    def listar(
        self,
        db: Session,
        usuario_id: int,
        paginacion: ParametrosPaginacion,
        estado: str | None = None,
        sucursal_id: int | None = None,
    ) -> list[Envio]:
        """Envíos para el personal. Con alcance global ve todas las sucursales
        (o filtra por una); si no, siempre la suya (403 si pide otra)."""
        sucursal_id = plataforma_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        ventas_de_sucursal = comercial_politicas.subconsulta_ventas_de_sucursal(sucursal_id) if sucursal_id else None
        return self._envios.listar(db, paginacion, estado=estado, ventas_de_sucursal=ventas_de_sucursal)

    def obtener(self, db: Session, usuario_id: int, envio_id: int) -> Envio:
        """Dueño de la compra o personal de su sucursal (mismo chequeo que `SolicitarEnvioDomicilio`)."""
        envio = self._envios.obtener(db, envio_id)
        comercial_politicas.obtener_comprobante(db, envio.venta_id, usuario_id)
        return envio

    def obtener_por_venta(self, db: Session, usuario_id: int, venta_id: int) -> Envio:
        comercial_politicas.obtener_comprobante(db, venta_id, usuario_id)
        envio = self._envios.obtener_por_venta(db, venta_id)
        if envio is None:
            raise NoEncontradoError("Esta venta no tiene envío")
        return envio
