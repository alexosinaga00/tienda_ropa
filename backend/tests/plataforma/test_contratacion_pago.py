"""Contratación de planes, fase 3: la COMPRA con PayPal (CU-04, `GestionarContratacion`), con PayPal simulado.

`POST /api/v1/public/contratacion/pedidos` crea un pedido `pendiente` y su orden de PayPal (monto recalculado por el
servidor en Bs y USD). Cuando el comprador vuelve, `.../{token}/capturar` consulta DIRECTAMENTE a PayPal, captura y crea
la empresa UNA sola vez. Nada de esto toca PayPal de verdad: `SimuladorPayPal` (tests/paypal_simulado.py)."""

import datetime as dt
import hashlib
from decimal import Decimal

import pytest
from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.core.exceptions import DomainError, ErrorFuncional
from app.core.tenant import sin_filtro
from app.core.tiempo import ahora_utc_naive, hoy_utc
from app.plataforma import politicas
from app.plataforma.models import Bitacora, Empresa, PedidoContratacion, Plan, Suscripcion, Usuario
from tests.conftest import crear_empresa
from tests.paypal_simulado import SimuladorPayPal
from tests.plataforma.ayudas_empresas import CLAVE, login_de_empresa, suscripciones_de

API = "/api/v1"
PEDIDOS = f"{API}/public/contratacion/pedidos"
TOKEN_DE_SERVICIO = {"X-Service-Token": "token-de-pruebas"}  # TAREAS_TOKEN de tests/conftest.py
CORREO = "ana@modasol.example.com"
FRONTEND = "https://web.example.com"


@pytest.fixture()
def pp(monkeypatch) -> SimuladorPayPal:
    monkeypatch.setattr(get_settings(), "frontend_public_url", FRONTEND + "/")  # con barra final a propósito
    return SimuladorPayPal(monkeypatch)


# ---- Ayudas ------------------------------------------------------------------------------------------------------------


def cuerpo(nombre: str = "Moda Sol", plan: str = "basico", periodo: str = "mensual", correo: str = CORREO, **admin) -> dict:
    return {
        "nombre": nombre,
        "plan_codigo": plan,
        "periodo": periodo,
        "administrador": {
            "nombre": "Ana",
            "apellido": "Rojas",
            "email": correo,
            "telefono": "70000000",
            "password": CLAVE,
            **admin,
        },
    }


def crear(client, nombre: str = "Moda Sol", plan: str = "basico", periodo: str = "mensual", correo: str = CORREO):
    return client.post(PEDIDOS, json=cuerpo(nombre, plan, periodo, correo))


def pedido_nuevo(client, nombre: str = "Moda Sol", plan: str = "basico", periodo: str = "mensual", correo: str = CORREO) -> str:
    respuesta = crear(client, nombre, plan, periodo, correo)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["token"]


def pedido_aprobado(client, pp, **kwargs) -> str:
    token = pedido_nuevo(client, **kwargs)
    pp.aprobar()
    return token


def capturar(client, token: str):
    return client.post(f"{PEDIDOS}/{token}/capturar")


def _pedido(db, token: str) -> PedidoContratacion:
    return db.scalar(select(PedidoContratacion).where(PedidoContratacion.token == token))


def _pedidos(db) -> list[PedidoContratacion]:
    return list(db.scalars(select(PedidoContratacion).order_by(PedidoContratacion.id)))


def _empresa(db, codigo: str) -> Empresa | None:
    return db.scalar(select(Empresa).where(Empresa.codigo == codigo))


def _n_empresas(db) -> int:
    return db.scalar(select(func.count()).select_from(Empresa))


def _n_usuarios(db, correo: str) -> int:
    return db.scalar(sin_filtro(select(func.count()).select_from(Usuario).where(Usuario.email == correo)))


def _bitacora(db) -> list[Bitacora]:
    return list(
        db.scalars(select(Bitacora).where(Bitacora.entidad == "pedido_contratacion").order_by(Bitacora.id))
    )


def _plan(db, codigo: str, **extra) -> Plan:
    plan = Plan(
        codigo=codigo, nombre=codigo.title(), max_sucursales=3, reportes_convencionales=True, reportes_ia=False,
        operacion_offline=False, analitica_ml=False, copias_seguridad=False, gestion_productos=True,
        gestion_ventas=True, reservas=True, **extra,
    )  # fmt: skip
    db.add(plan)
    db.commit()
    return plan


def _estado_de(db, token: str) -> str:
    db.expire_all()
    return _pedido(db, token).estado


def _nada_creado(db, codigo: str, correo: str = CORREO) -> None:
    assert _empresa(db, codigo) is None
    assert _n_usuarios(db, correo) == 0


# ---- La política de precios (pura) -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "plan, periodo, bs, usd",
    [
        ("basico", "mensual", "120.00", "17.24"),
        ("basico", "anual", "1152.00", "165.52"),  # 120 x 12 x 0,80
        ("profesional", "mensual", "590.00", "84.77"),
        ("profesional", "anual", "5664.00", "813.79"),  # 590 x 12 x 0,80
    ],
)
def test_montos_en_bs_y_usd_de_cada_plan_y_periodo(db_session, plan, periodo, bs, usd):
    registro = db_session.scalar(select(Plan).where(Plan.codigo == plan))

    precio = politicas.calcular_precio_contratacion(registro, periodo)

    assert (precio.monto_bs, precio.monto_usd) == (Decimal(bs), Decimal(usd))
    assert precio.tipo_cambio == Decimal("6.9600")


