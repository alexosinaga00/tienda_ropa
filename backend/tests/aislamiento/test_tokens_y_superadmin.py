"""E05, 4.5: autenticación, superadministrador y tokens.

- Toda ruta autenticada rechaza (401) un token sin `empresa_id`, uno con el `empresa_id` de otra
  empresa, uno firmado con otra clave, uno adulterado, el de una empresa inactiva y la ausencia de token.
- El superadministrador (modo plataforma) no alcanza datos de negocio (403, o 401 donde se exige
  perfil de cliente); sí entra a /plataforma, donde el administrador y el cajero de una empresa reciben 403.
- Los roles son globales: el administrador de una empresa no los escribe ni asigna el de superadministrador.
- `empresa_id` en el cuerpo, la query o las cabeceras no cambia la empresa efectiva.
- El mismo correo en dos empresas son dos cuentas distintas; el cliente registrado en una tienda
  no entra en la otra.

Las empresas descartables (`desc-e05-N`) son propias de este archivo y se dan de baja al terminar:
el universo (A y B) es compartido por todo el paquete y no se altera.
"""

import copy

import pytest

from app.core.database import get_db
from app.main import app

from .ayudas_tokens import (
    API,
    CLASES_DE_NEGOCIO,
    CLASES_NO_AUTENTICADAS,
    CLAVE,
    armar_ruta,
    cabecera_superadmin,
    crear_descartable,
    datos_del_usuario,
    hay_marca,
    nombre_corto,
    poner_activa_empresa,
    retirar_descartable,
    rutas_de,
    token_adulterado,
    token_con_empresa_ajena,
    token_con_otra_clave,
    token_sin_empresa_id,
)
from .casos_fk import PNG
from .oraculo import ID_INEXISTENTE
from .rutas_esperadas import PLATAFORMA, RUTAS

# --- 1. tokens inválidos en TODA ruta autenticada ----------------------------------------------

TODAS = sorted(RUTAS)
AUTENTICADAS = sorted(c for c, r in RUTAS.items() if r.clase not in CLASES_NO_AUTENTICADAS)



def extras_de(clave, universo=None) -> dict:
    """Parámetros mínimos para que la petición llegue hasta el handler.

    FastAPI valida el cuerpo y la query ANTES de entrar al handler: una ruta cuya identidad la resuelve
    el filtro de empresa (y no una dependencia propia: `/ia/*`, cotizar, disponibilidad) o un superadministrador
    que debe chocar con el cierre del modo plataforma darían 422 y no 401/403 si faltara un campo obligatorio.
    Con `universo` los ids son reales (solo para lecturas); sin él, no existen en ninguna empresa."""
    variante = universo.ids["variante"] if universo is not None else ID_INEXISTENTE
    tabla = {
        ("GET", f"{API}/catalogo/variantes/detalle"): {"params": {"variante_ids": variante}},
        ("GET", f"{API}/inventario/disponibilidad"): {"params": {"variante_id": variante}},
        ("POST", f"{API}/envios/cotizar"): {"json": {"direccion_id": ID_INEXISTENTE, "cantidad_prendas": 1}},
        ("POST", f"{API}/favoritos"): {"json": {"variante_id": ID_INEXISTENTE}},
        ("POST", f"{API}/ia/voz"): {"json": {"texto": "camisa"}},
        ("POST", f"{API}/ia/eventos"): {"json": {"tipo_evento": "vista", "producto_id": ID_INEXISTENTE}},
        ("POST", f"{API}/probador/generar"): {
            "data": {"variante_id": str(ID_INEXISTENTE)},
            "files": {"archivo": ("prenda.png", PNG, "image/png")},
        },
        ("POST", f"{API}/probador/talla"): {"json": {"variante_id": ID_INEXISTENTE, "estatura_cm": 175, "peso_kg": 70}},
        ("PUT", f"{API}/clientes/perfil"): {"json": {"telefono": "70000000"}},
        ("POST", f"{API}/dispositivos-push"): {"json": {"token": "t" * 40, "plataforma": "android"}},
        ("POST", f"{API}/dispositivos-push/baja"): {"json": {"token": "t" * 40}},
    }
    return copy.deepcopy(tabla.get(clave, {}))


