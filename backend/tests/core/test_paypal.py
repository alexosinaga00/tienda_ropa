"""core/paypal.py: el cliente compartido de PayPal, con httpx simulado (jamás sale a la red)."""

import base64
from decimal import Decimal

import httpx
import pytest

from app.core import paypal
from app.core.config import get_settings
from tests.paypal_simulado import SimuladorPayPal


@pytest.fixture()
def pp(monkeypatch) -> SimuladorPayPal:
    return SimuladorPayPal(monkeypatch)


def _crear(**extra):
    datos = dict(
        monto=Decimal("17.24"),
        moneda="USD",
        referencia="PED-1",
        descripcion="Plan Básico (mensual)",
        return_url="https://tienda.example.com/retorno?pedido=x",
        cancel_url="https://tienda.example.com/retorno?pedido=x&cancelado=1",
    )
    datos.update(extra)
    return paypal.crear_orden(**datos)


# ---- Token y URL base ---------------------------------------------------------------------------------------------


def test_el_token_se_pide_con_las_credenciales_en_basic(pp):
    assert paypal.obtener_token() == "token-simulado"
    (metodo, ruta) = pp.peticiones[0]
    assert (metodo, ruta) == ("POST", "/v1/oauth2/token")


def test_el_cuerpo_del_token_es_client_credentials_y_la_cabecera_basic_lleva_id_y_secreto(monkeypatch):
    vistas = []

    def manejar(peticion: httpx.Request) -> httpx.Response:
        vistas.append(peticion)
        return httpx.Response(200, json={"access_token": "T"})

    SimuladorPayPal(monkeypatch)
    monkeypatch.setattr(paypal, "_crear_cliente", lambda: httpx.Client(transport=httpx.MockTransport(manejar)))

    assert paypal.obtener_token() == "T"

    (peticion,) = vistas
    esperado = base64.b64encode(b"cliente-simulado:secreto-simulado").decode()
    assert peticion.headers["Authorization"] == f"Basic {esperado}"
    assert peticion.content == b"grant_type=client_credentials"
    assert peticion.headers["Content-Type"] == "application/x-www-form-urlencoded"


def test_la_url_base_sigue_a_paypal_mode(monkeypatch):
    ajustes = get_settings()
    monkeypatch.setattr(ajustes, "paypal_mode", "sandbox")
    assert paypal.url_base() == "https://api-m.sandbox.paypal.com"
    monkeypatch.setattr(ajustes, "paypal_mode", "live")
    assert paypal.url_base() == "https://api-m.paypal.com"


def test_sin_credenciales_no_hay_llamada_y_el_error_es_un_runtime_error(monkeypatch):
    pp = SimuladorPayPal(monkeypatch, con_credenciales=False)  # tests/conftest.py las deja vacías
    with pytest.raises(RuntimeError) as error:
        _crear()
    assert isinstance(error.value, paypal.PayPalError)
    assert "PAYPAL_CLIENT_ID" in str(error.value) and error.value.causa is None
    assert pp.peticiones == []


# ---- Crear la orden -----------------------------------------------------------------------------------------------


def test_crear_orden_devuelve_el_id_y_la_url_de_aprobacion(pp):
    orden = _crear()

    id_orden, url = orden  # se desempaqueta como (id, url)
    assert id_orden == orden.id == "ORD-SIM-0001"
    assert url == orden.url_aprobacion == "https://www.sandbox.paypal.com/checkoutnow?token=ORD-SIM-0001"


def test_crear_orden_envia_el_monto_la_moneda_y_las_urls_de_retorno(pp):
    _crear(request_id="clave-1")

    (cuerpo,) = pp.cuerpos_de_creacion
    assert cuerpo["intent"] == "CAPTURE"
    unidad = cuerpo["purchase_units"][0]
    assert unidad["reference_id"] == "PED-1"
    assert unidad["amount"] == {"currency_code": "USD", "value": "17.24"}
    assert unidad["description"] == "Plan Básico (mensual)"
    contexto = cuerpo["payment_source"]["paypal"]["experience_context"]
    assert contexto["return_url"] == "https://tienda.example.com/retorno?pedido=x"
    assert contexto["cancel_url"].endswith("&cancelado=1")
    assert (contexto["landing_page"], contexto["user_action"]) == ("GUEST_CHECKOUT", "PAY_NOW")


def test_sin_descripcion_el_cuerpo_no_la_lleva_y_una_larga_se_recorta(pp):
    _crear(descripcion=None)
    _crear(descripcion="x" * 300)

    sin, larga = (c["purchase_units"][0] for c in pp.cuerpos_de_creacion)
    assert "description" not in sin
    assert len(larga["description"]) == paypal.LARGO_MAXIMO_DESCRIPCION


def test_crear_orden_acepta_el_link_approve_antiguo(monkeypatch):
    def manejar(peticion: httpx.Request) -> httpx.Response:
        if peticion.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T"})
        return httpx.Response(201, json={"id": "O1", "links": [{"rel": "approve", "href": "https://aprobar.example.com/O1"}]})

    SimuladorPayPal(monkeypatch)
    monkeypatch.setattr(paypal, "_crear_cliente", lambda: httpx.Client(transport=httpx.MockTransport(manejar)))

    assert _crear().url_aprobacion == "https://aprobar.example.com/O1"


# ---- Consultar y capturar -----------------------------------------------------------------------------------------


def test_obtener_orden_informa_estado_monto_y_moneda(pp):
    orden = _crear()

    antes = paypal.obtener_orden(orden.id)
    assert (antes.estado, antes.monto, antes.moneda, antes.estado_captura) == ("CREATED", Decimal("17.24"), "USD", None)

    pp.aprobar()
    assert paypal.obtener_orden(orden.id).estado == "APPROVED"