def test_el_redondeo_es_mitad_hacia_arriba_y_no_el_bancario():
    assert politicas.convertir_bs_a_usd(Decimal("1.00"), Decimal("8.0000")) == Decimal("0.13")  # 0,125; round() daría 0,12
    assert politicas.redondear_monto(Decimal("2.675")) == Decimal("2.68")
    assert politicas.redondear_monto(Decimal("0.004")) == Decimal("0.00")


def test_el_descuento_anual_y_el_tipo_de_cambio_salen_de_los_settings(db_session, monkeypatch):
    profesional = db_session.scalar(select(Plan).where(Plan.codigo == "profesional"))
    monkeypatch.setattr(get_settings(), "descuento_anual_porcentaje", Decimal("10"))
    monkeypatch.setattr(get_settings(), "tipo_cambio_bs_por_usd", Decimal("7.00"))

    precio = politicas.calcular_precio_contratacion(profesional, "anual")

    assert precio.monto_bs == Decimal("6372.00")  # 590 x 12 x 0,90
    assert precio.monto_usd == Decimal("910.29")
    assert precio.tipo_cambio == Decimal("7.0000")


@pytest.mark.parametrize("precio", [None, Decimal("0")])
def test_un_plan_sin_precio_no_se_puede_comprar(db_session, precio):
    plan = _plan(db_session, "sin-precio", precio_mensual_bs=precio)

    with pytest.raises(ErrorFuncional) as error:
        politicas.calcular_precio_contratacion(plan, "mensual")

    assert (error.value.codigo, error.value.status_code) == ("plan_sin_precio", 409)


def test_un_periodo_desconocido_se_rechaza(db_session):
    basico = db_session.scalar(select(Plan).where(Plan.codigo == "basico"))
    with pytest.raises(DomainError) as error:
        politicas.monto_bs_del_plan(basico, "trimestral")
    assert error.value.status_code == 422


# ---- Crear el pedido ---------------------------------------------------------------------------------------------------


def test_crear_el_pedido_devuelve_el_token_la_url_de_paypal_y_los_montos(client_por_peticion, db_session, pp):
    respuesta = crear(client_por_peticion)

    assert respuesta.status_code == 201, respuesta.text
    cuerpo_ = respuesta.json()
    assert set(cuerpo_) == {
        "token", "url_aprobacion", "plan_codigo", "plan_nombre", "periodo", "monto_bs", "monto_usd", "tipo_cambio", "expira_en",
    }  # fmt: skip
    assert len(cuerpo_["token"]) >= 40
    assert cuerpo_["url_aprobacion"] == "https://www.sandbox.paypal.com/checkoutnow?token=ORD-SIM-0001"
    assert (cuerpo_["plan_codigo"], cuerpo_["periodo"]) == ("basico", "mensual")
    assert (Decimal(cuerpo_["monto_bs"]), Decimal(cuerpo_["monto_usd"]), Decimal(cuerpo_["tipo_cambio"])) == (
        Decimal("120.00"), Decimal("17.24"), Decimal("6.96"),
    )  # fmt: skip
    expira = dt.datetime.fromisoformat(cuerpo_["expira_en"])
    assert expira.tzinfo is not None  # con zona: el navegador no la lee como hora local
    restante = expira - dt.datetime.now(dt.timezone.utc)
    assert dt.timedelta(minutes=59) < restante <= dt.timedelta(minutes=60)


def test_el_pedido_guardado_tiene_lo_que_el_servidor_calculo(client_por_peticion, db_session, pp):
    token = pedido_nuevo(client_por_peticion)

    (pedido,) = _pedidos(db_session)
    assert pedido.token == token
    assert (pedido.tipo, pedido.estado, pedido.periodo) == ("pago", "pendiente", "mensual")
    assert (pedido.empresa_nombre, pedido.empresa_codigo, pedido.admin_email) == ("Moda Sol", "moda-sol", CORREO)
    assert (pedido.monto_bs, pedido.monto_usd, pedido.tipo_cambio) == (Decimal("120.00"), Decimal("17.24"), Decimal("6.96"))
    assert pedido.paypal_order_id == "ORD-SIM-0001" and pedido.empresa_creada_id is None
    assert pedido.ip
    assert pedido.plan_id == db_session.scalar(select(Plan.id).where(Plan.codigo == "basico"))
    assert abs((pedido.expira_en - ahora_utc_naive()) - dt.timedelta(minutes=60)) < dt.timedelta(seconds=30)
    # La empresa NO existe hasta que se cobre.
    _nada_creado(db_session, "moda-sol")


def test_la_orden_de_paypal_lleva_el_monto_en_usd_y_las_urls_de_retorno_con_el_token(client_por_peticion, pp):
    token = pedido_nuevo(client_por_peticion)

    (orden,) = pp.cuerpos_de_creacion
    unidad = orden["purchase_units"][0]
    assert unidad["amount"] == {"currency_code": "USD", "value": "17.24"}
    assert unidad["reference_id"] == "PED-1"
    contexto = orden["payment_source"]["paypal"]["experience_context"]
    assert contexto["return_url"] == f"{FRONTEND}/contratar/retorno?pedido={token}"
    assert contexto["cancel_url"] == f"{FRONTEND}/contratar/retorno?pedido={token}&cancelado=1"
    # Sin datos personales hacia PayPal: ni correo, ni nombre del comprador, ni contraseña, ni el nombre de la empresa.
    enviado = str(orden)
    assert CORREO not in enviado and "Rojas" not in enviado and CLAVE not in enviado and "Moda Sol" not in enviado
    assert "Básico" in unidad["description"] and "mensual" in unidad["description"]


