"""core/push.py: el cliente de Firebase Cloud Messaging (FCM HTTP v1) con OAuth2 de la cuenta de servicio.

Sin base de datos: FCM y el OAuth de Google son simulados (`tests/push_simulado.py`). NO se probó contra Firebase real."""

import json
import logging

import jwt
import pytest

from app.core import push
from app.core.push import MensajePush, ResultadoEnvio
from tests.push_simulado import CLIENT_EMAIL, PROJECT_ID, TOKEN_ACCESO, SimuladorFCM, error_fcm, llave_publica

TOKEN = "fcm-token-del-telefono-" + "x" * 120 + "ABC123"


@pytest.fixture()
def fcm(monkeypatch) -> SimuladorFCM:
    return SimuladorFCM(monkeypatch)


def _mensaje(token: str = TOKEN) -> MensajePush:
    return MensajePush(
        token=token,
        titulo="Cobramos tu pedido",
        cuerpo="Pagaste Bs 200.00",
        datos={"tipo": "pedido_diferido", "referencia_id": "7", "notificacion_id": "12"},
    )


# ---- configuración ----


def test_sin_credencial_no_hay_envio_ni_llamadas(monkeypatch):
    sim = SimuladorFCM(monkeypatch, con_credencial=False)

    assert push.envio_configurado() is False
    assert push.enviar_sin_romper(_mensaje()) is ResultadoEnvio.FALLIDO
    assert sim.mensajes == [] and sim.peticiones_oauth == []


@pytest.mark.parametrize("crudo", ["esto no es json", "[1, 2]", '{"project_id": "p"}', '{"project_id": "p", "client_email": "e", "private_key": ""}'])
def test_una_credencial_incompleta_o_ilegible_no_envia_y_no_lanza(monkeypatch, caplog, crudo):
    sim = SimuladorFCM(monkeypatch)
    monkeypatch.setattr(push.get_settings(), "firebase_credenciales_json", crudo)

    with caplog.at_level(logging.DEBUG):
        resultado = push.enviar_sin_romper(_mensaje())

    assert resultado is ResultadoEnvio.FALLIDO
    assert sim.mensajes == []
    assert crudo not in caplog.text


# ---- el mensaje ----


def test_el_mensaje_lleva_notificacion_datos_prioridad_alta_y_canal(fcm):
    assert push.enviar(_mensaje()) is ResultadoEnvio.ENVIADO

    (cuerpo,) = fcm.mensajes
    assert cuerpo == {
        "message": {
            "token": TOKEN,
            "notification": {"title": "Cobramos tu pedido", "body": "Pagaste Bs 200.00"},
            "data": {"tipo": "pedido_diferido", "referencia_id": "7", "notificacion_id": "12"},
            "android": {"priority": "HIGH", "notification": {"channel_id": "fashionstore_avisos"}},
            "webpush": {"headers": {"Urgency": "high"}},
        }
    }
    assert all(isinstance(v, str) for v in cuerpo["message"]["data"].values())
    assert fcm.urls_fcm == [f"https://fcm.googleapis.com/v1/projects/{PROJECT_ID}/messages:send"]
    assert fcm.cabeceras_fcm[0]["authorization"] == f"Bearer {TOKEN_ACCESO}"


def test_el_mismo_mensaje_sirve_a_android_y_al_navegador_con_un_bloque_para_cada_uno(fcm):
    push.enviar(_mensaje())

    mensaje = fcm.mensajes[0]["message"]
    assert mensaje["android"] == {"priority": "HIGH", "notification": {"channel_id": "fashionstore_avisos"}}  # intacto
    assert mensaje["webpush"] == {"headers": {"Urgency": "high"}}
    assert set(mensaje) == {"token", "notification", "data", "android", "webpush"}


def test_los_valores_de_datos_siempre_son_texto(fcm):
    push.enviar(MensajePush(token=TOKEN, titulo="t", cuerpo="", datos={"n": 5, "vacio": None}))  # type: ignore[dict-item]

    assert fcm.mensajes[0]["message"]["data"] == {"n": "5", "vacio": ""}


# ---- OAuth2 de la cuenta de servicio ----


