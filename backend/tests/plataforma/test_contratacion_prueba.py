"""Contratación de planes, fase 2: la PRUEBA GRATIS pública (CU-04, `GestionarContratacion.iniciar_prueba`).

`POST /api/v1/public/contratacion/prueba` (sin sesión) crea en UNA transacción la empresa, su suscripción de prueba
(`es_prueba`, 14 días completos: vencimiento = hoy + 13 porque el vencimiento es inclusivo), su administrador y el
pedido de contratación. Una prueba por correo; sin verificación de correo; con cualquier plan activo."""

import datetime as dt
import json

import pytest
from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.core.exceptions import DomainError
from app.core.tenant import sin_filtro
from app.core.tiempo import hoy_utc
from app.plataforma import politicas
from app.plataforma.models import Bitacora, Empresa, PedidoContratacion, Plan, Suscripcion, Usuario
from app.plataforma.repository import PedidoContratacionRepository
from tests.plataforma.ayudas_empresas import CLAVE, login_de_empresa, registrar, suscripciones_de

API = "/api/v1"
PRUEBA = f"{API}/public/contratacion/prueba"
SUSCRIPCIONES = f"{API}/plataforma/suscripciones"
TOKEN_DE_SERVICIO = {"X-Service-Token": "token-de-pruebas"}  # TAREAS_TOKEN de tests/conftest.py
CORREO = "ana@modasol.example.com"
CAMPOS_RESPUESTA = {
    "empresa_codigo", "empresa_nombre", "plan_codigo", "plan_nombre", "es_prueba", "fecha_inicio", "fecha_vencimiento",
}  # fmt: skip


def cuerpo(nombre: str = "Moda Sol", plan: str = "basico", correo: str = CORREO, **admin) -> dict:
    return {
        "nombre": nombre,
        "plan_codigo": plan,
        "administrador": {
            "nombre": "Ana",
            "apellido": "Rojas",
            "email": correo,
            "telefono": "70000000",
            "password": CLAVE,
            **admin,
        },
    }


def pedir(client, nombre: str = "Moda Sol", plan: str = "basico", correo: str = CORREO, **kwargs):
    return client.post(PRUEBA, json=cuerpo(nombre, plan, correo), **kwargs)


def _empresa(db, codigo: str) -> Empresa | None:
    return db.scalar(select(Empresa).where(Empresa.codigo == codigo))


def _pedidos(db) -> list[PedidoContratacion]:
    return list(db.scalars(select(PedidoContratacion).order_by(PedidoContratacion.id)))


def _crear_plan(db, codigo: str, **extra) -> Plan:
    plan = Plan(
        codigo=codigo, nombre=codigo.title(), max_sucursales=3, reportes_convencionales=True, reportes_ia=False,
        operacion_offline=False, analitica_ml=False, copias_seguridad=False, gestion_productos=True,
        gestion_ventas=True, reservas=True, **extra,
    )  # fmt: skip
    db.add(plan)
    db.commit()
    return plan


def _sin_nada_creado(db, codigo: str, correo: str) -> None:
    """Ni empresa, ni pedido, ni usuario con ese correo: el rollback fue total."""
    assert _empresa(db, codigo) is None
    assert _pedidos(db) == []
    assert db.scalar(sin_filtro(select(func.count()).select_from(Usuario).where(Usuario.email == correo))) == 0


# ---- Caso feliz ------------------------------------------------------------------------------------------