def test_el_plan_anual_cobra_doce_meses_con_el_descuento(client_por_peticion, db_session, pp):
    respuesta = crear(client_por_peticion, plan="profesional", periodo="anual")

    assert respuesta.status_code == 201, respuesta.text
    assert (Decimal(respuesta.json()["monto_bs"]), Decimal(respuesta.json()["monto_usd"])) == (Decimal("5664.00"), Decimal("813.79"))
    assert pp.cuerpos_de_creacion[0]["purchase_units"][0]["amount"]["value"] == "813.79"


def test_la_contrasena_nunca_se_guarda_ni_se_devuelve_en_claro(client_por_peticion, db_session, pp):
    respuesta = crear(client_por_peticion)
    token = respuesta.json()["token"]

    pedido = _pedido(db_session, token)
    assert pedido.admin_password_hash.startswith("$2") and CLAVE not in pedido.admin_password_hash
    todo = " ".join(str(v) for v in (pedido.__dict__.values()))
    assert CLAVE not in todo
    consulta = client_por_peticion.get(f"{PEDIDOS}/{token}")
    for texto in (respuesta.text, consulta.text):
        assert CLAVE not in texto and pedido.admin_password_hash not in texto and "$2" not in texto and CORREO not in texto


def test_el_cliente_no_puede_imponer_montos_ni_campos_extra(client_por_peticion, db_session, pp):
    for extra in ({"monto_bs": "1.00"}, {"monto_usd": "0.01"}, {"estado": "completado"}, {"token": "x"}):
        respuesta = client_por_peticion.post(PEDIDOS, json={**cuerpo(), **extra})
        assert respuesta.status_code == 422, (extra, respuesta.text)
    sin_periodo = {k: v for k, v in cuerpo().items() if k != "periodo"}
    assert client_por_peticion.post(PEDIDOS, json=sin_periodo).status_code == 422
    assert client_por_peticion.post(PEDIDOS, json=cuerpo(periodo="trimestral")).status_code == 422
    assert _pedidos(db_session) == [] and pp.ordenes == {}


def test_un_plan_sin_precio_da_409_plan_sin_precio_y_no_llama_a_paypal(client_por_peticion, db_session, pp):
    _plan(db_session, "sin-precio")

    respuesta = crear(client_por_peticion, plan="sin-precio")

    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == respuesta.json()["detail"] == "plan_sin_precio"
    assert _pedidos(db_session) == [] and pp.peticiones == []


def test_plan_inexistente_inactivo_y_nombre_invalido(client_por_peticion, db_session, pp):
    _plan(db_session, "inactivo", precio_mensual_bs=Decimal("50.00"), activo=False)
    crear_empresa(db_session, "tienda-ocupada")

    assert crear(client_por_peticion, plan="no-existe").status_code == 404
    assert crear(client_por_peticion, plan="inactivo").status_code == 409
    reservado = crear(client_por_peticion, nombre="Contratacion")
    assert reservado.status_code == 422 and reservado.json()["codigo"] == "nombre_empresa_reservado"
    assert crear(client_por_peticion, nombre="Tienda Ocupada").status_code == 409
    assert crear(client_por_peticion, nombre="!!!").status_code == 400
    assert _pedidos(db_session) == [] and pp.peticiones == []


@pytest.mark.parametrize("falla", ["todo", "crear"])
def test_si_paypal_falla_al_crear_la_orden_da_503_y_no_queda_nada(client_por_peticion, db_session, pp, falla):
    if falla == "todo":
        pp.caido = True
    else:
        pp.caer_en = {"crear"}

    respuesta = crear(client_por_peticion)

    assert respuesta.status_code == 503, respuesta.text
    assert respuesta.json()["codigo"] == respuesta.json()["detail"] == "paypal_no_disponible"
    assert "PayPal" in respuesta.json()["mensaje"]
    assert _pedidos(db_session) == [] and _nada_creado(db_session, "moda-sol") is None
    assert pp.ordenes == {} and _bitacora(db_session) == []
    # Cuando PayPal vuelve, el mismo cuerpo funciona.
    pp.caido, pp.caer_en = False, set()
    assert crear(client_por_peticion).status_code == 201


def test_sin_credenciales_de_paypal_tambien_da_503(client_por_peticion, db_session, monkeypatch):
    SimuladorPayPal(monkeypatch, con_credenciales=False)
    respuesta = crear(client_por_peticion)
    assert respuesta.status_code == 503 and respuesta.json()["codigo"] == "paypal_no_disponible"
    assert _pedidos(db_session) == []