def test_el_jwt_va_firmado_rs256_con_la_cuenta_y_el_scope_correctos(fcm):
    push.enviar(_mensaje())

    (peticion,) = fcm.peticiones_oauth
    assert peticion["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
    assert jwt.get_unverified_header(peticion["assertion"])["alg"] == "RS256"
    reclamos = jwt.decode(
        peticion["assertion"], llave_publica(), algorithms=["RS256"], audience="https://oauth2.googleapis.com/token"
    )
    assert reclamos["iss"] == CLIENT_EMAIL
    assert reclamos["scope"] == "https://www.googleapis.com/auth/firebase.messaging"
    assert 0 < reclamos["exp"] - reclamos["iat"] <= 3600


def test_el_token_de_acceso_se_guarda_en_cache(fcm):
    for _ in range(3):
        assert push.enviar(_mensaje()) is ResultadoEnvio.ENVIADO

    assert len(fcm.peticiones_oauth) == 1 and len(fcm.mensajes) == 3


def test_el_token_de_acceso_se_renueva_cerca_de_vencer(fcm, monkeypatch):
    push.enviar(_mensaje())
    # Pasan 56 minutos: el token (1 hora) está dentro del margen de renovación de 5 minutos.
    reloj = push.time.monotonic() + 56 * 60
    monkeypatch.setattr(push.time, "monotonic", lambda: reloj)

    push.enviar(_mensaje())

    assert len(fcm.peticiones_oauth) == 2


def test_un_token_corto_se_renueva_en_cada_envio(fcm):
    fcm.expira_en = 200  # menos que el margen de renovación: nunca queda vigente en caché

    push.enviar(_mensaje())
    push.enviar(_mensaje())

    assert len(fcm.peticiones_oauth) == 2


def test_oauth_caido_no_envia_y_no_lanza(fcm):
    fcm.oauth_caido = True

    assert push.enviar_sin_romper(_mensaje()) is ResultadoEnvio.FALLIDO
    assert fcm.mensajes == [] and len(fcm.peticiones_oauth) == 2  # el intento y su único reintento
    assert fcm.esperas == [push.ESPERA_REINTENTO_SEGUNDOS]


# ---- errores de FCM ----


@pytest.mark.parametrize(
    "respuesta",
    [
        error_fcm(404, "NOT_FOUND", "UNREGISTERED"),
        error_fcm(404, "NOT_FOUND"),
        error_fcm(400, "INVALID_ARGUMENT"),
        error_fcm(400, "FAILED_PRECONDITION", "UNREGISTERED"),
    ],
)
def test_un_token_muerto_se_informa_sin_reintentar(fcm, respuesta):
    fcm.respuestas[TOKEN] = respuesta

    assert push.enviar_sin_romper(_mensaje()) is ResultadoEnvio.TOKEN_INVALIDO
    assert len(fcm.mensajes) == 1 and fcm.esperas == []


@pytest.mark.parametrize("estado", [429, 500, 503])
def test_un_fallo_temporal_se_reintenta_una_vez_y_luego_se_abandona(fcm, estado):
    fcm.estado_global = (estado, {"error": {"status": "UNAVAILABLE"}})

    assert push.enviar_sin_romper(_mensaje()) is ResultadoEnvio.FALLIDO
    assert len(fcm.mensajes) == 2 and fcm.esperas == [push.ESPERA_REINTENTO_SEGUNDOS]


def test_si_el_reintento_funciona_el_push_sale(fcm):
    fcm.estado_global = (503, {"error": {"status": "UNAVAILABLE"}})
    llamadas = []
    original = fcm._fcm

    def _una_falla_y_luego_ok(peticion):
        llamadas.append(1)
        if len(llamadas) == 2:
            fcm.estado_global = None
        return original(peticion)

    fcm._fcm = _una_falla_y_luego_ok  # type: ignore[method-assign]

    assert push.enviar_sin_romper(_mensaje()) is ResultadoEnvio.ENVIADO
    assert len(fcm.mensajes) == 2


def test_la_red_caida_se_reintenta_una_vez_y_no_lanza(fcm):
    fcm.caido = True

    assert push.enviar_sin_romper(_mensaje()) is ResultadoEnvio.FALLIDO
    assert fcm.esperas == [push.ESPERA_REINTENTO_SEGUNDOS]


def test_un_401_descarta_el_token_de_acceso_y_reintenta_con_otro(fcm):
    fcm.estado_global = error_fcm(401, "UNAUTHENTICATED")
    llamadas = []
    original = fcm._fcm

    def _401_y_luego_ok(peticion):
        llamadas.append(1)
        if len(llamadas) == 2:
            fcm.estado_global = None
        return original(peticion)

    fcm._fcm = _401_y_luego_ok  # type: ignore[method-assign]

    assert push.enviar_sin_romper(_mensaje()) is ResultadoEnvio.ENVIADO
    assert len(fcm.peticiones_oauth) == 2  # pidió un token de acceso nuevo


@pytest.mark.parametrize("respuesta", [error_fcm(403, "PERMISSION_DENIED"), error_fcm(400, "FAILED_PRECONDITION")])
def test_un_error_que_no_es_del_token_ni_temporal_no_se_reintenta_ni_desactiva(fcm, respuesta):
    fcm.estado_global = respuesta

    assert push.enviar_sin_romper(_mensaje()) is ResultadoEnvio.FALLIDO
    assert len(fcm.mensajes) == 1 and fcm.esperas == []


# ---- nada sensible en los logs ----


def test_ni_la_credencial_ni_el_token_de_acceso_ni_el_token_completo_llegan_al_log(fcm, caplog, monkeypatch):
    llave = push.get_settings().firebase_credenciales_json
    fcm.estado_global = error_fcm(500, "INTERNAL")

    with caplog.at_level(logging.DEBUG):
        push.enviar_sin_romper(_mensaje())
        fcm.oauth_caido = True
        push.reiniciar_cache()
        push.enviar_sin_romper(_mensaje())
        rota = json.dumps({**json.loads(llave), "private_key": "LLAVE-ROTA-QUE-NO-DEBE-SALIR"})
        monkeypatch.setattr(push.get_settings(), "firebase_credenciales_json", rota)
        push.reiniciar_cache()
        assert push.enviar_sin_romper(_mensaje()) is ResultadoEnvio.FALLIDO

    texto = caplog.text
    assert "push_no_enviado" in texto and "...ABC123" in texto
    assert TOKEN not in texto and TOKEN[:-6] not in texto
    assert TOKEN_ACCESO not in texto and "LLAVE-ROTA" not in texto
    assert "BEGIN PRIVATE KEY" not in texto and "private_key" not in texto and CLIENT_EMAIL not in texto
    assert "Bearer" not in texto