def test_la_prueba_crea_una_empresa_activa_lista_para_usar(client_por_peticion, db_session):
    respuesta = pedir(client_por_peticion)

    assert respuesta.status_code == 201, respuesta.text
    hoy = hoy_utc()
    assert respuesta.json() == {
        "empresa_codigo": "moda-sol",
        "empresa_nombre": "Moda Sol",
        "plan_codigo": "basico",
        "plan_nombre": respuesta.json()["plan_nombre"],
        "es_prueba": True,
        "fecha_inicio": hoy.isoformat(),
        "fecha_vencimiento": (hoy + dt.timedelta(days=13)).isoformat(),  # 14 días completos
    }

    empresa = _empresa(db_session, "moda-sol")
    assert empresa is not None and empresa.activo is True
    (suscripcion,) = suscripciones_de(db_session, empresa.id)
    assert (suscripcion.estado, suscripcion.es_prueba) == ("activa", True)
    assert suscripcion.fecha_vencimiento == hoy + dt.timedelta(days=13)
    assert suscripcion.fecha_vencimiento - suscripcion.fecha_inicio == dt.timedelta(days=get_settings().prueba_dias - 1)

    (pedido,) = _pedidos(db_session)
    assert (pedido.tipo, pedido.estado) == ("prueba", "completado")
    assert pedido.empresa_creada_id == empresa.id
    assert (pedido.empresa_nombre, pedido.empresa_codigo, pedido.admin_email) == ("Moda Sol", "moda-sol", CORREO)
    assert pedido.admin_password_hash != CLAVE and pedido.admin_password_hash.startswith("$2")
    assert pedido.ip  # la del cliente
    assert pedido.plan_id == db_session.scalar(select(Plan.id).where(Plan.codigo == "basico"))
    assert (pedido.monto_bs, pedido.monto_usd, pedido.tipo_cambio, pedido.paypal_order_id, pedido.expira_en) == (None,) * 5
    assert pedido.token and len(pedido.token) <= 64


def test_el_administrador_inicia_sesion_y_la_tienda_esta_disponible(client_por_peticion):
    assert pedir(client_por_peticion).status_code == 201

    login = login_de_empresa(client_por_peticion, "moda-sol", CORREO)
    assert login.status_code == 200, login.text
    cabeceras = {"Authorization": f"Bearer {login.json()['access_token']}"}
    # También entra con el nombre comercial, como cualquier empresa, y con el correo en mayúsculas.
    assert login_de_empresa(client_por_peticion, "Moda Sol", CORREO.upper()).status_code == 200

    mi = client_por_peticion.get(f"{API}/mi-empresa/suscripcion", headers=cabeceras)
    assert mi.status_code == 200, mi.text
    assert (mi.json()["estado"], mi.json()["es_prueba"], mi.json()["plan_codigo"]) == ("activa", True, "basico")
    # El administrador ya puede operar (el rol y los catálogos base se crearon).
    assert client_por_peticion.get(f"{API}/sucursales", headers=cabeceras).status_code == 200
    tallas = client_por_peticion.get(f"{API}/tallas", headers=cabeceras)
    assert tallas.status_code == 200 and tallas.json()  # datos base de la empresa nueva

    tienda = client_por_peticion.get(f"{API}/public/moda-sol/tienda")
    assert tienda.status_code == 200, tienda.text
    assert tienda.json()["disponible"] is True
    assert "moda-sol" in {t["codigo"] for t in client_por_peticion.get(f"{API}/public/tiendas").json()}


@pytest.mark.parametrize("plan", ["basico", "profesional", "plan-a-medida"])
def test_cualquier_plan_activo_sirve(client_por_peticion, db_session, plan):
    if plan == "plan-a-medida":
        _crear_plan(db_session, plan)

    respuesta = pedir(client_por_peticion, plan=plan)

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["plan_codigo"] == plan
    (suscripcion,) = suscripciones_de(db_session, _empresa(db_session, "moda-sol").id)
    assert suscripcion.es_prueba is True
    assert db_session.get(Plan, suscripcion.plan_id).codigo == plan


def test_el_plan_se_acepta_con_mayusculas_y_espacios(client_por_peticion):
    assert pedir(client_por_peticion, plan=" Profesional ").json()["plan_codigo"] == "profesional"


# ---- Validaciones ---------------------------------------------------------------------------------------


def test_un_plan_inexistente_es_404_y_no_crea_nada(client_por_peticion, db_session):
    respuesta = pedir(client_por_peticion, plan="no-existe")

    assert respuesta.status_code == 404, respuesta.text
    _sin_nada_creado(db_session, "moda-sol", CORREO)


def test_un_plan_inactivo_es_409_y_no_crea_nada(client_por_peticion, db_session):
    db_session.execute(update(Plan).where(Plan.codigo == "basico").values(activo=False))
    db_session.commit()

    respuesta = pedir(client_por_peticion, plan="basico")

    assert respuesta.status_code == 409, respuesta.text
    _sin_nada_creado(db_session, "moda-sol", CORREO)


