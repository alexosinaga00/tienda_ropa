def crear_ciudad(client, headers, nombre="Santa Cruz", departamento="Santa Cruz"):
    return client.post(
        "/api/v1/ciudades", json={"nombre": nombre, "departamento": departamento}, headers=headers
    )


def crear_sucursal(client, headers, ciudad_id, codigo="SUC-001"):
    return client.post(
        "/api/v1/sucursales",
        json={
            "ciudad_id": ciudad_id,
            "codigo": codigo,
            "nombre": "Sucursal Centro",
            "direccion": "Av. Siempre Viva 123",
        },
        headers=headers,
    )


# ---- Permisos ---------------------------------------------------------------


def test_ciudades_requiere_admin(client, cliente_headers):
    respuesta = client.get("/api/v1/ciudades", headers=cliente_headers)
    assert respuesta.status_code == 403


def test_ciudades_sin_token_rechazado(client):
    assert client.get("/api/v1/ciudades").status_code == 401


def test_sucursales_get_es_publico(client):
    respuesta = client.get("/api/v1/sucursales")
    assert respuesta.status_code == 200


def test_sucursales_post_requiere_admin(client, cliente_headers):
    respuesta = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": 1, "codigo": "X", "nombre": "X", "direccion": "X"},
        headers=cliente_headers,
    )
    assert respuesta.status_code == 403


# ---- Ciudades / sucursales ---------------------------------------------------


def test_crear_sucursal_y_listar_publico_no_expone_empleados(client, admin_headers):
    ciudad = crear_ciudad(client, admin_headers).json()
    respuesta = crear_sucursal(client, admin_headers, ciudad["id"])
    assert respuesta.status_code == 201

    publico = client.get("/api/v1/sucursales")
    assert publico.status_code == 200
    cuerpo = publico.json()[0]
    assert set(cuerpo.keys()) == {
        "id",
        "ciudad_id",
        "codigo",
        "nombre",
        "direccion",
        "telefono",
        "latitud",
        "longitud",
        "es_deposito",
        "activo",
        "creado_en",
    }


def test_sucursal_dada_de_baja_se_reactiva_por_put(client, admin_headers):
    """Cubre el fix de CRUDBase.actualizar: antes, PUT con {"activo": true}
    sobre una fila inactiva daba 404 porque actualizar() usaba obtener()
    (que filtra activo=True) para ubicar la fila a editar."""
    ciudad = crear_ciudad(client, admin_headers).json()
    sucursal = crear_sucursal(client, admin_headers, ciudad["id"]).json()

    baja = client.delete(f"/api/v1/sucursales/{sucursal['id']}", headers=admin_headers)
    assert baja.status_code == 204

    reactivada = client.put(
        f"/api/v1/sucursales/{sucursal['id']}", json={"activo": True}, headers=admin_headers
    )
    assert reactivada.status_code == 200
    assert reactivada.json()["activo"] is True


def test_crear_sucursal_con_ciudad_inexistente_falla(client, admin_headers):
    respuesta = crear_sucursal(client, admin_headers, ciudad_id=9999)
    assert respuesta.status_code == 404


def test_crear_sucursal_codigo_duplicado_falla(client, admin_headers):
    ciudad = crear_ciudad(client, admin_headers).json()
    crear_sucursal(client, admin_headers, ciudad["id"], codigo="DUP")
    respuesta = crear_sucursal(client, admin_headers, ciudad["id"], codigo="DUP")
    assert respuesta.status_code == 409


# ---- Horarios -----------------------------------------------------------------


def test_horario_dia_duplicado_es_rechazado(client, admin_headers):
    ciudad = crear_ciudad(client, admin_headers).json()
    sucursal = crear_sucursal(client, admin_headers, ciudad["id"]).json()

    primero = client.post(
        f"/api/v1/sucursales/{sucursal['id']}/horarios",
        json={"dia_semana": 1, "hora_apertura": "08:00:00", "hora_cierre": "18:00:00"},
        headers=admin_headers,
    )
    assert primero.status_code == 201

    duplicado = client.post(
        f"/api/v1/sucursales/{sucursal['id']}/horarios",
        json={"dia_semana": 1, "hora_apertura": "09:00:00", "hora_cierre": "20:00:00"},
        headers=admin_headers,
    )
    assert duplicado.status_code == 409


