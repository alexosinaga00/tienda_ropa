"""`GET /api/v1/inicio/resumen`: lo de HOY (día de Bolivia) para la pantalla de inicio del personal, en una sola llamada y con
las cuentas hechas en la base. Cada sección depende del permiso y del plan; el administrador ve todas las sucursales y
quien no tiene alcance global, la suya."""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.comercial.models import Reserva, Venta
from app.core.tiempo import dia_bolivia
from app.plataforma.repository import UsuarioRepository
from app.plataforma.schemas import UsuarioCrear
from tests.comercial.test_pagos import contexto  # noqa: F401  (el fixture se reutiliza)
from tests.conftest import crear_cajero

RESUMEN = "/api/v1/inicio/resumen"
CLAVE = "claveSegura123"


# ---- ayudas ----


def _resumen(client, headers) -> dict:
    respuesta = client.get(RESUMEN, headers=headers)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _vender(client, headers, sucursal_id, variante_id, *, cantidad=1, cobrar=True) -> dict:
    cuerpo = {"sucursal_id": sucursal_id, "detalle": [{"variante_id": variante_id, "cantidad": cantidad}]}
    venta = client.post("/api/v1/ventas/presencial", json=cuerpo, headers=headers)
    assert venta.status_code == 201, venta.text
    if cobrar:
        pago = client.post(
            "/api/v1/pagos/caja", json={"venta_id": venta.json()["id"], "metodo_pago": "qr"}, headers=headers
        )
        assert pago.status_code == 201, pago.text
    return venta.json()


def _poner_fecha(db_session, venta_id: int, fecha: dt.datetime) -> None:
    venta = db_session.scalar(select(Venta).where(Venta.id == venta_id))
    venta.fecha = fecha
    db_session.commit()


def _otra_sucursal(client, admin_headers, contexto, db_session):  # noqa: F811
    """Una segunda sucursal con stock y su propio cajero."""
    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": "Cochabamba Inicio", "departamento": "Cochabamba"}, headers=admin_headers
    ).json()
    sucursal = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-INI2", "nombre": "Sucursal Dos", "direccion": "Av. 2"},
        headers=admin_headers,
    ).json()
    client.post(
        "/api/v1/inventario/movimientos",
        json={
            "variante_id": contexto["variante_id"],
            "sucursal_id": sucursal["id"],
            "tipo_movimiento_codigo": "recepcion",
            "cantidad": 10,
            "costo_unitario": "10.00",
        },
        headers=admin_headers,
    )
    cajero = crear_cajero(client, admin_headers, db_session, sucursal_id=sucursal["id"], email="cajero2@example.com")
    return {"sucursal_id": sucursal["id"], "cajero_headers": cajero}


# ---- las ventas de hoy ----


def test_sin_ventas_el_resumen_viene_en_ceros_y_con_la_sucursal_del_cajero(client, contexto):  # noqa: F811
    resumen = _resumen(client, contexto["cajero_headers"])

    assert resumen["sucursal_id"] == contexto["sucursal_id"]
    assert resumen["sucursal_nombre"] == "Sucursal Pago"
    ventas = resumen["ventas"]
    assert ventas["tickets"] == 0 and Decimal(ventas["total_ventas"]) == 0
    assert ventas["por_cobrar_cantidad"] == 0 and Decimal(ventas["por_cobrar_total"]) == 0
    assert ventas["mas_vendidas"] == [] and ventas["recientes"] == []


def test_cuenta_lo_cobrado_lo_que_falta_cobrar_y_las_prendas_mas_vendidas(client, contexto):  # noqa: F811
    caja, suc, var = contexto["cajero_headers"], contexto["sucursal_id"], contexto["variante_id"]
    _vender(client, caja, suc, var, cantidad=2)
    _vender(client, caja, suc, var, cantidad=1)
    pendiente = _vender(client, caja, suc, var, cantidad=1, cobrar=False)

    ventas = _resumen(client, caja)["ventas"]

    assert ventas["tickets"] == 2  # solo las pagadas y las entregadas cuentan como vendido
    assert Decimal(ventas["total_ventas"]) == Decimal("300.00")
    assert ventas["por_cobrar_cantidad"] == 1 and Decimal(ventas["por_cobrar_total"]) == Decimal("100.00")
    assert ventas["mas_vendidas"] == [{"variante_id": var, "nombre": "Camisa pago", "cantidad": 3}]
    assert len(ventas["recientes"]) == 3
    assert ventas["recientes"][0]["id"] == pendiente["id"]  # la más reciente primero
    assert ventas["recientes"][0]["estado"] == "pendiente_pago"
    assert {v["estado"] for v in ventas["recientes"][1:]} == {"pagada"}


