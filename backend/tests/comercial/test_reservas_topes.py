"""Topes de una reserva que hace el CLIENTE: fecha cercana, pocas unidades y pocas reservas abiertas. Sin ellos, un solo cliente
podía apartar todo el stock con una visita en el año 2099."""

import datetime as dt

import pytest

from app.core.config import get_settings
from tests.comercial.test_reservas import _payload_reserva, contexto  # noqa: F401  (el fixture se reutiliza)

RESERVAS = "/api/v1/reservas"


def _con_fecha(ctx, fecha: dt.date, **extra) -> dict:
    return {**_payload_reserva(ctx, **extra), "fecha_visita": fecha.isoformat()}


def _reservar(client, headers, cuerpo):
    return client.post(RESERVAS, json=cuerpo, headers=headers)


# ---- fecha de la visita ----


def test_una_fecha_ya_pasada_se_rechaza_con_400(client, cliente_headers, contexto):  # noqa: F811
    ayer = dt.date.today() - dt.timedelta(days=3)

    respuesta = _reservar(client, cliente_headers, _con_fecha(contexto, ayer))

    assert respuesta.status_code == 400
    assert "ya pasó" in respuesta.json()["detail"]


def test_una_visita_en_el_anio_2099_se_rechaza_con_400(client, cliente_headers, contexto):  # noqa: F811
    respuesta = _reservar(client, cliente_headers, _con_fecha(contexto, dt.date(2099, 1, 7)))

    assert respuesta.status_code == 400
    assert "días de anticipación" in respuesta.json()["detail"]


def test_una_visita_pasado_el_limite_de_anticipacion_se_rechaza_y_dentro_del_limite_se_acepta(
    client, cliente_headers, monkeypatch, contexto  # noqa: F811
):
    monkeypatch.setattr(get_settings(), "reserva_max_dias_anticipacion", 14)
    dentro = dt.date.fromisoformat(contexto["fecha_visita"])  # un miércoles entre 7 y 13 días adelante
    fuera = dentro + dt.timedelta(days=14)  # el miércoles siguiente al límite

    assert _reservar(client, cliente_headers, _con_fecha(contexto, fuera)).status_code == 400
    assert _reservar(client, cliente_headers, _con_fecha(contexto, dentro)).status_code == 201


# ---- unidades ----


def test_una_linea_con_mas_unidades_que_el_tope_se_rechaza(client, cliente_headers, contexto):  # noqa: F811
    tope = get_settings().reserva_max_unidades_por_linea

    respuesta = _reservar(client, cliente_headers, _payload_reserva(contexto, cantidad=tope + 1))

    assert respuesta.status_code == 400
    assert f"hasta {tope} unidades de cada prenda" in respuesta.json()["detail"]


def test_el_total_de_unidades_de_una_reserva_tiene_tope(client, cliente_headers, monkeypatch, contexto):  # noqa: F811
    monkeypatch.setattr(get_settings(), "reserva_max_unidades", 3)

    respuesta = _reservar(client, cliente_headers, _payload_reserva(contexto, cantidad=4))

    assert respuesta.status_code == 400
    assert "hasta 3 unidades en total" in respuesta.json()["detail"]


def test_una_reserva_dentro_de_los_topes_se_acepta(client, cliente_headers, contexto):  # noqa: F811
    assert _reservar(client, cliente_headers, _payload_reserva(contexto, cantidad=2)).status_code == 201


# ---- reservas abiertas por cliente ----


def test_un_cliente_no_puede_tener_mas_reservas_abiertas_que_el_tope(client, cliente_headers, monkeypatch, contexto):  # noqa: F811
    monkeypatch.setattr(get_settings(), "reserva_max_activas_por_cliente", 2)
    franjas = [("09:00:00", "10:00:00"), ("11:00:00", "12:00:00"), ("13:00:00", "14:00:00")]
    resultados = [
        _reservar(client, cliente_headers, _payload_reserva(contexto, hora_desde=desde, hora_hasta=hasta))
        for desde, hasta in franjas
    ]

    assert [r.status_code for r in resultados] == [201, 201, 400]
    assert "reservas abiertas" in resultados[2].json()["detail"]


def test_cancelar_una_reserva_libera_un_lugar_del_tope(client, cliente_headers, monkeypatch, contexto):  # noqa: F811
    monkeypatch.setattr(get_settings(), "reserva_max_activas_por_cliente", 1)
    primera = _reservar(client, cliente_headers, _payload_reserva(contexto))
    assert primera.status_code == 201
    assert _reservar(client, cliente_headers, _payload_reserva(contexto, hora_desde="12:00:00", hora_hasta="13:00:00")).status_code == 400

    cancelada = client.delete(f"{RESERVAS}/{primera.json()['id']}", headers=cliente_headers)
    assert cancelada.status_code == 200, cancelada.text

    assert _reservar(client, cliente_headers, _payload_reserva(contexto, hora_desde="12:00:00", hora_hasta="13:00:00")).status_code == 201


def test_el_tope_de_cada_cliente_es_propio(client, cliente_headers, monkeypatch, contexto):  # noqa: F811
    """Las reservas abiertas de otra persona no agotan el lugar de este cliente."""
    monkeypatch.setattr(get_settings(), "reserva_max_activas_por_cliente", 1)
    client.post(
        "/api/v1/public/fashionstore/registro",
        json={"nombre": "Otra", "apellido": "Persona", "email": "otra@example.com", "password": "claveSegura123"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"empresa": "fashionstore", "email": "otra@example.com", "password": "claveSegura123"}
    ).json()["access_token"]
    otra = {"Authorization": f"Bearer {token}"}

    assert _reservar(client, otra, _payload_reserva(contexto)).status_code == 201

    assert _reservar(client, cliente_headers, _payload_reserva(contexto, hora_desde="12:00:00", hora_hasta="13:00:00")).status_code == 201


@pytest.mark.parametrize("campo, valor", [("reserva_max_dias_anticipacion", 0), ("reserva_max_unidades_por_linea", 0)])
def test_los_topes_no_pueden_ser_cero(campo, valor):
    from app.core.config import Settings

    with pytest.raises(ValueError):
        Settings(_env_file=None, database_url="sqlite://", jwt_secret_key="k" * 40, **{campo: valor})
