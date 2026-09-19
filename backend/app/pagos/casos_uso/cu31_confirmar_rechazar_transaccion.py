"""CU-31 — Confirmar o rechazar transacción

Actor: Sistema de pagos (actor externo).
Precondición: existe un pago en estado 'iniciado' con esa referencia de
pasarela.
Postcondición: el pago queda aprobado o rechazado; si se aprueba, la
venta se confirma (y se descuenta el stock); si se rechaza, se anula.

Caso de uso COMPUESTO: agrupa el webhook real (Libélula/PayPal), el
polling activo de estado, la pantalla QR sandbox (que reusa el mismo
webhook para no duplicar la resolución) y anular/reembolsar un pago ya
aprobado -- todas formas de resolver o revertir el estado de una
transacción.
"""

import base64
import io
import json
from decimal import Decimal
from html import escape

import qrcode
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictoError, NoEncontradoError, PermisoDenegadoError
from app.organizacion import politicas as organizacion_politicas
from app.pagos.models import Pago
from app.pagos.pasarela import QrOnlineGateway, obtener_pasarela
from app.pagos.politicas import primera_transaccion, resolver_pago
from app.pagos.repository import EstadoPagoRepository, PagoRepository, TransaccionPasarelaRepository
from app.ventas.politicas import anular_venta, obtener_comprobante, obtener_venta

_URL_RETORNO_SANDBOX = "https://fashionstore.example.com/pago/retorno"


class ConfirmarRechazarTransaccion:
    def __init__(self) -> None:
        self._estados = EstadoPagoRepository()
        self._pagos = PagoRepository()
        self._transacciones = TransaccionPasarelaRepository()

    def procesar_webhook(self, db: Session, pasarela_codigo: str, payload_crudo: bytes, firma: str | None) -> Pago:
        # `pasarela_codigo` viene de la URL (path param), sin validar contra
        # la base -- a diferencia de CU-29, que ya lo saca de un
        # metodo_pago existente. Acá si no es una pasarela real, es un 404,
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
            raise ConflictoError("El body del webhook no es JSON válido") from exc

        resultado = pasarela.interpretar_webhook(payload)

        transaccion_original = self._transacciones.obtener_por_id_transaccion(
            db, pasarela_codigo, resultado.id_transaccion
        )
        if transaccion_original is None:
            raise NoEncontradoError(f"No hay ningún pago iniciado con id_transaccion '{resultado.id_transaccion}'")

        return resolver_pago(
            db,
            transaccion_original.pago_id,
            pasarela_codigo=pasarela_codigo,
            id_transaccion=resultado.id_transaccion,
            estado_resultado=resultado.estado,
            payload_respuesta=payload,
            commit=True,
        )

    def obtener_estado(self, db: Session, usuario_id: int, pago_id: int) -> Pago:
        pago = self._pagos.obtener(db, pago_id)
        obtener_comprobante(db, pago.venta_id, usuario_id)  # valida dueño o staff, 404 si no existe

        estado_actual = self._estados.obtener(db, pago.estado_id)
        if estado_actual.codigo != "iniciado":
            return pago

        # Todavía no llegó (o nunca llegó) el webhook: pregunta activamente
        # a la pasarela, por si acá se enteran antes que por webhook.
        primera = primera_transaccion(db, pago.id)
        if primera is None or primera.id_transaccion is None:
            return pago

        pasarela = obtener_pasarela(primera.pasarela)
        try:
            estado_pasarela = pasarela.consultar_estado(primera.id_transaccion)
        except RuntimeError:
            # Best-effort: si la pasarela real no responde ahora, se
            # devuelve el último estado guardado en vez de romper el
            # polling del cliente.
            return pago
        if estado_pasarela == "iniciado":
            return pago  # sin novedad

        return resolver_pago(
            db,
            pago.id,
            pasarela_codigo=primera.pasarela,
            id_transaccion=primera.id_transaccion,
            estado_resultado=estado_pasarela,
            payload_respuesta={"origen": "consultar_estado", "estado": estado_pasarela},
            commit=True,
        )

    def anular(self, db: Session, usuario_id: int, pago_id: int) -> Pago:
        """El permiso ('pagos.gestionar') ya lo gatea el router, como el
        resto de las acciones de staff en este proyecto -- acá no se
        revalida. Sí se valida que la venta sea de la sucursal del empleado
        (anular reingresa stock en esa sucursal)."""
        pago = self._pagos.obtener_bloqueado(db, pago_id)  # mismo lock que resolver_pago: evita pisar un webhook concurrente
        organizacion_politicas.validar_acceso_sucursal(db, usuario_id, obtener_venta(db, pago.venta_id).sucursal_id)
        estado_actual = self._estados.obtener(db, pago.estado_id)
        if estado_actual.codigo != "aprobado":
            raise ConflictoError(f"Solo se puede anular un pago 'aprobado' (está '{estado_actual.codigo}')")

        estado_reembolsado = self._estados.obtener_por_codigo(db, "reembolsado")
        pago.estado_id = estado_reembolsado.id

        anular_venta(db, pago.venta_id, commit=False)

        db.commit()
        db.refresh(pago)
        return pago

    # ---- QR online: pantalla pública de "pago" -----------------------------
    # Sin autenticación JWT en ninguna de las dos funciones de acá: el
    # id_transaccion (128 bits, ver QrOnlineGateway.iniciar_pago) es el
    # único requisito para verlas/usarlas, igual modelo de confianza que un
    # link de pago o que el propio webhook de las otras pasarelas.

    def _generar_qr_base64(self, contenido: str) -> str:
        imagen = qrcode.make(contenido)
        buffer = io.BytesIO()
        imagen.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def _plantilla_pantalla_qr(
        self, *, id_transaccion: str, monto: Decimal, imagen_qr_base64: str, ya_resuelto: bool, estado_codigo: str
    ) -> str:
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

    def renderizar_pantalla_qr(self, db: Session, id_transaccion: str) -> str:
        """GET /pagos/qr/{id}: pantalla pública (sin login) con el QR y el
        botón de confirmar. El QR codifica esta misma URL -- se puede abrir
        directo (mismo dispositivo del checkout) o escanear con otro
        celular."""
        transaccion = self._transacciones.obtener_por_id_transaccion(db, "qr_online", id_transaccion)
        if transaccion is None:
            raise NoEncontradoError("Transacción QR no encontrada")
        pago = self._pagos.obtener(db, transaccion.pago_id)
        estado = self._estados.obtener(db, pago.estado_id)

        base_url = get_settings().backend_public_url.rstrip("/")
        url_pantalla = f"{base_url}/api/v1/pagos/qr/{id_transaccion}"

        return self._plantilla_pantalla_qr(
            id_transaccion=id_transaccion,
            monto=pago.monto,
            imagen_qr_base64=self._generar_qr_base64(url_pantalla),
            ya_resuelto=estado.codigo != "iniciado",
            estado_codigo=estado.codigo,
        )

    def confirmar_pago_qr(self, db: Session, id_transaccion: str) -> Pago:
        """POST /pagos/qr/{id}/confirmar: lo llama el botón de la pantalla
        de arriba. Arma el mismo payload+firma que mandaría un webhook real
        y lo procesa por procesar_webhook(): reusa toda la idempotencia/
        auditoría ya probada para Libélula/PayPal en vez de duplicar la
        resolución acá."""
        payload = json.dumps({"id_transaccion": id_transaccion, "estado": "aprobado"}).encode("utf-8")
        firma = QrOnlineGateway().firmar_confirmacion(payload)
        return self.procesar_webhook(db, "qr_online", payload, firma)
