import hashlib
import io
import time

import pytest
from PIL import Image
from sqlalchemy.orm import sessionmaker

from app.probador import service


# ---- Fixtures -----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _sesion_background_en_memoria(monkeypatch, db_session):
    """`_ejecutar_generacion` abre su propia sesión con `SessionLocal()`
    (la del request ya se cerró para cuando el background task corre) --
    acá la apuntamos al mismo engine sqlite en memoria que usa `client`
    (con StaticPool comparten una única conexión), si no `SessionLocal()`
    real abriría una base `sqlite:///:memory:` nueva y vacía."""
    fabrica = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr(service, "SessionLocal", fabrica)


@pytest.fixture()
def storage_falso(monkeypatch):
    subidos: dict[str, bytes] = {}

    def _subir_imagen(contenido: bytes, carpeta: str, *, formato_forzado: str | None = None) -> str:
        assert formato_forzado == "png"
        public_id = f"{carpeta}/asset{len(subidos) + 1}"
        subidos[public_id] = contenido
        return public_id

    def _url_probador(public_id: str) -> str:
        return f"https://res.cloudinary.com/demo/image/upload/{public_id}.png"

    monkeypatch.setattr(service.storage, "subir_imagen", _subir_imagen)
    monkeypatch.setattr(service.storage, "url_probador", _url_probador)
    return subidos


@pytest.fixture()
def generativo_falso(monkeypatch):
    """Reemplaza el proveedor generativo real por uno en memoria: no llama
    a Vertex AI ni a ningún servicio externo. Registra cada llamada para
    poder verificar que el caché evita llamadas repetidas."""
    llamadas: list[tuple[bytes, bytes]] = []

    class _ProveedorFalso:
        nombre = "fake"

        def generar(self, foto_cliente: bytes, imagen_prenda: bytes) -> bytes:
            llamadas.append((foto_cliente, imagen_prenda))
            return b"contenido-png-generado-falso"

    monkeypatch.setattr(service, "obtener_proveedor_generativo", lambda: _ProveedorFalso())
    return llamadas


@pytest.fixture()
def descarga_falsa(monkeypatch):
    """Evita que `_ejecutar_generacion` haga un GET real a la URL (falsa)
    del flat-lay/overlay que devuelve `storage_falso`."""
    monkeypatch.setattr(service, "_descargar_bytes", lambda url: b"contenido-prenda-referencia")


@pytest.fixture()
def categoria_y_variante(client, admin_headers):
    """Producto en una categoría de torso superior (admite_probador=True),
    igual que exige `_resolver_admite_probador`."""
    cat = client.post("/api/v1/categorias", json={"nombre": "Camisas"}, headers=admin_headers).json()
    talla = client.post("/api/v1/tallas", json={"codigo": "M", "orden": 2}, headers=admin_headers).json()
    color = client.post("/api/v1/colores", json={"nombre": "Azul"}, headers=admin_headers).json()
    producto = client.post(
        "/api/v1/productos",
        json={
            "codigo": "PROBUSO-1",
            "nombre": "Camisa uso probador",
            "categoria_id": cat["id"],
            "precio_base": "100.00",
            "admite_probador": True,
            "tallas_ids": [talla["id"]],
            "colores_ids": [color["id"]],
        },
        headers=admin_headers,
    ).json()
    variante = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()[0]
    return {"producto": producto, "variante": variante, "categoria": cat, "talla": talla}


