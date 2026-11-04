"""Recuperar la contraseña por correo (Brevo, `core/correo.py`).

El correo sale en segundo plano, con el enlace a la pantalla de nueva contraseña de la web: el cliente entra por
su tienda (`/t/<codigo>/restablecer`) y el personal por `/restablecer`. La respuesta al cliente es siempre la
misma (exista o no la cuenta, salga o no el correo). Brevo es el simulado de `tests/correo_simulado.py`: ninguna
prueba sale a la red."""

import logging
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from app.core import correo
from app.core.config import get_settings
from app.core.correo import CorreoError, MensajeCorreo, enviar_correo
from app.core.rate_limit import limiter
from app.plataforma import router as router_plataforma
from app.plataforma.casos_uso import cu01_autenticar_registrar_usuarios as cu01
from app.plataforma.models import Empresa
from app.plataforma.politicas import construir_correo_recuperacion, enlace_de_recuperacion
from tests.correo_simulado import SimuladorBrevo

CLAVE = "claveSegura123"
NUEVA = "nuevaClave456"
CORREO = "cliente@example.com"
TEXTO = "Si el correo está registrado, se enviarán instrucciones de recuperación."


@pytest.fixture(autouse=True)
def _ajustes_fijos(monkeypatch):
    """Hermético: un backend/.env con otra URL de la web o otro límite no cambia lo que estas pruebas esperan."""
    ajustes = get_settings()
    monkeypatch.setattr(ajustes, "frontend_public_url", "http://localhost:4200")
    monkeypatch.setattr(ajustes, "recuperar_max_solicitudes", 3)
    monkeypatch.setattr(ajustes, "recuperar_ventana_segundos", 3600)


def _registrar(client, codigo: str, email: str = CORREO) -> dict:
    respuesta = client.post(
        f"/api/v1/public/{codigo}/registro",
        json={"nombre": "Cli", "apellido": "Ente", "email": email, "password": CLAVE},
    )
    assert respuesta.status_code == 201
    return respuesta.json()


def _recuperar(client, empresa: str | None, email: str = CORREO):
    cuerpo = {"email": email} if empresa is None else {"empresa": empresa, "email": email}
    return client.post("/api/v1/auth/recuperar", json=cuerpo)


def _token_del_enlace(texto: str) -> str:
    inicio = texto.index("http")
    enlace = texto[inicio:].split()[0]
    return parse_qs(urlparse(enlace).query)["token"][0]


def _enlace_del_correo(enviado: dict) -> str:
    texto = enviado["textContent"]
    return texto[texto.index("http") :].split()[0]


# ---- El correo sale con el enlace correcto ----


def test_el_cliente_recibe_el_enlace_dentro_de_su_tienda(client_por_peticion, dos_empresas, db_session, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch)
    _registrar(client_por_peticion, "tienda-a")

    respuesta = _recuperar(client_por_peticion, "tienda-a")

    assert respuesta.status_code == 202
    assert len(brevo.enviados) == 1
    enviado = brevo.ultimo()
    assert enviado["to"] == [{"email": CORREO, "name": "Cli"}]
    assert enviado["sender"] == {"name": "FashionStore", "email": "remitente@fashionstore.test"}
    assert brevo.cabeceras[0]["api-key"] == "clave-simulada"
    nombre_empresa = db_session.get(Empresa, dos_empresas.a.id).nombre
    assert nombre_empresa in enviado["subject"]
    enlace = _enlace_del_correo(enviado)
    assert enlace.startswith("http://localhost:4200/t/tienda-a/restablecer?token=")
    # El enlace lleva el MISMO token que en local se entrega por token_dev, y aparece en las dos versiones.
    assert _token_del_enlace(enviado["textContent"]) == respuesta.json()["token_dev"]
    assert enlace in enviado["htmlContent"]


def test_el_personal_recibe_el_enlace_del_acceso_del_personal(client_por_peticion, dos_empresas, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch)

    respuesta = _recuperar(client_por_peticion, "tienda-a", "admin@tienda-a.example.com")

    assert respuesta.status_code == 202
    assert len(brevo.enviados) == 1
    enlace = _enlace_del_correo(brevo.ultimo())
    assert enlace.startswith("http://localhost:4200/restablecer?token=")
    assert "/t/" not in enlace


