"""CU-17: cambio de talla o color. Una línea de la devolución trae `variante_nueva_id` (del MISMO producto y del
MISMO precio): reingresa lo devuelto y sale lo nuevo en UNA transacción; sin stock de lo nuevo no se registra nada.
A quien compró le llega un comprobante por correo (Brevo simulado; ninguna prueba sale a la red)."""

import datetime as dt
import logging

import pytest
from sqlalchemy import select

from app.catalogo.models import MovimientoInventario, Stock
from app.comercial.models import Devolucion, Venta
from app.plataforma.models import Cliente, Usuario
from tests.conftest import crear_cajero
from tests.correo_simulado import SimuladorBrevo

AHORA = dt.datetime(2026, 10, 26, 15, 0, 0)
STOCK_INICIAL = 20
VENDIDAS = 4


@pytest.fixture()
def reloj(monkeypatch):
    monkeypatch.setattr("app.comercial.politicas.ahora_utc_naive", lambda: AHORA)


@pytest.fixture()
def ctx(client, admin_headers, db_session, reloj):
    """Un producto con tallas M y L en un color, más un producto distinto con una talla; stock en una sucursal."""
    cat = client.post("/api/v1/categorias", json={"nombre": "Poleras Cambio"}, headers=admin_headers).json()
    talla_m = client.post("/api/v1/tallas", json={"codigo": "M", "orden": 1}, headers=admin_headers).json()
    talla_l = client.post("/api/v1/tallas", json={"codigo": "L", "orden": 2}, headers=admin_headers).json()
    color = client.post("/api/v1/colores", json={"nombre": "Azul Cambio"}, headers=admin_headers).json()

    def producto(codigo: str, nombre: str, precio: str, tallas: list[int]) -> dict:
        respuesta = client.post(
            "/api/v1/productos",
            json={
                "codigo": codigo,
                "nombre": nombre,
                "categoria_id": cat["id"],
                "precio_base": precio,
                "tallas_ids": tallas,
                "colores_ids": [color["id"]],
            },
            headers=admin_headers,
        )
        assert respuesta.status_code == 201, respuesta.text
        variantes = client.get(f"/api/v1/productos/{respuesta.json()['id']}/variantes", headers=admin_headers).json()
        return {"producto": respuesta.json(), "variantes": {v["talla_id"]: v for v in variantes}}

    polera = producto("CAM-1", "Polera Cambio", "100.00", [talla_m["id"], talla_l["id"]])
    otra = producto("CAM-2", "Camisa Otra", "100.00", [talla_m["id"]])
    ciudad = client.post(
        "/api/v1/ciudades", json={"nombre": "Santa Cruz Cambio", "departamento": "Santa Cruz"}, headers=admin_headers
    ).json()
    sucursal_id = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-CAM", "nombre": "Sucursal Cambio", "direccion": "Av. 1"},
        headers=admin_headers,
    ).json()["id"]

    def recibir(variante_id: int, cantidad: int) -> None:
        r = client.post(
            "/api/v1/inventario/movimientos",
            json={
                "variante_id": variante_id,
                "sucursal_id": sucursal_id,
                "tipo_movimiento_codigo": "recepcion",
                "cantidad": cantidad,
                "costo_unitario": "10.00",
            },
            headers=admin_headers,
        )
        assert r.status_code == 201, r.text

    m = polera["variantes"][talla_m["id"]]["id"]
    l = polera["variantes"][talla_l["id"]]["id"]
    otro = otra["variantes"][talla_m["id"]]["id"]
    for variante_id in (m, l, otro):
        recibir(variante_id, STOCK_INICIAL)
    return {
        "m": m,
        "l": l,
        "otro_producto": otro,
        "sucursal_id": sucursal_id,
        "cajero_headers": crear_cajero(client, admin_headers, db_session, sucursal_id=sucursal_id),
    }


def _vender(client, ctx, *, variante_id=None, cliente_id=None) -> dict:
    cuerpo = {
        "sucursal_id": ctx["sucursal_id"],
        "detalle": [{"variante_id": variante_id or ctx["m"], "cantidad": VENDIDAS}],
    }
    if cliente_id is not None:
        cuerpo["cliente_id"] = cliente_id
    venta = client.post("/api/v1/ventas/presencial", json=cuerpo, headers=ctx["cajero_headers"])
    assert venta.status_code == 201, venta.text
    pago = client.post(
        "/api/v1/pagos/caja", json={"venta_id": venta.json()["id"], "metodo_pago": "qr"}, headers=ctx["cajero_headers"]
    )
    assert pago.status_code in (200, 201), pago.text
    return venta.json()


def _fechar_hoy(db_session, venta_id: int) -> None:
    db_session.get(Venta, venta_id).fecha = AHORA - dt.timedelta(hours=1)
    db_session.commit()


def _devolver(client, ctx, venta: dict, *, cantidad=1, nueva=None, motivo="Talla"):
    linea = {"venta_detalle_id": venta["detalle"][0]["id"], "cantidad": cantidad}
    if nueva is not None:
        linea["variante_nueva_id"] = nueva
    return client.post(
        "/api/v1/devoluciones",
        json={"venta_id": venta["id"], "motivo": motivo, "detalle": [linea]},
        headers=ctx["cajero_headers"],
    )


