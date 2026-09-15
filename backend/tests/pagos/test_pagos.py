import hashlib
import hmac
import json

import pytest

from app.pagos.pasarela import LibelulaGateway
from tests.conftest import crear_cajero

SECRETO_LIBELULA = "sandbox-secret-libelula"


def _firmar(payload: dict) -> tuple[bytes, str]:
    cuerpo = json.dumps(payload).encode("utf-8")
    firma = hmac.new(SECRETO_LIBELULA.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()
    return cuerpo, firma


@pytest.fixture()
def contexto(client, admin_headers, db_session):
    cat = client.post("/api/v1/categorias", json={"nombre": "Camisas Pago"}, headers=admin_headers).json()
    talla = client.post("/api/v1/tallas", json={"codigo": "M", "orden": 1}, headers=admin_headers).json()
    color = client.post("/api/v1/colores", json={"nombre": "Azul Pago"}, headers=admin_headers).json()
    producto = client.post(
        "/api/v1/productos",
        json={
            "codigo": "PAG-1",
            "nombre": "Camisa pago",
            "categoria_id": cat["id"],
            "precio_base": "100.00",
            "tallas_ids": [talla["id"]],
            "colores_ids": [color["id"]],
        },
        headers=admin_headers,
    ).json()
    variantes = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()
    variante_id = variantes[0]["id"]

    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": "Santa Cruz Pago", "departamento": "Santa Cruz"}, headers=admin_headers
    ).json()
    sucursal = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-PAG", "nombre": "Sucursal Pago", "direccion": "Av. 1"},
        headers=admin_headers,
    ).json()
    sucursal_id = sucursal["id"]

    client.post(
        "/api/v1/inventario/movimientos",
        json={
            "variante_id": variante_id,
            "sucursal_id": sucursal_id,
            "tipo_movimiento_codigo": "recepcion",
            "cantidad": 10,
            "costo_unitario": "10.00",
        },
        headers=admin_headers,
    )

    cajero_headers = crear_cajero(client, admin_headers, db_session, sucursal_id=sucursal_id)

    return {"variante_id": variante_id, "sucursal_id": sucursal_id, "cajero_headers": cajero_headers}


def _stock(client, headers, ctx):
    return client.get(f"/api/v1/inventario/stock/{ctx['variante_id']}/{ctx['sucursal_id']}", headers=headers).json()


def _crear_venta(client, ctx, cantidad=1):
    return client.post(
        "/api/v1/ventas/presencial",
        json={"sucursal_id": ctx["sucursal_id"], "detalle": [{"variante_id": ctx["variante_id"], "cantidad": cantidad}]},
        headers=ctx["cajero_headers"],
    ).json()


# ---- cálculo de cambio -----------------------------------------------------------------


def test_calculo_de_cambio_en_efectivo(client, contexto):
    venta = _crear_venta(client, contexto, cantidad=2)  # total = 200.00

    respuesta = client.post(
        "/api/v1/pagos/caja",
        json={"venta_id": venta["id"], "metodo_pago": "efectivo", "monto_recibido": "250.00"},
        headers=contexto["cajero_headers"],
    )
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["cambio"] == "50.00"
    assert cuerpo["pago"]["estado"] == "aprobado"


def test_efectivo_no_alcanza_no_se_puede_pagar(client, contexto):
    venta = _crear_venta(client, contexto, cantidad=2)  # total = 200.00

    respuesta = client.post(
        "/api/v1/pagos/caja",
        json={"venta_id": venta["id"], "metodo_pago": "efectivo", "monto_recibido": "100.00"},
        headers=contexto["cajero_headers"],
    )
    assert respuesta.status_code == 400


def test_pago_con_qr_no_tiene_cambio(client, contexto):
    venta = _crear_venta(client, contexto, cantidad=1)
    respuesta = client.post(
        "/api/v1/pagos/caja", json={"venta_id": venta["id"], "metodo_pago": "qr"}, headers=contexto["cajero_headers"]
    )
    assert respuesta.status_code == 201
    assert respuesta.json()["cambio"] is None


# ---- pago rechazado no descuenta stock -------------------------------------------------


def test_pago_rechazado_no_descuenta_stock(client, admin_headers, cliente_headers, contexto):
    client.post("/api/v1/carrito", json={"variante_id": contexto["variante_id"], "cantidad": 3}, headers=cliente_headers)
    venta = client.post(
        "/api/v1/ventas/digital", json={"sucursal_id": contexto["sucursal_id"]}, headers=cliente_headers
    ).json()

    disponible_antes = _stock(client, admin_headers, contexto)["cantidad_disponible"]
    fisica_antes = _stock(client, admin_headers, contexto)["cantidad_fisica"]

    inicio = client.post(
        "/api/v1/pagos/iniciar", json={"venta_id": venta["id"], "metodo_pago": "libelula"}, headers=cliente_headers
    ).json()
    id_transaccion = inicio["pago"]["referencia_externa"]

    cuerpo, firma = _firmar({"id_transaccion": id_transaccion, "estado": "rechazado"})
    webhook = client.post(
        "/api/v1/pagos/webhook/libelula", content=cuerpo, headers={"Content-Type": "application/json", "x-signature": firma}
    )
    assert webhook.status_code == 200
    assert webhook.json()["estado"] == "rechazado"

    stock_final = _stock(client, admin_headers, contexto)
    assert stock_final["cantidad_fisica"] == fisica_antes  # nunca se descontó
    assert stock_final["cantidad_reservada"] == 0  # pero la reserva se liberó
    assert stock_final["cantidad_disponible"] == fisica_antes  # vuelve a estar disponible

    venta_final = client.get(f"/api/v1/ventas/{venta['id']}/comprobante", headers=admin_headers).json()
    assert venta_final["estado"] == "anulada"


