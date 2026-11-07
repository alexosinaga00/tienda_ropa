"""CRUD de usuarios (/api/v1/usuarios), roles (/api/v1/roles) y catálogo de
permisos (/api/v1/permisos). Comportamiento actual, fijado antes del refactor
(puntos 1, 3, 4, 5, 10 y 16 de 2.1 del análisis)."""

import pytest

from app.plataforma.models import Rol, Usuario
from tests.conftest import crear_superadmin_de_prueba

USUARIOS = "/api/v1/usuarios"
ROLES = "/api/v1/roles"
PERMISOS = "/api/v1/permisos"
CLAVE = "claveSegura123"


@pytest.fixture()
def client(client_por_peticion):
    """E03: escribir roles es de la plataforma (`plataforma.gestionar`), y el
    token del superadministrador no entra en una sesión que ya trae empresa;
    por eso este módulo usa el cliente con una sesión nueva por petición."""
    return client_por_peticion


@pytest.fixture()
def super_headers(client, db_session):
    """Cabeceras del superadministrador (login sin empresa)."""
    crear_superadmin_de_prueba(db_session)
    respuesta = client.post(
        "/api/v1/auth/login", json={"email": "super@plataforma.example.com", "password": CLAVE}
    )
    assert respuesta.status_code == 200, respuesta.text
    return {"Authorization": f"Bearer {respuesta.json()['access_token']}"}


def _datos_usuario(email="nuevo@example.com", **extra) -> dict:
    return {"nombre": "Nu", "apellido": "Evo", "email": email, "password": CLAVE, **extra}


