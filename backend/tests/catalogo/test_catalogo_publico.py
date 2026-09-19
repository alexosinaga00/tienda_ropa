import time

import pytest


@pytest.fixture()
def categoria_camisas(client, admin_headers):
    return client.post("/api/v1/categorias", json={"nombre": "Camisas"}, headers=admin_headers).json()


@pytest.fixture()
def tallas(client, admin_headers):
    s = client.post("/api/v1/tallas", json={"codigo": "S", "orden": 1}, headers=admin_headers).json()
    m = client.post("/api/v1/tallas", json={"codigo": "M", "orden": 2}, headers=admin_headers).json()
    return [s, m]


@pytest.fixture()
def colores(client, admin_headers):
    rojo = client.post("/api/v1/colores", json={"nombre": "Rojo"}, headers=admin_headers).json()
    azul = client.post("/api/v1/colores", json={"nombre": "Azul"}, headers=admin_headers).json()
    return [rojo, azul]


def _crear_producto(client, admin_headers, categoria_id, tallas_ids, colores_ids, codigo, **extra):
    payload = {
        "codigo": codigo,
        "nombre": extra.pop("nombre", "Camisa de lino"),
        "categoria_id": categoria_id,
        "precio_base": extra.pop("precio_base", "150.00"),
        "tallas_ids": tallas_ids,
        "colores_ids": colores_ids,
        **extra,
    }
    return client.post("/api/v1/productos", json=payload, headers=admin_headers).json()


# ---- Público, sin token -------------------------------------------------------


def test_catalogo_listado_es_publico(client, admin_headers, categoria_camisas, tallas, colores):
    _crear_producto(client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]], "PUB-1")

    respuesta = client.get("/api/v1/catalogo")
    assert respuesta.status_code == 200
    assert len(respuesta.json()) >= 1


def test_catalogo_detalle_es_publico(client, admin_headers, categoria_camisas, tallas, colores):
    producto = _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]], "PUB-2"
    )

    respuesta = client.get(f"/api/v1/catalogo/{producto['id']}")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["codigo"] == "PUB-2"
    assert len(cuerpo["variantes"]) == 1
    assert cuerpo["variantes"][0]["precio_efectivo"] == "150.00"
    # Sin stock registrado en `inventario` para esta variante, 0 disponible.
    assert cuerpo["variantes"][0]["cantidad_disponible"] == 0


def test_catalogo_no_muestra_producto_inactivo(client, admin_headers, categoria_camisas, tallas, colores):
    producto = _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]], "PUB-3"
    )
    client.delete(f"/api/v1/productos/{producto['id']}", headers=admin_headers)

    assert client.get(f"/api/v1/catalogo/{producto['id']}").status_code == 404
    ids_listado = {p["id"] for p in client.get("/api/v1/catalogo").json()}
    assert producto["id"] not in ids_listado


def test_catalogo_paginacion_maximo_50(client):
    respuesta = client.get("/api/v1/catalogo?tamanio=51")
    assert respuesta.status_code == 422


# ---- /buscar con filtros ------------------------------------------------------


def test_buscar_por_texto_libre(client, admin_headers, categoria_camisas, tallas, colores):
    _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]], "BUS-1",
        nombre="Camisa de lino premium",
    )
    _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]], "BUS-2",
        nombre="Pantalón cargo",
    )

    respuesta = client.get("/api/v1/catalogo/buscar?q=lino")
    resultados = respuesta.json()
    assert len(resultados) == 1
    assert resultados[0]["codigo"] == "BUS-1"


def test_buscar_por_categoria(client, admin_headers, tallas, colores):
    cat_a = client.post("/api/v1/categorias", json={"nombre": "CatA"}, headers=admin_headers).json()
    cat_b = client.post("/api/v1/categorias", json={"nombre": "CatB"}, headers=admin_headers).json()
    _crear_producto(client, admin_headers, cat_a["id"], [tallas[0]["id"]], [colores[0]["id"]], "BUS-CAT-A")
    _crear_producto(client, admin_headers, cat_b["id"], [tallas[0]["id"]], [colores[0]["id"]], "BUS-CAT-B")

    resultados = client.get(f"/api/v1/catalogo/buscar?categoria_id={cat_a['id']}").json()
    assert {p["codigo"] for p in resultados} == {"BUS-CAT-A"}