@pytest.fixture(scope="module")
def empresa_inactiva(_mundo):
    """Una empresa descartable con su administrador, dada de baja DESPUÉS de emitirle el token."""
    empresa = crear_descartable(_mundo, con_admin=True)
    poner_activa_empresa(_mundo, empresa.id, False)
    yield empresa
    retirar_descartable(_mundo, empresa)


@pytest.fixture(scope="module")
def tokens_a_medida(_mundo, empresa_inactiva):
    """Los tokens inválidos del administrador de A (nombre -> cabeceras)."""
    a, b = _mundo.a, _mundo.b
    roles, permisos = datos_del_usuario(_mundo, a)
    return {
        "sin token": {},
        "sin la clave empresa_id": token_sin_empresa_id(a.empresa.admin_id, roles, permisos),
        "usuario de A con el empresa_id de B": token_con_empresa_ajena(a.empresa.admin_id, b.id, roles, permisos),
        "firmado con otra clave": token_con_otra_clave(a.empresa.admin_id, a.id, roles, permisos),
        "adulterado (empresa_id cambiado sin firmar)": token_adulterado(a.admin, b.id),
        "empresa inactiva": empresa_inactiva.headers,
    }


@pytest.mark.parametrize("clave", AUTENTICADAS, ids=[nombre_corto(c) for c in AUTENTICADAS])
def test_ruta_autenticada_rechaza_cualquier_token_invalido(mundo, tokens_a_medida, clave):
    metodo, ruta = clave
    url = armar_ruta(ruta, inexistente=True)
    fallas = []
    for nombre, cabeceras in tokens_a_medida.items():
        respuesta = mundo.client.request(metodo, url, headers=cabeceras, **extras_de(clave))
        if respuesta.status_code != 401:
            fallas.append(f"{nombre}: {respuesta.status_code} {respuesta.text[:160]}")
    assert not fallas, f"{metodo} {url} debía dar 401 en todos los casos:\n  " + "\n  ".join(fallas)


def test_hay_unas_190_rutas_autenticadas():
    # Si cambia el registro, esta cuenta avisa que la parametrización cubre lo que se espera.
    assert 150 <= len(AUTENTICADAS) <= 260, len(AUTENTICADAS)  # 233 con las 7 rutas de /analitica (E12)
    assert len(AUTENTICADAS) + sum(1 for c in TODAS if RUTAS[c].clase in CLASES_NO_AUTENTICADAS) == len(RUTAS)


# --- 2. el superadministrador --------------------------------------------------------------------

NEGOCIO = rutas_de(CLASES_DE_NEGOCIO)

# Rutas de negocio que NO tocan tablas de empresa (roles, permisos y la propia sesión son globales):
# el superadministrador las usa de verdad. Se comprueba aparte que no traen marcas de ninguna empresa.
GLOBALES_PARA_SUPER = {
    ("GET", f"{API}/auth/yo"): "su propia sesión",
    ("GET", f"{API}/permisos"): "catálogo global de permisos",
    ("GET", f"{API}/roles"): "roles globales",
    ("GET", f"{API}/roles/{{rol_id}}"): "roles globales",
    ("POST", f"{API}/roles"): "escribe roles (plataforma.gestionar)",
    ("PUT", f"{API}/roles/{{rol_id}}"): "escribe roles (plataforma.gestionar)",
    ("DELETE", f"{API}/roles/{{rol_id}}"): "escribe roles (plataforma.gestionar)",
    ("PUT", f"{API}/roles/{{rol_id}}/permisos"): "escribe roles (plataforma.gestionar)",
}


