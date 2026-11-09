"""E05, 4.4: matriz de listados. Cada listado de A trae SOLO datos de A (y el de B solo de B);
los filtros de consulta con ids de B no devuelven nada de B; la paginación no se sale."""

import pytest
from sqlalchemy import text

from app.comercial.repository import VW_VENTAS_DETALLE_V2_SQL

from .introspeccion import parametros_de_consulta, ruta_por_clave
from .plantillas import token_de_ruta
from .rutas_esperadas import LISTADO, MATRIZ, RUTAS

# Funcionalidades que el plan Básico de B NO incluye (A es Profesional). Un listado de estas
# funcionalidades no puede dar 200 a las dos empresas: a A le responde (200, o 409 si aún no hay
# modelo entrenado) y a B le responde 403 `plan_no_incluye_funcionalidad`. Se prueban aparte
# (más abajo) y quedan fuera de `LISTADOS`, que exige 200 a ambos lados (también en PostgreSQL).
FUNCIONALIDADES_SOLO_PROFESIONAL = {"reportes_ia", "analitica_ml", "copias_seguridad"}

_TODOS_LOS_LISTADOS = sorted(clave for clave, ruta in RUTAS.items() if ruta.clase == LISTADO and ruta.cobertura == MATRIZ)
LISTADOS_DE_PLAN_SUPERIOR = [c for c in _TODOS_LOS_LISTADOS if RUTAS[c].funcionalidad in FUNCIONALIDADES_SOLO_PROFESIONAL]
LISTADOS = [c for c in _TODOS_LOS_LISTADOS if c not in LISTADOS_DE_PLAN_SUPERIOR]

# Consulta mínima para que la ruta responda 200 (parámetros obligatorios). Función(universo).
CONSULTA_BASE = {
    ("GET", "/api/v1/catalogo/variantes/buscar"): lambda u: {"q": u.ids["sku"]},
    ("GET", "/api/v1/catalogo/variantes/detalle"): lambda u: {"variante_ids": str(u.ids["variante"])},
    ("GET", "/api/v1/inventario/disponibilidad"): lambda u: {"variante_id": u.ids["variante"]},
    ("GET", "/api/v1/inventario/stock"): lambda u: {"variante_id": u.ids["variante"]},
    ("GET", "/api/v1/inventario/movimientos"): lambda u: {"variante_id": u.ids["variante"], "sucursal_id": u.ids["sucursal"]},
    ("GET", "/api/v1/probador/assets"): lambda u: {"variante_id": u.ids["variante"]},
    ("GET", "/api/v1/sincronizacion/paquete/stock"): lambda u: {"sucursal_id": u.ids["sucursal"]},
    ("GET", "/api/v1/caja/turnos/actual"): lambda u: {"sucursal_id": u.ids["sucursal"]},
}

# Listados que leen una vista que solo existe en PostgreSQL: los cubre el perfil PostgreSQL.
SOLO_POSTGRESQL = {
    ("GET", "/api/v1/reportes/ventas"): "lee vw_ventas_detalle (vista solo de PostgreSQL)",
    ("GET", "/api/v1/reportes/dashboard"): "lee vw_ventas_detalle (vista solo de PostgreSQL)",
}

