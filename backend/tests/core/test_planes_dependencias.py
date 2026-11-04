"""E04: las dependencias de plan y suscripción de `core/planes.py`, el
`ErrorFuncional` y el gancho de inicialización de empresas de `core/tenant.py`."""

import datetime as dt
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import planes, tenant
from app.core.exceptions import ErrorFuncional, registrar_handlers
from app.core.planes import (
    FUNCIONALIDADES,
    exigir_funcionalidad,
    ruta_exenta_de_suscripcion,
    verificar_funcionalidad,
    verificar_suscripcion_activa,
)
from app.core.tenant import en_empresa, empresa_de, en_modo_plataforma, fijar_empresa, fijar_plataforma
from app.plataforma import politicas
from app.plataforma.models import Empresa, Suscripcion
from tests.conftest import crear_empresa


def _cambiar_suscripcion(db, **campos) -> None:
    suscripcion = db.scalar(select(Suscripcion).where(Suscripcion.estado != "cancelada"))
    for campo, valor in campos.items():
        setattr(suscripcion, campo, valor)
    db.commit()


def test_exigir_funcionalidad_valida_el_nombre_al_importar():
    with pytest.raises(ValueError, match="Funcionalidad desconocida"):
        exigir_funcionalidad("tipo_invalido")
    for nombre in FUNCIONALIDADES:
        assert callable(exigir_funcionalidad(nombre))
    with pytest.raises(ValueError):
        verificar_funcionalidad(None, "tipo_invalido")


def test_verificar_funcionalidad_lee_el_plan_de_la_base(db_session):
    # 'fashionstore' es Profesional: todo incluido.
    for nombre in FUNCIONALIDADES:
        verificar_funcionalidad(db_session, nombre)

    basica = crear_empresa(db_session, "tienda-basica", plan="basico")
    fijar_empresa(db_session, basica.id)
    verificar_funcionalidad(db_session, planes.FUNC_GESTION_VENTAS)
    with pytest.raises(ErrorFuncional) as error:
        verificar_funcionalidad(db_session, planes.FUNC_REPORTES_IA)
    assert error.value.status_code == 403
    assert error.value.cuerpo() == {
        "detail": "plan_no_incluye_funcionalidad",
        "codigo": "plan_no_incluye_funcionalidad",
        "mensaje": "Su plan no incluye esta funcionalidad",
        "funcionalidad": "reportes_ia",
        "plan": "basico",
    }


@pytest.mark.parametrize(
    "cambios, estado",
    [
        ({"estado": "suspendida"}, "suspendida"),
        ({"estado": "cancelada"}, "sin_suscripcion"),  # la cancelada ya no es la vigente
        ({"estado": "vencida"}, "vencida"),
        ({"fecha_vencimiento": dt.date.today() - dt.timedelta(days=1), "fecha_inicio": dt.date.today() - dt.timedelta(days=30)}, "vencida"),
    ],
)
def test_verificar_suscripcion_activa_rechaza_lo_que_no_esta_activo(db_session, cambios, estado):
    verificar_suscripcion_activa(db_session)  # activa y vigente
    _cambiar_suscripcion(db_session, **cambios)
    with pytest.raises(ErrorFuncional) as error:
        verificar_suscripcion_activa(db_session)
    assert error.value.status_code == 403
    assert error.value.codigo == "suscripcion_no_activa"
    assert error.value.contexto == {"estado": estado}


def test_una_empresa_inactiva_no_pasa_la_verificacion(db_session):
    db_session.get(Empresa, 1).activo = False
    db_session.commit()
    with pytest.raises(ErrorFuncional) as error:
        verificar_suscripcion_activa(db_session)
    assert error.value.contexto == {"estado": "empresa_inactiva"}