@pytest.mark.parametrize("nombre", ["FashionStore", "fashionstore", "  Fashión Store  ".replace(" ", "")])
def test_un_nombre_repetido_es_409(client_por_peticion, db_session, nombre):
    respuesta = pedir(client_por_peticion, nombre=nombre)

    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["detail"] == "Ya existe una empresa con ese nombre"
    assert _pedidos(db_session) == []


@pytest.mark.parametrize("nombre", ["Planes", "Contratación", "ADMIN", "Tiendas", "mi empresa", "Planes Ropa", "Tiendas Juan"])
def test_un_codigo_reservado_es_422(client_por_peticion, db_session, nombre):
    respuesta = pedir(client_por_peticion, nombre=nombre)

    assert respuesta.status_code == 422, respuesta.text
    assert respuesta.json()["codigo"] == "nombre_empresa_reservado"
    assert _pedidos(db_session) == []
    assert _empresa(db_session, politicas.normalizar_nombre_empresa(nombre)) is None


def test_un_nombre_sin_letras_es_invalido(client_por_peticion, db_session):
    respuesta = pedir(client_por_peticion, nombre="!!")

    assert respuesta.status_code == 400, respuesta.text
    assert _pedidos(db_session) == []


def test_el_alta_del_superadministrador_tambien_rechaza_los_codigos_reservados(client_por_peticion, db_session, superadmin_headers):
    for nombre in ("Planes", "Contratacion", "Tiendas Norte"):
        respuesta = registrar(client_por_peticion, superadmin_headers, nombre=nombre)
        assert respuesta.status_code == 422, respuesta.text
        assert respuesta.json()["codigo"] == "nombre_empresa_reservado"
    assert registrar(client_por_peticion, superadmin_headers, nombre="Planetas").status_code == 201  # "planes" no es prefijo de "planetas"


def test_ninguna_empresa_de_los_datos_de_demostracion_usa_un_codigo_reservado():
    from scripts.demo_organizaciones import ORGANIZACIONES

    codigos = ["fashionstore", "boutique-andina", "tienda-a", "tienda-b", *(o.codigo for o in ORGANIZACIONES)]
    assert len(codigos) >= 10
    for codigo in codigos:
        politicas.validar_codigo_empresa_disponible(codigo)  # no lanza


def test_los_codigos_reservados_cubren_las_rutas_publicas_y_los_prefijos_exentos():
    for palabra in ("planes", "tiendas", "contratacion", "pedidos", "public", "health", "auth", "plataforma",
                    "mi-empresa", "tareas", "pagos", "admin"):  # fmt: skip
        assert palabra in politicas.CODIGOS_EMPRESA_RESERVADOS


# ---- Una prueba por correo ----------------------------------------------------------------------------------


def test_el_mismo_correo_no_repite_la_prueba(client_por_peticion, db_session):
    assert pedir(client_por_peticion).status_code == 201

    repetida = pedir(client_por_peticion, nombre="Otra Tienda")

    assert repetida.status_code == 409, repetida.text
    assert repetida.json()["codigo"] == "prueba_ya_usada"
    assert repetida.json()["detail"] == "prueba_ya_usada"
    assert _empresa(db_session, "otra-tienda") is None
    assert len(_pedidos(db_session)) == 1


def test_el_correo_no_distingue_mayusculas(client_por_peticion, db_session):
    assert pedir(client_por_peticion, correo="Ana@ModaSol.Example.com").status_code == 201

    repetida = pedir(client_por_peticion, nombre="Otra Tienda", correo="ANA@MODASOL.EXAMPLE.COM")

    assert repetida.status_code == 409 and repetida.json()["codigo"] == "prueba_ya_usada"
    assert [p.admin_email for p in _pedidos(db_session)] == [CORREO]  # se guarda en minúsculas


@pytest.mark.parametrize("estado", ["cancelado", "fallido", "vencido"])
def test_un_pedido_que_no_prospero_libera_el_correo(client_por_peticion, db_session, estado):
    assert pedir(client_por_peticion).status_code == 201
    db_session.execute(update(PedidoContratacion).values(estado=estado))
    db_session.commit()

    otra = pedir(client_por_peticion, nombre="Otra Tienda")

    assert otra.status_code == 201, otra.text
    assert sorted(p.estado for p in _pedidos(db_session)) == sorted([estado, "completado"])


