"""PayPal simulado para las pruebas: un servidor en memoria detrás de `httpx.MockTransport`.

Ninguna prueba toca PayPal de verdad. `SimuladorPayPal` sustituye el cliente HTTP de `app.core.paypal`
(`_crear_cliente`), así que el código de producción corre completo (token, cuerpo de las peticiones, cabeceras,
interpretación de la respuesta) y solo la red es falsa. Guarda las órdenes, cuenta cuántas capturas MOVIERON dinero
(`capturas`) y respeta la idempotencia de `PayPal-Request-Id` como PayPal: repetir la misma captura devuelve lo mismo
sin volver a cobrar; otra clave sobre una orden ya capturada da 422 `ORDER_ALREADY_CAPTURED`.

El comprador "aprueba" una orden con `aprobar(...)`. Para provocar fallos: `caido` (todo falla con error de red),
`caer_en` (solo esas operaciones), `monto_reportado`/`moneda_reportada` (PayPal informa otro monto u otra moneda) y
`estado_captura` (p. ej. `PENDING`).

También simula el Vault v3 (guardar el PayPal del cliente: setup token, payment token y borrarlo) y el cobro con el
token guardado (`payment_source.paypal.vault_id`), con `PayPal-Request-Id` idempotente: ver `setup_tokens`,
`payment_tokens`, `cobros_vault`, `rechazar_cobro_vault` y `perder_respuestas_de_cobro`."""

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
        # -- Vault v3 (PayPal guardado) y cobro con el token guardado --
        self.setup_tokens: dict[str, dict] = {}  # id -> {"aprobado": bool, "usado": bool, "cuerpo": dict}
        self.payment_tokens: dict[str, dict] = {}  # id -> {"activo": bool, "correo": str}
        self.correo_paypal: str | None = "juan.perez@gmail.com"  # el correo que PayPal informa al guardar
        self.aprobar_setup_al_crear = True  # el "cliente" aprueba en PayPal apenas se crea el setup token
        self.tokens_borrados: list[str] = []
        self.cuerpos_de_cobro_vault: list[dict] = []
        self.cabeceras_de_cobro_vault: list[dict] = []
        self.cobros_vault = 0  # cobros con vault_id que de verdad movieron dinero
        self.estado_cobro_vault = "COMPLETED"  # lo que PayPal responde al crear la orden con vault_id
        self.rechazar_cobro_vault: str | None = None  # p. ej. "INSTRUMENT_DECLINED": 422 con ese issue
        self.estado_http_cobro_vault: int = 422  # el estado con que se rechaza
        self.perder_respuestas_de_cobro = 0  # veces que el cobro SE HACE pero la respuesta se pierde (error de red)
        self._respuestas_de_cobro: dict[str, tuple[dict, dict]] = {}  # PayPal-Request-Id -> (cuerpo, respuesta)
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

        if ruta == "/v3/vault/setup-tokens" and metodo == "POST":
            return self._crear_setup_token(peticion)
        if ruta == "/v3/vault/payment-tokens" and metodo == "POST":
            return self._crear_payment_token(peticion)
        if ruta.startswith("/v3/vault/payment-tokens/") and metodo == "DELETE":
            return self._borrar_payment_token(peticion, ruta.rsplit("/", 1)[1])

        if ruta == "/v2/checkout/orders" and metodo == "POST":
            if "crear" in self.caer_en:
                raise httpx.ConnectError("PayPal simulado caído al crear", request=peticion)
            cuerpo = json.loads(peticion.content)
            if (cuerpo.get("payment_source", {}).get("paypal") or {}).get("vault_id"):
                return self._cobrar_con_vault(peticion, cuerpo)
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

    # -- Vault v3: guardar el PayPal del cliente -------------------------------------------------------------------

    def aprobar_setup(self, setup_id: str | None = None) -> str:
        """El cliente aprueba en la pantalla de PayPal (el setup token pasa a poder cambiarse por el payment token)."""
        setup_id = setup_id or list(self.setup_tokens)[-1]
        self.setup_tokens[setup_id]["aprobado"] = True
        return setup_id

    def ultimo_payment_token(self) -> str:
        return list(self.payment_tokens)[-1]

    def _crear_setup_token(self, peticion: httpx.Request) -> httpx.Response:
        if "setup" in self.caer_en:
            raise httpx.ConnectError("PayPal simulado caído al crear el setup token", request=peticion)
        cuerpo = json.loads(peticion.content)
        with self._cerrojo:
            self._numero += 1
            setup_id = f"ST-SIM-{self._numero:04d}"
            self.setup_tokens[setup_id] = {"aprobado": self.aprobar_setup_al_crear, "usado": False, "cuerpo": cuerpo}
        return httpx.Response(
            200,
            json={
                "id": setup_id,
                "status": "PAYER_ACTION_REQUIRED",
                "links": [
                    {"rel": "self", "href": f"https://api-m.sandbox.paypal.com/v3/vault/setup-tokens/{setup_id}"},
                    {"rel": "approve", "href": f"https://sandbox.paypal.com/agreements/approve?approval_session_id={setup_id}"},
                ],
            },
        )

    def _crear_payment_token(self, peticion: httpx.Request) -> httpx.Response:
        if "token" in self.caer_en:
            raise httpx.ConnectError("PayPal simulado caído al crear el payment token", request=peticion)
        fuente = json.loads(peticion.content)["payment_source"]["token"]
        with self._cerrojo:
            setup = self.setup_tokens.get(fuente["id"])
            if fuente.get("type") != "SETUP_TOKEN" or setup is None:
                return httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND", "details": [{"issue": "INVALID_RESOURCE_ID"}]})
            if setup["usado"]:
                return self._error(422, "SETUP_TOKEN_ALREADY_USED")
            if not setup["aprobado"]:
                return self._error(422, "SETUP_TOKEN_NOT_APPROVED")
            setup["usado"] = True
            self._numero += 1
            payment_id = f"VAULT-SIM-{self._numero:04d}"
            self.payment_tokens[payment_id] = {"activo": True, "correo": self.correo_paypal}
        paypal_fuente: dict = {"usage_type": "MERCHANT", "payer_id": "PAYER-SIM"}
        if self.correo_paypal:
            paypal_fuente["email_address"] = self.correo_paypal
        return httpx.Response(200, json={"id": payment_id, "payment_source": {"paypal": paypal_fuente}})

    def _borrar_payment_token(self, peticion: httpx.Request, payment_id: str) -> httpx.Response:
        if "borrar" in self.caer_en:
            raise httpx.ConnectError("PayPal simulado caído al borrar el token", request=peticion)
        with self._cerrojo:
            token = self.payment_tokens.get(payment_id)
            if token is None:
                return httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND"})
            token["activo"] = False
            self.tokens_borrados.append(payment_id)
        return httpx.Response(204)

    def _cobrar_con_vault(self, peticion: httpx.Request, cuerpo: dict) -> httpx.Response:
        """POST /v2/checkout/orders con `payment_source.paypal.vault_id`: cobra sin que el cliente esté presente.
        Respeta `PayPal-Request-Id` como PayPal: repetir la MISMA petición devuelve la orden original sin cobrar otra
        vez (y con otro cuerpo, 422 DUPLICATE_REQUEST_ID). `perder_respuestas_de_cobro` hace el cobro y pierde la
        respuesta (error de red), que es el caso incierto."""
        vault_id = cuerpo["payment_source"]["paypal"]["vault_id"]
        clave = peticion.headers.get("PayPal-Request-Id")
        with self._cerrojo:
            self.cuerpos_de_cobro_vault.append(cuerpo)
            self.cabeceras_de_cobro_vault.append(dict(peticion.headers))
            if clave and clave in self._respuestas_de_cobro:
                cuerpo_previo, respuesta = self._respuestas_de_cobro[clave]
                if cuerpo_previo != cuerpo:
                    return self._error(422, "DUPLICATE_REQUEST_ID")
                return httpx.Response(200, json=respuesta)
            token = self.payment_tokens.get(vault_id)
            if token is None or not token["activo"]:
                return httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND", "details": [{"issue": "INVALID_RESOURCE_ID"}]})
            if self.rechazar_cobro_vault:
                return self._error(self.estado_http_cobro_vault, self.rechazar_cobro_vault)
            self._numero += 1
            order_id = f"ORD-VLT-{self._numero:04d}"
            unidad = cuerpo["purchase_units"][0]
            orden = {
                "id": order_id,
                "status": self.estado_cobro_vault,
                "reference_id": unidad["reference_id"],
                "amount": unidad["amount"],
                "request_id_captura": clave if self.estado_cobro_vault == "COMPLETED" else None,
                "estado_captura": self.estado_captura,
                "links": [],
            }
            self.ordenes[order_id] = orden
            if self.estado_cobro_vault == "COMPLETED":
                self.cobros_vault += 1
            respuesta = self._como_json(orden)
            if clave:
                self._respuestas_de_cobro[clave] = (cuerpo, respuesta)
            perder = self.perder_respuestas_de_cobro > 0
            if perder:
                self.perder_respuestas_de_cobro -= 1
        if perder:
            raise httpx.ConnectError("PayPal simulado: se perdió la respuesta del cobro", request=peticion)
        return httpx.Response(201, json=respuesta)

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
