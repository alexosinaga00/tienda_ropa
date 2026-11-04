"""CU-17, Etapa 2: el CLIENTE solicita el cambio de talla o color de su compra y el personal de la sucursal lo
aprueba o lo rechaza cuando el cliente trae la prenda.

La solicitud es una `devolucion` en estado 'pendiente': no mueve stock ni reserva la prenda nueva. Al aprobar se
reutiliza el movimiento de stock del cambio registrado en la Caja (una transacción; sin stock, 409 y sigue
pendiente). El plazo se exige al solicitar y, al aprobar, con una tolerancia de horas. Una solicitud que nadie atiende
vence sola. Brevo es simulado: ninguna prueba sale a la red."""

import datetime as dt

import pytest
from sqlalchemy import select

from app.comercial.models import Devolucion, Venta
from app.comercial.politicas import vencer_solicitudes_cambio, vencer_solicitudes_de_todas_las_empresas
from app.core.config import get_settings
from app.core.tenant import fijar_empresa
from app.plataforma.models import Cliente, Usuario
from tests.comercial.test_cambio_talla import (  # noqa: F401  (los fixtures se reutilizan)
    AHORA,
    VENDIDAS,
    _agotar,
    _fechar_hoy,
    _fisico,
    _vender,
    ctx,
    reloj,
    venta_con_cliente,
)
from tests.conftest import crear_cajero
from tests.correo_simulado import SimuladorBrevo

URL = "/api/v1/solicitudes-cambio"


def _pedir(client, cliente_headers, venta: dict, *, cantidad=1, nueva, motivo="Me queda grande"):
    return client.post(
        URL,
        json={
            "venta_id": venta["id"],
            "motivo": motivo,
            "detalle": [{"venta_detalle_id": venta["detalle"][0]["id"], "cantidad": cantidad, "variante_nueva_id": nueva}],
        },
        headers=cliente_headers,
    )


def _solicitar(client, cliente_headers, venta: dict, nueva: int, cantidad=1) -> dict:
    respuesta = _pedir(client, cliente_headers, venta, nueva=nueva, cantidad=cantidad)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _aprobar(client, ctx, solicitud_id: int):
    return client.post(f"{URL}/{solicitud_id}/aprobar", headers=ctx["cajero_headers"])


def _rechazar(client, ctx, solicitud_id: int, motivo="La prenda está usada"):
    return client.post(f"{URL}/{solicitud_id}/rechazar", json={"motivo": motivo}, headers=ctx["cajero_headers"])


# ---- el cliente solicita ----


def test_el_cliente_solicita_y_queda_pendiente_sin_mover_stock(client, db_session, ctx, venta_con_cliente, cliente_headers):
    antes_m, antes_l = _fisico(db_session, ctx, ctx["m"]), _fisico(db_session, ctx, ctx["l"])

    respuesta = _pedir(client, cliente_headers, venta_con_cliente, nueva=ctx["l"], cantidad=2)

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "pendiente"
    assert cuerpo["codigo"].startswith("SOL-")
    assert cuerpo["venta_id"] == venta_con_cliente["id"]
    assert cuerpo["sucursal_id"] == ctx["sucursal_id"]
    assert cuerpo["motivo"] == "Me queda grande"
    assert cuerpo["cliente_nombre"] == "Cli Ente"
    linea = cuerpo["detalle"][0]
    assert linea["cantidad"] == 2
    assert linea["prenda_devuelta"] == "Polera Cambio · talla M · Azul Cambio"
    assert linea["prenda_nueva"] == "Polera Cambio · talla L · Azul Cambio"
    assert linea["disponible_nueva"] == 20  # informativo: no se reserva
    # El plazo de la empresa es de 24 h y la tolerancia de 48 h desde la venta (hace 1 h).
    assert dt.datetime.fromisoformat(cuerpo["atender_hasta"].replace("Z", "+00:00")).replace(tzinfo=None) == (
        AHORA - dt.timedelta(hours=1) + dt.timedelta(hours=24 + 48)
    )
    assert _fisico(db_session, ctx, ctx["m"]) == antes_m
    assert _fisico(db_session, ctx, ctx["l"]) == antes_l


