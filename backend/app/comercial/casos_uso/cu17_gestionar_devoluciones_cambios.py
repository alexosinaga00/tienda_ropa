"""CU-17 — Gestionar devoluciones y cambios

Absorbe el antiguo CU-40 (Registrar devolución).

Actor: Cajero, Encargado de sucursal (registran y resuelven); Cliente (solicita un cambio de talla o color).
Precondición: la venta existe, está pagada o entregada, es de la
sucursal del empleado (salvo alcance global) y está dentro del plazo de cambio
de la empresa (24 horas por defecto, desde la fecha real de la venta).
Postcondición: la devolución queda registrada y el stock reingresa a la
sucursal. Si la línea pide un CAMBIO (`variante_nueva_id`), la variante nueva sale
del stock de la misma sucursal en la misma transacción; si no hay stock, no se
registra nada. A quien compró (si tiene correo) le llega un comprobante.

Cambio de talla o color: la variante nueva debe ser del MISMO producto y del MISMO precio, así
no hay diferencia de dinero (el reembolso todavía no existe). La salida de la variante nueva queda en el kardex
(movimiento `venta`, referencia `devolucion` + id) y la respuesta del registro la informa en `reposiciones`. Una
prenda recibida en un cambio no se puede volver a cambiar (la línea de la venta ya está agotada).

Clases de control (el diseño de clases de la defensa lista todas):
- `ConsultarPlazoCambio`: cuánto le queda a una venta para devolver o cambiar.
- `RegistrarDevolucion`: el cajero registra una devolución o un cambio en el acto (nace aprobada). Etapa 1.
- `SolicitarCambio`: el CLIENTE pide un cambio de talla o color de su compra, dentro del plazo. Queda una SOLICITUD
  (una `devolucion` en estado 'pendiente'): no mueve stock ni reserva la prenda nueva. También la cancela. Etapa 2.
- `ResolverSolicitudCambio`: el personal de la sucursal la aprueba (reutiliza el movimiento de stock de
  `RegistrarDevolucion`: mismo bloqueo, misma transacción, mismo comprobante) o la rechaza con un motivo. La
  aprobación admite una tolerancia de horas sobre el plazo (el cliente llega a la tienda después de solicitar).
- `ConsultarSolicitudesCambio`: las solicitudes del cliente y las de una sucursal.
Una solicitud pendiente que nadie atiende vence sola (`politicas.vencer_solicitudes_de_todas_las_empresas`, tarea
periódica de `app/main.py`).

Nota: esta etapa no dispara ningún reembolso en Pagos (CU-18; no hay un flujo
de aprobación de devolución en el alcance actual) -- solo mueve stock
y deja constancia. Si en el futuro se agrega reembolso, va acá, como
llamada al caso de uso de Pagos, sin duplicar la lógica de devolución."""

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.catalogo.politicas import actualizar_stock_operacion, bloquear_stock_en_orden
from app.comercial.models import Devolucion, DevolucionDetalle
from app.comercial.politicas import (
    atender_solicitud_hasta,
    construir_correo_comprobante_devolucion,
    construir_correo_solicitud_rechazada,
    construir_correo_solicitud_recibida,
    construir_respuesta_solicitud,
    describir_plazo_cambio,
    destinatario_de_venta,
    exigir_plazo_cambio,
    obtener_comprobante,
    validar_cambio_de_variante,
)
from app.comercial.repository import DevolucionRepository, EstadoVentaRepository, VentaRepository
from app.comercial.schemas import (
    DevolucionCrear,
    ReposicionCambioRespuesta,
    SolicitudCambioCrear,
    SolicitudCambioRechazar,
    SolicitudCambioRespuesta,
)
from app.core.auditoria import (
    ACCION_APROBAR,
    ACCION_CANCELAR,
    ACCION_RECHAZAR,
    ACCION_REGISTRAR,
    ACCION_SOLICITAR,
    ENTIDAD_DEVOLUCION,
    ContextoAuditoria,
)
from app.core.codigos import generar_codigo
from app.core.config import get_settings
from app.core.correo import MensajeCorreo, enviar_correo_sin_romper, envio_configurado
from app.core.exceptions import (
    ConflictoError,
    DemasiadosIntentosError,
    DomainError,
    NoEncontradoError,
    StockInsuficienteError,
)
from app.core.rate_limit import limitador_solicitud_cambio
from app.core.tiempo import ahora_utc_naive
from app.plataforma import politicas as plataforma_politicas

