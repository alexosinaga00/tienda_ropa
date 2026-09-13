from decimal import Decimal

import pytest


@pytest.fixture()
def producto_sucursal(client, admin_headers):
    cat = client.post("/api/v1/categorias", json={"nombre": "Camisas Abast"}, headers=admin_headers).json()
    talla = client.post("/api/v1/tallas", json={"codigo": "M", "orden": 1}, headers=admin_headers).json()
    color = client.post("/api/v1/colores", json={"nombre": "Verde"}, headers=admin_headers).json()
    producto = client.post(
        "/api/v1/productos",
        json={
            "codigo": "ABAST-1",
            "nombre": "Camisa abastecimiento",
            "categoria_id": cat["id"],
            "precio_base": "90.00",
            "tallas_ids": [talla["id"]],
            "colores_ids": [color["id"]],
        },
        headers=admin_headers,
    ).json()
    variante = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()[0]

    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": "Cochabamba", "departamento": "Cochabamba"}, headers=admin_headers
    ).json()
    sucursal = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-ABAST", "nombre": "Depósito Abast", "direccion": "Av. 1"},
        headers=admin_headers,
    ).json()

    return {"producto_id": producto["id"], "variante_id": variante["id"], "sucursal_id": sucursal["id"]}


@pytest.fixture()
def proveedor(client, admin_headers):
    return client.post(
        "/api/v1/proveedores",
        json={"nombre": "Textiles SRL", "nit": "1234567", "contacto": "Juan Perez"},
        headers=admin_headers,
    ).json()


# ---- Permisos ---------------------------------------------------------------


def test_proveedores_requiere_permiso(client, cliente_headers):
    respuesta = client.get("/api/v1/proveedores", headers=cliente_headers)
    assert respuesta.status_code == 403


def test_proveedores_sin_token_rechazado(client):
    assert client.get("/api/v1/proveedores").status_code == 401


# ---- Proveedores --------------------------------------------------------------


def test_crear_y_obtener_proveedor(client, admin_headers):
    creado = client.post(
        "/api/v1/proveedores", json={"nombre": "Insumos SA", "nit": "999"}, headers=admin_headers
    )
    assert creado.status_code == 201
    proveedor_id = creado.json()["id"]

    obtenido = client.get(f"/api/v1/proveedores/{proveedor_id}", headers=admin_headers)
    assert obtenido.status_code == 200
    assert obtenido.json()["nombre"] == "Insumos SA"
    assert obtenido.json()["activo"] is True


def test_proveedor_nit_duplicado_falla(client, admin_headers):
    client.post("/api/v1/proveedores", json={"nombre": "A", "nit": "DUP-1"}, headers=admin_headers)
    duplicado = client.post("/api/v1/proveedores", json={"nombre": "B", "nit": "DUP-1"}, headers=admin_headers)
    assert duplicado.status_code == 409


def test_desactivar_proveedor(client, admin_headers, proveedor):
    respuesta = client.delete(f"/api/v1/proveedores/{proveedor['id']}", headers=admin_headers)
    assert respuesta.status_code == 204

    obtenido = client.get(f"/api/v1/proveedores/{proveedor['id']}", headers=admin_headers)
    assert obtenido.status_code == 404  # CRUDBase.obtener oculta los inactivos


def test_proveedor_dado_de_baja_se_puede_recrear_con_el_mismo_nit(client, admin_headers):
    creado = client.post(
        "/api/v1/proveedores", json={"nombre": "Insumos SA", "nit": "REINGRESO-1"}, headers=admin_headers
    ).json()

    baja = client.delete(f"/api/v1/proveedores/{creado['id']}", headers=admin_headers)
    assert baja.status_code == 204

    reingreso = client.post(
        "/api/v1/proveedores",
        json={"nombre": "Insumos SA Renovado", "nit": "REINGRESO-1"},
        headers=admin_headers,
    )
    assert reingreso.status_code == 201
    cuerpo = reingreso.json()
    assert cuerpo["id"] == creado["id"]
    assert cuerpo["activo"] is True
    assert cuerpo["nombre"] == "Insumos SA Renovado"


# ---- producto_proveedor -----------------------------------------------------------


def test_agregar_y_quitar_producto_proveedor(client, admin_headers, proveedor, producto_sucursal):
    producto_id = producto_sucursal["producto_id"]

    agregado = client.post(
        f"/api/v1/proveedores/{proveedor['id']}/productos",
        json={"producto_id": producto_id, "costo_referencial": "15.50", "dias_entrega": 7},
        headers=admin_headers,
    )
    assert agregado.status_code == 201
    assert Decimal(str(agregado.json()["costo_referencial"])) == Decimal("15.50")

    listado = client.get(f"/api/v1/proveedores/{proveedor['id']}/productos", headers=admin_headers)
    assert len(listado.json()) == 1

    quitado = client.delete(
        f"/api/v1/proveedores/{proveedor['id']}/productos/{producto_id}", headers=admin_headers
    )
    assert quitado.status_code == 204

    listado2 = client.get(f"/api/v1/proveedores/{proveedor['id']}/productos", headers=admin_headers)
    assert listado2.json() == []