def test_una_solicitud_pendiente_no_cuenta_como_devuelta(client, ctx, venta_con_cliente, cliente_headers):
    _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"], cantidad=2)

    compras = client.get("/api/v1/ventas/mis-compras", headers=cliente_headers).json()

    assert next(v for v in compras if v["id"] == venta_con_cliente["id"])["unidades_devueltas"] == 0
    # El cajero todavía puede registrar una devolución en el acto sobre esa línea.
    directa = client.post(
        "/api/v1/devoluciones",
        json={"venta_id": venta_con_cliente["id"], "detalle": [{"venta_detalle_id": venta_con_cliente["detalle"][0]["id"], "cantidad": 1}]},
        headers=ctx["cajero_headers"],
    )
    assert directa.status_code == 201, directa.text


def test_la_solicitud_manda_un_aviso_con_la_sucursal(client, ctx, venta_con_cliente, cliente_headers, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch)

    cuerpo = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"])

    assert cuerpo["correo_programado"] is True
    assert len(brevo.enviados) == 1
    correo = brevo.ultimo()
    assert correo["to"][0]["email"] == "cliente@example.com"
    assert cuerpo["codigo"] in correo["subject"]
    assert "Sucursal Cambio" in correo["textContent"]
    assert "Quieres: Polera Cambio · talla L · Azul Cambio" in correo["textContent"]


def test_sin_brevo_la_solicitud_se_registra_igual(client, ctx, venta_con_cliente, cliente_headers, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch, configurado=False)

    cuerpo = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"])

    assert cuerpo["correo_programado"] is False
    assert brevo.enviados == []


def test_la_compra_de_otra_persona_se_ve_inexistente(client, db_session, ctx, cliente_headers):
    venta = _vender(client, ctx)  # presencial sin cliente: no es de este cliente
    _fechar_hoy(db_session, venta["id"])

    assert _pedir(client, cliente_headers, venta, nueva=ctx["l"]).status_code == 404


def test_al_solicitar_el_plazo_es_estricto(client, db_session, ctx, venta_con_cliente, cliente_headers):
    # 30 h: dentro de la tolerancia de atención, pero el plazo de 24 h ya pasó.
    db_session.get(Venta, venta_con_cliente["id"]).fecha = AHORA - dt.timedelta(hours=30)
    db_session.commit()

    assert _pedir(client, cliente_headers, venta_con_cliente, nueva=ctx["l"]).status_code == 409


@pytest.mark.parametrize(
    ("nueva", "mensaje"),
    [("m", "es la misma"), ("otro_producto", "mismo producto")],
)
def test_un_cambio_invalido_se_rechaza_al_solicitar(client, ctx, venta_con_cliente, cliente_headers, nueva, mensaje):
    respuesta = _pedir(client, cliente_headers, venta_con_cliente, nueva=ctx[nueva])

    assert respuesta.status_code == 400
    assert mensaje in respuesta.json()["detail"]


def test_una_variante_inexistente_da_404(client, ctx, venta_con_cliente, cliente_headers):
    assert _pedir(client, cliente_headers, venta_con_cliente, nueva=999999).status_code == 404


def test_no_se_pide_mas_de_lo_comprado(client, ctx, venta_con_cliente, cliente_headers):
    assert _pedir(client, cliente_headers, venta_con_cliente, nueva=ctx["l"], cantidad=VENDIDAS + 1).status_code == 400


def test_una_sola_solicitud_pendiente_por_prenda(client, ctx, venta_con_cliente, cliente_headers):
    primera = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"])

    segunda = _pedir(client, cliente_headers, venta_con_cliente, nueva=ctx["l"])

    assert segunda.status_code == 409
    # Al cancelar la primera, la prenda queda libre.
    assert client.post(f"{URL}/{primera['id']}/cancelar", headers=cliente_headers).status_code == 200
    assert _pedir(client, cliente_headers, venta_con_cliente, nueva=ctx["l"]).status_code == 201