logger = logging.getLogger(__name__)

# `programar_envio(funcion, mensaje)` deja un correo para DESPUÉS de responder (el router pasa `BackgroundTasks.add_task`).
ProgramarEnvio = Callable[[Callable[[MensajeCorreo], object], MensajeCorreo], object]


class ConsultarPlazoCambio:
    """Cuánto le queda a una venta para devolver o cambiar prendas. Lo ve el dueño
    de la venta o el personal de su sucursal (misma regla que el comprobante)."""

    def ejecutar(self, db: Session, venta_id: int, usuario_id: int) -> dict:
        venta = obtener_comprobante(db, venta_id, usuario_id)
        return describir_plazo_cambio(db, venta)


class RegistrarDevolucion:
    def __init__(self) -> None:
        self._ventas = VentaRepository()
        self._estados = EstadoVentaRepository()
        self._devoluciones = DevolucionRepository()

    def ejecutar(
        self,
        db: Session,
        usuario_id: int,
        datos: DevolucionCrear,
        contexto: ContextoAuditoria | None = None,
        programar_envio: ProgramarEnvio | None = None,
    ) -> Devolucion:
        """Registra la devolución (y los cambios que pida). `programar_envio(funcion, mensaje)` deja el correo para
        DESPUÉS de responder (el router pasa `BackgroundTasks.add_task`); sin él, se envía en el acto. Un fallo del
        correo nunca afecta la devolución, que ya está confirmada."""
        try:
            devolucion, venta, lineas_correo = self._registrar(db, usuario_id, datos, contexto)
        except Exception:
            # Un cambio sin stock (o cualquier fallo) no deja nada a medias: ni devolución, ni reingreso, ni salida.
            db.rollback()
            raise
        devolucion.reposiciones = [
            ReposicionCambioRespuesta(
                venta_detalle_id=linea.venta_detalle_id,
                variante_devuelta_id=original_id,
                variante_nueva_id=nueva_id,
                cantidad=linea.cantidad,
            )
            for linea, original_id, nueva_id in lineas_correo.reposiciones
        ]
        devolucion.correo_programado = _programar_comprobante(db, venta, devolucion, lineas_correo, programar_envio)
        return devolucion

    def _registrar(self, db: Session, usuario_id: int, datos: DevolucionCrear, contexto: ContextoAuditoria | None):
        # Bloqueada hasta el commit: dos devoluciones simultáneas de la misma
        # venta se ponen en fila y la segunda suma lo que la primera ya
        # devolvió (y una anulación concurrente espera a que termine).
        venta = self._ventas.obtener_bloqueado(db, datos.venta_id)
        _exigir_venta_devolvible(db, self._estados, venta, usuario_id)

        # Antes de escribir nada: cada línea existe y cada cambio es válido (mismo producto y precio; 404 si la
        # variante nueva no es de esta empresa).
        cambios = _resolver_lineas(db, venta, datos.detalle)

        devolucion = Devolucion(
            codigo=generar_codigo(db, "DEV", self._devoluciones.obtener_por_codigo),
            venta_id=venta.id,
            motivo=datos.motivo,
            estado="aprobada",  # lo que el cajero registra en el acto no pasa por una solicitud
            usuario_id=usuario_id,
        )
        db.add(devolucion)
        db.flush()

        resultado = _mover_stock(db, self._devoluciones, venta, devolucion, cambios, usuario_id, crear_filas=True)

        # Misma transacción que la devolución y el stock: si algo falló antes,
        # no queda fila. El motivo (texto libre) no se copia a la bitácora.
        plataforma_politicas.registrar_bitacora_de(
            db,
            contexto,
            ENTIDAD_DEVOLUCION,
            devolucion.id,
            ACCION_REGISTRAR,
            {
                "venta_id": venta.id,
                "unidades": sum(linea.cantidad for linea in datos.detalle),
                # Solo si hubo cambio de talla o color: una devolución simple deja la misma fila de siempre.
                **({"cambios": len(resultado.reposiciones)} if resultado.reposiciones else {}),
            },
        )
        db.commit()
        db.refresh(devolucion)
        return devolucion, venta, resultado