def test_agregar_producto_proveedor_duplicado_falla(client, admin_headers, proveedor, producto_sucursal):
    producto_id = producto_sucursal["producto_id"]
    payload = {"producto_id": producto_id}
    client.post(f"/api/v1/proveedores/{proveedor['id']}/productos", json=payload, headers=admin_headers)
    duplicado = client.post(f"/api/v1/proveedores/{proveedor['id']}/productos", json=payload, headers=admin_headers)
    assert duplicado.status_code == 409


# ---- Órdenes de compra ----------------------------------------------------------


def _crear_orden(client, headers, proveedor_id, sucursal_id, variante_id, codigo="OC-1", cantidad=10, costo="20.00"):
    return client.post(
        "/api/v1/ordenes-compra",
        json={
            "codigo": codigo,
            "proveedor_id": proveedor_id,
            "sucursal_id": sucursal_id,
            "detalle": [{"variante_id": variante_id, "cantidad": cantidad, "costo_unitario": costo}],
        },
        headers=headers,
    )


def test_crear_orden_compra_calcula_total(client, admin_headers, proveedor, producto_sucursal):
    respuesta = _crear_orden(
        client, admin_headers, proveedor["id"], producto_sucursal["sucursal_id"], producto_sucursal["variante_id"],
        cantidad=10, costo="20.00",
    )
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "borrador"
    assert Decimal(str(cuerpo["total"])) == Decimal("200.00")
    assert len(cuerpo["detalle"]) == 1


def test_orden_compra_codigo_duplicado_falla(client, admin_headers, proveedor, producto_sucursal):
    _crear_orden(client, admin_headers, proveedor["id"], producto_sucursal["sucursal_id"], producto_sucursal["variante_id"], codigo="OC-DUP")
    duplicada = _crear_orden(client, admin_headers, proveedor["id"], producto_sucursal["sucursal_id"], producto_sucursal["variante_id"], codigo="OC-DUP")
    assert duplicada.status_code == 409


def test_actualizar_orden_compra_solo_en_borrador(client, admin_headers, proveedor, producto_sucursal):
    creada = _crear_orden(
        client, admin_headers, proveedor["id"], producto_sucursal["sucursal_id"], producto_sucursal["variante_id"], codigo="OC-2"
    ).json()

    actualizada = client.put(
        f"/api/v1/ordenes-compra/{creada['id']}",
        json={"fecha_esperada": "2026-12-01"},
        headers=admin_headers,
    )
    assert actualizada.status_code == 200
    assert actualizada.json()["fecha_esperada"] == "2026-12-01"

    client.post(f"/api/v1/ordenes-compra/{creada['id']}/enviar", headers=admin_headers)

    bloqueada = client.put(
        f"/api/v1/ordenes-compra/{creada['id']}",
        json={"fecha_esperada": "2026-12-15"},
        headers=admin_headers,
    )
    assert bloqueada.status_code == 409


def test_enviar_orden_compra_cambia_estado(client, admin_headers, proveedor, producto_sucursal):
    creada = _crear_orden(
        client, admin_headers, proveedor["id"], producto_sucursal["sucursal_id"], producto_sucursal["variante_id"], codigo="OC-3"
    ).json()
    respuesta = client.post(f"/api/v1/ordenes-compra/{creada['id']}/enviar", headers=admin_headers)
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "enviada"


def test_anular_orden_compra_desde_borrador(client, admin_headers, proveedor, producto_sucursal):
    creada = _crear_orden(
        client, admin_headers, proveedor["id"], producto_sucursal["sucursal_id"], producto_sucursal["variante_id"], codigo="OC-4"
    ).json()
    respuesta = client.delete(f"/api/v1/ordenes-compra/{creada['id']}", headers=admin_headers)
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "anulada"


# ---- Recepciones -----------------------------------------------------------------


def _crear_recepcion(client, headers, proveedor_id, sucursal_id, variante_id, codigo="REC-1", orden_compra_id=None, cantidad=10, costo="20.00"):
    payload = {
        "codigo": codigo,
        "proveedor_id": proveedor_id,
        "sucursal_id": sucursal_id,
        "detalle": [{"variante_id": variante_id, "cantidad": cantidad, "costo_unitario": costo}],
    }
    if orden_compra_id is not None:
        payload["orden_compra_id"] = orden_compra_id
    return client.post("/api/v1/recepciones", json=payload, headers=headers)


