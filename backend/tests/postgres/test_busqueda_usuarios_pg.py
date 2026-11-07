"""La búsqueda de usuarios en el servidor (`GET /usuarios?buscar=`) contra PostgreSQL real: ILIKE con ESCAPE y los
comodines `%` y `_` tratados como letras (en SQLite el comportamiento de LIKE es distinto)."""

from tests.postgres.conftest import CLAVE, registrar_cliente

USUARIOS = "/api/v1/usuarios"


def _crear(client_pg, admin_pg, email: str, nombre: str, apellido: str) -> int:
    respuesta = client_pg.post(
        USUARIOS,
        json={"nombre": nombre, "apellido": apellido, "email": email, "password": CLAVE},
        headers=admin_pg,
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _ids(client_pg, admin_pg, texto: str, **parametros) -> list[int]:
    respuesta = client_pg.get(USUARIOS, params={"buscar": texto, **parametros}, headers=admin_pg)
    assert respuesta.status_code == 200, respuesta.text
    return [u["id"] for u in respuesta.json()]


def test_busqueda_por_nombre_apellido_y_correo_sin_distinguir_mayusculas(client_pg, admin_pg):
    ana = _crear(client_pg, admin_pg, "ana.gomez@example.com", "Ana", "Gomez")
    _crear(client_pg, admin_pg, "otro@example.com", "Otro", "Zapata")

    assert _ids(client_pg, admin_pg, "ANA") == [ana]
    assert _ids(client_pg, admin_pg, "gomez") == [ana]
    assert _ids(client_pg, admin_pg, "ana gomez") == [ana]
    assert _ids(client_pg, admin_pg, "ana.gomez@EXAMPLE") == [ana]


def test_busqueda_encuentra_a_un_cliente_registrado_fuera_de_la_primera_pagina(client_pg, admin_pg, fabrica_pg):
    for i in range(5):
        _crear(client_pg, admin_pg, f"relleno{i}@example.com", "Relleno", f"Num{i}")
    cliente = registrar_cliente(client_pg, fabrica_pg, "luisa.cliente@example.com")

    primera = [u["id"] for u in client_pg.get(f"{USUARIOS}?pagina=1&tamanio=2", headers=admin_pg).json()]
    assert cliente not in primera

    assert _ids(client_pg, admin_pg, "luisa.cliente", pagina=1, tamanio=2) == [cliente]


def test_porcentaje_y_guion_bajo_son_letras_y_no_comodines(client_pg, admin_pg):
    _crear(client_pg, admin_pg, "normal@example.com", "Normal", "Persona")

    assert _ids(client_pg, admin_pg, "%") == []
    assert _ids(client_pg, admin_pg, "_") == []
    assert _ids(client_pg, admin_pg, "Nor_al") == []
    assert _ids(client_pg, admin_pg, "\\") == []
