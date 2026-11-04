"""PayPal simulado para las pruebas: un servidor en memoria detrás de `httpx.MockTransport`.

Ninguna prueba toca PayPal de verdad. `SimuladorPayPal` sustituye el cliente HTTP de `app.core.paypal`
(`_crear_cliente`), así que el código de producción corre completo (token, cuerpo de las peticiones, cabeceras,
interpretación de la respuesta) y solo la red es falsa. Guarda las órdenes, cuenta cuántas capturas MOVIERON dinero
(`capturas`) y respeta la idempotencia de `PayPal-Request-Id` como PayPal: repetir la misma captura devuelve lo mismo
sin volver a cobrar; otra clave sobre una orden ya capturada da 422 `ORDER_ALREADY_CAPTURED`.

El comprador "aprueba" una orden con `aprobar(...)`. Para provocar fallos: `caido` (todo falla con error de red),
`caer_en` (solo esas operaciones), `monto_reportado`/`moneda_reportada` (PayPal informa otro monto u otra moneda) y
`estado_captura` (p. ej. `PENDING`)."""

from __future__ import annotations

import json
import threading
from decimal import Decimal

import httpx

from app.core import paypal
from app.core.config import get_settings


class SimuladorPayPal:
    def __init__(self, monkeypatch, *, con_credenciales: bool = True) -> None:
        self.ordenes: dict[str, dict] = {}
        self.peticiones: list[tuple[str, str]] = []  # (método, ruta)
        self.cuerpos_de_creacion: list[dict] = []
        self.cabeceras_de_captura: list[dict] = []
        self.capturas = 0  # capturas que de verdad movieron dinero
        self.peticiones_de_captura = 0  # todas las llamadas a /capture, repetidas o no
        self.caido = False
        self.caer_en: set[str] = set()  # subconjunto de {"crear", "consultar", "capturar"}
        self.monto_reportado: Decimal | None = None
        self.moneda_reportada: str | None = None
        self.estado_captura = "COMPLETED"
        self.rechazar_captura = False  # PayPal contesta 422 (INSTRUMENT_DECLINED) a cualquier captura
        self.estado_en_consulta: str | None = None  # si se fija, la consulta informa ESTE estado (carrera simulada)
        self.demora_captura = 0.0  # segundos que "tarda" la captura (para provocar carreras)
        self._numero = 0
        self._cerrojo = threading.Lock()
        if con_credenciales:
            ajustes = get_settings()
            monkeypatch.setattr(ajustes, "paypal_client_id", "cliente-simulado")
            monkeypatch.setattr(ajustes, "paypal_client_secret", "secreto-simulado")
            monkeypatch.setattr(ajustes, "paypal_mode", "sandbox")
        monkeypatch.setattr(paypal, "_crear_cliente", lambda: httpx.Client(transport=httpx.MockTransport(self._manejar)))

    # -- Lo que hace el "comprador" y lo que consultan las pruebas ------------------------------------------------

    def ultima_orden(self) -> str:
        return list(self.ordenes)[-1]

    def aprobar(self, order_id: str | None = None) -> str:
        """El comprador aprueba la orden en la pantalla de PayPal (CREATED -> APPROVED)."""
        order_id = order_id or self.ultima_orden()
        self.ordenes[order_id]["status"] = "APPROVED"
        return order_id

    def anular(self, order_id: str | None = None) -> None:
        self.ordenes[order_id or self.ultima_orden()]["status"] = "VOIDED"

    def llamadas(self, metodo: str, fragmento: str) -> int:
        return sum(1 for m, ruta in self.peticiones if m == metodo and fragmento in ruta)

    # -- El servidor falso ---------------------------------------------------------------------------------------

    def _error(self, estado: int, issue: str) -> httpx.Response:
        return httpx.Response(estado, json={"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": issue}]})

    def _importe(self, orden: dict) -> dict:
        valor = orden["amount"]["value"] if self.monto_reportado is None else str(self.monto_reportado)
        moneda = orden["amount"]["currency_code"] if self.moneda_reportada is None else self.moneda_reportada
        return {"currency_code": moneda, "value": valor}

    def _como_json(self, orden: dict) -> dict:
        cuerpo: dict = {
            "id": orden["id"],
            "status": orden["status"],
            "purchase_units": [{"reference_id": orden["reference_id"], "amount": self._importe(orden)}],
            "links": orden["links"],
        }
        if orden["status"] == "COMPLETED":
            cuerpo["purchase_units"][0]["payments"] = {
                "captures": [{"id": f"CAP-{orden['id']}", "status": orden["estado_captura"], "amount": self._importe(orden)}]
            }
        return cuerpo

    def _manejar(self, peticion: httpx.Request) -> httpx.Response:
        ruta = peticion.url.path
        metodo = peticion.method
        with self._cerrojo:
            self.peticiones.append((metodo, ruta))
        if self.caido:
            raise httpx.ConnectError("PayPal simulado caído", request=peticion)

        if ruta == "/v1/oauth2/token":
            if not peticion.headers.get("Authorization", "").startswith("Basic "):
                return httpx.Response(401, json={"error": "invalid_client"})
            return httpx.Response(200, json={"access_token": "token-simulado", "token_type": "Bearer"})

        if peticion.headers.get("Authorization") != "Bearer token-simulado":
            return httpx.Response(401, json={"name": "AUTHENTICATION_FAILURE"})

        if ruta == "/v2/checkout/orders" and metodo == "POST":
            if "crear" in self.caer_en:
                raise httpx.ConnectError("PayPal simulado caído al crear", request=peticion)
            cuerpo = json.loads(peticion.content)
            with self._cerrojo:
                self.cuerpos_de_creacion.append(cuerpo)
                self._numero += 1
                order_id = f"ORD-SIM-{self._numero:04d}"
            unidad = cuerpo["purchase_units"][0]
            self.ordenes[order_id] = {
                "id": order_id,
                "status": "CREATED",
                "reference_id": unidad["reference_id"],
                "amount": unidad["amount"],
                "request_id_captura": None,
                "estado_captura": self.estado_captura,
                "links": [
                    {"rel": "self", "href": f"https://api-m.sandbox.paypal.com/v2/checkout/orders/{order_id}"},
                    {"rel": "payer-action", "href": f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}"},
                ],
            }
            return httpx.Response(201, json={"id": order_id, "status": "CREATED", "links": self.ordenes[order_id]["links"]})

        prefijo = "/v2/checkout/orders/"
        if not ruta.startswith(prefijo):
            return httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND"})
        resto = ruta[len(prefijo):]
        if resto.endswith("/capture") and metodo == "POST":
            return self._capturar(peticion, resto[: -len("/capture")])
        if metodo == "GET":
            if "consultar" in self.caer_en:
                raise httpx.ConnectError("PayPal simulado caído al consultar", request=peticion)
            orden = self.ordenes.get(resto)
            if orden is None:
                return httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND"})
            cuerpo = self._como_json(orden)
            if self.estado_en_consulta is not None:
                cuerpo["status"] = self.estado_en_consulta
            return httpx.Response(200, json=cuerpo)
        return httpx.Response(405, json={})

    def _capturar(self, peticion: httpx.Request, order_id: str) -> httpx.Response:
        with self._cerrojo:
            self.peticiones_de_captura += 1
            self.cabeceras_de_captura.append(dict(peticion.headers))
        if "capturar" in self.caer_en:
            raise httpx.ConnectError("PayPal simulado caído al capturar", request=peticion)
        if self.rechazar_captura:
            return self._error(422, "INSTRUMENT_DECLINED")
        if self.demora_captura:
            threading.Event().wait(self.demora_captura)
        with self._cerrojo:
            orden = self.ordenes.get(order_id)
            if orden is None:
                return httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND"})
            clave = peticion.headers.get("PayPal-Request-Id")
            if orden["status"] == "COMPLETED":
                if clave and clave == orden["request_id_captura"]:  # idempotencia: el mismo resultado, sin cobrar de nuevo
                    return httpx.Response(201, json=self._como_json(orden))
                return self._error(422, "ORDER_ALREADY_CAPTURED")
            if orden["status"] != "APPROVED":
                return self._error(422, "ORDER_NOT_APPROVED")
            orden["status"] = "COMPLETED"
            orden["request_id_captura"] = clave
            orden["estado_captura"] = self.estado_captura
            self.capturas += 1
            return httpx.Response(201, json=self._como_json(orden))
