"""CU-13: el pedido que el cliente armó SIN conexión se cobra al reconectar con el PayPal que guardó antes.

En UNA llamada el servidor revalida stock, precios y el tope que el cliente aceptó (`total_maximo`), crea la venta digital,
cobra con PayPal (convertida de Bs a USD) y la confirma. El resultado FINAL queda guardado por (empresa, operación):
reenviar no cobra otra vez. Un fallo temporal (PayPal o la red) responde 503 sin guardar nada ni dejar venta colgada, y el
reintento con la MISMA operación no cobra doble (PayPal-Request-Id derivado de la operación). PayPal y Brevo son
simulados: ninguna prueba sale a la red. NO se probó contra el sandbox real de PayPal."""

import datetime as dt
import uuid

import pytest
from sqlalchemy import func, select

from app.catalogo.models import ProductoVariante, Stock
from app.comercial.models import Pago, PedidoDiferido, TransaccionPasarela, Venta
from app.core.config import get_settings
from app.plataforma.models import Bitacora, Notificacion
from tests.comercial.test_cambio_talla import (  # noqa: F401  (los fixtures se reutilizan)
    STOCK_INICIAL,
    _agotar,
    _fisico,
    ctx,
    reloj,
)
from tests.comercial.test_paypal_guardado import _guardar, _otro_cliente
from tests.correo_simulado import SimuladorBrevo
from tests.paypal_simulado import SimuladorPayPal

URL = "/api/v1/pedidos-diferidos"
PRECIO = 100  # cada prenda de la prueba cuesta Bs 100


@pytest.fixture()
def pp(monkeypatch) -> SimuladorPayPal:
    return SimuladorPayPal(monkeypatch)


@pytest.fixture()
def listo(client, cliente_headers, pp, ctx):
    """El cliente ya guardó su PayPal (con conexión)."""
    _guardar(client, cliente_headers)
    return ctx


def _cuerpo(ctx, *, operacion=None, cantidad=2, variante=None, total_maximo="1000.00", costo_envio="0.00", **extra) -> dict:
    return {
        "operacion_id": operacion or str(uuid.uuid4()),
        "sucursal_id": ctx["sucursal_id"],
        "costo_envio": costo_envio,
        "lineas": [{"variante_id": variante or ctx["m"], "cantidad": cantidad}],
        "total_maximo": total_maximo,
        "fecha_pedido": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).isoformat(),
        **extra,
    }


def _enviar(client, headers, cuerpo):
    return client.post(URL, json=cuerpo, headers=headers)


def _contar(db_session, modelo) -> int:
    db_session.expire_all()
    return db_session.scalar(select(func.count()).select_from(modelo))


def _reservado(db_session, ctx) -> int:
    db_session.expire_all()
    return db_session.scalar(select(func.coalesce(func.sum(Stock.cantidad_reservada), 0)).where(Stock.sucursal_id == ctx["sucursal_id"]))


# ---- el pedido se cobra ----


def test_el_pedido_se_cobra_crea_la_venta_y_descuenta_el_stock(client, db_session, cliente_headers, listo, pp):
    ctx = listo
    antes = _fisico(db_session, ctx, ctx["m"])
    cuerpo = _cuerpo(ctx, cantidad=2)

    respuesta = _enviar(client, cliente_headers, cuerpo)

    assert respuesta.status_code == 200, respuesta.text
    datos = respuesta.json()
    assert datos["operacion_id"] == cuerpo["operacion_id"]
    assert (datos["estado"], datos["motivo"], datos["duplicada"]) == ("cobrado", None, False)
    assert datos["total"] == "200.00" and datos["total_usd"] == "28.74"  # 200 / 6,96
    assert datos["codigo_venta"].startswith("VTA-") and datos["venta_id"] > 0
    assert "Cobramos tu pedido" in datos["mensaje"] and datos["codigo_venta"] in datos["mensaje"]
    # La venta quedó pagada y el stock bajó (de verdad, no solo reservado).
    db_session.expire_all()
    venta = db_session.get(Venta, datos["venta_id"])
    assert venta.canal == "digital" and venta.total == 200 and venta.sucursal_id == ctx["sucursal_id"]
    assert _fisico(db_session, ctx, ctx["m"]) == antes - 2
    assert _reservado(db_session, ctx) == 0
    # El cobro quedó en el libro de pagos como el pago normal por PayPal.
    pago = db_session.scalar(select(Pago).where(Pago.venta_id == venta.id))
    assert pago.monto == 200 and pago.referencia_externa == "ORD-VLT-0003"
    transacciones = list(db_session.scalars(select(TransaccionPasarela).where(TransaccionPasarela.pago_id == pago.id)))
    assert {t.pasarela for t in transacciones} == {"paypal"} and "aprobado" in {t.estado for t in transacciones}
    assert "VAULT" not in str([t.payload_envio for t in transacciones] + [t.payload_respuesta for t in transacciones])
    # La compra aparece en "Mis compras" del cliente, ya pagada.
    compras = client.get("/api/v1/ventas/mis-compras", headers=cliente_headers).json()
    assert [(c["id"], c["estado"]) for c in compras] == [(venta.id, "pagada")]


