"""Notificaciones push de la sincronización offline (CU-25): cuando un encargado resuelve una operación en conflicto, el aviso
al operador sale también como push. La notificación se crea con `commit=False` dentro de la transacción de la resolución:
el push solo sale cuando esa transacción confirma. FCM es simulado; ninguna prueba sale a la red. NO se probó contra
Firebase real."""

import pytest

from tests.push_simulado import SimuladorFCM
from tests.sincronizacion.test_resolver_conflicto import _en_conflicto, _resolver

TOKEN = "token-del-telefono-del-cajero-" + "c" * 90


@pytest.fixture()
def fcm(monkeypatch, db_session) -> SimuladorFCM:
    return SimuladorFCM(monkeypatch, db_session)


def test_resolver_un_conflicto_avisa_por_push_al_operador(client, escenario, fcm):
    registro = client.post("/api/v1/dispositivos-push", json={"token": TOKEN, "plataforma": "android"}, headers=escenario.cajero)
    assert registro.status_code == 204
    operacion = _en_conflicto(client, escenario)
    assert fcm.programados == []  # el envío del lote en conflicto no crea avisos

    respuesta = _resolver(client, escenario.encargado, operacion, "rechazar", "No hay forma de cubrirla")

    assert respuesta.status_code == 200, respuesta.text
    assert fcm.correr() == 1
    (cuerpo,) = fcm.mensajes
    assert cuerpo["message"]["token"] == TOKEN
    assert cuerpo["message"]["notification"]["title"] == "Operación sincronizada resuelta"
    assert cuerpo["message"]["data"]["tipo"] == "sincronizacion"
    assert "rechazada" in cuerpo["message"]["notification"]["body"]


def test_una_resolucion_que_falla_no_manda_push(client, escenario, fcm):
    client.post("/api/v1/dispositivos-push", json={"token": TOKEN, "plataforma": "android"}, headers=escenario.cajero)
    operacion = _en_conflicto(client, escenario)
    _resolver(client, escenario.encargado, operacion, "rechazar", "Motivo uno")
    fcm.correr()
    fcm.mensajes.clear()

    contraria = _resolver(client, escenario.encargado, operacion, "forzar")  # ya está rechazada: 409

    assert contraria.status_code == 409
    assert fcm.correr() == 0 and fcm.mensajes == []