def test_lo_ya_devuelto_resta_de_lo_que_se_puede_pedir(client, ctx, venta_con_cliente, cliente_headers):
    directa = client.post(
        "/api/v1/devoluciones",
        json={"venta_id": venta_con_cliente["id"], "detalle": [{"venta_detalle_id": venta_con_cliente["detalle"][0]["id"], "cantidad": VENDIDAS - 1}]},
        headers=ctx["cajero_headers"],
    )
    assert directa.status_code == 201

    assert _pedir(client, cliente_headers, venta_con_cliente, nueva=ctx["l"], cantidad=2).status_code == 400
    assert _pedir(client, cliente_headers, venta_con_cliente, nueva=ctx["l"], cantidad=1).status_code == 201


def test_hay_un_limite_de_solicitudes_por_cuenta(client, db_session, ctx, venta_con_cliente, cliente_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "solicitud_cambio_max_por_ventana", 2)
    for _ in range(2):  # pedir y cancelar cuenta igual: lo que se limita es pedir
        solicitud = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"])
        assert client.post(f"{URL}/{solicitud['id']}/cancelar", headers=cliente_headers).status_code == 200

    respuesta = _pedir(client, cliente_headers, venta_con_cliente, nueva=ctx["l"])

    assert respuesta.status_code == 429
    assert int(respuesta.headers["Retry-After"]) >= 1


def test_una_solicitud_rechazada_por_validacion_no_cuenta_para_el_limite(
    client, ctx, venta_con_cliente, cliente_headers, monkeypatch
):
    monkeypatch.setattr(get_settings(), "solicitud_cambio_max_por_ventana", 1)
    assert _pedir(client, cliente_headers, venta_con_cliente, nueva=ctx["m"]).status_code == 400  # la misma talla

    assert _pedir(client, cliente_headers, venta_con_cliente, nueva=ctx["l"]).status_code == 201


# ---- el personal aprueba ----


def test_aprobar_mueve_el_stock_como_un_cambio_de_la_caja(client, db_session, ctx, venta_con_cliente, cliente_headers):
    solicitud = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"], cantidad=2)
    antes_m, antes_l = _fisico(db_session, ctx, ctx["m"]), _fisico(db_session, ctx, ctx["l"])

    respuesta = _aprobar(client, ctx, solicitud["id"])

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado"] == "aprobada"
    assert _fisico(db_session, ctx, ctx["m"]) == antes_m + 2  # la M devuelta vuelve
    assert _fisico(db_session, ctx, ctx["l"]) == antes_l - 2  # la L sale
    db_session.expire_all()
    fila = db_session.get(Devolucion, solicitud["id"])
    assert fila.estado == "aprobada" and fila.resuelta_por_id is not None and fila.resuelta_en is not None
    assert fila.usuario_id != fila.resuelta_por_id  # pidió el cliente, resolvió el cajero


def test_al_aprobar_el_cliente_recibe_el_comprobante(client, ctx, venta_con_cliente, cliente_headers, monkeypatch):
    solicitud = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"])
    brevo = SimuladorBrevo(monkeypatch)

    respuesta = _aprobar(client, ctx, solicitud["id"])

    assert respuesta.json()["correo_programado"] is True
    assert len(brevo.enviados) == 1
    assert "comprobante de cambio" in brevo.ultimo()["subject"].lower()
    assert "Recibes en su lugar: Polera Cambio · talla L · Azul Cambio" in brevo.ultimo()["textContent"]


def test_una_solicitud_aprobada_cuenta_como_devuelta_y_el_estado_de_la_venta_no_cambia(
    client, ctx, venta_con_cliente, cliente_headers
):
    solicitud = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"], cantidad=2)
    _aprobar(client, ctx, solicitud["id"])

    compras = client.get("/api/v1/ventas/mis-compras", headers=cliente_headers).json()
    venta = next(v for v in compras if v["id"] == venta_con_cliente["id"])

    assert venta["unidades_devueltas"] == 2
    assert venta["estado"] == "pagada"