def test_buscar_por_talla_y_color(client, admin_headers, categoria_camisas, tallas, colores):
    _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]], "BUS-TC-1"
    )
    _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[1]["id"]], [colores[1]["id"]], "BUS-TC-2"
    )

    resultados = client.get(
        f"/api/v1/catalogo/buscar?talla_id={tallas[0]['id']}&color_id={colores[0]['id']}"
    ).json()
    assert {p["codigo"] for p in resultados} == {"BUS-TC-1"}


def test_buscar_por_rango_de_precio(client, admin_headers, categoria_camisas, tallas, colores):
    _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]], "BUS-P-BARATO",
        precio_base="50.00",
    )
    _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]], "BUS-P-CARO",
        precio_base="500.00",
    )

    resultados = client.get("/api/v1/catalogo/buscar?precio_min=100&precio_max=1000").json()
    assert {p["codigo"] for p in resultados} == {"BUS-P-CARO"}


def test_buscar_no_duplica_por_join_de_variantes(client, admin_headers, categoria_camisas, tallas, colores):
    # Un producto con 2 tallas x 2 colores = 4 variantes. Filtrar por
    # color no debería devolver el producto repetido.
    _crear_producto(
        client,
        admin_headers,
        categoria_camisas["id"],
        [t["id"] for t in tallas],
        [c["id"] for c in colores],
        "BUS-NODUP",
    )

    resultados = client.get(f"/api/v1/catalogo/buscar?color_id={colores[0]['id']}").json()
    codigos = [p["codigo"] for p in resultados]
    assert codigos.count("BUS-NODUP") == 1


def test_buscar_genero_invalido_rechazado(client):
    respuesta = client.get("/api/v1/catalogo/buscar?genero=marciano")
    assert respuesta.status_code == 422


# ---- solo_disponibles / sucursal_id (CU-10, disponibilidad real) --------------


def _registrar_stock(client, admin_headers, variante_id, sucursal_id, cantidad=10):
    return client.post(
        "/api/v1/inventario/movimientos",
        json={
            "variante_id": variante_id,
            "sucursal_id": sucursal_id,
            "tipo_movimiento_codigo": "recepcion",
            "cantidad": cantidad,
            "costo_unitario": "10.00",
        },
        headers=admin_headers,
    )


def _crear_sucursal(client, admin_headers, ciudad_id, codigo):
    return client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad_id, "codigo": codigo, "nombre": codigo, "direccion": "Km 5"},
        headers=admin_headers,
    ).json()


def test_buscar_solo_disponibles_excluye_sin_stock(client, admin_headers, categoria_camisas, tallas, colores):
    con_stock = _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]], "DISP-CON"
    )
    _crear_producto(client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]], "DISP-SIN")
    variante = client.get(f"/api/v1/productos/{con_stock['id']}/variantes", headers=admin_headers).json()[0]
    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": "Santa Cruz", "departamento": "Santa Cruz"}, headers=admin_headers
    ).json()
    sucursal = _crear_sucursal(client, admin_headers, ciudad["id"], "SUC-DISP-1")
    assert _registrar_stock(client, admin_headers, variante["id"], sucursal["id"]).status_code == 201

    sin_filtro = client.get("/api/v1/catalogo/buscar").json()
    assert {"DISP-CON", "DISP-SIN"} <= {p["codigo"] for p in sin_filtro}

    resultados = client.get("/api/v1/catalogo/buscar?solo_disponibles=true").json()
    assert {p["codigo"] for p in resultados} == {"DISP-CON"}