def test_el_pago_no_restringe_el_correo_a_una_sola_compra(client_por_peticion, db_session, pp):
    assert crear(client_por_peticion, "Moda Sol").status_code == 201
    assert crear(client_por_peticion, "Moda Luna").status_code == 201  # mismo correo, otra empresa
    # Tampoco lo bloquea una prueba gratuita de ese correo.
    prueba = client_por_peticion.post(
        f"{API}/public/contratacion/prueba",
        json={"nombre": "Moda Sin Costo", "plan_codigo": "basico",
              "administrador": {"nombre": "Ana", "apellido": "Rojas", "email": CORREO, "password": CLAVE}},
    )  # fmt: skip
    assert prueba.status_code == 201, prueba.text
    assert crear(client_por_peticion, "Moda Estrella").status_code == 201
    assert len([p for p in _pedidos(db_session) if p.tipo == "pago"]) == 3


def test_dos_pedidos_pendientes_del_mismo_nombre_son_posibles_y_solo_el_primero_en_pagar_crea_la_empresa(
    client_por_peticion, db_session, pp
):
    primero = pedido_nuevo(client_por_peticion, "Misma Tienda", correo="uno@x.example.com")
    segundo = pedido_nuevo(client_por_peticion, "Misma Tienda", correo="dos@x.example.com")
    pp.aprobar("ORD-SIM-0001")
    pp.aprobar("ORD-SIM-0002")

    assert capturar(client_por_peticion, primero).status_code == 200
    perdedor = capturar(client_por_peticion, segundo)

    assert perdedor.status_code == 409 and perdedor.json()["codigo"] == "pagado_sin_empresa"
    assert _n_empresas(db_session) == 2  # fashionstore + una
    assert pp.capturas == 2  # el segundo SÍ pagó: queda para reembolso manual


# ---- Capturar: el caso feliz --------------------------------------------------------------------------------------------


def test_capturar_cobra_crea_la_empresa_y_completa_el_pedido(client_por_peticion, db_session, pp):
    token = pedido_aprobado(client_por_peticion, pp)

    respuesta = capturar(client_por_peticion, token)

    assert respuesta.status_code == 200, respuesta.text
    hoy = hoy_utc()
    assert respuesta.json() == {
        "estado": "completado",
        "empresa_codigo": "moda-sol",
        "empresa_nombre": "Moda Sol",
        "plan_codigo": "basico",
        "plan_nombre": "Básico",
        "periodo": "mensual",
        "es_prueba": False,
        "fecha_inicio": hoy.isoformat(),
        "fecha_vencimiento": (hoy + dt.timedelta(days=30)).isoformat(),
        "monto_bs": "120.00",
        "monto_usd": "17.24",
    }
    empresa = _empresa(db_session, "moda-sol")
    assert empresa is not None and empresa.activo is True
    (suscripcion,) = suscripciones_de(db_session, empresa.id)
    assert (suscripcion.estado, suscripcion.es_prueba) == ("activa", False)
    assert suscripcion.fecha_vencimiento - suscripcion.fecha_inicio == dt.timedelta(days=30)
    assert suscripcion.plan_id == db_session.scalar(select(Plan.id).where(Plan.codigo == "basico"))
    pedido = _pedido(db_session, token)
    assert (pedido.estado, pedido.empresa_creada_id) == ("completado", empresa.id)
    assert pp.capturas == 1


def test_la_captura_usa_una_clave_de_idempotencia_derivada_del_token_sin_revelarlo(client_por_peticion, pp):
    token = pedido_aprobado(client_por_peticion, pp)

    capturar(client_por_peticion, token)

    clave = pp.cabeceras_de_captura[0]["paypal-request-id"]
    assert clave == hashlib.sha256(f"fashionstore-captura:{token}".encode()).hexdigest()
    assert token not in clave


def test_el_plan_anual_vence_en_365_dias(client_por_peticion, db_session, pp):
    token = pedido_aprobado(client_por_peticion, pp, plan="profesional", periodo="anual")

    respuesta = capturar(client_por_peticion, token)

    assert respuesta.status_code == 200, respuesta.text
    hoy = hoy_utc()
    assert respuesta.json()["fecha_vencimiento"] == (hoy + dt.timedelta(days=365)).isoformat()
    assert (respuesta.json()["plan_codigo"], respuesta.json()["periodo"]) == ("profesional", "anual")
    (suscripcion,) = suscripciones_de(db_session, _empresa(db_session, "moda-sol").id)
    assert suscripcion.fecha_vencimiento == hoy + dt.timedelta(days=365) and suscripcion.es_prueba is False


def test_el_administrador_inicia_sesion_y_la_tienda_esta_disponible(client_por_peticion, db_session, pp):
    token = pedido_aprobado(client_por_peticion, pp)
    assert capturar(client_por_peticion, token).status_code == 200

    login = login_de_empresa(client_por_peticion, "moda-sol", CORREO)  # con la contraseña original del formulario
    assert login.status_code == 200, login.text
    cabeceras = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert login_de_empresa(client_por_peticion, "Moda Sol", CORREO.upper()).status_code == 200
    assert login_de_empresa(client_por_peticion, "moda-sol", CORREO, "otra-clave-1234").status_code == 401

    mi = client_por_peticion.get(f"{API}/mi-empresa/suscripcion", headers=cabeceras)
    assert mi.status_code == 200, mi.text
    assert (mi.json()["estado"], mi.json()["es_prueba"], mi.json()["plan_codigo"]) == ("activa", False, "basico")
    assert client_por_peticion.get(f"{API}/sucursales", headers=cabeceras).status_code == 200
    assert client_por_peticion.get(f"{API}/tallas", headers=cabeceras).json()  # datos base de la empresa nueva

    tienda = client_por_peticion.get(f"{API}/public/moda-sol/tienda")
    assert tienda.status_code == 200 and tienda.json()["disponible"] is True
    assert "moda-sol" in {t["codigo"] for t in client_por_peticion.get(f"{API}/public/tiendas").json()}


