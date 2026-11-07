"""Notificaciones push (FCM): el registro del teléfono (`/api/v1/dispositivos-push`) y el envío en segundo plano que
dispara cada `Notificacion` nueva. FCM y el OAuth de Google son simulados (`tests/push_simulado.py`): ninguna prueba sale
a la red. NO se probó contra Firebase real."""

import logging

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.tenant import empresa_de, fijar_empresa
from app.plataforma import politicas
from app.plataforma.models import Bitacora, DispositivoPush, Notificacion
from tests.push_simulado import SimuladorFCM, error_fcm

URL = "/api/v1/dispositivos-push"
BAJA = f"{URL}/baja"
TOKEN_1 = "token-del-telefono-uno-" + "a" * 100
TOKEN_2 = "token-del-telefono-dos-" + "b" * 100
TOKEN_3 = "token-del-telefono-tres-" + "c" * 100


@pytest.fixture()
def fcm(monkeypatch, db_session) -> SimuladorFCM:
    return SimuladorFCM(monkeypatch, db_session)


def _alta(client, headers, token=TOKEN_1):
    return client.post(URL, json={"token": token, "plataforma": "android"}, headers=headers)


def _baja(client, headers, token=TOKEN_1):
    return client.post(BAJA, json={"token": token}, headers=headers)


def _yo(client, headers) -> int:
    return client.get("/api/v1/auth/yo", headers=headers).json()["id"]


def _filas(db_session) -> list[DispositivoPush]:
    db_session.expire_all()
    return list(db_session.scalars(select(DispositivoPush).order_by(DispositivoPush.id)))


def _fila(db_session, token) -> DispositivoPush | None:
    return next((f for f in _filas(db_session) if f.token == token), None)


def _bitacora(db_session) -> list[Bitacora]:
    db_session.expire_all()
    return list(db_session.scalars(select(Bitacora).where(Bitacora.entidad == "dispositivo_push").order_by(Bitacora.id)))


# ---- alta ----


def test_el_alta_responde_204_y_guarda_el_dispositivo_del_usuario(client, db_session, cliente_headers):
    respuesta = _alta(client, cliente_headers)

    assert respuesta.status_code == 204 and respuesta.content == b""
    (fila,) = _filas(db_session)
    assert (fila.usuario_id, fila.token, fila.plataforma, fila.activo) == (_yo(client, cliente_headers), TOKEN_1, "android", True)
    assert fila.empresa_id is not None


def test_cualquier_usuario_autenticado_puede_registrar_sin_permiso_ni_plan(client, db_session, admin_headers, cliente_headers):
    assert _alta(client, admin_headers, TOKEN_1).status_code == 204
    assert _alta(client, cliente_headers, TOKEN_2).status_code == 204
    assert len(_filas(db_session)) == 2


def test_sin_sesion_responde_401(client):
    assert client.post(URL, json={"token": TOKEN_1, "plataforma": "android"}).status_code == 401
    assert client.post(BAJA, json={"token": TOKEN_1}).status_code == 401


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"token": "corto", "plataforma": "android"},
        {"token": "x" * 513, "plataforma": "android"},
        {"token": "con espacios " + "x" * 30, "plataforma": "android"},
        {"token": TOKEN_1, "plataforma": "ios"},
        {"token": TOKEN_1},
        {"plataforma": "android"},
    ],
)
def test_un_cuerpo_invalido_responde_422_y_no_guarda_nada(client, db_session, cliente_headers, cuerpo):
    assert client.post(URL, json=cuerpo, headers=cliente_headers).status_code == 422
    assert _filas(db_session) == []


def test_repetir_el_alta_es_idempotente_y_no_deja_mas_bitacora(client, db_session, cliente_headers):
    for _ in range(3):
        assert _alta(client, cliente_headers).status_code == 204

    assert len(_filas(db_session)) == 1
    assert [(b.accion, b.datos["reasignado"], b.datos["reactivado"]) for b in _bitacora(db_session)] == [("registrar", False, False)]