@pytest.mark.parametrize("estado", ["pendiente", "pagado", "pagado_sin_empresa", "completado"])
def test_un_pedido_en_curso_o_completado_ocupa_el_correo(client_por_peticion, db_session, estado):
    assert pedir(client_por_peticion).status_code == 201
    db_session.execute(update(PedidoContratacion).values(estado=estado))
    db_session.commit()

    assert pedir(client_por_peticion, nombre="Otra Tienda").status_code == 409


def test_una_carrera_por_el_correo_responde_el_mismo_409_y_no_deja_huerfanos(client_por_peticion, db_session, monkeypatch):
    """Si la revisión previa no ve el pedido ganador (otra petición simultánea), el índice único
    `ux_pedido_prueba_correo` salta al insertar: mismo 409 y rollback total."""
    assert pedir(client_por_peticion).status_code == 201
    original = PedidoContratacionRepository.prueba_que_ocupa_el_correo
    llamadas = []

    def ciega_la_primera_vez(self, db, correo):
        llamadas.append(correo)
        return None if len(llamadas) == 1 else original(self, db, correo)

    monkeypatch.setattr(PedidoContratacionRepository, "prueba_que_ocupa_el_correo", ciega_la_primera_vez)

    perdedora = pedir(client_por_peticion, nombre="Segunda Tienda")

    assert perdedora.status_code == 409, perdedora.text
    assert perdedora.json()["codigo"] == "prueba_ya_usada"
    assert len(llamadas) == 2  # la previa y la que decide el motivo del conflicto
    assert _empresa(db_session, "segunda-tienda") is None
    assert [p.empresa_codigo for p in _pedidos(db_session)] == ["moda-sol"]


# ---- Entrada --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("password", ["corta12", "x" * 73, ""])
def test_la_contrasena_debe_tener_de_8_a_72_caracteres(client_por_peticion, db_session, password):
    respuesta = pedir(client_por_peticion)  # ya existe una; esta usa otro correo y otro nombre
    assert respuesta.status_code == 201
    mala = client_por_peticion.post(PRUEBA, json=cuerpo("Otra Tienda", correo="otro@modasol.example.com", password=password))

    assert mala.status_code == 422, mala.text
    assert len(_pedidos(db_session)) == 1


def test_las_contrasenas_de_8_y_72_caracteres_se_aceptan(client_por_peticion):
    assert client_por_peticion.post(PRUEBA, json=cuerpo("Uno", correo="uno@x.example.com", password="12345678")).status_code == 201
    assert client_por_peticion.post(PRUEBA, json=cuerpo("Dos", correo="dos@x.example.com", password="p" * 72)).status_code == 201


@pytest.mark.parametrize(
    "campo",
    [
        {"fecha_vencimiento": "2030-01-01"},
        {"logo_url": "https://x.example.com/logo.png"},
        {"color_acento": "#112233"},
        {"activo": False},
        {"id": 7},
    ],
)
def test_un_campo_extra_en_la_empresa_es_422(client_por_peticion, db_session, campo):
    respuesta = client_por_peticion.post(PRUEBA, json={**cuerpo(), **campo})

    assert respuesta.status_code == 422, respuesta.text
    _sin_nada_creado(db_session, "moda-sol", CORREO)


@pytest.mark.parametrize("campo", [{"rol": "superadministrador"}, {"activo": False}, {"empresa_id": 1}])
def test_un_campo_extra_en_el_administrador_es_422(client_por_peticion, db_session, campo):
    respuesta = client_por_peticion.post(PRUEBA, json=cuerpo(**campo))

    assert respuesta.status_code == 422, respuesta.text
    _sin_nada_creado(db_session, "moda-sol", CORREO)


@pytest.mark.parametrize("quitar", ["nombre", "plan_codigo", "administrador"])
def test_faltan_campos_obligatorios(client_por_peticion, quitar):
    datos = cuerpo()
    del datos[quitar]
    assert client_por_peticion.post(PRUEBA, json=datos).status_code == 422


def test_un_correo_invalido_o_un_nombre_corto_es_422(client_por_peticion):
    assert client_por_peticion.post(PRUEBA, json=cuerpo(correo="no-es-correo")).status_code == 422
    assert client_por_peticion.post(PRUEBA, json=cuerpo(nombre="A")).status_code == 422
    assert client_por_peticion.post(PRUEBA, json=cuerpo(nombre="N" * 121)).status_code == 422