def _png_con_alfa(lado=512) -> bytes:
    img = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _foto_jpeg(color=(10, 20, 30)) -> bytes:
    img = Image.new("RGB", (64, 64), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _subir_y_validar_overlay(client, admin_headers, variante_id: int) -> None:
    activo = client.post(
        "/api/v1/probador/assets",
        data={"variante_id": variante_id, "tipo": "overlay_2d"},
        files={"archivo": ("overlay.png", io.BytesIO(_png_con_alfa()), "image/png")},
        headers=admin_headers,
    ).json()
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


# ---- GET /probador/variante/{id}/assets ----------------------------------------


def test_assets_uso_sin_overlay_validado_falla(client, cliente_headers, categoria_y_variante):
    respuesta = client.get(
        f"/api/v1/probador/variante/{categoria_y_variante['variante']['id']}/assets", headers=cliente_headers
    )
    assert respuesta.status_code == 404


def test_assets_uso_devuelve_overlay_validado(client, admin_headers, cliente_headers, storage_falso, categoria_y_variante):
    variante_id = categoria_y_variante["variante"]["id"]
    _subir_y_validar_overlay(client, admin_headers, variante_id)

    respuesta = client.get(f"/api/v1/probador/variante/{variante_id}/assets", headers=cliente_headers)
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["overlay"]["estado"] == "validado"
    assert cuerpo["flatlay"] is None


def test_assets_uso_requiere_autenticacion(client, categoria_y_variante):
    respuesta = client.get(f"/api/v1/probador/variante/{categoria_y_variante['variante']['id']}/assets")
    assert respuesta.status_code == 401


# ---- POST /probador/generar -----------------------------------------------------


def test_generar_sin_overlay_validado_falla(client, cliente_headers, categoria_y_variante):
    respuesta = client.post(
        "/api/v1/probador/generar",
        data={"variante_id": categoria_y_variante["variante"]["id"]},
        files={"archivo": ("foto.jpg", io.BytesIO(_foto_jpeg()), "image/jpeg")},
        headers=cliente_headers,
    )
    assert respuesta.status_code == 404


def test_generar_prenda_no_admite_probador_falla(
    client, admin_headers, cliente_headers, storage_falso, generativo_falso, descarga_falsa
):
    cat = client.post("/api/v1/categorias", json={"nombre": "Pantalones"}, headers=admin_headers).json()
    talla = client.post("/api/v1/tallas", json={"codigo": "M", "orden": 1}, headers=admin_headers).json()
    color = client.post("/api/v1/colores", json={"nombre": "Negro"}, headers=admin_headers).json()
    producto = client.post(
        "/api/v1/productos",
        json={
            "codigo": "PANT-1",
            "nombre": "Pantalón",
            "categoria_id": cat["id"],
            "precio_base": "50.00",
            "admite_probador": True,
            "tallas_ids": [talla["id"]],
            "colores_ids": [color["id"]],
        },
        headers=admin_headers,
    ).json()
    variante = client.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_headers).json()[0]

    respuesta = client.post(
        "/api/v1/probador/generar",
        data={"variante_id": variante["id"]},
        files={"archivo": ("foto.jpg", io.BytesIO(_foto_jpeg()), "image/jpeg")},
        headers=cliente_headers,
    )
    assert respuesta.status_code == 400


def test_generar_primera_vez_no_es_cache_y_termina_completada(
    client, admin_headers, cliente_headers, storage_falso, generativo_falso, descarga_falsa, categoria_y_variante
):
    variante_id = categoria_y_variante["variante"]["id"]
    _subir_y_validar_overlay(client, admin_headers, variante_id)

    respuesta = client.post(
        "/api/v1/probador/generar",
        data={"variante_id": variante_id},
        files={"archivo": ("foto.jpg", io.BytesIO(_foto_jpeg()), "image/jpeg")},
        headers=cliente_headers,
    )
    assert respuesta.status_code == 202
    cuerpo = respuesta.json()
    assert cuerpo["desde_cache"] is False
    assert len(generativo_falso) == 1  # el proveedor se llamó una vez

    # BackgroundTasks corre antes de que TestClient devuelva el control acá:
    # para cuando llegamos a este GET, la generación ya terminó.
    estado = client.get(f"/api/v1/probador/generar/{cuerpo['id']}", headers=cliente_headers).json()
    assert estado["estado"] == "completado"
    assert estado["url_resultado"] is not None


def test_cache_segunda_llamada_con_misma_foto_es_instantanea(
    client, admin_headers, cliente_headers, storage_falso, generativo_falso, descarga_falsa, categoria_y_variante
):
    """El punto del checklist: la segunda llamada con la misma foto+prenda
    devuelve la URL cacheada sin volver a llamar al proveedor."""
    variante_id = categoria_y_variante["variante"]["id"]
    _subir_y_validar_overlay(client, admin_headers, variante_id)
    foto = _foto_jpeg()

    primera = client.post(
        "/api/v1/probador/generar",
        data={"variante_id": variante_id},
        files={"archivo": ("foto.jpg", io.BytesIO(foto), "image/jpeg")},
        headers=cliente_headers,
    ).json()
    assert primera["desde_cache"] is False
    assert len(generativo_falso) == 1

    segunda = client.post(
        "/api/v1/probador/generar",
        data={"variante_id": variante_id},
        files={"archivo": ("foto.jpg", io.BytesIO(foto), "image/jpeg")},
        headers=cliente_headers,
    ).json()
    assert segunda["desde_cache"] is True
    assert segunda["estado"] == "completado"
    assert len(generativo_falso) == 1  # no se llamó de nuevo al proveedor

    estado_primera = client.get(f"/api/v1/probador/generar/{primera['id']}", headers=cliente_headers).json()
    assert segunda["url_resultado"] == estado_primera["url_resultado"]


