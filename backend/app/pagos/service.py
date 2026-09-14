"""Pagos: iniciar_pago_pasarela()/pagar_en_caja() crean el `pago`;
procesar_webhook() es quien lo resuelve (aprobado/rechazado) y, recién en
ese momento, dispara ventas.service.confirmar_venta()/anular_venta() --
"solo cuando el pago pasa a aprobado se confirma la venta y se descuenta
el stock" (P5.2).

Idempotencia del webhook: cada llamada agrega su propia fila de evidencia
a `transaccion_pasarela` (eso nunca se salta, es la auditoría), pero el
efecto de negocio (confirmar/anular la venta) solo se dispara la PRIMERA
vez que un pago sale de 'iniciado'. Un webhook repetido (red flaky, la
pasarela reintentando) encuentra el pago ya resuelto y no vuelve a tocar
la venta ni el stock -- ver `_ya_resuelto` y el test/"Revisar" de curl
duplicado.
"""

from __future__ import annotations

import base64
import io
import json
from decimal import Decimal
from html import escape

import qrcode
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictoError, DomainError, NoEncontradoError, PermisoDenegadoError
from app.organizacion import service as organizacion_service
from app.pagos.models import MetodoPago, Pago, TransaccionPasarela
from app.pagos.pasarela import QrOnlineGateway, obtener_pasarela
from app.pagos.repository import EstadoPagoRepository, MetodoPagoRepository, PagoRepository, TransaccionPasarelaRepository
from app.pagos.schemas import PagoCajaRequest, PagoIniciarRequest, PagoRespuesta
from app.ventas import service as ventas_service

metodo_repo = MetodoPagoRepository()
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


def iniciar_pago_pasarela(db: Session, usuario_id: int, datos: PagoIniciarRequest) -> tuple[Pago, str]:
    ventas_service.obtener_comprobante(db, datos.venta_id, usuario_id)  # valida dueño o staff, 404 si no existe

    # Bloquea la fila de la venta ANTES de decidir si se puede iniciar un
    # pago nuevo: serializa esta validación con cualquier otro
    # iniciar_pago_pasarela/confirmar_venta/anular_venta concurrente sobre
    # la misma venta (mismo patrón de lock que inventario.service usa para
    # stock). Sin esto, dos requests casi simultáneas (doble click, retry
    # con otro método de pago) pueden pasar la validación de "sin pago
    # activo" antes de que ninguna comitee, y terminar cobrando DOS veces
    # de verdad en la pasarela externa (B-2 de la auditoría).
    venta = ventas_service.obtener_venta_bloqueada(db, datos.venta_id)
    estado_venta_actual = ventas_service.obtener_estado_codigo(db, venta.estado_id)
    if estado_venta_actual != "pendiente_pago":
        raise ConflictoError(f"La venta está '{estado_venta_actual}', no se puede iniciar un pago")

    metodo = metodo_repo.obtener_por_codigo(db, datos.metodo_pago)
    if not metodo.requiere_pasarela:
        raise DomainError(f"'{metodo.codigo}' no es un método por pasarela, usá /pagos/caja")

    estado_iniciado = estado_repo.obtener_por_codigo(db, "iniciado")
    if any(p.estado_id == estado_iniciado.id for p in pago_repo.listar_por_venta(db, venta.id)):
        raise ConflictoError("Ya hay un pago en curso para esta venta")

    pago = Pago(venta_id=venta.id, metodo_pago_id=metodo.id, estado_id=estado_iniciado.id, monto=venta.total)
    pago_repo.crear(db, pago)  # flush: pago.id ya disponible

    pasarela = obtener_pasarela(metodo.codigo)
    try:
        resultado = pasarela.iniciar_pago(monto=venta.total, referencia=venta.codigo)
    except RuntimeError as exc:
        # No deja el pago en 'iniciado' colgado si la pasarela real (p.
        # ej. PayPal) no respondió: no tiene una transacción real detrás.
        db.rollback()
        raise DomainError(str(exc)) from exc
    pago.referencia_externa = resultado.id_transaccion

    payload_envio = {"monto": str(venta.total), "referencia": venta.codigo}
    payload_respuesta = {"id_transaccion": resultado.id_transaccion, "url_redireccion": resultado.url_redireccion}
    transaccion_repo.crear(
        db,
        TransaccionPasarela(
            pago_id=pago.id,
            pasarela=metodo.codigo,
            id_transaccion=resultado.id_transaccion,
            payload_envio=payload_envio,
            payload_respuesta=payload_respuesta,
            estado="iniciado",
        ),
    )

    db.commit()
    db.refresh(pago)
    return pago, resultado.url_redireccion


