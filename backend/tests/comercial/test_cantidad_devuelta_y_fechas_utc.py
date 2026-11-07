"""Dos contratos del API de ventas.

1. `detalle[].cantidad_devuelta`: cada línea de la venta dice cuántas unidades ya se devolvieron (SOLO devoluciones
   aprobadas: una solicitud pendiente, rechazada o cancelada no cuenta), para que las pantallas no ofrezcan cambiar lo
   que ya volvió. Sale en TODOS los endpoints que devuelven una venta.
2. Todo instante que sale del API es UTC con "Z" (`FechaUTC`); lo que es un valor de negocio (fecha de la visita, horas
   de atención) NO cambia de formato."""

import datetime as dt
import re

import pytest

from app.comercial.models import Venta
from tests.comercial.test_cambio_talla import AHORA, ctx, reloj  # noqa: F401  (los fixtures se reutilizan)
from tests.comercial.test_reservas import _payload_reserva, contexto  # noqa: F401
from tests.comercial.test_solicitud_cambio import _rechazar, _solicitar  # noqa: F401
from sqlalchemy import select

from app.plataforma.models import Cliente, Usuario

INSTANTE_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


@pytest.fixture()
def venta_de_dos_lineas(client, db_session, ctx, cliente_headers):
    """Una venta pagada del cliente de pruebas con dos líneas: 3 de la talla M y 2 de la L (misma polera)."""
    usuario = db_session.scalar(select(Usuario).where(Usuario.email == "cliente@example.com"))
    cliente = db_session.scalar(select(Cliente).where(Cliente.usuario_id == usuario.id))
    venta = client.post(
        "/api/v1/ventas/presencial",
        json={
            "sucursal_id": ctx["sucursal_id"],
            "cliente_id": cliente.id,
            "detalle": [{"variante_id": ctx["m"], "cantidad": 3}, {"variante_id": ctx["l"], "cantidad": 2}],
        },
        headers=ctx["cajero_headers"],
    )
    assert venta.status_code == 201, venta.text
    pago = client.post(
        "/api/v1/pagos/caja", json={"venta_id": venta.json()["id"], "metodo_pago": "qr"}, headers=ctx["cajero_headers"]
    )
    assert pago.status_code in (200, 201), pago.text
    db_session.get(Venta, venta.json()["id"]).fecha = AHORA - dt.timedelta(hours=1)
    db_session.commit()
    return venta.json()


def _devuelto_por_linea(venta: dict) -> dict[int, int]:
    return {linea["variante_id"]: linea["cantidad_devuelta"] for linea in venta["detalle"]}


def _las_cuatro_vistas(client, ctx, cliente_headers, venta_id: int) -> list[dict]:
    """La misma venta como la devuelven el comprobante, Mis compras y el listado de la sucursal."""
    comprobante = client.get(f"/api/v1/ventas/{venta_id}/comprobante", headers=cliente_headers)
    assert comprobante.status_code == 200, comprobante.text
    compras = client.get("/api/v1/ventas/mis-compras", headers=cliente_headers).json()
    sucursal = client.get(f"/api/v1/ventas/sucursal/{ctx['sucursal_id']}", headers=ctx["cajero_headers"]).json()
    return [
        comprobante.json(),
        next(v for v in compras if v["id"] == venta_id),
        next(v for v in sucursal if v["id"] == venta_id),
    ]


# ---- cantidad_devuelta ----


def test_una_venta_recien_hecha_trae_cantidad_devuelta_cero_en_cada_linea(client, ctx, venta_de_dos_lineas, cliente_headers):
    for venta in _las_cuatro_vistas(client, ctx, cliente_headers, venta_de_dos_lineas["id"]):
        assert _devuelto_por_linea(venta) == {ctx["m"]: 0, ctx["l"]: 0}
        assert venta["unidades_devueltas"] == 0