@pytest.mark.parametrize("clave", NEGOCIO, ids=[nombre_corto(c) for c in NEGOCIO])
def test_superadmin_no_alcanza_datos_de_negocio(mundo, clave):
    metodo, ruta = clave
    superadmin = cabecera_superadmin(mundo)
    # Lecturas con ids REALES de A (si el cierre fallara, aparecerían datos); escrituras con ids que no
    # existen, para que una fuga no dañe al universo compartido.
    url = armar_ruta(ruta, mundo.a) if metodo == "GET" else armar_ruta(ruta, inexistente=True)
    respuesta = mundo.client.request(
        metodo, url, headers=superadmin, **extras_de(clave, mundo.a if metodo == "GET" else None)
    )
    detalle = f"{metodo} {url} -> {respuesta.status_code} {respuesta.text[:200]}"
    assert not hay_marca(respuesta.text), f"marcas de una empresa en la respuesta al superadministrador: {detalle}"
    if clave in GLOBALES_PARA_SUPER:
        assert respuesta.status_code < 500, detalle
        return
    assert respuesta.status_code in (401, 403), f"se esperaba 403 (modo plataforma) o 401: {detalle}"


PLATAFORMA_RUTAS = rutas_de({PLATAFORMA})


def test_hay_19_rutas_de_plataforma():
    # 18 de CU-04 (E04) + GET /plataforma/bitacora (E06).
    assert len(PLATAFORMA_RUTAS) == 19


@pytest.mark.parametrize("clave", PLATAFORMA_RUTAS, ids=[nombre_corto(c) for c in PLATAFORMA_RUTAS])
def test_plataforma_es_solo_del_superadministrador(mundo, clave):
    metodo, ruta = clave
    url = armar_ruta(ruta, inexistente=True)  # ids que no existen: nada de esto toca a las empresas reales
    con_super = mundo.client.request(metodo, url, headers=cabecera_superadmin(mundo))
    assert con_super.status_code not in (401, 403), f"el superadministrador no entra: {metodo} {url} -> {con_super.status_code} {con_super.text[:200]}"
    assert con_super.status_code < 500
    if metodo == "GET" and "{" not in ruta:  # los listados responden 200
        assert con_super.status_code == 200, f"{metodo} {url} -> {con_super.status_code} {con_super.text[:200]}"
    for quien in ("admin", "cajero"):
        respuesta = mundo.client.request(metodo, url, headers=mundo.a.headers[quien])
        assert respuesta.status_code == 403, f"{quien} de A en {metodo} {url} -> {respuesta.status_code} {respuesta.text[:200]}"
    # Y el administrador de B (plan Básico) tampoco.
    de_b = mundo.client.request(metodo, url, headers=mundo.b.admin)
    assert de_b.status_code == 403, f"admin de B en {metodo} {url} -> {de_b.status_code}"


@pytest.mark.parametrize("quien", ["a", "b"])
def test_control_el_token_valido_si_funciona(mundo, quien):
    """Prueba positiva espejo: los tokens buenos entran. Sin esto, un 401 en todo sería una prueba verde falsa."""
    universo = mundo.a if quien == "a" else mundo.b
    for ruta in ("/sucursales", "/productos", "/auth/yo", "/categorias"):
        respuesta = mundo.client.get(f"{API}{ruta}", headers=universo.admin)
        assert respuesta.status_code == 200, f"{ruta}: {respuesta.status_code} {respuesta.text[:200]}"


# --- 3. roles globales ------------------------------------------------------------------------------


def _roles(mundo, headers) -> list[dict]:
    respuesta = mundo.client.get(f"{API}/roles?limite=100", headers=headers)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