def test_el_enlace_del_correo_sirve_para_cambiar_la_contrasena(client_por_peticion, dos_empresas, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch)
    _registrar(client_por_peticion, "tienda-a")
    _recuperar(client_por_peticion, "tienda-a")
    token = _token_del_enlace(brevo.ultimo()["textContent"])

    cambio = client_por_peticion.post("/api/v1/auth/recuperar/confirmar", json={"token": token, "password": NUEVA})

    assert cambio.status_code == 200
    entrar = client_por_peticion.post(
        "/api/v1/auth/login", json={"empresa": "tienda-a", "email": CORREO, "password": NUEVA}
    )
    assert entrar.status_code == 200


def test_en_produccion_el_correo_sale_y_la_respuesta_no_lleva_el_token(client_por_peticion, dos_empresas, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch)
    _registrar(client_por_peticion, "tienda-a")
    produccion = lambda: SimpleNamespace(environment="production")  # noqa: E731
    monkeypatch.setattr(cu01, "get_settings", produccion)
    monkeypatch.setattr(router_plataforma, "get_settings", produccion)

    respuesta = _recuperar(client_por_peticion, "tienda-a")

    assert respuesta.json() == {"detail": TEXTO, "token_dev": None}
    assert len(brevo.enviados) == 1
    assert "token=" in brevo.ultimo()["textContent"]


# ---- No se envía a quien no corresponde, y la respuesta no cambia ----


def test_no_se_envia_nada_si_la_cuenta_no_existe_y_la_respuesta_es_la_misma(
    client_por_peticion, dos_empresas, db_session, monkeypatch
):
    brevo = SimuladorBrevo(monkeypatch)
    _registrar(client_por_peticion, "tienda-a")
    db_session.execute(Empresa.__table__.update().where(Empresa.id == dos_empresas.b.id).values(activo=False))
    db_session.commit()

    desconocidas = {
        "empresa inexistente": _recuperar(client_por_peticion, "no-existe"),
        "correo inexistente": _recuperar(client_por_peticion, "tienda-a", "nadie@example.com"),
        "correo de otra empresa": _recuperar(client_por_peticion, "tienda-b"),
        "empresa inactiva": _recuperar(client_por_peticion, "tienda-b", "admin@tienda-b.example.com"),
    }

    for nombre, respuesta in desconocidas.items():
        assert respuesta.status_code == 202, nombre
        assert respuesta.json() == {"detail": TEXTO, "token_dev": None}, nombre
    limiter.reset()
    assert _recuperar(client_por_peticion, None, "super@plataforma.example.com").json()["token_dev"] is None
    assert brevo.enviados == []


def test_un_usuario_inactivo_no_recibe_correo(client_por_peticion, dos_empresas, db_session, monkeypatch):
    from app.plataforma.models import Usuario

    brevo = SimuladorBrevo(monkeypatch)
    usuario = _registrar(client_por_peticion, "tienda-a")
    db_session.execute(Usuario.__table__.update().where(Usuario.id == usuario["id"]).values(activo=False))
    db_session.commit()

    respuesta = _recuperar(client_por_peticion, "tienda-a")

    assert respuesta.status_code == 202
    assert brevo.enviados == []


def test_la_recuperacion_de_una_tienda_no_manda_a_la_otra(client_por_peticion, dos_empresas, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch)
    _registrar(client_por_peticion, "tienda-a")
    _registrar(client_por_peticion, "tienda-b")

    _recuperar(client_por_peticion, "tienda-b")

    assert len(brevo.enviados) == 1
    assert "/t/tienda-b/" in _enlace_del_correo(brevo.ultimo())


# ---- Si el correo falla o no está configurado, nada se rompe ----


def test_sin_brevo_configurado_la_recuperacion_responde_igual_y_no_envia(client_por_peticion, dos_empresas, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch, configurado=False)
    _registrar(client_por_peticion, "tienda-a")

    respuesta = _recuperar(client_por_peticion, "tienda-a")

    assert respuesta.status_code == 202
    assert respuesta.json()["detail"] == TEXTO
    assert respuesta.json()["token_dev"]  # en local sigue entregándose
    assert brevo.enviados == []


def test_si_brevo_esta_caido_la_respuesta_no_cambia_y_el_log_no_lleva_datos(
    client_por_peticion, dos_empresas, monkeypatch, caplog
):
    brevo = SimuladorBrevo(monkeypatch)
    brevo.caido = True
    _registrar(client_por_peticion, "tienda-a")

    with caplog.at_level(logging.WARNING):
        respuesta = _recuperar(client_por_peticion, "tienda-a")

    assert respuesta.status_code == 202
    assert respuesta.json()["token_dev"]
    avisos = [r.getMessage() for r in caplog.records if "correo_no_enviado" in r.getMessage()]
    assert len(avisos) == 1
    assert CORREO not in avisos[0] and "token" not in avisos[0].lower()