def test_sin_stock_de_la_talla_nueva_la_aprobacion_da_409_y_sigue_pendiente(
    client, db_session, ctx, venta_con_cliente, cliente_headers, admin_headers
):
    solicitud = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"])
    _agotar(client, ctx, admin_headers, ctx["l"])
    antes_m = _fisico(db_session, ctx, ctx["m"])

    respuesta = _aprobar(client, ctx, solicitud["id"])

    assert respuesta.status_code == 409
    assert "el cambio no se registró" in respuesta.json()["detail"]
    assert _fisico(db_session, ctx, ctx["m"]) == antes_m  # lo devuelto NO reingresó
    db_session.expire_all()
    assert db_session.get(Devolucion, solicitud["id"]).estado == "pendiente"
    # El cajero ve el faltante en la bandeja y puede rechazarla con un motivo.
    pendiente = client.get(f"{URL}/sucursal/{ctx['sucursal_id']}", headers=ctx["cajero_headers"]).json()[0]
    assert pendiente["detalle"][0]["disponible_nueva"] == 0
    assert _rechazar(client, ctx, solicitud["id"], "Sin stock de esa talla").status_code == 200


def test_si_el_precio_cambio_desde_que_se_pidio_la_aprobacion_da_400(
    client, db_session, ctx, venta_con_cliente, cliente_headers, admin_headers
):
    solicitud = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"])
    assert client.put(f"/api/v1/variantes/{ctx['l']}", json={"precio": "130.00"}, headers=admin_headers).status_code == 200

    respuesta = _aprobar(client, ctx, solicitud["id"])

    assert respuesta.status_code == 400
    assert "diferencia de precio" in respuesta.json()["detail"]
    db_session.expire_all()
    assert db_session.get(Devolucion, solicitud["id"]).estado == "pendiente"


def test_al_aprobar_el_plazo_admite_la_tolerancia(client, db_session, ctx, venta_con_cliente, cliente_headers):
    solicitud = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"])
    # El cliente llega a la tienda cuando la venta ya tiene 30 h: el plazo (24 h) pasó, la tolerancia (48 h) no.
    db_session.get(Venta, venta_con_cliente["id"]).fecha = AHORA - dt.timedelta(hours=30)
    db_session.commit()

    assert _aprobar(client, ctx, solicitud["id"]).status_code == 200


def test_pasada_la_tolerancia_no_se_aprueba(client, db_session, ctx, venta_con_cliente, cliente_headers):
    solicitud = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"])
    db_session.get(Venta, venta_con_cliente["id"]).fecha = AHORA - dt.timedelta(hours=80)
    db_session.commit()

    respuesta = _aprobar(client, ctx, solicitud["id"])

    assert respuesta.status_code == 409
    assert "tolerancia" in respuesta.json()["detail"]


def test_una_solicitud_resuelta_no_se_vuelve_a_resolver(client, ctx, venta_con_cliente, cliente_headers):
    solicitud = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"])
    assert _aprobar(client, ctx, solicitud["id"]).status_code == 200

    assert _aprobar(client, ctx, solicitud["id"]).status_code == 409  # ya aprobada: no mueve el stock otra vez
    assert _rechazar(client, ctx, solicitud["id"]).status_code == 409
    assert client.post(f"{URL}/{solicitud['id']}/cancelar", headers=cliente_headers).status_code == 409


def test_el_personal_de_otra_sucursal_no_la_resuelve(client, db_session, ctx, venta_con_cliente, cliente_headers, admin_headers):
    solicitud = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"])
    ciudad = client.post("/api/v1/ciudades", json={"nombre": "Otra Ciudad", "departamento": "La Paz"}, headers=admin_headers).json()
    otra = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-OTRA", "nombre": "Otra Sucursal", "direccion": "Av. 2"},
        headers=admin_headers,
    ).json()["id"]
    ajeno = crear_cajero(client, admin_headers, db_session, sucursal_id=otra, email="ajeno@example.com")

    assert client.post(f"{URL}/{solicitud['id']}/aprobar", headers=ajeno).status_code == 403
    assert client.post(f"{URL}/{solicitud['id']}/rechazar", json={"motivo": "no"}, headers=ajeno).status_code in (403, 422)
    assert client.post(f"{URL}/{solicitud['id']}/rechazar", json={"motivo": "motivo largo"}, headers=ajeno).status_code == 403
    assert client.get(f"{URL}/sucursal/{ctx['sucursal_id']}", headers=ajeno).status_code == 403