def test_la_bitacora_registra_el_pedido_y_la_captura_sin_datos_personales(client_por_peticion, db_session, pp):
    token = pedido_aprobado(client_por_peticion, pp)
    capturar(client_por_peticion, token)

    filas = _bitacora(db_session)

    assert [f.accion for f in filas] == ["crear", "capturar"]
    assert all(f.usuario_id is None for f in filas)  # anónima
    pedido = _pedido(db_session, token)
    assert all(f.entidad_id == pedido.id for f in filas)
    assert filas[1].empresa_id == pedido.empresa_creada_id
    volcado = " ".join(str(f.datos) for f in filas)
    for secreto in (CORREO, CLAVE, "Rojas", "Moda Sol", pedido.admin_password_hash, token):
        assert secreto not in volcado


# ---- Capturar: idempotencia -----------------------------------------------------------------------------------------------


def test_capturar_dos_veces_devuelve_la_misma_empresa_sin_cobrar_ni_crear_nada(client_por_peticion, db_session, pp):
    token = pedido_aprobado(client_por_peticion, pp)
    primera = capturar(client_por_peticion, token)
    empresas, bitacora = _n_empresas(db_session), len(_bitacora(db_session))

    segunda = capturar(client_por_peticion, token)
    tercera = capturar(client_por_peticion, token)  # p. ej. el usuario recarga la página de retorno

    assert primera.status_code == segunda.status_code == tercera.status_code == 200
    assert primera.json() == segunda.json() == tercera.json()
    assert pp.capturas == 1 and pp.peticiones_de_captura == 1  # PayPal no se vuelve a llamar para capturar
    assert _n_empresas(db_session) == empresas and _n_usuarios(db_session, CORREO) == 1
    assert len(_bitacora(db_session)) == bitacora
    assert len(suscripciones_de(db_session, _empresa(db_session, "moda-sol").id)) == 1


def test_el_estado_de_un_pedido_completado_trae_el_codigo_de_la_empresa(client_por_peticion, pp):
    token = pedido_aprobado(client_por_peticion, pp)
    antes = client_por_peticion.get(f"{PEDIDOS}/{token}")
    capturar(client_por_peticion, token)

    despues = client_por_peticion.get(f"{PEDIDOS}/{token}")

    assert antes.json()["estado"] == "pendiente" and antes.json()["empresa_codigo"] is None
    assert despues.json()["estado"] == "completado" and despues.json()["empresa_codigo"] == "moda-sol"


def test_si_el_cobro_existe_en_paypal_pero_no_se_guardo_la_captura_solo_crea_la_empresa(client_por_peticion, db_session, pp):
    """El proceso murió DESPUÉS de capturar y ANTES de confirmar: el pedido sigue `pendiente`, pero la orden ya está
    `COMPLETED` en PayPal. El reintento no vuelve a cobrar: reconoce el cobro y crea la empresa."""
    from app.core import paypal

    token = pedido_aprobado(client_por_peticion, pp)
    paypal.capturar_orden("ORD-SIM-0001", "captura-de-un-proceso-que-murio")
    assert _estado_de(db_session, token) == "pendiente" and pp.capturas == 1

    respuesta = capturar(client_por_peticion, token)

    assert respuesta.status_code == 200, respuesta.text
    assert pp.capturas == 1 and pp.peticiones_de_captura == 1  # solo la directa de arriba
    assert _empresa(db_session, "moda-sol") is not None


# ---- Capturar: lo que NO se cobra ------------------------------------------------------------------------------------


def test_sin_aprobar_en_paypal_da_409_pago_no_aprobado_y_sigue_pendiente(client_por_peticion, db_session, pp):
    token = pedido_nuevo(client_por_peticion)

    respuesta = capturar(client_por_peticion, token)

    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == respuesta.json()["detail"] == "pago_no_aprobado"
    assert _estado_de(db_session, token) == "pendiente" and pp.capturas == 0 and pp.peticiones_de_captura == 0
    _nada_creado(db_session, "moda-sol")
    # El comprador aprueba y vuelve: ahora sí.
    pp.aprobar()
    assert capturar(client_por_peticion, token).status_code == 200


@pytest.mark.parametrize(
    "campo, valor",
    [("monto_reportado", Decimal("1.00")), ("monto_reportado", Decimal("17.25")), ("moneda_reportada", "BOB"), ("moneda_reportada", "EUR")],
)
def test_otro_monto_u_otra_moneda_no_se_captura_y_el_pedido_queda_fallido(client_por_peticion, db_session, pp, campo, valor):
    token = pedido_aprobado(client_por_peticion, pp)
    setattr(pp, campo, valor)

    respuesta = capturar(client_por_peticion, token)

    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == respuesta.json()["detail"] == "pago_no_coincide"
    assert pp.peticiones_de_captura == 0 and pp.capturas == 0  # NO se capturó
    assert _estado_de(db_session, token) == "fallido"
    _nada_creado(db_session, "moda-sol")
    assert [f.accion for f in _bitacora(db_session)] == ["crear", "pago_no_coincide"]
    # Un pedido fallido no se reintenta: 409 con su propio código.
    pp.monto_reportado = pp.moneda_reportada = None
    otra = capturar(client_por_peticion, token)
    assert otra.status_code == 409 and otra.json()["codigo"] == "pedido_fallido"
    assert pp.capturas == 0