def test_a_paypal_se_le_manda_el_monto_en_dolares_el_vault_id_y_la_clave_de_idempotencia(
    client, cliente_headers, listo, pp, db_session
):
    cuerpo = _cuerpo(listo, cantidad=2)

    assert _enviar(client, cliente_headers, cuerpo).status_code == 200

    (cobro,) = pp.cuerpos_de_cobro_vault
    assert cobro["intent"] == "CAPTURE"
    assert cobro["purchase_units"][0]["amount"] == {"currency_code": "USD", "value": "28.74"}
    assert cobro["payment_source"]["paypal"]["vault_id"] == pp.ultimo_payment_token()
    # El cuerpo no cambia entre reintentos: la referencia es la operación, no el código de la venta.
    assert cobro["purchase_units"][0]["reference_id"] == cuerpo["operacion_id"]
    empresa_id = db_session.scalar(select(PedidoDiferido.empresa_id))
    assert pp.cabeceras_de_cobro_vault[0]["paypal-request-id"] == f"pd-{empresa_id}-{cuerpo['operacion_id']}"


def test_la_conversion_usa_el_tipo_de_cambio_del_servidor(client, cliente_headers, listo, pp, monkeypatch):
    from decimal import Decimal

    monkeypatch.setattr(get_settings(), "tipo_cambio_bs_por_usd", Decimal("10"))

    datos = _enviar(client, cliente_headers, _cuerpo(listo, cantidad=2)).json()

    assert datos["total"] == "200.00" and datos["total_usd"] == "20.00"
    assert pp.cuerpos_de_cobro_vault[0]["purchase_units"][0]["amount"]["value"] == "20.00"


def test_el_servidor_recalcula_el_precio_y_no_se_fia_del_cliente(client, cliente_headers, listo, pp):
    # El cliente solo manda variante y cantidad: cualquier precio extra se rechaza.
    cuerpo = _cuerpo(listo)
    cuerpo["lineas"][0]["precio_unitario"] = "1.00"

    assert _enviar(client, cliente_headers, cuerpo).status_code == 422


def test_un_costo_de_envio_se_suma_al_total(client, cliente_headers, listo, pp):
    datos = _enviar(client, cliente_headers, _cuerpo(listo, cantidad=1, costo_envio="15.50")).json()

    assert datos["estado"] == "cobrado" and datos["total"] == "115.50" and datos["total_usd"] == "16.59"


def test_una_orden_aprobada_pero_sin_capturar_se_captura(client, cliente_headers, listo, pp):
    pp.estado_cobro_vault = "APPROVED"

    datos = _enviar(client, cliente_headers, _cuerpo(listo)).json()

    assert datos["estado"] == "cobrado"
    assert pp.capturas == 1


# ---- idempotencia ----


def test_reenviar_la_misma_operacion_devuelve_lo_mismo_sin_cobrar_otra_vez(client, db_session, cliente_headers, listo, pp):
    ctx = listo
    cuerpo = _cuerpo(ctx, cantidad=2)
    primera = _enviar(client, cliente_headers, cuerpo).json()
    stock = _fisico(db_session, ctx, ctx["m"])
    ventas = _contar(db_session, Venta)

    segunda = _enviar(client, cliente_headers, cuerpo)

    assert segunda.status_code == 200
    assert segunda.json() == {**primera, "duplicada": True}
    assert pp.cobros_vault == 1 and len(pp.cuerpos_de_cobro_vault) == 1
    assert _contar(db_session, Venta) == ventas  # ninguna venta nueva
    assert _fisico(db_session, ctx, ctx["m"]) == stock
    assert _contar(db_session, PedidoDiferido) == 1


def test_el_reenvio_ignora_el_cuerpo_nuevo(client, cliente_headers, listo, pp):
    operacion = str(uuid.uuid4())
    primera = _enviar(client, cliente_headers, _cuerpo(listo, operacion=operacion, cantidad=2)).json()

    segunda = _enviar(client, cliente_headers, _cuerpo(listo, operacion=operacion, cantidad=5, total_maximo="1.00")).json()

    assert segunda == {**primera, "duplicada": True}
    assert pp.cobros_vault == 1


def test_un_rechazo_tambien_es_final_y_se_reenvia_igual(client, db_session, cliente_headers, ctx, pp):
    # Sin PayPal guardado: rechazado. Aunque después lo guarde, ESA operación sigue rechazada (el cliente arma otra).
    cuerpo = _cuerpo(ctx)
    primera = _enviar(client, cliente_headers, cuerpo).json()
    assert primera["estado"] == "rechazado"
    _guardar(client, cliente_headers)

    segunda = _enviar(client, cliente_headers, cuerpo).json()

    assert segunda == {**primera, "duplicada": True}
    assert pp.cobros_vault == 0
    assert _enviar(client, cliente_headers, _cuerpo(ctx)).json()["estado"] == "cobrado"  # una operación nueva sí


def test_la_operacion_de_otra_persona_se_ve_inexistente(client, cliente_headers, listo, pp):
    cuerpo = _cuerpo(listo)
    assert _enviar(client, cliente_headers, cuerpo).status_code == 200
    otro = _otro_cliente(client)

    respuesta = _enviar(client, otro, cuerpo)

    assert respuesta.status_code == 404
    assert pp.cobros_vault == 1


def test_un_reenvio_no_cuenta_para_el_limite_de_pedidos(client, cliente_headers, listo, pp, monkeypatch):
    monkeypatch.setattr(get_settings(), "pedido_diferido_max_por_ventana", 1)
    cuerpo = _cuerpo(listo, cantidad=1)
    assert _enviar(client, cliente_headers, cuerpo).status_code == 200

    assert _enviar(client, cliente_headers, cuerpo).status_code == 200  # el reenvío pasa
    bloqueado = _enviar(client, cliente_headers, _cuerpo(listo, cantidad=1))  # un pedido nuevo, no

    assert bloqueado.status_code == 429
    assert int(bloqueado.headers["Retry-After"]) >= 1


