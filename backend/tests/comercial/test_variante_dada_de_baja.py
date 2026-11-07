"""Dar de baja una prenda NO puede impedir confirmar el pago de una venta pendiente, ni anular, devolver o cambiar lo que ya se
vendió (antes respondía 404 y, con PayPal, el dinero quedaba cobrado sin venta). Vender o reservar la prenda de nuevo sigue
prohibido."""

import pytest

from tests.comercial.test_compra_confirmada import _iniciar, _venta_digital, _webhook
from tests.comercial.test_pagos import contexto  # noqa: F401  (el fixture se reutiliza)
from tests.comercial.test_reservas import _payload_reserva

# `_webhook` firma con el secreto de Libélula (la pasarela de prueba).


def _stock(client, headers, ctx) -> dict:  # noqa: F811
    return client.get(f"/api/v1/inventario/stock/{ctx['variante_id']}/{ctx['sucursal_id']}", headers=headers).json()


def _dar_de_baja(client, admin_headers, ctx) -> None:  # noqa: F811
    assert client.delete(f"/api/v1/variantes/{ctx['variante_id']}", headers=admin_headers).status_code == 204


def _vender_y_cobrar_en_caja(client, ctx, cantidad=2) -> dict:  # noqa: F811
    venta = client.post(
        "/api/v1/ventas/presencial",
        json={"sucursal_id": ctx["sucursal_id"], "detalle": [{"variante_id": ctx["variante_id"], "cantidad": cantidad}]},
        headers=ctx["cajero_headers"],
    )
    assert venta.status_code == 201, venta.text
    pago = client.post(
        "/api/v1/pagos/caja", json={"venta_id": venta.json()["id"], "metodo_pago": "qr"}, headers=ctx["cajero_headers"]
    )
    assert pago.status_code == 201, pago.text
    return {"venta": venta.json(), "pago": pago.json()["pago"]}


def test_el_pago_aprobado_de_una_venta_pendiente_se_confirma_aunque_la_prenda_se_de_de_baja(
    client, admin_headers, cliente_headers, contexto  # noqa: F811
):
    venta = _venta_digital(client, contexto, cliente_headers, cantidad=2)
    inicio = _iniciar(client, cliente_headers, venta)
    _dar_de_baja(client, admin_headers, contexto)  # la tienda descontinúa la prenda mientras el cliente paga

    respuesta = _webhook(client, inicio["pago"]["referencia_externa"])

    assert respuesta.status_code == 200, respuesta.text
    compras = client.get("/api/v1/ventas/mis-compras", headers=cliente_headers).json()
    assert [c["estado"] for c in compras] == ["pagada"]
    stock = _stock(client, admin_headers, contexto)
    assert stock["cantidad_fisica"] == 8 and stock["cantidad_reservada"] == 0  # salió del stock y se liberó el apartado


def test_se_puede_anular_una_venta_pagada_de_una_prenda_dada_de_baja(client, admin_headers, contexto):  # noqa: F811
    cobro = _vender_y_cobrar_en_caja(client, contexto, cantidad=2)
    _dar_de_baja(client, admin_headers, contexto)

    anulacion = client.post(f"/api/v1/pagos/{cobro['pago']['id']}/anular", headers=admin_headers)

    assert anulacion.status_code == 200, anulacion.text
    assert _stock(client, admin_headers, contexto)["cantidad_fisica"] == 10  # la prenda volvió al stock


def test_se_puede_devolver_una_prenda_que_ya_se_vendio_y_hoy_esta_dada_de_baja(client, admin_headers, contexto):  # noqa: F811
    cobro = _vender_y_cobrar_en_caja(client, contexto, cantidad=2)
    _dar_de_baja(client, admin_headers, contexto)

    devolucion = client.post(
        "/api/v1/devoluciones",
        json={
            "venta_id": cobro["venta"]["id"],
            "detalle": [{"venta_detalle_id": cobro["venta"]["detalle"][0]["id"], "cantidad": 1}],
        },
        headers=contexto["cajero_headers"],
    )

    assert devolucion.status_code == 201, devolucion.text
    assert _stock(client, admin_headers, contexto)["cantidad_fisica"] == 9


def test_la_prenda_dada_de_baja_no_se_puede_vender_de_nuevo(client, admin_headers, contexto):  # noqa: F811
    _dar_de_baja(client, admin_headers, contexto)

    venta = client.post(
        "/api/v1/ventas/presencial",
        json={"sucursal_id": contexto["sucursal_id"], "detalle": [{"variante_id": contexto["variante_id"], "cantidad": 1}]},
        headers=contexto["cajero_headers"],
    )

    assert venta.status_code == 404


def test_la_prenda_dada_de_baja_no_se_puede_reservar(client, admin_headers, cliente_headers, contexto):  # noqa: F811
    _dar_de_baja(client, admin_headers, contexto)

    reserva = client.post(
        "/api/v1/reservas",
        json={**_payload_reserva({**contexto, "fecha_visita": _un_miercoles_proximo()}), "fecha_visita": _un_miercoles_proximo()},
        headers=cliente_headers,
    )

    assert reserva.status_code in (400, 404)  # antes de llegar al stock se rechaza


def _un_miercoles_proximo() -> str:
    import datetime as dt

    base = dt.date.today() + dt.timedelta(days=7)
    return (base + dt.timedelta(days=(3 - base.isoweekday()) % 7)).isoformat()


@pytest.mark.parametrize("tipo", ["recepcion", "ajuste_positivo"])
def test_el_inventario_admite_movimientos_de_una_variante_dada_de_baja(client, admin_headers, contexto, tipo):  # noqa: F811
    """Un ajuste manual de una prenda descontinuada (por ejemplo, dar de baja el saldo que queda) no debe dar 404."""
    _dar_de_baja(client, admin_headers, contexto)

    cuerpo = {
        "variante_id": contexto["variante_id"],
        "sucursal_id": contexto["sucursal_id"],
        "tipo_movimiento_codigo": tipo,
        "cantidad": 1,
        **({"costo_unitario": "10.00"} if tipo == "recepcion" else {}),
    }
    respuesta = client.post("/api/v1/inventario/movimientos", json=cuerpo, headers=admin_headers)

    assert respuesta.status_code == 201, respuesta.text