def test_horario_cierre_antes_de_apertura_es_rechazado(client, admin_headers):
    ciudad = crear_ciudad(client, admin_headers).json()
    sucursal = crear_sucursal(client, admin_headers, ciudad["id"]).json()

    respuesta = client.post(
        f"/api/v1/sucursales/{sucursal['id']}/horarios",
        json={"dia_semana": 2, "hora_apertura": "18:00:00", "hora_cierre": "08:00:00"},
        headers=admin_headers,
    )
    assert respuesta.status_code == 422


def test_horarios_distintos_dias_se_pueden_crear(client, admin_headers):
    ciudad = crear_ciudad(client, admin_headers).json()
    sucursal = crear_sucursal(client, admin_headers, ciudad["id"]).json()

    for dia in (1, 2, 3):
        respuesta = client.post(
            f"/api/v1/sucursales/{sucursal['id']}/horarios",
            json={"dia_semana": dia, "hora_apertura": "08:00:00", "hora_cierre": "18:00:00"},
            headers=admin_headers,
        )
        assert respuesta.status_code == 201

    listado = client.get(f"/api/v1/sucursales/{sucursal['id']}/horarios", headers=admin_headers)
    assert len(listado.json()) == 3


def test_horarios_get_es_publico(client, admin_headers):
    # El cliente (Flutter) necesita el horario de la sucursal para elegir
    # franja al reservar, sin ser administrador.
    ciudad = crear_ciudad(client, admin_headers).json()
    sucursal = crear_sucursal(client, admin_headers, ciudad["id"]).json()
    client.post(
        f"/api/v1/sucursales/{sucursal['id']}/horarios",
        json={"dia_semana": 1, "hora_apertura": "08:00:00", "hora_cierre": "18:00:00"},
        headers=admin_headers,
    )

    respuesta = client.get(f"/api/v1/sucursales/{sucursal['id']}/horarios")
    assert respuesta.status_code == 200
    assert len(respuesta.json()) == 1


def test_horarios_post_sigue_requiriendo_admin(client, cliente_headers, admin_headers):
    ciudad = crear_ciudad(client, admin_headers).json()
    sucursal = crear_sucursal(client, admin_headers, ciudad["id"]).json()
    respuesta = client.post(
        f"/api/v1/sucursales/{sucursal['id']}/horarios",
        json={"dia_semana": 1, "hora_apertura": "08:00:00", "hora_cierre": "18:00:00"},
        headers=cliente_headers,
    )
    assert respuesta.status_code == 403


# ---- Empleados ----------------------------------------------------------------


def test_empleado_pertenece_a_una_sola_sucursal(client, admin_headers, db_session):
    from app.seguridad.repository import UsuarioRepository
    from app.seguridad.schemas import UsuarioCrear

    usuario_repo = UsuarioRepository()
    usuario = usuario_repo.crear(
        db_session,
        UsuarioCrear(nombre="Emp", apellido="Leado", email="empleado@example.com", password="claveSegura123"),
    )

    ciudad = crear_ciudad(client, admin_headers).json()
    sucursal_1 = crear_sucursal(client, admin_headers, ciudad["id"], codigo="S1").json()
    sucursal_2 = crear_sucursal(client, admin_headers, ciudad["id"], codigo="S2").json()

    creado = client.post(
        "/api/v1/empleados",
        json={"usuario_id": usuario.id, "sucursal_id": sucursal_1["id"], "cargo": "Cajero"},
        headers=admin_headers,
    )
    assert creado.status_code == 201
    assert creado.json()["sucursal_id"] == sucursal_1["id"]

    duplicado = client.post(
        "/api/v1/empleados",
        json={"usuario_id": usuario.id, "sucursal_id": sucursal_2["id"], "cargo": "Cajero"},
        headers=admin_headers,
    )
    assert duplicado.status_code == 409

    actualizado = client.put(
        f"/api/v1/empleados/{creado.json()['id']}",
        json={"sucursal_id": sucursal_2["id"]},
        headers=admin_headers,
    )
    assert actualizado.status_code == 200
    assert actualizado.json()["sucursal_id"] == sucursal_2["id"]