def test_el_administrador_puede_resolver_la_de_cualquier_sucursal(client, ctx, venta_con_cliente, cliente_headers, admin_headers):
    solicitud = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"])

    assert client.post(f"{URL}/{solicitud['id']}/aprobar", headers=admin_headers).status_code == 200


# ---- el personal rechaza ----


def test_rechazar_guarda_el_motivo_y_avisa_al_cliente(client, db_session, ctx, venta_con_cliente, cliente_headers, monkeypatch):
    solicitud = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"])
    brevo = SimuladorBrevo(monkeypatch)
    antes_m, antes_l = _fisico(db_session, ctx, ctx["m"]), _fisico(db_session, ctx, ctx["l"])

    respuesta = _rechazar(client, ctx, solicitud["id"], "La prenda llegó usada")

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "rechazada"
    assert cuerpo["motivo_rechazo"] == "La prenda llegó usada"
    assert cuerpo["resuelta_en"] is not None
    assert (_fisico(db_session, ctx, ctx["m"]), _fisico(db_session, ctx, ctx["l"])) == (antes_m, antes_l)
    assert len(brevo.enviados) == 1
    assert "no fue aprobada" in brevo.ultimo()["subject"]
    assert "Motivo: La prenda llegó usada" in brevo.ultimo()["textContent"]
    # Rechazada, la prenda queda libre para pedir otra vez.
    assert _pedir(client, cliente_headers, venta_con_cliente, nueva=ctx["l"]).status_code == 201


def test_rechazar_exige_un_motivo(client, ctx, venta_con_cliente, cliente_headers):
    solicitud = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"])

    assert client.post(f"{URL}/{solicitud['id']}/rechazar", json={}, headers=ctx["cajero_headers"]).status_code == 422
    assert _rechazar(client, ctx, solicitud["id"], "  ").status_code == 422


# ---- el cliente cancela ----


def test_el_cliente_cancela_su_solicitud_pendiente(client, db_session, ctx, venta_con_cliente, cliente_headers):
    solicitud = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"])

    respuesta = client.post(f"{URL}/{solicitud['id']}/cancelar", headers=cliente_headers)

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "cancelada"
    assert _aprobar(client, ctx, solicitud["id"]).status_code == 409  # cancelada: ya no se aprueba


def test_la_solicitud_de_otro_cliente_no_se_cancela(client, ctx, venta_con_cliente, cliente_headers):
    solicitud = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"])
    # Una cuenta de personal (no es quien la pidió) la ve inexistente.
    r = client.post(f"{URL}/{solicitud['id']}/cancelar", headers=ctx["cajero_headers"])
    assert r.status_code in (403, 404)


# ---- listados ----


def test_el_cliente_ve_sus_solicitudes_y_el_cajero_las_pendientes_de_su_sucursal(
    client, ctx, venta_con_cliente, cliente_headers
):
    primera = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"])

    mias = client.get(f"{URL}/mias", headers=cliente_headers).json()
    assert [s["id"] for s in mias] == [primera["id"]]
    assert client.get(f"{URL}/mias?venta_id={venta_con_cliente['id'] + 999}", headers=cliente_headers).json() == []

    bandeja = client.get(f"{URL}/sucursal/{ctx['sucursal_id']}", headers=ctx["cajero_headers"])
    assert bandeja.status_code == 200
    assert [s["id"] for s in bandeja.json()] == [primera["id"]]

    _rechazar(client, ctx, primera["id"])
    assert client.get(f"{URL}/sucursal/{ctx['sucursal_id']}", headers=ctx["cajero_headers"]).json() == []
    todas = client.get(f"{URL}/sucursal/{ctx['sucursal_id']}?estado=todas", headers=ctx["cajero_headers"]).json()
    assert [(s["id"], s["estado"]) for s in todas] == [(primera["id"], "rechazada")]