def test_un_token_dado_de_baja_se_reactiva_con_el_alta(client, db_session, cliente_headers):
    _alta(client, cliente_headers)
    _baja(client, cliente_headers)
    assert _fila(db_session, TOKEN_1).activo is False

    assert _alta(client, cliente_headers).status_code == 204

    assert len(_filas(db_session)) == 1 and _fila(db_session, TOKEN_1).activo is True
    assert [(b.accion, b.datos.get("reactivado")) for b in _bitacora(db_session)] == [
        ("registrar", False), ("quitar", None), ("registrar", True),
    ]


def test_si_otro_usuario_inicia_sesion_en_el_mismo_telefono_el_registro_se_reasigna(client, db_session, admin_headers, cliente_headers):
    _alta(client, cliente_headers)

    assert _alta(client, admin_headers).status_code == 204

    (fila,) = _filas(db_session)
    assert fila.usuario_id == _yo(client, admin_headers) and fila.activo is True
    assert [(b.accion, b.datos["reasignado"]) for b in _bitacora(db_session)] == [("registrar", False), ("registrar", True)]


def test_el_antiguo_dueno_ya_no_recibe_los_avisos_del_telefono(client, db_session, admin_headers, cliente_headers, fcm):
    cliente_id = _yo(client, cliente_headers)
    _alta(client, cliente_headers)
    _alta(client, admin_headers)  # el teléfono pasa al administrador

    politicas.crear_notificacion(db_session, cliente_id, "Para el cliente")
    fcm.correr()

    assert fcm.mensajes == []


# ---- baja ----


def test_la_baja_desactiva_el_token_propio_y_deja_bitacora(client, db_session, cliente_headers):
    _alta(client, cliente_headers)

    respuesta = _baja(client, cliente_headers)

    assert respuesta.status_code == 204
    assert _fila(db_session, TOKEN_1).activo is False
    assert [b.accion for b in _bitacora(db_session)] == ["registrar", "quitar"]


def test_la_baja_es_idempotente(client, db_session, cliente_headers):
    _alta(client, cliente_headers)

    assert [_baja(client, cliente_headers).status_code for _ in range(3)] == [204, 204, 204]

    assert len(_filas(db_session)) == 1 and [b.accion for b in _bitacora(db_session)] == ["registrar", "quitar"]


def test_la_baja_de_un_token_ajeno_responde_204_y_no_toca_nada(client, db_session, admin_headers, cliente_headers):
    _alta(client, cliente_headers)

    assert _baja(client, admin_headers).status_code == 204  # el administrador no es dueño de ese token

    assert _fila(db_session, TOKEN_1).activo is True
    assert [b.accion for b in _bitacora(db_session)] == ["registrar"]


def test_la_baja_de_un_token_inexistente_responde_204(client, cliente_headers):
    assert _baja(client, cliente_headers, "token-que-nunca-se-registro-" + "z" * 30).status_code == 204


def test_la_baja_valida_el_cuerpo(client, cliente_headers):
    assert client.post(BAJA, json={}, headers=cliente_headers).status_code == 422
    assert client.post(BAJA, json={"token": ""}, headers=cliente_headers).status_code == 422


# ---- bitácora sin tokens ----


def test_la_bitacora_nunca_guarda_el_token(client, db_session, admin_headers, cliente_headers):
    _alta(client, cliente_headers)
    _alta(client, admin_headers)
    _baja(client, admin_headers)

    filas = _bitacora(db_session)

    assert len(filas) == 3
    for fila in filas:
        assert TOKEN_1 not in str(fila.datos) and TOKEN_1 not in str(fila.entidad_id)
        assert set(fila.datos) <= {"plataforma", "reasignado", "reactivado"}


# ---- límites ----


def test_al_pasar_el_maximo_se_desactiva_el_dispositivo_mas_antiguo(client, db_session, cliente_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "push_max_dispositivos_por_usuario", 2)
    _alta(client, cliente_headers, TOKEN_1)
    _alta(client, cliente_headers, TOKEN_2)

    _alta(client, cliente_headers, TOKEN_3)

    assert [(f.token, f.activo) for f in _filas(db_session)] == [(TOKEN_1, False), (TOKEN_2, True), (TOKEN_3, True)]


