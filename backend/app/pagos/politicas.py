"""Operaciones internas del paquete `pagos`, compartidas por más de un
caso de uso:
- `resolver_pago` (antes `_resolver_pago`): aplica el resultado de un pago
  (aprobado/rechazado) UNA sola vez -- la usan CU-31 (webhook, polling y
  la pantalla QR) y `cerrar_pagos_iniciados`.
- `cerrar_pagos_iniciados`/`cancelar_venta_pendiente`: las usan CU-29 (al
  reintentar o cancelar una compra) y `expirar_ventas_pendientes`.
- `expirar_ventas_pendientes`: tarea programada sin actor humano, la
  dispara la tarea periódica de `app/main.py`.
- `construir_pago_respuesta`: para que el router arme PagoRespuesta sin
  consultar `estado_pago`/`metodo_pago` directamente, sin importar qué CU
  atendió la petición.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictoError
from app.pagos.models import MetodoPago, Pago, TransaccionPasarela
from app.pagos.pasarela import obtener_pasarela
from app.pagos.repository import EstadoPagoRepository, PagoRepository, TransaccionPasarelaRepository
from app.pagos.schemas import PagoRespuesta
from app.ventas.politicas import (
    anular_venta,
    confirmar_venta,
    es_venta_pendiente,
    listar_ventas_pendientes_vencidas,
    obtener_estado_codigo,
    obtener_venta_bloqueada,
)

logger = logging.getLogger(__name__)

estado_repo = EstadoPagoRepository()
pago_repo = PagoRepository()
transaccion_repo = TransaccionPasarelaRepository()


def construir_pago_respuesta(db: Session, pago: Pago) -> PagoRespuesta:
    """Para que el router arme PagoRespuesta sin consultar `estado_pago`/
    `metodo_pago` directamente."""
    estado = estado_repo.obtener(db, pago.estado_id)
    metodo = db.get(MetodoPago, pago.metodo_pago_id)
    return PagoRespuesta(
        id=pago.id,
        venta_id=pago.venta_id,
        monto=pago.monto,
        referencia_externa=pago.referencia_externa,
        fecha=pago.fecha,
        metodo_pago=metodo.codigo if metodo else "",
        estado=estado.codigo,
    )


def primera_transaccion(db: Session, pago_id: int) -> TransaccionPasarela | None:
    """La transacción que dejó CU-29 al iniciar el pago: de ahí salen la
    pasarela y el id de transacción para consultarla."""
    return db.scalar(
        select(TransaccionPasarela)
        .where(TransaccionPasarela.pago_id == pago_id)
        .order_by(TransaccionPasarela.creado_en.asc())
        .limit(1)
    )


def _abandonar_pago(db: Session, pago: Pago, *, pasarela_codigo: str, motivo: str) -> None:
    """Marca 'rechazado' un pago 'iniciado' que nunca se completó. A
    diferencia de `resolver_pago(rechazado)`, NO toca la venta: quien
    llama decide si se reintenta (sigue 'pendiente_pago') o se cancela."""
    pago = pago_repo.obtener_bloqueado(db, pago.id)
    pago.estado_id = estado_repo.obtener_por_codigo(db, "rechazado").id
    transaccion_repo.crear(
        db,
        TransaccionPasarela(
            pago_id=pago.id,
            pasarela=pasarela_codigo,
            id_transaccion=pago.referencia_externa,
            payload_envio=None,
            payload_respuesta={"origen": motivo},
            estado="rechazado",
        ),
    )


def cerrar_pagos_iniciados(db: Session, venta_id: int, *, motivo: str) -> bool:
    """Cierra los pagos 'iniciado' de una venta antes de reintentar o
    cancelar. A cada uno se le pregunta primero a la pasarela: si ya cobró,
    se aplica esa aprobación (confirma la venta, commit) y devuelve True
    para que quien llama NO inicie un segundo cobro ni anule una venta
    pagada. Si no cobró (o la pasarela no responde), el pago se abandona."""
    estado_iniciado = estado_repo.obtener_por_codigo(db, "iniciado")
    for previo in pago_repo.listar_por_venta(db, venta_id):
        if previo.estado_id != estado_iniciado.id:
            continue
        primera = primera_transaccion(db, previo.id)
        estado_pasarela = "iniciado"
        if primera is not None and primera.id_transaccion is not None:
            try:
                estado_pasarela = obtener_pasarela(primera.pasarela).consultar_estado(primera.id_transaccion)
            except RuntimeError:
                estado_pasarela = "iniciado"
        if estado_pasarela == "aprobado":
            resolver_pago(
                db,
                previo.id,
                pasarela_codigo=primera.pasarela,
                id_transaccion=primera.id_transaccion,
                estado_resultado="aprobado",
                payload_respuesta={"origen": "consultar_estado", "estado": "aprobado"},
                commit=True,
            )
            return True
        metodo = db.get(MetodoPago, previo.metodo_pago_id)
        _abandonar_pago(db, previo, pasarela_codigo=primera.pasarela if primera else metodo.codigo, motivo=motivo)
    return False


def cancelar_venta_pendiente(db: Session, venta_id: int, *, motivo: str) -> None:
    venta = obtener_venta_bloqueada(db, venta_id)
    estado_venta = obtener_estado_codigo(db, venta.estado_id)
    if estado_venta != "pendiente_pago":
        raise ConflictoError(f"La venta está '{estado_venta}', no se puede cancelar")
    if cerrar_pagos_iniciados(db, venta.id, motivo=motivo):
        raise ConflictoError("Esta venta ya fue pagada")
    anular_venta(db, venta.id, commit=False, restaurar_carrito=True)
    db.commit()


def expirar_ventas_pendientes(db: Session) -> dict[str, int]:
    """Vence las ventas que siguen 'pendiente_pago' pasado
    VENTA_PENDIENTE_MINUTOS. No es un caso de uso del catálogo (no tiene
    actor humano): la dispara la tarea periódica de `app/main.py`. Cada
    venta es su propia transacción: una que falle no frena al resto. Si la
    pasarela sí había cobrado, la venta queda pagada en vez de anulada."""
    anuladas = pagadas = 0
    for venta_id in listar_ventas_pendientes_vencidas(db, get_settings().venta_pendiente_minutos):
        try:
            cancelar_venta_pendiente(db, venta_id, motivo="vencido")
            anuladas += 1
        except ConflictoError:
            db.rollback()
            if not es_venta_pendiente(db, venta_id):
                pagadas += 1
        except Exception:
            db.rollback()
            logger.exception("No se pudo vencer la venta %s", venta_id)
    return {"anuladas": anuladas, "pagadas": pagadas}


def _ya_resuelto(codigo_estado: str) -> bool:
    return codigo_estado != "iniciado"


def resolver_pago(
    db: Session,
    pago_id: int,
    *,
    pasarela_codigo: str,
    id_transaccion: str | None,
    estado_resultado: str,
    payload_respuesta: dict,
    commit: bool,
) -> Pago:
    """Registra la evidencia y, si el pago todavía estaba 'iniciado',
    aplica el resultado (aprobado/rechazado) UNA sola vez. La usan tanto
    el webhook como el polling activo y la pantalla QR (todo CU-31): es el
    único lugar que decide si un resultado ya se aplicó o no (ahí vive la
    idempotencia).

    Bloquea la fila de `pago` (obtener_bloqueado) ANTES de leer su estado:
    si un webhook y un polling concurrente (o dos reintentos del mismo
    webhook) llegan casi juntos para el mismo pago, el segundo espera a
    que el primero comitee y recién ahí lee el estado ya actualizado, en
    vez de decidir con un `pago.estado_id` leído antes del commit del
    primero -- eso era lo que permitía el doble descuento de stock."""
    pago = pago_repo.obtener_bloqueado(db, pago_id)
    estado_actual = estado_repo.obtener(db, pago.estado_id)

    transaccion_repo.crear(
        db,
        TransaccionPasarela(
            pago_id=pago.id,
            pasarela=pasarela_codigo,
            id_transaccion=id_transaccion,
            payload_envio=None,
            payload_respuesta=payload_respuesta,
            estado=estado_resultado,
        ),
    )

    if _ya_resuelto(estado_actual.codigo):
        # Idempotencia: este pago ya salió de 'iniciado' antes. No se
        # vuelve a confirmar/anular la venta ni a tocar el stock.
        if commit:
            db.commit()
            db.refresh(pago)
        else:
            db.flush()
        return pago

    if estado_resultado in ("aprobado", "rechazado"):
        estado_nuevo = estado_repo.obtener_por_codigo(db, estado_resultado)
        pago.estado_id = estado_nuevo.id
        if estado_resultado == "aprobado":
            confirmar_venta(db, pago.venta_id, commit=False)
        else:
            anular_venta(db, pago.venta_id, commit=False, restaurar_carrito=True)
    # 'iniciado' repetido (sin novedad real): no cambia nada más.

    if commit:
        db.commit()
        db.refresh(pago)
    else:
        db.flush()
    return pago