def test_recepcion_genera_movimiento_de_tipo_recepcion(client, admin_headers, proveedor, producto_sucursal):
    respuesta = _crear_recepcion(
        client, admin_headers, proveedor["id"], producto_sucursal["sucursal_id"], producto_sucursal["variante_id"],
        codigo="REC-A", cantidad=15, costo="12.00",
    )
    assert respuesta.status_code == 201

    variante_id = producto_sucursal["variante_id"]
    sucursal_id = producto_sucursal["sucursal_id"]
    stock = client.get(f"/api/v1/inventario/stock/{variante_id}/{sucursal_id}", headers=admin_headers).json()
    assert stock["cantidad_fisica"] == 15
    assert Decimal(str(stock["costo_promedio"])) == Decimal("12.0000")

    kardex = client.get(
        f"/api/v1/inventario/movimientos?variante_id={variante_id}&sucursal_id={sucursal_id}", headers=admin_headers
    ).json()
    assert len(kardex) == 1
    assert kardex[0]["tipo_movimiento_codigo"] == "recepcion"
    assert kardex[0]["referencia_tipo"] == "recepcion"
    assert kardex[0]["referencia_id"] == respuesta.json()["id"]


def test_recepcion_codigo_duplicado_falla(client, admin_headers, proveedor, producto_sucursal):
    _crear_recepcion(client, admin_headers, proveedor["id"], producto_sucursal["sucursal_id"], producto_sucursal["variante_id"], codigo="REC-DUP")
    duplicada = _crear_recepcion(client, admin_headers, proveedor["id"], producto_sucursal["sucursal_id"], producto_sucursal["variante_id"], codigo="REC-DUP")
    assert duplicada.status_code == 409


def test_recepcion_con_linea_invalida_no_deja_nada_aplicado(client, admin_headers, proveedor, producto_sucursal):
    """Atomicidad: la recepción tiene dos líneas, la segunda con una
    variante inexistente. Ninguna de las dos debe quedar aplicada (ni el
    movimiento de la primera línea, ni la fila de stock)."""
    payload = {
        "codigo": "REC-ATOMICA",
        "proveedor_id": proveedor["id"],
        "sucursal_id": producto_sucursal["sucursal_id"],
        "detalle": [
            {"variante_id": producto_sucursal["variante_id"], "cantidad": 5, "costo_unitario": "10.00"},
            {"variante_id": 999999, "cantidad": 5, "costo_unitario": "10.00"},
        ],
    }
    respuesta = client.post("/api/v1/recepciones", json=payload, headers=admin_headers)
    assert respuesta.status_code == 404

    variante_id = producto_sucursal["variante_id"]
    sucursal_id = producto_sucursal["sucursal_id"]
    stock = client.get(f"/api/v1/inventario/stock/{variante_id}/{sucursal_id}", headers=admin_headers)
    assert stock.status_code == 404  # nunca se creó la fila de stock

    listado = client.get("/api/v1/recepciones", headers=admin_headers).json()
    assert not any(r["codigo"] == "REC-ATOMICA" for r in listado)


def test_recepcion_con_orden_compra_actualiza_estado_a_recibida(client, admin_headers, proveedor, producto_sucursal):
    orden = _crear_orden(
        client, admin_headers, proveedor["id"], producto_sucursal["sucursal_id"], producto_sucursal["variante_id"],
        codigo="OC-REC-1", cantidad=10, costo="20.00",
    ).json()
    client.post(f"/api/v1/ordenes-compra/{orden['id']}/enviar", headers=admin_headers)

    respuesta = _crear_recepcion(
        client, admin_headers, proveedor["id"], producto_sucursal["sucursal_id"], producto_sucursal["variante_id"],
        codigo="REC-OC-1", orden_compra_id=orden["id"], cantidad=10, costo="20.00",
    )
    assert respuesta.status_code == 201

    orden_actualizada = client.get(f"/api/v1/ordenes-compra/{orden['id']}", headers=admin_headers).json()
    assert orden_actualizada["estado"] == "recibida"


def test_recepcion_parcial_de_orden_compra(client, admin_headers, proveedor, producto_sucursal):
    orden = _crear_orden(
        client, admin_headers, proveedor["id"], producto_sucursal["sucursal_id"], producto_sucursal["variante_id"],
        codigo="OC-REC-2", cantidad=10, costo="20.00",
    ).json()
    client.post(f"/api/v1/ordenes-compra/{orden['id']}/enviar", headers=admin_headers)

    respuesta = _crear_recepcion(
        client, admin_headers, proveedor["id"], producto_sucursal["sucursal_id"], producto_sucursal["variante_id"],
        codigo="REC-OC-2", orden_compra_id=orden["id"], cantidad=4, costo="20.00",
    )
    assert respuesta.status_code == 201

    orden_actualizada = client.get(f"/api/v1/ordenes-compra/{orden['id']}", headers=admin_headers).json()
    assert orden_actualizada["estado"] == "parcial"


def test_recepcion_contra_orden_en_borrador_falla(client, admin_headers, proveedor, producto_sucursal):
    orden = _crear_orden(
        client, admin_headers, proveedor["id"], producto_sucursal["sucursal_id"], producto_sucursal["variante_id"],
        codigo="OC-REC-3",
    ).json()

    respuesta = _crear_recepcion(
        client, admin_headers, proveedor["id"], producto_sucursal["sucursal_id"], producto_sucursal["variante_id"],
        codigo="REC-OC-3", orden_compra_id=orden["id"],
    )
    assert respuesta.status_code == 400
