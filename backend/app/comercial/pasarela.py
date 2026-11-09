"""Interfaz de las pasarelas de pago. Todo lo que sabe hablar con un
proveedor externo de pagos vive detrás de `PasarelaBase`. El resto del
paquete (`cu18_procesar_pagos.py`) solo conoce esta interfaz, nunca a la pasarela
concreta -- agregar una pasarela nueva es escribir una clase acá, no
tocar el flujo de pago/webhook/confirmación de la venta.

LibelulaGateway sigue siendo un SIMULADOR de sandbox (no hay credenciales
de Libélula configuradas). PayPalGateway ya tiene credenciales reales de
sandbox (PAYPAL_CLIENT_ID/PAYPAL_CLIENT_SECRET) y llama de verdad a la
API de PayPal (OAuth2 + Orders v2) para iniciar_pago()/consultar_estado(), a
través de `app/core/paypal.py` (el mismo cliente que usa la compra de un plan).
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

import hashlib
import hmac
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from app.core import paypal
from app.core.config import get_settings
from app.core.exceptions import DomainError, ErrorFuncional
from app.plataforma import politicas as plataforma_politicas

CUATRO_DECIMALES = Decimal("0.0001")


def monto_en_usd(monto_bs: Decimal) -> tuple[Decimal, Decimal]:
    """(monto en dólares, tipo de cambio usado) de un total en bolivianos. PayPal solo cobra en USD, así que TODO cobro
    con PayPal pasa por aquí (el mismo tipo de cambio de referencia y el mismo redondeo que la compra de un plan). El
    tipo de cambio sale de `Settings` (a 4 decimales, como lo guarda el pedido de contratación)."""
    tipo_cambio = get_settings().tipo_cambio_bs_por_usd.quantize(CUATRO_DECIMALES)
    if tipo_cambio <= 0:
        raise ErrorFuncional("tipo_cambio_no_configurado", "El tipo de cambio no está configurado", 503)
    monto_usd = plataforma_politicas.convertir_bs_a_usd(monto_bs, tipo_cambio)
    if monto_usd <= 0:
        raise DomainError("El monto es demasiado bajo para cobrarlo con PayPal")
    return monto_usd, tipo_cambio


@dataclass(frozen=True)
class ResultadoIniciar:
    id_transaccion: str
    url_redireccion: str
    monto_usd: Decimal | None = None  # lo que se mandó a PayPal, si la pasarela cobra en otra moneda


@dataclass(frozen=True)
class ResultadoWebhook:
    id_transaccion: str
    estado: str  # código de estado_pago: 'aprobado' o 'rechazado'


@dataclass(frozen=True)
class ResultadoReembolso:
    referencia: str  # el id del reembolso en la pasarela
    completado: bool  # False = la pasarela lo aceptó pero todavía no lo completó (queda `pendiente`)


class ReembolsoRechazado(RuntimeError):
    """La pasarela contestó que NO devuelve ese dinero (la petición es inválida o la rechazó): es un resultado
    definitivo, distinto de "no respondió". `motivo` es un código corto, nunca el cuerpo de la respuesta."""

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


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

    def reembolsar(
        self, *, id_transaccion: str, monto: Decimal, monto_usd: Decimal | None, request_id: str
    ) -> ResultadoReembolso:
        """Devuelve `monto` (en bolivianos; `monto_usd` si la pasarela cobró en dólares) de la transacción
        `id_transaccion`. `request_id` hace idempotente el reintento. Por defecto es el de las pasarelas SIMULADAS
        (sandbox, sin ningún banco detrás): no mueve dinero y queda completado. Una pasarela real lo sobreescribe.
        `ReembolsoRechazado` = la pasarela dijo que no (definitivo); cualquier otro `RuntimeError` = no respondió
        (se puede reintentar con el mismo `request_id`)."""
        return ResultadoReembolso(referencia=f"SIM-{secrets.token_hex(6).upper()}", completado=True)

    def interpretar_webhook(self, payload: dict) -> ResultadoWebhook:
        """Ya verificada la firma, extrae el id de transacción y el
        estado resultante del payload. Las tres pasarelas (todas en
        sandbox, con el mismo HMAC) lo estructuran igual; una que lo
        estructure distinto sobreescribe este método."""
        return ResultadoWebhook(id_transaccion=payload["id_transaccion"], estado=payload["estado"])


def _firmar(secreto: str, payload_crudo: bytes) -> str:
    return hmac.new(secreto.encode("utf-8"), payload_crudo, hashlib.sha256).hexdigest()


def _firma_valida(secreto: str, payload_crudo: bytes, firma: str | None) -> bool:
    """Sin secreto configurado no hay firma válida posible: un HMAC con
    clave vacía lo puede calcular cualquiera."""
    if not secreto or not firma:
        return False
    return hmac.compare_digest(_firmar(secreto, payload_crudo), firma)


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
        return _firma_valida(self._secreto, payload_crudo, firma)


class PayPalGateway(PasarelaBase):
    """A diferencia de LibelulaGateway, esta sí llama a la API real de
    PayPal (sandbox): iniciar_pago() crea una orden de verdad en
    /v2/checkout/orders, consultar_estado() la consulta (y la captura si
    el comprador ya la aprobó del lado de PayPal pero todavía no se
    capturó el dinero)."""

    nombre = "paypal"

    def __init__(self) -> None:
        self._webhook_secret = get_settings().paypal_webhook_secret

    def iniciar_pago(self, *, monto: Decimal, referencia: str) -> ResultadoIniciar:
        # `monto` es el total de la venta en BOLIVIANOS y PayPal cobra en dólares: se convierte con el tipo de cambio
        # de referencia (el mismo de la compra de un plan). Antes se mandaba el total en Bs como si fueran USD.
        monto_usd, _tipo_cambio = monto_en_usd(monto)
        try:
            orden = paypal.crear_orden(
                monto=monto_usd,
                moneda="USD",
                referencia=referencia,
                descripcion=None,
                # Sandbox sin frontend real todavía: son URLs de vuelta de ejemplo, no rutas que existan hoy.
                return_url="https://fashionstore.example.com/pago/retorno",
                cancel_url="https://fashionstore.example.com/pago/cancelado",
            )
        except paypal.PayPalError as exc:
            if exc.causa is None:  # sin credenciales: el mensaje de configuración, como siempre
                raise
            raise RuntimeError(f"No se pudo iniciar el pago con PayPal: {exc.causa}") from exc
        return ResultadoIniciar(id_transaccion=orden.id, url_redireccion=orden.url_aprobacion, monto_usd=monto_usd)

    def consultar_estado(self, id_transaccion: str) -> str:
        try:
            orden = paypal.obtener_orden(id_transaccion)
            if orden.estado == paypal.ESTADO_COMPLETADA:
                return "aprobado"
            if orden.estado == paypal.ESTADO_APROBADA:
                # El comprador ya aprobó del lado de PayPal; hay que capturar para que el dinero se mueva de verdad.
                try:
                    captura = paypal.capturar_orden(id_transaccion, tratar_ya_capturada=False)
                except paypal.PayPalError as exc:
                    if exc.status_code is not None:  # PayPal contestó con un error: sigue sin cobrarse
                        return "iniciado"
                    raise
                return "aprobado" if captura.estado == paypal.ESTADO_COMPLETADA else "iniciado"
            if orden.estado == paypal.ESTADO_ANULADA:
                return "rechazado"
            return "iniciado"
        except paypal.PayPalError as exc:
            if exc.causa is None:
                raise
            raise RuntimeError(f"No se pudo consultar el estado en PayPal: {exc.causa}") from exc

    def reembolsar(
        self, *, id_transaccion: str, monto: Decimal, monto_usd: Decimal | None, request_id: str
    ) -> ResultadoReembolso:
        """Reembolso REAL: busca la captura de la orden (`id_transaccion`) y devuelve `monto_usd` a ese PayPal, con
        `PayPal-Request-Id` para que repetirlo no devuelva el dinero dos veces. PayPal cobra en dólares: sin `monto_usd`
        (un pago anterior a la conversión) no se puede reembolsar solo."""
        if monto_usd is None or monto_usd <= 0:
            raise ReembolsoRechazado("sin_monto_usd")
        try:
            orden = paypal.obtener_orden(id_transaccion)
            if not orden.captura_id:
                raise ReembolsoRechazado("sin_captura")
            reembolso = paypal.reembolsar_captura(
                orden.captura_id, monto=monto_usd, moneda=orden.moneda or "USD", request_id=request_id
            )
        except paypal.PayPalError as exc:
            if exc.causa is None:  # sin credenciales: el mensaje de configuración, como siempre
                raise
            # Una respuesta 4xx de PayPal (salvo 401/429) es un "no" definitivo; lo demás (red, 5xx) es "no respondió".
            if exc.status_code is not None and 400 <= exc.status_code < 500 and exc.status_code not in (401, 429):
                raise ReembolsoRechazado("rechazado_por_paypal") from exc
            raise RuntimeError("No se pudo comunicar con PayPal para reembolsar") from exc
        if reembolso.estado == paypal.ESTADO_REEMBOLSO_COMPLETADO:
            return ResultadoReembolso(referencia=reembolso.id, completado=True)
        if reembolso.estado == paypal.ESTADO_REEMBOLSO_PENDIENTE:
            return ResultadoReembolso(referencia=reembolso.id, completado=False)
        raise ReembolsoRechazado("rechazado_por_paypal")

    def verificar_firma(self, payload_crudo: bytes, firma: str | None) -> bool:
        return _firma_valida(self._webhook_secret, payload_crudo, firma)


class QrOnlineGateway(PasarelaBase):
    """Pasarela simulada de pago por QR: a diferencia de LibelulaGateway
    (que redirige a una URL externa que nunca existió), acá
    `url_redireccion` apunta a una pantalla que sirve nuestro propio
    backend (`GET /pagos/qr/{id_transaccion}`, ver `comercial/router.py` y
    `ConfirmarRechazarTransaccion.confirmar_pago_qr`) con un QR de verdad y un botón "Confirmar pago".
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
        # (ConfirmarRechazarTransaccion.confirmar_pago_qr), no por polling activo acá.
        return "iniciado"

    def verificar_firma(self, payload_crudo: bytes, firma: str | None) -> bool:
        return _firma_valida(self._secreto, payload_crudo, firma)

    def firmar_confirmacion(self, payload_crudo: bytes) -> str:
        """No es parte de PasarelaBase: la usa únicamente
        ConfirmarRechazarTransaccion.confirmar_pago_qr() para firmar, del lado del servidor,
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
