"""CU-17 y CU-18: reembolsos, el dinero que se le devuelve a quien compró.

Una devolución SIN cambio de prenda y anular un pago crean un `reembolso` con el método del pago original. En efectivo y
en los métodos de la tienda (qr, tarjeta, transferencia) el dinero sale en el acto; con PayPal lo devuelve la pasarela
(simulada: `tests/paypal_simulado.py`, con idempotencia por `PayPal-Request-Id`). Un cambio de talla o color no mueve dinero.
Al completarse, el comprador recibe una notificación (con su push) y un correo de constancia (Brevo simulado). Ninguna
prueba sale a la red."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.comercial.models import EstadoPago, Pago, Reembolso, Venta
from app.comercial.politicas import crear_reembolso, pago_aprobado_de_venta
from app.core.exceptions import ErrorFuncional
from app.plataforma.models import Cliente, Notificacion, Usuario
from tests.comercial.test_cambio_talla import (  # noqa: F401  (fixtures y ayudas del contexto de cambio de talla)
    AHORA,
    VENDIDAS,
    _devolver,
    _fechar_hoy,
    _vender,
    ctx,
    reloj,
    venta_con_cliente,
)
from tests.correo_simulado import SimuladorBrevo
from tests.paypal_simulado import SimuladorPayPal

API = "/api/v1"


@pytest.fixture()
def pp(monkeypatch) -> SimuladorPayPal:
    return SimuladorPayPal(monkeypatch)


def _cobrar_qr(client, ctx, cliente_id=None) -> tuple[dict, int]:
    """Una venta presencial de VENDIDAS prendas (4 x Bs 100) cobrada con QR en la Caja. Devuelve (venta, id del pago)."""
    cuerpo = {"sucursal_id": ctx["sucursal_id"], "detalle": [{"variante_id": ctx["m"], "cantidad": VENDIDAS}]}
    if cliente_id is not None:
        cuerpo["cliente_id"] = cliente_id
    venta = client.post(f"{API}/ventas/presencial", json=cuerpo, headers=ctx["cajero_headers"])
    assert venta.status_code == 201, venta.text
    pago = client.post(
        f"{API}/pagos/caja", json={"venta_id": venta.json()["id"], "metodo_pago": "qr"}, headers=ctx["cajero_headers"]
    )
    assert pago.status_code == 201, pago.text
    return venta.json(), pago.json()["pago"]["id"]


def _cobrar_paypal(client, db_session, ctx, pp, cliente_id=None) -> tuple[dict, int]:
    """Lo mismo, pero pagado con PayPal: se inicia el pago, el comprador aprueba y la consulta de estado captura."""
    cuerpo = {"sucursal_id": ctx["sucursal_id"], "detalle": [{"variante_id": ctx["m"], "cantidad": VENDIDAS}]}
    if cliente_id is not None:
        cuerpo["cliente_id"] = cliente_id
    venta = client.post(f"{API}/ventas/presencial", json=cuerpo, headers=ctx["cajero_headers"])
    assert venta.status_code == 201, venta.text
    iniciado = client.post(
        f"{API}/pagos/iniciar", json={"venta_id": venta.json()["id"], "metodo_pago": "paypal"}, headers=ctx["cajero_headers"]
    )
    assert iniciado.status_code == 201, iniciado.text
    pago_id = iniciado.json()["pago"]["id"]
    pp.aprobar()
    estado = client.get(f"{API}/pagos/{pago_id}/estado", headers=ctx["cajero_headers"])
    assert estado.json()["estado"] == "aprobado", estado.text
    _fechar_hoy(db_session, venta.json()["id"])
    return venta.json(), pago_id


def _cliente_id(db_session) -> int:
    usuario = db_session.scalar(select(Usuario).where(Usuario.email == "cliente@example.com"))
    return db_session.scalar(select(Cliente).where(Cliente.usuario_id == usuario.id)).id


def _reembolsos_de(db_session, venta_id: int) -> list[Reembolso]:
    db_session.expire_all()
    return list(db_session.scalars(select(Reembolso).where(Reembolso.venta_id == venta_id).order_by(Reembolso.id)))


def _estado_del_pago(db_session, pago_id: int) -> str:
    db_session.expire_all()
    pago = db_session.get(Pago, pago_id)
    return db_session.get(EstadoPago, pago.estado_id).codigo


def _avisos_de_reembolso(db_session) -> list[Notificacion]:
    db_session.expire_all()
    return list(db_session.scalars(select(Notificacion).where(Notificacion.tipo == "reembolso")))


# ---- una devolución sin cambio devuelve el dinero; un cambio de talla no ----------------------------------------------


def test_una_devolucion_simple_con_qr_deja_el_reembolso_hecho(client, db_session, ctx):
    venta, pago_id = _cobrar_qr(client, ctx)
    _fechar_hoy(db_session, venta["id"])

    respuesta = _devolver(client, ctx, venta, cantidad=1)

    assert respuesta.status_code == 201, respuesta.text
    (reembolso,) = respuesta.json()["reembolsos"]
    assert reembolso["monto"] == "100.00" and reembolso["metodo"] == "qr" and reembolso["estado"] == "reembolsado"
    assert reembolso["monto_usd"] is None and reembolso["completado_en"].endswith("Z")
    assert reembolso["devolucion_id"] == respuesta.json()["id"] and reembolso["pago_id"] == pago_id
    # Solo se devolvió una parte: el pago sigue aprobado.
    assert _estado_del_pago(db_session, pago_id) == "aprobado"
    listado = client.get(f"{API}/ventas/{venta['id']}/reembolsos", headers=ctx["cajero_headers"])
    assert [r["id"] for r in listado.json()] == [reembolso["id"]]


def test_un_cambio_de_talla_no_mueve_dinero(client, db_session, ctx):
    venta, _pago = _cobrar_qr(client, ctx)
    _fechar_hoy(db_session, venta["id"])

    respuesta = _devolver(client, ctx, venta, cantidad=2, nueva=ctx["l"])

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["reembolsos"] == []
    assert _reembolsos_de(db_session, venta["id"]) == []


def test_devolver_todo_deja_el_pago_reembolsado_y_no_se_puede_devolver_mas(client, db_session, ctx):
    venta, pago_id = _cobrar_qr(client, ctx)
    _fechar_hoy(db_session, venta["id"])

    assert _devolver(client, ctx, venta, cantidad=3).status_code == 201
    assert _estado_del_pago(db_session, pago_id) == "aprobado"
    ultima = _devolver(client, ctx, venta, cantidad=1)

    assert ultima.status_code == 201, ultima.text
    assert [Decimal(r.monto) for r in _reembolsos_de(db_session, venta["id"])] == [Decimal("300.00"), Decimal("100.00")]
    assert _estado_del_pago(db_session, pago_id) == "reembolsado"  # ya se devolvió todo lo pagado
    assert _devolver(client, ctx, venta, cantidad=1).status_code == 400  # y no hay más prendas que devolver


def test_el_reembolso_nunca_pasa_de_lo_pagado(client, db_session, ctx):
    venta, pago_id = _cobrar_qr(client, ctx)
    pago = db_session.get(Pago, pago_id)
    venta_orm = db_session.get(Venta, venta["id"])
    crear_reembolso(db_session, venta=venta_orm, pago=pago, monto=Decimal("300"), usuario_id=1)

    with pytest.raises(ErrorFuncional) as error:
        crear_reembolso(db_session, venta=venta_orm, pago=pago, monto=Decimal("100.01"), usuario_id=1)

    assert error.value.codigo == "reembolso_supera_lo_pagado" and error.value.status_code == 409
    assert error.value.contexto["restante"] == "100.00"


# ---- avisos al comprador: notificación + correo de constancia ---------------------------------------------------------


def test_el_reembolso_avisa_al_comprador_con_notificacion_y_correo(client, db_session, ctx, cliente_headers, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch)
    venta, _pago = _cobrar_qr(client, ctx, cliente_id=_cliente_id(db_session))
    _fechar_hoy(db_session, venta["id"])

    respuesta = _devolver(client, ctx, venta, cantidad=2)

    assert respuesta.status_code == 201, respuesta.text
    (aviso,) = _avisos_de_reembolso(db_session)
    assert aviso.titulo == "Te devolvimos tu dinero" and aviso.referencia_id == venta["id"]
    assert "Bs 200.00" in aviso.mensaje and venta["codigo"] in aviso.mensaje and "por QR" in aviso.mensaje
    # Dos correos: el comprobante de la devolución y la constancia del reembolso.
    constancia = next(c for c in brevo.enviados if "te devolvimos tu dinero" in c["subject"].lower())
    assert constancia["to"][0]["email"] == "cliente@example.com"
    assert venta["codigo"] in constancia["subject"]
    texto = constancia["textContent"]
    assert "Monto devuelto: Bs 200.00" in texto and "Cómo: por QR" in texto and respuesta.json()["codigo"] in texto
    assert "constancia de tu reembolso" in texto


def test_sin_cliente_no_hay_aviso_pero_el_reembolso_queda(client, db_session, ctx, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch)
    venta, _pago = _cobrar_qr(client, ctx)  # presencial sin cuenta
    _fechar_hoy(db_session, venta["id"])

    respuesta = _devolver(client, ctx, venta, cantidad=1)

    assert respuesta.status_code == 201
    assert respuesta.json()["reembolsos"][0]["estado"] == "reembolsado"
    assert _avisos_de_reembolso(db_session) == []
    assert brevo.enviados == []


def test_sin_brevo_el_reembolso_funciona_igual_y_deja_la_notificacion(
    client, db_session, ctx, cliente_headers, monkeypatch
):
    SimuladorBrevo(monkeypatch, configurado=False)
    venta, _pago = _cobrar_qr(client, ctx, cliente_id=_cliente_id(db_session))
    _fechar_hoy(db_session, venta["id"])

    respuesta = _devolver(client, ctx, venta, cantidad=1)

    assert respuesta.status_code == 201
    assert len(_avisos_de_reembolso(db_session)) == 1


# ---- anular un pago devuelve el dinero de verdad -----------------------------------------------------------------------


def test_anular_un_pago_en_la_tienda_devuelve_todo_y_deja_el_pago_reembolsado(client, db_session, ctx, admin_headers):
    venta, pago_id = _cobrar_qr(client, ctx)

    anulado = client.post(f"{API}/pagos/{pago_id}/anular", headers=admin_headers)

    assert anulado.status_code == 200, anulado.text
    assert anulado.json()["estado"] == "reembolsado"
    (reembolso,) = _reembolsos_de(db_session, venta["id"])
    assert Decimal(reembolso.monto) == Decimal("400.00") and reembolso.estado == "reembolsado" and reembolso.devolucion_id is None
    assert client.post(f"{API}/pagos/{pago_id}/anular", headers=admin_headers).status_code == 409  # no se devuelve dos veces


def test_anular_descuenta_lo_que_ya_se_devolvio_en_devoluciones(client, db_session, ctx, admin_headers):
    venta, pago_id = _cobrar_qr(client, ctx)
    _fechar_hoy(db_session, venta["id"])
    assert _devolver(client, ctx, venta, cantidad=1).status_code == 201  # Bs 100 ya devueltos

    anulado = client.post(f"{API}/pagos/{pago_id}/anular", headers=admin_headers)

    assert anulado.status_code == 200, anulado.text
    assert [Decimal(r.monto) for r in _reembolsos_de(db_session, venta["id"])] == [Decimal("100.00"), Decimal("300.00")]
    assert anulado.json()["estado"] == "reembolsado"


# ---- PayPal: el reembolso lo hace la pasarela (idempotente, en dólares) ------------------------------------------------


def test_una_devolucion_pagada_con_paypal_reembolsa_en_dolares_proporcionales(client, db_session, ctx, pp):
    venta, pago_id = _cobrar_paypal(client, db_session, ctx, pp)

    respuesta = _devolver(client, ctx, venta, cantidad=1)

    assert respuesta.status_code == 201, respuesta.text
    (reembolso,) = respuesta.json()["reembolsos"]
    assert reembolso["estado"] == "reembolsado" and reembolso["metodo"] == "paypal"
    assert reembolso["monto"] == "100.00" and reembolso["monto_usd"] == "14.37"  # 57.47 USD cobrados x 100 / 400
    assert reembolso["referencia_externa"].startswith("REF-SIM-")
    assert pp.reembolsos_hechos == 1
    assert pp.cuerpos_de_reembolso[0]["amount"] == {"currency_code": "USD", "value": "14.37"}
    clave = pp.cabeceras_de_reembolso[0]["paypal-request-id"]
    assert clave == f"reembolso-{db_session.get(Pago, pago_id).empresa_id}-{reembolso['id']}"


def test_el_ultimo_reembolso_de_un_pago_paypal_se_lleva_el_resto_en_dolares(client, db_session, ctx, pp):
    venta, _pago = _cobrar_paypal(client, db_session, ctx, pp)
    for cantidad in (1, 1, 2):
        assert _devolver(client, ctx, venta, cantidad=cantidad).status_code == 201

    devuelto = sum(Decimal(c["amount"]["value"]) for c in pp.cuerpos_de_reembolso)
    assert devuelto == Decimal("57.47")  # exactamente lo cobrado: sin centavos perdidos por el redondeo


def test_si_paypal_no_responde_el_reembolso_queda_pendiente_y_se_reintenta(
    client, db_session, ctx, pp, cliente_headers, monkeypatch
):
    brevo = SimuladorBrevo(monkeypatch)
    venta, _pago = _cobrar_paypal(client, db_session, ctx, pp, cliente_id=_cliente_id(db_session))
    pp.caer_en = {"reembolsar"}

    respuesta = _devolver(client, ctx, venta, cantidad=1)

    assert respuesta.status_code == 201, respuesta.text  # la devolución no se deshace
    (reembolso,) = respuesta.json()["reembolsos"]
    assert reembolso["estado"] == "pendiente" and reembolso["motivo_fallo"] == "sin_respuesta"
    assert _avisos_de_reembolso(db_session) == []  # todavía no se devolvió nada: no se avisa
    assert not any("te devolvimos" in c["subject"].lower() for c in brevo.enviados)

    pp.caer_en = set()
    reintento = client.post(f"{API}/reembolsos/{reembolso['id']}/reintentar", headers=ctx["cajero_headers"])

    assert reintento.status_code == 200, reintento.text
    assert reintento.json()["estado"] == "reembolsado" and reintento.json()["motivo_fallo"] is None
    assert pp.reembolsos_hechos == 1
    assert len(_avisos_de_reembolso(db_session)) == 1
    assert any("te devolvimos" in c["subject"].lower() for c in brevo.enviados)
    again = client.post(f"{API}/reembolsos/{reembolso['id']}/reintentar", headers=ctx["cajero_headers"])
    assert again.status_code == 409  # ya se hizo


def test_si_paypal_rechaza_el_reembolso_queda_fallido_sin_avisar_al_cliente(
    client, db_session, ctx, pp, cliente_headers, monkeypatch
):
    brevo = SimuladorBrevo(monkeypatch)
    venta, _pago = _cobrar_paypal(client, db_session, ctx, pp, cliente_id=_cliente_id(db_session))
    pp.rechazar_reembolso = "TRANSACTION_REFUSED"

    respuesta = _devolver(client, ctx, venta, cantidad=1)

    assert respuesta.status_code == 201, respuesta.text
    (reembolso,) = respuesta.json()["reembolsos"]
    assert reembolso["estado"] == "fallido" and reembolso["motivo_fallo"] == "rechazado_por_paypal"
    assert _avisos_de_reembolso(db_session) == []
    assert not any("te devolvimos" in c["subject"].lower() for c in brevo.enviados)

    pp.rechazar_reembolso = None
    reintento = client.post(f"{API}/reembolsos/{reembolso['id']}/reintentar", headers=ctx["cajero_headers"])
    assert reintento.status_code == 200, reintento.text
    assert reintento.json()["estado"] == "reembolsado" and pp.reembolsos_hechos == 1


def test_si_la_respuesta_de_paypal_se_pierde_el_reintento_no_devuelve_el_dinero_dos_veces(client, db_session, ctx, pp):
    venta, _pago = _cobrar_paypal(client, db_session, ctx, pp)
    pp.perder_respuestas_de_reembolso = 1  # PayPal SÍ devuelve, pero la respuesta no llega

    respuesta = _devolver(client, ctx, venta, cantidad=1)

    (reembolso,) = respuesta.json()["reembolsos"]
    assert reembolso["estado"] == "pendiente" and pp.reembolsos_hechos == 1
    reintento = client.post(f"{API}/reembolsos/{reembolso['id']}/reintentar", headers=ctx["cajero_headers"])
    assert reintento.status_code == 200 and reintento.json()["estado"] == "reembolsado"
    assert pp.reembolsos_hechos == 1  # misma clave de idempotencia: PayPal devolvió la respuesta original


def test_un_reembolso_pending_de_paypal_sigue_pendiente_con_su_referencia(client, db_session, ctx, pp):
    venta, _pago = _cobrar_paypal(client, db_session, ctx, pp)
    pp.estado_reembolso = "PENDING"

    respuesta = _devolver(client, ctx, venta, cantidad=1)

    (reembolso,) = respuesta.json()["reembolsos"]
    assert reembolso["estado"] == "pendiente" and reembolso["referencia_externa"].startswith("REF-SIM-")
    assert reembolso["completado_en"] is None


def test_anular_un_pago_de_paypal_reembolsa_todo_y_solo_entonces_queda_reembolsado(
    client, db_session, ctx, pp, admin_headers
):
    venta, pago_id = _cobrar_paypal(client, db_session, ctx, pp)
    pp.caer_en = {"reembolsar"}

    anulado = client.post(f"{API}/pagos/{pago_id}/anular", headers=admin_headers)

    assert anulado.status_code == 200, anulado.text
    assert anulado.json()["estado"] == "aprobado"  # el dinero todavía no salió: no se dice que sí
    (reembolso,) = _reembolsos_de(db_session, venta["id"])
    assert reembolso.estado == "pendiente" and Decimal(reembolso.monto) == Decimal("400.00")

    pp.caer_en = set()
    assert client.post(f"{API}/reembolsos/{reembolso.id}/reintentar", headers=admin_headers).status_code == 200
    assert _estado_del_pago(db_session, pago_id) == "reembolsado"
    assert pp.monto_reembolsado["CAP-" + pp.ultima_orden()] == Decimal("57.47")


# ---- la solicitud del cliente: devolver y recibir su dinero -------------------------------------------------------------


def test_el_cliente_pide_devolver_y_el_personal_aprueba_y_se_le_reembolsa(
    client, db_session, ctx, cliente_headers, monkeypatch
):
    brevo = SimuladorBrevo(monkeypatch)
    cliente = _cliente_id(db_session)
    venta, _pago = _cobrar_qr(client, ctx, cliente_id=cliente)
    _fechar_hoy(db_session, venta["id"])

    solicitud = client.post(
        f"{API}/solicitudes-cambio",
        json={"venta_id": venta["id"], "detalle": [{"venta_detalle_id": venta["detalle"][0]["id"], "cantidad": 2}]},
        headers=cliente_headers,
    )

    assert solicitud.status_code == 201, solicitud.text
    assert solicitud.json()["estado"] == "pendiente" and solicitud.json()["detalle"][0]["variante_nueva_id"] is None
    assert any("solicitud de devolución" in c["subject"].lower() for c in brevo.enviados)
    assert _reembolsos_de(db_session, venta["id"]) == []  # nada se devuelve hasta que el personal revisa la prenda

    aprobada = client.post(f"{API}/solicitudes-cambio/{solicitud.json()['id']}/aprobar", headers=ctx["cajero_headers"])

    assert aprobada.status_code == 200, aprobada.text
    assert aprobada.json()["estado"] == "aprobada"
    (reembolso,) = aprobada.json()["reembolsos"]
    assert reembolso["monto"] == "200.00" and reembolso["estado"] == "reembolsado"
    assert len(_avisos_de_reembolso(db_session)) == 1


def test_pago_aprobado_de_venta_solo_cuenta_pagos_aprobados(client, db_session, ctx):
    venta, pago_id = _cobrar_qr(client, ctx)

    pago = pago_aprobado_de_venta(db_session, db_session.get(Venta, venta["id"]))

    assert pago is not None and pago.id == pago_id
