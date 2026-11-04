"""CU-17 — Gestionar devoluciones y cambios

Absorbe el antiguo CU-40 (Registrar devolución).

Actor: Cajero, Encargado de sucursal.
Precondición: la venta existe, está pagada o entregada, es de la
sucursal del empleado (salvo alcance global) y está dentro del plazo de cambio
de la empresa (24 horas por defecto, desde la fecha real de la venta).
Postcondición: la devolución queda registrada y el stock reingresa a la
sucursal. Si la línea pide un CAMBIO (`variante_nueva_id`), la variante nueva sale
del stock de la misma sucursal en la misma transacción; si no hay stock, no se
registra nada. A quien compró (si tiene correo) le llega un comprobante.

Cambio de talla o color: la variante nueva debe ser del MISMO producto y del MISMO precio, así
no hay diferencia de dinero (el reembolso todavía no existe). No hay tabla ni columna nueva: la salida de la
variante nueva queda en el kardex (movimiento `venta`, referencia `devolucion` + id) y la respuesta del registro
la informa en `reposiciones`. Una prenda recibida en un cambio no se puede volver a cambiar (la línea de la venta
ya está agotada).

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
    construir_correo_comprobante_devolucion,
    describir_plazo_cambio,
    destinatario_de_venta,
    exigir_plazo_cambio,
    obtener_comprobante,
    validar_cambio_de_variante,
)
from app.comercial.repository import DevolucionRepository, EstadoVentaRepository, VentaRepository
from app.comercial.schemas import DevolucionCrear, ReposicionRespuesta
from app.core.auditoria import ACCION_REGISTRAR, ENTIDAD_DEVOLUCION, ContextoAuditoria
from app.core.codigos import generar_codigo
from app.core.correo import MensajeCorreo, enviar_correo_sin_romper, envio_configurado
from app.core.exceptions import ConflictoError, DomainError, NoEncontradoError, StockInsuficienteError
from app.plataforma import politicas as plataforma_politicas

logger = logging.getLogger(__name__)


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
        programar_envio: Callable[[Callable[[MensajeCorreo], object], MensajeCorreo], object] | None = None,
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
            ReposicionRespuesta(
                venta_detalle_id=linea.venta_detalle_id,
                variante_devuelta_id=original_id,
                variante_nueva_id=nueva_id,
                cantidad=linea.cantidad,
            )
            for linea, original_id, nueva_id in lineas_correo.reposiciones
        ]
        devolucion.correo_programado = self._programar_comprobante(db, venta, devolucion, lineas_correo, programar_envio)
        return devolucion

    def _registrar(self, db: Session, usuario_id: int, datos: DevolucionCrear, contexto: ContextoAuditoria | None):
        # Bloqueada hasta el commit: dos devoluciones simultáneas de la misma
        # venta se ponen en fila y la segunda suma lo que la primera ya
        # devolvió (y una anulación concurrente espera a que termine).
        venta = self._ventas.obtener_bloqueado(db, datos.venta_id)
        # El stock reingresa a la sucursal de la venta: solo su personal.
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, venta.sucursal_id)

        # Con el pago gateado, una venta 'pendiente_pago' nunca descontó
        # stock físico -- no hay nada real que devolver todavía.
        estado_venta = self._estados.obtener(db, venta.estado_id)
        if estado_venta.codigo not in ("pagada", "entregada"):
            raise DomainError(f"No se puede devolver una venta en estado '{estado_venta.codigo}'")
        # D19: pasado el plazo de la empresa (desde la fecha real de la venta) ya no
        # se acepta. Cada devolución se evalúa por separado contra esa fecha.
        exigir_plazo_cambio(db, venta)

        detalle_por_id = {linea.id: linea for linea in venta.detalle}

        # Antes de escribir nada: cada línea existe y cada cambio es válido (mismo producto y precio; 404 si la
        # variante nueva no es de esta empresa).
        cambios = []  # (línea del pedido, línea de la venta, variante devuelta, variante nueva o None)
        for linea in datos.detalle:
            detalle = detalle_por_id.get(linea.venta_detalle_id)
            if detalle is None:
                raise NoEncontradoError(f"La línea {linea.venta_detalle_id} no pertenece a la venta {venta.id}")
            original = catalogo_politicas.obtener_variante(db, detalle.variante_id)
            nueva = None
            if linea.variante_nueva_id is not None:
                nueva = catalogo_politicas.obtener_variante(db, linea.variante_nueva_id)
                validar_cambio_de_variante(original, nueva)
            cambios.append((linea, detalle, original, nueva))

        devolucion = Devolucion(
            codigo=generar_codigo(db, "DEV", self._devoluciones.obtener_por_codigo),
            venta_id=venta.id,
            motivo=datos.motivo,
            estado="aprobada",  # esta etapa no tiene un flujo de aprobación aparte
            usuario_id=usuario_id,
        )
        db.add(devolucion)
        db.flush()

        # Se bloquean TODAS las filas de stock (lo que reingresa y lo que sale) en un orden fijo.
        pares = [(detalle.variante_id, venta.sucursal_id) for _, detalle, _, _ in cambios]
        pares += [(nueva.id, venta.sucursal_id) for _, _, _, nueva in cambios if nueva is not None]
        bloquear_stock_en_orden(db, pares)

        resultado = _ResultadoRegistro()
        for linea, detalle, original, nueva in cambios:
            ya_devuelto = self._devoluciones.cantidad_devuelta(db, linea.venta_detalle_id)
            if ya_devuelto + linea.cantidad > detalle.cantidad:
                raise DomainError(
                    f"No se puede devolver más de lo vendido en la línea {linea.venta_detalle_id} "
                    f"({ya_devuelto} ya devuelto de {detalle.cantidad})"
                )

            db.add(DevolucionDetalle(devolucion_id=devolucion.id, venta_detalle_id=detalle.id, cantidad=linea.cantidad))

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

    def _programar_comprobante(
        self,
        db: Session,
        venta,
        devolucion: Devolucion,
        resultado: "_ResultadoRegistro",
        programar_envio,
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
            if programar_envio is None:
                enviar_correo_sin_romper(mensaje)
            else:
                programar_envio(enviar_correo_sin_romper, mensaje)
            return True
        except Exception:  # noqa: BLE001 - el comprobante es un extra: jamás deshace la devolución
            logger.exception("comprobante_devolucion_no_armado devolucion_id=%s", devolucion.id)
            return False


class _ResultadoRegistro:
    """Lo que el registro deja para armar la respuesta y el correo (no se guarda en la base)."""

    def __init__(self) -> None:
        self.reposiciones: list[tuple] = []  # (línea del pedido, id de la variante devuelta, id de la nueva)
        self.lineas: list[tuple] = []  # (variante devuelta, variante nueva o None, cantidad)