# ---- rechazos finales: ni venta, ni stock apartado, ni cobro ----


def _nada_quedo(db_session, ctx, pp, antes: int) -> None:
    assert _contar(db_session, Venta) == antes
    assert _reservado(db_session, ctx) == 0
    assert _fisico(db_session, ctx, ctx["m"]) == STOCK_INICIAL
    assert pp.cobros_vault == 0 and pp.capturas == 0


def test_sin_paypal_guardado_se_rechaza_con_un_mensaje_claro(client, db_session, cliente_headers, ctx, pp):
    ventas = _contar(db_session, Venta)

    respuesta = _enviar(client, cliente_headers, _cuerpo(ctx))

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert (datos["estado"], datos["motivo"]) == ("rechazado", "sin_metodo_pago")
    assert datos["venta_id"] is None and datos["codigo_venta"] is None and datos["total"] is None
    assert "Guárdalo con conexión" in datos["mensaje"]
    _nada_quedo(db_session, ctx, pp, ventas)
    assert pp.peticiones == []  # ni siquiera se habló con PayPal


def test_un_paypal_quitado_cuenta_como_sin_metodo_de_pago(client, db_session, cliente_headers, listo, pp):
    client.delete("/api/v1/metodos-pago/paypal", headers=cliente_headers)

    datos = _enviar(client, cliente_headers, _cuerpo(listo)).json()

    assert datos["motivo"] == "sin_metodo_pago"


def test_sin_stock_suficiente_se_rechaza_sin_apartar_nada(client, db_session, admin_headers, cliente_headers, listo, pp):
    _agotar(client, listo, admin_headers, listo["m"])
    ventas = _contar(db_session, Venta)

    datos = _enviar(client, cliente_headers, _cuerpo(listo, cantidad=1)).json()

    assert (datos["estado"], datos["motivo"]) == ("rechazado", "stock_insuficiente")
    assert "Polera Cambio · talla M · Azul Cambio" in datos["mensaje"] and "no se cobró" in datos["mensaje"]
    assert _contar(db_session, Venta) == ventas and _reservado(db_session, listo) == 0
    assert pp.cobros_vault == 0 and pp.cuerpos_de_cobro_vault == []


def test_si_una_prenda_no_alcanza_no_se_aparta_ninguna_de_las_otras(client, db_session, admin_headers, cliente_headers, listo, pp):
    _agotar(client, listo, admin_headers, listo["l"])
    cuerpo = _cuerpo(listo, cantidad=1)
    cuerpo["lineas"].append({"variante_id": listo["l"], "cantidad": 1})

    datos = _enviar(client, cliente_headers, cuerpo).json()

    assert datos["motivo"] == "stock_insuficiente"
    assert _reservado(db_session, listo) == 0
    assert _fisico(db_session, listo, listo["m"]) == STOCK_INICIAL


def test_si_el_total_supera_el_maximo_aceptado_no_se_cobra(client, db_session, cliente_headers, listo, pp):
    ventas = _contar(db_session, Venta)

    datos = _enviar(client, cliente_headers, _cuerpo(listo, cantidad=2, total_maximo="150.00")).json()

    assert (datos["estado"], datos["motivo"]) == ("rechazado", "total_supera_maximo")
    assert "Bs 200.00" in datos["mensaje"] and "Bs 150.00" in datos["mensaje"]
    assert datos["total"] is None
    _nada_quedo(db_session, listo, pp, ventas)


def test_un_total_igual_al_maximo_si_se_cobra(client, listo, cliente_headers, pp):
    assert _enviar(client, cliente_headers, _cuerpo(listo, cantidad=2, total_maximo="200.00")).json()["estado"] == "cobrado"


def test_si_cambia_el_precio_y_sube_del_maximo_se_rechaza(client, db_session, admin_headers, cliente_headers, listo, pp):
    # El cliente vio Bs 100 y aceptó hasta Bs 100; mientras estaba sin conexión el precio subió a 120.
    variante = db_session.get(ProductoVariante, listo["m"])
    variante.precio = 120
    db_session.commit()
    ventas = _contar(db_session, Venta)

    datos = _enviar(client, cliente_headers, _cuerpo(listo, cantidad=1, total_maximo="100.00")).json()

    assert datos["motivo"] == "total_supera_maximo" and "Bs 120.00" in datos["mensaje"]
    _nada_quedo(db_session, listo, pp, ventas)


def test_si_paypal_rechaza_el_cobro_no_queda_venta_ni_stock_apartado(client, db_session, cliente_headers, listo, pp):
    pp.rechazar_cobro_vault = "INSTRUMENT_DECLINED"
    ventas = _contar(db_session, Venta)

    datos = _enviar(client, cliente_headers, _cuerpo(listo)).json()

    assert (datos["estado"], datos["motivo"]) == ("rechazado", "pago_rechazado")
    assert datos["venta_id"] is None
    _nada_quedo(db_session, listo, pp, ventas)
    assert not db_session.scalars(select(Pago).where(Pago.referencia_externa.like("ORD-VLT%"))).all()


def test_un_token_revocado_en_paypal_es_un_pago_rechazado(client, db_session, cliente_headers, listo, pp):
    pp.payment_tokens[pp.ultimo_payment_token()]["activo"] = False  # el cliente lo revocó desde su cuenta de PayPal
    ventas = _contar(db_session, Venta)

    datos = _enviar(client, cliente_headers, _cuerpo(listo)).json()

    assert datos["motivo"] == "pago_rechazado"
    _nada_quedo(db_session, listo, pp, ventas)


