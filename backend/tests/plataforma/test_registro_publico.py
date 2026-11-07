"""E03, PASO 5: el registro de clientes por tienda, POST /api/v1/public/{codigo}/registro.

La empresa sale SOLO del código de la ruta; el correo es único por empresa (el
mismo correo puede registrarse en dos tiendas); tienda inexistente o inactiva ->
404; el registro solo crea clientes; /auth/registro ya no existe. Todas las
pruebas usan `client_por_peticion` (sesión nueva y sin empresa por petición) y
`dos_empresas` (A = 'tienda-a', B = 'tienda-b')."""

from sqlalchemy import select

from app.core.tenant import empresa_de, fijar_empresa
from app.plataforma.models import Empresa, Usuario

CLAVE = "claveSegura123"


def _datos(email: str = "cliente@example.com") -> dict:
    return {"nombre": "Cli", "apellido": "Ente", "email": email, "password": CLAVE}


def _registrar(client, codigo: str, email: str = "cliente@example.com"):
    return client.post(f"/api/v1/public/{codigo}/registro", json=_datos(email))


def _login(client, empresa: str, email: str = "cliente@example.com"):
    return client.post("/api/v1/auth/login", json={"empresa": empresa, "email": email, "password": CLAVE})


def _usuarios_de(db, empresa_id: int, email: str) -> list[tuple[int, int, list[str]]]:
    """(id, empresa_id, roles) de los usuarios de esa empresa con ese correo."""
    original = empresa_de(db)
    fijar_empresa(db, empresa_id)
    try:
        filas = db.scalars(select(Usuario).where(Usuario.email == email)).all()
        return [(u.id, u.empresa_id, [r.nombre for r in u.roles]) for u in filas]
    finally:
        fijar_empresa(db, original)


def test_registro_por_tienda_crea_el_cliente_en_esa_empresa(client_por_peticion, dos_empresas, db_session):
    respuesta = _registrar(client_por_peticion, "tienda-a")

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["email"] == "cliente@example.com"
    assert cuerpo["roles"] == ["cliente"]
    assert "password" not in cuerpo and "password_hash" not in cuerpo
    assert len(_usuarios_de(db_session, dos_empresas.a.id, "cliente@example.com")) == 1
    assert _usuarios_de(db_session, dos_empresas.b.id, "cliente@example.com") == []


def test_el_mismo_correo_se_registra_en_dos_tiendas(client_por_peticion, dos_empresas, db_session):
    en_a = _registrar(client_por_peticion, "tienda-a")
    en_b = _registrar(client_por_peticion, "tienda-b")

    assert en_a.status_code == en_b.status_code == 201
    assert en_a.json()["id"] != en_b.json()["id"]
    assert _usuarios_de(db_session, dos_empresas.a.id, "cliente@example.com")[0][1] == dos_empresas.a.id
    assert _usuarios_de(db_session, dos_empresas.b.id, "cliente@example.com")[0][1] == dos_empresas.b.id


def test_correo_repetido_en_la_misma_tienda_devuelve_409(client_por_peticion, dos_empresas):
    assert _registrar(client_por_peticion, "tienda-a").status_code == 201

    repetido = _registrar(client_por_peticion, "tienda-a")

    assert repetido.status_code == 409
    assert repetido.json() == {"detail": "Ya existe un usuario con ese email"}


def test_el_registro_no_reactiva_una_cuenta_dada_de_baja_ni_le_cambia_la_clave(client_por_peticion, dos_empresas, db_session):
    """Quien se registra con el correo de una cuenta dada de baja heredaría sus compras, su dirección y su PayPal guardado:
    el registro público la rechaza (409, el mismo mensaje que con una activa) y no toca la cuenta."""
    original = _registrar(client_por_peticion, "tienda-a")
    assert original.status_code == 201
    fijar_empresa(db_session, dos_empresas.a.id)
    usuario = db_session.scalar(select(Usuario).where(Usuario.email == "cliente@example.com"))
    usuario.activo = False
    db_session.commit()
    hash_antes = usuario.password_hash

    intruso = client_por_peticion.post(
        "/api/v1/public/tienda-a/registro",
        json={**_datos(), "password": "otraClaveDistinta99"},
    )

    assert intruso.status_code == 409
    assert intruso.json() == {"detail": "Ya existe un usuario con ese email"}
    db_session.expire_all()
    usuario = db_session.scalar(select(Usuario).where(Usuario.email == "cliente@example.com"))
    assert usuario.activo is False and usuario.password_hash == hash_antes
    assert _login(client_por_peticion, "tienda-a").status_code == 401  # sigue sin poder entrar nadie


def test_el_correo_de_una_cuenta_dada_de_baja_en_otra_tienda_si_se_puede_registrar(client_por_peticion, dos_empresas, db_session):
    assert _registrar(client_por_peticion, "tienda-a").status_code == 201
    fijar_empresa(db_session, dos_empresas.a.id)
    db_session.scalar(select(Usuario).where(Usuario.email == "cliente@example.com")).activo = False
    db_session.commit()

    assert _registrar(client_por_peticion, "tienda-b").status_code == 201  # el correo es único POR empresa


def test_tienda_inexistente_o_inactiva_devuelve_404(client_por_peticion, dos_empresas, db_session):
    db_session.execute(Empresa.__table__.update().where(Empresa.id == dos_empresas.b.id).values(activo=False))
    db_session.commit()

    inexistente = _registrar(client_por_peticion, "no-existe")
    inactiva = _registrar(client_por_peticion, "tienda-b")

    assert inexistente.status_code == inactiva.status_code == 404
    assert inexistente.json() == inactiva.json() == {"detail": "Tienda no encontrada"}
    assert _usuarios_de(db_session, dos_empresas.b.id, "cliente@example.com") == []


def test_el_registro_solo_crea_clientes(client_por_peticion, dos_empresas, db_session):
    # Aunque el cuerpo traiga campos de más (roles, empresa_id), se ignoran.
    cuerpo = _datos() | {"roles": ["administrador"], "nombres_rol": ["administrador"], "empresa_id": dos_empresas.b.id}

    respuesta = client_por_peticion.post("/api/v1/public/tienda-a/registro", json=cuerpo)

    assert respuesta.status_code == 201
    assert respuesta.json()["roles"] == ["cliente"]
    assert _usuarios_de(db_session, dos_empresas.a.id, "cliente@example.com")[0][2] == ["cliente"]
    assert _usuarios_de(db_session, dos_empresas.b.id, "cliente@example.com") == []


def test_auth_registro_ya_no_existe(client_por_peticion, dos_empresas):
    respuesta = client_por_peticion.post("/api/v1/auth/registro", json=_datos())

    assert respuesta.status_code in (404, 405)


def test_el_registro_esta_limitado_a_5_por_minuto(client_por_peticion, dos_empresas):
    estados = [_registrar(client_por_peticion, "tienda-a", f"cli{i}@example.com").status_code for i in range(6)]

    assert estados == [201, 201, 201, 201, 201, 429]


def test_el_cliente_registrado_en_a_no_entra_en_b(client_por_peticion, dos_empresas):
    assert _registrar(client_por_peticion, "tienda-a").status_code == 201

    en_a = _login(client_por_peticion, "tienda-a")
    en_b = _login(client_por_peticion, "tienda-b")

    assert en_a.status_code == 200
    assert en_b.status_code == 401
