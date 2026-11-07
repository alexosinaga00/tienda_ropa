"""PayPal guardado y pedido sin conexión en PostgreSQL real (PayPal y Brevo simulados).

SQLite no aplica `SELECT ... FOR UPDATE` ni espera a otra transacción en un INSERT con clave repetida. Aquí:
- dos (u ocho) envíos SIMULTÁNEOS de la misma operación cobran UNA vez y dejan UNA venta (el segundo INSERT espera al
  primero y devuelve lo guardado);
- dos pedidos distintos que compiten por las últimas unidades no venden de más ni cobran de más;
- dos confirmaciones simultáneas del mismo token llaman a PayPal una sola vez;
- el índice único parcial deja UN solo método activo por usuario, y el reemplazo funciona.
Cada hilo tiene su propia sesión (su propia transacción), como dos peticiones a la vez."""

import uuid

import pytest
from sqlalchemy import func, select

from app.catalogo.models import Stock
from app.comercial.casos_uso.cu13_gestionar_carrito_compra_digital import RealizarPedidoDiferido
from app.comercial.casos_uso.cu18_procesar_pagos import GestionarMetodoPagoGuardado
from app.comercial.models import MetodoPagoGuardado, Pago, PedidoDiferido, Venta
from app.comercial.schemas import MetodoPagoPayPalConfirmar, PedidoDiferidoCrear
from tests.paypal_simulado import SimuladorPayPal

from .conftest import CLAVE, registrar_cliente
from .paralelo import ejecutar_en_paralelo

URL = "/api/v1/metodos-pago/paypal"


@pytest.fixture()
def pp(monkeypatch) -> SimuladorPayPal:
    return SimuladorPayPal(monkeypatch)