def test_usar_un_token_antiguo_lo_vuelve_el_mas_reciente(client, db_session, cliente_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "push_max_dispositivos_por_usuario", 2)
    _alta(client, cliente_headers, TOKEN_1)
    _alta(client, cliente_headers, TOKEN_2)
    _alta(client, cliente_headers, TOKEN_1)  # el uno vuelve a usarse: ahora el más antiguo es el dos

    _alta(client, cliente_headers, TOKEN_3)

    assert {f.token: f.activo for f in _filas(db_session)} == {TOKEN_1: True, TOKEN_2: False, TOKEN_3: True}


def test_hay_un_limite_de_peticiones_por_cuenta(client, cliente_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "push_dispositivos_max_por_ventana", 3)
    assert _alta(client, cliente_headers).status_code == 204
    assert _alta(client, cliente_headers).status_code == 204
    assert _baja(client, cliente_headers).status_code == 204  # las bajas también cuentan

    respuesta = _alta(client, cliente_headers)

    assert respuesta.status_code == 429 and int(respuesta.headers["Retry-After"]) >= 1


def test_el_limite_es_por_cuenta_y_no_afecta_a_otro_usuario(client, admin_headers, cliente_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "push_dispositivos_max_por_ventana", 1)
    assert _alta(client, cliente_headers).status_code == 204
    assert _alta(client, cliente_headers, TOKEN_2).status_code == 429

    assert _alta(client, admin_headers, TOKEN_3).status_code == 204


# ---- una empresa no ve el token de otra ----


def test_el_mismo_token_en_dos_empresas_son_dos_registros_independientes(client_por_peticion, db_session, dos_empresas):
    a, b = dos_empresas.a, dos_empresas.b
    assert _alta(client_por_peticion, a.headers).status_code == 204
    assert _alta(client_por_peticion, b.headers).status_code == 204

    def _de(empresa) -> list[tuple[int, bool]]:
        fijar_empresa(db_session, empresa.id)  # el filtro por empresa hace que cada una vea solo lo suyo
        return [(f.usuario_id, f.activo) for f in _filas(db_session)]

    original = empresa_de(db_session)
    try:
        assert _de(a) == [(a.admin_id, True)] and _de(b) == [(b.admin_id, True)]
        assert _baja(client_por_peticion, b.headers).status_code == 204
        assert _de(a) == [(a.admin_id, True)] and _de(b) == [(b.admin_id, False)]
    finally:
        fijar_empresa(db_session, original)


# ---- envío ----


def _registrar_y_notificar(client, db_session, headers, titulo="Hola", **extra):
    _alta(client, headers)
    return politicas.crear_notificacion(db_session, _yo(client, headers), titulo, **extra)


def test_una_notificacion_nueva_programa_el_push_y_llega_a_fcm(client, db_session, cliente_headers, fcm):
    aviso = _registrar_y_notificar(client, db_session, cliente_headers, "Cobramos tu pedido", mensaje="Pagaste Bs 200", tipo="pedido_diferido", referencia_id=9)

    assert len(fcm.programados) == 1
    assert fcm.mensajes == []  # nada sale en el hilo de la petición
    assert fcm.correr() == 1

    (cuerpo,) = fcm.mensajes
    assert cuerpo["message"]["token"] == TOKEN_1
    assert cuerpo["message"]["notification"] == {"title": "Cobramos tu pedido", "body": "Pagaste Bs 200"}
    assert cuerpo["message"]["data"] == {"tipo": "pedido_diferido", "referencia_id": "9", "notificacion_id": str(aviso.id)}
    assert cuerpo["message"]["android"] == {"priority": "HIGH", "notification": {"channel_id": "fashionstore_avisos"}}


def test_una_notificacion_sin_tipo_ni_referencia_manda_datos_vacios(client, db_session, cliente_headers, fcm):
    aviso = _registrar_y_notificar(client, db_session, cliente_headers)
    fcm.correr()

    assert fcm.mensajes[0]["message"]["data"] == {"tipo": "", "referencia_id": "", "notificacion_id": str(aviso.id)}
    assert fcm.mensajes[0]["message"]["notification"]["body"] == ""