def pagar_en_caja(db: Session, usuario_id: int, datos: PagoCajaRequest) -> tuple[Pago, Decimal | None]:
    empleado = organizacion_service.obtener_empleado_por_usuario(db, usuario_id)
    if empleado is None:
        raise PermisoDenegadoError("Este usuario no es un empleado, no puede cobrar en caja")

    venta = ventas_service.obtener_venta(db, datos.venta_id)
    metodo = metodo_repo.obtener_por_codigo(db, datos.metodo_pago)
    if not metodo.disponible_caja:
        raise DomainError(f"'{metodo.codigo}' no está disponible en caja")

    cambio: Decimal | None = None
    if metodo.codigo == "efectivo":
        if datos.monto_recibido is None:
            raise DomainError("El pago en efectivo necesita monto_recibido")
        if datos.monto_recibido < venta.total:
            raise DomainError(f"El monto recibido ({datos.monto_recibido}) no cubre el total ({venta.total})")
        cambio = datos.monto_recibido - venta.total

    estado_aprobado = estado_repo.obtener_por_codigo(db, "aprobado")
    pago = Pago(venta_id=venta.id, metodo_pago_id=metodo.id, estado_id=estado_aprobado.id, monto=venta.total)
    pago_repo.crear(db, pago)  # flush

    # El pago en caja se aprueba en el momento: no hay pasarela ni
    # webhook, así que acá mismo se dispara la confirmación de la venta.
    ventas_service.confirmar_venta(db, venta.id, usuario_id=usuario_id, commit=False)

    db.commit()
    db.refresh(pago)
    return pago, cambio


def _ya_resuelto(codigo_estado: str) -> bool:
    return codigo_estado != "iniciado"


