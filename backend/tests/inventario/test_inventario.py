from decimal import Decimal

import pytest

from app.core.exceptions import ConflictoError
from app.inventario.politicas import liberar_stock, reservar_stock


@pytest.fixture()
def variante_y_sucursal(client, admin_headers):
    cat = client.post("/api/v1/categorias", json={"nombre": "Camisas"}, headers=admin_headers).json()
    talla = client.post("/api/v1/tallas", json={"codigo": "M", "orden": 1}, headers=admin_headers).json()
    color = client.post("/api/v1/colores", json={"nombre": "Azul"}, headers=admin_headers).json()
    producto = client.post(
        "/api/v1/productos",
        json={
            "codigo": "INV-1",
            "nombre": "Camisa inventario",
            "categoria_id": cat["id"],
            "precio_base": "100.00",
            "tallas_ids": [talla["id"]],
            "colores_ids": [color["id"]],
        },
        headers=admin_headers,
    ).json()
    variante = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()[0]

    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": "Santa Cruz", "departamento": "Santa Cruz"}, headers=admin_headers
    ).json()
    sucursal = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-INV", "nombre": "Depósito", "direccion": "Km 5"},
        headers=admin_headers,
    ).json()

    return variante["id"], sucursal["id"]


def _registrar(client, headers, variante_id, sucursal_id, **overrides):
    payload = {
        "variante_id": variante_id,
        "sucursal_id": sucursal_id,
        "tipo_movimiento_codigo": "recepcion",
        "cantidad": 10,
        "costo_unitario": "10.00",
    }
    payload.update(overrides)
    return client.post("/api/v1/inventario/movimientos", json=payload, headers=headers)


# ---- Permisos ---------------------------------------------------------------


def test_movimientos_requiere_permiso_gestionar(client, cliente_headers, variante_y_sucursal):
    variante_id, sucursal_id = variante_y_sucursal
    respuesta = _registrar(client, cliente_headers, variante_id, sucursal_id)
    assert respuesta.status_code == 403


def test_stock_sin_token_rechazado(client, variante_y_sucursal):
    variante_id, sucursal_id = variante_y_sucursal
    respuesta = client.get(f"/api/v1/inventario/stock/{variante_id}/{sucursal_id}")
    assert respuesta.status_code == 401


# ---- registrar_movimiento: costeo promedio ponderado -------------------------


def test_promedio_ponderado_tres_recepciones(client, admin_headers, variante_y_sucursal):
    """Verificado a mano:
    10 u a 10  -> promedio 10.0000
    +20 u a 20 -> (10*10 + 20*20) / 30 = 500/30 = 16.6667
    +15 u a 30 -> (30*16.6667 + 15*30) / 45 = (500 + 450) / 45 = 950/45 = 21.1111
    """
    r1 = _registrar(client, admin_headers, *variante_y_sucursal, cantidad=10, costo_unitario="10.00")
    assert r1.status_code == 201
    assert Decimal(r1.json()["costo_promedio_post"]) == Decimal("10.0000")
    assert r1.json()["saldo_post"] == 10

    r2 = _registrar(client, admin_headers, *variante_y_sucursal, cantidad=20, costo_unitario="20.00")
    assert r2.status_code == 201
    assert Decimal(r2.json()["costo_promedio_post"]) == Decimal("16.6667")
    assert r2.json()["saldo_post"] == 30

    r3 = _registrar(client, admin_headers, *variante_y_sucursal, cantidad=15, costo_unitario="30.00")
    assert r3.status_code == 201
    assert Decimal(r3.json()["costo_promedio_post"]) == Decimal("21.1111")
    assert r3.json()["saldo_post"] == 45

    variante_id, sucursal_id = variante_y_sucursal
    stock = client.get(f"/api/v1/inventario/stock/{variante_id}/{sucursal_id}", headers=admin_headers).json()
    assert stock["cantidad_fisica"] == 45
    assert Decimal(stock["costo_promedio"]) == Decimal("21.1111")


def test_movimiento_que_no_afecta_costo_no_cambia_promedio(client, admin_headers, variante_y_sucursal):
    _registrar(client, admin_headers, *variante_y_sucursal, cantidad=10, costo_unitario="10.00")
    # devolución no afecta costo (afecta_costo=False)
    respuesta = _registrar(
        client,
        admin_headers,
        *variante_y_sucursal,
        tipo_movimiento_codigo="devolucion",
        cantidad=5,
        costo_unitario=None,
    )
    assert respuesta.status_code == 201
    assert respuesta.json()["costo_promedio_post"] is None
    assert respuesta.json()["saldo_post"] == 15

    variante_id, sucursal_id = variante_y_sucursal
    stock = client.get(f"/api/v1/inventario/stock/{variante_id}/{sucursal_id}", headers=admin_headers).json()
    assert Decimal(stock["costo_promedio"]) == Decimal("10.0000")


def test_movimiento_afecta_costo_requiere_costo_unitario(client, admin_headers, variante_y_sucursal):
    respuesta = _registrar(client, admin_headers, *variante_y_sucursal, costo_unitario=None)
    assert respuesta.status_code == 400


def test_movimiento_salida_reduce_stock(client, admin_headers, variante_y_sucursal):
    _registrar(client, admin_headers, *variante_y_sucursal, cantidad=10, costo_unitario="10.00")
    respuesta = _registrar(
        client, admin_headers, *variante_y_sucursal, tipo_movimiento_codigo="venta", cantidad=4, costo_unitario=None
    )
    assert respuesta.status_code == 201
    assert respuesta.json()["cantidad"] == -4
    assert respuesta.json()["saldo_post"] == 6