def test_empleado_con_usuario_inexistente_falla(client, admin_headers):
    respuesta = client.post(
        "/api/v1/empleados", json={"usuario_id": 9999, "cargo": "Cajero"}, headers=admin_headers
    )
    assert respuesta.status_code == 404


def test_empleado_dado_de_baja_se_puede_volver_a_registrar(client, admin_headers, db_session):
    from app.seguridad.repository import UsuarioRepository
    from app.seguridad.schemas import UsuarioCrear

    usuario_repo = UsuarioRepository()
    usuario = usuario_repo.crear(
        db_session,
        UsuarioCrear(nombre="Ex", apellido="Empleado", email="ex.empleado@example.com", password="claveSegura123"),
    )

    ciudad = crear_ciudad(client, admin_headers).json()
    sucursal = crear_sucursal(client, admin_headers, ciudad["id"], codigo="S3").json()

    creado = client.post(
        "/api/v1/empleados",
        json={"usuario_id": usuario.id, "sucursal_id": sucursal["id"], "cargo": "Cajero"},
        headers=admin_headers,
    )
    assert creado.status_code == 201
    empleado_id = creado.json()["id"]

    baja = client.delete(f"/api/v1/empleados/{empleado_id}", headers=admin_headers)
    assert baja.status_code == 204

    reingreso = client.post(
        "/api/v1/empleados",
        json={"usuario_id": usuario.id, "sucursal_id": sucursal["id"], "cargo": "Encargado"},
        headers=admin_headers,
    )
    assert reingreso.status_code == 201
    assert reingreso.json()["id"] == empleado_id
    assert reingreso.json()["activo"] is True
    assert reingreso.json()["cargo"] == "Encargado"


def test_empleados_yo_devuelve_mi_propio_registro(client, admin_headers, db_session):
    from tests.conftest import crear_cajero

    ciudad = crear_ciudad(client, admin_headers).json()
    sucursal = crear_sucursal(client, admin_headers, ciudad["id"], codigo="S-YO").json()
    cajero_headers = crear_cajero(client, admin_headers, db_session, sucursal_id=sucursal["id"])

    respuesta = client.get("/api/v1/empleados/yo", headers=cajero_headers)
    assert respuesta.status_code == 200
    assert respuesta.json()["sucursal_id"] == sucursal["id"]


def test_empleados_yo_sin_ser_empleado_da_404(client, cliente_headers):
    respuesta = client.get("/api/v1/empleados/yo", headers=cliente_headers)
    assert respuesta.status_code == 404


def test_empleados_yo_no_requiere_permiso_admin(client, admin_headers, db_session):
    """A diferencia del resto de /empleados, /yo no exige
    organizacion.gestionar: lo llama cualquier empleado logueado (la caja
    en Angular necesita saber su propia sucursal)."""
    from tests.conftest import crear_cajero

    ciudad = crear_ciudad(client, admin_headers).json()
    sucursal = crear_sucursal(client, admin_headers, ciudad["id"], codigo="S-YO2").json()
    cajero_headers = crear_cajero(
        client, admin_headers, db_session, sucursal_id=sucursal["id"], email="cajero-yo@example.com"
    )

    sin_permiso_admin = client.get("/api/v1/empleados", headers=cajero_headers)
    assert sin_permiso_admin.status_code == 403

    con_yo = client.get("/api/v1/empleados/yo", headers=cajero_headers)
    assert con_yo.status_code == 200