def test_una_orden_que_paypal_no_completa_es_un_pago_rechazado(client, db_session, cliente_headers, listo, pp):
    pp.estado_cobro_vault = "PAYER_ACTION_REQUIRED"
    ventas = _contar(db_session, Venta)

    datos = _enviar(client, cliente_headers, _cuerpo(listo)).json()

    assert datos["motivo"] == "pago_rechazado"
    _nada_quedo(db_session, listo, pp, ventas)


def test_una_prenda_dada_de_baja_se_rechaza(client, db_session, cliente_headers, listo, pp):
    db_session.get(ProductoVariante, listo["m"]).activo = False
    db_session.commit()
    ventas = _contar(db_session, Venta)

    datos = _enviar(client, cliente_headers, _cuerpo(listo)).json()

    assert (datos["estado"], datos["motivo"]) == ("rechazado", "variante_inactiva")
    assert "ya no está disponible" in datos["mensaje"]
    assert _contar(db_session, Venta) == ventas and pp.cuerpos_de_cobro_vault == []


def test_un_pedido_demasiado_grande_se_rechaza_como_invalido(client, db_session, cliente_headers, listo, pp, monkeypatch):
    monkeypatch.setattr(get_settings(), "pedido_diferido_max_unidades_por_linea", 3)
    ventas = _contar(db_session, Venta)

    datos = _enviar(client, cliente_headers, _cuerpo(listo, cantidad=4)).json()

    assert (datos["estado"], datos["motivo"]) == ("rechazado", "pedido_invalido")
    assert "hasta 3 unidades" in datos["mensaje"]
    assert _contar(db_session, Venta) == ventas and pp.cuerpos_de_cobro_vault == []


@pytest.mark.parametrize(
    ("ajuste", "valor", "cuerpo_extra"),
    [
        ("pedido_diferido_max_lineas", 1, "dos_lineas"),
        ("pedido_diferido_max_unidades", 3, "cinco_unidades"),
        ("pedido_diferido_max_costo_envio", 10, "envio_caro"),
    ],
)
def test_los_topes_del_pedido(client, listo, cliente_headers, pp, monkeypatch, ajuste, valor, cuerpo_extra):
    monkeypatch.setattr(get_settings(), ajuste, valor)
    cuerpo = _cuerpo(listo, cantidad=1)
    if cuerpo_extra == "dos_lineas":
        cuerpo["lineas"].append({"variante_id": listo["l"], "cantidad": 1})
    elif cuerpo_extra == "cinco_unidades":
        cuerpo["lineas"] = [{"variante_id": listo["m"], "cantidad": 2}, {"variante_id": listo["l"], "cantidad": 2}]
    else:
        cuerpo["costo_envio"] = "10.01"

    datos = _enviar(client, cliente_headers, cuerpo).json()

    assert (datos["estado"], datos["motivo"]) == ("rechazado", "pedido_invalido")
    assert pp.cuerpos_de_cobro_vault == []


def _hace(**tiempo) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(**tiempo)).isoformat()


def test_un_pedido_de_hace_mas_de_7_dias_vence_sin_vender_ni_cobrar(client, db_session, cliente_headers, listo, pp):
    ventas = _contar(db_session, Venta)
    cuerpo = _cuerpo(listo, fecha_pedido=_hace(days=7, hours=1))

    respuesta = _enviar(client, cliente_headers, cuerpo)

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert (datos["estado"], datos["motivo"]) == ("rechazado", "pedido_vencido")
    assert datos["mensaje"].startswith("Tu pedido venció: pasaron más de 7 días sin conexión")
    assert datos["venta_id"] is None and datos["total"] is None
    _nada_quedo(db_session, listo, pp, ventas)
    assert pp.cuerpos_de_cobro_vault == []
    # Es final como cualquier rechazo: reenviar devuelve lo mismo.
    assert _enviar(client, cliente_headers, cuerpo).json() == {**datos, "duplicada": True}


def test_un_pedido_vencido_avisa_por_notificacion_y_por_correo(client, cliente_headers, listo, pp, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch)

    _enviar(client, cliente_headers, _cuerpo(listo, fecha_pedido=_hace(days=30)))

    (aviso,) = client.get("/api/v1/notificaciones", headers=cliente_headers).json()
    assert aviso["tipo"] == "pedido_diferido" and "venció" in aviso["mensaje"]
    (correo,) = brevo.enviados
    assert "No pudimos cobrar tu pedido" in correo["subject"] and "venció" in correo["textContent"]


def test_un_pedido_de_menos_de_7_dias_o_sin_fecha_se_cobra(client, cliente_headers, listo, pp):
    assert _enviar(client, cliente_headers, _cuerpo(listo, cantidad=1, fecha_pedido=_hace(days=6, hours=23))).json()["estado"] == "cobrado"
    sin_fecha = _cuerpo(listo, cantidad=1)
    del sin_fecha["fecha_pedido"]
    assert _enviar(client, cliente_headers, sin_fecha).json()["estado"] == "cobrado"
    sin_zona = _cuerpo(listo, cantidad=1, fecha_pedido=(dt.datetime.utcnow() - dt.timedelta(days=1)).isoformat())
    assert _enviar(client, cliente_headers, sin_zona).json()["estado"] == "cobrado"  # sin zona se toma como UTC


def test_la_antiguedad_maxima_sale_de_la_configuracion(client, cliente_headers, listo, pp, monkeypatch):
    monkeypatch.setattr(get_settings(), "pedido_diferido_max_dias", 2)

    datos = _enviar(client, cliente_headers, _cuerpo(listo, fecha_pedido=_hace(days=3))).json()

    assert datos["motivo"] == "pedido_vencido" and "más de 2 días" in datos["mensaje"]