@pytest.fixture(scope="module")
def rol_descartable(_mundo):
    """Un rol creado por el superadministrador solo para que el administrador de una empresa intente
    escribirlo: si una escritura se colara, solo caería este rol y no uno de verdad. Se desactiva al final."""
    app.dependency_overrides[get_db] = _mundo.db_por_peticion  # `mundo` (por prueba) aún no corrió
    superadmin = cabecera_superadmin(_mundo)
    creado = _mundo.client.post(
        f"{API}/roles", json={"nombre": "descartable-e05", "descripcion": "solo para pruebas"}, headers=superadmin
    )
    assert creado.status_code == 201, creado.text
    yield creado.json()["id"]
    _mundo.client.delete(f"{API}/roles/{creado.json()['id']}", headers=superadmin)


ESCRITURAS_DE_ROLES = (
    ("POST", "/roles", {"nombre": "inventado-e05", "descripcion": "x"}),
    ("PUT", "/roles/{id}", {"descripcion": "cambiada"}),
    ("DELETE", "/roles/{id}", None),
    ("PUT", "/roles/{id}/permisos", {"codigos_permiso": ["catalogo.ver"]}),
)


@pytest.mark.parametrize("quien", ["admin_a", "cajero_a", "admin_b"])
@pytest.mark.parametrize(("metodo", "ruta", "cuerpo"), ESCRITURAS_DE_ROLES, ids=[f"{m} {r}" for m, r, _ in ESCRITURAS_DE_ROLES])
def test_ninguna_empresa_escribe_roles(mundo, rol_descartable, quien, metodo, ruta, cuerpo):
    headers = {"admin_a": mundo.a.admin, "cajero_a": mundo.a.headers["cajero"], "admin_b": mundo.b.admin}[quien]
    respuesta = mundo.client.request(metodo, API + ruta.format(id=rol_descartable), json=cuerpo, headers=headers)
    assert respuesta.status_code == 403, f"{quien}: {metodo} {ruta} -> {respuesta.status_code} {respuesta.text[:200]}"
    # El rol sigue intacto (activo y con su descripción original) y se ve desde la plataforma.
    visto = mundo.client.get(f"{API}/roles/{rol_descartable}", headers=cabecera_superadmin(mundo))
    assert visto.status_code == 200 and visto.json()["descripcion"] == "solo para pruebas"


@pytest.mark.parametrize("quien", ["a", "b"])
def test_get_roles_de_una_empresa_no_lista_al_superadministrador(mundo, quien):
    universo = mundo.a if quien == "a" else mundo.b
    de_empresa = _roles(mundo, universo.admin)
    de_plataforma = _roles(mundo, cabecera_superadmin(mundo))
    assert "superadministrador" not in {r["nombre"] for r in de_empresa}
    assert {"administrador", "cajero", "cliente"} <= {r["nombre"] for r in de_empresa}
    id_super = next(r["id"] for r in de_plataforma if r["nombre"] == "superadministrador")
    # Tampoco por id: se ve igual que un rol inexistente.
    ajeno = mundo.client.get(f"{API}/roles/{id_super}", headers=universo.admin)
    inexistente = mundo.client.get(f"{API}/roles/{ID_INEXISTENTE}", headers=universo.admin)
    assert ajeno.status_code == inexistente.status_code == 404
    assert ajeno.json() == inexistente.json()


@pytest.mark.parametrize("quien", ["a", "b"])
@pytest.mark.parametrize("roles", [["superadministrador"], ["cajero", "superadministrador"]], ids=["solo", "con_otro_rol"])
def test_no_se_asigna_el_rol_superadministrador_a_un_usuario_de_empresa(mundo, quien, roles):
    universo = mundo.a if quien == "a" else mundo.b
    usuario = universo.ids["usuario_extra"]
    antes = mundo.client.get(f"{API}/usuarios/{usuario}", headers=universo.admin).json()
    respuesta = mundo.client.put(f"{API}/usuarios/{usuario}/roles", json={"nombres_rol": roles}, headers=universo.admin)
    assert respuesta.status_code == 403, f"{respuesta.status_code} {respuesta.text[:200]}"
    despues = mundo.client.get(f"{API}/usuarios/{usuario}", headers=universo.admin).json()
    assert despues == antes, "el rechazo dejó el usuario cambiado"
    assert "superadministrador" not in str(despues)