class SolicitarCambio:
    """El cliente pide cambiar la talla o el color de una prenda de SU compra (Etapa 2). No mueve stock ni reserva
    la prenda nueva: el cajero la revisa cuando el cliente trae la prenda (`ResolverSolicitudCambio`)."""

    def __init__(self) -> None:
        self._ventas = VentaRepository()
        self._estados = EstadoVentaRepository()
        self._devoluciones = DevolucionRepository()

    def solicitar(
        self,
        db: Session,
        usuario_id: int,
        datos: SolicitudCambioCrear,
        contexto: ContextoAuditoria | None = None,
        programar_envio: ProgramarEnvio | None = None,
    ) -> SolicitudCambioRespuesta:
        clave = str(usuario_id)
        espera = limitador_solicitud_cambio.bloqueado(clave)
        if espera is not None:
            raise DemasiadosIntentosError(espera, "Hiciste muchas solicitudes de cambio. Intenta de nuevo más tarde.")
        try:
            devolucion, venta, lineas = self._crear(db, usuario_id, datos, contexto)
        except Exception:
            db.rollback()
            raise
        limitador_solicitud_cambio.registrar_fallo(clave)  # cuenta toda solicitud hecha (no es un "fallo")
        correo = self._programar_aviso(db, venta, devolucion, lineas, programar_envio)
        return construir_respuesta_solicitud(db, devolucion, venta, correo)

    def _crear(self, db: Session, usuario_id: int, datos: SolicitudCambioCrear, contexto: ContextoAuditoria | None):
        # Bloqueada: dos solicitudes simultáneas de la misma venta se ponen en fila y la segunda ve la primera.
        venta = self._ventas.obtener_bloqueado(db, datos.venta_id)
        cliente = plataforma_politicas.obtener_perfil_cliente(db, usuario_id)
        if venta.cliente_id != cliente.id:
            # La venta de otro cliente se ve igual que una inexistente.
            raise NoEncontradoError("Venta no encontrada")
        estado_venta = self._estados.obtener(db, venta.estado_id)
        if estado_venta.codigo not in ("pagada", "entregada"):
            raise DomainError(f"No se puede cambiar una compra en estado '{estado_venta.codigo}'")
        # Al SOLICITAR el plazo es estricto (sin tolerancia): la tolerancia es para atenderla en la tienda.
        exigir_plazo_cambio(db, venta)

        vistas: set[int] = set()
        for linea in datos.detalle:
            if linea.venta_detalle_id in vistas:
                raise DomainError("Cada prenda va una sola vez en la solicitud")
            vistas.add(linea.venta_detalle_id)
        cambios = _resolver_lineas(db, venta, datos.detalle)
        for linea, detalle, _original, _nueva in cambios:
            if self._devoluciones.cantidad_pendiente(db, detalle.id) > 0:
                raise ConflictoError("Ya tienes una solicitud de cambio pendiente para esa prenda")
            ya_devuelto = self._devoluciones.cantidad_devuelta(db, detalle.id)
            if ya_devuelto + linea.cantidad > detalle.cantidad:
                raise DomainError(
                    f"Solo puedes cambiar {detalle.cantidad - ya_devuelto} unidad(es) de esa prenda "
                    f"({ya_devuelto} ya devuelta(s) de {detalle.cantidad})"
                )

        devolucion = Devolucion(
            codigo=generar_codigo(db, "SOL", self._devoluciones.obtener_por_codigo),
            venta_id=venta.id,
            motivo=datos.motivo,
            estado="pendiente",
            usuario_id=usuario_id,
        )
        db.add(devolucion)
        db.flush()
        for linea, detalle, _original, nueva in cambios:
            db.add(
                DevolucionDetalle(
                    devolucion_id=devolucion.id,
                    venta_detalle_id=detalle.id,
                    cantidad=linea.cantidad,
                    variante_nueva_id=nueva.id,
                )
            )
        plataforma_politicas.registrar_bitacora_de(
            db,
            contexto,
            ENTIDAD_DEVOLUCION,
            devolucion.id,
            ACCION_SOLICITAR,
            {"venta_id": venta.id, "unidades": sum(linea.cantidad for linea in datos.detalle)},
        )
        db.commit()
        db.refresh(devolucion)
        return devolucion, venta, cambios

    def _programar_aviso(self, db: Session, venta, devolucion: Devolucion, cambios, programar_envio) -> bool:
        """Correo de 'recibimos tu solicitud'. Nunca lanza: la solicitud ya está confirmada."""
        try:
            if not envio_configurado():
                return False
            destinatario = destinatario_de_venta(db, venta)
            if destinatario is None:
                return False
            empresa = plataforma_politicas.obtener_empresa(db, venta.empresa_id)
            sucursal = plataforma_politicas.obtener_sucursal(db, venta.sucursal_id)
            mensaje = construir_correo_solicitud_recibida(
                para_email=destinatario[0],
                nombre=destinatario[1],
                nombre_empresa=empresa.nombre if empresa is not None else "FashionStore",
                codigo_solicitud=devolucion.codigo,
                codigo_venta=venta.codigo,
                sucursal=sucursal.nombre,
                atender_hasta=atender_solicitud_hasta(db, venta),
                lineas=[
                    (
                        catalogo_politicas.describir_variante(db, original),
                        catalogo_politicas.describir_variante(db, nueva),
                        linea.cantidad,
                    )
                    for linea, _detalle, original, nueva in cambios
                ],
            )
            _despachar(mensaje, programar_envio)
            return True
        except Exception:  # noqa: BLE001 - el aviso es un extra: jamás deshace la solicitud
            logger.exception("aviso_solicitud_cambio_no_armado devolucion_id=%s", devolucion.id)
            return False

    def cancelar(
        self, db: Session, usuario_id: int, solicitud_id: int, contexto: ContextoAuditoria | None = None
    ) -> SolicitudCambioRespuesta:
        """El cliente cancela su solicitud mientras siga pendiente."""
        try:
            devolucion = self._devoluciones.obtener_bloqueado(db, solicitud_id)
            if devolucion.usuario_id != usuario_id:
                raise NoEncontradoError("Solicitud no encontrada")  # la de otra persona se ve inexistente
            _exigir_pendiente(devolucion)
            ahora = ahora_utc_naive()
            devolucion.estado = "cancelada"
            devolucion.resuelta_por_id = usuario_id
            devolucion.resuelta_en = ahora
            plataforma_politicas.registrar_bitacora_de(
                db, contexto, ENTIDAD_DEVOLUCION, devolucion.id, ACCION_CANCELAR, {"venta_id": devolucion.venta_id}
            )
            db.commit()
            db.refresh(devolucion)
        except Exception:
            db.rollback()
            raise
        venta = self._ventas.obtener(db, devolucion.venta_id)
        return construir_respuesta_solicitud(db, devolucion, venta)