@pytest.fixture()
def cliente(client_pg, fabrica_pg, pp) -> dict:
    """Un cliente de la tienda con su PayPal ya guardado."""
    usuario_id = registrar_cliente(client_pg, fabrica_pg, "cliente-pg@example.com")
    login = client_pg.post(
        "/api/v1/auth/login", json={"empresa": "fashionstore", "email": "cliente-pg@example.com", "password": CLAVE}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    token = client_pg.post(f"{URL}/iniciar", json={"canal": "web"}, headers=headers).json()["token_preparacion"]
    assert client_pg.post(f"{URL}/confirmar", json={"token_preparacion": token}, headers=headers).status_code == 200
    return {"usuario_id": usuario_id, "headers": headers}


def _pedido(escenario, *, operacion=None, cantidad=2) -> PedidoDiferidoCrear:
    return PedidoDiferidoCrear.model_validate(
        {
            "operacion_id": operacion or str(uuid.uuid4()),
            "sucursal_id": escenario["sucursal_id"],
            "costo_envio": "0.00",
            "lineas": [{"variante_id": escenario["variantes"][0], "cantidad": cantidad}],
            "total_maximo": "5000.00",
        }
    )


def _enviar(usuario_id: int, datos: PedidoDiferidoCrear):
    return lambda db: RealizarPedidoDiferido().ejecutar(db, usuario_id, datos)


def _contar(fabrica, modelo) -> int:
    with fabrica() as db:
        return db.scalar(select(func.count()).select_from(modelo))


def _stock(fabrica, variante_id: int, sucursal_id: int) -> tuple[int, int]:
    with fabrica() as db:
        fila = db.execute(
            select(Stock.cantidad_fisica, Stock.cantidad_reservada).where(
                Stock.variante_id == variante_id, Stock.sucursal_id == sucursal_id
            )
        ).one()
        return fila.cantidad_fisica, fila.cantidad_reservada


# ---- el mismo pedido a la vez ----


def test_dos_envios_simultaneos_de_la_misma_operacion_cobran_una_vez(client_pg, fabrica_pg, escenario, cliente, pp):
    datos = _pedido(escenario, cantidad=2)

    resultados = ejecutar_en_paralelo(
        fabrica_pg, [_enviar(cliente["usuario_id"], datos), _enviar(cliente["usuario_id"], datos)]
    )

    assert all(r.ok for r in resultados), [r.error for r in resultados if not r.ok]
    respuestas = [r.valor for r in resultados]
    assert [x.estado for x in respuestas] == ["cobrado", "cobrado"]
    assert sorted(x.duplicada for x in respuestas) == [False, True]  # exactamente uno es el reenvío
    assert len({x.venta_id for x in respuestas}) == 1  # la MISMA venta
    assert pp.cobros_vault == 1
    assert _contar(fabrica_pg, PedidoDiferido) == 1
    assert _contar(fabrica_pg, Venta) == 1
    assert _stock(fabrica_pg, escenario["variantes"][0], escenario["sucursal_id"]) == (8, 0)  # descontado una sola vez


def test_ocho_envios_simultaneos_de_la_misma_operacion_dejan_una_sola_venta(client_pg, fabrica_pg, escenario, cliente, pp):
    datos = _pedido(escenario, cantidad=1)

    resultados = ejecutar_en_paralelo(fabrica_pg, [_enviar(cliente["usuario_id"], datos) for _ in range(8)])

    assert all(r.ok for r in resultados), [r.error for r in resultados if not r.ok]
    assert sum(not r.valor.duplicada for r in resultados) == 1
    assert pp.cobros_vault == 1
    assert _contar(fabrica_pg, Venta) == 1 and _contar(fabrica_pg, Pago) == 1
    assert _stock(fabrica_pg, escenario["variantes"][0], escenario["sucursal_id"]) == (9, 0)


def test_dos_pedidos_que_compiten_por_las_ultimas_unidades_no_venden_ni_cobran_de_mas(
    client_pg, fabrica_pg, escenario, cliente, pp
):
    # 10 unidades en stock; cada pedido quiere 6: solo uno cabe.
    a, b = _pedido(escenario, cantidad=6), _pedido(escenario, cantidad=6)

    resultados = ejecutar_en_paralelo(fabrica_pg, [_enviar(cliente["usuario_id"], a), _enviar(cliente["usuario_id"], b)])

    assert all(r.ok for r in resultados), [r.error for r in resultados if not r.ok]
    estados = sorted((r.valor.estado, r.valor.motivo) for r in resultados)
    assert estados == [("cobrado", None), ("rechazado", "stock_insuficiente")]
    assert pp.cobros_vault == 1  # solo se cobró el que cabía
    assert _stock(fabrica_pg, escenario["variantes"][0], escenario["sucursal_id"]) == (4, 0)
    assert _contar(fabrica_pg, Venta) == 1 and _contar(fabrica_pg, PedidoDiferido) == 2


def test_la_respuesta_perdida_del_cobro_se_recupera_sin_cobrar_doble(client_pg, fabrica_pg, escenario, cliente, pp):
    cuerpo = {
        "operacion_id": str(uuid.uuid4()),
        "sucursal_id": escenario["sucursal_id"],
        "costo_envio": "0.00",
        "lineas": [{"variante_id": escenario["variantes"][0], "cantidad": 3}],
        "total_maximo": "5000.00",
    }
    pp.perder_respuestas_de_cobro = 1

    primera = client_pg.post("/api/v1/pedidos-diferidos", json=cuerpo, headers=cliente["headers"])

    assert primera.status_code == 503 and primera.json()["codigo"] == "paypal_no_disponible"
    assert (_contar(fabrica_pg, Venta), _contar(fabrica_pg, PedidoDiferido)) == (0, 0)
    assert _stock(fabrica_pg, escenario["variantes"][0], escenario["sucursal_id"]) == (10, 0)

    segunda = client_pg.post("/api/v1/pedidos-diferidos", json=cuerpo, headers=cliente["headers"])

    assert segunda.status_code == 200 and segunda.json()["estado"] == "cobrado"
    assert pp.cobros_vault == 1
    assert _stock(fabrica_pg, escenario["variantes"][0], escenario["sucursal_id"]) == (7, 0)
    assert _contar(fabrica_pg, Venta) == 1


# ---- guardar el PayPal ----


def test_dos_confirmaciones_simultaneas_del_mismo_token_llaman_a_paypal_una_vez(client_pg, fabrica_pg, pp):
    usuario_id = registrar_cliente(client_pg, fabrica_pg, "doble-pg@example.com")
    login = client_pg.post(
        "/api/v1/auth/login", json={"empresa": "fashionstore", "email": "doble-pg@example.com", "password": CLAVE}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    token = client_pg.post(f"{URL}/iniciar", json={"canal": "app"}, headers=headers).json()["token_preparacion"]
    datos = MetodoPagoPayPalConfirmar(token_preparacion=token)

    resultados = ejecutar_en_paralelo(
        fabrica_pg, [lambda db: GestionarMetodoPagoGuardado().confirmar(db, usuario_id, datos) for _ in range(3)]
    )

    assert all(r.ok for r in resultados), [r.error for r in resultados if not r.ok]
    assert all(r.valor.guardado for r in resultados)
    assert pp.llamadas("POST", "/v3/vault/payment-tokens") == 1
    with fabrica_pg() as db:
        assert db.scalar(select(func.count()).select_from(MetodoPagoGuardado).where(MetodoPagoGuardado.estado == "activo")) == 1


def test_guardar_otro_reemplaza_al_anterior_y_el_indice_deja_un_solo_activo(client_pg, fabrica_pg, cliente, pp):
    primero = pp.ultimo_payment_token()
    token = client_pg.post(f"{URL}/iniciar", json={"canal": "web"}, headers=cliente["headers"]).json()["token_preparacion"]

    assert client_pg.post(f"{URL}/confirmar", json={"token_preparacion": token}, headers=cliente["headers"]).status_code == 200

    with fabrica_pg() as db:
        estados = list(db.scalars(select(MetodoPagoGuardado.estado).order_by(MetodoPagoGuardado.id)))
    assert estados == ["revocado", "activo"]
    assert pp.tokens_borrados == [primero]
    assert client_pg.delete(URL, headers=cliente["headers"]).status_code == 204
    with fabrica_pg() as db:
        assert set(db.scalars(select(MetodoPagoGuardado.estado))) == {"revocado"}
