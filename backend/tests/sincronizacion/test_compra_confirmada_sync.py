"""Compra confirmada y sincronización offline (CU-25): una venta de contado con cliente, sincronizada por el personal, avisa
UNA vez al cliente (notificación y correo); una anónima o reenviada no. Brevo y FCM son simulados; ninguna prueba sale a
la red. NO se probó contra Brevo ni Firebase reales."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.plataforma.models import Notificacion
from tests.correo_simulado import SimuladorBrevo
from tests.push_simulado import SimuladorFCM
from tests.sincronizacion.ayudas import armar_venta, enviar


@pytest.fixture()
def avisos(monkeypatch, db_session) -> SimpleNamespace:
    return SimpleNamespace(fcm=SimuladorFCM(monkeypatch, db_session), brevo=SimuladorBrevo(monkeypatch))


def _avisos_de_compra(db_session, usuario_id: int) -> list[Notificacion]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(Notificacion).where(Notificacion.usuario_id == usuario_id, Notificacion.tipo == "compra_confirmada")
        )
    )


def test_una_venta_offline_con_cliente_avisa_una_vez_y_el_reenvio_no_repite(client, db_session, escenario, avisos):
    operacion = armar_venta(escenario)

    primera = enviar(client, escenario.cajero, [operacion])
    assert primera.status_code == 200, primera.text
    assert primera.json()["resultados"][0]["estado"] == "confirmada"
    avisos.fcm.correr()

    (aviso,) = _avisos_de_compra(db_session, escenario.cliente_usuario_id)
    assert "está pagada" in aviso.mensaje and aviso.referencia_id is not None
    (correo,) = avisos.brevo.enviados
    assert correo["to"][0]["email"] == "cliente@example.com"

    reenvio = enviar(client, escenario.cajero, [operacion])  # mismo operacion_id: se devuelve lo guardado
    assert reenvio.json()["resultados"][0]["duplicada"] is True
    avisos.fcm.correr()
    assert len(_avisos_de_compra(db_session, escenario.cliente_usuario_id)) == 1
    assert len(avisos.brevo.enviados) == 1


def test_una_venta_offline_anonima_no_avisa_a_nadie(client, db_session, escenario, avisos):
    respuesta = enviar(client, escenario.cajero, [armar_venta(escenario, cliente_id=None)])

    assert respuesta.json()["resultados"][0]["estado"] == "confirmada"
    avisos.fcm.correr()
    assert avisos.brevo.enviados == []
    assert db_session.scalar(select(Notificacion.id).where(Notificacion.tipo == "compra_confirmada")) is None


def test_una_operacion_que_se_deshace_por_falta_de_stock_no_avisa(client, db_session, escenario, avisos):
    # v2 solo tiene 3 unidades: pedir 5 deja la operación en conflicto y la venta se deshace entera.
    lineas = [{"variante_id": escenario.v2, "cantidad": 5, "precio_unitario": "100.00", "descuento_unitario": "0.00"}]
    respuesta = enviar(client, escenario.cajero, [armar_venta(escenario, lineas=lineas, monto_recibido="500.00")])

    assert respuesta.json()["resultados"][0]["estado"] == "en_conflicto"
    avisos.fcm.correr()
    assert avisos.brevo.enviados == []
    assert _avisos_de_compra(db_session, escenario.cliente_usuario_id) == []
