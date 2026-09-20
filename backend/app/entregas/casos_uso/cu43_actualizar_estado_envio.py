"""CU-43 — Actualizar estado del envío

Actor: Administrador, Encargado de sucursal.
Precondición: el envío existe y su venta es de la sucursal del empleado
(salvo alcance global). Para despacharlo (en_ruta) o entregarlo, la venta
tiene que estar pagada.
Postcondición: el envío avanza desde programado hasta entregado o
fallido. Al entregarse, la venta pasa a 'entregada' en la misma
transacción; si falla, la venta no cambia (el personal decide después). Al
pasar a en ruta, entregado o fallido se le avisa al cliente con una notificación
(tipo 'envio') en esa misma transacción.

Caso de uso compuesto (entidad principal con operaciones relacionadas): además
de actualizar el estado, expone las consultas de envíos que el personal y el
cliente necesitan para encontrar y seguir el envío.
"""

import datetime as dt

from sqlalchemy.orm import Session

from app.core import service as core_service
from app.core.deps import ParametrosPaginacion
from app.core.exceptions import ConflictoError, NoEncontradoError
from app.entregas.models import Envio
from app.entregas.repository import EnvioRepository
from app.entregas.schemas import EnvioEstadoActualizar
from app.organizacion import politicas as organizacion_politicas
from app.seguridad import politicas as seguridad_politicas
from app.ventas import politicas as ventas_politicas

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


class ActualizarEstadoEnvio:
    def __init__(self) -> None:
        self._envios = EnvioRepository()

    def actualizar_estado(self, db: Session, usuario_id: int, envio_id: int, datos: EnvioEstadoActualizar) -> Envio:
        # Fila bloqueada: dos actualizaciones simultáneas del mismo envío se
        # serializan, la segunda ve el estado que dejó la primera.
        envio = self._envios.obtener_bloqueado(db, envio_id)
        venta = ventas_politicas.obtener_venta(db, envio.venta_id)
        # El envío sale de la sucursal de la venta: lo mueve su personal.
        organizacion_politicas.validar_acceso_sucursal(db, usuario_id, venta.sucursal_id)

        permitidos = _TRANSICIONES.get(envio.estado, set())
        if datos.estado not in permitidos:
            raise ConflictoError(f"No se puede pasar de '{envio.estado}' a '{datos.estado}'")

        if datos.estado in _ESTADOS_QUE_EXIGEN_VENTA_PAGADA:
            estado_venta = ventas_politicas.obtener_estado_codigo(db, venta.estado_id)
            if estado_venta != "pagada":
                raise ConflictoError(
                    f"No se puede pasar el envío a '{datos.estado}': la venta está '{estado_venta}', debe estar 'pagada'"
                )

        envio.estado = datos.estado
        if datos.repartidor is not None:
            envio.repartidor = datos.repartidor
        if datos.estado == "en_ruta" and envio.fecha_programada is None:
            envio.fecha_programada = dt.datetime.now(dt.timezone.utc)
        elif datos.estado == "entregado":
            envio.fecha_entrega = dt.datetime.now(dt.timezone.utc)
            # Sin commit propio: envío y venta cambian en una sola transacción.
            ventas_politicas.marcar_venta_entregada(db, envio.venta_id, commit=False)

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
        cliente = seguridad_politicas.obtener_cliente(db, venta.cliente_id)
        titulo, mensaje = aviso
        core_service.crear_notificacion(
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
        sucursal_id = organizacion_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        ventas_de_sucursal = ventas_politicas.subconsulta_ventas_de_sucursal(sucursal_id) if sucursal_id else None
        return self._envios.listar(db, paginacion, estado=estado, ventas_de_sucursal=ventas_de_sucursal)

    def obtener(self, db: Session, usuario_id: int, envio_id: int) -> Envio:
        """Dueño de la compra o personal de su sucursal (mismo chequeo que CU-42)."""
        envio = self._envios.obtener(db, envio_id)
        ventas_politicas.obtener_comprobante(db, envio.venta_id, usuario_id)
        return envio

    def obtener_por_venta(self, db: Session, usuario_id: int, venta_id: int) -> Envio:
        ventas_politicas.obtener_comprobante(db, venta_id, usuario_id)
        envio = self._envios.obtener_por_venta(db, venta_id)
        if envio is None:
            raise NoEncontradoError("Esta venta no tiene envío")
        return envio