def test_buscar_solo_disponibles_respeta_sucursal_id(client, admin_headers, categoria_camisas, tallas, colores):
    producto = _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]], "DISP-SUC"
    )
    variante = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()[0]
    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": "Santa Cruz", "departamento": "Santa Cruz"}, headers=admin_headers
    ).json()
    sucursal_con_stock = _crear_sucursal(client, admin_headers, ciudad["id"], "SUC-DISP-A")
    sucursal_sin_stock = _crear_sucursal(client, admin_headers, ciudad["id"], "SUC-DISP-B")
    assert _registrar_stock(client, admin_headers, variante["id"], sucursal_con_stock["id"]).status_code == 201

    en_su_sucursal = client.get(
        f"/api/v1/catalogo/buscar?solo_disponibles=true&sucursal_id={sucursal_con_stock['id']}"
    ).json()
    assert "DISP-SUC" in {p["codigo"] for p in en_su_sucursal}

    en_otra_sucursal = client.get(
        f"/api/v1/catalogo/buscar?solo_disponibles=true&sucursal_id={sucursal_sin_stock['id']}"
    ).json()
    assert "DISP-SUC" not in {p["codigo"] for p in en_otra_sucursal}


# ---- Variantes para la caja (POS) ---------------------------------------------


def _primera_variante(client, admin_headers, producto_id):
    return client.get(f"/api/v1/productos/{producto_id}/variantes", headers=admin_headers).json()[0]


def test_buscar_variante_por_codigo_de_barras_exacto(client, admin_headers, categoria_camisas, tallas, colores):
    producto = _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]], "POS-1"
    )
    variante = _primera_variante(client, admin_headers, producto["id"])
    asignado = client.put(
        f"/api/v1/variantes/{variante['id']}", json={"codigo_barras": "7591234567890"}, headers=admin_headers
    )
    assert asignado.status_code == 200

    resultados = client.get(
        "/api/v1/catalogo/variantes/buscar?q=7591234567890", headers=admin_headers
    ).json()
    assert len(resultados) == 1
    assert resultados[0]["variante_id"] == variante["id"]
    assert resultados[0]["producto_nombre"] == "Camisa de lino"
    assert resultados[0]["precio_efectivo"] == "150.00"


def test_buscar_variante_por_nombre_requiere_catalogo_ver(client, admin_headers, categoria_camisas, tallas, colores):
    _crear_producto(
        client,
        admin_headers,
        categoria_camisas["id"],
        [tallas[0]["id"]],
        [colores[0]["id"]],
        "POS-2",
        nombre="Chamarra de cuero",
    )
    # Sin token: esta búsqueda es para la caja (POS), no público como
    # /catalogo/buscar -- exige el permiso catalogo.ver del cajero (B-6).
    sin_auth = client.get("/api/v1/catalogo/variantes/buscar?q=chamarra")
    assert sin_auth.status_code == 401

    resultados = client.get(
        "/api/v1/catalogo/variantes/buscar?q=chamarra", headers=admin_headers
    ).json()
    assert any(r["producto_codigo"] == "POS-2" for r in resultados)


def test_detalle_para_dashboard_requiere_sesion(client, admin_headers, categoria_camisas, tallas, colores):
    producto = _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]], "POS-4"
    )
    variante = _primera_variante(client, admin_headers, producto["id"])

    # Sin token: puede mostrar productos inactivos (B-6), así que no queda
    # público -- exige cualquier usuario logueado (staff o cliente).
    sin_auth = client.get(f"/api/v1/catalogo/variantes/detalle?variante_ids={variante['id']}")
    assert sin_auth.status_code == 401

    resultados = client.get(
        f"/api/v1/catalogo/variantes/detalle?variante_ids={variante['id']}", headers=admin_headers
    ).json()
    assert any(r["variante_id"] == variante["id"] for r in resultados)