def test_solo_cuenta_lo_aprobado_en_cada_linea_y_en_todos_los_endpoints(
    client, ctx, venta_de_dos_lineas, cliente_headers
):
    linea_m, linea_l = venta_de_dos_lineas["detalle"]
    assert linea_m["variante_id"] == ctx["m"] and linea_l["variante_id"] == ctx["l"]
    # Línea M: dos devoluciones aprobadas (1 + 1). Línea L: una solicitud PENDIENTE del cliente (no cuenta).
    for _ in range(2):
        r = client.post(
            "/api/v1/devoluciones",
            json={"venta_id": venta_de_dos_lineas["id"], "detalle": [{"venta_detalle_id": linea_m["id"], "cantidad": 1}]},
            headers=ctx["cajero_headers"],
        )
        assert r.status_code == 201, r.text
    pendiente = client.post(
        "/api/v1/solicitudes-cambio",
        json={
            "venta_id": venta_de_dos_lineas["id"],
            "detalle": [{"venta_detalle_id": linea_l["id"], "cantidad": 2, "variante_nueva_id": ctx["m"]}],
        },
        headers=cliente_headers,
    )
    assert pendiente.status_code == 201, pendiente.text

    for venta in _las_cuatro_vistas(client, ctx, cliente_headers, venta_de_dos_lineas["id"]):
        assert _devuelto_por_linea(venta) == {ctx["m"]: 2, ctx["l"]: 0}
        assert venta["unidades_devueltas"] == 2  # la suma de las líneas
        assert venta["estado"] == "pagada"