def test_una_captura_en_revision_no_crea_la_empresa_hasta_que_paypal_la_confirme(client_por_peticion, db_session, pp):
    pp.estado_captura = "PENDING"
    token = pedido_aprobado(client_por_peticion, pp)

    respuesta = capturar(client_por_peticion, token)

    assert respuesta.status_code == 409 and respuesta.json()["codigo"] == "pago_no_aprobado"
    _nada_creado(db_session, "moda-sol")
    assert _estado_de(db_session, token) == "pendiente"
    pp.ordenes["ORD-SIM-0001"]["estado_captura"] = "COMPLETED"  # PayPal la confirma después
    assert capturar(client_por_peticion, token).status_code == 200
    assert pp.capturas == 1  # no se cobró otra vez


def test_un_pedido_vencido_sin_aprobar_pasa_a_vencido(client_por_peticion, db_session, pp):
    token = pedido_nuevo(client_por_peticion)
    db_session.execute(
        update(PedidoContratacion).where(PedidoContratacion.token == token).values(expira_en=ahora_utc_naive() - dt.timedelta(minutes=1))
    )
    db_session.commit()

    respuesta = capturar(client_por_peticion, token)

    assert respuesta.status_code == 409 and respuesta.json()["codigo"] == "pedido_vencido"
    assert _estado_de(db_session, token) == "vencido"
    assert [f.accion for f in _bitacora(db_session)] == ["crear", "vencer"]
    # Ya vencido, aunque después aprueben la orden, no se cobra.
    pp.aprobar()
    otra = capturar(client_por_peticion, token)
    assert otra.status_code == 409 and otra.json()["codigo"] == "pedido_vencido"
    assert pp.capturas == 0
    _nada_creado(db_session, "moda-sol")


def test_un_pedido_aprobado_a_tiempo_se_cobra_aunque_el_plazo_corra_mientras_vuelve(client_por_peticion, db_session, pp):
    """El comprador aprobó en PayPal dentro del plazo y la tarea de vencimiento aún no corrió: se cobra (lo que no se
    aprobó es lo que vence)."""
    token = pedido_aprobado(client_por_peticion, pp)
    db_session.execute(
        update(PedidoContratacion).where(PedidoContratacion.token == token).values(expira_en=ahora_utc_naive() - dt.timedelta(minutes=5))
    )
    db_session.commit()

    assert capturar(client_por_peticion, token).status_code == 200
    assert pp.capturas == 1


# ---- Cancelar ------------------------------------------------------------------------------------------------------------


def test_cancelar_un_pedido_pendiente_es_idempotente_y_impide_cobrarlo(client_por_peticion, db_session, pp):
    token = pedido_nuevo(client_por_peticion)

    primera = client_por_peticion.post(f"{PEDIDOS}/{token}/cancelar")
    segunda = client_por_peticion.post(f"{PEDIDOS}/{token}/cancelar")

    assert primera.status_code == segunda.status_code == 200
    assert primera.json() == segunda.json() and primera.json()["estado"] == "cancelado"
    assert _estado_de(db_session, token) == "cancelado"
    assert [f.accion for f in _bitacora(db_session)] == ["crear", "cancelar"]  # la repetida no anota otra
    pp.aprobar()
    capturada = capturar(client_por_peticion, token)
    assert capturada.status_code == 409 and capturada.json()["codigo"] == "pedido_cancelado"
    assert pp.capturas == 0


def test_cancelar_un_pedido_ya_pagado_da_409(client_por_peticion, db_session, pp):
    token = pedido_aprobado(client_por_peticion, pp)
    capturar(client_por_peticion, token)

    respuesta = client_por_peticion.post(f"{PEDIDOS}/{token}/cancelar")

    assert respuesta.status_code == 409 and respuesta.json()["codigo"] == "pedido_ya_pagado"
    assert _estado_de(db_session, token) == "completado"


@pytest.mark.parametrize("estado, codigo", [("vencido", "pedido_vencido"), ("fallido", "pedido_fallido")])
def test_cancelar_un_pedido_vencido_o_fallido_da_409_con_su_codigo(client_por_peticion, db_session, pp, estado, codigo):
    token = pedido_nuevo(client_por_peticion)
    db_session.execute(update(PedidoContratacion).where(PedidoContratacion.token == token).values(estado=estado))
    db_session.commit()

    respuesta = client_por_peticion.post(f"{PEDIDOS}/{token}/cancelar")

    assert respuesta.status_code == 409 and respuesta.json()["codigo"] == codigo


# ---- Pagado sin empresa ----------------------------------------------------------------------------------------------------