def test_el_superadministrador_si_escribe_roles(mundo):
    superadmin = cabecera_superadmin(mundo)
    creado = mundo.client.post(
        f"{API}/roles", json={"nombre": "auditor-e05", "descripcion": "Solo lectura"}, headers=superadmin
    )
    assert creado.status_code == 201, creado.text
    rol_id = creado.json()["id"]
    try:
        actualizado = mundo.client.put(f"{API}/roles/{rol_id}", json={"descripcion": "Otra"}, headers=superadmin)
        con_permisos = mundo.client.put(
            f"{API}/roles/{rol_id}/permisos", json={"codigos_permiso": ["catalogo.ver"]}, headers=superadmin
        )
        assert actualizado.status_code == 200 and actualizado.json()["descripcion"] == "Otra"
        assert con_permisos.status_code == 200
        assert [p["codigo"] for p in con_permisos.json()["permisos"]] == ["catalogo.ver"]
    finally:
        desactivado = mundo.client.delete(f"{API}/roles/{rol_id}", headers=superadmin)
    assert desactivado.status_code == 204


# --- 4. empresa_id en el cuerpo, la query o las cabeceras no cuenta ---------------------------------------


ALTAS = [
    ("ciudades", lambda u, n: {"nombre": f"Ciudad inyectada {n}"}),
    ("categorias", lambda u, n: {"nombre": f"Categoria inyectada {n}"}),
    ("tallas", lambda u, n: {"codigo": f"I{n}", "orden": 80 + n}),
    ("colores", lambda u, n: {"nombre": f"Color inyectado {n}"}),
    ("materiales", lambda u, n: {"nombre": f"Material inyectado {n}"}),
    ("temporadas", lambda u, n: {"nombre": f"Temporada inyectada {n}", "anio": 2024}),
    ("colecciones", lambda u, n: {"nombre": f"Coleccion inyectada {n}"}),
    ("proveedores", lambda u, n: {"nombre": f"Proveedor inyectado {n}"}),
    ("zonas-envio", lambda u, n: {"ciudad_id": u.ids["ciudad"], "nombre": f"Zona inyectada {n}", "tarifa_base": "5.00"}),
    ("usuarios", lambda u, n: {"nombre": "Inyectado", "apellido": str(n), "email": f"inyectado{n}@tienda.bo", "password": CLAVE}),
]

def _deltas(cambios: list[str]) -> dict[str, int]:
    """'ciudad: 2 -> 3 filas' -> {'ciudad': 1}: cuántas filas cambió cada tabla, sin importar cuántas había."""
    resultado = {}
    for linea in cambios:
        tabla, _, resto = linea.partition(": ")
        antes, _, despues = resto.removesuffix(" filas").partition(" -> ")
        resultado[tabla] = int(despues) - int(antes) if despues.isdigit() and antes.isdigit() else resto
    return resultado


MODOS_DE_INYECCION =["cuerpo", "query", "cabeceras", "todo"]


def _alta(mundo, recurso, fabrica, modo):
    """Da de alta un registro en A, con `empresa_id` de B colado según `modo`. Devuelve la respuesta y
    los cambios en A y en B."""
    a, b = mundo.a, mundo.b
    cuerpo, params, cabeceras = fabrica(a, a.n()), {}, dict(a.admin)
    if modo in ("cuerpo", "todo"):
        cuerpo["empresa_id"] = b.id
    if modo in ("query", "todo"):
        params["empresa_id"] = b.id
    if modo in ("cabeceras", "todo"):
        cabeceras.update({"X-Empresa-Id": str(b.id), "X-Tenant": b.codigo, "X-Empresa": b.codigo})
    antes_a, antes_b = mundo.instantanea(a.id), mundo.instantanea(b.id)
    respuesta = mundo.client.post(f"{API}/{recurso}", json=cuerpo, params=params, headers=cabeceras)
    return respuesta, mundo.cambios(antes_a, mundo.instantanea(a.id)), mundo.cambios(antes_b, mundo.instantanea(b.id))