def test_generar_foto_original_no_se_persiste(
    client, admin_headers, cliente_headers, storage_falso, generativo_falso, descarga_falsa, categoria_y_variante, db_session
):
    variante_id = categoria_y_variante["variante"]["id"]
    _subir_y_validar_overlay(client, admin_headers, variante_id)
    foto = _foto_jpeg()

    client.post(
        "/api/v1/probador/generar",
        data={"variante_id": variante_id},
        files={"archivo": ("foto.jpg", io.BytesIO(foto), "image/jpeg")},
        headers=cliente_headers,
    )

    # La foto cruda nunca llega a Cloudinary (solo el resultado generado).
    assert foto not in storage_falso.values()

    # Lo único que queda de ella en la fila es su hash sha256 (64 hex).
    hash_foto = hashlib.sha256(foto).hexdigest()
    fila = service.generacion_repo.buscar_completado(db_session, hash_foto, variante_id)
    assert fila is not None
    assert fila.hash_foto == hash_foto
    assert len(fila.hash_foto) == 64


def test_generar_limite_diario(
    client, admin_headers, cliente_headers, storage_falso, generativo_falso, descarga_falsa, categoria_y_variante
):
    variante_id = categoria_y_variante["variante"]["id"]
    _subir_y_validar_overlay(client, admin_headers, variante_id)

    for i in range(service.LIMITE_GENERACIONES_DIARIAS):
        respuesta = client.post(
            "/api/v1/probador/generar",
            data={"variante_id": variante_id},
            files={"archivo": (f"foto{i}.jpg", io.BytesIO(_foto_jpeg(color=(i, i, i))), "image/jpeg")},
            headers=cliente_headers,
        )
        assert respuesta.status_code == 202, respuesta.json()

    respuesta = client.post(
        "/api/v1/probador/generar",
        data={"variante_id": variante_id},
        files={"archivo": ("foto-extra.jpg", io.BytesIO(_foto_jpeg(color=(99, 99, 99))), "image/jpeg")},
        headers=cliente_headers,
    )
    assert respuesta.status_code == 429


def test_generar_limite_diario_no_cuenta_hits_de_cache(
    client, admin_headers, cliente_headers, storage_falso, generativo_falso, descarga_falsa, categoria_y_variante
):
    """Repetir la misma foto no debería gastar cupo del límite diario."""
    variante_id = categoria_y_variante["variante"]["id"]
    _subir_y_validar_overlay(client, admin_headers, variante_id)
    foto = _foto_jpeg()

    for _ in range(service.LIMITE_GENERACIONES_DIARIAS + 2):
        respuesta = client.post(
            "/api/v1/probador/generar",
            data={"variante_id": variante_id},
            files={"archivo": ("foto.jpg", io.BytesIO(foto), "image/jpeg")},
            headers=cliente_headers,
        )
        assert respuesta.status_code == 202
    assert len(generativo_falso) == 1


def test_generar_limite_diario_no_cuenta_fallidos(
    client, admin_headers, cliente_headers, storage_falso, descarga_falsa, categoria_y_variante, monkeypatch
):
    """Si el proveedor externo falla, el intento no debería gastar cupo."""
    variante_id = categoria_y_variante["variante"]["id"]
    _subir_y_validar_overlay(client, admin_headers, variante_id)

    class _ProveedorCaido:
        nombre = "caido"

        def generar(self, foto_cliente: bytes, imagen_prenda: bytes) -> bytes:
            raise RuntimeError("proveedor caído")

    monkeypatch.setattr(service, "obtener_proveedor_generativo", lambda: _ProveedorCaido())

    for i in range(service.LIMITE_GENERACIONES_DIARIAS + 2):
        respuesta = client.post(
            "/api/v1/probador/generar",
            data={"variante_id": variante_id},
            files={"archivo": (f"foto{i}.jpg", io.BytesIO(_foto_jpeg(color=(i, i, i))), "image/jpeg")},
            headers=cliente_headers,
        )
        assert respuesta.status_code == 202, respuesta.json()