def test_el_push_va_a_todos_los_dispositivos_activos_del_usuario_y_a_nadie_mas(client, db_session, admin_headers, cliente_headers, fcm):
    _alta(client, cliente_headers, TOKEN_1)
    _alta(client, cliente_headers, TOKEN_2)
    _alta(client, cliente_headers, TOKEN_3)
    _baja(client, cliente_headers, TOKEN_3)  # inactivo: no recibe
    _alta(client, admin_headers, "token-del-administrador-" + "d" * 60)  # de otro usuario: no recibe

    politicas.crear_notificacion(db_session, _yo(client, cliente_headers), "Solo para el cliente")
    fcm.correr()

    assert sorted(fcm.destinatarios) == sorted([TOKEN_1, TOKEN_2])


def test_un_usuario_sin_dispositivos_no_genera_llamadas_a_fcm(client, db_session, cliente_headers, fcm):
    politicas.crear_notificacion(db_session, _yo(client, cliente_headers), "Nadie escucha")

    fcm.correr()

    assert fcm.mensajes == [] and fcm.peticiones_oauth == []


def test_un_usuario_desactivado_no_recibe_push(client, db_session, cliente_headers, fcm):
    from app.plataforma.models import Usuario

    _alta(client, cliente_headers)
    usuario_id = _yo(client, cliente_headers)
    db_session.get(Usuario, usuario_id).activo = False
    db_session.commit()

    politicas.crear_notificacion(db_session, usuario_id, "Ya no trabaja aquí")
    fcm.correr()

    assert fcm.mensajes == []


def test_sin_credencial_no_se_programa_nada_y_todo_funciona(client, db_session, cliente_headers, monkeypatch):
    sim = SimuladorFCM(monkeypatch, db_session, con_credencial=False)
    _alta(client, cliente_headers)

    aviso = politicas.crear_notificacion(db_session, _yo(client, cliente_headers), "Sin Firebase")

    assert sim.programados == [] and sim.mensajes == []
    assert [n["titulo"] for n in client.get("/api/v1/notificaciones", headers=cliente_headers).json()] == ["Sin Firebase"]
    assert aviso.id is not None


def test_con_commit_false_el_push_espera_al_commit_de_quien_llamo(client, db_session, cliente_headers, fcm):
    _alta(client, cliente_headers)
    usuario_id = _yo(client, cliente_headers)

    politicas.crear_notificacion(db_session, usuario_id, "Uno", commit=False)
    politicas.crear_notificacion(db_session, usuario_id, "Dos", commit=False)
    assert fcm.programados == []

    db_session.commit()
    assert len(fcm.programados) == 1  # una sola tarea con las dos notificaciones
    fcm.correr()

    assert sorted(m["message"]["notification"]["title"] for m in fcm.mensajes) == ["Dos", "Uno"]


def test_si_la_transaccion_se_revierte_no_sale_ningun_push(client, db_session, cliente_headers, fcm):
    _alta(client, cliente_headers)

    politicas.crear_notificacion(db_session, _yo(client, cliente_headers), "Se arrepintió", commit=False)
    db_session.rollback()
    db_session.commit()

    assert fcm.correr() == 0 and fcm.mensajes == []


def test_soltar_un_savepoint_no_dispara_el_push_hasta_el_commit_real(client, db_session, cliente_headers, fcm):
    _alta(client, cliente_headers)
    usuario_id = _yo(client, cliente_headers)

    with db_session.begin_nested():
        politicas.crear_notificacion(db_session, usuario_id, "Dentro del savepoint", commit=False)
    assert fcm.programados == []

    db_session.commit()
    assert len(fcm.programados) == 1
    fcm.correr()
    assert [m["message"]["notification"]["title"] for m in fcm.mensajes] == ["Dentro del savepoint"]


def test_una_notificacion_de_un_savepoint_revertido_no_sale_aunque_la_transaccion_confirme(client, db_session, cliente_headers, fcm):
    _alta(client, cliente_headers)
    usuario_id = _yo(client, cliente_headers)
    politicas.crear_notificacion(db_session, usuario_id, "Se queda", commit=False)

    savepoint = db_session.begin_nested()
    politicas.crear_notificacion(db_session, usuario_id, "Se deshace", commit=False)
    savepoint.rollback()
    db_session.commit()
    fcm.correr()

    assert [m["message"]["notification"]["title"] for m in fcm.mensajes] == ["Se queda"]
    assert db_session.scalar(select(Notificacion.id).where(Notificacion.titulo == "Se deshace")) is None


