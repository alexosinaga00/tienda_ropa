import datetime as dt
import hashlib
import hmac
import json

import pytest

from app.pagos import service as pagos_service
from app.pagos.pasarela import LibelulaGateway
from app.ventas.models import Venta
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

    # Las prendas vuelven al carrito para poder reintentar la compra.
    carrito = client.get("/api/v1/carrito", headers=cliente_headers).json()
    assert [(l["variante_id"], l["cantidad"]) for l in carrito["detalle"]] == [(contexto["variante_id"], 3)]


# ---- cancelar / vencer una compra que nunca se pagó -----------------------------------


def test_cancelar_compra_libera_stock_y_devuelve_el_carrito(client, admin_headers, cliente_headers, contexto):
    fisica = _stock(client, admin_headers, contexto)["cantidad_fisica"]
    venta, _ = _venta_con_pago_iniciado(client, cliente_headers, contexto)
    assert _stock(client, admin_headers, contexto)["cantidad_reservada"] == 1

    respuesta = client.post(f"/api/v1/pagos/venta/{venta['id']}/cancelar", headers=cliente_headers)
    assert respuesta.status_code == 200

    stock = _stock(client, admin_headers, contexto)
    assert stock["cantidad_reservada"] == 0
    assert stock["cantidad_fisica"] == fisica
    venta_final = client.get(f"/api/v1/ventas/{venta['id']}/comprobante", headers=admin_headers).json()
    assert venta_final["estado"] == "anulada"
    carrito = client.get("/api/v1/carrito", headers=cliente_headers).json()
    assert [(l["variante_id"], l["cantidad"]) for l in carrito["detalle"]] == [(contexto["variante_id"], 1)]

    # Cancelar dos veces no vuelve a tocar nada.
    assert client.post(f"/api/v1/pagos/venta/{venta['id']}/cancelar", headers=cliente_headers).status_code == 409


def test_cancelar_compra_que_la_pasarela_ya_cobro_la_deja_pagada(
    client, admin_headers, cliente_headers, contexto, monkeypatch
):
    venta, _ = _venta_con_pago_iniciado(client, cliente_headers, contexto)
    monkeypatch.setattr(LibelulaGateway, "consultar_estado", lambda self, id_transaccion: "aprobado")

    respuesta = client.post(f"/api/v1/pagos/venta/{venta['id']}/cancelar", headers=cliente_headers)
    assert respuesta.status_code == 409
    venta_final = client.get(f"/api/v1/ventas/{venta['id']}/comprobante", headers=admin_headers).json()
    assert venta_final["estado"] == "pagada"


def test_expirar_ventas_pendientes_solo_toca_las_vencidas(
    client, admin_headers, cliente_headers, contexto, db_session
):
    vieja, _ = _venta_con_pago_iniciado(client, cliente_headers, contexto)
    nueva, _ = _venta_con_pago_iniciado(client, cliente_headers, contexto)

    db_session.get(Venta, vieja["id"]).fecha = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(
        hours=2
    )
    db_session.commit()

    resultado = pagos_service.expirar_ventas_pendientes(db_session)
    assert resultado == {"anuladas": 1, "pagadas": 0}

    estado = lambda v: client.get(f"/api/v1/ventas/{v['id']}/comprobante", headers=admin_headers).json()["estado"]
    assert estado(vieja) == "anulada"
    assert estado(nueva) == "pendiente_pago"
    assert _stock(client, admin_headers, contexto)["cantidad_reservada"] == 1  # solo la nueva sigue reservando


def test_tarea_expirar_ventas_pendientes_requiere_token(client):
    assert client.post("/api/v1/tareas/expirar-ventas-pendientes").status_code == 401
    respuesta = client.post(
        "/api/v1/tareas/expirar-ventas-pendientes", headers={"X-Service-Token": "token-de-pruebas"}
    )
    assert respuesta.status_code == 200


def test_deposito_no_acepta_retiro_ni_reservas_pero_si_despacha(client, admin_headers, cliente_headers, contexto):
    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": "Ciudad Deposito", "departamento": "Santa Cruz"}, headers=admin_headers
    ).json()
    deposito = client.post(
        "/api/v1/sucursales",
        json={
            "ciudad_id": ciudad["id"],
            "codigo": "DEP-1",
            "nombre": "Deposito",
            "direccion": "Parque industrial",
            "es_deposito": True,
        },
        headers=admin_headers,
    ).json()
    client.post(
        "/api/v1/inventario/movimientos",
        json={
            "variante_id": contexto["variante_id"],
            "sucursal_id": deposito["id"],
            "tipo_movimiento_codigo": "recepcion",
            "cantidad": 5,
            "costo_unitario": "10.00",
        },
        headers=admin_headers,
    )
    client.post("/api/v1/carrito", json={"variante_id": contexto["variante_id"], "cantidad": 1}, headers=cliente_headers)

    retiro = client.post("/api/v1/ventas/digital", json={"sucursal_id": deposito["id"]}, headers=cliente_headers)
    assert retiro.status_code == 400
    assert "no atiende al público" in retiro.json()["detail"]

    manana = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    reserva = client.post(
        "/api/v1/reservas",
        json={
            "sucursal_id": deposito["id"],
            "fecha_visita": manana,
            "hora_visita_desde": "10:00",
            "hora_visita_hasta": "11:00",
            "detalle": [{"variante_id": contexto["variante_id"]}],
        },
        headers=cliente_headers,
    )
    assert reserva.status_code == 400
    assert "depósito" in reserva.json()["detail"]

    envio = client.post(
        "/api/v1/ventas/digital", json={"sucursal_id": deposito["id"], "costo_envio": "10.00"}, headers=cliente_headers
    )
    assert envio.status_code == 201


