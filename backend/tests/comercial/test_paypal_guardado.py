"""CU-18: el cliente guarda su PayPal (Vault v3) UNA vez, con conexión, para que después se le pueda cobrar sin conexión.

Dos pasos: `iniciar` (el servidor crea el setup token en PayPal y el cliente aprueba allá) y `confirmar` (el servidor
cambia ese token por el payment token y lo guarda). Solo hay UN método activo por usuario. El correo de PayPal sale
ENMASCARADO y los tokens no salen jamás. PayPal es simulado (`tests/paypal_simulado.py`): ninguna prueba sale a la red.
NO se probó contra el sandbox real de PayPal."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.comercial.models import MetodoPagoGuardado
from app.core import paypal
from app.core.config import get_settings
from app.plataforma.models import Bitacora
from tests.conftest import EMPRESA_DEFECTO
from tests.paypal_simulado import SimuladorPayPal

URL = "/api/v1/metodos-pago/paypal"
RETORNO = "http://localhost:4200/t/fashionstore/mi-cuenta/paypal-guardado"


@pytest.fixture()
def pp(monkeypatch) -> SimuladorPayPal:
    return SimuladorPayPal(monkeypatch)


def _iniciar(client, headers, canal="web"):
    return client.post(f"{URL}/iniciar", json={"canal": canal}, headers=headers)


def _confirmar(client, headers, token: str):
    return client.post(f"{URL}/confirmar", json={"token_preparacion": token}, headers=headers)


def _guardar(client, headers) -> dict:
    token = _iniciar(client, headers).json()["token_preparacion"]
    respuesta = _confirmar(client, headers, token)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _otro_cliente(client, email="otro@example.com") -> dict:
    cuerpo = {"nombre": "Otro", "apellido": "Cliente", "email": email, "password": "claveSegura123"}
    assert client.post(f"/api/v1/public/{EMPRESA_DEFECTO}/registro", json=cuerpo).status_code == 201
    login = client.post(
        "/api/v1/auth/login", json={"empresa": EMPRESA_DEFECTO, "email": email, "password": "claveSegura123"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _filas(db_session) -> list[MetodoPagoGuardado]:
    db_session.expire_all()
    return list(db_session.scalars(select(MetodoPagoGuardado).order_by(MetodoPagoGuardado.id)))


# ---- consultar ----


def test_sin_nada_guardado_el_estado_es_no_guardado(client, cliente_headers, pp):
    respuesta = client.get(URL, headers=cliente_headers)

    assert respuesta.status_code == 200
    assert respuesta.json() == {"guardado": False, "correo_paypal": None, "guardado_en": None}


def test_sin_sesion_responde_401(client, pp):
    assert client.get(URL).status_code == 401
    assert client.delete(URL).status_code == 401
    assert client.post(f"{URL}/iniciar", json={"canal": "web"}).status_code == 401


# ---- iniciar ----


def test_iniciar_crea_el_setup_token_con_las_urls_que_arma_el_servidor(client, db_session, cliente_headers, pp):
    respuesta = _iniciar(client, cliente_headers, canal="app")

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["token_preparacion"] == "ST-SIM-0001"
    assert cuerpo["url_aprobacion"] == "https://sandbox.paypal.com/agreements/approve?approval_session_id=ST-SIM-0001"
    fuente = pp.setup_tokens["ST-SIM-0001"]["cuerpo"]["payment_source"]["paypal"]
    assert fuente["usage_type"] == "MERCHANT" and fuente["customer_type"] == "CONSUMER"
    assert fuente["usage_pattern"] == "UNSCHEDULED_POSTPAID"
    assert fuente["experience_context"] == {"return_url": RETORNO, "cancel_url": f"{RETORNO}?cancelado=1"}
    (fila,) = _filas(db_session)
    assert (fila.estado, fila.setup_token_id, fila.payment_token_id) == ("pendiente", "ST-SIM-0001", None)


def test_el_cliente_no_puede_mandar_urls_ni_otros_campos(client, cliente_headers, pp):
    assert client.post(f"{URL}/iniciar", json={"canal": "web", "return_url": "https://malo.example"}, headers=cliente_headers).status_code == 422
    assert client.post(f"{URL}/iniciar", json={"canal": "escritorio"}, headers=cliente_headers).status_code == 422
    assert client.post(f"{URL}/iniciar", json={}, headers=cliente_headers).status_code == 422
    assert pp.setup_tokens == {}


def test_iniciar_con_paypal_caido_da_503_y_no_deja_fila(client, db_session, cliente_headers, pp):
    pp.caido = True

    respuesta = _iniciar(client, cliente_headers)

    assert respuesta.status_code == 503
    assert respuesta.json()["codigo"] == "paypal_no_disponible"
    assert _filas(db_session) == []


def test_un_intento_nuevo_cancela_los_anteriores(client, db_session, cliente_headers, pp):
    primero = _iniciar(client, cliente_headers).json()["token_preparacion"]
    segundo = _iniciar(client, cliente_headers).json()["token_preparacion"]

    assert _confirmar(client, cliente_headers, primero).status_code == 404  # ya no sirve
    assert _confirmar(client, cliente_headers, segundo).status_code == 200
    assert [f.estado for f in _filas(db_session)] == ["revocado", "activo"]


def test_hay_un_limite_de_inicios_por_cuenta(client, cliente_headers, pp, monkeypatch):
    monkeypatch.setattr(get_settings(), "paypal_guardado_max_por_ventana", 2)
    assert _iniciar(client, cliente_headers).status_code == 201
    assert _iniciar(client, cliente_headers).status_code == 201

    respuesta = _iniciar(client, cliente_headers)

    assert respuesta.status_code == 429
    assert int(respuesta.headers["Retry-After"]) >= 1
    assert len(pp.setup_tokens) == 2  # el tercero ni llegó a PayPal


# ---- confirmar ----


def test_confirmar_guarda_el_token_y_enmascara_el_correo(client, db_session, cliente_headers, pp):
    token = _iniciar(client, cliente_headers).json()["token_preparacion"]

    respuesta = _confirmar(client, cliente_headers, token)

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["guardado"] is True
    assert cuerpo["correo_paypal"] == "j***@gmail.com"
    assert cuerpo["guardado_en"].endswith("Z")
    # Nada sensible en la respuesta: ni el token de PayPal ni el correo completo.
    assert "VAULT-SIM" not in respuesta.text and "juan.perez" not in respuesta.text
    assert set(cuerpo) == {"guardado", "correo_paypal", "guardado_en"}
    assert client.get(URL, headers=cliente_headers).json() == cuerpo
    (fila,) = _filas(db_session)
    assert fila.estado == "activo" and fila.payment_token_id == "VAULT-SIM-0002"
    assert fila.correo_paypal == "j***@gmail.com" and "juan" not in fila.correo_paypal.replace("j***", "")
    assert fila.confirmado_en is not None


def test_si_paypal_no_informa_el_correo_queda_en_null(client, cliente_headers, pp):
    pp.correo_paypal = None

    cuerpo = _guardar(client, cliente_headers)

    assert cuerpo["guardado"] is True and cuerpo["correo_paypal"] is None


def test_confirmar_dos_veces_es_idempotente(client, cliente_headers, pp):
    token = _iniciar(client, cliente_headers).json()["token_preparacion"]
    primera = _confirmar(client, cliente_headers, token).json()

    segunda = _confirmar(client, cliente_headers, token)

    assert segunda.status_code == 200 and segunda.json() == primera
    assert pp.llamadas("POST", "/v3/vault/payment-tokens") == 1  # PayPal no se vuelve a llamar


def test_el_token_de_otra_persona_o_inexistente_da_404(client, db_session, cliente_headers, pp):
    token = _iniciar(client, cliente_headers).json()["token_preparacion"]
    otro = _otro_cliente(client)

    ajeno = _confirmar(client, otro, token)
    inexistente = _confirmar(client, otro, "ST-NO-EXISTE")

    assert ajeno.status_code == inexistente.status_code == 404
    assert ajeno.json() == inexistente.json()  # el token ajeno se ve igual que uno inexistente
    assert pp.llamadas("POST", "/v3/vault/payment-tokens") == 0
    assert client.get(URL, headers=otro).json()["guardado"] is False
    # El dueño sí puede confirmar su propio token.
    assert _confirmar(client, cliente_headers, token).status_code == 200


def test_el_token_debe_tener_forma_de_token(client, cliente_headers, pp):
    for malo in ("", "con espacios", "../../etc", "a" * 300):
        assert _confirmar(client, cliente_headers, malo).status_code == 422


def test_confirmar_sin_haber_aprobado_en_paypal_da_409_y_se_puede_reintentar(client, db_session, cliente_headers, pp):
    pp.aprobar_setup_al_crear = False
    token = _iniciar(client, cliente_headers).json()["token_preparacion"]

    respuesta = _confirmar(client, cliente_headers, token)

    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "paypal_no_aprobado"
    assert client.get(URL, headers=cliente_headers).json()["guardado"] is False
    pp.aprobar_setup(token)  # el cliente termina de aprobar en PayPal
    assert _confirmar(client, cliente_headers, token).status_code == 200
    assert _filas(db_session)[0].estado == "activo"


def test_confirmar_con_paypal_caido_da_503_y_despues_funciona(client, cliente_headers, pp):
    token = _iniciar(client, cliente_headers).json()["token_preparacion"]
    pp.caer_en = {"token"}

    respuesta = _confirmar(client, cliente_headers, token)

    assert respuesta.status_code == 503 and respuesta.json()["codigo"] == "paypal_no_disponible"
    assert client.get(URL, headers=cliente_headers).json()["guardado"] is False
    pp.caer_en = set()
    assert _confirmar(client, cliente_headers, token).status_code == 200


def test_guardar_otro_reemplaza_al_anterior_y_lo_revoca_en_paypal(client, db_session, cliente_headers, pp):
    _guardar(client, cliente_headers)
    primero = pp.ultimo_payment_token()
    pp.correo_paypal = "maria@outlook.com"

    segundo = _guardar(client, cliente_headers)

    assert segundo["correo_paypal"] == "m***@outlook.com"
    assert pp.tokens_borrados == [primero]  # el viejo se revocó en PayPal
    assert pp.payment_tokens[primero]["activo"] is False
    assert [f.estado for f in _filas(db_session)] == ["revocado", "activo"]
    assert client.get(URL, headers=cliente_headers).json()["correo_paypal"] == "m***@outlook.com"


def test_si_paypal_no_puede_revocar_al_anterior_el_reemplazo_igual_funciona(client, db_session, cliente_headers, pp):
    _guardar(client, cliente_headers)
    pp.caer_en = {"borrar"}

    segundo = _guardar(client, cliente_headers)

    assert segundo["guardado"] is True
    assert [f.estado for f in _filas(db_session)] == ["revocado", "activo"]


def test_cada_usuario_guarda_el_suyo(client, cliente_headers, pp):
    _guardar(client, cliente_headers)
    otro = _otro_cliente(client)
    pp.correo_paypal = "ana@correo.bo"
    _guardar(client, otro)

    assert client.get(URL, headers=cliente_headers).json()["correo_paypal"] == "j***@gmail.com"
    assert client.get(URL, headers=otro).json()["correo_paypal"] == "a***@correo.bo"


# ---- quitar ----


def test_quitar_revoca_el_token_en_paypal_y_es_idempotente(client, db_session, cliente_headers, pp):
    _guardar(client, cliente_headers)
    token = pp.ultimo_payment_token()

    primera = client.delete(URL, headers=cliente_headers)
    segunda = client.delete(URL, headers=cliente_headers)

    assert primera.status_code == segunda.status_code == 204
    assert client.get(URL, headers=cliente_headers).json()["guardado"] is False
    assert pp.tokens_borrados == [token]  # la segunda vez no hay nada que revocar
    assert [f.estado for f in _filas(db_session)] == ["revocado"]
    assert _filas(db_session)[0].revocado_en is not None


def test_quitar_sin_nada_guardado_no_llama_a_paypal(client, cliente_headers, pp):
    assert client.delete(URL, headers=cliente_headers).status_code == 204
    assert pp.peticiones == []


def test_quitar_con_paypal_caido_igual_deja_de_cobrarse(client, db_session, cliente_headers, pp):
    _guardar(client, cliente_headers)
    pp.caido = True

    respuesta = client.delete(URL, headers=cliente_headers)

    assert respuesta.status_code == 204
    assert client.get(URL, headers=cliente_headers).json()["guardado"] is False
    assert _filas(db_session)[0].estado == "revocado"


def test_quitar_descarta_tambien_un_intento_pendiente(client, db_session, cliente_headers, pp):
    token = _iniciar(client, cliente_headers).json()["token_preparacion"]

    assert client.delete(URL, headers=cliente_headers).status_code == 204

    assert _confirmar(client, cliente_headers, token).status_code == 404


def test_quitar_lo_de_uno_no_toca_lo_del_otro(client, cliente_headers, pp):
    _guardar(client, cliente_headers)
    otro = _otro_cliente(client)
    _guardar(client, otro)

    assert client.delete(URL, headers=otro).status_code == 204

    assert client.get(URL, headers=cliente_headers).json()["guardado"] is True


# ---- bitácora ----


def test_la_bitacora_registra_guardar_y_quitar_sin_tokens_ni_correos(client, db_session, cliente_headers, pp):
    _guardar(client, cliente_headers)
    client.delete(URL, headers=cliente_headers)

    db_session.expire_all()
    filas = list(db_session.scalars(select(Bitacora).where(Bitacora.entidad == "metodo_pago_guardado")))
    assert sorted(f.accion for f in filas) == ["guardar", "quitar"]
    texto = " ".join(str(f.datos) for f in filas)
    assert "VAULT" not in texto and "ST-SIM" not in texto and "gmail" not in texto and "juan" not in texto


# ---- core/paypal.py: lo que se manda a PayPal ----


def test_el_cobro_con_vault_manda_el_vault_id_y_la_clave_de_idempotencia(pp):
    setup = paypal.crear_setup_token(return_url="https://x/r", cancel_url="https://x/c", request_id="rid")
    pp.aprobar_setup(setup.id)
    vault = paypal.crear_payment_token(setup.id)

    orden = paypal.cobrar_con_vault(
        vault_id=vault.id, monto=Decimal("14.44"), moneda="USD", referencia="op-1", descripcion="Pedido", request_id="pd-1-x"
    )

    assert orden.estado == "COMPLETED" and orden.monto == Decimal("14.44") and orden.moneda == "USD"
    (cuerpo,) = pp.cuerpos_de_cobro_vault
    assert cuerpo["intent"] == "CAPTURE"
    assert cuerpo["payment_source"] == {"paypal": {"vault_id": vault.id}}  # sin stored_credential por defecto
    assert cuerpo["purchase_units"][0]["amount"] == {"currency_code": "USD", "value": "14.44"}
    assert pp.cabeceras_de_cobro_vault[0]["paypal-request-id"] == "pd-1-x"


def test_stored_credential_se_manda_solo_si_se_enciende(pp, monkeypatch):
    monkeypatch.setattr(get_settings(), "paypal_vault_stored_credential", True)
    setup = paypal.crear_setup_token(return_url="https://x/r", cancel_url="https://x/c", request_id="rid")
    vault = paypal.crear_payment_token(setup.id)

    paypal.cobrar_con_vault(
        vault_id=vault.id, monto=Decimal("1.00"), moneda="USD", referencia="op", descripcion=None, request_id="k"
    )

    assert pp.cuerpos_de_cobro_vault[0]["payment_source"]["paypal"]["stored_credential"] == {
        "payment_initiator": "MERCHANT",
        "payment_type": "UNSCHEDULED",
        "usage": "SUBSEQUENT",
    }


def test_una_orden_aprobada_se_captura_con_una_clave_derivada(pp):
    setup = paypal.crear_setup_token(return_url="https://x/r", cancel_url="https://x/c", request_id="rid")
    vault = paypal.crear_payment_token(setup.id)
    pp.estado_cobro_vault = "APPROVED"

    orden = paypal.cobrar_con_vault(
        vault_id=vault.id, monto=Decimal("5.00"), moneda="USD", referencia="op", descripcion=None, request_id="k"
    )

    assert orden.estado == "COMPLETED"
    assert pp.capturas == 1
    assert pp.cabeceras_de_captura[0]["paypal-request-id"] == "k-captura"


def test_el_usage_pattern_sale_de_la_configuracion(pp, monkeypatch):
    monkeypatch.setattr(get_settings(), "paypal_vault_usage_pattern", "IMMEDIATE")

    setup = paypal.crear_setup_token(return_url="https://x/r", cancel_url="https://x/c", request_id="rid")

    assert pp.setup_tokens[setup.id]["cuerpo"]["payment_source"]["paypal"]["usage_pattern"] == "IMMEDIATE"


def test_sin_credenciales_no_hay_llamada(monkeypatch):
    sim = SimuladorPayPal(monkeypatch, con_credenciales=False)
    with pytest.raises(paypal.PayPalError):
        paypal.crear_setup_token(return_url="https://x/r", cancel_url="https://x/c", request_id="rid")
    with pytest.raises(paypal.PayPalError):
        paypal.borrar_payment_token("VAULT-1")
    assert sim.peticiones == []


def test_una_respuesta_de_error_de_paypal_es_paypal_error_con_su_estado(pp):
    with pytest.raises(paypal.PayPalError) as error:
        paypal.crear_payment_token("ST-NO-EXISTE")
    assert error.value.status_code == 404

    setup = paypal.crear_setup_token(return_url="https://x/r", cancel_url="https://x/c", request_id="rid")
    pp.setup_tokens[setup.id]["aprobado"] = False
    with pytest.raises(paypal.PayPalError) as error:
        paypal.crear_payment_token(setup.id)
    assert error.value.status_code == 422 and "SETUP_TOKEN_NOT_APPROVED" in error.value.problemas


def test_borrar_un_token_inexistente_es_paypal_error(pp):
    with pytest.raises(paypal.PayPalError) as error:
        paypal.borrar_payment_token("VAULT-NO-EXISTE")
    assert error.value.status_code == 404