def test_una_fecha_en_el_futuro_es_invalida_pero_con_una_pequena_tolerancia(client, db_session, cliente_headers, listo, pp):
    futuro = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)).isoformat()
    ligeramente = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)).isoformat()
    ventas = _contar(db_session, Venta)

    lejos = _enviar(client, cliente_headers, _cuerpo(listo, fecha_pedido=futuro)).json()
    cerca = _enviar(client, cliente_headers, _cuerpo(listo, cantidad=1, fecha_pedido=ligeramente)).json()

    assert (lejos["estado"], lejos["motivo"]) == ("rechazado", "pedido_invalido")
    assert "fecha" in lejos["mensaje"]
    assert cerca["estado"] == "cobrado"
    assert _contar(db_session, Venta) == ventas + 1


def test_retirar_en_un_deposito_se_rechaza_pero_con_envio_se_acepta(client, admin_headers, cliente_headers, listo, pp):
    ciudad = client.post("/api/v1/ciudades", json={"nombre": "Oruro Dep", "departamento": "Oruro"}, headers=admin_headers).json()
    deposito = client.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "DEP-1", "nombre": "Depósito", "direccion": "Av. 9", "es_deposito": True},
        headers=admin_headers,
    )
    assert deposito.status_code == 201, deposito.text
    cuerpo = _cuerpo(listo, cantidad=1)
    cuerpo["sucursal_id"] = deposito.json()["id"]

    datos = _enviar(client, cliente_headers, cuerpo).json()

    assert (datos["estado"], datos["motivo"]) == ("rechazado", "pedido_invalido")
    assert "no atiende al público" in datos["mensaje"]


# ---- fallos temporales: 503, nada guardado, el reintento no cobra doble ----


def _filas_de_pedido(db_session) -> list[PedidoDiferido]:
    db_session.expire_all()
    return list(db_session.scalars(select(PedidoDiferido).order_by(PedidoDiferido.id)))


def test_con_paypal_caido_responde_503_sin_decision_y_el_reintento_funciona(client, db_session, cliente_headers, listo, pp):
    ventas = _contar(db_session, Venta)
    cuerpo = _cuerpo(listo, cantidad=2)
    pp.caer_en = {"crear"}

    respuesta = _enviar(client, cliente_headers, cuerpo)

    assert respuesta.status_code == 503
    assert respuesta.json()["codigo"] == "paypal_no_disponible"
    # Sin decisión final: solo la marca `incierto` con el monto (PayPal pudo haber cobrado y no se supo).
    (marca,) = _filas_de_pedido(db_session)
    assert marca.estado == "incierto" and marca.venta_id is None
    assert marca.total == 200 and marca.total_usd is not None
    assert _contar(db_session, Venta) == ventas and _reservado(db_session, listo) == 0  # ni venta colgada ni stock apartado
    assert pp.cobros_vault == 0
    pp.caer_en = set()
    reintento = _enviar(client, cliente_headers, cuerpo)
    assert reintento.status_code == 200
    assert reintento.json()["estado"] == "cobrado" and reintento.json()["duplicada"] is False
    assert pp.cobros_vault == 1
    (final,) = _filas_de_pedido(db_session)  # la MISMA fila pasó de incierto a cobrado
    assert final.id == marca.id and final.estado == "cobrado" and final.venta_id is not None


def test_si_el_cobro_se_hace_pero_la_respuesta_se_pierde_el_reintento_no_cobra_doble(
    client, db_session, cliente_headers, listo, pp
):
    """El caso más delicado: PayPal SÍ cobró y la respuesta nunca llegó. El servidor no sabe qué pasó (503, solo la marca
    `incierto`). El reintento con la misma operación manda la misma clave y el mismo cuerpo: PayPal devuelve el cobro
    original y la venta se arma con él. Un solo cobro, una sola venta, el stock descontado una vez."""
    ctx = listo
    ventas = _contar(db_session, Venta)
    cuerpo = _cuerpo(ctx, cantidad=2)
    pp.perder_respuestas_de_cobro = 1

    primera = _enviar(client, cliente_headers, cuerpo)

    assert primera.status_code == 503 and primera.json()["codigo"] == "paypal_no_disponible"
    assert pp.cobros_vault == 1  # el dinero se movió
    assert _contar(db_session, Venta) == ventas
    assert [f.estado for f in _filas_de_pedido(db_session)] == ["incierto"]
    assert _reservado(db_session, ctx) == 0 and _fisico(db_session, ctx, ctx["m"]) == STOCK_INICIAL

    segunda = _enviar(client, cliente_headers, cuerpo)

    assert segunda.status_code == 200, segunda.text
    assert segunda.json()["estado"] == "cobrado"
    assert pp.cobros_vault == 1  # NO se cobró otra vez
    assert len(pp.cuerpos_de_cobro_vault) == 2  # dos peticiones, la misma clave y el mismo cuerpo
    assert pp.cuerpos_de_cobro_vault[0] == pp.cuerpos_de_cobro_vault[1]
    assert pp.cabeceras_de_cobro_vault[0]["paypal-request-id"] == pp.cabeceras_de_cobro_vault[1]["paypal-request-id"]
    assert _contar(db_session, Venta) == ventas + 1 and _contar(db_session, Pago) >= 1
    assert _fisico(db_session, ctx, ctx["m"]) == STOCK_INICIAL - 2  # descontado UNA vez
    assert _reservado(db_session, ctx) == 0
    assert _enviar(client, cliente_headers, cuerpo).json()["duplicada"] is True