class ResolverSolicitudCambio:
    """El personal de la sucursal de la venta aprueba o rechaza una solicitud pendiente (Etapa 2). El administrador
    (alcance global) puede resolver las de cualquier sucursal."""

    def __init__(self) -> None:
        self._ventas = VentaRepository()
        self._estados = EstadoVentaRepository()
        self._devoluciones = DevolucionRepository()

    def aprobar(
        self,
        db: Session,
        usuario_id: int,
        solicitud_id: int,
        contexto: ContextoAuditoria | None = None,
        programar_envio: ProgramarEnvio | None = None,
    ) -> SolicitudCambioRespuesta:
        """Entra la prenda devuelta y sale la nueva en UNA transacción, igual que un cambio registrado en la Caja.
        Sin stock de la prenda nueva (409), o con cualquier otro fallo, no cambia nada: la solicitud sigue pendiente
        para que el cajero la rechace con un motivo o la reintente."""
        try:
            devolucion, venta, resultado = self._aprobar(db, usuario_id, solicitud_id, contexto)
        except Exception:
            db.rollback()
            raise
        correo = _programar_comprobante(db, venta, devolucion, resultado, programar_envio)
        return construir_respuesta_solicitud(db, devolucion, venta, correo)

    def _aprobar(self, db: Session, usuario_id: int, solicitud_id: int, contexto: ContextoAuditoria | None):
        devolucion = self._devoluciones.obtener_bloqueado(db, solicitud_id)
        _exigir_pendiente(devolucion)
        venta = self._ventas.obtener_bloqueado(db, devolucion.venta_id)
        # Con tolerancia: el cliente solicitó dentro del plazo y llega a la tienda unas horas después.
        _exigir_venta_devolvible(
            db,
            self._estados,
            venta,
            usuario_id,
            tolerancia_horas=get_settings().solicitud_cambio_tolerancia_horas,
        )
        # Se valida OTRA VEZ lo que pudo cambiar desde que se pidió (precio, talla dada de baja, otra devolución).
        cambios = _resolver_lineas(db, venta, devolucion.detalle)
        resultado = _mover_stock(db, self._devoluciones, venta, devolucion, cambios, usuario_id, crear_filas=False)

        devolucion.estado = "aprobada"
        devolucion.resuelta_por_id = usuario_id
        devolucion.resuelta_en = ahora_utc_naive()
        plataforma_politicas.registrar_bitacora_de(
            db,
            contexto,
            ENTIDAD_DEVOLUCION,
            devolucion.id,
            ACCION_APROBAR,
            {
                "venta_id": venta.id,
                "unidades": sum(linea.cantidad for linea in devolucion.detalle),
                "cambios": len(resultado.reposiciones),
            },
        )
        db.commit()
        db.refresh(devolucion)
        return devolucion, venta, resultado

    def rechazar(
        self,
        db: Session,
        usuario_id: int,
        solicitud_id: int,
        datos: SolicitudCambioRechazar,
        contexto: ContextoAuditoria | None = None,
        programar_envio: ProgramarEnvio | None = None,
    ) -> SolicitudCambioRespuesta:
        try:
            devolucion = self._devoluciones.obtener_bloqueado(db, solicitud_id)
            _exigir_pendiente(devolucion)
            venta = self._ventas.obtener(db, devolucion.venta_id)
            plataforma_politicas.validar_acceso_sucursal(db, usuario_id, venta.sucursal_id)
            devolucion.estado = "rechazada"
            devolucion.resuelta_por_id = usuario_id
            devolucion.resuelta_en = ahora_utc_naive()
            devolucion.motivo_rechazo = datos.motivo.strip()
            # El motivo (texto libre) no se copia a la bitácora.
            plataforma_politicas.registrar_bitacora_de(
                db, contexto, ENTIDAD_DEVOLUCION, devolucion.id, ACCION_RECHAZAR, {"venta_id": venta.id}
            )
            db.commit()
            db.refresh(devolucion)
        except Exception:
            db.rollback()
            raise
        correo = self._programar_rechazo(db, venta, devolucion, programar_envio)
        return construir_respuesta_solicitud(db, devolucion, venta, correo)

    def _programar_rechazo(self, db: Session, venta, devolucion: Devolucion, programar_envio) -> bool:
        """Avisa al cliente que no se aprobó, con el motivo. Nunca lanza: el rechazo ya está confirmado."""
        try:
            if not envio_configurado():
                return False
            destinatario = destinatario_de_venta(db, venta)
            if destinatario is None:
                return False
            empresa = plataforma_politicas.obtener_empresa(db, venta.empresa_id)
            mensaje = construir_correo_solicitud_rechazada(
                para_email=destinatario[0],
                nombre=destinatario[1],
                nombre_empresa=empresa.nombre if empresa is not None else "FashionStore",
                codigo_solicitud=devolucion.codigo,
                codigo_venta=venta.codigo,
                motivo=devolucion.motivo_rechazo or "",
            )
            _despachar(mensaje, programar_envio)
            return True
        except Exception:  # noqa: BLE001
            logger.exception("aviso_rechazo_cambio_no_armado devolucion_id=%s", devolucion.id)
            return False


