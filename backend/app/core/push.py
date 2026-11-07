"""Cliente mínimo de Firebase Cloud Messaging (FCM HTTP v1) para las notificaciones push.

Infraestructura transversal: NO importa ningún paquete de negocio. Quien necesita avisar a un teléfono (hoy, `plataforma`
al crear una `Notificacion`) arma un `MensajePush` y llama a `enviar_sin_romper`; aquí vive lo único que sabe hablar con
Google: el token OAuth2 de la cuenta de servicio y el `messages:send` de FCM.

- Configuración por variable de entorno (regla 9, nada en el código): `FIREBASE_CREDENCIALES_JSON`, el JSON COMPLETO de
  la cuenta de servicio (de ahí salen `project_id`, `client_email` y `private_key`). Sin ella, `envio_configurado()` es
  falso y no hay ninguna llamada: todo lo demás funciona igual (como Brevo sin clave).
- Autenticación: JWT firmado RS256 con PyJWT (usa `cryptography`) -> `https://oauth2.googleapis.com/token`, scope
  `firebase.messaging`. El token de acceso se guarda en memoria hasta cerca de su expiración (un solo worker).
- Errores: un token de dispositivo que FCM da por muerto (`UNREGISTERED`, `NOT_FOUND`, `INVALID_ARGUMENT`) devuelve
  `ResultadoEnvio.TOKEN_INVALIDO`: quien llama lo desactiva. 429, 5xx, red y OAuth caído se reintentan UNA vez, tras una
  espera corta, y si siguen fallando es `PushError` (mejor esfuerzo: no se desactiva nada). Un 401 de FCM descarta el
  token de acceso en caché y cuenta como ese único reintento.
- Privacidad: jamás se registra la credencial, el token de acceso, el cuerpo de una respuesta ni un token de dispositivo
  completo (solo sus últimos 6 caracteres, `token_corto`). Las pruebas nunca salen a la red: `tests/conftest.py` vacía la
  credencial y los tests que necesitan FCM sustituyen `_crear_cliente` (ver `tests/push_simulado.py`).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum

import httpx
import jwt

from app.core.config import get_settings

logger = logging.getLogger(__name__)

URL_TOKEN_OAUTH = "https://oauth2.googleapis.com/token"
URL_FCM = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
SCOPE_FCM = "https://www.googleapis.com/auth/firebase.messaging"
TIPO_CONCESION = "urn:ietf:params:oauth:grant-type:jwt-bearer"
CANAL_ANDROID = "fashionstore_avisos"  # el canal que crea la app móvil
TIMEOUT_SEGUNDOS = 10
VIGENCIA_JWT_SEGUNDOS = 3600
MARGEN_RENOVACION_SEGUNDOS = 300  # el token de acceso se renueva 5 minutos antes de vencer
ESPERA_REINTENTO_SEGUNDOS = 0.5
# Códigos con que FCM dice que ESE token de dispositivo ya no sirve (en `error.status` o en `details[].errorCode`).
CODIGOS_TOKEN_INVALIDO = frozenset({"UNREGISTERED", "NOT_FOUND", "INVALID_ARGUMENT"})


class PushError(RuntimeError):
    """FCM (o el OAuth de Google) no respondió, rechazó el mensaje o el envío no está configurado.

    `status_code` es el estado HTTP con que se respondió (`None` si ni siquiera hubo respuesta)."""

    def __init__(self, mensaje: str, *, causa: Exception | None = None, status_code: int | None = None) -> None:
        super().__init__(mensaje)
        self.causa = causa
        self.status_code = status_code


class ResultadoEnvio(str, Enum):
    ENVIADO = "enviado"
    TOKEN_INVALIDO = "token_invalido"  # FCM ya no reconoce el token: hay que desactivarlo
    FALLIDO = "fallido"  # caída temporal o error nuestro: el token sigue como estaba


@dataclass(frozen=True)
class MensajePush:
    """Un push ya armado para UN dispositivo. Los valores de `datos` son siempre texto (lo exige FCM)."""

    token: str
    titulo: str
    cuerpo: str
    datos: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _Credencial:
    project_id: str
    client_email: str
    private_key: str


def token_corto(token: str) -> str:
    """Lo único de un token de dispositivo que se permite escribir en un log."""
    return f"...{token[-6:]}" if token else "..."


def envio_configurado() -> bool:
    return bool(get_settings().firebase_credenciales_json.strip())


def _crear_cliente() -> httpx.Client:
    """Un cliente nuevo por llamada. Las pruebas lo sustituyen por uno con `httpx.MockTransport`."""
    return httpx.Client(timeout=TIMEOUT_SEGUNDOS)


def _esperar(segundos: float) -> None:
    """Pausa entre el intento y su reintento. Las pruebas lo sustituyen para no esperar."""
    time.sleep(segundos)


def _credencial() -> _Credencial:
    crudo = get_settings().firebase_credenciales_json.strip()
    if not crudo:
        raise PushError("FIREBASE_CREDENCIALES_JSON no está configurada")
    try:
        datos = json.loads(crudo)
    except ValueError:
        raise PushError("FIREBASE_CREDENCIALES_JSON no es un JSON válido") from None  # sin eco del contenido
    if not isinstance(datos, dict):
        raise PushError("FIREBASE_CREDENCIALES_JSON no es una cuenta de servicio")
    faltan = [c for c in ("project_id", "client_email", "private_key") if not isinstance(datos.get(c), str) or not datos[c]]
    if faltan:
        raise PushError(f"FIREBASE_CREDENCIALES_JSON no trae: {', '.join(faltan)}")
    return _Credencial(datos["project_id"], datos["client_email"], datos["private_key"])


# ---- Token de acceso OAuth2 (cuenta de servicio), en caché ------------------------------------------------------------

_cerrojo = threading.Lock()
_cache: dict[str, object] = {}  # {"cuenta": client_email, "token": str, "vence": monotonic}


def reiniciar_cache() -> None:
    """Olvida el token de acceso guardado (las pruebas, y un 401 de FCM)."""
    with _cerrojo:
        _cache.clear()


def _pedir_token_de_acceso(credencial: _Credencial) -> tuple[str, int]:
    ahora = int(time.time())
    reclamos = {
        "iss": credencial.client_email,
        "scope": SCOPE_FCM,
        "aud": URL_TOKEN_OAUTH,
        "iat": ahora,
        "exp": ahora + VIGENCIA_JWT_SEGUNDOS,
    }
    try:
        asercion = jwt.encode(reclamos, credencial.private_key, algorithm="RS256")
    except Exception:  # noqa: BLE001 - llave ilegible: nunca se escribe ni se encadena (podría traer la llave)
        raise PushError("La llave privada de la cuenta de servicio no sirve para firmar") from None
    try:
        with _crear_cliente() as cliente:
            respuesta = cliente.post(URL_TOKEN_OAUTH, data={"grant_type": TIPO_CONCESION, "assertion": asercion})
            respuesta.raise_for_status()
            datos = respuesta.json()
    except httpx.HTTPStatusError as exc:
        raise PushError(
            f"Google respondió {exc.response.status_code} al pedir el token", status_code=exc.response.status_code
        ) from None
    except httpx.HTTPError:
        raise PushError("No se pudo comunicar con Google para pedir el token") from None
    except ValueError:
        raise PushError("Google devolvió un token ilegible") from None
    token = datos.get("access_token") if isinstance(datos, dict) else None
    if not token:
        raise PushError("Google no devolvió un token de acceso")
    try:
        vigencia = int(datos.get("expires_in", VIGENCIA_JWT_SEGUNDOS))
    except (TypeError, ValueError):
        vigencia = VIGENCIA_JWT_SEGUNDOS
    return str(token), vigencia


def obtener_token_de_acceso(credencial: _Credencial | None = None) -> str:
    """El token OAuth2 vigente; lo pide a Google solo si no hay uno o está por vencer."""
    credencial = credencial or _credencial()
    with _cerrojo:
        if (
            _cache.get("cuenta") == credencial.client_email
            and float(_cache.get("vence", 0)) > time.monotonic()  # type: ignore[arg-type]
        ):
            return str(_cache["token"])
        token, vigencia = _pedir_token_de_acceso(credencial)
        _cache.clear()
        _cache.update(
            cuenta=credencial.client_email,
            token=token,
            vence=time.monotonic() + max(vigencia - MARGEN_RENOVACION_SEGUNDOS, 0),
        )
        return token


# ---- Envío ------------------------------------------------------------------------------------------------------------


def _codigos_de_error(respuesta: httpx.Response) -> set[str]:
    try:
        error = respuesta.json().get("error") or {}
    except (ValueError, AttributeError):
        return set()
    if not isinstance(error, dict):
        return set()
    codigos = {str(error.get("status", ""))}
    for detalle in error.get("details") or []:
        if isinstance(detalle, dict) and detalle.get("errorCode"):
            codigos.add(str(detalle["errorCode"]))
    return codigos


def _cuerpo_fcm(mensaje: MensajePush) -> dict:
    return {
        "message": {
            "token": mensaje.token,
            "notification": {"title": mensaje.titulo, "body": mensaje.cuerpo},
            "data": {str(k): "" if v is None else str(v) for k, v in mensaje.datos.items()},
            "android": {"priority": "HIGH", "notification": {"channel_id": CANAL_ANDROID}},
        }
    }


def _intentar(mensaje: MensajePush, credencial: _Credencial) -> ResultadoEnvio:
    """UN intento. Devuelve el resultado o lanza `PushError` (con `status_code`: 401, 429 y 5xx son reintentables)."""
    acceso = obtener_token_de_acceso(credencial)
    url = URL_FCM.format(project_id=credencial.project_id)
    try:
        with _crear_cliente() as cliente:
            respuesta = cliente.post(url, json=_cuerpo_fcm(mensaje), headers={"Authorization": f"Bearer {acceso}"})
    except httpx.HTTPError:
        raise PushError("No se pudo comunicar con FCM") from None
    if respuesta.is_success:
        return ResultadoEnvio.ENVIADO
    if respuesta.status_code in (400, 404) and _codigos_de_error(respuesta) & CODIGOS_TOKEN_INVALIDO:
        return ResultadoEnvio.TOKEN_INVALIDO
    raise PushError(f"FCM respondió {respuesta.status_code}", status_code=respuesta.status_code)


def _es_reintentable(exc: PushError) -> bool:
    return exc.status_code is None or exc.status_code in (401, 429) or exc.status_code >= 500


def enviar(mensaje: MensajePush) -> ResultadoEnvio:
    """Manda el push. `ENVIADO` o `TOKEN_INVALIDO`; cualquier otro fallo (tras un único reintento) es `PushError`."""
    credencial = _credencial()
    try:
        return _intentar(mensaje, credencial)
    except PushError as primero:
        if not _es_reintentable(primero):
            raise
        if primero.status_code == 401:
            reiniciar_cache()  # el token de acceso ya no vale: se pide otro en el reintento
        _esperar(ESPERA_REINTENTO_SEGUNDOS)
        return _intentar(mensaje, credencial)


def enviar_sin_romper(mensaje: MensajePush) -> ResultadoEnvio:
    """Para el segundo plano: devuelve el resultado y nunca lanza. El log lleva solo el motivo, el estado HTTP y el
    final del token del dispositivo."""
    try:
        return enviar(mensaje)
    except PushError as exc:
        logger.warning(
            "push_no_enviado motivo=%s estado_http=%s dispositivo=%s", exc, exc.status_code, token_corto(mensaje.token)
        )
    except Exception:  # noqa: BLE001 - un push jamás debe tumbar el proceso que lo pidió
        logger.error("push_no_enviado motivo=error_inesperado dispositivo=%s", token_corto(mensaje.token))
    return ResultadoEnvio.FALLIDO
