"""Una promoción por porcentaje no puede superar 100 (tampoco al editarla) y una venta no puede quedar con total cero: la Caja no
acepta cobrar 0 y el pago exige un monto mayor a cero, así que quedaría pendiente de pago hasta expirar."""

import datetime as dt

from tests.comercial.test_ventas import _payload_presencial, _stock, contexto  # noqa: F401  (el fixture se reutiliza)

PROMOCIONES = "/api/v1/promociones"


def _crear_promocion(client, headers, ctx, *, tipo="porcentaje", valor="20") -> dict:  # noqa: F811
    hoy = dt.date.today()
    respuesta = client.post(
        PROMOCIONES,
        json={
            "nombre": "Promoción de prueba",
            "tipo": tipo,
            "valor": valor,
            "fecha_inicio": (hoy - dt.timedelta(days=1)).isoformat(),
            "fecha_fin": (hoy + dt.timedelta(days=1)).isoformat(),
            "alcances": [{"categoria_id": ctx["categoria_id"]}],
        },
        headers=headers,
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


# ---- porcentaje de la promoción ----


def test_al_crear_un_porcentaje_mayor_a_100_se_rechaza(client, admin_headers, contexto):  # noqa: F811
    hoy = dt.date.today()
    respuesta = client.post(
        PROMOCIONES,
        json={
            "nombre": "Regalo",
            "tipo": "porcentaje",
            "valor": "150",
            "fecha_inicio": hoy.isoformat(),
            "fecha_fin": (hoy + dt.timedelta(days=1)).isoformat(),
            "alcances": [{"categoria_id": contexto["categoria_id"]}],
        },
        headers=admin_headers,
    )

    assert respuesta.status_code == 422


def test_al_editar_un_porcentaje_a_mas_de_100_se_rechaza_y_la_promocion_no_cambia(client, admin_headers, contexto):  # noqa: F811
    promocion = _crear_promocion(client, admin_headers, contexto, valor="20")

    respuesta = client.put(f"{PROMOCIONES}/{promocion['id']}", json={"valor": "500"}, headers=admin_headers)

    assert respuesta.status_code == 400
    assert "no puede superar 100" in respuesta.json()["detail"]
    assert client.get(f"{PROMOCIONES}/{promocion['id']}", headers=admin_headers).json()["valor"] == "20.00"


def test_al_editar_un_porcentaje_a_un_valor_valido_se_acepta(client, admin_headers, contexto):  # noqa: F811
    promocion = _crear_promocion(client, admin_headers, contexto, valor="20")

    respuesta = client.put(f"{PROMOCIONES}/{promocion['id']}", json={"valor": "100"}, headers=admin_headers)

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["valor"] == "100.00"


def test_un_descuento_por_monto_si_puede_ser_mayor_a_100(client, admin_headers, contexto):  # noqa: F811
    promocion = _crear_promocion(client, admin_headers, contexto, tipo="monto", valor="30")

    respuesta = client.put(f"{PROMOCIONES}/{promocion['id']}", json={"valor": "250"}, headers=admin_headers)

    assert respuesta.status_code == 200, respuesta.text


# ---- ventas con total cero ----


def test_una_venta_con_descuento_del_100_por_ciento_se_rechaza_y_no_aparta_stock(client, admin_headers, contexto):  # noqa: F811
    _crear_promocion(client, admin_headers, contexto, valor="100")
    antes = _stock(client, contexto["cajero_headers"], contexto)

    venta = client.post(
        "/api/v1/ventas/presencial", json=_payload_presencial(contexto, cantidad=1), headers=contexto["cajero_headers"]
    )

    assert venta.status_code == 400
    assert "total es cero" in venta.json()["detail"]
    assert _stock(client, contexto["cajero_headers"], contexto) == antes  # nada quedó apartado


def test_una_venta_con_descuento_parcial_sigue_funcionando(client, admin_headers, contexto):  # noqa: F811
    _crear_promocion(client, admin_headers, contexto, valor="20")

    venta = client.post(
        "/api/v1/ventas/presencial", json=_payload_presencial(contexto, cantidad=1), headers=contexto["cajero_headers"]
    )

    assert venta.status_code == 201, venta.text
    assert venta.json()["total"] == "80.00"
