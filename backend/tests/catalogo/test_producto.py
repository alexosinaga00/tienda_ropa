import pytest


@pytest.fixture()
def categoria_camisas(client, admin_headers):
    return client.post("/api/v1/categorias", json={"nombre": "Camisas"}, headers=admin_headers).json()


@pytest.fixture()
def categoria_pantalones(client, admin_headers):
    return client.post("/api/v1/categorias", json={"nombre": "Pantalones"}, headers=admin_headers).json()


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


def _crear_producto(client, admin_headers, categoria_id, tallas_ids, colores_ids, **extra):
    payload = {
        "codigo": "CAM-001",
        "nombre": "Camisa de lino",
        "categoria_id": categoria_id,
        "precio_base": "150.00",
        "tallas_ids": tallas_ids,
        "colores_ids": colores_ids,
        **extra,
    }
    return client.post("/api/v1/productos", json=payload, headers=admin_headers)


# ---- Permisos ---------------------------------------------------------------


def test_productos_requiere_admin_incluso_para_get(client, cliente_headers):
    assert client.get("/api/v1/productos", headers=cliente_headers).status_code == 403


def test_productos_sin_token_rechazado(client):
    assert client.get("/api/v1/productos").status_code == 401


# ---- Combinatoria de variantes -----------------------------------------------


def test_crear_producto_genera_combinatoria_completa(client, admin_headers, categoria_camisas, tallas, colores):
    tallas_ids = [t["id"] for t in tallas]
    colores_ids = [c["id"] for c in colores]

    respuesta = _crear_producto(client, admin_headers, categoria_camisas["id"], tallas_ids, colores_ids)
    assert respuesta.status_code == 201
    producto = respuesta.json()

    variantes = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()
    assert len(variantes) == 4  # 2 tallas x 2 colores

    skus = {v["sku"] for v in variantes}
    assert skus == {
        "CAM-001-S-ROJO",
        "CAM-001-S-AZUL",
        "CAM-001-M-ROJO",
        "CAM-001-M-AZUL",
    }


def test_sku_es_unico_por_variante(client, admin_headers, categoria_camisas, tallas, colores):
    tallas_ids = [t["id"] for t in tallas]
    colores_ids = [c["id"] for c in colores]
    producto = _crear_producto(client, admin_headers, categoria_camisas["id"], tallas_ids, colores_ids).json()

    variantes = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()
    skus = [v["sku"] for v in variantes]
    assert len(skus) == len(set(skus))


def test_agregar_color_no_duplica_variantes_existentes(client, admin_headers, categoria_camisas, tallas, colores):
    tallas_ids = [t["id"] for t in tallas]
    rojo_id = colores[0]["id"]
    producto = _crear_producto(client, admin_headers, categoria_camisas["id"], tallas_ids, [rojo_id]).json()

    variantes_iniciales = client.get(
        f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers
    ).json()
    assert len(variantes_iniciales) == 2  # 2 tallas x 1 color
    ids_iniciales = {v["id"] for v in variantes_iniciales}

    azul_id = colores[1]["id"]
    respuesta = client.post(
        f"/api/v1/productos/{producto['id']}/variantes",
        json={"tallas_ids": tallas_ids, "colores_ids": [rojo_id, azul_id]},
        headers=admin_headers,
    )
    assert respuesta.status_code == 201
    nuevas = respuesta.json()
    # Solo se crean las combinaciones nuevas (talla x azul), no se repite
    # talla x rojo que ya existía.
    assert len(nuevas) == 2
    assert {v["color_id"] for v in nuevas} == {azul_id}

    variantes_finales = client.get(
        f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers
    ).json()
    assert len(variantes_finales) == 4
    # Las variantes originales no se tocaron (mismos ids).
    assert ids_iniciales.issubset({v["id"] for v in variantes_finales})


