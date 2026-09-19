"""MOB-001: contrato de POST /ia/eventos entre la app y el backend."""


def test_evento_con_tipo_evento_se_registra(client):
    respuesta = client.post("/api/v1/ia/eventos", json={"tipo_evento": "busqueda"})
    assert respuesta.status_code == 201


def test_evento_con_tipo_de_versiones_viejas_de_la_app_tambien_se_registra(client):
    """Las apps instaladas antes de la corrección mandan `tipo` (más
    `texto` y `creado_en`, que el backend ignora)."""
    respuesta = client.post(
        "/api/v1/ia/eventos",
        json={"tipo": "busqueda", "texto": "camisa", "creado_en": "2026-09-18T10:00:00.000"},
    )
    assert respuesta.status_code == 201


def test_evento_sin_tipo_o_con_tipo_invalido_da_422(client):
    assert client.post("/api/v1/ia/eventos", json={"producto_id": 1}).status_code == 422
    assert client.post("/api/v1/ia/eventos", json={"tipo_evento": "otro"}).status_code == 422