# ---- Lo que NO se filtra --------------------------------------------------------------------------------------


def test_la_respuesta_no_trae_secretos(client_por_peticion):
    respuesta = pedir(client_por_peticion)

    assert set(respuesta.json()) == CAMPOS_RESPUESTA
    texto = respuesta.text.lower()
    for prohibido in (CLAVE.lower(), "$2b$", "hash", "token", "password", CORREO, "ana", "70000000"):
        assert prohibido not in texto


def test_la_bitacora_registra_la_prueba_sin_datos_personales(client_por_peticion, db_session):
    assert pedir(client_por_peticion).status_code == 201
    empresa = _empresa(db_session, "moda-sol")

    filas = list(db_session.scalars(select(Bitacora).where(Bitacora.empresa_id == empresa.id, Bitacora.entidad == "empresa")))

    assert len(filas) == 1
    fila = filas[0]
    assert (fila.accion, fila.entidad_id, fila.usuario_id) == ("crear", empresa.id, None)
    assert fila.datos == {"codigo": "moda-sol", "plan": "basico", "es_prueba": True}
    assert fila.ip
    texto = json.dumps(fila.datos).lower()
    assert CORREO not in texto and "ana" not in texto and "moda sol" not in texto


# ---- Atomicidad -------------------------------------------------------------------------------------------


def test_si_algo_falla_a_mitad_no_queda_nada_a_medias(client_por_peticion, db_session, monkeypatch):
    from app.plataforma.casos_uso import cu04_gestionar_empresas_planes_suscripciones as cu04

    def explota(db, empresa_id):
        raise DomainError("Falla simulada", 503)

    monkeypatch.setattr(cu04, "inicializar_empresa", explota)

    fallida = pedir(client_por_peticion)

    assert fallida.status_code == 503, fallida.text
    _sin_nada_creado(db_session, "moda-sol", CORREO)
    assert db_session.scalar(sin_filtro(select(func.count()).select_from(Suscripcion).where(Suscripcion.es_prueba.is_(True)))) == 0
    assert db_session.scalar(select(func.count()).select_from(Bitacora).where(Bitacora.entidad == "empresa")) == 0

    # El correo y el nombre no se gastaron: al arreglarse la falla, el visitante puede intentarlo de nuevo.
    monkeypatch.undo()
    assert pedir(client_por_peticion).status_code == 201


def test_la_ruta_siempre_es_anonima_aunque_el_navegador_mande_un_token_de_otra_empresa(client_por_peticion, db_session, dos_empresas):
    # El token de B sigue vigente, pero su suscripción está suspendida: no debe afectar a la prueba.
    db_session.execute(
        sin_filtro(update(Suscripcion).where(Suscripcion.empresa_id == dos_empresas.b.id).values(estado="suspendida")),
        execution_options={"synchronize_session": False},
    )
    db_session.commit()

    respuesta = pedir(client_por_peticion, headers=dos_empresas.b.headers)

    assert respuesta.status_code == 201, respuesta.text
    empresa = _empresa(db_session, "moda-sol")
    assert empresa is not None and empresa.id not in (dos_empresas.a.id, dos_empresas.b.id)
    assert suscripciones_de(db_session, empresa.id)[0].es_prueba is True


# ---- Vencimiento -----------------------------------------------------------------------------------------