def test_movimiento_no_puede_dejar_stock_negativo(client, admin_headers, variante_y_sucursal):
    _registrar(client, admin_headers, *variante_y_sucursal, cantidad=5, costo_unitario="10.00")
    respuesta = _registrar(
        client, admin_headers, *variante_y_sucursal, tipo_movimiento_codigo="venta", cantidad=6, costo_unitario=None
    )
    assert respuesta.status_code == 409


def test_movimiento_tipo_inexistente_falla(client, admin_headers, variante_y_sucursal):
    respuesta = _registrar(client, admin_headers, *variante_y_sucursal, tipo_movimiento_codigo="no_existe")
    assert respuesta.status_code == 404


def test_movimiento_variante_inexistente_falla(client, admin_headers, variante_y_sucursal):
    _, sucursal_id = variante_y_sucursal
    respuesta = _registrar(client, admin_headers, 9999, sucursal_id)
    assert respuesta.status_code == 404


# ---- saldo_post == suma acumulada de movimientos ------------------------------


def test_saldo_post_coincide_con_suma_acumulada(client, admin_headers, variante_y_sucursal):
    _registrar(client, admin_headers, *variante_y_sucursal, cantidad=10, costo_unitario="10.00")
    _registrar(client, admin_headers, *variante_y_sucursal, tipo_movimiento_codigo="venta", cantidad=3, costo_unitario=None)
    _registrar(client, admin_headers, *variante_y_sucursal, cantidad=7, costo_unitario="15.00")

    variante_id, sucursal_id = variante_y_sucursal
    kardex = client.get(
        f"/api/v1/inventario/movimientos?variante_id={variante_id}&sucursal_id={sucursal_id}", headers=admin_headers
    ).json()

    assert len(kardex) == 3
    suma_acumulada = 0
    for movimiento in kardex:
        suma_acumulada += movimiento["cantidad"]
        assert movimiento["saldo_post"] == suma_acumulada

    stock = client.get(f"/api/v1/inventario/stock/{variante_id}/{sucursal_id}", headers=admin_headers).json()
    assert stock["cantidad_fisica"] == suma_acumulada


# ---- reservar_stock / liberar_stock -------------------------------------------
# Son pasos internos de reservas y ventas (ya no hay endpoints sueltos para
# moverlos a mano, BE-007): se prueban llamando directo a la política.


def test_reservar_no_altera_cantidad_fisica(client, admin_headers, db_session, variante_y_sucursal):
    variante_id, sucursal_id = variante_y_sucursal
    _registrar(client, admin_headers, variante_id, sucursal_id, cantidad=10, costo_unitario="10.00")

    stock = reservar_stock(db_session, variante_id, sucursal_id, 4)
    assert stock.cantidad_fisica == 10
    assert stock.cantidad_reservada == 4
    assert stock.cantidad_disponible == 6


def test_no_se_puede_reservar_mas_de_lo_disponible(client, admin_headers, db_session, variante_y_sucursal):
    variante_id, sucursal_id = variante_y_sucursal
    _registrar(client, admin_headers, variante_id, sucursal_id, cantidad=10, costo_unitario="10.00")

    with pytest.raises(ConflictoError):
        reservar_stock(db_session, variante_id, sucursal_id, 11)
    db_session.rollback()

    stock = client.get(f"/api/v1/inventario/stock/{variante_id}/{sucursal_id}", headers=admin_headers).json()
    assert stock["cantidad_reservada"] == 0


def test_reservar_no_genera_movimiento(client, admin_headers, db_session, variante_y_sucursal):
    variante_id, sucursal_id = variante_y_sucursal
    _registrar(client, admin_headers, variante_id, sucursal_id, cantidad=10, costo_unitario="10.00")
    reservar_stock(db_session, variante_id, sucursal_id, 4)

    kardex = client.get(
        f"/api/v1/inventario/movimientos?variante_id={variante_id}&sucursal_id={sucursal_id}", headers=admin_headers
    ).json()
    assert len(kardex) == 1  # solo la recepción; la reserva no aparece acá


def test_liberar_stock_decrementa_reservada(client, admin_headers, db_session, variante_y_sucursal):
    variante_id, sucursal_id = variante_y_sucursal
    _registrar(client, admin_headers, variante_id, sucursal_id, cantidad=10, costo_unitario="10.00")
    reservar_stock(db_session, variante_id, sucursal_id, 6)

    stock = liberar_stock(db_session, variante_id, sucursal_id, 2)
    assert stock.cantidad_reservada == 4
    assert stock.cantidad_fisica == 10


def test_no_se_puede_liberar_mas_de_lo_reservado(client, admin_headers, db_session, variante_y_sucursal):
    variante_id, sucursal_id = variante_y_sucursal
    _registrar(client, admin_headers, variante_id, sucursal_id, cantidad=10, costo_unitario="10.00")
    reservar_stock(db_session, variante_id, sucursal_id, 3)

    with pytest.raises(ConflictoError):
        liberar_stock(db_session, variante_id, sucursal_id, 4)


def test_ya_no_hay_endpoints_para_reservar_o_liberar_a_mano(client, admin_headers, variante_y_sucursal):
    variante_id, sucursal_id = variante_y_sucursal
    payload = {"variante_id": variante_id, "sucursal_id": sucursal_id, "cantidad": 1}
    assert client.post("/api/v1/inventario/reservas", json=payload, headers=admin_headers).status_code in (404, 405)
    assert client.post("/api/v1/inventario/liberaciones", json=payload, headers=admin_headers).status_code in (404, 405)


# ---- tipos de movimiento -------------------------------------------------------


def test_listar_tipos_movimiento(client, admin_headers):
    respuesta = client.get("/api/v1/inventario/tipos-movimiento", headers=admin_headers)
    assert respuesta.status_code == 200
    codigos = {t["codigo"] for t in respuesta.json()}
    assert "recepcion" in codigos
    assert "venta" in codigos