# Listados cuya respuesta no incluye ningún texto libre al que ponerle marca (ids, cifras,
# códigos globales). La ausencia de datos de B se comprueba por ids (ver `fuga_por_ids`).
SIN_MARCA = {
    ("GET", "/api/v1/inventario/alertas"): "solo cifras y ids de variante y sucursal",
    ("GET", "/api/v1/inventario/disponibilidad"): "solo cifras y ids",
    ("GET", "/api/v1/inventario/stock"): "solo cifras y ids",
    ("GET", "/api/v1/inventario/tipos-movimiento"): "catálogo global del sistema",
    ("GET", "/api/v1/permisos"): "catálogo global del sistema",
    ("GET", "/api/v1/roles"): "catálogo global del sistema",
    ("GET", "/api/v1/ordenes-compra"): "solo códigos, ids y cifras",
    ("GET", "/api/v1/recepciones"): "solo códigos, ids y cifras",
    ("GET", "/api/v1/transferencias"): "solo códigos, ids y cifras",
    ("GET", "/api/v1/reportes/inventario"): "solo cifras",
    ("GET", "/api/v1/reportes/reservas"): "solo cifras",
    ("GET", "/api/v1/inventario/valuacion"): "solo cifras",
    ("GET", "/api/v1/inventario/consolidado"): "nombre del producto sin marca en la vista",
    ("GET", "/api/v1/sincronizacion/paquete/stock"): "solo ids y cifras de stock",
    ("GET", "/api/v1/caja/turnos/actual"): "sin turno abierto solo trae ids y el monto sugerido",
    ("GET", "/api/v1/caja/turnos/estado"): "una tarjeta por sucursal; el nombre de la sucursal del universo no lleva marca en esta lista",
    ("GET", "/api/v1/sincronizacion/paquete/clientes"): "nombre y apellido del cliente del universo sin marca; el aislamiento se prueba en tests/sincronizacion/test_paquete_seguridad.py",
}

# Claves de una respuesta que son ids de un recurso con id único entre empresas.
CLAVE_A_RECURSO = {
    "sucursal_id": "sucursal",
    "sucursal_origen_id": "sucursal",
    "sucursal_destino_id": "sucursal",
    "variante_id": "variante",
    "producto_id": "producto",
    "cliente_id": "cliente",
    "venta_id": "venta",
    "proveedor_id": "proveedor",
    "categoria_id": "categoria",
    "ciudad_id": "ciudad",
    "zona_envio_id": "zona_envio",
}

# Parámetro de consulta -> recurso del universo, para las pruebas de filtro con ids de B.
FILTRO_A_RECURSO = {
    "sucursal_id": "sucursal",
    "categoria_id": "categoria",
    "talla_id": "talla",
    "color_id": "color",
    "material_id": "material",
    "temporada_id": "temporada",
    "coleccion_id": "coleccion",
    "producto_id": "producto",
    "variante_id": "variante",
    "cliente_id": "cliente",
    "proveedor_id": "proveedor",
}


def _recorrer(valor):
    if isinstance(valor, dict):
        for clave, hijo in valor.items():
            yield clave, hijo
            yield from _recorrer(hijo)
    elif isinstance(valor, list):
        for hijo in valor:
            yield from _recorrer(hijo)


def fuga_por_ids(cuerpo, ajena) -> list[str]:
    """Claves de la respuesta cuyo valor es un id de un recurso de la otra empresa."""
    fugas = []
    for clave, valor in _recorrer(cuerpo):
        recurso = CLAVE_A_RECURSO.get(clave)
        if recurso and valor is not None and valor == ajena.ids[recurso]:
            fugas.append(f"{clave}={valor}")
    return fugas


def _consulta(metodo, ruta, universo) -> dict:
    return CONSULTA_BASE.get((metodo, ruta), lambda u: {})(universo)


def _pedir(mundo, metodo, ruta, quien, params):
    return mundo.client.request(metodo, ruta, params=params, headers=quien.headers[token_de_ruta(metodo, ruta)])


def _ids(clave):
    return f"{clave[0]} {clave[1].removeprefix('/api/v1')}"