def test_producto_talla_inexistente_falla(client, admin_headers, categoria_camisas, colores):
    colores_ids = [c["id"] for c in colores]
    respuesta = _crear_producto(client, admin_headers, categoria_camisas["id"], [9999], colores_ids)
    assert respuesta.status_code == 404


def test_producto_color_inexistente_falla(client, admin_headers, categoria_camisas, tallas):
    tallas_ids = [t["id"] for t in tallas]
    respuesta = _crear_producto(client, admin_headers, categoria_camisas["id"], tallas_ids, [9999])
    assert respuesta.status_code == 404


def test_producto_categoria_inexistente_falla(client, admin_headers, tallas, colores):
    respuesta = _crear_producto(
        client, admin_headers, 9999, [t["id"] for t in tallas], [c["id"] for c in colores]
    )
    assert respuesta.status_code == 404


def test_producto_codigo_duplicado_falla(client, admin_headers, categoria_camisas, tallas, colores):
    tallas_ids = [t["id"] for t in tallas]
    colores_ids = [c["id"] for c in colores]
    _crear_producto(client, admin_headers, categoria_camisas["id"], tallas_ids, colores_ids)

    duplicado = _crear_producto(client, admin_headers, categoria_camisas["id"], tallas_ids, colores_ids)
    assert duplicado.status_code == 409


# ---- admite_probador ----------------------------------------------------------


def test_producto_dado_de_baja_se_puede_recrear_con_el_mismo_codigo(
    client, admin_headers, categoria_camisas, tallas, colores
):
    tallas_ids = [t["id"] for t in tallas]
    colores_ids = [c["id"] for c in colores]
    producto = _crear_producto(client, admin_headers, categoria_camisas["id"], tallas_ids, colores_ids).json()

    baja = client.delete(f"/api/v1/productos/{producto['id']}", headers=admin_headers)
    assert baja.status_code == 204

    reingreso = _crear_producto(
        client, admin_headers, categoria_camisas["id"], tallas_ids, colores_ids, nombre="Camisa relanzada"
    )
    assert reingreso.status_code == 201
    cuerpo = reingreso.json()
    assert cuerpo["id"] == producto["id"]
    assert cuerpo["activo"] is True
    assert cuerpo["nombre"] == "Camisa relanzada"


def test_generar_variantes_reactiva_una_variante_dada_de_baja(
    client, admin_headers, categoria_camisas, tallas, colores
):
    tallas_ids = [t["id"] for t in tallas]
    colores_ids = [c["id"] for c in colores]
    producto = _crear_producto(client, admin_headers, categoria_camisas["id"], tallas_ids, colores_ids).json()

    variantes = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()
    variante = variantes[0]

    baja = client.delete(f"/api/v1/variantes/{variante['id']}", headers=admin_headers)
    assert baja.status_code == 204

    regenerar = client.post(
        f"/api/v1/productos/{producto['id']}/variantes",
        json={"tallas_ids": tallas_ids, "colores_ids": colores_ids},
        headers=admin_headers,
    )
    assert regenerar.status_code == 201

    variantes_finales = client.get(
        f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers
    ).json()
    reactivada = next(v for v in variantes_finales if v["id"] == variante["id"])
    assert reactivada["activo"] is True
    assert reactivada["sku"] == variante["sku"]  # se reactiva la misma fila, no genera un sku nuevo
    assert len(variantes_finales) == len(variantes)  # no se duplicó la combinación


def test_admite_probador_se_activa_en_categoria_torso_superior(
    client, admin_headers, categoria_camisas, tallas, colores
):
    respuesta = _crear_producto(
        client,
        admin_headers,
        categoria_camisas["id"],
        [t["id"] for t in tallas],
        [c["id"] for c in colores],
        admite_probador=True,
    )
    assert respuesta.status_code == 201
    assert respuesta.json()["admite_probador"] is True


