"""El costo de una prenda es el margen del negocio: el COMPRADOR no lo ve en ninguna respuesta de venta (compra digital, "Mis
compras" y comprobante). El personal de ventas (Caja, administrador) sí, porque lo usa para sus reportes."""

from tests.comercial.test_pagos import contexto  # noqa: F401  (el fixture se reutiliza)


def _comprar(client, cliente_headers, contexto, cantidad=1) -> dict:  # noqa: F811
    client.post(
        "/api/v1/carrito", json={"variante_id": contexto["variante_id"], "cantidad": cantidad}, headers=cliente_headers
    )
    respuesta = client.post("/api/v1/ventas/digital", json={"sucursal_id": contexto["sucursal_id"]}, headers=cliente_headers)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _cobrar_en_caja(client, contexto, venta_id) -> None:  # noqa: F811
    pago = client.post(
        "/api/v1/pagos/caja", json={"venta_id": venta_id, "metodo_pago": "qr"}, headers=contexto["cajero_headers"]
    )
    assert pago.status_code == 201, pago.text


def _costos(venta: dict) -> list:
    return [linea["costo_unitario"] for linea in venta["detalle"]]


def test_la_compra_digital_no_devuelve_el_costo_al_comprador(client, cliente_headers, contexto):  # noqa: F811
    venta = _comprar(client, cliente_headers, contexto)

    assert _costos(venta) == [None]


def test_mis_compras_y_el_comprobante_del_comprador_no_traen_el_costo(client, cliente_headers, contexto):  # noqa: F811
    venta = _comprar(client, cliente_headers, contexto)
    _cobrar_en_caja(client, contexto, venta["id"])

    mis_compras = client.get("/api/v1/ventas/mis-compras", headers=cliente_headers).json()
    comprobante = client.get(f"/api/v1/ventas/{venta['id']}/comprobante", headers=cliente_headers).json()

    assert [_costos(v) for v in mis_compras] == [[None]]
    assert _costos(comprobante) == [None]
    assert comprobante["detalle"][0]["precio_unitario"] == "100.00"  # el precio sí se ve


def test_el_personal_sigue_viendo_el_costo_congelado(client, admin_headers, cliente_headers, contexto):  # noqa: F811
    venta = _comprar(client, cliente_headers, contexto)
    _cobrar_en_caja(client, contexto, venta["id"])

    comprobante_admin = client.get(f"/api/v1/ventas/{venta['id']}/comprobante", headers=admin_headers).json()
    comprobante_cajero = client.get(
        f"/api/v1/ventas/{venta['id']}/comprobante", headers=contexto["cajero_headers"]
    ).json()
    ventas_de_la_sucursal = client.get(
        f"/api/v1/ventas/sucursal/{contexto['sucursal_id']}", headers=contexto["cajero_headers"]
    ).json()

    assert _costos(comprobante_admin) == ["10.0000"]
    assert _costos(comprobante_cajero) == ["10.0000"]
    assert [_costos(v) for v in ventas_de_la_sucursal] == [["10.0000"]]


def test_una_venta_presencial_en_caja_conserva_el_costo_para_el_cajero(client, contexto):  # noqa: F811
    venta = client.post(
        "/api/v1/ventas/presencial",
        json={"sucursal_id": contexto["sucursal_id"], "detalle": [{"variante_id": contexto["variante_id"], "cantidad": 1}]},
        headers=contexto["cajero_headers"],
    )

    assert venta.status_code == 201, venta.text
    assert "costo_unitario" in venta.json()["detalle"][0]  # el campo sigue existiendo para el personal


def test_ninguna_respuesta_del_comprador_contiene_el_costo_en_el_texto(client, cliente_headers, contexto):  # noqa: F811
    venta = _comprar(client, cliente_headers, contexto)
    _cobrar_en_caja(client, contexto, venta["id"])

    for ruta in ("/api/v1/ventas/mis-compras", f"/api/v1/ventas/{venta['id']}/comprobante"):
        assert "10.0000" not in client.get(ruta, headers=cliente_headers).text