def _crear_usuario(client, admin_headers, email="nuevo@example.com", **extra) -> dict:
    respuesta = client.post(USUARIOS, json=_datos_usuario(email, **extra), headers=admin_headers)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _crear_rol(client, headers, nombre="auditor", descripcion="Solo lectura") -> dict:
    respuesta = client.post(
        ROLES, json={"nombre": nombre, "descripcion": descripcion}, headers=headers
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _login(client, email, password=CLAVE):
    return client.post("/api/v1/auth/login", json={"empresa": "fashionstore", "email": email, "password": password})


# ---- Usuarios: crear / obtener / listar -----------------------------------------------------


def test_crear_usuario_devuelve_201_sin_roles_y_sin_password(client, admin_headers):
    respuesta = client.post(USUARIOS, json=_datos_usuario(telefono="71234567"), headers=admin_headers)

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["email"] == "nuevo@example.com"
    assert cuerpo["telefono"] == "71234567"
    assert cuerpo["activo"] is True
    assert cuerpo["roles"] == []
    assert "password" not in cuerpo and "password_hash" not in cuerpo


def test_usuario_creado_puede_iniciar_sesion(client, admin_headers):
    _crear_usuario(client, admin_headers)

    assert _login(client, "nuevo@example.com").status_code == 200


def test_crear_usuario_con_email_duplicado_devuelve_409(client, admin_headers):
    _crear_usuario(client, admin_headers)

    duplicado = client.post(USUARIOS, json=_datos_usuario(), headers=admin_headers)

    assert duplicado.status_code == 409
    assert duplicado.json()["detail"] == "Ya existe un usuario con ese email"


def test_crear_usuario_con_datos_invalidos_devuelve_422(client, admin_headers):
    corta = client.post(USUARIOS, json={**_datos_usuario(), "password": "corta"}, headers=admin_headers)
    sin_correo = client.post(USUARIOS, json=_datos_usuario("no-es-correo"), headers=admin_headers)
    sin_nombre = client.post(
        USUARIOS, json={"apellido": "x", "email": "a@example.com", "password": CLAVE}, headers=admin_headers
    )

    assert corta.status_code == 422
    assert sin_correo.status_code == 422
    assert sin_nombre.status_code == 422


def test_obtener_usuario_existente(client, admin_headers):
    creado = _crear_usuario(client, admin_headers)

    respuesta = client.get(f"{USUARIOS}/{creado['id']}", headers=admin_headers)

    assert respuesta.status_code == 200
    assert respuesta.json() == creado


def test_obtener_usuario_inexistente_devuelve_404(client, admin_headers):
    assert client.get(f"{USUARIOS}/999999", headers=admin_headers).status_code == 404


def test_listar_usuarios_incluye_al_administrador_y_a_los_creados(client, admin_headers):
    creado = _crear_usuario(client, admin_headers)

    respuesta = client.get(USUARIOS, headers=admin_headers)

    assert respuesta.status_code == 200
    emails = [u["email"] for u in respuesta.json()]
    assert "admin@example.com" in emails
    assert creado["email"] in emails


def test_listar_usuarios_pagina_sin_solapar_ni_saltar(client, admin_headers):
    for i in range(5):
        _crear_usuario(client, admin_headers, email=f"pag{i}@example.com")
    todos = [u["id"] for u in client.get(f"{USUARIOS}?tamanio=100", headers=admin_headers).json()]

    paginas: list[int] = []
    for pagina in (1, 2, 3, 4):
        lote = client.get(f"{USUARIOS}?pagina={pagina}&tamanio=2", headers=admin_headers).json()
        assert len(lote) <= 2
        paginas.extend(u["id"] for u in lote)

    assert paginas == todos  # orden actual: por id ascendente en SQLite
    assert len(todos) >= 6


def test_listar_usuarios_valida_los_parametros_de_paginacion(client, admin_headers):
    assert client.get(f"{USUARIOS}?pagina=0", headers=admin_headers).status_code == 422
    assert client.get(f"{USUARIOS}?tamanio=101", headers=admin_headers).status_code == 422


def test_listar_usuarios_no_incluye_desactivados(client, admin_headers):
    creado = _crear_usuario(client, admin_headers)
    client.delete(f"{USUARIOS}/{creado['id']}", headers=admin_headers)

    ids = [u["id"] for u in client.get(USUARIOS, headers=admin_headers).json()]

    assert creado["id"] not in ids


# ---- Usuarios: búsqueda en el servidor -----------------------------------------------------


def _buscar(client, admin_headers, texto: str, **parametros) -> list[dict]:
    respuesta = client.get(USUARIOS, params={"buscar": texto, **parametros}, headers=admin_headers)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def test_buscar_usuarios_por_nombre_apellido_o_correo_sin_distinguir_mayusculas(client, admin_headers):
    ana = _crear_usuario(client, admin_headers, email="ana.gomez@example.com", nombre="Ana", apellido="Gomez")
    _crear_usuario(client, admin_headers, email="otro@example.com", nombre="Otro", apellido="Zapata")

    assert [u["id"] for u in _buscar(client, admin_headers, "ana")] == [ana["id"]]
    assert [u["id"] for u in _buscar(client, admin_headers, "GOMEZ")] == [ana["id"]]
    assert [u["id"] for u in _buscar(client, admin_headers, "ana.gomez@")] == [ana["id"]]


def test_buscar_usuarios_con_nombre_y_apellido_a_la_vez(client, admin_headers):
    ana = _crear_usuario(client, admin_headers, email="ana1@example.com", nombre="Ana", apellido="Gomez")
    _crear_usuario(client, admin_headers, email="ana2@example.com", nombre="Ana", apellido="Rojas")

    assert [u["id"] for u in _buscar(client, admin_headers, "Ana Gomez")] == [ana["id"]]
    assert [u["id"] for u in _buscar(client, admin_headers, "gomez   ana")] == [ana["id"]]  # orden y espacios no importan


def test_buscar_usuarios_encuentra_a_quien_esta_fuera_de_la_primera_pagina(client, admin_headers):
    for i in range(6):
        _crear_usuario(client, admin_headers, email=f"relleno{i}@example.com")
    lejano = _crear_usuario(client, admin_headers, email="lejano@example.com", nombre="Zacarias", apellido="Lejano")
    primera_pagina = [u["id"] for u in client.get(f"{USUARIOS}?pagina=1&tamanio=3", headers=admin_headers).json()]
    assert lejano["id"] not in primera_pagina  # sin buscar, no sale en la primera página

    encontrados = _buscar(client, admin_headers, "zacarias", pagina=1, tamanio=3)

    assert [u["id"] for u in encontrados] == [lejano["id"]]


def test_buscar_usuarios_sin_coincidencias_devuelve_lista_vacia(client, admin_headers):
    _crear_usuario(client, admin_headers)

    assert _buscar(client, admin_headers, "nadie-se-llama-asi") == []


def test_buscar_usuarios_vacio_o_solo_espacios_devuelve_todos(client, admin_headers):
    _crear_usuario(client, admin_headers)
    todos = [u["id"] for u in client.get(USUARIOS, headers=admin_headers).json()]

    assert [u["id"] for u in _buscar(client, admin_headers, "")] == todos
    assert [u["id"] for u in _buscar(client, admin_headers, "   ")] == todos


def test_buscar_usuarios_trata_porcentaje_y_guion_bajo_como_letras(client, admin_headers):
    _crear_usuario(client, admin_headers, email="normal@example.com", nombre="Normal", apellido="Persona")

    assert _buscar(client, admin_headers, "%") == []  # no es un comodín que traiga a todos
    assert _buscar(client, admin_headers, "_") == []
    assert _buscar(client, admin_headers, "Nor_al") == []  # `_` no reemplaza a una letra


def test_buscar_usuarios_no_trae_a_los_desactivados(client, admin_headers):
    creado = _crear_usuario(client, admin_headers, email="baja@example.com", nombre="Baja", apellido="Pronto")
    client.delete(f"{USUARIOS}/{creado['id']}", headers=admin_headers)

    assert _buscar(client, admin_headers, "baja") == []


def test_buscar_usuarios_rechaza_un_texto_demasiado_largo(client, admin_headers):
    assert client.get(USUARIOS, params={"buscar": "a" * 101}, headers=admin_headers).status_code == 422


# ---- Usuarios: actualizar -------------------------------------------------------------------


def test_actualizar_usuario_cambia_solo_los_campos_enviados(client, admin_headers):
    creado = _crear_usuario(client, admin_headers, telefono="70000000")

    respuesta = client.put(f"{USUARIOS}/{creado['id']}", json={"nombre": "Renombrado"}, headers=admin_headers)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["nombre"] == "Renombrado"
    assert cuerpo["apellido"] == "Evo"
    assert cuerpo["telefono"] == "70000000"
    assert cuerpo["email"] == "nuevo@example.com"


def test_actualizar_telefono_a_null_lo_borra(client, admin_headers):
    # telefono es nullable: enviar null es válido y lo anula.
    creado = _crear_usuario(client, admin_headers, telefono="70000000")

    respuesta = client.put(f"{USUARIOS}/{creado['id']}", json={"telefono": None}, headers=admin_headers)

    assert respuesta.status_code == 200
    assert respuesta.json()["telefono"] is None


def test_actualizar_con_nombre_null_devuelve_409(client, admin_headers):
    # CRUDBase.actualizar escribe None en una columna NOT NULL; la base lanza
    # IntegrityError y core/crud_base.py lo convierte en ConflictoError.
    creado = _crear_usuario(client, admin_headers)

    respuesta = client.put(f"{USUARIOS}/{creado['id']}", json={"nombre": None}, headers=admin_headers)

    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "detail": "No se pudo guardar Usuario: choca con un registro existente o tiene datos inválidos"
    }
    # la fila no quedó dañada
    assert client.get(f"{USUARIOS}/{creado['id']}", headers=admin_headers).json()["nombre"] == "Nu"


