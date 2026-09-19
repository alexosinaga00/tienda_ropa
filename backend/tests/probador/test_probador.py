import io

import pytest
from PIL import Image

from app.core import storage
from app.probador.casos_uso.cu21_cargar_assets_anclajes import CargarAssetsAnclajes

_cu_assets = CargarAssetsAnclajes()


@pytest.fixture()
def storage_falso(monkeypatch):
    subidos: dict[str, bytes] = {}

    def _subir_imagen(contenido: bytes, carpeta: str, *, formato_forzado: str | None = None) -> str:
        assert formato_forzado == "png"  # el probador nunca sube sin forzar png
        public_id = f"{carpeta}/asset{len(subidos) + 1}"
        subidos[public_id] = contenido
        return public_id

    def _url_probador(public_id: str) -> str:
        return f"https://res.cloudinary.com/demo/image/upload/{public_id}.png"

    monkeypatch.setattr(storage, "subir_imagen", _subir_imagen)
    monkeypatch.setattr(storage, "url_probador", _url_probador)
    return subidos


@pytest.fixture()
def categoria_y_variante(client, admin_headers):
    cat = client.post("/api/v1/categorias", json={"nombre": "Camisas"}, headers=admin_headers).json()
    talla = client.post("/api/v1/tallas", json={"codigo": "M", "orden": 1}, headers=admin_headers).json()
    color = client.post("/api/v1/colores", json={"nombre": "Azul"}, headers=admin_headers).json()
    producto = client.post(
        "/api/v1/productos",
        json={
            "codigo": "PROB-1",
            "nombre": "Camisa probador",
            "categoria_id": cat["id"],
            "precio_base": "100.00",
            "tallas_ids": [talla["id"]],
            "colores_ids": [color["id"]],
        },
        headers=admin_headers,
    ).json()
    variante = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()[0]
    return variante


