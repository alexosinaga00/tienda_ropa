"""Brevo simulado para las pruebas: un servidor en memoria detrás de `httpx.MockTransport`.

Ninguna prueba toca Brevo de verdad. `SimuladorBrevo` sustituye el cliente HTTP de `app.core.correo`
(`_crear_cliente`), así que el código de producción corre completo (cuerpo, cabeceras, interpretación de la
respuesta) y solo la red es falsa. Guarda cada correo recibido en `enviados`. Para provocar fallos: `caido` (error de
red) o `estado_error` (Brevo responde ese estado HTTP)."""

from __future__ import annotations

import json

import httpx

from app.core import correo
from app.core.config import get_settings


class SimuladorBrevo:
    def __init__(self, monkeypatch, *, configurado: bool = True) -> None:
        self.enviados: list[dict] = []  # cuerpos JSON recibidos
        self.cabeceras: list[dict] = []
        self.caido = False
        self.estado_error: int | None = None
        if configurado:
            ajustes = get_settings()
            monkeypatch.setattr(ajustes, "brevo_api_key", "clave-simulada")
            monkeypatch.setattr(ajustes, "correo_remitente_email", "remitente@fashionstore.test")
            monkeypatch.setattr(ajustes, "correo_remitente_nombre", "FashionStore")
        monkeypatch.setattr(correo, "_crear_cliente", lambda: httpx.Client(transport=httpx.MockTransport(self._manejar)))

    def _manejar(self, peticion: httpx.Request) -> httpx.Response:
        if self.caido:
            raise httpx.ConnectError("sin red", request=peticion)
        if self.estado_error is not None:
            return httpx.Response(self.estado_error, json={"code": "error", "message": "rechazado"})
        self.cabeceras.append(dict(peticion.headers))
        self.enviados.append(json.loads(peticion.content))
        return httpx.Response(201, json={"messageId": f"<{len(self.enviados)}@simulado>"})

    def ultimo(self) -> dict:
        return self.enviados[-1]