def test_un_cobro_pendiente_de_revision_no_se_decide_todavia(client, db_session, cliente_headers, listo, pp):
    pp.estado_captura = "PENDING"
    ventas = _contar(db_session, Venta)
    cuerpo = _cuerpo(listo)

    respuesta = _enviar(client, cliente_headers, cuerpo)

    assert respuesta.status_code == 503
    assert _contar(db_session, Venta) == ventas and [f.estado for f in _filas_de_pedido(db_session)] == ["incierto"]
    assert _reservado(db_session, listo) == 0
    # Mientras PayPal siga revisándolo, el reintento sigue sin decidir (y no cobra otra vez).
    assert _enviar(client, cliente_headers, cuerpo).status_code == 503
    assert [f.estado for f in _filas_de_pedido(db_session)] == ["incierto"] and pp.cobros_vault == 1


def test_si_paypal_informa_otro_monto_no_se_confirma_nada(client, db_session, cliente_headers, listo, pp):
    from decimal import Decimal

    pp.monto_reportado = Decimal("1.00")
    ventas = _contar(db_session, Venta)
    cuerpo = _cuerpo(listo)

    respuesta = _enviar(client, cliente_headers, cuerpo)

    assert respuesta.status_code == 503
    assert _contar(db_session, Venta) == ventas and [f.estado for f in _filas_de_pedido(db_session)] == ["incierto"]
    assert _enviar(client, cliente_headers, cuerpo).status_code == 503  # el monto sigue sin coincidir: no se decide


def test_si_falla_al_confirmar_despues_de_cobrar_el_reintento_arma_la_venta_con_ese_cobro(
    client, db_session, cliente_headers, listo, pp, monkeypatch
):
    import app.comercial.casos_uso.cu13_gestionar_carrito_compra_digital as cu13

    original = cu13.registrar_cobro_pasarela_aprobado

    def falla(*args, **kwargs):
        raise RuntimeError("falla simulada al confirmar")

    monkeypatch.setattr(cu13, "registrar_cobro_pasarela_aprobado", falla)
    ventas = _contar(db_session, Venta)
    cuerpo = _cuerpo(listo)

    respuesta = _enviar(client, cliente_headers, cuerpo)

    assert respuesta.status_code == 503
    assert _contar(db_session, Venta) == ventas and [f.estado for f in _filas_de_pedido(db_session)] == ["incierto"]
    assert _reservado(db_session, listo) == 0 and pp.cobros_vault == 1  # PayPal SÍ cobró

    monkeypatch.setattr(cu13, "registrar_cobro_pasarela_aprobado", original)
    reintento = _enviar(client, cliente_headers, cuerpo)

    assert reintento.status_code == 200 and reintento.json()["estado"] == "cobrado"
    assert pp.cobros_vault == 1  # el mismo cobro, no otro
    assert _contar(db_session, Venta) == ventas + 1


# ---- cobro incierto que se confirma: lo cobrado nunca se pierde ni se niega ----


def test_si_paypal_cobro_y_el_stock_se_agoto_antes_del_reintento_el_pedido_queda_para_reembolso(
    client, db_session, admin_headers, cliente_headers, listo, pp, caplog
):
    """PayPal SÍ cobró (la respuesta se perdió) y, antes del reintento, alguien se llevó el stock. Antes el reintento
    guardaba un rechazo FINAL con "tu pedido no se cobró": mentira, y sin rastro del dinero. Ahora el cliente recibe la
    verdad y queda un log de ERROR con el monto y la orden para devolverlo."""
    ctx = listo
    ventas = _contar(db_session, Venta)
    cuerpo = _cuerpo(ctx, cantidad=2)
    pp.perder_respuestas_de_cobro = 1
    assert _enviar(client, cliente_headers, cuerpo).status_code == 503 and pp.cobros_vault == 1
    _agotar(client, ctx, admin_headers, ctx["m"])

    with caplog.at_level("ERROR", logger="app.comercial.casos_uso.cu13_gestionar_carrito_compra_digital"):
        respuesta = _enviar(client, cliente_headers, cuerpo)

    assert respuesta.status_code == 200, respuesta.text
    datos = respuesta.json()
    assert (datos["estado"], datos["motivo"]) == ("rechazado", "cobro_a_reembolsar")
    assert "Cobramos Bs 200.00" in datos["mensaje"] and "devolveremos" in datos["mensaje"]
    assert "no se cobró" not in datos["mensaje"].lower() and datos["venta_id"] is None
    assert pp.cobros_vault == 1  # no se cobró otra vez
    assert _contar(db_session, Venta) == ventas and _reservado(db_session, ctx) == 0
    (fila,) = _filas_de_pedido(db_session)
    assert fila.estado == "rechazado" and fila.motivo == "cobro_a_reembolsar" and fila.total == 200
    assert "pedido_diferido_cobro_a_reembolsar" in caplog.text and "total_usd=" in caplog.text and "orden=" in caplog.text
    avisos = [n.titulo for n in db_session.scalars(select(Notificacion).order_by(Notificacion.id))]
    assert avisos[-1] == "No pudimos completar tu pedido"  # no dice "no pudimos cobrar": SÍ se cobró
    again = _enviar(client, cliente_headers, cuerpo).json()  # decisión final: un reenvío devuelve lo mismo
    assert again["motivo"] == "cobro_a_reembolsar" and again["duplicada"] is True and pp.cobros_vault == 1