def test_codigo_de_barras_duplicado_es_rechazado(client, admin_headers, categoria_camisas, tallas, colores):
    prod_a = _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]], "POS-3A"
    )
    prod_b = _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]], "POS-3B"
    )
    variante_a = _primera_variante(client, admin_headers, prod_a["id"])
    variante_b = _primera_variante(client, admin_headers, prod_b["id"])

    client.put(f"/api/v1/variantes/{variante_a['id']}", json={"codigo_barras": "111"}, headers=admin_headers)
    duplicado = client.put(
        f"/api/v1/variantes/{variante_b['id']}", json={"codigo_barras": "111"}, headers=admin_headers
    )
    assert duplicado.status_code == 409


# ---- Favoritos ------------------------------------------------------------------


def test_favoritos_requiere_sesion(client):
    assert client.get("/api/v1/favoritos").status_code == 401


def test_favoritos_flujo_completo(client, admin_headers, cliente_headers, categoria_camisas, tallas, colores):
    producto = _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]], "FAV-1"
    )
    variante = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()[0]

    agregado = client.post(
        "/api/v1/favoritos", json={"variante_id": variante["id"]}, headers=cliente_headers
    )
    assert agregado.status_code == 201
    assert agregado.json()["sku"] == variante["sku"]

    listado = client.get("/api/v1/favoritos", headers=cliente_headers).json()
    assert len(listado) == 1
    assert listado[0]["variante_id"] == variante["id"]

    quitado = client.delete(f"/api/v1/favoritos/{variante['id']}", headers=cliente_headers)
    assert quitado.status_code == 204
    assert client.get("/api/v1/favoritos", headers=cliente_headers).json() == []


def test_agregar_favorito_dos_veces_es_idempotente(
    client, admin_headers, cliente_headers, categoria_camisas, tallas, colores
):
    producto = _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]], "FAV-2"
    )
    variante = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()[0]

    client.post("/api/v1/favoritos", json={"variante_id": variante["id"]}, headers=cliente_headers)
    client.post("/api/v1/favoritos", json={"variante_id": variante["id"]}, headers=cliente_headers)

    listado = client.get("/api/v1/favoritos", headers=cliente_headers).json()
    assert len(listado) == 1


def test_quitar_favorito_inexistente_falla(client, cliente_headers):
    respuesta = client.delete("/api/v1/favoritos/9999", headers=cliente_headers)
    assert respuesta.status_code == 404


def test_agregar_favorito_con_variante_inexistente_falla(client, cliente_headers):
    respuesta = client.post("/api/v1/favoritos", json={"variante_id": 9999}, headers=cliente_headers)
    assert respuesta.status_code == 404


# ---- Rendimiento / N+1 -----------------------------------------------------------


def test_catalogo_con_30_productos_responde_rapido_y_sin_n_mas_1(
    client, admin_headers, db_session, categoria_camisas, tallas, colores
):
    from sqlalchemy import event

    for i in range(30):
        _crear_producto(
            client,
            admin_headers,
            categoria_camisas["id"],
            [t["id"] for t in tallas],
            [c["id"] for c in colores],
            f"PERF-{i:03d}",
        )

    # El engine real de la app (app.core.database.engine) NO es el que usan
    # los tests (la sesión sqlite en memoria del fixture db_session), así
    # que hay que escuchar en el engine correcto para que el conteo sea real.
    engine = db_session.get_bind()

    consultas = {"n": 0}

    def _contar(*args, **kwargs):
        consultas["n"] += 1

    event.listen(engine, "before_cursor_execute", _contar)
    try:
        inicio = time.perf_counter()
        respuesta = client.get("/api/v1/catalogo?tamanio=50")
        duracion = time.perf_counter() - inicio
    finally:
        event.remove(engine, "before_cursor_execute", _contar)

    assert respuesta.status_code == 200
    assert len(respuesta.json()) == 30
    assert duracion < 1.0, f"tardó {duracion:.2f}s con 30 productos"
    # 1 query de productos + 1 selectinload de imágenes = 2, no 31 (N+1).
    assert consultas["n"] <= 3, f"se ejecutaron {consultas['n']} queries, huele a N+1"