def test_al_vencer_la_prueba_la_tienda_deja_de_estar_disponible_y_no_se_borra_nada(client_por_peticion, db_session):
    assert pedir(client_por_peticion).status_code == 201
    empresa = _empresa(db_session, "moda-sol")
    empresa_id = empresa.id
    ayer = hoy_utc() - dt.timedelta(days=1)
    db_session.execute(
        sin_filtro(update(Suscripcion).where(Suscripcion.empresa_id == empresa_id).values(fecha_inicio=ayer - dt.timedelta(days=13), fecha_vencimiento=ayer)),
        execution_options={"synchronize_session": False},
    )
    db_session.commit()

    # Estado efectivo: vencida aunque la tarea todavía no corrió.
    assert client_por_peticion.get(f"{API}/public/moda-sol/tienda").json()["disponible"] is False
    assert "moda-sol" not in {t["codigo"] for t in client_por_peticion.get(f"{API}/public/tiendas").json()}
    assert client_por_peticion.get(f"{API}/public/moda-sol/catalogo").status_code == 403
    login = login_de_empresa(client_por_peticion, "moda-sol", CORREO)
    assert login.status_code == 200  # puede entrar a ver su estado y pedir la renovación
    cabeceras = {"Authorization": f"Bearer {login.json()['access_token']}"}
    mi = client_por_peticion.get(f"{API}/mi-empresa/suscripcion", headers=cabeceras).json()
    assert (mi["estado"], mi["es_prueba"]) == ("vencida", True)
    assert client_por_peticion.get(f"{API}/sucursales", headers=cabeceras).status_code == 403

    # La tarea periódica lo persiste; la empresa, el usuario y el pedido siguen ahí.
    tarea = client_por_peticion.post(f"{API}/tareas/vencer-suscripciones", headers=TOKEN_DE_SERVICIO)
    assert tarea.status_code == 200 and tarea.json()["vencidas"] >= 1
    (suscripcion,) = suscripciones_de(db_session, empresa_id)
    assert (suscripcion.estado, suscripcion.es_prueba) == ("vencida", True)
    assert _empresa(db_session, "moda-sol").activo is True
    assert [p.estado for p in _pedidos(db_session)] == ["completado"]
    assert db_session.scalar(sin_filtro(select(func.count()).select_from(Usuario).where(Usuario.email == CORREO))) == 1


def test_el_ultimo_dia_de_la_prueba_la_tienda_sigue_disponible(client_por_peticion, db_session):
    assert pedir(client_por_peticion).status_code == 201
    hoy = hoy_utc()
    db_session.execute(
        sin_filtro(update(Suscripcion).where(Suscripcion.es_prueba.is_(True)).values(fecha_inicio=hoy - dt.timedelta(days=13), fecha_vencimiento=hoy)),
        execution_options={"synchronize_session": False},
    )
    db_session.commit()

    assert client_por_peticion.get(f"{API}/public/moda-sol/tienda").json()["disponible"] is True


# ---- Límite de tasa --------------------------------------------------------------------------------------------


def test_el_limite_por_ip_es_de_5_por_hora_y_solo_cuentan_las_peticiones_validas(client_por_peticion):
    for _ in range(8):  # el cuerpo inválido se rechaza antes de contar
        assert client_por_peticion.post(PRUEBA, json=cuerpo(password="corta")).status_code == 422
    for i in range(5):
        assert client_por_peticion.post(PRUEBA, json=cuerpo(f"Tienda Limite {i}", correo=f"u{i}@x.example.com")).status_code == 201

    sexta = client_por_peticion.post(PRUEBA, json=cuerpo("Tienda Limite 6", correo="u6@x.example.com"))

    assert sexta.status_code == 429, sexta.text


# ---- Pasar de prueba a pago (fase 3) ------------------------------------------------------------------------------


def _id_de_la_prueba(client, db, superadmin_headers) -> int:
    assert pedir(client).status_code == 201
    return _empresa(db, "moda-sol").id


def test_una_prueba_puede_cambiarse_al_mismo_plan_y_deja_de_ser_prueba(client_por_peticion, db_session, superadmin_headers):
    empresa_id = _id_de_la_prueba(client_por_peticion, db_session, superadmin_headers)

    cambio = client_por_peticion.post(SUSCRIPCIONES, json={"empresa_id": empresa_id, "plan_codigo": "basico"}, headers=superadmin_headers)

    assert cambio.status_code == 201, cambio.text
    assert (cambio.json()["plan_codigo"], cambio.json()["es_prueba"], cambio.json()["estado_efectivo"]) == ("basico", False, "activa")
    antigua, nueva = suscripciones_de(db_session, empresa_id)
    assert (antigua.estado, antigua.es_prueba) == ("cancelada", True)  # el historial conserva que fue prueba
    assert (nueva.estado, nueva.es_prueba) == ("activa", False)
    assert nueva.fecha_vencimiento == hoy_utc() + dt.timedelta(days=get_settings().suscripcion_dias_por_defecto)
    fila = db_session.scalar(select(Bitacora).where(Bitacora.entidad == "suscripcion", Bitacora.accion == "cambiar_plan"))
    assert fila.datos["era_prueba"] is True and fila.datos["plan_antes"] == fila.datos["plan_despues"] == "basico"
    # Y ya no es prueba: pedir el mismo plan otra vez vuelve a ser un 409.
    otra = client_por_peticion.post(SUSCRIPCIONES, json={"empresa_id": empresa_id, "plan_codigo": "basico"}, headers=superadmin_headers)
    assert otra.status_code == 409, otra.text


