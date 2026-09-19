import pytest


@pytest.fixture()
def zona_1er_anillo(client):
    zonas = client.get("/api/v1/zonas-envio").json()
    return next(z for z in zonas if z["nombre"] == "1er anillo")


@pytest.fixture()
def contexto(client, admin_headers):
    cat = client.post("/api/v1/categorias", json={"nombre": "Camisas Entrega"}, headers=admin_headers).json()
    talla = client.post("/api/v1/tallas", json={"codigo": "M", "orden": 1}, headers=admin_headers).json()
    color = client.post("/api/v1/colores", json={"nombre": "Azul Entrega"}, headers=admin_headers).json()
    producto = client.post(
        "/api/v1/productos",
        json={
            "codigo": "ENT-1",
            "nombre": "Camisa entrega",
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
        "/api/v1/ciudades", json={"nombre": "Santa Cruz Entrega", "departamento": "Santa Cruz"}, headers=admin_headers
    ).json()
    sucursal = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-ENT", "nombre": "Sucursal Entrega", "direccion": "Av. 1"},
        headers=admin_headers,
    ).json()
    sucursal_id = sucursal["id"]

    client.post(
        "/api/v1/inventario/movimientos",
        json={
            "variante_id": variante_id,
            "sucursal_id": sucursal_id,
            "tipo_movimiento_codigo": "recepcion",
            "cantidad": 50,
            "costo_unitario": "10.00",
        },
        headers=admin_headers,
    )

    return {"variante_id": variante_id, "sucursal_id": sucursal_id}


def _crear_direccion(client, cliente_headers, zona_id):
    return client.post(
        "/api/v1/clientes/direcciones",
        json={"zona_envio_id": zona_id, "direccion": "Calle Falsa 123"},
        headers=cliente_headers,
    ).json()


# ---- cálculo de tarifa por anillo, con y sin recargo por peso (Revisar) ----------------


def test_cotizar_sin_recargo_por_peso(client, cliente_headers, zona_1er_anillo):
    direccion = _crear_direccion(client, cliente_headers, zona_1er_anillo["id"])

    # peso_promedio_prenda_kg=0.3 (default) * 5 = 1.5kg, dentro de la
    # franja 0-2kg de regla_tarifa_envio: sin recargo.
    respuesta = client.post("/api/v1/envios/cotizar", json={"direccion_id": direccion["id"], "cantidad_prendas": 5})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["peso_kg"] == "1.5"
    assert cuerpo["recargo_peso"] == "0.00"
    assert cuerpo["costo"] == zona_1er_anillo["tarifa_base"]


def test_cotizar_con_recargo_por_peso(client, cliente_headers, zona_1er_anillo):
    direccion = _crear_direccion(client, cliente_headers, zona_1er_anillo["id"])

    # 0.3 * 20 = 6.0kg, cae en la franja 5kg+ (recargo 10.00).
    respuesta = client.post("/api/v1/envios/cotizar", json={"direccion_id": direccion["id"], "cantidad_prendas": 20})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["peso_kg"] == "6.0"
    assert cuerpo["recargo_peso"] == "10.00"
    assert float(cuerpo["costo"]) == float(zona_1er_anillo["tarifa_base"]) + 10.00


def test_cotizar_no_persiste_nada(client, db_session, cliente_headers, zona_1er_anillo):
    from app.entregas.models import Envio

    direccion = _crear_direccion(client, cliente_headers, zona_1er_anillo["id"])
    antes = db_session.query(Envio).count()

    for _ in range(3):
        respuesta = client.post(
            "/api/v1/envios/cotizar", json={"direccion_id": direccion["id"], "cantidad_prendas": 8}
        )
        assert respuesta.status_code == 200

    despues = db_session.query(Envio).count()
    assert despues == antes == 0


# ---- crear envío: el costo de la venta tiene que coincidir con la tarifa real -----------


def test_crear_envio_usa_costo_ya_fijado_en_la_venta(client, cliente_headers, contexto, zona_1er_anillo):
    direccion = _crear_direccion(client, cliente_headers, zona_1er_anillo["id"])
    cotizacion = client.post(
        "/api/v1/envios/cotizar", json={"direccion_id": direccion["id"], "cantidad_prendas": 2}
    ).json()

    client.post(
        "/api/v1/carrito", json={"variante_id": contexto["variante_id"], "cantidad": 2}, headers=cliente_headers
    )
    venta = client.post(
        "/api/v1/ventas/digital",
        json={"sucursal_id": contexto["sucursal_id"], "costo_envio": cotizacion["costo"]},
        headers=cliente_headers,
    ).json()
    assert venta["costo_envio"] == cotizacion["costo"]

    respuesta = client.post(
        "/api/v1/envios", json={"venta_id": venta["id"], "direccion_id": direccion["id"]}, headers=cliente_headers
    )
    assert respuesta.status_code == 201
    envio = respuesta.json()
    assert envio["costo"] == cotizacion["costo"]
    assert envio["zona_envio_id"] == zona_1er_anillo["id"]
    assert envio["estado"] == "programado"

    # no se puede crear un segundo envío para la misma venta
    segundo = client.post(
        "/api/v1/envios", json={"venta_id": venta["id"], "direccion_id": direccion["id"]}, headers=cliente_headers
    )
    assert segundo.status_code == 409