def test_solo_cuentan_las_ventas_del_dia_de_bolivia(client, db_session, contexto):  # noqa: F811
    caja, suc, var = contexto["cajero_headers"], contexto["sucursal_id"], contexto["variante_id"]
    _hoy, desde, hasta = dia_bolivia()
    dentro = _vender(client, caja, suc, var)
    justo_al_empezar = _vender(client, caja, suc, var)
    ayer_por_un_segundo = _vender(client, caja, suc, var)
    justo_al_terminar = _vender(client, caja, suc, var)
    _poner_fecha(db_session, dentro["id"], desde + dt.timedelta(hours=12))
    _poner_fecha(db_session, justo_al_empezar["id"], desde)  # el límite inferior se incluye
    _poner_fecha(db_session, ayer_por_un_segundo["id"], desde - dt.timedelta(seconds=1))
    _poner_fecha(db_session, justo_al_terminar["id"], hasta)  # el superior ya es de mañana

    ventas = _resumen(client, caja)["ventas"]

    assert ventas["tickets"] == 2
    assert {v["id"] for v in ventas["recientes"]} == {dentro["id"], justo_al_empezar["id"]}


def test_una_venta_devuelta_dice_cuantas_unidades_se_devolvieron(client, contexto):  # noqa: F811
    caja, suc, var = contexto["cajero_headers"], contexto["sucursal_id"], contexto["variante_id"]
    venta = _vender(client, caja, suc, var, cantidad=2)
    devolucion = client.post(
        "/api/v1/devoluciones",
        json={"venta_id": venta["id"], "detalle": [{"venta_detalle_id": venta["detalle"][0]["id"], "cantidad": 1}]},
        headers=caja,
    )
    assert devolucion.status_code == 201, devolucion.text

    reciente = _resumen(client, caja)["ventas"]["recientes"][0]

    assert reciente["unidades_vendidas"] == 2 and reciente["unidades_devueltas"] == 1


def test_la_hora_de_la_venta_sale_en_utc_con_z(client, contexto):  # noqa: F811
    _vender(client, contexto["cajero_headers"], contexto["sucursal_id"], contexto["variante_id"])

    reciente = _resumen(client, contexto["cajero_headers"])["ventas"]["recientes"][0]

    assert reciente["fecha"].endswith("Z")


# ---- sucursales ----


def test_el_cajero_ve_solo_su_sucursal_y_el_administrador_todas(client, admin_headers, db_session, contexto):  # noqa: F811
    otra = _otra_sucursal(client, admin_headers, contexto, db_session)
    var = contexto["variante_id"]
    _vender(client, contexto["cajero_headers"], contexto["sucursal_id"], var, cantidad=1)
    _vender(client, otra["cajero_headers"], otra["sucursal_id"], var, cantidad=2)

    uno = _resumen(client, contexto["cajero_headers"])
    otro = _resumen(client, otra["cajero_headers"])
    admin = _resumen(client, admin_headers)

    assert (uno["sucursal_id"], uno["ventas"]["tickets"]) == (contexto["sucursal_id"], 1)
    assert (otro["sucursal_id"], otro["ventas"]["tickets"]) == (otra["sucursal_id"], 1)
    assert Decimal(otro["ventas"]["total_ventas"]) == Decimal("200.00")
    assert admin["sucursal_id"] is None and admin["sucursal_nombre"] == "Todas las sucursales"
    assert admin["ventas"]["tickets"] == 2 and Decimal(admin["ventas"]["total_ventas"]) == Decimal("300.00")
    assert admin["ventas"]["mas_vendidas"][0]["cantidad"] == 3


# ---- las otras secciones ----


def test_el_administrador_ve_las_tres_secciones(client, admin_headers, contexto):  # noqa: F811
    resumen = _resumen(client, admin_headers)

    assert resumen["ventas"] is not None and resumen["stock"] is not None and resumen["reservas"] is not None
    assert resumen["stock"]["total_alertas"] >= 0


