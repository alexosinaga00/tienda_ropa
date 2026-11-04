"""Compra de un plan con PayPal en PostgreSQL real (PayPal simulado): capturas SIMULTÁNEAS del mismo pedido.

SQLite no aplica `SELECT ... FOR UPDATE`. Aquí la segunda captura espera a la primera en el bloqueo de la fila del
pedido, la ve ya `completado` y devuelve la misma empresa SIN cobrar ni crear nada: UNA empresa y UNA captura aunque
lleguen varias a la vez. Las sesiones son anónimas (sin empresa), como en producción, y cada hilo tiene la suya."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import ErrorFuncional
from app.core.tenant import sin_filtro
from app.plataforma.casos_uso.cu04_gestionar_empresas_planes_suscripciones import GestionarContratacion
from app.plataforma.models import Empresa, PedidoContratacion, Suscripcion, Usuario
from app.plataforma.schemas import PedidoSolicitud
from tests.paypal_simulado import SimuladorPayPal
from tests.postgres.paralelo import ejecutar_en_paralelo

CLAVE = "claveSegura123"


@pytest.fixture()
def anonimas(engine_pg):
    """Sesiones SIN empresa (a diferencia de `fabrica_pg`, que fija la de pruebas)."""
    return sessionmaker(bind=engine_pg, autoflush=False, autocommit=False)


@pytest.fixture()
def pp(monkeypatch) -> SimuladorPayPal:
    return SimuladorPayPal(monkeypatch)


def _solicitud(nombre: str, correo: str) -> PedidoSolicitud:
    return PedidoSolicitud(
        nombre=nombre,
        plan_codigo="basico",
        periodo="mensual",
        administrador={"nombre": "Ana", "apellido": "Rojas", "email": correo, "password": CLAVE},
    )


def _crear_pedido(anonimas, nombre: str, correo: str, pp: SimuladorPayPal, aprobar: bool = True) -> str:
    with anonimas() as db:
        token = GestionarContratacion().crear_pedido(db, _solicitud(nombre, correo)).token
    if aprobar:
        pp.aprobar()
    return token


def _contar(anonimas) -> dict:
    with anonimas() as db:
        return {
            "empresas": db.scalar(select(func.count()).select_from(Empresa).where(Empresa.codigo != "fashionstore")),
            "suscripciones_pagas": db.scalar(
                sin_filtro(select(func.count()).select_from(Suscripcion).where(Suscripcion.es_prueba.is_(False), Suscripcion.empresa_id != 1))
            ),
            "administradores": db.scalar(
                sin_filtro(select(func.count()).select_from(Usuario).where(Usuario.email.like("%@carrera.example.com")))
            ),
        }


def _estado(anonimas, token: str) -> str:
    with anonimas() as db:
        return db.scalar(select(PedidoContratacion.estado).where(PedidoContratacion.token == token))


@pytest.mark.parametrize("hilos", [2, 5])
def test_capturas_simultaneas_del_mismo_pedido_crean_una_sola_empresa_y_cobran_una_vez(anonimas, pp, hilos):
    token = _crear_pedido(anonimas, "Carrera Uno", "ana@carrera.example.com", pp)
    pp.demora_captura = 0.4  # ensancha la ventana: los demás llegan mientras el primero cobra
    operaciones = [lambda db: GestionarContratacion().capturar_pedido(db, token) for _ in range(hilos)]

    resultados = ejecutar_en_paralelo(anonimas, operaciones)

    assert all(r.ok for r in resultados), [repr(r.error) for r in resultados if not r.ok]
    assert {r.valor.empresa_codigo for r in resultados} == {"carrera-uno"}
    assert {r.valor.estado for r in resultados} == {"completado"}
    assert pp.capturas == 1 and pp.peticiones_de_captura == 1  # los demás ni siquiera llaman a capturar
    assert _contar(anonimas) == {"empresas": 1, "suscripciones_pagas": 1, "administradores": 1}
    assert _estado(anonimas, token) == "completado"


def test_una_captura_y_una_cancelacion_simultaneas_dejan_un_estado_coherente(anonimas, pp):
    token = _crear_pedido(anonimas, "Carrera Dos", "ana@carrera.example.com", pp)
    pp.demora_captura = 0.3
    operaciones = [
        lambda db: GestionarContratacion().capturar_pedido(db, token),
        lambda db: GestionarContratacion().cancelar_pedido(db, token),
    ]

    capturar, cancelar = ejecutar_en_paralelo(anonimas, operaciones)

    estado = _estado(anonimas, token)
    if estado == "completado":  # ganó la captura: la cancelación no puede deshacer un cobro
        assert capturar.ok and not cancelar.ok
        assert isinstance(cancelar.error, ErrorFuncional) and cancelar.error.codigo == "pedido_ya_pagado"
        assert pp.capturas == 1 and _contar(anonimas)["empresas"] == 1
    else:  # ganó la cancelación: nada se cobra
        assert estado == "cancelado" and cancelar.ok and not capturar.ok
        assert isinstance(capturar.error, ErrorFuncional) and capturar.error.codigo == "pedido_cancelado"
        assert pp.capturas == 0 and _contar(anonimas)["empresas"] == 0


def test_dos_pedidos_del_mismo_nombre_pagados_a_la_vez_dejan_una_empresa_y_un_pagado_sin_empresa(anonimas, pp):
    primero = _crear_pedido(anonimas, "Misma Tienda", "uno@carrera.example.com", pp, aprobar=False)
    segundo = _crear_pedido(anonimas, "Misma Tienda", "dos@carrera.example.com", pp, aprobar=False)
    pp.aprobar("ORD-SIM-0001")
    pp.aprobar("ORD-SIM-0002")
    operaciones = [
        lambda db: GestionarContratacion().capturar_pedido(db, primero),
        lambda db: GestionarContratacion().capturar_pedido(db, segundo),
    ]

    resultados = ejecutar_en_paralelo(anonimas, operaciones)

    ganadoras = [r for r in resultados if r.ok]
    perdedoras = [r for r in resultados if not r.ok]
    assert len(ganadoras) == 1 and len(perdedoras) == 1, [repr(r.error) for r in perdedoras]
    assert isinstance(perdedoras[0].error, ErrorFuncional) and perdedoras[0].error.codigo == "pagado_sin_empresa"
    assert _contar(anonimas)["empresas"] == 1
    assert sorted([_estado(anonimas, primero), _estado(anonimas, segundo)]) == ["completado", "pagado_sin_empresa"]
    assert pp.capturas == 2  # la perdedora sí pagó: reembolso manual
    # Y el reintento de la perdedora no vuelve a cobrar.
    perdedor = primero if _estado(anonimas, primero) == "pagado_sin_empresa" else segundo
    with anonimas() as db:
        with pytest.raises(ErrorFuncional) as error:
            GestionarContratacion().capturar_pedido(db, perdedor)
    assert error.value.codigo == "pagado_sin_empresa" and pp.capturas == 2 and pp.peticiones_de_captura == 2