def _agotar(client, ctx, admin_headers, variante_id: int) -> None:
    """Saca todo el stock de la variante en la sucursal con un ajuste negativo."""
    r = client.post(
        "/api/v1/inventario/movimientos",
        json={
            "variante_id": variante_id,
            "sucursal_id": ctx["sucursal_id"],
            "tipo_movimiento_codigo": "ajuste_negativo",
            "cantidad": STOCK_INICIAL,
        },
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text


def _fisico(db_session, ctx, variante_id: int) -> int:
    db_session.expire_all()
    stock = db_session.scalar(
        select(Stock).where(Stock.variante_id == variante_id, Stock.sucursal_id == ctx["sucursal_id"])
    )
    return stock.cantidad_fisica


@pytest.fixture()
def venta_con_cliente(client, db_session, ctx, cliente_headers):
    """Una venta pagada, de hoy, cuyo dueño es el cliente de las pruebas (con correo)."""
    usuario = db_session.scalar(select(Usuario).where(Usuario.email == "cliente@example.com"))
    cliente = db_session.scalar(select(Cliente).where(Cliente.usuario_id == usuario.id))
    venta = _vender(client, ctx, cliente_id=cliente.id)
    _fechar_hoy(db_session, venta["id"])
    return venta


# ---- el cambio mueve el stock, en una sola transacción ----


def test_un_cambio_reingresa_lo_devuelto_y_saca_lo_nuevo(client, db_session, ctx):
    venta = _vender(client, ctx)
    _fechar_hoy(db_session, venta["id"])
    antes_m, antes_l = _fisico(db_session, ctx, ctx["m"]), _fisico(db_session, ctx, ctx["l"])

    respuesta = _devolver(client, ctx, venta, cantidad=2, nueva=ctx["l"])

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["reposiciones"] == [
        {
            "venta_detalle_id": venta["detalle"][0]["id"],
            "variante_devuelta_id": ctx["m"],
            "variante_nueva_id": ctx["l"],
            "cantidad": 2,
        }
    ]
    assert _fisico(db_session, ctx, ctx["m"]) == antes_m + 2  # la M devuelta vuelve
    assert _fisico(db_session, ctx, ctx["l"]) == antes_l - 2  # la L sale


def test_el_kardex_deja_las_dos_pistas_ligadas_a_la_devolucion(client, db_session, ctx):
    venta = _vender(client, ctx)
    _fechar_hoy(db_session, venta["id"])

    devolucion_id = _devolver(client, ctx, venta, nueva=ctx["l"]).json()["id"]

    movimientos = db_session.scalars(
        select(MovimientoInventario).where(
            MovimientoInventario.referencia_tipo == "devolucion", MovimientoInventario.referencia_id == devolucion_id
        )
    ).all()
    assert len(movimientos) == 2
    por_variante = {m.variante_id: m for m in movimientos}
    assert set(por_variante) == {ctx["m"], ctx["l"]}
    assert "Cambio" in (por_variante[ctx["l"]].observacion or "")


def test_una_devolucion_simple_sigue_igual_y_no_trae_reposiciones(client, db_session, ctx):
    venta = _vender(client, ctx)
    _fechar_hoy(db_session, venta["id"])
    antes_m, antes_l = _fisico(db_session, ctx, ctx["m"]), _fisico(db_session, ctx, ctx["l"])

    respuesta = _devolver(client, ctx, venta, cantidad=1)

    assert respuesta.status_code == 201
    assert respuesta.json()["reposiciones"] == []
    assert _fisico(db_session, ctx, ctx["m"]) == antes_m + 1
    assert _fisico(db_session, ctx, ctx["l"]) == antes_l


# ---- lo que se rechaza no deja nada a medias ----


def test_sin_stock_de_la_talla_nueva_no_se_registra_nada(client, db_session, ctx, admin_headers):
    venta = _vender(client, ctx)
    _fechar_hoy(db_session, venta["id"])
    _agotar(client, ctx, admin_headers, ctx["l"])
    antes_m, antes_l = _fisico(db_session, ctx, ctx["m"]), _fisico(db_session, ctx, ctx["l"])
    devoluciones_antes = db_session.scalars(select(Devolucion)).all()

    respuesta = _devolver(client, ctx, venta, nueva=ctx["l"])

    assert respuesta.status_code == 409
    assert "el cambio no se registró" in respuesta.json()["detail"]
    assert _fisico(db_session, ctx, ctx["m"]) == antes_m  # lo devuelto NO reingresó
    assert _fisico(db_session, ctx, ctx["l"]) == antes_l
    db_session.expire_all()
    assert len(db_session.scalars(select(Devolucion)).all()) == len(devoluciones_antes)


@pytest.mark.parametrize(
    ("nueva", "mensaje"),
    [
        ("m", "es la misma"),  # la misma variante que se devuelve
        ("otro_producto", "mismo producto"),  # otro producto
    ],
)
def test_un_cambio_invalido_da_400_y_no_toca_el_stock(client, db_session, ctx, nueva, mensaje):
    venta = _vender(client, ctx)
    _fechar_hoy(db_session, venta["id"])
    antes = {k: _fisico(db_session, ctx, ctx[k]) for k in ("m", "l", "otro_producto")}

    respuesta = _devolver(client, ctx, venta, nueva=ctx[nueva])

    assert respuesta.status_code == 400, respuesta.text
    assert mensaje in respuesta.json()["detail"]
    assert {k: _fisico(db_session, ctx, ctx[k]) for k in antes} == antes


def test_una_diferencia_de_precio_se_rechaza(client, db_session, ctx, admin_headers):
    venta = _vender(client, ctx)
    _fechar_hoy(db_session, venta["id"])
    # La L pasa a tener un precio propio, distinto del de la M.
    cambio = client.put(f"/api/v1/variantes/{ctx['l']}", json={"precio": "130.00"}, headers=admin_headers)
    assert cambio.status_code == 200, cambio.text

    respuesta = _devolver(client, ctx, venta, nueva=ctx["l"])

    assert respuesta.status_code == 400
    assert "diferencia de precio" in respuesta.json()["detail"]


def test_una_variante_inexistente_da_404(client, db_session, ctx):
    venta = _vender(client, ctx)
    _fechar_hoy(db_session, venta["id"])

    assert _devolver(client, ctx, venta, nueva=999999).status_code == 404


def test_el_cambio_respeta_el_plazo(client, db_session, ctx):
    venta = _vender(client, ctx)
    db_session.get(Venta, venta["id"]).fecha = AHORA - dt.timedelta(hours=25)
    db_session.commit()

    assert _devolver(client, ctx, venta, nueva=ctx["l"]).status_code == 409


def test_no_se_puede_cambiar_mas_de_lo_vendido(client, db_session, ctx):
    venta = _vender(client, ctx)
    _fechar_hoy(db_session, venta["id"])

    assert _devolver(client, ctx, venta, cantidad=VENDIDAS + 1, nueva=ctx["l"]).status_code == 400


# ---- el comprobante por correo ----


def test_el_cliente_recibe_el_comprobante_de_su_cambio(client, ctx, venta_con_cliente, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch)

    respuesta = _devolver(client, ctx, venta_con_cliente, nueva=ctx["l"])

    assert respuesta.status_code == 201
    assert respuesta.json()["correo_programado"] is True
    assert len(brevo.enviados) == 1
    correo = brevo.ultimo()
    assert correo["to"][0]["email"] == "cliente@example.com"
    assert "cambio" in correo["subject"].lower()
    assert respuesta.json()["codigo"] in correo["subject"]
    texto = correo["textContent"]
    assert "Devolviste: Polera Cambio · talla M · Azul Cambio" in texto
    assert "Recibes en su lugar: Polera Cambio · talla L · Azul Cambio" in texto
    assert "Sucursal Cambio" in texto


def test_una_devolucion_simple_manda_constancia_sin_reposicion(client, ctx, venta_con_cliente, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch)

    respuesta = _devolver(client, ctx, venta_con_cliente)

    assert respuesta.status_code == 201
    assert len(brevo.enviados) == 1
    assert "devolución" in brevo.ultimo()["subject"].lower()
    assert "Recibes en su lugar" not in brevo.ultimo()["textContent"]


def test_sin_cliente_no_se_envia_correo_y_la_devolucion_queda(client, db_session, ctx, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch)
    venta = _vender(client, ctx)  # presencial sin cliente
    _fechar_hoy(db_session, venta["id"])

    respuesta = _devolver(client, ctx, venta, nueva=ctx["l"])

    assert respuesta.status_code == 201
    assert respuesta.json()["correo_programado"] is False
    assert brevo.enviados == []


def test_sin_brevo_configurado_la_devolucion_funciona_igual(client, ctx, venta_con_cliente, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch, configurado=False)

    respuesta = _devolver(client, ctx, venta_con_cliente, nueva=ctx["l"])

    assert respuesta.status_code == 201
    assert respuesta.json()["correo_programado"] is False
    assert brevo.enviados == []


def test_si_brevo_falla_la_devolucion_ya_esta_registrada(client, db_session, ctx, venta_con_cliente, monkeypatch, caplog):
    brevo = SimuladorBrevo(monkeypatch)
    brevo.caido = True
    antes_l = _fisico(db_session, ctx, ctx["l"])

    with caplog.at_level(logging.WARNING):
        respuesta = _devolver(client, ctx, venta_con_cliente, nueva=ctx["l"])

    assert respuesta.status_code == 201
    assert _fisico(db_session, ctx, ctx["l"]) == antes_l - 1
    avisos = [r.getMessage() for r in caplog.records if "correo_no_enviado" in r.getMessage()]
    assert avisos and "cliente@example.com" not in avisos[0]


def test_un_cambio_rechazado_no_manda_correo(client, ctx, venta_con_cliente, admin_headers, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch)
    _agotar(client, ctx, admin_headers, ctx["l"])

    assert _devolver(client, ctx, venta_con_cliente, nueva=ctx["l"]).status_code == 409
    assert brevo.enviados == []