def test_generar_timeout_no_bloquea_el_background_task(
    client, admin_headers, cliente_headers, storage_falso, descarga_falsa, categoria_y_variante, monkeypatch
):
    """Si el proveedor externo se cuelga más allá del timeout, el
    background task tiene que devolver el control igual (marcando
    'fallido'), no quedarse esperando a que el hilo colgado termine solo."""
    variante_id = categoria_y_variante["variante"]["id"]
    _subir_y_validar_overlay(client, admin_headers, variante_id)

    class _ProveedorColgado:
        nombre = "colgado"

        def generar(self, foto_cliente: bytes, imagen_prenda: bytes) -> bytes:
            time.sleep(5)  # mucho más que el timeout de prueba de abajo
            return b"nunca-llega"

    monkeypatch.setattr(service, "obtener_proveedor_generativo", lambda: _ProveedorColgado())
    monkeypatch.setattr(service, "TIMEOUT_GENERACION_SEG", 0.2)

    inicio = time.monotonic()
    respuesta = client.post(
        "/api/v1/probador/generar",
        data={"variante_id": variante_id},
        files={"archivo": ("foto.jpg", io.BytesIO(_foto_jpeg()), "image/jpeg")},
        headers=cliente_headers,
    )
    duracion = time.monotonic() - inicio

    assert respuesta.status_code == 202
    assert duracion < 2  # si el shutdown del executor bloqueara, tardaría >=5s

    cuerpo = respuesta.json()
    estado = client.get(f"/api/v1/probador/generar/{cuerpo['id']}", headers=cliente_headers).json()
    assert estado["estado"] == "fallido"
    assert "espera agotado" in estado["mensaje_error"].lower()


def test_generar_requiere_autenticacion(client, categoria_y_variante):
    respuesta = client.post(
        "/api/v1/probador/generar",
        data={"variante_id": categoria_y_variante["variante"]["id"]},
        files={"archivo": ("foto.jpg", io.BytesIO(_foto_jpeg()), "image/jpeg")},
    )
    assert respuesta.status_code == 401


def test_consultar_generacion_ajena_falla(
    client, admin_headers, cliente_headers, storage_falso, generativo_falso, descarga_falsa, categoria_y_variante
):
    variante_id = categoria_y_variante["variante"]["id"]
    _subir_y_validar_overlay(client, admin_headers, variante_id)
    generacion = client.post(
        "/api/v1/probador/generar",
        data={"variante_id": variante_id},
        files={"archivo": ("foto.jpg", io.BytesIO(_foto_jpeg()), "image/jpeg")},
        headers=cliente_headers,
    ).json()

    client.post(
        "/api/v1/auth/registro",
        json={"nombre": "Otro", "apellido": "Cliente", "email": "otro@example.com", "password": "claveSegura123"},
    )
    token_otro = client.post(
        "/api/v1/auth/login", json={"email": "otro@example.com", "password": "claveSegura123"}
    ).json()["access_token"]

    respuesta = client.get(
        f"/api/v1/probador/generar/{generacion['id']}", headers={"Authorization": f"Bearer {token_otro}"}
    )
    assert respuesta.status_code == 403


# ---- POST /probador/sesion -------------------------------------------------------


def test_registrar_sesion_ok(client, cliente_headers, categoria_y_variante):
    respuesta = client.post(
        "/api/v1/probador/sesion",
        json={"variante_id": categoria_y_variante["variante"]["id"], "modo": "espejo", "duracion_seg": 42},
        headers=cliente_headers,
    )
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["modo"] == "espejo"
    assert cuerpo["duracion_seg"] == 42


def test_registrar_sesion_variante_inexistente_falla(client, cliente_headers):
    respuesta = client.post(
        "/api/v1/probador/sesion",
        json={"variante_id": 9999, "modo": "generativo"},
        headers=cliente_headers,
    )
    assert respuesta.status_code == 404


def test_registrar_sesion_requiere_autenticacion(client, categoria_y_variante):
    respuesta = client.post(
        "/api/v1/probador/sesion",
        json={"variante_id": categoria_y_variante["variante"]["id"], "modo": "espejo"},
    )
    assert respuesta.status_code == 401


# ---- POST /probador/talla --------------------------------------------------------