# ---- fallos de FCM ----


def test_un_token_que_fcm_da_por_muerto_se_desactiva_y_los_demas_siguen(client, db_session, cliente_headers, fcm):
    _alta(client, cliente_headers, TOKEN_1)
    _alta(client, cliente_headers, TOKEN_2)
    fcm.respuestas[TOKEN_1] = error_fcm(404, "NOT_FOUND", "UNREGISTERED")

    politicas.crear_notificacion(db_session, _yo(client, cliente_headers), "Aviso")
    fcm.correr()

    assert {f.token: f.activo for f in _filas(db_session)} == {TOKEN_1: False, TOKEN_2: True}
    assert sorted(fcm.destinatarios) == sorted([TOKEN_1, TOKEN_2])
    # El siguiente aviso ya no intenta con el muerto.
    politicas.crear_notificacion(db_session, _yo(client, cliente_headers), "Otro aviso")
    fcm.mensajes.clear()
    fcm.correr()
    assert fcm.destinatarios == [TOKEN_2]


def test_invalid_argument_tambien_desactiva_el_token(client, db_session, cliente_headers, fcm):
    _alta(client, cliente_headers)
    fcm.respuestas[TOKEN_1] = error_fcm(400, "INVALID_ARGUMENT")

    politicas.crear_notificacion(db_session, _yo(client, cliente_headers), "Aviso")
    fcm.correr()

    assert _fila(db_session, TOKEN_1).activo is False


@pytest.mark.parametrize("modo", ["caido", "http_500", "http_429", "oauth_caido"])
def test_fcm_caido_no_rompe_la_operacion_ni_desactiva_dispositivos(client, db_session, cliente_headers, fcm, modo):
    _alta(client, cliente_headers)
    if modo == "caido":
        fcm.caido = True
    elif modo == "oauth_caido":
        fcm.oauth_caido = True
    else:
        fcm.estado_global = error_fcm(int(modo[5:]), "UNAVAILABLE")

    aviso = politicas.crear_notificacion(db_session, _yo(client, cliente_headers), "Aviso")
    fcm.correr()  # no lanza

    assert db_session.get(Notificacion, aviso.id) is not None
    assert _fila(db_session, TOKEN_1).activo is True
    assert [n["titulo"] for n in client.get("/api/v1/notificaciones", headers=cliente_headers).json()] == ["Aviso"]


def test_si_el_segundo_plano_revienta_no_sale_ninguna_excepcion(client, db_session, cliente_headers, fcm, monkeypatch, caplog):
    _alta(client, cliente_headers)

    def _revienta(*_a):
        raise RuntimeError("base caída " + TOKEN_1)

    monkeypatch.setattr(politicas, "_nueva_sesion", _revienta)
    politicas.crear_notificacion(db_session, _yo(client, cliente_headers), "Aviso")

    with caplog.at_level(logging.DEBUG):
        fcm.correr()

    assert "push_fallido" in caplog.text and TOKEN_1 not in caplog.text


def test_si_programar_el_envio_falla_la_operacion_igual_confirma(client, db_session, cliente_headers, fcm, monkeypatch):
    _alta(client, cliente_headers)

    def _no_programa(*_a):
        raise RuntimeError("sin hilos")

    monkeypatch.setattr(politicas, "_programar_en_segundo_plano", _no_programa)

    aviso = politicas.crear_notificacion(db_session, _yo(client, cliente_headers), "Aviso")  # no lanza

    assert db_session.get(Notificacion, aviso.id) is not None


# ---- nada sensible en los logs ----


def test_los_tokens_de_dispositivo_no_salen_completos_en_ningun_log(client, db_session, cliente_headers, fcm, caplog):
    _alta(client, cliente_headers)
    fcm.estado_global = error_fcm(500, "INTERNAL")

    with caplog.at_level(logging.DEBUG):
        politicas.crear_notificacion(db_session, _yo(client, cliente_headers), "Aviso")
        fcm.correr()

    assert "push_no_enviado" in caplog.text
    assert TOKEN_1 not in caplog.text and TOKEN_1[-6:] in caplog.text
    assert "BEGIN PRIVATE KEY" not in caplog.text