def _png_con_alfa(lado=512) -> bytes:
    img = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    for x in range(lado // 4, 3 * lado // 4):
        for y in range(lado // 4, 3 * lado // 4):
            img.putpixel((x, y), (10, 20, 30, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _png_sin_alfa(lado=512) -> bytes:
    img = Image.new("RGB", (lado, lado), (10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _jpeg(lado=512) -> bytes:
    img = Image.new("RGB", (lado, lado), (10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _archivo(contenido: bytes, content_type="image/png", nombre="asset.png"):
    return {"archivo": (nombre, io.BytesIO(contenido), content_type)}


# ---- Permisos ---------------------------------------------------------------


def test_requiere_admin(client, cliente_headers, categoria_y_variante):
    respuesta = client.post(
        "/api/v1/probador/assets",
        data={"variante_id": categoria_y_variante["id"], "tipo": "overlay_2d"},
        files=_archivo(_png_con_alfa()),
        headers=cliente_headers,
    )
    assert respuesta.status_code == 403


def test_sin_token_rechazado(client, categoria_y_variante):
    respuesta = client.get(f"/api/v1/probador/assets?variante_id={categoria_y_variante['id']}")
    assert respuesta.status_code == 401


# ---- Validaciones de subida --------------------------------------------------


def test_subir_png_con_alfa_valido(client, admin_headers, storage_falso, categoria_y_variante):
    respuesta = client.post(
        "/api/v1/probador/assets",
        data={"variante_id": categoria_y_variante["id"], "tipo": "overlay_2d"},
        files=_archivo(_png_con_alfa()),
        headers=admin_headers,
    )
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "pendiente"
    assert cuerpo["ancho_px"] == 512
    assert cuerpo["alto_px"] == 512
    assert cuerpo["anclajes"] is None


def test_rechaza_png_sin_canal_alfa_real(client, admin_headers, storage_falso, categoria_y_variante):
    """El punto del checklist: se verifica con Pillow, no por extensión.
    Este archivo ES un PNG válido, pero no tiene canal alfa."""
    respuesta = client.post(
        "/api/v1/probador/assets",
        data={"variante_id": categoria_y_variante["id"], "tipo": "overlay_2d"},
        files=_archivo(_png_sin_alfa()),
        headers=admin_headers,
    )
    assert respuesta.status_code == 400
    assert "alfa" in respuesta.json()["detail"].lower()


def test_rechaza_jpeg_disfrazado_de_png(client, admin_headers, storage_falso, categoria_y_variante):
    """Manda un JPEG real con extensión/nombre .png y content-type png: la
    validación tiene que abrir el archivo de verdad, no confiar en nada
    de lo que dice el cliente."""
    respuesta = client.post(
        "/api/v1/probador/assets",
        data={"variante_id": categoria_y_variante["id"], "tipo": "overlay_2d"},
        files=_archivo(_jpeg(), content_type="image/png", nombre="falso.png"),
        headers=admin_headers,
    )
    assert respuesta.status_code == 400
    assert "png" in respuesta.json()["detail"].lower()


def test_rechaza_content_type_no_png(client, admin_headers, storage_falso, categoria_y_variante):
    respuesta = client.post(
        "/api/v1/probador/assets",
        data={"variante_id": categoria_y_variante["id"], "tipo": "overlay_2d"},
        files=_archivo(_png_con_alfa(), content_type="image/jpeg"),
        headers=admin_headers,
    )
    assert respuesta.status_code == 400


def test_rechaza_imagen_menor_a_512px(client, admin_headers, storage_falso, categoria_y_variante):
    respuesta = client.post(
        "/api/v1/probador/assets",
        data={"variante_id": categoria_y_variante["id"], "tipo": "overlay_2d"},
        files=_archivo(_png_con_alfa(lado=256)),
        headers=admin_headers,
    )
    assert respuesta.status_code == 400
    assert "512" in respuesta.json()["detail"]


def test_rechaza_archivo_mayor_a_3mb(client, admin_headers, storage_falso, categoria_y_variante):
    contenido_grande = _png_con_alfa() + b"\x00" * (3 * 1024 * 1024 + 1)
    respuesta = client.post(
        "/api/v1/probador/assets",
        data={"variante_id": categoria_y_variante["id"], "tipo": "overlay_2d"},
        files=_archivo(contenido_grande),
        headers=admin_headers,
    )
    assert respuesta.status_code == 400


def test_subir_asset_variante_inexistente_falla(client, admin_headers, storage_falso):
    respuesta = client.post(
        "/api/v1/probador/assets",
        data={"variante_id": 9999, "tipo": "overlay_2d"},
        files=_archivo(_png_con_alfa()),
        headers=admin_headers,
    )
    assert respuesta.status_code == 404


def test_subir_asset_tipo_invalido_falla(client, admin_headers, categoria_y_variante):
    respuesta = client.post(
        "/api/v1/probador/assets",
        data={"variante_id": categoria_y_variante["id"], "tipo": "algo_raro"},
        files=_archivo(_png_con_alfa()),
        headers=admin_headers,
    )
    assert respuesta.status_code == 422  # Literal de Pydantic en el Form


# ---- Anclajes -----------------------------------------------------------------


def _subir(client, admin_headers, variante_id, tipo="overlay_2d"):
    return client.post(
        "/api/v1/probador/assets",
        data={"variante_id": variante_id, "tipo": tipo},
        files=_archivo(_png_con_alfa()),
        headers=admin_headers,
    ).json()


def test_guardar_anclajes_normalizados(client, admin_headers, storage_falso, categoria_y_variante):
    activo = _subir(client, admin_headers, categoria_y_variante["id"])

    respuesta = client.put(
        f"/api/v1/probador/assets/{activo['id']}/anclajes",
        json={
            "hombro_izq": {"x": 0.3, "y": 0.15},
            "hombro_der": {"x": 0.7, "y": 0.15},
            "cadera": {"x": 0.5, "y": 0.65},
        },
        headers=admin_headers,
    )
    assert respuesta.status_code == 200
    anclajes = respuesta.json()["anclajes"]
    assert anclajes["hombro_izq"] == {"x": 0.3, "y": 0.15}
    assert anclajes["cadera"] == {"x": 0.5, "y": 0.65}


def test_anclajes_fuera_de_rango_rechazados(client, admin_headers, storage_falso, categoria_y_variante):
    activo = _subir(client, admin_headers, categoria_y_variante["id"])

    respuesta = client.put(
        f"/api/v1/probador/assets/{activo['id']}/anclajes",
        json={
            "hombro_izq": {"x": 1.5, "y": 0.15},  # > 1, inválido
            "hombro_der": {"x": 0.7, "y": 0.15},
            "cadera": {"x": 0.5, "y": 0.65},
        },
        headers=admin_headers,
    )
    assert respuesta.status_code == 422


def test_anclajes_incompletos_rechazados(client, admin_headers, storage_falso, categoria_y_variante):
    activo = _subir(client, admin_headers, categoria_y_variante["id"])

    respuesta = client.put(
        f"/api/v1/probador/assets/{activo['id']}/anclajes",
        json={"hombro_izq": {"x": 0.3, "y": 0.15}, "hombro_der": {"x": 0.7, "y": 0.15}},
        headers=admin_headers,
    )
    assert respuesta.status_code == 422


# ---- Validar --------------------------------------------------------------------


def test_no_se_puede_validar_sin_anclajes(client, admin_headers, storage_falso, categoria_y_variante):
    activo = _subir(client, admin_headers, categoria_y_variante["id"])

    respuesta = client.put(f"/api/v1/probador/assets/{activo['id']}/validar", headers=admin_headers)
    assert respuesta.status_code == 400


def test_validar_con_anclajes_cambia_estado(client, admin_headers, storage_falso, categoria_y_variante):
    activo = _subir(client, admin_headers, categoria_y_variante["id"])
    client.put(
        f"/api/v1/probador/assets/{activo['id']}/anclajes",
        json={
            "hombro_izq": {"x": 0.3, "y": 0.15},
            "hombro_der": {"x": 0.7, "y": 0.15},
            "cadera": {"x": 0.5, "y": 0.65},
        },
        headers=admin_headers,
    )

    respuesta = client.put(f"/api/v1/probador/assets/{activo['id']}/validar", headers=admin_headers)
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "validado"


def test_no_se_puede_revalidar(client, admin_headers, storage_falso, categoria_y_variante):
    activo = _subir(client, admin_headers, categoria_y_variante["id"])
    client.put(
        f"/api/v1/probador/assets/{activo['id']}/anclajes",
        json={
            "hombro_izq": {"x": 0.3, "y": 0.15},
            "hombro_der": {"x": 0.7, "y": 0.15},
            "cadera": {"x": 0.5, "y": 0.65},
        },
        headers=admin_headers,
    )
    client.put(f"/api/v1/probador/assets/{activo['id']}/validar", headers=admin_headers)

    respuesta = client.put(f"/api/v1/probador/assets/{activo['id']}/validar", headers=admin_headers)
    assert respuesta.status_code == 400


# ---- Listado ------------------------------------------------------------------


def test_listar_por_variante(client, admin_headers, storage_falso, categoria_y_variante):
    _subir(client, admin_headers, categoria_y_variante["id"], tipo="overlay_2d")
    _subir(client, admin_headers, categoria_y_variante["id"], tipo="thumb")

    listado = client.get(
        f"/api/v1/probador/assets?variante_id={categoria_y_variante['id']}", headers=admin_headers
    ).json()
    assert len(listado) == 2
    assert {a["tipo"] for a in listado} == {"overlay_2d", "thumb"}


# ---- Reutilizar un asset entre variantes ---------------------------------------


def test_clonar_asset_a_otra_talla_del_mismo_producto(client, admin_headers, db_session, storage_falso):
    cat = client.post("/api/v1/categorias", json={"nombre": "Poleras"}, headers=admin_headers).json()
    talla_l = client.post("/api/v1/tallas", json={"codigo": "L", "orden": 1}, headers=admin_headers).json()
    talla_xl = client.post("/api/v1/tallas", json={"codigo": "XL", "orden": 2}, headers=admin_headers).json()
    color = client.post("/api/v1/colores", json={"nombre": "Negro"}, headers=admin_headers).json()
    producto = client.post(
        "/api/v1/productos",
        json={
            "codigo": "CLON-1",
            "nombre": "Polera clonada",
            "categoria_id": cat["id"],
            "precio_base": "149.00",
            "admite_probador": True,
            "tallas_ids": [talla_l["id"], talla_xl["id"]],
            "colores_ids": [color["id"]],
        },
        headers=admin_headers,
    ).json()
    variantes = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()
    origen_id, destino_id = variantes[0]["id"], variantes[1]["id"]

    activo = _subir(client, admin_headers, origen_id)
    anclajes = {"hombro_izq": {"x": 0.3, "y": 0.15}, "hombro_der": {"x": 0.7, "y": 0.15}, "cadera": {"x": 0.5, "y": 0.65}}
    client.put(f"/api/v1/probador/assets/{activo['id']}/anclajes", json=anclajes, headers=admin_headers)
    client.put(f"/api/v1/probador/assets/{activo['id']}/validar", headers=admin_headers)

    copia = _cu_assets.clonar_a_variante(db_session, activo["id"], destino_id)

    assert copia.variante_id == destino_id
    assert copia.url == activo["public_id"]  # mismo archivo, sin volver a subir
    assert copia.anclajes == anclajes
    assert copia.estado == "validado"
    assert len(storage_falso) == 1

    usados = client.get(f"/api/v1/probador/variante/{destino_id}/assets", headers=admin_headers)
    assert usados.status_code == 200
    assert usados.json()["overlay"]["estado"] == "validado"


def test_clonar_asset_a_otro_producto_rechazado(client, admin_headers, db_session, storage_falso, categoria_y_variante):
    from app.core.exceptions import DomainError

    activo = _subir(client, admin_headers, categoria_y_variante["id"])
    talla = client.post("/api/v1/tallas", json={"codigo": "XL", "orden": 2}, headers=admin_headers).json()
    color = client.get("/api/v1/colores", headers=admin_headers).json()[0]
    otro = client.post(
        "/api/v1/productos",
        json={
            "codigo": "OTRO-1",
            "nombre": "Otra camisa",
            "categoria_id": client.get("/api/v1/categorias", headers=admin_headers).json()[0]["id"],
            "precio_base": "100.00",
            "tallas_ids": [talla["id"]],
            "colores_ids": [color["id"]],
        },
        headers=admin_headers,
    ).json()
    variante_otro = client.get(f"/api/v1/productos/{otro['id']}/variantes", headers=admin_headers).json()[0]

    with pytest.raises(DomainError):
        _cu_assets.clonar_a_variante(db_session, activo["id"], variante_otro["id"])