def test_si_otro_toma_el_nombre_mientras_se_paga_queda_pagado_sin_empresa_y_el_reintento_no_recobra(
    client_por_peticion, db_session, pp
):
    token = pedido_aprobado(client_por_peticion, pp, nombre="Tienda Veloz")
    crear_empresa(db_session, "tienda-veloz")  # otra empresa tomó el nombre mientras el comprador pagaba
    empresas = _n_empresas(db_session)

    respuesta = capturar(client_por_peticion, token)

    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["codigo"] == respuesta.json()["detail"] == "pagado_sin_empresa"
    assert "pago" in respuesta.json()["mensaje"] and "soporte" in respuesta.json()["mensaje"]
    assert _estado_de(db_session, token) == "pagado_sin_empresa"  # confirmado: no se pierde
    assert pp.capturas == 1  # el dinero SÍ se cobró
    assert _n_empresas(db_session) == empresas and _n_usuarios(db_session, CORREO) == 0  # nada a medias
    acciones = [f.accion for f in _bitacora(db_session)]
    assert acciones == ["crear", "pagado_sin_empresa"]
    registro = _bitacora(db_session)[1]
    assert registro.datos["motivo"] == "nombre_en_uso" and registro.datos["paypal_order_id"] == "ORD-SIM-0001"
    assert CORREO not in str(registro.datos)

    peticiones = len(pp.peticiones)
    reintento = capturar(client_por_peticion, token)
    assert reintento.status_code == 409 and reintento.json()["codigo"] == "pagado_sin_empresa"
    assert len(pp.peticiones) == peticiones  # ni siquiera consulta a PayPal
    assert pp.capturas == 1 and pp.peticiones_de_captura == 1
    assert [f.accion for f in _bitacora(db_session)] == acciones  # no repite la anotación

    # Si el nombre se libera, el mismo pedido termina de crear la empresa SIN cobrar otra vez.
    db_session.execute(update(Empresa).where(Empresa.codigo == "tienda-veloz").values(codigo="tienda-veloz-vieja"))
    db_session.commit()
    final = capturar(client_por_peticion, token)
    assert final.status_code == 200, final.text
    assert final.json()["empresa_codigo"] == "tienda-veloz"
    assert _estado_de(db_session, token) == "completado"
    assert pp.capturas == 1 and pp.peticiones_de_captura == 1
    assert [f.accion for f in _bitacora(db_session)] == ["crear", "pagado_sin_empresa", "capturar"]
    assert login_de_empresa(client_por_peticion, "tienda-veloz", CORREO).status_code == 200


def test_cualquier_fallo_al_crear_la_empresa_tras_cobrar_deja_pagado_sin_empresa(client_por_peticion, db_session, pp, monkeypatch):
    from app.plataforma.casos_uso import cu04_gestionar_empresas_planes_suscripciones as cu04

    token = pedido_aprobado(client_por_peticion, pp)

    def falla(*args, **kwargs):
        raise RuntimeError("fallo inesperado con CORREO " + CORREO)

    monkeypatch.setattr(cu04, "_crear_empresa_completa", falla)

    respuesta = capturar(client_por_peticion, token)

    assert respuesta.status_code == 409 and respuesta.json()["codigo"] == "pagado_sin_empresa"
    assert _estado_de(db_session, token) == "pagado_sin_empresa"
    assert _bitacora(db_session)[-1].datos["motivo"] == "error_interno"
    assert CORREO not in str(_bitacora(db_session)[-1].datos) and CORREO not in respuesta.text


# ---- PayPal caído al capturar -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("operacion", ["consultar", "capturar"])
def test_paypal_caido_al_capturar_da_503_y_el_pedido_sigue_pendiente_para_reintentar(client_por_peticion, db_session, pp, operacion):
    token = pedido_aprobado(client_por_peticion, pp)
    pp.caer_en = {operacion}

    respuesta = capturar(client_por_peticion, token)

    assert respuesta.status_code == 503
    assert respuesta.json()["codigo"] == respuesta.json()["detail"] == "paypal_no_disponible"
    assert _estado_de(db_session, token) == "pendiente" and pp.capturas == 0
    _nada_creado(db_session, "moda-sol")

    pp.caer_en = set()
    assert capturar(client_por_peticion, token).status_code == 200
    assert pp.capturas == 1


# ---- Consultar el estado ------------------------------------------------------------------------------------------------


def test_el_estado_publico_no_trae_datos_personales(client_por_peticion, pp):
    token = pedido_nuevo(client_por_peticion, plan="profesional", periodo="anual")

    respuesta = client_por_peticion.get(f"{PEDIDOS}/{token}")

    assert respuesta.status_code == 200, respuesta.text
    assert set(respuesta.json()) == {
        "estado", "plan_codigo", "plan_nombre", "periodo", "monto_bs", "monto_usd", "tipo_cambio", "expira_en", "empresa_codigo",
    }  # fmt: skip
    assert respuesta.json()["estado"] == "pendiente" and respuesta.json()["plan_codigo"] == "profesional"
    assert Decimal(respuesta.json()["monto_bs"]) == Decimal("5664.00")
    for dato in (CORREO, "Rojas", "Ana", "70000000", "moda-sol", "Moda Sol", "$2"):
        assert dato not in respuesta.text