def test_si_el_precio_cambio_entre_el_cobro_incierto_y_el_reintento_se_marca_para_reembolso(
    client, db_session, admin_headers, cliente_headers, listo, pp
):
    """Lo cobrado fue por Bs 200; si el precio sube, la venta ya no coincide con lo cobrado: no se entrega por menos ni se
    cobra de más. Se devuelve el dinero."""
    from decimal import Decimal

    ctx = listo
    cuerpo = _cuerpo(ctx, cantidad=2)
    pp.perder_respuestas_de_cobro = 1
    assert _enviar(client, cliente_headers, cuerpo).status_code == 503
    producto = db_session.scalar(select(ProductoVariante).where(ProductoVariante.id == ctx["m"])).producto
    producto.precio_base = Decimal("150.00")
    db_session.commit()

    respuesta = _enviar(client, cliente_headers, cuerpo)

    assert respuesta.status_code == 200
    assert respuesta.json()["motivo"] == "cobro_a_reembolsar" and "precio cambió" in respuesta.json()["mensaje"]
    assert pp.cobros_vault == 1 and _reservado(db_session, ctx) == 0


def test_si_paypal_confirma_que_no_cobro_la_marca_se_descarta_y_el_pedido_sigue_como_nuevo(
    client, db_session, cliente_headers, listo, pp
):
    ctx = listo
    cuerpo = _cuerpo(ctx, cantidad=2)
    pp.caer_en = {"crear"}
    assert _enviar(client, cliente_headers, cuerpo).status_code == 503
    assert [f.estado for f in _filas_de_pedido(db_session)] == ["incierto"]
    pp.caer_en = set()
    pp.rechazar_cobro_vault = "INSTRUMENT_DECLINED"  # al preguntar, PayPal dice con claridad que NO cobró

    respuesta = _enviar(client, cliente_headers, cuerpo)

    assert respuesta.status_code == 200
    assert (respuesta.json()["estado"], respuesta.json()["motivo"]) == ("rechazado", "pago_rechazado")
    assert pp.cobros_vault == 0
    (fila,) = _filas_de_pedido(db_session)  # la marca no quedó: solo la decisión final
    assert fila.estado == "rechazado" and fila.motivo == "pago_rechazado"


def test_sin_paypal_guardado_la_marca_no_se_puede_conciliar_y_se_conserva(
    client, db_session, cliente_headers, listo, pp
):
    cuerpo = _cuerpo(listo, cantidad=2)
    pp.perder_respuestas_de_cobro = 1
    assert _enviar(client, cliente_headers, cuerpo).status_code == 503
    assert client.delete("/api/v1/metodos-pago/paypal", headers=cliente_headers).status_code == 204

    respuesta = _enviar(client, cliente_headers, cuerpo)

    assert respuesta.status_code == 503  # sin el token no se puede preguntar a PayPal: no se decide nada
    assert [f.estado for f in _filas_de_pedido(db_session)] == ["incierto"]


def test_la_marca_incierta_de_otra_persona_se_ve_inexistente(client, db_session, cliente_headers, listo, pp):
    cuerpo = _cuerpo(listo, cantidad=2)
    pp.perder_respuestas_de_cobro = 1
    assert _enviar(client, cliente_headers, cuerpo).status_code == 503
    otro = _otro_cliente(client)

    respuesta = _enviar(client, otro, cuerpo)

    assert respuesta.status_code == 404
    assert [f.estado for f in _filas_de_pedido(db_session)] == ["incierto"]


def test_la_marca_incierta_nunca_se_ve_en_la_respuesta_ni_cuenta_para_el_limite(client, db_session, cliente_headers, listo, pp):
    cuerpo = _cuerpo(listo, cantidad=1)
    pp.perder_respuestas_de_cobro = 1
    primera = _enviar(client, cliente_headers, cuerpo)

    assert primera.status_code == 503 and "incierto" not in primera.text
    assert _enviar(client, cliente_headers, cuerpo).status_code == 200  # el reintento concilia sin gastar el límite


# ---- validación del cuerpo y permisos ----


@pytest.mark.parametrize(
    "cambio",
    [
        {"total_maximo": "0"},
        {"total_maximo": "-5.00"},
        {"costo_envio": "-1"},
        {"operacion_id": "no-es-un-uuid"},
        {"lineas": []},
        {"campo_extra": 1},
    ],
)
def test_un_cuerpo_mal_formado_da_422(client, cliente_headers, listo, pp, cambio):
    assert _enviar(client, cliente_headers, {**_cuerpo(listo), **cambio}).status_code == 422
    assert pp.cuerpos_de_cobro_vault == []


def test_una_prenda_repetida_o_una_cantidad_cero_dan_422(client, cliente_headers, listo, pp):
    repetida = _cuerpo(listo)
    repetida["lineas"].append({"variante_id": listo["m"], "cantidad": 1})
    cero = _cuerpo(listo, cantidad=0)

    assert _enviar(client, cliente_headers, repetida).status_code == 422
    assert _enviar(client, cliente_headers, cero).status_code == 422


def test_una_sucursal_o_prenda_inexistente_da_404_y_no_deja_filas(client, db_session, cliente_headers, listo, pp):
    sin_sucursal = {**_cuerpo(listo), "sucursal_id": 999999}
    sin_prenda = _cuerpo(listo, variante=999999)

    assert _enviar(client, cliente_headers, sin_sucursal).status_code == 404
    assert _enviar(client, cliente_headers, sin_prenda).status_code == 404
    assert _contar(db_session, PedidoDiferido) == 0 and pp.cuerpos_de_cobro_vault == []


def test_sin_sesion_responde_401(client, listo):
    assert client.post(URL, json=_cuerpo(listo)).status_code == 401