@pytest.mark.parametrize("clave", LISTADOS, ids=[_ids(c) for c in LISTADOS])
@pytest.mark.parametrize("lado", ["A", "B"])
def test_el_listado_trae_solo_datos_de_la_empresa(mundo, clave, lado):
    metodo, ruta = clave
    if clave in SOLO_POSTGRESQL:
        pytest.skip(SOLO_POSTGRESQL[clave])
    propia, ajena = (mundo.a, mundo.b) if lado == "A" else (mundo.b, mundo.a)
    respuesta = _pedir(mundo, metodo, ruta, propia, _consulta(metodo, ruta, propia))
    assert respuesta.status_code == 200, f"{metodo} {ruta}: {respuesta.status_code} {respuesta.text[:300]}"
    assert ajena.m("") not in respuesta.text, f"{metodo} {ruta}: marca de la otra empresa en la respuesta"
    assert fuga_por_ids(respuesta.json(), ajena) == [], f"{metodo} {ruta}: ids de la otra empresa"
    if clave not in SIN_MARCA:
        assert propia.m("") in respuesta.text, f"{metodo} {ruta}: no trae datos de la propia empresa (¿prueba mal armada?)"


def _filtros_de(clave) -> list[str]:
    metodo, ruta = clave
    return sorted(p for p in parametros_de_consulta(ruta_por_clave(metodo, ruta)) if p in FILTRO_A_RECURSO)


CASOS_FILTRO = [(clave, filtro) for clave in LISTADOS if clave not in SOLO_POSTGRESQL for filtro in _filtros_de(clave)]


@pytest.mark.parametrize("caso", CASOS_FILTRO, ids=[f"{_ids(c)} ?{f}" for c, f in CASOS_FILTRO])
def test_un_filtro_con_id_de_b_no_devuelve_datos_de_b(mundo, caso):
    (metodo, ruta), filtro = caso
    a, b = mundo.a, mundo.b
    consulta = {**_consulta(metodo, ruta, a), filtro: b.ids[FILTRO_A_RECURSO[filtro]]}
    respuesta = _pedir(mundo, metodo, ruta, a, consulta)
    assert respuesta.status_code in (200, 404), f"{metodo} {ruta}?{filtro}: {respuesta.status_code} {respuesta.text[:300]}"
    assert b.m("") not in respuesta.text
    if respuesta.status_code == 200:
        assert fuga_por_ids(respuesta.json(), b) == [], f"{metodo} {ruta}?{filtro}: ids de B en la respuesta"


@pytest.fixture(scope="module")
def vista_de_ventas(_mundo):
    """La vista de ventas solo existe de forma permanente en PostgreSQL; la analítica la lee en `/estado` y `/panel`.
    Se crea mientras corre este módulo y se retira al terminar (igual que en test_planes_y_suscripcion)."""
    with _mundo.engine.begin() as conexion:
        conexion.execute(text("DROP VIEW IF EXISTS vw_ventas_detalle"))
        conexion.execute(text(VW_VENTAS_DETALLE_V2_SQL))
    try:
        yield
    finally:
        with _mundo.engine.begin() as conexion:
            conexion.execute(text("DROP VIEW IF EXISTS vw_ventas_detalle"))


def test_los_listados_de_plan_superior_no_estan_vacios_y_b_no_los_incluye(mundo):
    """Guarda de la partición: A (Profesional) incluye la funcionalidad de cada listado y B (Básico) no."""
    assert LISTADOS_DE_PLAN_SUPERIOR, "ya no hay listados de plan superior: ¿se quitó la analítica del registro?"
    for clave in LISTADOS_DE_PLAN_SUPERIOR:
        funcionalidad = RUTAS[clave].funcionalidad
        incluidas = {}
        for lado, universo in (("A", mundo.a), ("B", mundo.b)):
            respuesta = mundo.client.get("/api/v1/mi-empresa/suscripcion", headers=universo.admin)
            assert respuesta.status_code == 200, respuesta.text[:200]
            incluidas[lado] = funcionalidad in respuesta.json()["funcionalidades"]
        assert incluidas == {"A": True, "B": False}, f"{clave}: {funcionalidad} {incluidas}"