class ConsultarSolicitudesCambio:
    def __init__(self) -> None:
        self._ventas = VentaRepository()
        self._devoluciones = DevolucionRepository()

    def listar_mias(self, db: Session, usuario_id: int, venta_id: int | None = None) -> list[SolicitudCambioRespuesta]:
        """Las solicitudes que pidió el cliente (de una compra o de todas), la más reciente primero."""
        ventas: dict[int, object] = {}
        respuestas = []
        for devolucion in self._devoluciones.listar_solicitudes_de_usuario(db, usuario_id, venta_id):
            venta = ventas.get(devolucion.venta_id) or self._ventas.obtener(db, devolucion.venta_id)
            ventas[devolucion.venta_id] = venta
            respuestas.append(construir_respuesta_solicitud(db, devolucion, venta))
        return respuestas

    def listar_sucursal(
        self, db: Session, usuario_id: int, sucursal_id: int, estado: str | None = "pendiente"
    ) -> list[SolicitudCambioRespuesta]:
        """Las solicitudes de las ventas de una sucursal (por defecto las pendientes; `estado` None o "todas": de
        todos los estados). El personal solo ve las de su sucursal."""
        plataforma_politicas.obtener_sucursal(db, sucursal_id)  # 404 si no existe o es de otra empresa
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, sucursal_id)
        ventas: dict[int, object] = {}
        respuestas = []
        filtro = None if estado in (None, "todas") else estado
        for devolucion in self._devoluciones.listar_solicitudes_de_sucursal(db, sucursal_id, filtro):
            venta = ventas.get(devolucion.venta_id) or self._ventas.obtener(db, devolucion.venta_id)
            ventas[devolucion.venta_id] = venta
            respuestas.append(construir_respuesta_solicitud(db, devolucion, venta))
        return respuestas