def test_el_personal_sin_permiso_de_compra_digital_recibe_403(client, listo, pp):
    assert client.post(URL, json=_cuerpo(listo), headers=listo["cajero_headers"]).status_code == 403


# ---- avisos: notificación y correo ----


def test_el_cliente_recibe_una_notificacion_que_puede_leer(client, db_session, cliente_headers, listo, pp):
    datos = _enviar(client, cliente_headers, _cuerpo(listo)).json()

    notificaciones = client.get("/api/v1/notificaciones", headers=cliente_headers).json()

    assert [(n["tipo"], n["titulo"], n["leida"]) for n in notificaciones] == [("pedido_diferido", "Cobramos tu pedido", False)]
    assert datos["codigo_venta"] in notificaciones[0]["mensaje"] and "Bs 200.00" in notificaciones[0]["mensaje"]
    assert notificaciones[0]["referencia_id"] == datos["venta_id"]
    marcada = client.put(f"/api/v1/notificaciones/{notificaciones[0]['id']}/leida", headers=cliente_headers)
    assert marcada.status_code == 200 and marcada.json()["leida"] is True


def test_un_rechazo_tambien_avisa_dentro_del_sistema(client, cliente_headers, ctx, pp):
    _enviar(client, cliente_headers, _cuerpo(ctx))  # sin PayPal guardado

    (aviso,) = client.get("/api/v1/notificaciones", headers=cliente_headers).json()

    assert aviso["tipo"] == "pedido_diferido" and aviso["titulo"] == "No pudimos cobrar tu pedido"
    assert aviso["referencia_id"] is None and "PayPal" in aviso["mensaje"]


def test_un_reenvio_no_duplica_el_aviso(client, cliente_headers, listo, pp):
    cuerpo = _cuerpo(listo)
    _enviar(client, cliente_headers, cuerpo)
    _enviar(client, cliente_headers, cuerpo)

    assert len(client.get("/api/v1/notificaciones", headers=cliente_headers).json()) == 1


def test_el_cliente_recibe_un_correo_al_cobrarse(client, cliente_headers, listo, pp, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch)

    datos = _enviar(client, cliente_headers, _cuerpo(listo)).json()

    assert len(brevo.enviados) == 1
    correo = brevo.ultimo()
    assert correo["to"][0]["email"] == "cliente@example.com"
    assert datos["codigo_venta"] in correo["subject"] and "Cobramos tu pedido" in correo["subject"]
    assert "Bs 200.00" in correo["textContent"] and "Sucursal Cambio" in correo["textContent"]
    assert datos["codigo_venta"] in correo["textContent"]


def test_el_correo_de_un_rechazo_dice_el_motivo_en_palabras(client, cliente_headers, ctx, pp, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch)

    _enviar(client, cliente_headers, _cuerpo(ctx))  # sin PayPal guardado

    (correo,) = brevo.enviados
    assert "No pudimos cobrar tu pedido" in correo["subject"]
    assert "no tienes un PayPal guardado" in correo["textContent"] and "No se te cobró nada" in correo["textContent"]


def test_sin_brevo_el_pedido_se_cobra_igual(client, cliente_headers, listo, pp, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch, configurado=False)

    datos = _enviar(client, cliente_headers, _cuerpo(listo)).json()

    assert datos["estado"] == "cobrado" and brevo.enviados == []


def test_si_brevo_falla_el_pedido_no_se_ve_afectado(client, cliente_headers, listo, pp, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch)
    brevo.caido = True

    respuesta = _enviar(client, cliente_headers, _cuerpo(listo))

    assert respuesta.status_code == 200 and respuesta.json()["estado"] == "cobrado"


def test_un_reenvio_no_manda_otro_correo(client, cliente_headers, listo, pp, monkeypatch):
    brevo = SimuladorBrevo(monkeypatch)
    cuerpo = _cuerpo(listo)
    _enviar(client, cliente_headers, cuerpo)
    _enviar(client, cliente_headers, cuerpo)

    assert len(brevo.enviados) == 1


# ---- bitácora y registro ----


def test_la_bitacora_registra_el_cobro_y_el_rechazo_sin_datos_personales(client, db_session, cliente_headers, listo, pp):
    cobrado = _enviar(client, cliente_headers, _cuerpo(listo)).json()
    pp.rechazar_cobro_vault = "INSTRUMENT_DECLINED"
    _enviar(client, cliente_headers, _cuerpo(listo))

    db_session.expire_all()
    filas = list(db_session.scalars(select(Bitacora).where(Bitacora.entidad == "pedido_diferido").order_by(Bitacora.id)))
    assert [f.accion for f in filas] == ["cobrar", "rechazar"]
    assert filas[0].datos == {"venta_id": cobrado["venta_id"], "lineas": 1, "unidades": 2}
    assert filas[1].datos == {"motivo": "pago_rechazado", "lineas": 1}
    assert "cliente@example.com" not in str([f.datos for f in filas])


def test_el_pedido_guarda_su_resultado_final(client, db_session, cliente_headers, listo, pp):
    cuerpo = _cuerpo(listo, cantidad=2)
    datos = _enviar(client, cliente_headers, cuerpo).json()

    db_session.expire_all()
    (fila,) = db_session.scalars(select(PedidoDiferido)).all()
    assert str(fila.operacion_id) == cuerpo["operacion_id"] and fila.estado == "cobrado" and fila.motivo is None
    assert fila.venta_id == datos["venta_id"] and fila.total == 200 and str(fila.total_usd) == "28.74"
    assert fila.sucursal_id == listo["sucursal_id"] and fila.creado_en is not None
    assert len(db_session.scalars(select(Notificacion)).all()) == 1