@pytest.mark.parametrize("clave", LISTADOS_DE_PLAN_SUPERIOR, ids=[_ids(c) for c in LISTADOS_DE_PLAN_SUPERIOR])
@pytest.mark.parametrize("lado", ["A", "B"])
def test_el_listado_de_plan_superior_da_lo_suyo_a_a_y_403_de_plan_a_b(mundo, vista_de_ventas, clave, lado):
    metodo, ruta = clave
    propia, ajena = (mundo.a, mundo.b) if lado == "A" else (mundo.b, mundo.a)
    respuesta = _pedir(mundo, metodo, ruta, propia, _consulta(metodo, ruta, propia))
    cuerpo = respuesta.json()
    if lado == "A":
        # Sin modelo entrenado, la demanda, los segmentos, las anomalías y la reposición responden 409; el estado y el panel, 200.
        if respuesta.status_code == 409:
            assert cuerpo["codigo"] == "modelo_no_entrenado", f"{metodo} {ruta}: {respuesta.text[:300]}"
        else:
            assert respuesta.status_code == 200, f"{metodo} {ruta}: {respuesta.status_code} {respuesta.text[:300]}"
    else:
        assert respuesta.status_code == 403, f"{metodo} {ruta}: {respuesta.status_code} {respuesta.text[:300]}"
        assert cuerpo["codigo"] == "plan_no_incluye_funcionalidad"
        assert cuerpo["funcionalidad"] == RUTAS[clave].funcionalidad
    assert ajena.m("") not in respuesta.text, f"{metodo} {ruta}: marca de la otra empresa en la respuesta"
    assert fuga_por_ids(cuerpo, ajena) == [], f"{metodo} {ruta}: ids de la otra empresa"
    # Sin datos de texto libre que marcar: lo que prueba el aislamiento de fondo con un modelo
    # entrenado está en tests/inteligencia/test_analitica_aislamiento.py.


CASOS_FILTRO_PLAN_SUPERIOR = [(clave, filtro) for clave in LISTADOS_DE_PLAN_SUPERIOR for filtro in _filtros_de(clave)]


@pytest.mark.parametrize("caso", CASOS_FILTRO_PLAN_SUPERIOR, ids=[f"{_ids(c)} ?{f}" for c, f in CASOS_FILTRO_PLAN_SUPERIOR])
def test_un_filtro_con_id_de_b_no_devuelve_datos_de_b_en_los_de_plan_superior(mundo, vista_de_ventas, caso):
    (metodo, ruta), filtro = caso
    a, b = mundo.a, mundo.b
    consulta = {**_consulta(metodo, ruta, a), filtro: b.ids[FILTRO_A_RECURSO[filtro]]}
    respuesta = _pedir(mundo, metodo, ruta, a, consulta)
    # 409: A aún no tiene modelo y no llega a mirar el filtro; 404: la categoría de B se ve como inexistente.
    assert respuesta.status_code in (200, 404, 409), f"{metodo} {ruta}?{filtro}: {respuesta.status_code} {respuesta.text[:300]}"
    if respuesta.status_code == 409:
        assert respuesta.json()["codigo"] == "modelo_no_entrenado"
    assert b.m("") not in respuesta.text
    if respuesta.status_code == 200:
        assert fuga_por_ids(respuesta.json(), b) == [], f"{metodo} {ruta}?{filtro}: ids de B en la respuesta"


CON_PAGINA = [c for c in LISTADOS if c not in SOLO_POSTGRESQL and "pagina" in parametros_de_consulta(ruta_por_clave(*c))]


@pytest.mark.parametrize("clave", CON_PAGINA, ids=[_ids(c) for c in CON_PAGINA])
def test_la_segunda_pagina_no_trae_datos_de_b(mundo, clave):
    metodo, ruta = clave
    a, b = mundo.a, mundo.b
    for pagina in (1, 2, 3):
        consulta = {**_consulta(metodo, ruta, a), "pagina": pagina, "tamanio": 1}
        respuesta = _pedir(mundo, metodo, ruta, a, consulta)
        assert respuesta.status_code == 200, f"{metodo} {ruta} pagina {pagina}: {respuesta.status_code} {respuesta.text[:200]}"
        assert b.m("") not in respuesta.text