def test_las_rutas_exentas_de_suscripcion_son_las_documentadas():
    exentas = [
        "/health",
        "/api/v1/auth/login",
        "/api/v1/auth/recuperar/confirmar",
        "/api/v1/mi-empresa",
        "/api/v1/mi-empresa/suscripcion",
        "/api/v1/plataforma/empresas",
        "/api/v1/public/tiendas",
        "/api/v1/public/planes",
        "/api/v1/public/contratacion/prueba",
        "/api/v1/public/contratacion/pedidos",
        "/api/v1/public/contratacion/pedidos/abc123",
        "/api/v1/public/contratacion/pedidos/abc123/capturar",
        "/api/v1/public/contratacion/pedidos/abc123/cancelar",
        "/api/v1/public/boutique-andina/tienda",
        "/api/v1/pagos/webhook/libelula",
        "/api/v1/pagos/qr/abc",
        "/api/v1/tareas/expirar-reservas",
    ]
    protegidas = [
        "/api/v1/productos",
        "/api/v1/ventas",
        "/api/v1/pagos",
        "/api/v1/pagos/1",
        "/api/v1/public/boutique-andina/catalogo",
        "/api/v1/public/boutique-andina/tienda/otra",
        "/api/v1/public/boutique-andina/registro",
        "/api/v1/usuarios",
        "/api/v1/catalogo",
    ]
    assert all(ruta_exenta_de_suscripcion(r) for r in exentas)
    assert not any(ruta_exenta_de_suscripcion(r) for r in protegidas)
    assert planes.RUTAS_SIN_SUSCRIPCION == (
        "/health",
        "/api/v1/auth/",
        "/api/v1/mi-empresa",
        "/api/v1/plataforma/",
        "/api/v1/public/tiendas",
        "/api/v1/public/planes",
        "/api/v1/public/contratacion/",  # contratación pública (prueba gratuita): no es una tienda
        "/api/v1/pagos/webhook/",
        "/api/v1/pagos/qr/",
        "/api/v1/tareas/",
        "/api/v1/sincronizacion/lote",  # E07: para guardar el rechazo de cada operación (D16)
    )


def test_la_situacion_se_calcula_una_sola_vez_por_peticion(db_session, monkeypatch):
    llamadas = []
    original = politicas.situacion_de_la_empresa
    monkeypatch.setattr(politicas, "situacion_de_la_empresa", lambda db: (llamadas.append(1), original(db))[1])
    peticion = SimpleNamespace(state=SimpleNamespace())

    verificar_suscripcion_activa(db_session, peticion)
    verificar_funcionalidad(db_session, planes.FUNC_RESERVAS, peticion)
    verificar_suscripcion_activa(db_session, peticion)
    assert len(llamadas) == 1

    # Otra petición (o la misma sesión con otra empresa) no reutiliza el cálculo.
    verificar_suscripcion_activa(db_session, SimpleNamespace(state=SimpleNamespace()))
    assert len(llamadas) == 2


def test_error_funcional_responde_con_detail_codigo_mensaje_y_contexto():
    app = FastAPI()
    registrar_handlers(app)

    @app.get("/limite")
    def limite():
        raise ErrorFuncional("limite_plan_excedido", "Demasiadas sucursales", 409, recurso="sucursales", limite=2, actual=2)

    respuesta = TestClient(app).get("/limite")
    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "detail": "limite_plan_excedido",
        "codigo": "limite_plan_excedido",
        "mensaje": "Demasiadas sucursales",
        "recurso": "sucursales",
        "limite": 2,
        "actual": 2,
    }


# ---- core/tenant.py: en_empresa y los inicializadores ------------------------------


def test_en_empresa_restaura_la_empresa_o_el_modo_plataforma(db_session):
    otra = crear_empresa(db_session, "otra-empresa").id
    assert empresa_de(db_session) == 1

    with en_empresa(db_session, otra):
        assert empresa_de(db_session) == otra
    assert empresa_de(db_session) == 1

    fijar_plataforma(db_session)
    with en_empresa(db_session, otra):
        assert empresa_de(db_session) == otra
        assert not en_modo_plataforma(db_session)
    assert en_modo_plataforma(db_session)
    assert empresa_de(db_session) is None


def test_en_empresa_restaura_aunque_falle_lo_de_adentro(db_session):
    otra = crear_empresa(db_session, "otra-empresa").id
    with pytest.raises(RuntimeError):
        with en_empresa(db_session, otra):
            raise RuntimeError("falló")
    assert empresa_de(db_session) == 1


def test_inicializar_empresa_corre_los_inicializadores_dentro_de_la_empresa(db_session, monkeypatch):
    monkeypatch.setattr(tenant, "_inicializadores", [])
    vistos = []

    @tenant.registrar_inicializador
    def anotar(db):
        vistos.append(empresa_de(db))

    tenant.registrar_inicializador(anotar)  # idempotente: no se duplica
    nueva = crear_empresa(db_session, "nueva-empresa").id
    tenant.inicializar_empresa(db_session, nueva)

    assert vistos == [nueva]
    assert empresa_de(db_session) == 1