@pytest.mark.parametrize("modo", MODOS_DE_INYECCION)
@pytest.mark.parametrize(("recurso", "fabrica"), ALTAS, ids=[r for r, _ in ALTAS])
def test_empresa_id_colado_en_un_alta_no_cambia_la_empresa(mundo, recurso, fabrica, modo):
    control, cambios_control, _ = _alta(mundo, recurso, fabrica, "ninguno")
    assert control.status_code == 201, f"el alta de control falló (prueba mal armada): {control.status_code} {control.text[:200]}"
    colado, cambios_a, cambios_b = _alta(mundo, recurso, fabrica, modo)
    assert colado.status_code == control.status_code, f"{modo}: {colado.status_code} {colado.text[:200]}"
    assert set(colado.json()) == set(control.json()), f"{modo}: la respuesta cambió de forma"
    assert _deltas(cambios_a) == _deltas(cambios_control), (
        f"{modo}: A cambió distinto que sin el campo: {cambios_a} / {cambios_control}"
    )
    assert _deltas(cambios_a), "el alta no dejó nada en A (prueba mal armada)"
    assert cambios_b == [], f"{modo}: B cambió: {cambios_b}"


LECTURAS = [
    "/productos", "/sucursales", "/categorias", "/ciudades", "/proveedores", "/promociones", "/usuarios", "/empleados",
    "/productos/{producto_id}", "/sucursales/{sucursal_id}",
]


@pytest.mark.parametrize("ruta", LECTURAS)
def test_empresa_id_colado_en_una_lectura_no_cambia_la_empresa(mundo, ruta):
    a, b = mundo.a, mundo.b
    url = API + armar_ruta(ruta, a)
    limpia = mundo.client.get(url, headers=a.admin)
    colada = mundo.client.get(
        url,
        params={"empresa_id": b.id},
        headers={**a.admin, "X-Empresa-Id": str(b.id), "X-Tenant": b.codigo, "X-Empresa": b.codigo},
    )
    assert limpia.status_code == 200, limpia.text[:200]
    assert colada.status_code == limpia.status_code
    assert colada.text == limpia.text, "el resultado cambió al colar empresa_id"
    assert b.m("") not in colada.text and a.m("") in colada.text


def test_empresa_id_colado_en_una_ruta_publica_no_cambia_la_tienda(mundo):
    a, b = mundo.a, mundo.b
    url = f"{API}/public/{a.codigo}/categorias"
    limpia = mundo.client.get(url)
    colada = mundo.client.get(
        url, params={"empresa_id": b.id}, headers={"X-Empresa-Id": str(b.id), "X-Tenant": b.codigo, "X-Empresa": b.codigo}
    )
    assert limpia.status_code == colada.status_code == 200
    assert colada.text == limpia.text
    assert b.m("") not in colada.text and a.m("") in colada.text


def test_empresa_id_colado_no_da_acceso_al_recurso_de_otra_empresa(mundo):
    a, b = mundo.a, mundo.b
    ruta = f"{API}/productos/{b.ids['producto']}"
    inexistente = mundo.client.get(f"{API}/productos/{ID_INEXISTENTE}", headers=a.admin)
    colada = mundo.client.get(
        ruta, params={"empresa_id": b.id}, headers={**a.admin, "X-Empresa-Id": str(b.id), "X-Tenant": b.codigo}
    )
    assert colada.status_code == 404 and inexistente.status_code == 404
    assert b.m("") not in colada.text


# --- 5. el mismo correo en las dos empresas ------------------------------------------------------------------


def _login(mundo, empresa, email, password):
    cuerpo = {"email": email, "password": password}
    if empresa is not None:
        cuerpo["empresa"] = empresa
    return mundo.client.post(f"{API}/auth/login", json=cuerpo)


