"""Cliente mínimo de la API de correo transaccional de Brevo (`POST /v3/smtp/email`).

Infraestructura transversal: NO importa ningún paquete de negocio. Quien necesita mandar un correo (hoy, la
recuperación de contraseña de `plataforma`, CU-01) arma un `MensajeCorreo` y llama a `enviar_correo`; aquí vive lo
único que sabe hablar con Brevo.

- Configuración por variables de entorno (regla 9, nada en el código): `BREVO_API_KEY`, `CORREO_REMITENTE_EMAIL` (un
  remitente VERIFICADO en Brevo, el mismo para todas las empresas) y `CORREO_REMITENTE_NOMBRE`. Sin clave o sin
  remitente no hay llamada: `CorreoError`.
- Cualquier fallo de red o respuesta HTTP de error se convierte en `CorreoError`, que HEREDA de `RuntimeError`.
- `enviar_correo_sin_romper` es para el segundo plano: traga el error y deja una línea de log SIN el correo del
  destinatario, sin el asunto y sin el cuerpo (el enlace de recuperación lleva un token): solo el motivo y el estado
  HTTP. Un correo que no sale nunca tumba la petición que lo pidió.
- Las pruebas jamás salen a la red: `tests/conftest.py` vacía la clave y los tests que necesitan Brevo sustituyen
  `_crear_cliente` (ver `tests/correo_simulado.py`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

URL_BREVO = "https://api.brevo.com/v3/smtp/email"
TIMEOUT_SEGUNDOS = 10


class CorreoError(RuntimeError):
    """Brevo no respondió, rechazó el mensaje o el envío no está configurado.

    `status_code` es el estado HTTP con que Brevo respondió (`None` si ni siquiera hubo respuesta)."""

    def __init__(self, mensaje: str, *, causa: Exception | None = None, status_code: int | None = None) -> None:
        super().__init__(mensaje)
        self.causa = causa
        self.status_code = status_code


@dataclass(frozen=True)
class MensajeCorreo:
    """Un correo ya armado. `para_nombre` es opcional (Brevo lo muestra junto a la dirección)."""

    para_email: str
    asunto: str
    html: str
    texto: str
    para_nombre: str = ""


def envio_configurado() -> bool:
    ajustes = get_settings()
    return bool(ajustes.brevo_api_key and ajustes.correo_remitente_email)


def _crear_cliente() -> httpx.Client:
    """Un cliente nuevo por llamada. Las pruebas lo sustituyen por uno con `httpx.MockTransport`."""
    return httpx.Client(timeout=TIMEOUT_SEGUNDOS)


def enviar_correo(mensaje: MensajeCorreo) -> None:
    """Manda el correo por Brevo. Cualquier fallo es `CorreoError`."""
    ajustes = get_settings()
    if not ajustes.brevo_api_key or not ajustes.correo_remitente_email:
        raise CorreoError("BREVO_API_KEY/CORREO_REMITENTE_EMAIL no están configurados")

    destinatario: dict[str, str] = {"email": mensaje.para_email}
    if mensaje.para_nombre:
        destinatario["name"] = mensaje.para_nombre
    cuerpo = {
        "sender": {"name": ajustes.correo_remitente_nombre, "email": ajustes.correo_remitente_email},
        "to": [destinatario],
        "subject": mensaje.asunto,
        "htmlContent": mensaje.html,
        "textContent": mensaje.texto,
    }
    try:
        with _crear_cliente() as cliente:
            respuesta = cliente.post(
                URL_BREVO,
                json=cuerpo,
                headers={"api-key": ajustes.brevo_api_key, "accept": "application/json"},
            )
            respuesta.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise CorreoError(
            f"Brevo respondió {exc.response.status_code}", causa=exc, status_code=exc.response.status_code
        ) from exc
    except httpx.HTTPError as exc:
        raise CorreoError("No se pudo comunicar con Brevo", causa=exc) from exc


def enviar_correo_sin_romper(mensaje: MensajeCorreo) -> bool:
    """Para el segundo plano: devuelve si se envió y nunca lanza. El log no lleva datos del mensaje."""
    try:
        enviar_correo(mensaje)
    except CorreoError as exc:
        logger.warning("correo_no_enviado motivo=%s estado_http=%s", exc, exc.status_code)
        return False
    except Exception:  # noqa: BLE001 - un correo jamás debe tumbar el proceso que lo pidió
        logger.exception("correo_no_enviado motivo=error_inesperado")
        return False
    return True
