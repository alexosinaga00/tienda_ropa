"""Notificaciones push del pedido sin conexión (CU-13): al cobrarse o rechazarse, la notificación del cliente sale también
como push a sus teléfonos registrados. FCM y PayPal son simulados; ninguna prueba sale a la red. NO se probó contra
Firebase ni contra el sandbox real de PayPal."""

import pytest

from tests.comercial.test_cambio_talla import ctx, reloj  # noqa: F401  (los fixtures se reutilizan)
from tests.comercial.test_pedido_diferido import _cuerpo, _enviar, listo, pp  # noqa: F401
from tests.push_simulado import SimuladorFCM, error_fcm

TOKEN = "token-del-telefono-del-cliente-" + "k" * 90


@pytest.fixture()
def fcm(monkeypatch, db_session) -> SimuladorFCM:
    return SimuladorFCM(monkeypatch, db_session)


def _registrar_telefono(client, headers) -> None:
    assert client.post("/api/v1/dispositivos-push", json={"token": TOKEN, "plataforma": "android"}, headers=headers).status_code == 204


def test_un_pedido_cobrado_manda_el_push_con_la_venta(client, cliente_headers, listo, pp, fcm):
    _registrar_telefono(client, cliente_headers)

    datos = _enviar(client, cliente_headers, _cuerpo(listo)).json()
    assert datos["estado"] == "cobrado"
    assert fcm.mensajes == []  # la respuesta no espera al push
    assert fcm.correr() == 1

    (cuerpo,) = fcm.mensajes
    mensaje = cuerpo["message"]
    assert mensaje["token"] == TOKEN
    assert mensaje["notification"]["title"] == "Cobramos tu pedido"
    assert datos["codigo_venta"] in mensaje["notification"]["body"]
    assert mensaje["data"]["tipo"] == "pedido_diferido" and mensaje["data"]["referencia_id"] == str(datos["venta_id"])
    assert mensaje["data"]["notificacion_id"].isdigit()


def test_un_pedido_rechazado_tambien_manda_el_push(client, cliente_headers, ctx, pp, fcm):  # noqa: F811 - sin PayPal guardado
    _registrar_telefono(client, cliente_headers)

    datos = _enviar(client, cliente_headers, _cuerpo(ctx)).json()
    assert datos["estado"] == "rechazado"
    fcm.correr()

    (cuerpo,) = fcm.mensajes
    assert cuerpo["message"]["notification"]["title"] == "No pudimos cobrar tu pedido"
    assert cuerpo["message"]["data"] == {
        "tipo": "pedido_diferido",
        "referencia_id": "",
        "notificacion_id": cuerpo["message"]["data"]["notificacion_id"],
        "empresa_codigo": "fashionstore",
    }


def test_reenviar_la_misma_operacion_no_repite_el_push(client, cliente_headers, listo, pp, fcm):
    _registrar_telefono(client, cliente_headers)
    cuerpo = _cuerpo(listo)
    _enviar(client, cliente_headers, cuerpo)
    fcm.correr()

    _enviar(client, cliente_headers, cuerpo)  # reenvío: devuelve lo guardado y no crea otro aviso
    fcm.correr()

    assert len(fcm.mensajes) == 1


def test_fcm_caido_no_cambia_el_resultado_del_pedido(client, cliente_headers, listo, pp, fcm):
    _registrar_telefono(client, cliente_headers)
    fcm.estado_global = error_fcm(503, "UNAVAILABLE")

    datos = _enviar(client, cliente_headers, _cuerpo(listo)).json()
    fcm.correr()  # no lanza

    assert datos["estado"] == "cobrado" and pp.cobros_vault == 1
    avisos = client.get("/api/v1/notificaciones", headers=cliente_headers).json()
    assert [a["titulo"] for a in avisos] == ["Cobramos tu pedido"]


def test_sin_telefono_registrado_el_pedido_no_llama_a_fcm(client, cliente_headers, listo, pp, fcm):
    assert _enviar(client, cliente_headers, _cuerpo(listo)).json()["estado"] == "cobrado"

    fcm.correr()

    assert fcm.mensajes == [] and fcm.peticiones_oauth == []