def test_el_mismo_correo_en_dos_empresas_son_dos_cuentas(mundo):
    a, b = mundo.a, mundo.b
    correo, clave_a, clave_b = f"gemelo{a.n()}@tienda.bo", "claveDeLaEmpresaA1", "claveDeLaEmpresaB2"
    cuerpo = {"nombre": "Ge", "apellido": "Melo", "email": correo}
    en_a = mundo.client.post(f"{API}/usuarios", json={**cuerpo, "password": clave_a}, headers=a.admin)
    en_b = mundo.client.post(f"{API}/usuarios", json={**cuerpo, "password": clave_b}, headers=b.admin)
    assert en_a.status_code == en_b.status_code == 201, (en_a.text, en_b.text)
    assert en_a.json()["id"] != en_b.json()["id"]

    # Hasta 4 fallos por cuenta (el 5.º bloquea): aquí A acumula 2 y B 1.
    clave_de_b_en_a = _login(mundo, a.codigo, correo, clave_b)
    clave_mala_en_a = _login(mundo, a.codigo, correo, "una-clave-cualquiera-9")
    clave_de_a_en_b = _login(mundo, b.codigo, correo, clave_a)
    assert clave_de_b_en_a.status_code == 401 and clave_de_a_en_b.status_code == 401
    assert clave_de_b_en_a.json() == clave_mala_en_a.json()  # el mismo 401 que una clave mala
    assert clave_de_a_en_b.json() == clave_mala_en_a.json()
    # Sin empresa solo entra un superadministrador: una cuenta de empresa nunca.
    assert _login(mundo, None, correo, clave_a).status_code == 401

    for universo, clave, id_esperado in ((a, clave_a, en_a.json()["id"]), (b, clave_b, en_b.json()["id"])):
        entrada = _login(mundo, universo.codigo, correo, clave)
        assert entrada.status_code == 200, entrada.text
        yo = mundo.client.get(
            f"{API}/auth/yo", headers={"Authorization": f"Bearer {entrada.json()['access_token']}"}
        ).json()
        assert yo["id"] == id_esperado and yo["email"] == correo
        assert yo["empresa_id"] == universo.id and yo["empresa_codigo"] == universo.codigo


# --- 6. el cliente registrado en una tienda no entra en la otra -----------------------------------------------


def _registrar(mundo, codigo, email, password):
    return mundo.client.post(
        f"{API}/public/{codigo}/registro", json={"nombre": "Cli", "apellido": "Registro", "email": email, "password": password}
    )


@pytest.mark.parametrize(("origen", "otra"), [("a", "b"), ("b", "a")])
def test_el_cliente_registrado_en_una_tienda_no_entra_en_la_otra(mundo, origen, otra):
    de = {"a": mundo.a, "b": mundo.b}
    correo = f"cliente-{origen}{mundo.a.n()}@tienda.bo"
    clave_origen, clave_otra = "claveDeLaTiendaDeOrigen1", "claveDeLaOtraTienda2"

    registro = _registrar(mundo, de[origen].codigo, correo, clave_origen)
    assert registro.status_code == 201, registro.text
    assert _login(mundo, de[origen].codigo, correo, clave_origen).status_code == 200
    # Mismo correo y misma clave en la OTRA tienda: no existe esa cuenta.
    assert _login(mundo, de[otra].codigo, correo, clave_origen).status_code == 401
    # Y el correo no está tomado allí: se puede registrar como cuenta nueva, con otra clave.
    nuevo = _registrar(mundo, de[otra].codigo, correo, clave_otra)
    assert nuevo.status_code == 201, nuevo.text
    assert nuevo.json()["id"] != registro.json()["id"]
    assert _login(mundo, de[origen].codigo, correo, clave_otra).status_code == 401
    assert _login(mundo, de[otra].codigo, correo, clave_otra).status_code == 200
