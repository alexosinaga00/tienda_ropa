"""PayPalGateway tras pasar a usar `core/paypal.py`: mismo comportamiento observable que antes del refactor
(firmas, resultados y mensajes de error), con PayPal simulado (jamás sale a la red)."""

from decimal import Decimal

import pytest

from app.comercial.pasarela import PayPalGateway, ResultadoIniciar, obtener_pasarela
from tests.paypal_simulado import SimuladorPayPal


@pytest.fixture()
def pp(monkeypatch) -> SimuladorPayPal:
    return SimuladorPayPal(monkeypatch)


def test_iniciar_pago_crea_la_orden_y_devuelve_su_id_y_la_url(pp):
    resultado = obtener_pasarela("paypal").iniciar_pago(monto=Decimal("100.50"), referencia="VTA-1")

    assert resultado == ResultadoIniciar(
        id_transaccion="ORD-SIM-0001",
        url_redireccion="https://www.sandbox.paypal.com/checkoutnow?token=ORD-SIM-0001",
        monto_usd=Decimal("14.44"),
    )
    (cuerpo,) = pp.cuerpos_de_creacion
    unidad = cuerpo["purchase_units"][0]
    # El total (Bs) se CONVIERTE a dólares con el tipo de cambio (6,96): 100,50 / 6,96 = 14,44. Antes se mandaba 100.50 USD.
    assert unidad["reference_id"] == "VTA-1" and unidad["amount"] == {"currency_code": "USD", "value": "14.44"}
    assert "description" not in unidad
    contexto = cuerpo["payment_source"]["paypal"]["experience_context"]
    assert contexto["return_url"] == "https://fashionstore.example.com/pago/retorno"
    assert contexto["cancel_url"] == "https://fashionstore.example.com/pago/cancelado"
    assert (contexto["landing_page"], contexto["user_action"]) == ("GUEST_CHECKOUT", "PAY_NOW")


@pytest.mark.parametrize(
    ("total_bs", "tipo_cambio", "esperado"),
    [
        ("696.00", "6.96", "100.00"),
        ("100.00", "6.96", "14.37"),
        ("1.00", "6.96", "0.14"),
        ("129.00", "10", "12.90"),
        ("0.01", "6.96", None),  # en dólares quedaría en cero: PayPal no cobra 0
    ],
)
def test_el_total_en_bolivianos_se_convierte_a_dolares(pp, monkeypatch, total_bs, tipo_cambio, esperado):
    from app.comercial.pasarela import monto_en_usd
    from app.core.config import get_settings
    from app.core.exceptions import DomainError

    monkeypatch.setattr(get_settings(), "tipo_cambio_bs_por_usd", Decimal(tipo_cambio))
    if esperado is None:
        with pytest.raises(DomainError):
            monto_en_usd(Decimal(total_bs))
        return

    monto_usd, usado = monto_en_usd(Decimal(total_bs))
    assert monto_usd == Decimal(esperado) and usado == Decimal(tipo_cambio).quantize(Decimal("0.0001"))
    PayPalGateway().iniciar_pago(monto=Decimal(total_bs), referencia="VTA-9")
    assert pp.cuerpos_de_creacion[-1]["purchase_units"][0]["amount"]["value"] == esperado


def test_sin_tipo_de_cambio_no_se_cobra(pp, monkeypatch):
    from app.comercial.pasarela import monto_en_usd
    from app.core.config import get_settings
    from app.core.exceptions import ErrorFuncional

    monkeypatch.setattr(get_settings(), "tipo_cambio_bs_por_usd", Decimal("0"))
    with pytest.raises(ErrorFuncional):
        monto_en_usd(Decimal("100"))
    assert pp.cuerpos_de_creacion == []


def test_sin_credenciales_iniciar_pago_da_el_mismo_runtime_error_de_siempre(monkeypatch):
    SimuladorPayPal(monkeypatch, con_credenciales=False)
    with pytest.raises(RuntimeError, match="PAYPAL_CLIENT_ID/PAYPAL_CLIENT_SECRET no están configurados"):
        PayPalGateway().iniciar_pago(monto=Decimal("10"), referencia="VTA-1")