def test_admite_probador_se_ignora_fuera_de_torso_superior(
    client, admin_headers, categoria_pantalones, tallas, colores
):
    respuesta = _crear_producto(
        client,
        admin_headers,
        categoria_pantalones["id"],
        [t["id"] for t in tallas],
        [c["id"] for c in colores],
        admite_probador=True,
    )
    assert respuesta.status_code == 201
    assert respuesta.json()["admite_probador"] is False


def test_admite_probador_se_recalcula_al_cambiar_categoria(
    client, admin_headers, categoria_camisas, categoria_pantalones, tallas, colores
):
    producto = _crear_producto(
        client,
        admin_headers,
        categoria_camisas["id"],
        [t["id"] for t in tallas],
        [c["id"] for c in colores],
        admite_probador=True,
    ).json()
    assert producto["admite_probador"] is True

    actualizado = client.put(
        f"/api/v1/productos/{producto['id']}",
        json={"categoria_id": categoria_pantalones["id"]},
        headers=admin_headers,
    )
    assert actualizado.status_code == 200
    assert actualizado.json()["admite_probador"] is False


# ---- Precio efectivo de la variante -------------------------------------------


def test_precio_efectivo_usa_precio_base_si_variante_no_tiene_precio(
    client, admin_headers, categoria_camisas, tallas, colores
):
    producto = _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]]
    ).json()
    variante = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()[0]

    assert variante["precio"] is None
    assert variante["precio_efectivo"] == "150.00"


def test_precio_efectivo_usa_precio_propio_si_esta_definido(
    client, admin_headers, categoria_camisas, tallas, colores
):
    producto = _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]]
    ).json()
    variante = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()[0]

    actualizada = client.put(
        f"/api/v1/variantes/{variante['id']}", json={"precio": "199.90"}, headers=admin_headers
    ).json()
    assert actualizada["precio"] == "199.90"
    assert actualizada["precio_efectivo"] == "199.90"


# ---- Tabla de medidas -----------------------------------------------------------


def test_medidas_crud(client, admin_headers, categoria_camisas, tallas, colores):
    producto = _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]]
    ).json()

    creada = client.post(
        f"/api/v1/productos/{producto['id']}/medidas",
        json={"talla_id": tallas[0]["id"], "pecho_min_cm": "90.0", "pecho_max_cm": "95.0"},
        headers=admin_headers,
    )
    assert creada.status_code == 201
    medida_id = creada.json()["id"]

    listado = client.get(f"/api/v1/productos/{producto['id']}/medidas", headers=admin_headers).json()
    assert len(listado) == 1

    actualizada = client.put(
        f"/api/v1/productos/{producto['id']}/medidas/{medida_id}",
        json={"pecho_max_cm": "97.0"},
        headers=admin_headers,
    )
    assert actualizada.status_code == 200
    assert actualizada.json()["pecho_max_cm"] == "97.0"

    eliminada = client.delete(
        f"/api/v1/productos/{producto['id']}/medidas/{medida_id}", headers=admin_headers
    )
    assert eliminada.status_code == 204
    assert client.get(f"/api/v1/productos/{producto['id']}/medidas", headers=admin_headers).json() == []


def test_medida_con_talla_inexistente_falla(client, admin_headers, categoria_camisas, tallas, colores):
    producto = _crear_producto(
        client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]]
    ).json()

    respuesta = client.post(
        f"/api/v1/productos/{producto['id']}/medidas",
        json={"talla_id": 9999},
        headers=admin_headers,
    )
    assert respuesta.status_code == 404


# ---- Categoría con productos no se puede desactivar ---------------------------


def test_categoria_con_productos_no_se_puede_desactivar(
    client, admin_headers, categoria_camisas, tallas, colores
):
    _crear_producto(client, admin_headers, categoria_camisas["id"], [tallas[0]["id"]], [colores[0]["id"]])

    respuesta = client.delete(f"/api/v1/categorias/{categoria_camisas['id']}", headers=admin_headers)
    assert respuesta.status_code == 409