def test_actualizar_con_activo_null_devuelve_409(client, admin_headers):
    # activo es NOT NULL: igual que nombre null, termina en ConflictoError.
    creado = _crear_usuario(client, admin_headers)

    respuesta = client.put(f"{USUARIOS}/{creado['id']}", json={"activo": None}, headers=admin_headers)

    assert respuesta.status_code == 409


def test_actualizar_con_nombre_demasiado_largo_devuelve_422(client, admin_headers):
    creado = _crear_usuario(client, admin_headers)

    respuesta = client.put(f"{USUARIOS}/{creado['id']}", json={"nombre": "x" * 61}, headers=admin_headers)

    assert respuesta.status_code == 422


def test_actualizar_ignora_en_silencio_email_y_password(client, admin_headers):
    # UsuarioActualizar no declara email ni password: pydantic descarta los
    # campos extra sin error y nada de eso cambia.
    creado = _crear_usuario(client, admin_headers)

    respuesta = client.put(
        f"{USUARIOS}/{creado['id']}",
        json={"nombre": "Otro", "email": "otro@example.com", "password": "otraClave999"},
        headers=admin_headers,
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["email"] == "nuevo@example.com"
    assert _login(client, "nuevo@example.com").status_code == 200
    assert _login(client, "nuevo@example.com", "otraClave999").status_code == 401


def test_actualizar_usuario_inexistente_devuelve_404(client, admin_headers):
    respuesta = client.put(f"{USUARIOS}/999999", json={"nombre": "x"}, headers=admin_headers)

    assert respuesta.status_code == 404


def test_actualizar_activo_false_desactiva_y_activo_true_reactiva(client, admin_headers):
    creado = _crear_usuario(client, admin_headers)

    baja = client.put(f"{USUARIOS}/{creado['id']}", json={"activo": False}, headers=admin_headers)
    assert baja.status_code == 200
    assert baja.json()["activo"] is False
    assert _login(client, "nuevo@example.com").status_code == 401

    alta = client.put(f"{USUARIOS}/{creado['id']}", json={"activo": True}, headers=admin_headers)
    assert alta.status_code == 200
    assert alta.json()["activo"] is True
    assert _login(client, "nuevo@example.com").status_code == 200


def test_actualizar_un_usuario_desactivado_funciona_aunque_obtener_lo_oculte(client, admin_headers):
    # comportamiento actual: CRUDBase.actualizar usa db.get (no filtra activo)
    # mientras que GET /usuarios/{id} sí lo oculta (404).
    creado = _crear_usuario(client, admin_headers)
    client.delete(f"{USUARIOS}/{creado['id']}", headers=admin_headers)
    assert client.get(f"{USUARIOS}/{creado['id']}", headers=admin_headers).status_code == 404

    respuesta = client.put(f"{USUARIOS}/{creado['id']}", json={"nombre": "Editado"}, headers=admin_headers)

    assert respuesta.status_code == 200
    assert respuesta.json()["nombre"] == "Editado"
    assert respuesta.json()["activo"] is False


# ---- Usuarios: desactivar y roles -----------------------------------------------------------


def test_desactivar_usuario_es_borrado_logico(client, admin_headers, db_session):
    creado = _crear_usuario(client, admin_headers)

    respuesta = client.delete(f"{USUARIOS}/{creado['id']}", headers=admin_headers)

    assert respuesta.status_code == 204
    assert respuesta.content == b""
    fila = db_session.get(Usuario, creado["id"])
    assert fila is not None and fila.activo is False
    assert _login(client, "nuevo@example.com").status_code == 401


def test_desactivar_usuario_con_sesion_abierta_invalida_su_token(client, admin_headers):
    creado = _crear_usuario(client, admin_headers)
    token = _login(client, "nuevo@example.com").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/auth/yo", headers=headers).status_code == 200

    client.delete(f"{USUARIOS}/{creado['id']}", headers=admin_headers)

    assert client.get("/api/v1/auth/yo", headers=headers).status_code == 401


def test_desactivar_usuario_inexistente_o_ya_desactivado_devuelve_404(client, admin_headers):
    creado = _crear_usuario(client, admin_headers)
    client.delete(f"{USUARIOS}/{creado['id']}", headers=admin_headers)

    assert client.delete(f"{USUARIOS}/{creado['id']}", headers=admin_headers).status_code == 404
    assert client.delete(f"{USUARIOS}/999999", headers=admin_headers).status_code == 404


def test_un_administrador_puede_desactivarse_a_si_mismo_si_queda_otro(client, admin_headers, db_session):
    # No hay protección contra la auto-baja, salvo la de E04 (D36): la empresa
    # no puede quedarse sin administrador activo.
    yo = client.get("/api/v1/auth/yo", headers=admin_headers).json()
    assert client.delete(f"{USUARIOS}/{yo['id']}", headers=admin_headers).status_code == 409
    otro = _crear_usuario(client, admin_headers, email="segundo-admin@example.com")
    client.put(f"{USUARIOS}/{otro['id']}/roles", json={"nombres_rol": ["administrador"]}, headers=admin_headers)

    respuesta = client.delete(f"{USUARIOS}/{yo['id']}", headers=admin_headers)

    assert respuesta.status_code == 204
    assert client.get("/api/v1/auth/yo", headers=admin_headers).status_code == 401


def test_asignar_roles_a_usuario(client, admin_headers):
    creado = _crear_usuario(client, admin_headers)

    respuesta = client.put(
        f"{USUARIOS}/{creado['id']}/roles", json={"nombres_rol": ["cajero", "cliente"]}, headers=admin_headers
    )

    assert respuesta.status_code == 200
    assert sorted(respuesta.json()["roles"]) == ["cajero", "cliente"]


def test_asignar_roles_reemplaza_y_vacio_quita_todos(client, admin_headers):
    creado = _crear_usuario(client, admin_headers)
    client.put(f"{USUARIOS}/{creado['id']}/roles", json={"nombres_rol": ["cajero"]}, headers=admin_headers)

    cambiado = client.put(
        f"{USUARIOS}/{creado['id']}/roles", json={"nombres_rol": ["cliente"]}, headers=admin_headers
    )
    vacio = client.put(f"{USUARIOS}/{creado['id']}/roles", json={"nombres_rol": []}, headers=admin_headers)

    assert cambiado.json()["roles"] == ["cliente"]
    assert vacio.status_code == 200
    assert vacio.json()["roles"] == []


def test_asignar_roles_con_nombre_inexistente_devuelve_400_y_no_cambia_nada(client, admin_headers):
    creado = _crear_usuario(client, admin_headers)
    client.put(f"{USUARIOS}/{creado['id']}/roles", json={"nombres_rol": ["cajero"]}, headers=admin_headers)

    respuesta = client.put(
        f"{USUARIOS}/{creado['id']}/roles", json={"nombres_rol": ["cajero", "no_existe"]}, headers=admin_headers
    )

    assert respuesta.status_code == 400
    assert respuesta.json()["detail"] == "Uno o más roles no existen o están inactivos"
    assert client.get(f"{USUARIOS}/{creado['id']}", headers=admin_headers).json()["roles"] == ["cajero"]


def test_asignar_roles_a_usuario_inexistente_devuelve_404(client, admin_headers):
    respuesta = client.put(f"{USUARIOS}/999999/roles", json={"nombres_rol": ["cajero"]}, headers=admin_headers)

    assert respuesta.status_code == 404


def test_asignar_un_rol_desactivado_devuelve_400(client, admin_headers, super_headers):
    rol = _crear_rol(client, super_headers, "temporal")
    client.delete(f"{ROLES}/{rol['id']}", headers=super_headers)
    creado = _crear_usuario(client, admin_headers)

    respuesta = client.put(
        f"{USUARIOS}/{creado['id']}/roles", json={"nombres_rol": ["temporal"]}, headers=admin_headers
    )

    assert respuesta.status_code == 400


def test_roles_asignados_dan_permisos_reales_en_yo(client, admin_headers):
    creado = _crear_usuario(client, admin_headers)
    client.put(f"{USUARIOS}/{creado['id']}/roles", json={"nombres_rol": ["cajero"]}, headers=admin_headers)
    token = _login(client, "nuevo@example.com").json()["access_token"]

    cuerpo = client.get("/api/v1/auth/yo", headers={"Authorization": f"Bearer {token}"}).json()

    assert cuerpo["roles"] == ["cajero"]
    assert "ventas.presencial" in cuerpo["permisos"]
    assert "roles.gestionar" not in cuerpo["permisos"]


# ---- Roles ----------------------------------------------------------------------------------


def test_listar_roles_trae_los_del_seed_con_sus_permisos(client, admin_headers):
    respuesta = client.get(ROLES, headers=admin_headers)

    assert respuesta.status_code == 200
    por_nombre = {r["nombre"]: r for r in respuesta.json()}
    assert {"administrador", "encargado_sucursal", "cajero", "proveedor", "cliente"} <= set(por_nombre)
    assert "ventas.presencial" in [p["codigo"] for p in por_nombre["cajero"]["permisos"]]
    assert all(r["activo"] for r in por_nombre.values())


def test_crear_rol_devuelve_201_activo_y_sin_permisos(client, admin_headers, super_headers):
    respuesta = client.post(
        ROLES, json={"nombre": "auditor", "descripcion": "Solo lectura"}, headers=super_headers
    )

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["nombre"] == "auditor"
    assert cuerpo["descripcion"] == "Solo lectura"
    assert cuerpo["activo"] is True
    assert cuerpo["permisos"] == []


def test_crear_rol_con_nombre_duplicado_devuelve_409(client, admin_headers, super_headers):
    # RolRepository no sobrescribe crear() y rol.nombre es UNIQUE: el
    # IntegrityError de CRUDBase.crear se convierte en ConflictoError.
    _crear_rol(client, super_headers, "auditor")

    respuesta = client.post(ROLES, json={"nombre": "auditor"}, headers=super_headers)

    assert respuesta.status_code == 409


def test_crear_rol_con_nombre_largo_o_ausente_devuelve_422(client, admin_headers, super_headers):
    assert client.post(ROLES, json={"nombre": "x" * 41}, headers=super_headers).status_code == 422
    assert client.post(ROLES, json={"descripcion": "sin nombre"}, headers=super_headers).status_code == 422


def test_obtener_rol_existente_e_inexistente(client, admin_headers, super_headers):
    rol = _crear_rol(client, super_headers)

    assert client.get(f"{ROLES}/{rol['id']}", headers=admin_headers).json() == rol
    assert client.get(f"{ROLES}/999999", headers=admin_headers).status_code == 404


def test_actualizar_rol_parcial_conserva_lo_no_enviado(client, admin_headers, super_headers):
    rol = _crear_rol(client, super_headers, "auditor", "Solo lectura")

    respuesta = client.put(f"{ROLES}/{rol['id']}", json={"descripcion": "Nueva descripcion"}, headers=super_headers)

    assert respuesta.status_code == 200
    assert respuesta.json()["nombre"] == "auditor"
    assert respuesta.json()["descripcion"] == "Nueva descripcion"


def test_actualizar_rol_inexistente_devuelve_404(client, admin_headers, super_headers):
    assert client.put(f"{ROLES}/999999", json={"nombre": "x"}, headers=super_headers).status_code == 404


def test_actualizar_rol_a_nombre_duplicado_devuelve_409(client, admin_headers, super_headers):
    _crear_rol(client, super_headers, "auditor")
    otro = _crear_rol(client, super_headers, "supervisor")

    respuesta = client.put(f"{ROLES}/{otro['id']}", json={"nombre": "auditor"}, headers=super_headers)

    assert respuesta.status_code == 409
    assert client.get(f"{ROLES}/{otro['id']}", headers=admin_headers).json()["nombre"] == "supervisor"


def test_actualizar_rol_con_nombre_null_devuelve_409(client, admin_headers, super_headers):
    rol = _crear_rol(client, super_headers)

    respuesta = client.put(f"{ROLES}/{rol['id']}", json={"nombre": None}, headers=super_headers)

    assert respuesta.status_code == 409
    assert client.get(f"{ROLES}/{rol['id']}", headers=admin_headers).json()["nombre"] == rol["nombre"]


def test_actualizar_rol_no_permite_reactivarlo_por_la_api(client, admin_headers, super_headers, db_session):
    # RolActualizar no declara `activo` (2.1 punto 15): el campo se ignora y el
    # rol desactivado sigue inactivo.
    rol = _crear_rol(client, super_headers)
    client.delete(f"{ROLES}/{rol['id']}", headers=super_headers)

    respuesta = client.put(f"{ROLES}/{rol['id']}", json={"activo": True}, headers=super_headers)

    assert respuesta.status_code == 200
    assert respuesta.json()["activo"] is False
    assert db_session.get(Rol, rol["id"]).activo is False


def test_desactivar_rol_es_borrado_logico(client, admin_headers, super_headers, db_session):
    rol = _crear_rol(client, super_headers)

    respuesta = client.delete(f"{ROLES}/{rol['id']}", headers=super_headers)

    assert respuesta.status_code == 204
    assert db_session.get(Rol, rol["id"]).activo is False
    assert client.get(f"{ROLES}/{rol['id']}", headers=admin_headers).status_code == 404
    assert rol["id"] not in [r["id"] for r in client.get(ROLES, headers=admin_headers).json()]


def test_desactivar_rol_inexistente_o_ya_desactivado_devuelve_404(client, admin_headers, super_headers):
    rol = _crear_rol(client, super_headers)
    client.delete(f"{ROLES}/{rol['id']}", headers=super_headers)

    assert client.delete(f"{ROLES}/{rol['id']}", headers=super_headers).status_code == 404
    assert client.delete(f"{ROLES}/999999", headers=super_headers).status_code == 404


def test_desactivar_un_rol_quita_los_permisos_a_sus_usuarios(client, admin_headers, super_headers):
    rol = _crear_rol(client, super_headers, "auditor")
    client.put(f"{ROLES}/{rol['id']}/permisos", json={"codigos_permiso": ["reportes.ver"]}, headers=super_headers)
    usuario = _crear_usuario(client, admin_headers)
    client.put(f"{USUARIOS}/{usuario['id']}/roles", json={"nombres_rol": ["auditor"]}, headers=admin_headers)
    token = _login(client, "nuevo@example.com").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert "reportes.ver" in client.get("/api/v1/auth/yo", headers=headers).json()["permisos"]

    client.delete(f"{ROLES}/{rol['id']}", headers=super_headers)

    assert client.get("/api/v1/auth/yo", headers=headers).json()["permisos"] == []


def test_listar_roles_pagina_sin_solapar_ni_saltar(client, admin_headers, super_headers):
    for i in range(4):
        _crear_rol(client, super_headers, f"rol{i}")
    todos = [r["id"] for r in client.get(f"{ROLES}?tamanio=100", headers=admin_headers).json()]

    recorrido: list[int] = []
    for pagina in range(1, 8):
        recorrido.extend(r["id"] for r in client.get(f"{ROLES}?pagina={pagina}&tamanio=2", headers=admin_headers).json())

    assert recorrido == todos
    assert len(todos) >= 9


# ---- Roles: asignar permisos y catálogo de permisos -----------------------------------------


def test_asignar_permisos_a_rol(client, admin_headers, super_headers):
    rol = _crear_rol(client, super_headers)

    respuesta = client.put(
        f"{ROLES}/{rol['id']}/permisos",
        json={"codigos_permiso": ["reportes.ver", "catalogo.ver"]},
        headers=super_headers,
    )

    assert respuesta.status_code == 200
    assert sorted(p["codigo"] for p in respuesta.json()["permisos"]) == ["catalogo.ver", "reportes.ver"]
    assert client.get(f"{ROLES}/{rol['id']}", headers=admin_headers).json() == respuesta.json()


def test_asignar_permisos_reemplaza_el_conjunto_y_acepta_duplicados_y_vacio(client, admin_headers, super_headers):
    rol = _crear_rol(client, super_headers)
    client.put(f"{ROLES}/{rol['id']}/permisos", json={"codigos_permiso": ["reportes.ver"]}, headers=super_headers)

    reemplazo = client.put(
        f"{ROLES}/{rol['id']}/permisos",
        json={"codigos_permiso": ["catalogo.ver", "catalogo.ver"]},
        headers=super_headers,
    )
    vacio = client.put(f"{ROLES}/{rol['id']}/permisos", json={"codigos_permiso": []}, headers=super_headers)

    assert [p["codigo"] for p in reemplazo.json()["permisos"]] == ["catalogo.ver"]
    assert vacio.status_code == 200
    assert vacio.json()["permisos"] == []


def test_asignar_permisos_con_codigo_inexistente_devuelve_400_y_no_cambia_nada(client, admin_headers, super_headers):
    rol = _crear_rol(client, super_headers)
    client.put(f"{ROLES}/{rol['id']}/permisos", json={"codigos_permiso": ["reportes.ver"]}, headers=super_headers)

    respuesta = client.put(
        f"{ROLES}/{rol['id']}/permisos",
        json={"codigos_permiso": ["reportes.ver", "no.existe"]},
        headers=super_headers,
    )

    assert respuesta.status_code == 400
    assert respuesta.json()["detail"] == "Uno o más códigos de permiso no existen"
    assert [p["codigo"] for p in client.get(f"{ROLES}/{rol['id']}", headers=admin_headers).json()["permisos"]] == [
        "reportes.ver"
    ]


def test_asignar_permisos_a_rol_inexistente_devuelve_404(client, admin_headers, super_headers):
    respuesta = client.put(f"{ROLES}/999999/permisos", json={"codigos_permiso": []}, headers=super_headers)

    assert respuesta.status_code == 404


def test_los_permisos_del_rol_se_reflejan_de_inmediato_en_sus_usuarios(client, admin_headers, super_headers):
    rol = _crear_rol(client, super_headers, "auditor")
    usuario = _crear_usuario(client, admin_headers)
    client.put(f"{USUARIOS}/{usuario['id']}/roles", json={"nombres_rol": ["auditor"]}, headers=admin_headers)
    token = _login(client, "nuevo@example.com").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get(PERMISOS, headers=headers).status_code == 403

    client.put(f"{ROLES}/{rol['id']}/permisos", json={"codigos_permiso": ["roles.gestionar"]}, headers=super_headers)

    assert "roles.gestionar" in client.get("/api/v1/auth/yo", headers=headers).json()["permisos"]
    assert client.get(PERMISOS, headers=headers).status_code == 200


def test_listar_permisos_devuelve_el_catalogo_ordenado_por_modulo_y_codigo(client, admin_headers):
    respuesta = client.get(PERMISOS, headers=admin_headers)

    assert respuesta.status_code == 200
    permisos = respuesta.json()
    codigos = [p["codigo"] for p in permisos]
    assert {"usuarios.gestionar", "roles.gestionar", "reportes.ver"} <= set(codigos)
    assert len(set(codigos)) == len(codigos)
    assert [(p["modulo"], p["codigo"]) for p in permisos] == sorted((p["modulo"], p["codigo"]) for p in permisos)
    assert set(permisos[0]) == {"id", "codigo", "modulo", "descripcion"}


# ---- Autorización: sin permiso -> 403, sin token -> 401 ---------------------------------------

RUTAS_PROTEGIDAS = [
    ("get", USUARIOS, None),
    ("get", f"{USUARIOS}/1", None),
    ("post", USUARIOS, _datos_usuario("x@example.com")),
    ("put", f"{USUARIOS}/1", {"nombre": "x"}),
    ("delete", f"{USUARIOS}/1", None),
    ("put", f"{USUARIOS}/1/roles", {"nombres_rol": []}),
    ("get", ROLES, None),
    ("get", f"{ROLES}/1", None),
    ("post", ROLES, {"nombre": "x"}),
    ("put", f"{ROLES}/1", {"nombre": "x"}),
    ("delete", f"{ROLES}/1", None),
    ("put", f"{ROLES}/1/permisos", {"codigos_permiso": []}),
    ("get", PERMISOS, None),
]


@pytest.mark.parametrize("metodo,ruta,cuerpo", RUTAS_PROTEGIDAS)
def test_cliente_sin_permiso_recibe_403(client, cliente_headers, metodo, ruta, cuerpo):
    respuesta = getattr(client, metodo)(ruta, headers=cliente_headers, **({"json": cuerpo} if cuerpo else {}))

    assert respuesta.status_code == 403
    assert respuesta.json()["detail"] in (
        "Falta el permiso 'usuarios.gestionar'",
        "Falta el permiso 'roles.gestionar'",
        "Falta el permiso 'plataforma.gestionar'",  # E03: escribir roles es de la plataforma
    )


@pytest.mark.parametrize("metodo,ruta,cuerpo", RUTAS_PROTEGIDAS)
def test_sin_token_recibe_401(client, metodo, ruta, cuerpo):
    respuesta = getattr(client, metodo)(ruta, **({"json": cuerpo} if cuerpo else {}))

    assert respuesta.status_code == 401


def test_usuarios_gestionar_no_da_acceso_a_roles_y_viceversa(client, admin_headers, super_headers):
    rol_solo_usuarios = _crear_rol(client, super_headers, "solo_usuarios")
    client.put(
        f"{ROLES}/{rol_solo_usuarios['id']}/permisos",
        json={"codigos_permiso": ["usuarios.gestionar"]},
        headers=super_headers,
    )
    usuario = _crear_usuario(client, admin_headers)
    client.put(f"{USUARIOS}/{usuario['id']}/roles", json={"nombres_rol": ["solo_usuarios"]}, headers=admin_headers)
    token = _login(client, "nuevo@example.com").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get(USUARIOS, headers=headers).status_code == 200
    assert client.get(ROLES, headers=headers).status_code == 403
    assert client.get(PERMISOS, headers=headers).status_code == 403
