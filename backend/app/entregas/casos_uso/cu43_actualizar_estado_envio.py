"""CU-43 — Actualizar estado del envío

Actor: Administrador, Encargado de sucursal.
Precondición: el envío existe y su venta es de la sucursal del empleado
(salvo alcance global).
Postcondición: el envío avanza desde programado hasta entregado o
fallido.
"""

import datetime as dt

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictoError
from app.entregas.models import Envio
from app.entregas.repository import EnvioRepository
from app.entregas.schemas import EnvioEstadoActualizar
from app.organizacion import politicas as organizacion_politicas
from app.ventas.politicas import obtener_venta

# programado -> en_ruta -> entregado | fallido. 'entregado' y 'fallido' son
# terminales: un envío que ya llegó (o falló) no vuelve a moverse de ahí.
_TRANSICIONES: dict[str, set[str]] = {
    "programado": {"en_ruta", "fallido"},
    "en_ruta": {"entregado", "fallido"},
    "entregado": set(),
    "fallido": set(),
}


class ActualizarEstadoEnvio:
    def __init__(self) -> None:
        self._envios = EnvioRepository()

    def ejecutar(self, db: Session, usuario_id: int, envio_id: int, datos: EnvioEstadoActualizar) -> Envio:
        envio = self._envios.obtener(db, envio_id)
        # El envío sale de la sucursal de la venta: lo mueve su personal.
        organizacion_politicas.validar_acceso_sucursal(db, usuario_id, obtener_venta(db, envio.venta_id).sucursal_id)
        permitidos = _TRANSICIONES.get(envio.estado, set())
        if datos.estado not in permitidos:
            raise ConflictoError(f"No se puede pasar de '{envio.estado}' a '{datos.estado}'")

        envio.estado = datos.estado
        if datos.repartidor is not None:
            envio.repartidor = datos.repartidor
        if datos.estado == "en_ruta" and envio.fecha_programada is None:
            envio.fecha_programada = dt.datetime.now(dt.timezone.utc)
        elif datos.estado == "entregado":
            envio.fecha_entrega = dt.datetime.now(dt.timezone.utc)

        db.commit()
        db.refresh(envio)
        return envio