def test_un_cambio_registrado_en_la_caja_no_aparece_como_solicitud(client, ctx, venta_con_cliente, cliente_headers):
    directa = client.post(
        "/api/v1/devoluciones",
        json={
            "venta_id": venta_con_cliente["id"],
            "detalle": [{"venta_detalle_id": venta_con_cliente["detalle"][0]["id"], "cantidad": 1, "variante_nueva_id": ctx["l"]}],
        },
        headers=ctx["cajero_headers"],
    )
    assert directa.status_code == 201

    assert client.get(f"{URL}/sucursal/{ctx['sucursal_id']}?estado=todas", headers=ctx["cajero_headers"]).json() == []
    assert client.get(f"{URL}/mias", headers=cliente_headers).json() == []
    # Y la respuesta de la devolución ya informa la talla nueva de cada línea.
    assert directa.json()["detalle"][0]["variante_nueva_id"] == ctx["l"]


def test_la_bandeja_ordena_la_mas_antigua_primero(client, db_session, ctx, cliente_headers):
    # Dos ventas del mismo cliente, una solicitud en cada una.
    usuario = db_session.scalar(select(Usuario).where(Usuario.email == "cliente@example.com"))
    cliente = db_session.scalar(select(Cliente).where(Cliente.usuario_id == usuario.id))
    ventas = []
    for _ in range(2):
        venta = _vender(client, ctx, cliente_id=cliente.id)
        _fechar_hoy(db_session, venta["id"])
        ventas.append(venta)
    primera = _solicitar(client, cliente_headers, ventas[0], ctx["l"])
    segunda = _solicitar(client, cliente_headers, ventas[1], ctx["l"])
    db_session.get(Devolucion, primera["id"]).fecha = dt.datetime(2026, 10, 26, 10, 0, 0)
    db_session.get(Devolucion, segunda["id"]).fecha = dt.datetime(2026, 10, 26, 9, 0, 0)
    db_session.commit()

    bandeja = client.get(f"{URL}/sucursal/{ctx['sucursal_id']}", headers=ctx["cajero_headers"]).json()

    assert [s["id"] for s in bandeja] == [segunda["id"], primera["id"]]  # la que lleva más esperando, primero


# ---- vencimiento ----


def test_una_solicitud_que_nadie_atiende_vence_sola(client, db_session, ctx, venta_con_cliente, cliente_headers):
    solicitud = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"])
    assert vencer_solicitudes_cambio(db_session) == 0  # todavía dentro de la tolerancia

    db_session.get(Venta, venta_con_cliente["id"]).fecha = AHORA - dt.timedelta(hours=80)
    db_session.commit()
    assert vencer_solicitudes_cambio(db_session) == 1

    db_session.expire_all()
    fila = db_session.get(Devolucion, solicitud["id"])
    assert fila.estado == "vencida" and fila.resuelta_en is not None and fila.resuelta_por_id is None
    assert _aprobar(client, ctx, solicitud["id"]).status_code == 409  # vencida: ya no se aprueba
    assert vencer_solicitudes_cambio(db_session) == 0  # idempotente


def test_el_vencimiento_recorre_todas_las_empresas_y_no_toca_las_resueltas(
    client, db_session, ctx, venta_con_cliente, cliente_headers
):
    solicitud = _solicitar(client, cliente_headers, venta_con_cliente, ctx["l"])
    assert _rechazar(client, ctx, solicitud["id"]).status_code == 200
    db_session.get(Venta, venta_con_cliente["id"]).fecha = AHORA - dt.timedelta(hours=80)
    db_session.commit()
    empresa_id = db_session.get(Venta, venta_con_cliente["id"]).empresa_id

    try:
        assert vencer_solicitudes_de_todas_las_empresas(db_session) == 0
    finally:
        fijar_empresa(db_session, empresa_id)  # la tarea deja la sesión sin empresa

    db_session.expire_all()
    assert db_session.get(Devolucion, solicitud["id"]).estado == "rechazada"
