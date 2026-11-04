"""Cliente mínimo de la API REST de PayPal (OAuth2 + Orders v2), compartido por quien cobra con PayPal.

Infraestructura transversal: NO importa ningún paquete de negocio. Lo usan `comercial.pasarela.PayPalGateway` (pago
de una venta de tienda) y la compra de un plan (`plataforma`, CU-04). Aquí vive lo único que sabe hablar con PayPal:
el token OAuth, la URL base según `paypal_mode`, y crear, consultar y capturar una orden. Quien llama decide qué
hacer con el resultado.

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