def test_obtener_orden_inexistente_es_un_paypal_error_con_el_estado_http(pp):
    with pytest.raises(paypal.PayPalError) as error:
        paypal.obtener_orden("NO-EXISTE")
    assert error.value.status_code == 404 and isinstance(error.value.causa, httpx.HTTPStatusError)


def test_capturar_manda_la_clave_de_idempotencia_y_devuelve_el_resultado(pp):
    orden = _crear()
    pp.aprobar()

    resultado = paypal.capturar_orden(orden.id, "clave-captura-1")

    assert (resultado.estado, resultado.estado_captura) == ("COMPLETED", "COMPLETED")
    assert (resultado.monto, resultado.moneda) == (Decimal("17.24"), "USD")  # los de la captura
    (cabeceras,) = pp.cabeceras_de_captura
    assert cabeceras["paypal-request-id"] == "clave-captura-1"
    assert cabeceras["authorization"] == "Bearer token-simulado"
    assert pp.capturas == 1


def test_repetir_la_captura_con_la_misma_clave_no_cobra_dos_veces(pp):
    orden = _crear()
    pp.aprobar()

    primera = paypal.capturar_orden(orden.id, "clave-captura-1")
    segunda = paypal.capturar_orden(orden.id, "clave-captura-1")

    assert primera == segunda
    assert pp.capturas == 1 and pp.peticiones_de_captura == 2


def test_order_already_captured_se_trata_como_orden_ya_capturada(pp):
    orden = _crear()
    pp.aprobar()
    paypal.capturar_orden(orden.id, "clave-A")

    resultado = paypal.capturar_orden(orden.id, "clave-B")  # otra clave: PayPal responde 422 ORDER_ALREADY_CAPTURED

    assert (resultado.estado, resultado.estado_captura) == ("COMPLETED", "COMPLETED")
    assert pp.capturas == 1
    assert pp.llamadas("GET", "/v2/checkout/orders/") == 1  # la consultó para devolverla


def test_con_tratar_ya_capturada_apagado_el_error_se_propaga_con_su_problema(pp):
    orden = _crear()
    pp.aprobar()
    paypal.capturar_orden(orden.id, "clave-A")

    with pytest.raises(paypal.PayPalError) as error:
        paypal.capturar_orden(orden.id, "clave-B", tratar_ya_capturada=False)
    assert error.value.status_code == 422 and "ORDER_ALREADY_CAPTURED" in error.value.problemas


def test_capturar_una_orden_sin_aprobar_es_un_error_de_paypal(pp):
    orden = _crear()
    with pytest.raises(paypal.PayPalError) as error:
        paypal.capturar_orden(orden.id, "clave")
    assert error.value.status_code == 422 and "ORDER_NOT_APPROVED" in error.value.problemas
    assert pp.capturas == 0


def test_capturar_sin_clave_no_manda_la_cabecera(pp):
    orden = _crear()
    pp.aprobar()
    paypal.capturar_orden(orden.id)
    assert "paypal-request-id" not in pp.cabeceras_de_captura[0]


# ---- Errores de red y de contenido --------------------------------------------------------------------------------


def test_un_fallo_de_red_es_un_paypal_error_sin_estado_http(pp):
    pp.caido = True
    with pytest.raises(paypal.PayPalError) as error:
        paypal.obtener_orden("O1")
    assert isinstance(error.value, RuntimeError)
    assert error.value.status_code is None and isinstance(error.value.causa, httpx.ConnectError)


def test_un_error_http_5xx_es_un_paypal_error_con_su_estado(monkeypatch):
    SimuladorPayPal(monkeypatch)
    monkeypatch.setattr(
        paypal,
        "_crear_cliente",
        lambda: httpx.Client(
            transport=httpx.MockTransport(
                lambda p: httpx.Response(200, json={"access_token": "T"})
                if p.url.path == "/v1/oauth2/token"
                else httpx.Response(503, text="no disponible")
            )
        ),
    )
    with pytest.raises(paypal.PayPalError) as error:
        paypal.obtener_orden("O1")
    assert error.value.status_code == 503 and error.value.problemas == ()


@pytest.mark.parametrize("cuerpo", [b"esto no es json", b"[1, 2]", b"{}"])
def test_una_respuesta_ilegible_o_incompleta_es_un_paypal_error(monkeypatch, cuerpo):
    SimuladorPayPal(monkeypatch)
    monkeypatch.setattr(
        paypal,
        "_crear_cliente",
        lambda: httpx.Client(
            transport=httpx.MockTransport(
                lambda p: httpx.Response(200, json={"access_token": "T"})
                if p.url.path == "/v1/oauth2/token"
                else httpx.Response(200, content=cuerpo)
            )
        ),
    )
    with pytest.raises(paypal.PayPalError):
        paypal.obtener_orden("O1")


def test_el_token_rechazado_es_un_paypal_error(monkeypatch):
    SimuladorPayPal(monkeypatch)
    monkeypatch.setattr(
        paypal, "_crear_cliente", lambda: httpx.Client(transport=httpx.MockTransport(lambda p: httpx.Response(401, json={})))
    )
    with pytest.raises(paypal.PayPalError) as error:
        paypal.obtener_token()
    assert error.value.status_code == 401


def test_el_cuerpo_de_las_peticiones_no_se_registra_en_el_log(pp, caplog):
    caplog.set_level("DEBUG")
    _crear()
    assert "17.24" not in caplog.text and "cliente-simulado" not in caplog.text