def _crear_medida(client, admin_headers, producto_id, talla_id, **rangos):
    return client.post(
        f"/api/v1/productos/{producto_id}/medidas",
        json={"talla_id": talla_id, **rangos},
        headers=admin_headers,
    ).json()


@pytest.fixture()
def tabla_medidas(client, admin_headers, categoria_y_variante):
    """Tres tallas (S, M, L) con rangos de pecho centrados alrededor de la
    estimación real que calcula `_estimar_medidas` para una persona de
    180cm/80kg, así el test no depende de recalcular la fórmula a mano."""
    pecho_est, cintura_est = service._estimar_medidas(180, 80)

    producto_id = categoria_y_variante["producto"]["id"]
    talla_m = categoria_y_variante["talla"]  # ya viene de la fixture, orden=2
    talla_s = client.post("/api/v1/tallas", json={"codigo": "S", "orden": 1}, headers=admin_headers).json()
    talla_l = client.post("/api/v1/tallas", json={"codigo": "L", "orden": 3}, headers=admin_headers).json()

    _crear_medida(client, admin_headers, producto_id, talla_s["id"], pecho_min_cm=str(pecho_est - 30), pecho_max_cm=str(pecho_est - 10))
    _crear_medida(
        client,
        admin_headers,
        producto_id,
        talla_m["id"],
        pecho_min_cm=str(pecho_est - 3),
        pecho_max_cm=str(pecho_est + 3),
        cintura_min_cm=str(cintura_est - 3),
        cintura_max_cm=str(cintura_est + 3),
    )
    _crear_medida(client, admin_headers, producto_id, talla_l["id"], pecho_min_cm=str(pecho_est + 10), pecho_max_cm=str(pecho_est + 30))

    return {"S": talla_s, "M": talla_m, "L": talla_l}


def test_recomendar_talla_sin_tabla_medida_devuelve_advertencia(client, cliente_headers, categoria_y_variante):
    respuesta = client.post(
        "/api/v1/probador/talla",
        json={
            "variante_id": categoria_y_variante["variante"]["id"],
            "estatura_cm": 180,
            "peso_kg": 80,
            "preferencia_ajuste": "regular",
        },
        headers=cliente_headers,
    )
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["talla_id"] is None
    assert cuerpo["advertencia"] is not None


def test_recomendar_talla_regular_elige_la_que_calza(client, cliente_headers, categoria_y_variante, tabla_medidas):
    respuesta = client.post(
        "/api/v1/probador/talla",
        json={
            "variante_id": categoria_y_variante["variante"]["id"],
            "estatura_cm": 180,
            "peso_kg": 80,
            "preferencia_ajuste": "regular",
        },
        headers=cliente_headers,
    )
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["talla_codigo"] == "M"
    assert cuerpo["advertencia"] is None


def test_recomendar_talla_ajustado_baja_una_talla(client, cliente_headers, categoria_y_variante, tabla_medidas):
    respuesta = client.post(
        "/api/v1/probador/talla",
        json={
            "variante_id": categoria_y_variante["variante"]["id"],
            "estatura_cm": 180,
            "peso_kg": 80,
            "preferencia_ajuste": "ajustado",
        },
        headers=cliente_headers,
    ).json()
    assert respuesta["talla_codigo"] == "S"


def test_recomendar_talla_holgado_sube_una_talla(client, cliente_headers, categoria_y_variante, tabla_medidas):
    respuesta = client.post(
        "/api/v1/probador/talla",
        json={
            "variante_id": categoria_y_variante["variante"]["id"],
            "estatura_cm": 180,
            "peso_kg": 80,
            "preferencia_ajuste": "holgado",
        },
        headers=cliente_headers,
    ).json()
    assert respuesta["talla_codigo"] == "L"


def test_recomendar_talla_variante_inexistente_falla(client, cliente_headers):
    respuesta = client.post(
        "/api/v1/probador/talla",
        json={"variante_id": 9999, "estatura_cm": 180, "peso_kg": 80, "preferencia_ajuste": "regular"},
        headers=cliente_headers,
    )
    assert respuesta.status_code == 404


def test_recomendar_talla_requiere_autenticacion(client, categoria_y_variante):
    respuesta = client.post(
        "/api/v1/probador/talla",
        json={
            "variante_id": categoria_y_variante["variante"]["id"],
            "estatura_cm": 180,
            "peso_kg": 80,
            "preferencia_ajuste": "regular",
        },
    )
    assert respuesta.status_code == 401