# ---- Piezas compartidas por el registro en Caja y la aprobación de una solicitud ------------------------


class _ResultadoRegistro:
    """Lo que el registro deja para armar la respuesta y el correo (no se guarda en la base)."""

    def __init__(self) -> None:
        self.reposiciones: list[tuple] = []  # (línea del pedido, id de la variante devuelta, id de la nueva)
        self.lineas: list[tuple] = []  # (variante devuelta, variante nueva o None, cantidad)


def _exigir_pendiente(devolucion: Devolucion) -> None:
    if devolucion.estado != "pendiente":
        raise ConflictoError(f"La solicitud ya fue resuelta (estado: {devolucion.estado})")


def _exigir_venta_devolvible(
    db: Session, estados: EstadoVentaRepository, venta, usuario_id: int, tolerancia_horas: int = 0
) -> None:
    """La venta es de la sucursal del empleado (salvo alcance global), está pagada o entregada y sigue dentro del
    plazo de cambio (más la tolerancia al atender una solicitud)."""
    # El stock reingresa a la sucursal de la venta: solo su personal.
    plataforma_politicas.validar_acceso_sucursal(db, usuario_id, venta.sucursal_id)
    # Con el pago gateado, una venta 'pendiente_pago' nunca descontó
    # stock físico -- no hay nada real que devolver todavía.
    estado_venta = estados.obtener(db, venta.estado_id)
    if estado_venta.codigo not in ("pagada", "entregada"):
        raise DomainError(f"No se puede devolver una venta en estado '{estado_venta.codigo}'")
    # D19: pasado el plazo de la empresa (desde la fecha real de la venta) ya no
    # se acepta. Cada devolución se evalúa por separado contra esa fecha.
    exigir_plazo_cambio(db, venta, tolerancia_horas=tolerancia_horas)


def _resolver_lineas(db: Session, venta, lineas) -> list[tuple]:
    """Cada línea pedida existe en la venta y cada cambio es válido (mismo producto y precio, variante activa; 404
    si la variante nueva no es de esta empresa). `lineas` trae `venta_detalle_id`, `cantidad` y `variante_nueva_id`
    (el pedido de la Caja, la solicitud del cliente o las filas de una solicitud guardada). Devuelve
    (línea, línea de la venta, variante devuelta, variante nueva o None)."""
    detalle_por_id = {linea.id: linea for linea in venta.detalle}
    cambios = []
    for linea in lineas:
        detalle = detalle_por_id.get(linea.venta_detalle_id)
        if detalle is None:
            raise NoEncontradoError(f"La línea {linea.venta_detalle_id} no pertenece a la venta {venta.id}")
        # La prenda que se devuelve ya se vendió: aunque hoy esté dada de baja se puede devolver o cambiar. La NUEVA sí
        # debe estar activa (se vuelve a vender).
        original = catalogo_politicas.obtener_variante_aunque_este_dada_de_baja(db, detalle.variante_id)
        nueva = None
        if linea.variante_nueva_id is not None:
            nueva = catalogo_politicas.obtener_variante(db, linea.variante_nueva_id)
            validar_cambio_de_variante(original, nueva)
        cambios.append((linea, detalle, original, nueva))
    return cambios