def test_carrito_no_deja_agregar_mas_que_el_stock(client, cliente_headers, contexto):
    # El contexto tiene 10 unidades en una sola sucursal.
    respuesta = client.post(
        "/api/v1/carrito", json={"variante_id": contexto["variante_id"], "cantidad": 11}, headers=cliente_headers
    )
    assert respuesta.status_code == 409
    assert "10" in respuesta.json()["detail"]

    assert client.post(
        "/api/v1/carrito", json={"variante_id": contexto["variante_id"], "cantidad": 10}, headers=cliente_headers
    ).status_code in (200, 201)
    assert client.put(
        f"/api/v1/carrito/{contexto['variante_id']}", json={"cantidad": 11}, headers=cliente_headers
    ).status_code == 409


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



# ---- pasarela simulada "qr_online" -----------------------------------------------------


def test_iniciar_pago_qr_online_redirige_a_pantalla_propia(client, cliente_headers, contexto):
    client.post("/api/v1/carrito", json={"variante_id": contexto["variante_id"], "cantidad": 1}, headers=cliente_headers)
    venta = client.post(
        "/api/v1/ventas/digital", json={"sucursal_id": contexto["sucursal_id"]}, headers=cliente_headers
    ).json()

    inicio = client.post(
        "/api/v1/pagos/iniciar", json={"venta_id": venta["id"], "metodo_pago": "qr_online"}, headers=cliente_headers
    )
    assert inicio.status_code == 201
    cuerpo = inicio.json()
    id_transaccion = cuerpo["pago"]["referencia_externa"]
    assert cuerpo["url_redireccion"] == f"http://localhost:8000/api/v1/pagos/qr/{id_transaccion}"


def test_pantalla_qr_muestra_el_monto_sin_requerir_login(client, cliente_headers, contexto):
    client.post("/api/v1/carrito", json={"variante_id": contexto["variante_id"], "cantidad": 1}, headers=cliente_headers)
    venta = client.post(
        "/api/v1/ventas/digital", json={"sucursal_id": contexto["sucursal_id"]}, headers=cliente_headers
    ).json()
    inicio = client.post(
        "/api/v1/pagos/iniciar", json={"venta_id": venta["id"], "metodo_pago": "qr_online"}, headers=cliente_headers
    ).json()
    id_transaccion = inicio["pago"]["referencia_externa"]

    # Sin headers de auth: la pantalla es pública.
    pantalla = client.get(f"/api/v1/pagos/qr/{id_transaccion}")
    assert pantalla.status_code == 200
    assert "100.00" in pantalla.text
    assert "data:image/png;base64," in pantalla.text


def test_pantalla_qr_inexistente_da_404(client):
    assert client.get("/api/v1/pagos/qr/QR-NOEXISTE").status_code == 404


def test_confirmar_pago_qr_aprueba_la_venta_y_descuenta_stock(client, admin_headers, cliente_headers, contexto):
    client.post("/api/v1/carrito", json={"variante_id": contexto["variante_id"], "cantidad": 2}, headers=cliente_headers)
    venta = client.post(
        "/api/v1/ventas/digital", json={"sucursal_id": contexto["sucursal_id"]}, headers=cliente_headers
    ).json()
    fisica_antes = _stock(client, admin_headers, contexto)["cantidad_fisica"]

    inicio = client.post(
        "/api/v1/pagos/iniciar", json={"venta_id": venta["id"], "metodo_pago": "qr_online"}, headers=cliente_headers
    ).json()
    id_transaccion = inicio["pago"]["referencia_externa"]

    confirmacion = client.post(f"/api/v1/pagos/qr/{id_transaccion}/confirmar")
    assert confirmacion.status_code == 200
    assert confirmacion.json()["estado"] == "aprobado"

    stock_final = _stock(client, admin_headers, contexto)
    assert stock_final["cantidad_fisica"] == fisica_antes - 2

    venta_final = client.get(f"/api/v1/ventas/{venta['id']}/comprobante", headers=admin_headers).json()
    assert venta_final["estado"] == "pagada"

    # Confirmar de nuevo es idempotente: no vuelve a descontar stock.
    otra_vez = client.post(f"/api/v1/pagos/qr/{id_transaccion}/confirmar")
    assert otra_vez.status_code == 200
    assert _stock(client, admin_headers, contexto)["cantidad_fisica"] == fisica_antes - 2

    # Y la pantalla, una vez resuelto el pago, ya no ofrece el botón de confirmar.
    pantalla_resuelta = client.get(f"/api/v1/pagos/qr/{id_transaccion}")
    assert "id=\"btn-confirmar\"" not in pantalla_resuelta.text


def test_confirmar_pago_qr_con_id_inexistente_da_404(client):
    assert client.post("/api/v1/pagos/qr/QR-NOEXISTE/confirmar").status_code == 404


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