def test_si_brevo_rechaza_el_mensaje_queda_el_estado_http_en_el_log(client_por_peticion, dos_empresas, monkeypatch, caplog):
    brevo = SimuladorBrevo(monkeypatch)
    brevo.estado_error = 401
    _registrar(client_por_peticion, "tienda-a")

    with caplog.at_level(logging.WARNING):
        respuesta = _recuperar(client_por_peticion, "tienda-a")

    assert respuesta.status_code == 202
    assert any("estado_http=401" in r.getMessage() for r in caplog.records)


# ---- Límite por cuenta ----


def test_pasado_el_limite_por_cuenta_no_hay_token_ni_correo_y_la_respuesta_es_la_misma(
    client_por_peticion, dos_empresas, monkeypatch
):
    brevo = SimuladorBrevo(monkeypatch)
    _registrar(client_por_peticion, "tienda-a")

    respuestas = [_recuperar(client_por_peticion, "tienda-a") for _ in range(4)]

    assert [r.status_code for r in respuestas] == [202, 202, 202, 202]
    assert all(r.json()["detail"] == TEXTO for r in respuestas)
    assert all(r.json()["token_dev"] for r in respuestas[:3])
    assert respuestas[3].json()["token_dev"] is None
    assert len(brevo.enviados) == 3


def test_el_limite_cuenta_tambien_las_cuentas_que_no_existen(client_por_peticion, dos_empresas, monkeypatch):
    """Si solo contara las cuentas reales, el límite delataría cuáles existen."""
    brevo = SimuladorBrevo(monkeypatch)
    monkeypatch.setattr(get_settings(), "recuperar_max_solicitudes", 2)

    for _ in range(3):
        assert _recuperar(client_por_peticion, "tienda-a", "nadie@example.com").status_code == 202
    _registrar(client_por_peticion, "tienda-a", "nadie@example.com")  # ahora SÍ existe, pero ya agotó su cupo

    assert _recuperar(client_por_peticion, "tienda-a", "nadie@example.com").json()["token_dev"] is None
    assert brevo.enviados == []


def test_el_limite_es_por_cuenta_no_global(client_por_peticion, dos_empresas, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch)
    monkeypatch.setattr(get_settings(), "recuperar_max_solicitudes", 1)
    _registrar(client_por_peticion, "tienda-a")
    _registrar(client_por_peticion, "tienda-a", "otro@example.com")

    _recuperar(client_por_peticion, "tienda-a")
    _recuperar(client_por_peticion, "tienda-a", "otro@example.com")

    assert len(brevo.enviados) == 2


# ---- core/correo.py y la plantilla ----


def test_enviar_correo_sin_configurar_lanza_correo_error(monkeypatch):
    SimuladorBrevo(monkeypatch, configurado=False)

    try:
        enviar_correo(MensajeCorreo(para_email="a@example.com", asunto="x", html="<p>x</p>", texto="x"))
    except CorreoError as exc:
        assert exc.status_code is None
    else:  # pragma: no cover
        raise AssertionError("debía lanzar CorreoError")


def test_enviar_correo_sin_romper_devuelve_false_ante_cualquier_fallo(monkeypatch):
    brevo = SimuladorBrevo(monkeypatch)
    mensaje = MensajeCorreo(para_email="a@example.com", asunto="x", html="<p>x</p>", texto="x")
    assert correo.enviar_correo_sin_romper(mensaje) is True
    brevo.estado_error = 500
    assert correo.enviar_correo_sin_romper(mensaje) is False
    brevo.estado_error = None
    brevo.caido = True
    assert correo.enviar_correo_sin_romper(mensaje) is False


def test_la_plantilla_escapa_los_datos_variables():
    mensaje = construir_correo_recuperacion(
        para_email="a@example.com",
        nombre='<script>alert(1)</script>',
        nombre_empresa='Tienda "X" & <b>Cía</b>',
        enlace="http://localhost:4200/restablecer?token=abc",
    )

    assert "<script>" not in mensaje.html
    assert "&lt;script&gt;" in mensaje.html
    assert "<b>Cía</b>" not in mensaje.html
    assert "http://localhost:4200/restablecer?token=abc" in mensaje.html


def test_el_enlace_codifica_el_codigo_y_el_token():
    enlace = enlace_de_recuperacion("tienda a/../x", "a b&c=d", es_cliente=True)

    assert enlace == "http://localhost:4200/t/tienda%20a%2F..%2Fx/restablecer?token=a%20b%26c%3Dd"
