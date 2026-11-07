"""FCM y el OAuth de Google simulados para las pruebas: servidores en memoria detrás de `httpx.MockTransport`.

Ninguna prueba toca Firebase de verdad. `SimuladorFCM` sustituye el cliente HTTP de `app.core.push` (`_crear_cliente`),
así que el código de producción corre completo (JWT firmado RS256 con una llave de prueba, token de acceso, cuerpo de
`messages:send`, interpretación de los errores) y solo la red es falsa.

También reemplaza lo que haría el envío real en segundo plano: los hilos (`plataforma.politicas._programar_en_segundo_plano`
guarda la tarea en `programados` y `correr()` la ejecuta cuando la prueba quiere, en orden y sin carreras) y la sesión
propia del segundo plano (`_nueva_sesion`, sobre la misma base de la prueba).

Para provocar fallos: `caido` (todo FCM falla con error de red), `estado_global` (FCM responde ese estado a todo),
`respuestas[token]` (estado y cuerpo para UN token) y `oauth_caido`."""

from __future__ import annotations

import json
import threading

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.orm import sessionmaker

from app.core import push
from app.core.config import get_settings
from app.plataforma import politicas

PROJECT_ID = "fashionstore-prueba"
CLIENT_EMAIL = "push@fashionstore-prueba.iam.gserviceaccount.com"
TOKEN_ACCESO = "ya29.token-de-acceso-simulado"

_llaves: dict[str, str] = {}


def _llave_de_prueba() -> tuple[str, str]:
    """(privada, pública) PEM de una llave RSA generada una sola vez por proceso (generarla cuesta ~0,2 s)."""
    if not _llaves:
        llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        _llaves["privada"] = llave.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
        _llaves["publica"] = (
            llave.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        )
    return _llaves["privada"], _llaves["publica"]


def llave_publica() -> str:
    return _llave_de_prueba()[1]


def credencial_json() -> str:
    """El JSON de una cuenta de servicio de mentira, con una llave RSA real (para poder firmar)."""
    return json.dumps(
        {
            "type": "service_account",
            "project_id": PROJECT_ID,
            "private_key_id": "abc123",
            "private_key": _llave_de_prueba()[0],
            "client_email": CLIENT_EMAIL,
            "token_uri": push.URL_TOKEN_OAUTH,
        }
    )


def error_fcm(estado_http: int, status: str, error_code: str | None = None) -> tuple[int, dict]:
    """El cuerpo de error de la API v1 de FCM: `error.status` y, a veces, `details[].errorCode`."""
    error: dict = {"code": estado_http, "message": "mensaje de Google", "status": status}
    if error_code:
        error["details"] = [{"@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError", "errorCode": error_code}]
    return estado_http, {"error": error}


class SimuladorFCM:
    def __init__(self, monkeypatch, db_session=None, *, con_credencial: bool = True) -> None:
        self.mensajes: list[dict] = []  # el cuerpo JSON de cada messages:send recibido
        self.cabeceras_fcm: list[dict] = []
        self.urls_fcm: list[str] = []
        self.peticiones_oauth: list[dict] = []  # los campos del formulario de cada petición de token
        self.caido = False  # todo falla con error de red (FCM y OAuth)
        self.oauth_caido = False  # solo el OAuth falla (Google responde 500)
        self.estado_global: tuple[int, dict] | None = None  # FCM responde esto a TODO
        self.respuestas: dict[str, tuple[int, dict]] = {}  # token de dispositivo -> (estado, cuerpo)
        self.programados: list[tuple] = []  # (función, argumentos) que el código de producción mandó al segundo plano
        self.esperas: list[float] = []  # pausas pedidas entre intento y reintento
        self.expira_en = 3600  # `expires_in` del token de acceso
        self._cerrojo = threading.Lock()
        self._db = db_session
        ajustes = get_settings()
        monkeypatch.setattr(ajustes, "firebase_credenciales_json", credencial_json() if con_credencial else "")
        monkeypatch.setattr(push, "_crear_cliente", lambda: httpx.Client(transport=httpx.MockTransport(self._manejar)))
        monkeypatch.setattr(push, "_esperar", self.esperas.append)
        push.reiniciar_cache()
        monkeypatch.setattr(politicas, "_programar_en_segundo_plano", lambda f, *a: self.programados.append((f, a)))
        if db_session is not None:
            fabrica = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)
            monkeypatch.setattr(politicas, "_nueva_sesion", fabrica)

    # -- Lo que hacen las pruebas ----------------------------------------------------------------------------------

    def correr(self) -> int:
        """Ejecuta (en orden) lo que quedó programado en segundo plano. Devuelve cuántas tareas corrió."""
        if self._db is not None:
            self._db.commit()  # la sesión de la prueba comparte conexión con la del segundo plano: debe estar libre
        tareas, self.programados = self.programados, []
        for funcion, argumentos in tareas:
            funcion(*argumentos)
        return len(tareas)

    @property
    def destinatarios(self) -> list[str]:
        return [m["message"]["token"] for m in self.mensajes]

    # -- El "servidor" ------------------------------------------------------------------------------------------------

    def _manejar(self, peticion: httpx.Request) -> httpx.Response:
        with self._cerrojo:
            if self.caido:
                raise httpx.ConnectError("sin red (simulado)", request=peticion)
            if str(peticion.url) == push.URL_TOKEN_OAUTH:
                return self._oauth(peticion)
            if peticion.url.host == "fcm.googleapis.com":
                return self._fcm(peticion)
        return httpx.Response(404, json={})

    def _oauth(self, peticion: httpx.Request) -> httpx.Response:
        formulario = httpx.QueryParams(peticion.content.decode())  # application/x-www-form-urlencoded
        self.peticiones_oauth.append(
            {
                "grant_type": formulario.get("grant_type"),
                "assertion": formulario.get("assertion"),
                "campos": sorted(formulario.keys()),
            }
        )
        if self.oauth_caido:
            return httpx.Response(500, json={"error": "backend_error"})
        return httpx.Response(200, json={"access_token": TOKEN_ACCESO, "expires_in": self.expira_en, "token_type": "Bearer"})

    def _fcm(self, peticion: httpx.Request) -> httpx.Response:
        cuerpo = json.loads(peticion.content)
        self.mensajes.append(cuerpo)
        self.cabeceras_fcm.append(dict(peticion.headers))
        self.urls_fcm.append(str(peticion.url))
        token = cuerpo["message"]["token"]
        estado, contenido = self.respuestas.get(token) or self.estado_global or (200, {"name": "projects/x/messages/1"})
        return httpx.Response(estado, json=contenido)
