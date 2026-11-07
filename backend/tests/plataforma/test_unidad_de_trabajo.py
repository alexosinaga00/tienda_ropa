"""Unidad de trabajo (G1) en plataforma: el registro de cliente es UNA sola
transacción (usuario + rol + perfil de cliente, un solo commit).

Antes hacía 3 commits: si faltaba el rol "cliente" el usuario ya estaba
confirmado y quedaba huérfano (sin rol ni perfil).
"""

import pytest
from sqlalchemy import func, select

from app.core.exceptions import DomainError
from app.plataforma.casos_uso.cu01_autenticar_registrar_usuarios import ROL_CLIENTE, RegistrarCliente
from app.plataforma.models import Cliente, Rol, Usuario
from app.plataforma.repository import ClienteRepository, UsuarioRepository
from app.plataforma.schemas import RegistroRequest, UsuarioCrear

EMAIL = "nuevo.cliente@example.com"


def _registro(email: str = EMAIL, ci_nit: str | None = "1234567") -> RegistroRequest:
    return RegistroRequest(
        nombre="Nuevo", apellido="Cliente", email=email, password="claveSegura123", ci_nit=ci_nit
    )


def _desactivar_rol_cliente(db) -> None:
    rol = db.scalar(select(Rol).where(Rol.nombre == ROL_CLIENTE))
    rol.activo = False
    db.commit()


def _contar_usuarios(db, email: str) -> int:
    return db.scalar(select(func.count()).select_from(Usuario).where(Usuario.email == email))


def _contar_clientes(db) -> int:
    return db.scalar(select(func.count()).select_from(Cliente))


def test_registro_sin_rol_cliente_no_deja_usuario_huerfano(db_session):
    _desactivar_rol_cliente(db_session)
    clientes_antes = _contar_clientes(db_session)

    with pytest.raises(DomainError, match="Uno o más roles no existen o están inactivos"):
        RegistrarCliente().registrar(db_session, _registro())

    # Nada quedó: ni usuario, ni perfil de cliente (ni siquiera sin confirmar).
    assert _contar_usuarios(db_session, EMAIL) == 0
    assert _contar_clientes(db_session) == clientes_antes
    db_session.rollback()
    assert _contar_usuarios(db_session, EMAIL) == 0


def test_registro_http_sin_rol_cliente_da_400_y_no_deja_usuario(client, db_session):
    _desactivar_rol_cliente(db_session)

    respuesta = client.post(
        "/api/v1/public/fashionstore/registro",
        json={"nombre": "Nuevo", "apellido": "Cliente", "email": EMAIL, "password": "claveSegura123"},
    )

    # Mismo código y mensaje de siempre.
    assert respuesta.status_code == 400
    assert respuesta.json()["detail"] == "Uno o más roles no existen o están inactivos"
    assert _contar_usuarios(db_session, EMAIL) == 0


def test_registro_de_usuario_dado_de_baja_sin_rol_no_lo_reactiva(client, db_session):
    cuerpo = {"nombre": "Nuevo", "apellido": "Cliente", "email": EMAIL, "password": "claveSegura123"}
    assert client.post("/api/v1/public/fashionstore/registro", json=cuerpo).status_code == 201
    usuario = UsuarioRepository().obtener_por_email(db_session, EMAIL)
    usuario.activo = False
    db_session.commit()
    hash_original = usuario.password_hash
    _desactivar_rol_cliente(db_session)

    with pytest.raises(DomainError):
        RegistrarCliente().registrar(db_session, _registro(ci_nit="999"))

    db_session.expire_all()
    usuario = UsuarioRepository().obtener_por_email(db_session, EMAIL)
    assert usuario.activo is False  # la reactivación también se revirtió
    assert usuario.password_hash == hash_original


def test_registro_exitoso_hace_un_solo_commit(db_session, monkeypatch):
    commits: list[int] = []
    commit_original = db_session.commit

    def commit_contado():
        commits.append(1)
        commit_original()

    monkeypatch.setattr(db_session, "commit", commit_contado)

    usuario = RegistrarCliente().registrar(db_session, _registro(ci_nit="555"))

    assert len(commits) == 1
    db_session.rollback()  # lo confirmado sobrevive
    assert [r.nombre for r in usuario.roles] == [ROL_CLIENTE]
    perfil = ClienteRepository().obtener_por_usuario(db_session, usuario.id)
    assert perfil.ci_nit == "555"


def test_registro_http_exitoso_sigue_igual(client, db_session):
    respuesta = client.post(
        "/api/v1/public/fashionstore/registro",
        json={
            "nombre": "Nuevo",
            "apellido": "Cliente",
            "email": EMAIL,
            "password": "claveSegura123",
            "ci_nit": "42",
        },
    )

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["email"] == EMAIL
    assert cuerpo["roles"] == [ROL_CLIENTE]
    assert ClienteRepository().obtener_por_usuario(db_session, cuerpo["id"]).ci_nit == "42"


def test_reregistro_de_usuario_dado_de_baja_se_rechaza_y_no_toca_su_perfil_de_cliente(client, db_session):
    cuerpo = {
        "nombre": "Nuevo",
        "apellido": "Cliente",
        "email": EMAIL,
        "password": "claveSegura123",
        "ci_nit": "111",
    }
    primero = client.post("/api/v1/public/fashionstore/registro", json=cuerpo).json()
    usuario = UsuarioRepository().obtener_por_email(db_session, EMAIL)
    usuario.activo = False
    db_session.commit()
    clientes_antes = _contar_clientes(db_session)

    respuesta = client.post("/api/v1/public/fashionstore/registro", json={**cuerpo, "ci_nit": "222"})

    assert respuesta.status_code == 409  # el registro público ya no reactiva cuentas dadas de baja
    assert _contar_clientes(db_session) == clientes_antes  # no se duplicó el perfil
    db_session.expire_all()
    assert ClienteRepository().obtener_por_usuario(db_session, primero["id"]).ci_nit == "111"  # y no se pisó el CI


def test_cliente_repository_crear_o_actualizar_perfil_commit_false_mas_rollback(db_session):
    usuario = UsuarioRepository().crear(
        db_session,
        UsuarioCrear(nombre="A", apellido="B", email="solo.usuario@example.com", password="claveSegura123"),
    )
    repo = ClienteRepository()

    repo.crear_o_actualizar_perfil(db_session, usuario.id, "77", commit=False)
    assert repo.buscar_por_usuario(db_session, usuario.id) is not None

    db_session.rollback()
    assert repo.buscar_por_usuario(db_session, usuario.id) is None


def test_usuario_repository_crear_y_asignar_roles_commit_false_mas_rollback(db_session):
    repo = UsuarioRepository()
    usuario = repo.crear(
        db_session,
        UsuarioCrear(nombre="A", apellido="B", email="uow.usuario@example.com", password="claveSegura123"),
        commit=False,
    )
    repo.asignar_roles(db_session, usuario, [ROL_CLIENTE], commit=False)
    assert usuario.id is not None

    db_session.rollback()
    assert _contar_usuarios(db_session, "uow.usuario@example.com") == 0
