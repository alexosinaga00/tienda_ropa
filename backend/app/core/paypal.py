"""Cliente mínimo de la API REST de PayPal (OAuth2 + Orders v2 + Vault v3), compartido por quien cobra con PayPal.

Infraestructura transversal: NO importa ningún paquete de negocio. Lo usan `comercial.pasarela.PayPalGateway` (pago
de una venta de tienda), el PayPal guardado y el pedido sin conexión del cliente (`comercial`, CU-18 y CU-13) y la
compra de un plan (`plataforma`, CU-04). Aquí vive lo único que sabe hablar con PayPal: el token OAuth, la URL base
según `paypal_mode`, crear, consultar y capturar una orden, y guardar (Vault) el PayPal de un cliente para cobrarle
después. Quien llama decide qué hacer con el resultado.

- Cualquier fallo de red o respuesta HTTP de error se convierte en `PayPalError`, que HEREDA de `RuntimeError`:
  `cu18_procesar_pagos` captura `RuntimeError` para no romper el polling cuando la pasarela no responde.
- `capturar_orden` manda la cabecera `PayPal-Request-Id` (idempotencia: repetir la misma captura con el mismo id
  devuelve el mismo resultado y no cobra dos veces) y trata `ORDER_ALREADY_CAPTURED` como una orden ya capturada
  (la consulta y la devuelve).
- Sin credenciales (`PAYPAL_CLIENT_ID`/`PAYPAL_CLIENT_SECRET`) no hay llamada: `PayPalError`. Las pruebas jamás
  salen a la red: `tests/conftest.py` vacía las credenciales y los tests que necesitan PayPal sustituyen
  `_crear_cliente` (o las funciones de este módulo).
- Nunca se registra el cuerpo de una petición ni de una respuesta (pueden traer datos del pagador).
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

TIMEOUT_SEGUNDOS = 15
LARGO_MAXIMO_DESCRIPCION = 127  # límite de PayPal para `purchase_units[].description`

ESTADO_APROBADA = "APPROVED"
ESTADO_COMPLETADA = "COMPLETED"
ESTADO_ANULADA = "VOIDED"
PROBLEMA_YA_CAPTURADA = "ORDER_ALREADY_CAPTURED"


class PayPalError(RuntimeError):
    """PayPal no respondió o rechazó la petición.

    - `causa`: la excepción de `httpx` original (red, o estado HTTP de error); `None` si el fallo fue de configuración
      (sin credenciales) o de contenido (respuesta ilegible).
    - `status_code`: el estado HTTP con que PayPal respondió (`None` si ni siquiera hubo respuesta).
    - `problemas`: los `issue` que PayPal informa en el cuerpo del error (p. ej. `ORDER_ALREADY_CAPTURED`)."""

    def __init__(
        self,
        mensaje: str,
        *,
        causa: Exception | None = None,
        status_code: int | None = None,
        problemas: tuple[str, ...] = (),
    ) -> None:
        super().__init__(mensaje)
        self.causa = causa
        self.status_code = status_code
        self.problemas = problemas


@dataclass(frozen=True)
class OrdenCreada:
    id: str
    url_aprobacion: str  # el link `payer-action` (o el antiguo `approve`); "" si PayPal no lo trajo

    def __iter__(self):  # se desempaqueta como (id, url_aprobacion)
        yield self.id
        yield self.url_aprobacion


@dataclass(frozen=True)
class EstadoOrden:
    """La orden tal como la ve PayPal. `monto` y `moneda` salen de la CAPTURA si ya existe y, si no, de la orden;
    `estado_captura` es el de la primera captura (`COMPLETED`, `PENDING`...) o `None` si aún no se capturó."""

    id: str
    estado: str
    monto: Decimal | None
    moneda: str | None
    estado_captura: str | None = None
    # El id de la primera captura (lo necesita un reembolso); `None` si la orden todavía no se capturó.
    captura_id: str | None = None


@dataclass(frozen=True)
class ReembolsoCreado:
    """El reembolso de una captura tal como lo ve PayPal: su id y su estado (`COMPLETED`, `PENDING`, `FAILED`...)."""

    id: str
    estado: str


def url_base() -> str:
    return "https://api-m.paypal.com" if get_settings().paypal_mode == "live" else "https://api-m.sandbox.paypal.com"


def _crear_cliente() -> httpx.Client:
    """Un cliente nuevo por llamada. Las pruebas lo sustituyen por uno con `httpx.MockTransport`."""
    return httpx.Client(timeout=TIMEOUT_SEGUNDOS)


def _problemas(respuesta: httpx.Response) -> tuple[str, ...]:
    try:
        cuerpo = respuesta.json()
        return tuple(str(d["issue"]) for d in cuerpo.get("details") or [] if isinstance(d, dict) and "issue" in d)
    except (ValueError, AttributeError, TypeError):
        return ()


def _enviar(metodo: str, url: str, **kwargs: Any) -> dict:
    """Una petición. Devuelve el JSON; cualquier fallo es `PayPalError` (con la excepción de `httpx` en `causa`)."""
    try:
        with _crear_cliente() as cliente:
            respuesta = cliente.request(metodo, url, **kwargs)
            respuesta.raise_for_status()
            datos = respuesta.json()
    except httpx.HTTPStatusError as exc:
        raise PayPalError(
            f"PayPal respondió {exc.response.status_code}",
            causa=exc,
            status_code=exc.response.status_code,
            problemas=_problemas(exc.response),
        ) from exc
    except httpx.HTTPError as exc:
        raise PayPalError("No se pudo comunicar con PayPal", causa=exc) from exc
    except ValueError as exc:
        raise PayPalError("PayPal devolvió una respuesta ilegible") from exc
    if not isinstance(datos, dict):
        raise PayPalError("PayPal devolvió una respuesta inesperada")
    return datos


def obtener_token() -> str:
    """Token OAuth2 (client credentials). No se guarda en caché: cada operación pide el suyo."""
    ajustes = get_settings()
    if not ajustes.paypal_client_id or not ajustes.paypal_client_secret:
        raise PayPalError("PAYPAL_CLIENT_ID/PAYPAL_CLIENT_SECRET no están configurados")
    credenciales = base64.b64encode(f"{ajustes.paypal_client_id}:{ajustes.paypal_client_secret}".encode("utf-8"))
    datos = _enviar(
        "POST",
        f"{url_base()}/v1/oauth2/token",
        headers={"Authorization": f"Basic {credenciales.decode('ascii')}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials"},
    )
    token = datos.get("access_token")
    if not token:
        raise PayPalError("PayPal no devolvió un token de acceso")
    return str(token)


def _decimal(valor: Any) -> Decimal | None:
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return None


def _a_estado(datos: dict) -> EstadoOrden:
    unidades = datos.get("purchase_units") or [{}]
    unidad = unidades[0] if isinstance(unidades[0], dict) else {}
    capturas = (unidad.get("payments") or {}).get("captures") or []
    captura = capturas[0] if capturas and isinstance(capturas[0], dict) else None
    importe = (captura or {}).get("amount") or unidad.get("amount") or {}
    estado = datos.get("status")
    if not estado:
        raise PayPalError("PayPal no informó el estado de la orden")
    return EstadoOrden(
        id=str(datos.get("id", "")),
        estado=str(estado),
        monto=_decimal(importe.get("value")) if importe.get("value") is not None else None,
        moneda=importe.get("currency_code"),
        estado_captura=captura.get("status") if captura else None,
        captura_id=str(captura["id"]) if captura and captura.get("id") else None,
    )


def crear_orden(
    *,
    monto: Decimal,
    moneda: str,
    referencia: str,
    descripcion: str | None,
    return_url: str,
    cancel_url: str,
    request_id: str | None = None,
) -> OrdenCreada:
    """Crea una orden de PayPal (`intent=CAPTURE`) y devuelve su id y la URL a la que hay que mandar al comprador.
    `monto` se envía tal cual (`str(monto)`): quien llama lo entrega ya redondeado a 2 decimales."""
    unidad: dict[str, Any] = {"reference_id": referencia, "amount": {"currency_code": moneda, "value": str(monto)}}
    if descripcion:
        unidad["description"] = descripcion[:LARGO_MAXIMO_DESCRIPCION]
    cuerpo = {
        "intent": "CAPTURE",
        "purchase_units": [unidad],
        "payment_source": {
            "paypal": {
                "experience_context": {
                    "return_url": return_url,
                    "cancel_url": cancel_url,
                    # Sin esto PayPal manda primero a la pantalla de login (pensada para quien ya tiene cuenta).
                    # GUEST_CHECKOUT lleva directo al formulario de tarjeta, sin iniciar sesión.
                    "landing_page": "GUEST_CHECKOUT",
                    "user_action": "PAY_NOW",
                }
            }
        },
    }
    token = obtener_token()
    cabeceras = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if request_id:
        cabeceras["PayPal-Request-Id"] = request_id
    datos = _enviar("POST", f"{url_base()}/v2/checkout/orders", headers=cabeceras, json=cuerpo)
    if not datos.get("id"):
        raise PayPalError("PayPal no devolvió el id de la orden")
    # El link para redirigir al comprador se llama "payer-action" en la API actual de Orders v2 ("approve" es el
    # nombre viejo, de antes de que payment_source.paypal reemplazara application_context).
    url = next(
        (v["href"] for v in datos.get("links") or [] if isinstance(v, dict) and v.get("rel") in ("payer-action", "approve")),
        "",
    )
    return OrdenCreada(id=str(datos["id"]), url_aprobacion=url)


# ---- Vault v3: guardar el PayPal del cliente para cobrarle después ------------------------------------------------------
#
# Flujo (documentación oficial de PayPal, "Save PayPal with the Payment Method Tokens API"):
#   1. `crear_setup_token`  -> POST /v3/vault/setup-tokens. PayPal responde `status = PAYER_ACTION_REQUIRED` y un link
#      `rel = approve` al que se manda al cliente. Al volver, PayPal agrega `?approval_token_id=<id del setup token>` a
#      la `return_url`.
#   2. `crear_payment_token` -> POST /v3/vault/payment-tokens con `payment_source.token {id, type: SETUP_TOKEN}`. Responde
#      el `id` del payment token (el "vault_id" que se guarda) y, en `payment_source.paypal.email_address`, el correo.
#   3. `cobrar_con_vault`    -> POST /v2/checkout/orders con `payment_source.paypal.vault_id` (intent CAPTURE): con un token
#      de uso MERCHANT la orden sale ya COMPLETED (el ejemplo oficial); si saliera APPROVED se captura.
#   4. `borrar_payment_token` -> DELETE /v3/vault/payment-tokens/{id} (204 sin cuerpo).
# SUPOSICIONES (no probadas contra el sandbox real; todo se simula en las pruebas): `usage_pattern = UNSCHEDULED_POSTPAID`
# es un valor válido del enumerado, pero los ejemplos oficiales usan IMMEDIATE (ver `Settings.paypal_vault_usage_pattern`);
# `stored_credential` en el cobro es opcional (ver `Settings.paypal_vault_stored_credential`).

@dataclass(frozen=True)
class SetupTokenCreado:
    id: str  # es el `approval_token_id` con el que PayPal vuelve a la `return_url`
    url_aprobacion: str


@dataclass(frozen=True)
class PaymentTokenCreado:
    id: str  # el `vault_id` con el que se cobra después
    correo: str | None  # el correo de PayPal del cliente, si PayPal lo informa


def _cabeceras_json(request_id: str | None = None) -> dict[str, str]:
    cabeceras = {"Authorization": f"Bearer {obtener_token()}", "Content-Type": "application/json"}
    if request_id:
        cabeceras["PayPal-Request-Id"] = request_id
    return cabeceras


def crear_setup_token(*, return_url: str, cancel_url: str, request_id: str) -> SetupTokenCreado:
    """Pide a PayPal un setup token (la autorización pendiente del cliente) y la URL a la que hay que mandarlo."""
    cuerpo = {
        "payment_source": {
            "paypal": {
                "usage_type": "MERCHANT",
                "usage_pattern": get_settings().paypal_vault_usage_pattern,
                "customer_type": "CONSUMER",
                "experience_context": {"return_url": return_url, "cancel_url": cancel_url},
            }
        }
    }
    datos = _enviar("POST", f"{url_base()}/v3/vault/setup-tokens", headers=_cabeceras_json(request_id), json=cuerpo)
    if not datos.get("id"):
        raise PayPalError("PayPal no devolvió el id del setup token")
    url = next(
        (v["href"] for v in datos.get("links") or [] if isinstance(v, dict) and v.get("rel") in ("approve", "payer-action")),
        "",
    )
    if not url:
        raise PayPalError("PayPal no devolvió el enlace de aprobación del setup token")
    return SetupTokenCreado(id=str(datos["id"]), url_aprobacion=url)


def crear_payment_token(setup_token_id: str) -> PaymentTokenCreado:
    """Cambia un setup token que el cliente ya aprobó por el payment token definitivo. Si el cliente no aprobó (o el
    token venció) PayPal contesta con un error 4xx: `PayPalError` con `status_code`."""
    cuerpo = {"payment_source": {"token": {"id": setup_token_id, "type": "SETUP_TOKEN"}}}
    datos = _enviar("POST", f"{url_base()}/v3/vault/payment-tokens", headers=_cabeceras_json(), json=cuerpo)
    if not datos.get("id"):
        raise PayPalError("PayPal no devolvió el id del payment token")
    fuente = (datos.get("payment_source") or {}).get("paypal") or {}
    correo = fuente.get("email_address") if isinstance(fuente, dict) else None
    return PaymentTokenCreado(id=str(datos["id"]), correo=str(correo) if correo else None)


def borrar_payment_token(payment_token_id: str) -> None:
    """Revoca un payment token en PayPal (204 sin cuerpo). Aquí NO se usa `_enviar`: no hay JSON que leer."""
    token = obtener_token()
    try:
        with _crear_cliente() as cliente:
            respuesta = cliente.request(
                "DELETE",
                f"{url_base()}/v3/vault/payment-tokens/{quote(payment_token_id, safe='')}",
                headers={"Authorization": f"Bearer {token}"},
            )
            respuesta.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise PayPalError(
            f"PayPal respondió {exc.response.status_code}",
            causa=exc,
            status_code=exc.response.status_code,
            problemas=_problemas(exc.response),
        ) from exc
    except httpx.HTTPError as exc:
        raise PayPalError("No se pudo comunicar con PayPal", causa=exc) from exc


def cobrar_con_vault(
    *, vault_id: str, monto: Decimal, moneda: str, referencia: str, descripcion: str | None, request_id: str
) -> EstadoOrden:
    """Cobra `monto` al PayPal guardado (sin que el cliente esté presente). `request_id` va en `PayPal-Request-Id`: si el
    resultado se pierde y se repite la MISMA petición, PayPal devuelve la orden original sin cobrar otra vez. Una
    orden `APPROVED` se captura (con un id derivado del anterior); `COMPLETED` ya está cobrada. Cualquier otro estado
    lo interpreta quien llama (no se cobró dinero)."""
    unidad: dict[str, Any] = {"reference_id": referencia, "amount": {"currency_code": moneda, "value": str(monto)}}
    if descripcion:
        unidad["description"] = descripcion[:LARGO_MAXIMO_DESCRIPCION]
    fuente: dict[str, Any] = {"vault_id": vault_id}
    if get_settings().paypal_vault_stored_credential:
        fuente["stored_credential"] = {"payment_initiator": "MERCHANT", "payment_type": "UNSCHEDULED", "usage": "SUBSEQUENT"}
    cuerpo = {"intent": "CAPTURE", "purchase_units": [unidad], "payment_source": {"paypal": fuente}}
    datos = _enviar("POST", f"{url_base()}/v2/checkout/orders", headers=_cabeceras_json(request_id), json=cuerpo)
    if not datos.get("id"):
        raise PayPalError("PayPal no devolvió el id de la orden")
    orden = _a_estado(datos)
    if orden.estado == ESTADO_APROBADA:
        return capturar_orden(orden.id, f"{request_id}-captura")
    return orden


def obtener_orden(order_id: str) -> EstadoOrden:
    """Consulta la orden (estado, monto y moneda) directamente a PayPal."""
    token = obtener_token()
    datos = _enviar(
        "GET", f"{url_base()}/v2/checkout/orders/{quote(order_id, safe='')}", headers={"Authorization": f"Bearer {token}"}
    )
    return _a_estado(datos)


def capturar_orden(order_id: str, request_id: str | None = None, *, tratar_ya_capturada: bool = True) -> EstadoOrden:
    """Captura el dinero de una orden que el comprador ya aprobó. `request_id` va en `PayPal-Request-Id`: PayPal
    devuelve el mismo resultado si se repite con el mismo id (idempotencia). Con `tratar_ya_capturada` (por defecto),
    `ORDER_ALREADY_CAPTURED` no es un error: se consulta la orden y se devuelve tal como quedó."""
    token = obtener_token()
    cabeceras = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if request_id:
        cabeceras["PayPal-Request-Id"] = request_id
    try:
        datos = _enviar("POST", f"{url_base()}/v2/checkout/orders/{quote(order_id, safe='')}/capture", headers=cabeceras)
    except PayPalError as exc:
        if tratar_ya_capturada and PROBLEMA_YA_CAPTURADA in exc.problemas:
            logger.info("La orden de PayPal ya estaba capturada; se consulta su estado")
            return obtener_orden(order_id)
        raise
    return _a_estado(datos)


ESTADO_REEMBOLSO_COMPLETADO = "COMPLETED"
ESTADO_REEMBOLSO_PENDIENTE = "PENDING"


def reembolsar_captura(captura_id: str, *, monto: Decimal, moneda: str, request_id: str) -> ReembolsoCreado:
    """Devuelve `monto` de una captura ya cobrada (`POST /v2/payments/captures/{id}/refund`). `request_id` va en
    `PayPal-Request-Id`: si la respuesta se pierde y se repite la MISMA petición, PayPal devuelve el reembolso original y
    no devuelve el dinero dos veces. Un reembolso parcial lleva el importe; PayPal responde `COMPLETED`, `PENDING` o
    `FAILED`: lo interpreta quien llama. SUPOSICIÓN no probada contra el sandbox real (se simula en las pruebas)."""
    cuerpo = {"amount": {"currency_code": moneda, "value": str(monto)}}
    datos = _enviar(
        "POST",
        f"{url_base()}/v2/payments/captures/{quote(captura_id, safe='')}/refund",
        headers=_cabeceras_json(request_id),
        json=cuerpo,
    )
    if not datos.get("id") or not datos.get("status"):
        raise PayPalError("PayPal no informó el reembolso")
    return ReembolsoCreado(id=str(datos["id"]), estado=str(datos["status"]))
