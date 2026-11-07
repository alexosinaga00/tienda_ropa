"""Dispositivos de notificaciones push en PostgreSQL real (FCM simulado; solo contra una base `_test`).

SQLite no hace esperar a un INSERT con clave repetida hasta que la otra transacción termina. Aquí:
- varias altas SIMULTÁNEAS del mismo token (del mismo usuario o de dos usuarios) dejan UNA sola fila y ninguna falla
  (el UNIQUE (empresa, token) hace perder la carrera a la segunda, que recoge la fila ya creada);
- el UNIQUE y el CHECK de plataforma existen de verdad en el esquema que dejan las migraciones;
- el envío en segundo plano funciona con sesiones propias contra PostgreSQL: llega a los dispositivos activos y
  desactiva el token que FCM da por muerto."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.plataforma import politicas
from app.plataforma.casos_uso.cu01_autenticar_registrar_usuarios import GestionarDispositivosPush
from app.plataforma.models import DispositivoPush, Notificacion
from app.plataforma.schemas import DispositivoPushRegistrar
from tests.push_simulado import SimuladorFCM, error_fcm

from .conftest import CLAVE, registrar_cliente
from .paralelo import ejecutar_en_paralelo

URL = "/api/v1/dispositivos-push"
TOKEN = "token-del-telefono-pg-" + "p" * 100
TOKEN_2 = "token-del-segundo-telefono-pg-" + "q" * 100


@pytest.fixture()
def fcm(monkeypatch, fabrica_pg) -> SimuladorFCM:
    simulador = SimuladorFCM(monkeypatch)
    monkeypatch.setattr(politicas, "_nueva_sesion", fabrica_pg)
    return simulador


def _cliente(client_pg, fabrica_pg, email="push-pg@example.com") -> tuple[int, dict]:
    usuario_id = registrar_cliente(client_pg, fabrica_pg, email)
    login = client_pg.post("/api/v1/auth/login", json={"empresa": "fashionstore", "email": email, "password": CLAVE})
    return usuario_id, {"Authorization": f"Bearer {login.json()['access_token']}"}


def _registrar(usuario_id: int, token: str = TOKEN):
    datos = DispositivoPushRegistrar(token=token, plataforma="android")
    return lambda db: GestionarDispositivosPush().registrar(db, usuario_id, datos)


def _filas(fabrica) -> list[DispositivoPush]:
    with fabrica() as db:
        return list(db.scalars(select(DispositivoPush).order_by(DispositivoPush.id)))


def test_el_esquema_de_las_migraciones_tiene_el_unique_y_el_check(client_pg, fabrica_pg, admin_pg):
    with fabrica_pg() as db:
        db.add(DispositivoPush(usuario_id=1, token=TOKEN, plataforma="android", activo=True))
        db.commit()
        db.add(DispositivoPush(usuario_id=1, token=TOKEN, plataforma="android", activo=True))
        with pytest.raises(IntegrityError):  # UNIQUE (empresa_id, token)
            db.commit()
        db.rollback()
        db.add(DispositivoPush(usuario_id=1, token=TOKEN_2, plataforma="ios", activo=True))
        with pytest.raises(IntegrityError):  # CHECK plataforma IN ('android','web')
            db.commit()
        db.rollback()
        db.add(DispositivoPush(usuario_id=1, token=TOKEN_2, plataforma="web", activo=True))
        db.commit()  # el navegador (push web) cabe desde la migración b6d1f3a8c725


def test_la_migracion_del_push_web_se_puede_bajar_y_volver_a_subir(url_pg, client_pg, fabrica_pg, admin_pg, engine_pg):
    from sqlalchemy import text

    from tests.postgres.conftest import ejecutar_alembic

    with fabrica_pg() as db:
        db.add(DispositivoPush(usuario_id=1, token=TOKEN, plataforma="android", activo=True))
        db.add(DispositivoPush(usuario_id=1, token=TOKEN_2, plataforma="web", activo=True))
        db.commit()
    engine_pg.dispose()  # sin conexiones abiertas que bloqueen el DDL de alembic
    try:
        bajada = ejecutar_alembic(url_pg, "downgrade", "f4b8d2a6c139")
        assert bajada.returncode == 0, bajada.stderr
        with engine_pg.begin() as conexion:
            # La baja borra las filas web (tokens de navegador) y deja el CHECK de solo android.
            assert [f[0] for f in conexion.execute(text("SELECT plataforma FROM dispositivo_push"))] == ["android"]
        with pytest.raises(IntegrityError), engine_pg.begin() as conexion:
            conexion.execute(
                text(
                    "INSERT INTO dispositivo_push (empresa_id, usuario_id, token, plataforma, activo) "
                    "VALUES (1, 1, 'token-web-rechazado', 'web', true)"
                )
            )
    finally:
        engine_pg.dispose()
        subida = ejecutar_alembic(url_pg, "upgrade", "head")
        assert subida.returncode == 0, subida.stderr
    with fabrica_pg() as db:
        db.add(DispositivoPush(usuario_id=1, token=TOKEN_2, plataforma="web", activo=True))
        db.commit()  # otra vez acepta web


def test_ocho_altas_simultaneas_del_mismo_token_dejan_una_fila_y_ninguna_falla(client_pg, fabrica_pg):
    usuario_id, _ = _cliente(client_pg, fabrica_pg)

    resultados = ejecutar_en_paralelo(fabrica_pg, [_registrar(usuario_id) for _ in range(8)])

    assert all(r.ok for r in resultados), [r.error for r in resultados if not r.ok]
    (fila,) = _filas(fabrica_pg)
    assert (fila.usuario_id, fila.token, fila.activo) == (usuario_id, TOKEN, True)


def test_dos_usuarios_que_registran_el_mismo_telefono_a_la_vez_dejan_una_fila_de_uno_de_ellos(client_pg, fabrica_pg):
    uno, _ = _cliente(client_pg, fabrica_pg, "uno-pg@example.com")
    otro, _ = _cliente(client_pg, fabrica_pg, "otro-pg@example.com")

    resultados = ejecutar_en_paralelo(fabrica_pg, [_registrar(uno), _registrar(otro), _registrar(uno), _registrar(otro)])

    assert all(r.ok for r in resultados), [r.error for r in resultados if not r.ok]
    (fila,) = _filas(fabrica_pg)
    assert fila.usuario_id in (uno, otro) and fila.activo is True


def test_el_flujo_http_de_alta_y_baja_en_postgres(client_pg, fabrica_pg):
    usuario_id, headers = _cliente(client_pg, fabrica_pg)

    assert client_pg.post(URL, json={"token": TOKEN, "plataforma": "android"}, headers=headers).status_code == 204
    assert client_pg.post(f"{URL}/baja", json={"token": TOKEN}, headers=headers).status_code == 204

    (fila,) = _filas(fabrica_pg)
    assert (fila.usuario_id, fila.activo) == (usuario_id, False)


def test_el_envio_en_segundo_plano_llega_a_los_activos_y_desactiva_el_token_muerto(client_pg, fabrica_pg, fcm):
    usuario_id, headers = _cliente(client_pg, fabrica_pg)
    for token in (TOKEN, TOKEN_2):
        assert client_pg.post(URL, json={"token": token, "plataforma": "android"}, headers=headers).status_code == 204
    fcm.respuestas[TOKEN_2] = error_fcm(404, "NOT_FOUND", "UNREGISTERED")

    with fabrica_pg() as db:
        aviso = politicas.crear_notificacion(db, usuario_id, "Cobramos tu pedido", "Listo", "pedido_diferido", 5)
        aviso_id = aviso.id
    assert fcm.mensajes == [] and len(fcm.programados) == 1
    fcm.correr()

    assert sorted(fcm.destinatarios) == sorted([TOKEN, TOKEN_2])
    assert {f.token: f.activo for f in _filas(fabrica_pg)} == {TOKEN: True, TOKEN_2: False}
    assert fcm.mensajes[0]["message"]["data"]["notificacion_id"] == str(aviso_id)
    with fabrica_pg() as db:
        assert db.scalar(select(Notificacion.titulo).where(Notificacion.id == aviso_id)) == "Cobramos tu pedido"


def test_si_la_transaccion_se_revierte_en_postgres_no_sale_el_push(client_pg, fabrica_pg, fcm):
    usuario_id, headers = _cliente(client_pg, fabrica_pg)
    client_pg.post(URL, json={"token": TOKEN, "plataforma": "android"}, headers=headers)

    with fabrica_pg() as db:
        politicas.crear_notificacion(db, usuario_id, "Se arrepintió", commit=False)
        db.rollback()

    assert fcm.programados == [] and fcm.correr() == 0