def test_una_prueba_tambien_puede_cambiarse_a_otro_plan(client_por_peticion, db_session, superadmin_headers):
    empresa_id = _id_de_la_prueba(client_por_peticion, db_session, superadmin_headers)

    cambio = client_por_peticion.post(SUSCRIPCIONES, json={"empresa_id": empresa_id, "plan_codigo": "profesional"}, headers=superadmin_headers)

    assert cambio.status_code == 201, cambio.text
    assert (cambio.json()["plan_codigo"], cambio.json()["es_prueba"]) == ("profesional", False)


def test_el_mismo_plan_sigue_siendo_409_si_la_suscripcion_no_es_de_prueba(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    respuesta = client_por_peticion.post(SUSCRIPCIONES, json={"empresa_id": dos_empresas.b.id, "plan_codigo": "basico"}, headers=superadmin_headers)

    assert respuesta.status_code == 409, respuesta.text


def test_renovar_una_prueba_la_convierte_en_suscripcion_normal(client_por_peticion, db_session, superadmin_headers):
    empresa_id = _id_de_la_prueba(client_por_peticion, db_session, superadmin_headers)
    (prueba,) = suscripciones_de(db_session, empresa_id)
    nueva_fecha = (hoy_utc() + dt.timedelta(days=60)).isoformat()

    renovada = client_por_peticion.put(f"{SUSCRIPCIONES}/{prueba.id}/renovar", json={"fecha_vencimiento": nueva_fecha}, headers=superadmin_headers)

    assert renovada.status_code == 200, renovada.text
    assert (renovada.json()["es_prueba"], renovada.json()["fecha_vencimiento"]) == (False, nueva_fecha)
    (despues,) = suscripciones_de(db_session, empresa_id)  # renovar no crea otra fila
    assert despues.es_prueba is False
    fila = db_session.scalar(select(Bitacora).where(Bitacora.entidad == "suscripcion", Bitacora.accion == "renovar"))
    assert fila.datos["era_prueba"] is True


def test_renovar_una_prueba_vencida_la_reactiva_como_normal(client_por_peticion, db_session, superadmin_headers):
    empresa_id = _id_de_la_prueba(client_por_peticion, db_session, superadmin_headers)
    (prueba,) = suscripciones_de(db_session, empresa_id)
    ayer = hoy_utc() - dt.timedelta(days=1)
    db_session.execute(
        sin_filtro(update(Suscripcion).where(Suscripcion.id == prueba.id).values(fecha_inicio=ayer - dt.timedelta(days=13), fecha_vencimiento=ayer)),
        execution_options={"synchronize_session": False},
    )
    db_session.commit()

    renovada = client_por_peticion.put(
        f"{SUSCRIPCIONES}/{prueba.id}/renovar",
        json={"fecha_vencimiento": (hoy_utc() + dt.timedelta(days=30)).isoformat()},
        headers=superadmin_headers,
    )

    assert renovada.status_code == 200, renovada.text
    assert (renovada.json()["estado_efectivo"], renovada.json()["es_prueba"]) == ("activa", False)
    assert client_por_peticion.get(f"{API}/public/moda-sol/tienda").json()["disponible"] is True


def test_renovar_una_suscripcion_normal_no_la_marca_como_prueba(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    (vigente,) = suscripciones_de(db_session, dos_empresas.b.id)

    renovada = client_por_peticion.put(
        f"{SUSCRIPCIONES}/{vigente.id}/renovar",
        json={"fecha_vencimiento": (hoy_utc() + dt.timedelta(days=400)).isoformat()},
        headers=superadmin_headers,
    )

    assert renovada.status_code == 200 and renovada.json()["es_prueba"] is False
    fila = db_session.scalar(select(Bitacora).where(Bitacora.entidad == "suscripcion", Bitacora.accion == "renovar"))
    assert "era_prueba" not in fila.datos
