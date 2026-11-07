"""Compra confirmada: cuando una venta pasa a `pagada` el comprador recibe UNA notificación (con su push) y UN correo, sea
cual sea el origen del pago (webhook, polling, QR, Caja, pedido sin conexión). Brevo y FCM son simulados
(`tests/correo_simulado.py` y `tests/push_simulado.py`); ninguna prueba sale a la red. NO se probó contra Brevo ni
Firebase reales."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.comercial.politicas import (
    confirmar_venta,
    construir_correo_compra_confirmada,
    construir_enlace_verificacion,
)
from app.comercial.pasarela import LibelulaGateway
from app.core.config import get_settings
from app.plataforma import politicas as plataforma_politicas
from app.plataforma.models import Cliente, Notificacion, Usuario
from tests.comercial.test_cambio_talla import ctx, reloj  # noqa: F401  (los fixtures se reutilizan)
from tests.comercial.test_pagos import _firmar, contexto  # noqa: F401
from tests.comercial.test_pedido_diferido import _cuerpo, _enviar, listo, pp  # noqa: F401
from tests.correo_simulado import SimuladorBrevo
from tests.push_simulado import SimuladorFCM

TOKEN = "token-del-telefono-del-comprador-" + "z" * 90
TIPO = "compra_confirmada"


@pytest.fixture()
def avisos(monkeypatch, db_session) -> SimpleNamespace:
    """Brevo y FCM simulados; los envíos en segundo plano se corren con `avisos.fcm.correr()`."""
    return SimpleNamespace(fcm=SimuladorFCM(monkeypatch, db_session), brevo=SimuladorBrevo(monkeypatch))


# ---- ayudas ----


def _venta_digital(client, contexto, cliente_headers, cantidad=1) -> dict:
    client.post(
        "/api/v1/carrito", json={"variante_id": contexto["variante_id"], "cantidad": cantidad}, headers=cliente_headers
    )
    venta = client.post("/api/v1/ventas/digital", json={"sucursal_id": contexto["sucursal_id"]}, headers=cliente_headers)
    assert venta.status_code == 201, venta.text
    return venta.json()


def _iniciar(client, cliente_headers, venta, metodo="libelula") -> dict:
    inicio = client.post(
        "/api/v1/pagos/iniciar", json={"venta_id": venta["id"], "metodo_pago": metodo}, headers=cliente_headers
    )
    assert inicio.status_code == 201, inicio.text
    return inicio.json()


def _webhook(client, id_transaccion: str, estado: str = "aprobado"):
    cuerpo, firma = _firmar({"id_transaccion": id_transaccion, "estado": estado})
    return client.post(
        "/api/v1/pagos/webhook/libelula", content=cuerpo, headers={"Content-Type": "application/json", "x-signature": firma}
    )


def _avisos_de_compra(client, headers) -> list[dict]:
    return [n for n in client.get("/api/v1/notificaciones", headers=headers).json() if n["tipo"] == TIPO]


def _registrar_telefono(client, headers) -> None:
    assert client.post("/api/v1/dispositivos-push", json={"token": TOKEN, "plataforma": "android"}, headers=headers).status_code == 204


def _cliente_id(db_session, email: str = "cliente@example.com") -> int:
    usuario = db_session.scalar(select(Usuario).where(Usuario.email == email))
    return db_session.scalar(select(Cliente.id).where(Cliente.usuario_id == usuario.id))


def _venta_en_caja(client, contexto, *, cliente_id=None) -> dict:
    cuerpo = {"sucursal_id": contexto["sucursal_id"], "detalle": [{"variante_id": contexto["variante_id"], "cantidad": 2}]}
    if cliente_id is not None:
        cuerpo["cliente_id"] = cliente_id
    venta = client.post("/api/v1/ventas/presencial", json=cuerpo, headers=contexto["cajero_headers"])
    assert venta.status_code == 201, venta.text
    return venta.json()


def _cobrar_en_caja(client, contexto, venta) -> None:
    pago = client.post(
        "/api/v1/pagos/caja", json={"venta_id": venta["id"], "metodo_pago": "qr"}, headers=contexto["cajero_headers"]
    )
    assert pago.status_code == 201, pago.text


# ---- cada origen del pago avisa una vez ----


def test_el_webhook_avisa_con_una_notificacion_un_push_y_un_correo(client, cliente_headers, contexto, avisos):
    _registrar_telefono(client, cliente_headers)
    venta = _venta_digital(client, contexto, cliente_headers)
    inicio = _iniciar(client, cliente_headers, venta)
    assert avisos.fcm.programados == [] and avisos.brevo.enviados == []  # nada antes de pagar

    assert _webhook(client, inicio["pago"]["referencia_externa"]).status_code == 200
    assert avisos.brevo.enviados == []  # el pago no espera a los envíos
    avisos.fcm.correr()

    (aviso,) = _avisos_de_compra(client, cliente_headers)
    assert aviso["titulo"] == "Compra confirmada" and aviso["referencia_id"] == venta["id"]
    assert aviso["mensaje"] == f"Tu compra {venta['codigo']} por Bs 100.00 está pagada."
    (push,) = avisos.fcm.mensajes
    assert push["message"]["token"] == TOKEN
    assert push["message"]["data"] == {
        "tipo": TIPO,
        "referencia_id": str(venta["id"]),
        "notificacion_id": str(aviso["id"]),
        "empresa_codigo": "fashionstore",
    }
    (correo,) = avisos.brevo.enviados
    assert correo["to"][0]["email"] == "cliente@example.com"
    assert venta["codigo"] in correo["subject"]


def test_un_webhook_repetido_no_duplica_ni_el_correo_ni_la_notificacion(client, cliente_headers, contexto, avisos):
    venta = _venta_digital(client, contexto, cliente_headers)
    id_transaccion = _iniciar(client, cliente_headers, venta)["pago"]["referencia_externa"]

    for _ in range(3):
        assert _webhook(client, id_transaccion).status_code == 200
        avisos.fcm.correr()

    assert len(_avisos_de_compra(client, cliente_headers)) == 1
    assert len(avisos.brevo.enviados) == 1


def test_polling_y_webhook_de_la_misma_venta_avisan_una_sola_vez(client, cliente_headers, contexto, avisos, monkeypatch):
    venta = _venta_digital(client, contexto, cliente_headers)
    inicio = _iniciar(client, cliente_headers, venta)
    monkeypatch.setattr(LibelulaGateway, "consultar_estado", lambda self, id_transaccion: "aprobado")

    sondeo = client.get(f"/api/v1/pagos/{inicio['pago']['id']}/estado", headers=cliente_headers)
    assert sondeo.json()["estado"] == "aprobado"
    avisos.fcm.correr()
    assert _webhook(client, inicio["pago"]["referencia_externa"]).status_code == 200  # llega tarde
    avisos.fcm.correr()

    assert len(_avisos_de_compra(client, cliente_headers)) == 1
    assert len(avisos.brevo.enviados) == 1


def test_el_pago_qr_sandbox_avisa_una_sola_vez(client, cliente_headers, contexto, avisos):
    venta = _venta_digital(client, contexto, cliente_headers)
    id_transaccion = _iniciar(client, cliente_headers, venta, "qr_online")["pago"]["referencia_externa"]

    assert client.post(f"/api/v1/pagos/qr/{id_transaccion}/confirmar").status_code == 200
    assert client.post(f"/api/v1/pagos/qr/{id_transaccion}/confirmar").status_code == 200  # idempotente
    avisos.fcm.correr()

    assert len(_avisos_de_compra(client, cliente_headers)) == 1
    assert len(avisos.brevo.enviados) == 1


def test_el_cobro_en_caja_de_una_venta_con_cliente_avisa_al_cliente(client, db_session, cliente_headers, contexto, avisos):
    venta = _venta_en_caja(client, contexto, cliente_id=_cliente_id(db_session))

    _cobrar_en_caja(client, contexto, venta)
    avisos.fcm.correr()

    (aviso,) = _avisos_de_compra(client, cliente_headers)
    assert aviso["referencia_id"] == venta["id"] and venta["codigo"] in aviso["mensaje"]
    (correo,) = avisos.brevo.enviados
    assert correo["to"][0]["email"] == "cliente@example.com"


def test_una_venta_en_caja_sin_cliente_no_avisa_a_nadie(client, db_session, cliente_headers, contexto, avisos):
    venta = _venta_en_caja(client, contexto)

    _cobrar_en_caja(client, contexto, venta)
    avisos.fcm.correr()

    assert _avisos_de_compra(client, cliente_headers) == []
    assert avisos.brevo.enviados == []
    assert db_session.scalar(select(Notificacion.id).where(Notificacion.tipo == TIPO)) is None


def test_un_cliente_sin_usuario_activo_no_recibe_aviso(client, db_session, cliente_headers, contexto, avisos):
    cliente_id = _cliente_id(db_session)
    venta = _venta_en_caja(client, contexto, cliente_id=cliente_id)
    db_session.get(Usuario, db_session.get(Cliente, cliente_id).usuario_id).activo = False
    db_session.commit()

    _cobrar_en_caja(client, contexto, venta)
    avisos.fcm.correr()

    assert avisos.brevo.enviados == []
    assert db_session.scalar(select(Notificacion.id).where(Notificacion.tipo == TIPO)) is None


# ---- el pedido sin conexión conserva su propio aviso (no se duplica) ----


def test_el_pedido_sin_conexion_cobrado_sigue_con_un_solo_correo_y_una_sola_notificacion(
    client, cliente_headers, listo, pp, avisos
):
    datos = _enviar(client, cliente_headers, _cuerpo(listo)).json()
    assert datos["estado"] == "cobrado"
    avisos.fcm.correr()

    (correo,) = avisos.brevo.enviados
    assert "Cobramos tu pedido" in correo["subject"]
    titulos = [(n["tipo"], n["titulo"]) for n in client.get("/api/v1/notificaciones", headers=cliente_headers).json()]
    assert titulos == [("pedido_diferido", "Cobramos tu pedido")]
    assert _avisos_de_compra(client, cliente_headers) == []


# ---- un SAVEPOINT revertido no avisa; el cinturón evita repetir ----


def test_un_savepoint_revertido_no_deja_notificacion_ni_manda_correo(client, db_session, cliente_headers, contexto, avisos):
    venta = _venta_digital(client, contexto, cliente_headers)
    db_session.commit()

    savepoint = db_session.begin_nested()
    confirmar_venta(db_session, venta["id"], commit=False)
    savepoint.rollback()  # la operación se deshace; la transacción de afuera sigue y confirma
    db_session.commit()
    avisos.fcm.correr()  # el correo anotado se revalida: la venta sigue pendiente de pago

    assert avisos.brevo.enviados == []
    assert _avisos_de_compra(client, cliente_headers) == []
    assert client.get(f"/api/v1/ventas/{venta['id']}/comprobante", headers=cliente_headers).json()["estado"] == "pendiente_pago"


def test_si_ya_existe_el_aviso_de_esa_venta_no_se_crea_otro_ni_se_manda_otro_correo(
    client, db_session, cliente_headers, contexto, avisos
):
    venta = _venta_digital(client, contexto, cliente_headers)
    usuario_id = client.get("/api/v1/auth/yo", headers=cliente_headers).json()["id"]
    plataforma_politicas.crear_notificacion(db_session, usuario_id, "Compra confirmada", "ya avisada", TIPO, venta["id"])
    avisos.fcm.correr()
    inicio = _iniciar(client, cliente_headers, venta)

    assert _webhook(client, inicio["pago"]["referencia_externa"]).status_code == 200
    avisos.fcm.correr()

    assert len(_avisos_de_compra(client, cliente_headers)) == 1
    assert avisos.brevo.enviados == []


# ---- fallos de los servicios no afectan la venta ----


def test_con_brevo_caido_la_venta_queda_pagada_y_la_notificacion_existe(client, cliente_headers, contexto, avisos):
    avisos.brevo.caido = True
    venta = _venta_digital(client, contexto, cliente_headers)
    id_transaccion = _iniciar(client, cliente_headers, venta)["pago"]["referencia_externa"]

    assert _webhook(client, id_transaccion).status_code == 200
    avisos.fcm.correr()  # no lanza

    assert avisos.brevo.enviados == []
    assert len(_avisos_de_compra(client, cliente_headers)) == 1
    assert client.get(f"/api/v1/ventas/{venta['id']}/comprobante", headers=cliente_headers).json()["estado"] == "pagada"


def test_sin_brevo_configurado_hay_notificacion_pero_no_se_programa_correo(client, cliente_headers, contexto, monkeypatch, db_session):
    fcm = SimuladorFCM(monkeypatch, db_session)
    brevo = SimuladorBrevo(monkeypatch, configurado=False)
    venta = _venta_digital(client, contexto, cliente_headers)
    id_transaccion = _iniciar(client, cliente_headers, venta)["pago"]["referencia_externa"]

    assert _webhook(client, id_transaccion).status_code == 200

    assert len(fcm.programados) == 1  # solo el push: el correo ni siquiera se anota
    fcm.correr()
    assert brevo.enviados == []
    assert len(_avisos_de_compra(client, cliente_headers)) == 1


def test_con_fcm_caido_el_aviso_y_el_correo_igual_se_crean(client, cliente_headers, contexto, avisos):
    _registrar_telefono(client, cliente_headers)
    avisos.fcm.caido = True
    venta = _venta_digital(client, contexto, cliente_headers)
    id_transaccion = _iniciar(client, cliente_headers, venta)["pago"]["referencia_externa"]

    assert _webhook(client, id_transaccion).status_code == 200
    avisos.fcm.correr()

    assert len(_avisos_de_compra(client, cliente_headers)) == 1
    assert len(avisos.brevo.enviados) == 1


# ---- el correo ----


def test_el_correo_trae_codigo_prendas_importes_y_el_enlace_al_comprobante_sin_qr_ni_adjuntos(
    client, cliente_headers, contexto, avisos
):
    venta = _venta_digital(client, contexto, cliente_headers, cantidad=2)
    id_transaccion = _iniciar(client, cliente_headers, venta)["pago"]["referencia_externa"]
    _webhook(client, id_transaccion)
    avisos.fcm.correr()

    (correo,) = avisos.brevo.enviados
    enlace = f"http://localhost:4200/t/fashionstore/mis-compras/{venta['id']}"
    assert correo["subject"] == f"Compra confirmada {venta['codigo']} · FashionStore"
    for texto in (venta["codigo"], "Camisa pago · talla M · Azul Pago", "(x2)", "Bs 200.00", "Sucursal Pago"):
        assert texto in correo["htmlContent"] and texto in correo["textContent"]
    assert f'href="{enlace}"' in correo["htmlContent"] and "Ver mi comprobante" in correo["htmlContent"]
    assert enlace in correo["textContent"]
    assert "<img" not in correo["htmlContent"] and "attachment" not in correo and "data:image" not in correo["htmlContent"]


def _correo_de_prueba(**cambios) -> object:
    datos = dict(
        para_email="ana@example.com",
        nombre="Ana",
        nombre_empresa="Moda & Co",
        codigo_empresa="moda-co",
        venta_id=7,
        codigo_venta="VTA-1",
        fecha=__import__("datetime").datetime(2026, 11, 7, 3, 30),
        sucursal="Centro",
        lineas=[("Polera · talla M · Azul", 1)],
        subtotal="100.00",
        descuento="0.00",
        costo_envio="0.00",
        total="100.00",
    )
    datos.update(cambios)
    return construir_correo_compra_confirmada(**datos)


def test_el_correo_escapa_todo_dato_variable_y_el_enlace():
    mensaje = _correo_de_prueba(
        nombre="<b>Ana</b>",
        nombre_empresa='Moda "&" <Co>',
        codigo_empresa='mo"da/co?x=1',
        sucursal="<script>alert(1)</script>",
        lineas=[("<img src=x onerror=1> · talla M", 1)],
    )

    assert "<script>" not in mensaje.html and "<img" not in mensaje.html and "<b>Ana" not in mensaje.html
    assert "&lt;script&gt;" in mensaje.html and "&lt;img" in mensaje.html
    assert 'href="http://localhost:4200/t/mo%22da%2Fco%3Fx%3D1/mis-compras/7"' in mensaje.html


def test_el_correo_muestra_descuento_y_envio_solo_si_los_hay_y_la_fecha_en_hora_de_bolivia():
    sin = _correo_de_prueba()
    con = _correo_de_prueba(descuento="10.00", costo_envio="15.00", total="105.00")

    assert "Descuento" not in sin.texto and "Envío" not in sin.texto
    assert "Descuento: - Bs 10.00" in con.texto and "Envío: Bs 15.00" in con.texto and "Total: Bs 105.00" in con.texto
    assert "06/11/2026 23:30" in sin.texto  # 03:30 UTC del 7 son las 23:30 del 6 en Bolivia (UTC-4)


# ---- el comprobante trae el enlace del QR ----


def test_el_comprobante_trae_el_enlace_de_verificacion_y_las_demas_respuestas_no(client, cliente_headers, contexto):
    venta = _venta_digital(client, contexto, cliente_headers)

    comprobante = client.get(f"/api/v1/ventas/{venta['id']}/comprobante", headers=cliente_headers).json()
    mis_compras = client.get("/api/v1/ventas/mis-compras", headers=cliente_headers).json()

    assert comprobante["enlace_verificacion"] == f"http://localhost:4200/caja?venta={venta['codigo']}"
    assert venta["enlace_verificacion"] is None and mis_compras[0]["enlace_verificacion"] is None


def test_el_enlace_de_verificacion_no_duplica_la_barra_final(monkeypatch):
    monkeypatch.setattr(get_settings(), "frontend_public_url", "https://fashionstore.example.com/")

    assert construir_enlace_verificacion("VTA-9") == "https://fashionstore.example.com/caja?venta=VTA-9"