# ---- webhook duplicado no duplica la venta (idempotencia) ------------------------------


def test_webhook_duplicado_no_duplica_venta(client, admin_headers, cliente_headers, contexto):
    client.post("/api/v1/carrito", json={"variante_id": contexto["variante_id"], "cantidad": 2}, headers=cliente_headers)
    venta = client.post(
        "/api/v1/ventas/digital", json={"sucursal_id": contexto["sucursal_id"]}, headers=cliente_headers
    ).json()

    fisica_antes = _stock(client, admin_headers, contexto)["cantidad_fisica"]

    inicio = client.post(
        "/api/v1/pagos/iniciar", json={"venta_id": venta["id"], "metodo_pago": "libelula"}, headers=cliente_headers
    ).json()
    id_transaccion = inicio["pago"]["referencia_externa"]
    cuerpo, firma = _firmar({"id_transaccion": id_transaccion, "estado": "aprobado"})
    headers_webhook = {"Content-Type": "application/json", "x-signature": firma}

    primero = client.post("/api/v1/pagos/webhook/libelula", content=cuerpo, headers=headers_webhook)
    assert primero.status_code == 200
    assert primero.json()["estado"] == "aprobado"

    stock_tras_primero = _stock(client, admin_headers, contexto)
    assert stock_tras_primero["cantidad_fisica"] == fisica_antes - 2

    # Mismo webhook, mandado de nuevo (red flaky / la pasarela reintentando).
    segundo = client.post("/api/v1/pagos/webhook/libelula", content=cuerpo, headers=headers_webhook)
    assert segundo.status_code == 200
    assert segundo.json()["estado"] == "aprobado"

    stock_tras_segundo = _stock(client, admin_headers, contexto)
    assert stock_tras_segundo["cantidad_fisica"] == fisica_antes - 2  # NO se descontó una segunda vez

    # No hay una venta duplicada: sigue existiendo solo esta.
    mis_compras = client.get("/api/v1/ventas/mis-compras", headers=cliente_headers).json()
    assert len(mis_compras) == 1


# ---- reintentar con un pago iniciado que nunca se completó -----------------------------


def _venta_con_pago_iniciado(client, cliente_headers, contexto):
    client.post("/api/v1/carrito", json={"variante_id": contexto["variante_id"], "cantidad": 1}, headers=cliente_headers)
    venta = client.post(
        "/api/v1/ventas/digital", json={"sucursal_id": contexto["sucursal_id"]}, headers=cliente_headers
    ).json()
    inicio = client.post(
        "/api/v1/pagos/iniciar", json={"venta_id": venta["id"], "metodo_pago": "libelula"}, headers=cliente_headers
    )
    assert inicio.status_code == 201
    return venta, inicio.json()["pago"]


def test_reintentar_reemplaza_pago_iniciado_sin_anular_la_venta(client, admin_headers, cliente_headers, contexto):
    venta, pago_viejo = _venta_con_pago_iniciado(client, cliente_headers, contexto)

    reintento = client.post(
        "/api/v1/pagos/iniciar", json={"venta_id": venta["id"], "metodo_pago": "libelula"}, headers=cliente_headers
    )
    assert reintento.status_code == 201
    assert reintento.json()["pago"]["id"] != pago_viejo["id"]

    viejo = client.get(f"/api/v1/pagos/{pago_viejo['id']}/estado", headers=cliente_headers).json()
    assert viejo["estado"] == "rechazado"
    venta_final = client.get(f"/api/v1/ventas/{venta['id']}/comprobante", headers=admin_headers).json()
    assert venta_final["estado"] == "pendiente_pago"


def test_reintentar_si_la_pasarela_ya_cobro_no_inicia_otro_pago(
    client, admin_headers, cliente_headers, contexto, monkeypatch
):
    venta, pago_viejo = _venta_con_pago_iniciado(client, cliente_headers, contexto)
    monkeypatch.setattr(LibelulaGateway, "consultar_estado", lambda self, id_transaccion: "aprobado")

    reintento = client.post(
        "/api/v1/pagos/iniciar", json={"venta_id": venta["id"], "metodo_pago": "libelula"}, headers=cliente_headers
    )
    assert reintento.status_code == 409

    viejo = client.get(f"/api/v1/pagos/{pago_viejo['id']}/estado", headers=cliente_headers).json()
    assert viejo["estado"] == "aprobado"
    venta_final = client.get(f"/api/v1/ventas/{venta['id']}/comprobante", headers=admin_headers).json()
    assert venta_final["estado"] == "pagada"


def test_webhook_con_firma_invalida_se_rechaza(client, cliente_headers, contexto):
    client.post("/api/v1/carrito", json={"variante_id": contexto["variante_id"], "cantidad": 1}, headers=cliente_headers)
    venta = client.post(
        "/api/v1/ventas/digital", json={"sucursal_id": contexto["sucursal_id"]}, headers=cliente_headers
    ).json()
    inicio = client.post(
        "/api/v1/pagos/iniciar", json={"venta_id": venta["id"], "metodo_pago": "libelula"}, headers=cliente_headers
    ).json()
    id_transaccion = inicio["pago"]["referencia_externa"]

    cuerpo = json.dumps({"id_transaccion": id_transaccion, "estado": "aprobado"}).encode("utf-8")
    respuesta = client.post(
        "/api/v1/pagos/webhook/libelula",
        content=cuerpo,
        headers={"Content-Type": "application/json", "x-signature": "firma-trucha"},
    )
    assert respuesta.status_code == 403