def _resolver_pago(
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
    el webhook como el polling activo de obtener_estado_pago(): es el
    único lugar que decide si un resultado ya se aplicó o no (ahí vive la
    idempotencia).

    Bloquea la fila de `pago` (obtener_bloqueado) ANTES de leer su estado:
    si un webhook y un polling concurrente (o dos reintentos del mismo
    webhook) llegan casi juntos para el mismo pago, el segundo espera a
    que el primero comitee y recién ahí lee el estado ya actualizado, en
    vez de decidir con un `pago.estado_id` leído antes del commit del
    primero -- eso era lo que permitía el doble descuento de stock (B-1)."""
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
            ventas_service.confirmar_venta(db, pago.venta_id, commit=False)
        else:
            ventas_service.anular_venta(db, pago.venta_id, commit=False)
    # 'iniciado' repetido (sin novedad real): no cambia nada más.

    if commit:
        db.commit()
        db.refresh(pago)
    else:
        db.flush()
    return pago


def procesar_webhook(db: Session, pasarela_codigo: str, payload_crudo: bytes, firma: str | None) -> Pago:
    # `pasarela_codigo` viene de la URL (path param), sin validar contra
    # la base -- a diferencia de iniciar_pago_pasarela, que ya lo saca de
    # un metodo_pago existente. Acá si no es una pasarela real, es un 404,
    # no un error 500.
    try:
        pasarela = obtener_pasarela(pasarela_codigo)
    except ValueError as exc:
        raise NoEncontradoError(f"No existe la pasarela '{pasarela_codigo}'") from exc

    if not pasarela.verificar_firma(payload_crudo, firma):
        raise PermisoDenegadoError("Firma de webhook inválida")

    try:
        payload = json.loads(payload_crudo)
    except json.JSONDecodeError as exc:
        raise DomainError("El body del webhook no es JSON válido") from exc

    resultado = pasarela.interpretar_webhook(payload)

    transaccion_original = transaccion_repo.obtener_por_id_transaccion(db, pasarela_codigo, resultado.id_transaccion)
    if transaccion_original is None:
        raise NoEncontradoError(f"No hay ningún pago iniciado con id_transaccion '{resultado.id_transaccion}'")

    return _resolver_pago(
        db,
        transaccion_original.pago_id,
        pasarela_codigo=pasarela_codigo,
        id_transaccion=resultado.id_transaccion,
        estado_resultado=resultado.estado,
        payload_respuesta=payload,
        commit=True,
    )


def obtener_estado_pago(db: Session, usuario_id: int, pago_id: int) -> Pago:
    pago = pago_repo.obtener(db, pago_id)
    ventas_service.obtener_comprobante(db, pago.venta_id, usuario_id)  # valida dueño o staff, 404 si no existe

    estado_actual = estado_repo.obtener(db, pago.estado_id)
    if estado_actual.codigo != "iniciado":
        return pago

    # Todavía no llegó (o nunca llegó) el webhook: pregunta activamente a
    # la pasarela, por si acá se enteran antes que por webhook.
    primera = db.scalar(
        select(TransaccionPasarela)
        .where(TransaccionPasarela.pago_id == pago.id)
        .order_by(TransaccionPasarela.creado_en.asc())
        .limit(1)
    )
    if primera is None or primera.id_transaccion is None:
        return pago

    pasarela = obtener_pasarela(primera.pasarela)
    try:
        estado_pasarela = pasarela.consultar_estado(primera.id_transaccion)
    except RuntimeError:
        # Best-effort: si la pasarela real no responde ahora, se devuelve
        # el último estado guardado en vez de romper el polling del cliente.
        return pago
    if estado_pasarela == "iniciado":
        return pago  # sin novedad

    return _resolver_pago(
        db,
        pago.id,
        pasarela_codigo=primera.pasarela,
        id_transaccion=primera.id_transaccion,
        estado_resultado=estado_pasarela,
        payload_respuesta={"origen": "consultar_estado", "estado": estado_pasarela},
        commit=True,
    )


def anular_pago(db: Session, pago_id: int) -> Pago:
    """El permiso ('pagos.gestionar') ya lo gatea el router, como el
    resto de las acciones de staff en este proyecto -- acá no se
    revalida."""
    pago = pago_repo.obtener_bloqueado(db, pago_id)  # mismo lock que _resolver_pago: evita pisar un webhook concurrente
    estado_actual = estado_repo.obtener(db, pago.estado_id)
    if estado_actual.codigo != "aprobado":
        raise ConflictoError(f"Solo se puede anular un pago 'aprobado' (está '{estado_actual.codigo}')")

    estado_reembolsado = estado_repo.obtener_por_codigo(db, "reembolsado")
    pago.estado_id = estado_reembolsado.id

    ventas_service.anular_venta(db, pago.venta_id, commit=False)

    db.commit()
    db.refresh(pago)
    return pago


# ---- QR online: pantalla pública de "pago" -----------------------------------
# Sin autenticación JWT en ninguna de las dos funciones de acá: el
# id_transaccion (128 bits, ver QrOnlineGateway.iniciar_pago) es el único
# requisito para verlas/usarlas, igual modelo de confianza que un link de
# pago o que el propio webhook de las otras pasarelas.

_URL_RETORNO_SANDBOX = "https://fashionstore.example.com/pago/retorno"


def _generar_qr_base64(contenido: str) -> str:
    imagen = qrcode.make(contenido)
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _plantilla_pantalla_qr(*, id_transaccion: str, monto: Decimal, imagen_qr_base64: str, ya_resuelto: bool, estado_codigo: str) -> str:
    if ya_resuelto:
        cuerpo_accion = (
            f'<p class="estado">Este pago ya quedó registrado como <strong>{escape(estado_codigo)}</strong>. '
            "Podés cerrar esta pantalla.</p>"
        )
    else:
        cuerpo_accion = f"""
        <button id="btn-confirmar" onclick="confirmar()">Confirmar pago</button>
        <p id="mensaje" class="estado"></p>
        <script>
          function confirmar() {{
            const boton = document.getElementById('btn-confirmar');
            const mensaje = document.getElementById('mensaje');
            boton.disabled = true;
            boton.textContent = 'Confirmando...';
            fetch(window.location.pathname + '/confirmar', {{ method: 'POST' }})
              .then((resp) => {{
                if (!resp.ok) throw new Error('fallo');
                mensaje.textContent = '¡Pago confirmado! Ya podés volver a la aplicación.';
                setTimeout(() => {{ window.location.href = '{_URL_RETORNO_SANDBOX}'; }}, 1200);
              }})
              .catch(() => {{
                boton.disabled = false;
                boton.textContent = 'Confirmar pago';
                mensaje.textContent = 'No se pudo confirmar. Probá de nuevo.';
              }});
          }}
        </script>
        """
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pagar con QR - FashionStore</title>
<style>
  body {{ background: #EAE4DA; color: #1C1713; font-family: system-ui, sans-serif;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 16px; }}
  .tarjeta {{ background: #FFFFFF; border: 1px solid #DBD0C1; border-radius: 18px;
             padding: 32px; max-width: 360px; width: 100%; text-align: center; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .monto {{ font-size: 28px; font-weight: 700; margin: 4px 0 20px; }}
  img {{ width: 220px; height: 220px; margin-bottom: 20px; }}
  button {{ background: #9A3E1F; color: #fff; border: none; border-radius: 6px;
           padding: 12px 24px; font-size: 16px; cursor: pointer; width: 100%; }}
  button:disabled {{ opacity: .6; cursor: default; }}
  .estado {{ color: #6E6156; font-size: 14px; margin-top: 12px; }}
  .transaccion {{ color: #C7BCAC; font-size: 11px; margin-top: 20px; }}
</style>
</head>
<body>
  <div class="tarjeta">
    <h1>Pagar con QR</h1>
    <div class="monto">Bs {escape(str(monto))}</div>
    <img src="data:image/png;base64,{imagen_qr_base64}" alt="Código QR de pago">
    {cuerpo_accion}
    <div class="transaccion">{escape(id_transaccion)}</div>
  </div>
</body>
</html>"""


def renderizar_pantalla_qr(db: Session, id_transaccion: str) -> str:
    """GET /pagos/qr/{id}: pantalla pública (sin login) con el QR y el
    botón de confirmar. El QR codifica esta misma URL -- se puede abrir
    directo (mismo dispositivo del checkout) o escanear con otro celular."""
    transaccion = transaccion_repo.obtener_por_id_transaccion(db, "qr_online", id_transaccion)
    if transaccion is None:
        raise NoEncontradoError("Transacción QR no encontrada")
    pago = pago_repo.obtener(db, transaccion.pago_id)
    estado = estado_repo.obtener(db, pago.estado_id)

    base_url = get_settings().backend_public_url.rstrip("/")
    url_pantalla = f"{base_url}/api/v1/pagos/qr/{id_transaccion}"

    return _plantilla_pantalla_qr(
        id_transaccion=id_transaccion,
        monto=pago.monto,
        imagen_qr_base64=_generar_qr_base64(url_pantalla),
        ya_resuelto=estado.codigo != "iniciado",
        estado_codigo=estado.codigo,
    )


def confirmar_pago_qr(db: Session, id_transaccion: str) -> Pago:
    """POST /pagos/qr/{id}/confirmar: lo llama el botón de la pantalla de
    arriba. Arma el mismo payload+firma que mandaría un webhook real y lo
    procesa por procesar_webhook(): reusa toda la idempotencia/auditoría
    ya probada para Libélula/PayPal en vez de duplicar la resolución acá."""
    payload = json.dumps({"id_transaccion": id_transaccion, "estado": "aprobado"}).encode("utf-8")
    firma = QrOnlineGateway().firmar_confirmacion(payload)
    return procesar_webhook(db, "qr_online", payload, firma)