def test_un_token_inexistente_o_de_una_prueba_gratuita_da_el_mismo_404(client_por_peticion, db_session, pp):
    prueba = client_por_peticion.post(
        f"{API}/public/contratacion/prueba",
        json={"nombre": "Solo Prueba", "plan_codigo": "basico",
              "administrador": {"nombre": "Ana", "apellido": "Rojas", "email": "p@x.example.com", "password": CLAVE}},
    )  # fmt: skip
    assert prueba.status_code == 201
    token_de_prueba = db_session.scalar(select(PedidoContratacion.token).where(PedidoContratacion.tipo == "prueba"))

    respuestas = [
        client_por_peticion.request(metodo, f"{PEDIDOS}/{token}{sufijo}")
        for token in ("no-existe-en-ningun-lado", token_de_prueba)
        for metodo, sufijo in (("GET", ""), ("POST", "/capturar"), ("POST", "/cancelar"))
    ]

    assert {r.status_code for r in respuestas} == {404}
    assert len({r.text for r in respuestas}) == 1  # el mismo cuerpo siempre
    assert pp.peticiones == []
    assert client_por_peticion.get(f"{PEDIDOS}/{'x' * 65}").status_code == 422  # un token absurdo ni se consulta


def test_las_rutas_de_contratacion_se_atienden_como_anonimas_y_sin_suscripcion(client_por_peticion, dos_empresas, pp):
    """Un token de una empresa (aunque su suscripción esté vencida) no fija empresa ni exige suscripción."""
    token = pedido_nuevo(client_por_peticion)
    cabeceras = dos_empresas.a.headers

    assert client_por_peticion.get(f"{PEDIDOS}/{token}", headers=cabeceras).status_code == 200
    assert client_por_peticion.get(f"{PEDIDOS}/{token}", headers={"Authorization": "Bearer basura"}).status_code == 200
    assert client_por_peticion.post(f"{PEDIDOS}/{token}/cancelar", headers=cabeceras).status_code == 200


# ---- Vencimiento de pedidos ---------------------------------------------------------------------------------------------


def test_la_tarea_de_vencimiento_vence_solo_los_pedidos_pendientes_con_el_plazo_cumplido(client_por_peticion, db_session, pp):
    vencido = pedido_nuevo(client_por_peticion, "Vence Ya")
    vigente = pedido_nuevo(client_por_peticion, "Vence Luego")
    cancelado = pedido_nuevo(client_por_peticion, "Ya Cancelado")
    client_por_peticion.post(f"{PEDIDOS}/{cancelado}/cancelar")
    completado = pedido_aprobado(client_por_peticion, pp, nombre="Ya Completado")  # aprueba la última orden creada
    assert capturar(client_por_peticion, completado).status_code == 200
    # Una prueba gratuita (sin plazo) tampoco se toca.
    client_por_peticion.post(
        f"{API}/public/contratacion/prueba",
        json={"nombre": "Prueba Intacta", "plan_codigo": "basico",
              "administrador": {"nombre": "Ana", "apellido": "R", "email": "i@x.example.com", "password": CLAVE}},
    )  # fmt: skip
    pasado = ahora_utc_naive() - dt.timedelta(minutes=1)
    for token in (vencido, cancelado, completado):
        db_session.execute(update(PedidoContratacion).where(PedidoContratacion.token == token).values(expira_en=pasado))
    db_session.commit()

    tarea = client_por_peticion.post(f"{API}/tareas/vencer-suscripciones", headers=TOKEN_DE_SERVICIO)

    assert tarea.status_code == 200 and tarea.json() == {"vencidas": 0}  # el contrato de la ruta no cambia
    assert _estado_de(db_session, vencido) == "vencido"
    assert _estado_de(db_session, vigente) == "pendiente"
    assert _estado_de(db_session, cancelado) == "cancelado"
    assert _estado_de(db_session, completado) == "completado"
    assert [p.estado for p in _pedidos(db_session) if p.tipo == "prueba"] == ["completado"]
    assert politicas.vencer_pedidos_contratacion(db_session) == 0  # idempotente


def test_vencer_pedidos_contratacion_devuelve_cuantos_vencio(client_por_peticion, db_session, pp):
    for i in range(3):
        pedido_nuevo(client_por_peticion, f"Tienda Vieja {i}")
    db_session.execute(update(PedidoContratacion).values(expira_en=ahora_utc_naive() - dt.timedelta(hours=2)))
    db_session.commit()

    assert politicas.vencer_pedidos_contratacion(db_session) == 3
    assert {p.estado for p in _pedidos(db_session)} == {"vencido"}


# ---- Límites de tasa ----------------------------------------------------------------------------------------------------


def test_crear_pedidos_esta_limitado_a_5_por_hora_y_solo_cuentan_las_peticiones_validas(client_por_peticion, pp):
    for _ in range(6):  # el cuerpo inválido se rechaza antes de contar
        assert client_por_peticion.post(PEDIDOS, json=cuerpo(password="corta")).status_code == 422
    for i in range(5):
        assert crear(client_por_peticion, f"Tienda Limite {i}", correo=f"u{i}@x.example.com").status_code == 201

    sexta = crear(client_por_peticion, "Tienda Limite 6", correo="u6@x.example.com")

    assert sexta.status_code == 429, sexta.text


def test_consultar_esta_limitado_a_60_por_minuto(client_por_peticion, pp):
    token = pedido_nuevo(client_por_peticion)
    for _ in range(60):
        assert client_por_peticion.get(f"{PEDIDOS}/{token}").status_code == 200
    assert client_por_peticion.get(f"{PEDIDOS}/{token}").status_code == 429


def test_capturar_esta_limitado_a_10_por_minuto(client_por_peticion, pp):
    token = pedido_nuevo(client_por_peticion)
    for _ in range(10):
        assert capturar(client_por_peticion, token).status_code == 409  # sin aprobar
    assert capturar(client_por_peticion, token).status_code == 429
