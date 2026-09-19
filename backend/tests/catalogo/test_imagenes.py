import io

import pytest

from app.core import storage


@pytest.fixture()
def storage_falso(monkeypatch):
    """Nunca se pega a Cloudinary de verdad en los tests: se reemplazan
    las funciones de storage por dobles en memoria."""
    subidos: dict[str, bytes] = {}
    eliminados: list[str] = []
    contador = {"n": 0}

    def _subir_imagen(contenido: bytes, carpeta: str, *, formato_forzado: str | None = None) -> str:
        contador["n"] += 1
        public_id = f"{carpeta}/img{contador['n']}"
        subidos[public_id] = contenido
        return public_id

    def _eliminar_imagen(public_id: str) -> None:
        eliminados.append(public_id)
        subidos.pop(public_id, None)

    def _url_catalogo(public_id: str, ancho=None, alto=None) -> str:
        return f"https://res.cloudinary.com/demo/image/upload/f_auto,q_auto/{public_id}.jpg"

    monkeypatch.setattr(storage, "subir_imagen", _subir_imagen)
    monkeypatch.setattr(storage, "eliminar_imagen", _eliminar_imagen)
    monkeypatch.setattr(storage, "url_catalogo", _url_catalogo)

    return {"subidos": subidos, "eliminados": eliminados}


@pytest.fixture()
def categoria_camisas(client, admin_headers):
    return client.post("/api/v1/categorias", json={"nombre": "Camisas"}, headers=admin_headers).json()


@pytest.fixture()
def producto(client, admin_headers, categoria_camisas):
    s = client.post("/api/v1/tallas", json={"codigo": "S", "orden": 1}, headers=admin_headers).json()
    rojo = client.post("/api/v1/colores", json={"nombre": "Rojo"}, headers=admin_headers).json()
    return client.post(
        "/api/v1/productos",
        json={
            "codigo": "CAM-IMG",
            "nombre": "Camisa",
            "categoria_id": categoria_camisas["id"],
            "precio_base": "100.00",
            "tallas_ids": [s["id"]],
            "colores_ids": [rojo["id"]],
        },
        headers=admin_headers,
    ).json()


def _archivo_falso(nombre="foto.jpg", content_type="image/jpeg", contenido=b"contenido-de-prueba"):
    return {"archivo": (nombre, io.BytesIO(contenido), content_type)}


# ---- Subida --------------------------------------------------------------------


def test_subir_imagen_no_expone_api_secret(client, admin_headers, storage_falso, producto):
    respuesta = client.post(
        f"/api/v1/productos/{producto['id']}/imagenes",
        files=_archivo_falso(),
        headers=admin_headers,
    )
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()

    # El api_secret no debe aparecer en ningún lado de la respuesta.
    texto_respuesta = respuesta.text.lower()
    assert "api_secret" not in texto_respuesta
    assert "secret" not in texto_respuesta
    # La base guarda public_id, no una URL de Cloudinary con parámetros de firma.
    assert cuerpo["public_id"].startswith("fashionstore/productos/")
    assert "sha1" not in cuerpo["url"].lower()


def test_subir_imagen_guarda_public_id_no_url_completa(client, admin_headers, db_session, storage_falso, producto):
    from app.catalogo.models import ProductoImagen

    respuesta = client.post(
        f"/api/v1/productos/{producto['id']}/imagenes",
        files=_archivo_falso(),
        headers=admin_headers,
    )
    imagen_id = respuesta.json()["id"]

    fila = db_session.get(ProductoImagen, imagen_id)
    # La columna `url` en la base guarda el public_id, no la URL completa.
    assert fila.url == respuesta.json()["public_id"]
    assert not fila.url.startswith("http")


def test_subir_imagen_usa_carpeta_por_producto(client, admin_headers, storage_falso, producto):
    respuesta = client.post(
        f"/api/v1/productos/{producto['id']}/imagenes", files=_archivo_falso(), headers=admin_headers
    )
    public_id = respuesta.json()["public_id"]
    assert public_id.startswith(f"fashionstore/productos/{producto['id']}/")


def test_subir_imagen_tipo_invalido_es_rechazado(client, admin_headers, storage_falso, producto):
    respuesta = client.post(
        f"/api/v1/productos/{producto['id']}/imagenes",
        files=_archivo_falso(nombre="doc.pdf", content_type="application/pdf"),
        headers=admin_headers,
    )
    assert respuesta.status_code == 400
    assert len(storage_falso["subidos"]) == 0


def test_subir_imagen_producto_inexistente_falla(client, admin_headers, storage_falso):
    respuesta = client.post(
        "/api/v1/productos/9999/imagenes", files=_archivo_falso(), headers=admin_headers
    )
    assert respuesta.status_code == 404


def test_subir_imagen_requiere_admin(client, cliente_headers, storage_falso, producto):
    respuesta = client.post(
        f"/api/v1/productos/{producto['id']}/imagenes", files=_archivo_falso(), headers=cliente_headers
    )
    assert respuesta.status_code == 403


# ---- Marcar principal -----------------------------------------------------------


def test_marcar_principal_desmarca_las_demas(client, admin_headers, db_session, storage_falso, producto):
    from app.catalogo.models import ProductoImagen

    img1 = client.post(
        f"/api/v1/productos/{producto['id']}/imagenes",
        files=_archivo_falso(),
        data={"es_principal": "true"},
        headers=admin_headers,
    ).json()
    img2 = client.post(
        f"/api/v1/productos/{producto['id']}/imagenes", files=_archivo_falso(), headers=admin_headers
    ).json()
    assert img1["es_principal"] is True
    assert img2["es_principal"] is False

    respuesta = client.put(f"/api/v1/imagenes/{img2['id']}/principal", headers=admin_headers)
    assert respuesta.status_code == 200
    assert respuesta.json()["es_principal"] is True

    assert db_session.get(ProductoImagen, img1["id"]).es_principal is False


# ---- Borrado ------------------------------------------------------------------


def test_eliminar_imagen_borra_en_cloudinary_y_en_la_base(
    client, admin_headers, db_session, storage_falso, producto
):
    from app.catalogo.models import ProductoImagen

    creada = client.post(
        f"/api/v1/productos/{producto['id']}/imagenes", files=_archivo_falso(), headers=admin_headers
    ).json()

    respuesta = client.delete(f"/api/v1/imagenes/{creada['id']}", headers=admin_headers)
    assert respuesta.status_code == 204

    assert creada["public_id"] in storage_falso["eliminados"]
    assert db_session.get(ProductoImagen, creada["id"]) is None


def test_eliminar_imagen_inexistente_falla(client, admin_headers, storage_falso):
    respuesta = client.delete("/api/v1/imagenes/9999", headers=admin_headers)
    assert respuesta.status_code == 404
