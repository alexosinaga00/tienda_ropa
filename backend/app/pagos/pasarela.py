"""Interfaz de las pasarelas de pago. Todo lo que sabe hablar con un
proveedor externo de pagos vive detrás de `PasarelaBase`. El resto del
paquete (`service.py`) solo conoce esta interfaz, nunca a la pasarela
concreta -- agregar una pasarela nueva es escribir una clase acá, no
tocar el flujo de pago/webhook/confirmación de la venta.

LibelulaGateway sigue siendo un SIMULADOR de sandbox (no hay credenciales
de Libélula configuradas). PayPalGateway ya tiene credenciales reales de
sandbox (PAYPAL_CLIENT_ID/PAYPAL_CLIENT_SECRET) y llama de verdad a la
API de PayPal (OAuth2 + Orders v2) para iniciar_pago()/consultar_estado().
El webhook (verificar_firma/interpretar_webhook) sigue siendo el HMAC de
sandbox para las dos: verificarlo de verdad con la API de PayPal
(verify-webhook-signature) necesita un PAYPAL_WEBHOOK_ID configurado en
su dashboard contra una URL pública, que este entorno local no tiene.

QrOnlineGateway es una tercera pasarela, también simulada (sin ningún
banco real detrás), pero con una pantalla de pago propia y funcional:
genera un QR de verdad que apunta a `GET /pagos/qr/{id}`, servido por
este mismo backend, en vez del link externo muerto de Libélula.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

import httpx

from app.core.config import get_settings


@dataclass(frozen=True)
class ResultadoIniciar:
    id_transaccion: str
    url_redireccion: str


@dataclass(frozen=True)
class ResultadoWebhook:
    id_transaccion: str
    estado: str  # código de estado_pago: 'aprobado' o 'rechazado'


class PasarelaBase(ABC):
    nombre: str

    @abstractmethod
    def iniciar_pago(self, *, monto: Decimal, referencia: str) -> ResultadoIniciar:
        """Arranca el pago del lado de la pasarela y devuelve el id de
        transacción y la URL a la que hay que redirigir al cliente."""
        raise NotImplementedError

    @abstractmethod
    def consultar_estado(self, id_transaccion: str) -> str:
        """Le pregunta a la pasarela el estado actual de una transacción
        (para el polling de GET /pagos/{id}/estado cuando todavía no llegó
        el webhook). Devuelve un código de estado_pago."""
        raise NotImplementedError

    @abstractmethod
    def verificar_firma(self, payload_crudo: bytes, firma: str | None) -> bool:
        """Valida que el webhook realmente venga de la pasarela antes de
        confiar en su contenido."""
        raise NotImplementedError

    @abstractmethod
    def interpretar_webhook(self, payload: dict) -> ResultadoWebhook:
        """Ya verificada la firma, extrae el id de transacción y el
        estado resultante del payload (cada pasarela lo estructura
        distinto)."""
        raise NotImplementedError


def _firmar(secreto: str, payload_crudo: bytes) -> str:
    return hmac.new(secreto.encode("utf-8"), payload_crudo, hashlib.sha256).hexdigest()


class LibelulaGateway(PasarelaBase):
    nombre = "libelula"

    def __init__(self) -> None:
        self._secreto = get_settings().libelula_webhook_secret

    def iniciar_pago(self, *, monto: Decimal, referencia: str) -> ResultadoIniciar:
        id_transaccion = f"LIB-{secrets.token_hex(8).upper()}"
        return ResultadoIniciar(
            id_transaccion=id_transaccion,
            url_redireccion=f"https://sandbox.libelula.bo/checkout/{id_transaccion}",
        )

    def consultar_estado(self, id_transaccion: str) -> str:
        # Sandbox sin servidor real detrás: sin webhook no hay forma de
        # saber que cambió, así que "sigue iniciado" es la respuesta
        # honesta (no inventa una aprobación que nunca llegó).
        return "iniciado"

    def verificar_firma(self, payload_crudo: bytes, firma: str | None) -> bool:
        if not firma:
            return False
        return hmac.compare_digest(_firmar(self._secreto, payload_crudo), firma)

    def interpretar_webhook(self, payload: dict) -> ResultadoWebhook:
        return ResultadoWebhook(id_transaccion=payload["id_transaccion"], estado=payload["estado"])


class PayPalGateway(PasarelaBase):
    """A diferencia de LibelulaGateway, esta sí llama a la API real de
    PayPal (sandbox): iniciar_pago() crea una orden de verdad en
    /v2/checkout/orders, consultar_estado() la consulta (y la captura si
    el comprador ya la aprobó del lado de PayPal pero todavía no se
    capturó el dinero)."""

    nombre = "paypal"

    def __init__(self) -> None:
        settings = get_settings()
        self._client_id = settings.paypal_client_id
        self._client_secret = settings.paypal_client_secret
        self._webhook_secret = settings.paypal_webhook_secret
        self._base_url = (
            "https://api-m.paypal.com" if settings.paypal_mode == "live" else "https://api-m.sandbox.paypal.com"
        )

    def _token(self) -> str:
        if not self._client_id or not self._client_secret:
            raise RuntimeError("PAYPAL_CLIENT_ID/PAYPAL_CLIENT_SECRET no están configurados")
        credenciales = base64.b64encode(f"{self._client_id}:{self._client_secret}".encode("utf-8")).decode("ascii")
        respuesta = httpx.post(
            f"{self._base_url}/v1/oauth2/token",
            headers={"Authorization": f"Basic {credenciales}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials"},
            timeout=15,
        )
        respuesta.raise_for_status()
        return respuesta.json()["access_token"]

    def iniciar_pago(self, *, monto: Decimal, referencia: str) -> ResultadoIniciar:
        try:
            token = self._token()
            cuerpo = {
                "intent": "CAPTURE",
                "purchase_units": [
                    {"reference_id": referencia, "amount": {"currency_code": "USD", "value": str(monto)}}
                ],
                "payment_source": {
                    "paypal": {
                        "experience_context": {
                            # Sandbox sin frontend real todavía: son URLs de
                            # vuelta de ejemplo, no rutas que existan hoy.
                            "return_url": "https://fashionstore.example.com/pago/retorno",
                            "cancel_url": "https://fashionstore.example.com/pago/cancelado",
                            # Sin esto, PayPal manda primero a la pantalla de
                            # login (pensada para quien ya tiene cuenta).
                            # GUEST_CHECKOUT lleva directo al formulario de
                            # tarjeta, sin necesidad de iniciar sesión.
                            "landing_page": "GUEST_CHECKOUT",
                            "user_action": "PAY_NOW",
                        }
                    }
                },
            }
            respuesta = httpx.post(
                f"{self._base_url}/v2/checkout/orders",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=cuerpo,
                timeout=15,
            )
            respuesta.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"No se pudo iniciar el pago con PayPal: {exc}") from exc

        datos = respuesta.json()
        # El link para redirigir al comprador se llama "payer-action" en
        # la API actual de Orders v2 ("approve" es el nombre viejo, de
        # antes de que payment_source.paypal reemplazara application_context).
        url = next((link["href"] for link in datos["links"] if link["rel"] in ("payer-action", "approve")), "")
        return ResultadoIniciar(id_transaccion=datos["id"], url_redireccion=url)

    def consultar_estado(self, id_transaccion: str) -> str:
        try:
            token = self._token()
            respuesta = httpx.get(
                f"{self._base_url}/v2/checkout/orders/{id_transaccion}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            respuesta.raise_for_status()
            estado_paypal = respuesta.json()["status"]

            if estado_paypal == "COMPLETED":
                return "aprobado"
            if estado_paypal == "APPROVED":
                # El comprador ya aprobó del lado de PayPal; hay que
                # capturar para que el dinero se mueva de verdad.
                captura = httpx.post(
                    f"{self._base_url}/v2/checkout/orders/{id_transaccion}/capture",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    timeout=15,
                )
                if captura.status_code == 201 and captura.json().get("status") == "COMPLETED":
                    return "aprobado"
                return "iniciado"
            if estado_paypal in ("VOIDED",):
                return "rechazado"
            return "iniciado"
        except httpx.HTTPError as exc:
            raise RuntimeError(f"No se pudo consultar el estado en PayPal: {exc}") from exc

    def verificar_firma(self, payload_crudo: bytes, firma: str | None) -> bool:
        if not firma:
            return False
        return hmac.compare_digest(_firmar(self._webhook_secret, payload_crudo), firma)

    def interpretar_webhook(self, payload: dict) -> ResultadoWebhook:
        return ResultadoWebhook(id_transaccion=payload["id_transaccion"], estado=payload["estado"])


class QrOnlineGateway(PasarelaBase):
    """Pasarela simulada de pago por QR: a diferencia de LibelulaGateway
    (que redirige a una URL externa que nunca existió), acá
    `url_redireccion` apunta a una pantalla que sirve nuestro propio
    backend (`GET /pagos/qr/{id_transaccion}`, ver `pagos/router.py` y
    `pagos/service.py`) con un QR de verdad y un botón "Confirmar pago".
    El QR y la pantalla son reales; lo simulado es solo que no hay ningún
    banco detrás verificando ni moviendo dinero -- mismo espíritu de
    sandbox que las otras dos pasarelas."""

    nombre = "qr_online"

    def __init__(self) -> None:
        self._secreto = get_settings().qr_online_webhook_secret

    def iniciar_pago(self, *, monto: Decimal, referencia: str) -> ResultadoIniciar:
        id_transaccion = f"QR-{secrets.token_hex(12).upper()}"
        base_url = get_settings().backend_public_url.rstrip("/")
        return ResultadoIniciar(
            id_transaccion=id_transaccion,
            url_redireccion=f"{base_url}/api/v1/pagos/qr/{id_transaccion}",
        )

    def consultar_estado(self, id_transaccion: str) -> str:
        # Igual que Libélula: sin servidor externo real, el único cambio
        # de estado posible llega por la confirmación manual del botón
        # (service.confirmar_pago_qr), no por polling activo acá.
        return "iniciado"

    def verificar_firma(self, payload_crudo: bytes, firma: str | None) -> bool:
        if not firma:
            return False
        return hmac.compare_digest(_firmar(self._secreto, payload_crudo), firma)

    def interpretar_webhook(self, payload: dict) -> ResultadoWebhook:
        return ResultadoWebhook(id_transaccion=payload["id_transaccion"], estado=payload["estado"])

    def firmar_confirmacion(self, payload_crudo: bytes) -> str:
        """No es parte de PasarelaBase: la usa únicamente
        service.confirmar_pago_qr() para firmar, del lado del servidor,
        la confirmación que dispara el botón de la pantalla QR -- así el
        secreto nunca se expone al navegador/WebView que la muestra."""
        return _firmar(self._secreto, payload_crudo)


_PASARELAS: dict[str, type[PasarelaBase]] = {
    "libelula": LibelulaGateway,
    "paypal": PayPalGateway,
    "qr_online": QrOnlineGateway,
}


def obtener_pasarela(codigo: str) -> PasarelaBase:
    clase = _PASARELAS.get(codigo)
    if clase is None:
        raise ValueError(f"No hay pasarela registrada para '{codigo}'")
    return clase()