def test_una_solicitud_aprobada_si_cuenta_y_una_rechazada_no(client, ctx, venta_de_dos_lineas, cliente_headers):
    linea_m, linea_l = venta_de_dos_lineas["detalle"]

    def pedir(linea: dict, nueva: int) -> int:
        r = client.post(
            "/api/v1/solicitudes-cambio",
            json={"venta_id": venta_de_dos_lineas["id"], "detalle": [{"venta_detalle_id": linea["id"], "cantidad": 1, "variante_nueva_id": nueva}]},
            headers=cliente_headers,
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    aprobada = pedir(linea_m, ctx["l"])
    rechazada = pedir(linea_l, ctx["m"])
    assert client.post(f"/api/v1/solicitudes-cambio/{aprobada}/aprobar", headers=ctx["cajero_headers"]).status_code == 200
    assert _rechazar(client, ctx, rechazada).status_code == 200

    for venta in _las_cuatro_vistas(client, ctx, cliente_headers, venta_de_dos_lineas["id"]):
        assert _devuelto_por_linea(venta) == {ctx["m"]: 1, ctx["l"]: 0}


def test_una_linea_totalmente_devuelta_dice_cuanto_se_devolvio(client, ctx, venta_de_dos_lineas, cliente_headers):
    linea_l = venta_de_dos_lineas["detalle"][1]
    r = client.post(
        "/api/v1/devoluciones",
        json={"venta_id": venta_de_dos_lineas["id"], "detalle": [{"venta_detalle_id": linea_l["id"], "cantidad": linea_l["cantidad"]}]},
        headers=ctx["cajero_headers"],
    )
    assert r.status_code == 201, r.text

    venta = _las_cuatro_vistas(client, ctx, cliente_headers, venta_de_dos_lineas["id"])[1]
    linea = next(l for l in venta["detalle"] if l["variante_id"] == ctx["l"])
    assert linea["cantidad_devuelta"] == linea["cantidad"] == 2


def test_la_venta_recien_registrada_en_caja_trae_el_campo(client, ctx):
    r = client.post(
        "/api/v1/ventas/presencial",
        json={"sucursal_id": ctx["sucursal_id"], "detalle": [{"variante_id": ctx["m"], "cantidad": 1}]},
        headers=ctx["cajero_headers"],
    )
    assert r.status_code == 201, r.text
    assert [linea["cantidad_devuelta"] for linea in r.json()["detalle"]] == [0]


# ---- fechas en UTC con Z ----


def test_la_fecha_de_la_venta_sale_en_utc_con_z_y_no_se_corre(client, db_session, ctx, venta_de_dos_lineas, cliente_headers):
    # Una compra de las 23:12 en Bolivia (UTC-4) es la 03:12 del día siguiente en UTC: el instante lleva la Z para que
    # el cliente la convierta a su hora local y no la lea como local.
    venta_db = db_session.get(Venta, venta_de_dos_lineas["id"])
    venta_db.fecha = dt.datetime(2026, 11, 7, 3, 12, 0)
    db_session.commit()

    for venta in _las_cuatro_vistas(client, ctx, cliente_headers, venta_de_dos_lineas["id"]):
        assert venta["fecha"] == "2026-11-07T03:12:00Z"


def test_la_fecha_de_la_venta_recien_creada_y_del_pago_llevan_z(client, ctx):
    venta = client.post(
        "/api/v1/ventas/presencial",
        json={"sucursal_id": ctx["sucursal_id"], "detalle": [{"variante_id": ctx["m"], "cantidad": 1}]},
        headers=ctx["cajero_headers"],
    )
    assert INSTANTE_UTC.match(venta.json()["fecha"]), venta.json()["fecha"]
    pago = client.post(
        "/api/v1/pagos/caja", json={"venta_id": venta.json()["id"], "metodo_pago": "qr"}, headers=ctx["cajero_headers"]
    )
    assert INSTANTE_UTC.match(pago.json()["pago"]["fecha"]), pago.json()


def test_la_devolucion_lleva_z(client, ctx, venta_de_dos_lineas):
    r = client.post(
        "/api/v1/devoluciones",
        json={"venta_id": venta_de_dos_lineas["id"], "detalle": [{"venta_detalle_id": venta_de_dos_lineas["detalle"][0]["id"], "cantidad": 1}]},
        headers=ctx["cajero_headers"],
    )
    assert INSTANTE_UTC.match(r.json()["fecha"]), r.json()


def test_la_reserva_saca_creado_en_con_z_pero_la_visita_y_las_horas_no_cambian(
    client, admin_headers, cliente_headers, contexto
):
    r = client.post("/api/v1/reservas", json=_payload_reserva(contexto), headers=cliente_headers)
    assert r.status_code == 201, r.text
    reserva = r.json()

    assert INSTANTE_UTC.match(reserva["creado_en"]), reserva["creado_en"]
    assert INSTANTE_UTC.match(reserva["historial"][0]["creado_en"])
    # Valores de negocio: la fecha de la visita y las horas de la sucursal salen como siempre, sin zona.
    assert reserva["fecha_visita"] == contexto["fecha_visita"]
    assert reserva["hora_visita_desde"] == "10:00:00"
    assert reserva["hora_visita_hasta"] == "11:00:00"
    # El vencimiento es "fin de la visita + 24 h" en hora de pared de la sucursal (no un instante real): no lleva Z.
    visita = dt.date.fromisoformat(contexto["fecha_visita"])
    esperado = dt.datetime.combine(visita, dt.time(11, 0)) + dt.timedelta(hours=24)
    assert reserva["fecha_expiracion"] == esperado.isoformat()


def test_los_horarios_de_sucursal_no_cambian(client, admin_headers, contexto):
    horarios = client.get(f"/api/v1/sucursales/{contexto['sucursal_id']}/horarios", headers=admin_headers).json()
    assert horarios[0]["hora_apertura"] == "08:00:00"
    assert horarios[0]["hora_cierre"] == "20:00:00"


def test_las_notificaciones_y_las_sucursales_llevan_z(client, admin_headers, cliente_headers, contexto):
    reserva = client.post("/api/v1/reservas", json=_payload_reserva(contexto), headers=cliente_headers).json()
    client.put(f"/api/v1/reservas/{reserva['id']}/preparar", headers=admin_headers)

    sucursales = client.get("/api/v1/sucursales", headers=admin_headers).json()
    assert sucursales and all(INSTANTE_UTC.match(s["creado_en"]) for s in sucursales)
    notificaciones = client.get("/api/v1/notificaciones", headers=cliente_headers).json()
    assert notificaciones, "la reserva avisa al personal"
    assert all(INSTANTE_UTC.match(n["creado_en"]) for n in notificaciones)