def test_un_fallo_de_paypal_al_iniciar_se_informa_con_el_mensaje_de_siempre(pp):
    pp.caido = True
    with pytest.raises(RuntimeError, match="^No se pudo iniciar el pago con PayPal: "):
        PayPalGateway().iniciar_pago(monto=Decimal("10"), referencia="VTA-1")


def test_consultar_estado_de_una_orden_sin_aprobar_sigue_iniciado(pp):
    pasarela = PayPalGateway()
    orden = pasarela.iniciar_pago(monto=Decimal("10"), referencia="VTA-1").id_transaccion

    assert pasarela.consultar_estado(orden) == "iniciado"
    assert pp.capturas == 0


def test_consultar_estado_de_una_orden_aprobada_la_captura_y_responde_aprobado(pp):
    pasarela = PayPalGateway()
    orden = pasarela.iniciar_pago(monto=Decimal("10"), referencia="VTA-1").id_transaccion
    pp.aprobar()

    assert pasarela.consultar_estado(orden) == "aprobado"
    assert pp.capturas == 1
    assert "paypal-request-id" not in pp.cabeceras_de_captura[0]  # como antes: sin clave de idempotencia

    assert pasarela.consultar_estado(orden) == "aprobado"  # ya COMPLETED: no vuelve a capturar
    assert pp.capturas == 1 and pp.peticiones_de_captura == 1


def test_si_paypal_rechaza_la_captura_sigue_iniciado(pp):
    pasarela = PayPalGateway()
    orden = pasarela.iniciar_pago(monto=Decimal("10"), referencia="VTA-1").id_transaccion
    pp.aprobar()
    pp.rechazar_captura = True

    assert pasarela.consultar_estado(orden) == "iniciado"
    assert pp.capturas == 0


def test_si_otra_captura_gano_la_carrera_sigue_iniciado_y_la_siguiente_consulta_ve_aprobado(pp):
    """PayPal contesta ORDER_ALREADY_CAPTURED a la captura: el gateway NO lo trata como éxito (como antes del
    refactor; solo la compra de un plan lo hace). La consulta siguiente ve la orden COMPLETED."""
    pasarela = PayPalGateway()
    orden = pasarela.iniciar_pago(monto=Decimal("10"), referencia="VTA-1").id_transaccion
    pp.aprobar()
    pp.ordenes[orden]["status"] = "COMPLETED"  # la ganó otra captura (webhook, otra pestaña...)
    pp.ordenes[orden]["request_id_captura"] = "de-otro"
    pp.estado_en_consulta = "APPROVED"  # pero esta consulta todavía vio la orden aprobada

    assert pasarela.consultar_estado(orden) == "iniciado"

    pp.estado_en_consulta = None
    assert pasarela.consultar_estado(orden) == "aprobado"


def test_una_orden_anulada_es_rechazado(pp):
    pasarela = PayPalGateway()
    orden = pasarela.iniciar_pago(monto=Decimal("10"), referencia="VTA-1").id_transaccion
    pp.anular()

    assert pasarela.consultar_estado(orden) == "rechazado"


def test_un_fallo_de_paypal_al_consultar_se_informa_con_el_mensaje_de_siempre(pp):
    pasarela = PayPalGateway()
    orden = pasarela.iniciar_pago(monto=Decimal("10"), referencia="VTA-1").id_transaccion
    pp.caido = True

    with pytest.raises(RuntimeError, match="^No se pudo consultar el estado en PayPal: "):
        pasarela.consultar_estado(orden)


def test_una_captura_que_falla_por_red_se_informa_como_error_de_consulta(pp):
    pasarela = PayPalGateway()
    orden = pasarela.iniciar_pago(monto=Decimal("10"), referencia="VTA-1").id_transaccion
    pp.aprobar()
    pp.caer_en = {"capturar"}

    with pytest.raises(RuntimeError, match="^No se pudo consultar el estado en PayPal: "):
        pasarela.consultar_estado(orden)


def test_el_webhook_sigue_siendo_el_hmac_de_sandbox():
    pasarela = PayPalGateway()
    assert pasarela.verificar_firma(b"{}", None) is False
    assert pasarela.nombre == "paypal"