@pytest.mark.parametrize("costo_envio", ["0.01", "0.00"])
def test_crear_envio_rechaza_costo_distinto_a_la_tarifa(
    client, db_session, cliente_headers, contexto, zona_1er_anillo, costo_envio
):
    """El costo de envío de la venta lo manda el cliente: si no coincide con
    la tarifa real de la zona, no hay envío (ni pagando de menos ni con una
    compra registrada como retiro en sucursal)."""
    from app.entregas.models import Envio

    assert float(zona_1er_anillo["tarifa_base"]) > 0
    direccion = _crear_direccion(client, cliente_headers, zona_1er_anillo["id"])
    client.post(
        "/api/v1/carrito", json={"variante_id": contexto["variante_id"], "cantidad": 1}, headers=cliente_headers
    )
    venta = client.post(
        "/api/v1/ventas/digital",
        json={"sucursal_id": contexto["sucursal_id"], "costo_envio": costo_envio},
        headers=cliente_headers,
    ).json()

    respuesta = client.post(
        "/api/v1/envios", json={"venta_id": venta["id"], "direccion_id": direccion["id"]}, headers=cliente_headers
    )
    # 400 y no 409: los clientes toman un 409 acá como "el envío ya existía".
    assert respuesta.status_code == 400
    assert "no coincide con la tarifa" in respuesta.json()["detail"]
    assert db_session.query(Envio).filter(Envio.venta_id == venta["id"]).count() == 0


# ---- máquina de estados del envío -------------------------------------------------------


def _crear_envio(client, admin_headers, cliente_headers, contexto, zona_1er_anillo):
    direccion = _crear_direccion(client, cliente_headers, zona_1er_anillo["id"])
    cotizacion = client.post(
        "/api/v1/envios/cotizar", json={"direccion_id": direccion["id"], "cantidad_prendas": 1}
    ).json()
    client.post(
        "/api/v1/carrito", json={"variante_id": contexto["variante_id"], "cantidad": 1}, headers=cliente_headers
    )
    venta = client.post(
        "/api/v1/ventas/digital",
        json={"sucursal_id": contexto["sucursal_id"], "costo_envio": cotizacion["costo"]},
        headers=cliente_headers,
    ).json()
    return client.post(
        "/api/v1/envios", json={"venta_id": venta["id"], "direccion_id": direccion["id"]}, headers=cliente_headers
    ).json()


def test_no_se_puede_saltar_directo_a_entregado(client, admin_headers, cliente_headers, contexto, zona_1er_anillo):
    envio = _crear_envio(client, admin_headers, cliente_headers, contexto, zona_1er_anillo)

    respuesta = client.put(f"/api/v1/envios/{envio['id']}/estado", json={"estado": "entregado"}, headers=admin_headers)
    assert respuesta.status_code == 409


def test_ciclo_completo_hasta_entregado(client, admin_headers, cliente_headers, contexto, zona_1er_anillo):
    envio = _crear_envio(client, admin_headers, cliente_headers, contexto, zona_1er_anillo)

    en_ruta = client.put(
        f"/api/v1/envios/{envio['id']}/estado",
        json={"estado": "en_ruta", "repartidor": "Juan Perez"},
        headers=admin_headers,
    )
    assert en_ruta.status_code == 200
    cuerpo = en_ruta.json()
    assert cuerpo["repartidor"] == "Juan Perez"
    assert cuerpo["fecha_programada"] is not None
    assert cuerpo["fecha_entrega"] is None

    entregado = client.put(f"/api/v1/envios/{envio['id']}/estado", json={"estado": "entregado"}, headers=admin_headers)
    assert entregado.status_code == 200
    assert entregado.json()["fecha_entrega"] is not None

    # 'entregado' es terminal
    otro = client.put(f"/api/v1/envios/{envio['id']}/estado", json={"estado": "en_ruta"}, headers=admin_headers)
    assert otro.status_code == 409