def test_las_reservas_de_hoy_se_cuentan_por_estado(client, admin_headers, cliente_headers, db_session, contexto):  # noqa: F811
    hoy, _desde, _hasta = dia_bolivia()
    futura = dt.date.today() + dt.timedelta(days=7)
    client.post(
        f"/api/v1/sucursales/{contexto['sucursal_id']}/horarios",
        json={"dia_semana": futura.isoweekday(), "hora_apertura": "08:00:00", "hora_cierre": "20:00:00"},
        headers=admin_headers,
    )
    reserva = client.post(
        "/api/v1/reservas",
        json={
            "sucursal_id": contexto["sucursal_id"],
            "fecha_visita": futura.isoformat(),
            "hora_visita_desde": "10:00:00",
            "hora_visita_hasta": "11:00:00",
            "detalle": [{"variante_id": contexto["variante_id"], "cantidad": 1}],
        },
        headers=cliente_headers,
    )
    assert reserva.status_code == 201, reserva.text
    assert _resumen(client, admin_headers)["reservas"] == {"total": 0, "por_estado": []}  # es de otro día

    fila = db_session.scalar(select(Reserva).where(Reserva.id == reserva.json()["id"]))
    fila.fecha_visita = hoy
    db_session.commit()

    reservas = _resumen(client, admin_headers)["reservas"]

    assert reservas["total"] == 1
    assert [(r["codigo"], r["cantidad"]) for r in reservas["por_estado"]] == [("pendiente", 1)]


def test_el_stock_bajo_trae_las_prendas_por_debajo_de_su_minimo(client, admin_headers, contexto):  # noqa: F811
    fila = client.get(
        f"/api/v1/inventario/stock/{contexto['variante_id']}/{contexto['sucursal_id']}", headers=admin_headers
    ).json()
    limites = client.put(
        f"/api/v1/inventario/stock/{fila['id']}/limites", json={"stock_minimo": 50}, headers=admin_headers
    )
    assert limites.status_code == 200, limites.text

    stock = _resumen(client, admin_headers)["stock"]

    assert stock["total_alertas"] == 1
    assert stock["alertas"][0]["variante_id"] == contexto["variante_id"]
    assert stock["alertas"][0]["producto"] == "Camisa pago"
    assert stock["alertas"][0]["stock_minimo"] == 50 and stock["alertas"][0]["cantidad_disponible"] == 10


def test_si_el_plan_no_incluye_las_reservas_esa_seccion_va_en_null(client, admin_headers, contexto, monkeypatch):  # noqa: F811
    from app.inteligencia.casos_uso import cu22_consultar_reportes_indicadores as cu22

    monkeypatch.setattr(cu22, "plan_incluye_funcionalidad", lambda db, funcionalidad: funcionalidad != "reservas")

    resumen = _resumen(client, admin_headers)

    assert resumen["reservas"] is None
    assert resumen["ventas"] is not None and resumen["stock"] is not None


# ---- quién puede verlo ----


def test_sin_sesion_responde_401(client):
    assert client.get(RESUMEN).status_code == 401


def test_un_cliente_recibe_un_resumen_vacio_sin_secciones(client, cliente_headers):
    resumen = _resumen(client, cliente_headers)

    assert resumen["ventas"] is None and resumen["stock"] is None and resumen["reservas"] is None
    assert resumen["sucursal_id"] is None and resumen["sucursal_nombre"] == ""


def test_el_personal_sin_sucursal_asignada_recibe_403(client, db_session, contexto):  # noqa: F811
    repo = UsuarioRepository()
    usuario = repo.crear(
        db_session, UsuarioCrear(nombre="Sin", apellido="Sucursal", email="sinsucursal@example.com", password=CLAVE)
    )
    repo.asignar_roles(db_session, usuario, ["cajero"])
    token = client.post(
        "/api/v1/auth/login", json={"empresa": "fashionstore", "email": "sinsucursal@example.com", "password": CLAVE}
    ).json()["access_token"]

    respuesta = client.get(RESUMEN, headers={"Authorization": f"Bearer {token}"})

    assert respuesta.status_code == 403


# ---- el día de Bolivia ----


@pytest.mark.parametrize(
    "ahora_utc, hoy, desde_utc",
    [
        # 23:30 en Bolivia del 6 es 03:30 UTC del 7: todavía es el día 6.
        (dt.datetime(2026, 11, 7, 3, 30, tzinfo=dt.timezone.utc), dt.date(2026, 11, 6), dt.datetime(2026, 11, 6, 4, 0)),
        # La medianoche de Bolivia (04:00 UTC) ya es el día 7.
        (dt.datetime(2026, 11, 7, 4, 0, tzinfo=dt.timezone.utc), dt.date(2026, 11, 7), dt.datetime(2026, 11, 7, 4, 0)),
        (dt.datetime(2026, 11, 7, 15, 0, tzinfo=dt.timezone.utc), dt.date(2026, 11, 7), dt.datetime(2026, 11, 7, 4, 0)),
    ],
)
def test_el_dia_de_bolivia_y_sus_limites_en_utc(ahora_utc, hoy, desde_utc):
    fecha, desde, hasta = dia_bolivia(ahora_utc)

    assert fecha == hoy
    assert desde == desde_utc and hasta == desde_utc + dt.timedelta(days=1)
    assert desde.tzinfo is None  # naive, como las columnas de la base