def _mover_stock(
    db: Session,
    devoluciones: DevolucionRepository,
    venta,
    devolucion: Devolucion,
    cambios: list[tuple],
    usuario_id: int,
    *,
    crear_filas: bool,
) -> _ResultadoRegistro:
    """Reingresa lo devuelto y saca lo que se entrega en su lugar, dentro de la transacción de quien llama (no
    confirma). `crear_filas`: el registro en la Caja crea las líneas de la devolución aquí; al aprobar una solicitud
    ya existen. Con la solicitud todavía pendiente, sus líneas no cuentan como devueltas en la comprobación de
    cantidades (solo cuentan las devoluciones aprobadas)."""
    # Se bloquean TODAS las filas de stock (lo que reingresa y lo que sale) en un orden fijo.
    pares = [(detalle.variante_id, venta.sucursal_id) for _, detalle, _, _ in cambios]
    pares += [(nueva.id, venta.sucursal_id) for _, _, _, nueva in cambios if nueva is not None]
    bloquear_stock_en_orden(db, pares)

    resultado = _ResultadoRegistro()
    for linea, detalle, original, nueva in cambios:
        ya_devuelto = devoluciones.cantidad_devuelta(db, linea.venta_detalle_id)
        if ya_devuelto + linea.cantidad > detalle.cantidad:
            raise DomainError(
                f"No se puede devolver más de lo vendido en la línea {linea.venta_detalle_id} "
                f"({ya_devuelto} ya devuelto de {detalle.cantidad})"
            )

        if crear_filas:
            db.add(
                DevolucionDetalle(
                    devolucion_id=devolucion.id,
                    venta_detalle_id=detalle.id,
                    cantidad=linea.cantidad,
                    variante_nueva_id=nueva.id if nueva is not None else None,
                )
            )

        # La devolución reingresa stock (movimiento tipo 'devolucion');
        # no reabre la venta ni cambia su estado -- esta etapa no toca
        # Pagos.
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

        if nueva is not None:
            try:
                actualizar_stock_operacion(
                    db,
                    variante_id=nueva.id,
                    sucursal_id=venta.sucursal_id,
                    tipo_movimiento_codigo="venta",
                    cantidad=linea.cantidad,
                    referencia_tipo="devolucion",
                    referencia_id=devolucion.id,
                    usuario_id=usuario_id,
                    observacion="Cambio de talla o color",
                    commit=False,
                )
            except ConflictoError as exc:
                raise StockInsuficienteError(
                    "No hay stock disponible de la talla o el color elegido en esta sucursal: "
                    "el cambio no se registró.",
                    variante_id=nueva.id,
                    solicitado=linea.cantidad,
                ) from exc
            resultado.reposiciones.append((linea, original.id, nueva.id))
        resultado.lineas.append((original, nueva, linea.cantidad))
    return resultado


def _despachar(mensaje: MensajeCorreo, programar_envio: ProgramarEnvio | None) -> None:
    if programar_envio is None:
        enviar_correo_sin_romper(mensaje)
    else:
        programar_envio(enviar_correo_sin_romper, mensaje)


def _programar_comprobante(
    db: Session, venta, devolucion: Devolucion, resultado: _ResultadoRegistro, programar_envio: ProgramarEnvio | None
) -> bool:
    """Deja el comprobante por correo para después de responder. Devuelve si quedó programado. Nunca lanza: la
    devolución ya está confirmada y un correo que no se pueda armar no debe deshacerla."""
    try:
        if not envio_configurado():
            return False
        destinatario = destinatario_de_venta(db, venta)
        if destinatario is None:
            return False
        empresa = plataforma_politicas.obtener_empresa(db, venta.empresa_id)
        sucursal = plataforma_politicas.obtener_sucursal(db, venta.sucursal_id)
        mensaje = construir_correo_comprobante_devolucion(
            para_email=destinatario[0],
            nombre=destinatario[1],
            nombre_empresa=empresa.nombre if empresa is not None else "FashionStore",
            codigo_devolucion=devolucion.codigo,
            codigo_venta=venta.codigo,
            sucursal=sucursal.nombre,
            fecha=devolucion.fecha,
            lineas=[
                (
                    catalogo_politicas.describir_variante(db, original),
                    catalogo_politicas.describir_variante(db, nueva) if nueva is not None else None,
                    cantidad,
                )
                for original, nueva, cantidad in resultado.lineas
            ],
        )
        _despachar(mensaje, programar_envio)
        return True
    except Exception:  # noqa: BLE001 - el comprobante es un extra: jamás deshace la devolución
        logger.exception("comprobante_devolucion_no_armado devolucion_id=%s", devolucion.id)
        return False
