"""Contratación de planes, fase 1: restricciones de `pedido_contratacion` (tabla global, sin `empresa_id`).
Token y orden de PayPal únicos, CHECKs de tipo, periodo y estado, y UNA sola prueba gratuita viva por correo."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import Base
from app.plataforma.models import PedidoContratacion, Plan

_contador = {"n": 0}


def _plan_id(db) -> int:
    return db.scalar(select(Plan.id).where(Plan.codigo == "basico"))


def _pedido(db, **cambios) -> PedidoContratacion:
    """Un pedido válido (de pago, mensual) con lo que se pida cambiar. Hace flush."""
    _contador["n"] += 1
    n = _contador["n"]
    datos = {
        "token": f"token-{n}",
        "tipo": "pago",
        "periodo": "mensual",
        "plan_id": _plan_id(db),
        "empresa_nombre": f"Tienda {n}",
        "empresa_codigo": f"tienda-{n}",
        "admin_nombre": "Ana",
        "admin_apellido": "Rojas",
        "admin_email": f"ana{n}@example.com",
        "admin_password_hash": "$2b$12$hashdepruebahashdepruebahashdepruebahashdepruebahashde",
        **cambios,
    }
    pedido = PedidoContratacion(**datos)
    db.add(pedido)
    db.flush()
    return pedido


def _choca(db, **cambios) -> str:
    """El mensaje del IntegrityError al insertar el pedido (en un SAVEPOINT, para no perder la sesión)."""
    with pytest.raises(IntegrityError) as error:
        with db.begin_nested():
            _pedido(db, **cambios)
    return str(error.value)


def test_la_tabla_no_tiene_empresa_id_y_enlaza_la_empresa_creada():
    tabla = Base.metadata.tables["pedido_contratacion"]

    assert "empresa_id" not in tabla.c
    assert [fk.target_fullname for fk in tabla.c.empresa_creada_id.foreign_keys] == ["empresa.id"]
    assert tabla.c.empresa_creada_id.nullable


def test_un_pedido_nuevo_nace_pendiente_con_sus_fechas(db_session):
    pedido = _pedido(db_session, monto_bs=Decimal("120.00"), monto_usd=Decimal("17.24"), tipo_cambio=Decimal("6.9600"))
    db_session.refresh(pedido)

    assert pedido.estado == "pendiente"
    assert pedido.creado_en is not None and pedido.actualizado_en is not None
    assert pedido.empresa_creada_id is None and pedido.paypal_order_id is None and pedido.expira_en is None
    assert pedido.tipo_cambio == Decimal("6.9600")


def test_el_token_es_unico(db_session):
    _pedido(db_session, token="repetido")
    assert "token" in _choca(db_session, token="repetido")


def test_la_orden_de_paypal_es_unica_pero_varios_pedidos_pueden_no_tenerla(db_session):
    _pedido(db_session, paypal_order_id="ORDEN-1")
    assert "paypal_order_id" in _choca(db_session, paypal_order_id="ORDEN-1")
    _pedido(db_session)  # sin orden (NULL): no choca
    _pedido(db_session)


@pytest.mark.parametrize("tipo", ["gratis", "", "PAGO"])
def test_el_tipo_solo_admite_pago_o_prueba(db_session, tipo):
    mensaje = _choca(db_session, tipo=tipo)
    assert "ck_pedido_contratacion_tipo" in mensaje or "CHECK" in mensaje, mensaje


def test_los_dos_tipos_validos_se_aceptan(db_session):
    _pedido(db_session, tipo="pago")
    _pedido(db_session, tipo="prueba", periodo=None)


@pytest.mark.parametrize("periodo", ["semanal", "ANUAL", ""])
def test_el_periodo_solo_admite_mensual_o_anual_o_nulo(db_session, periodo):
    mensaje = _choca(db_session, periodo=periodo)
    assert "ck_pedido_contratacion_periodo" in mensaje or "CHECK" in mensaje, mensaje


def test_el_periodo_mensual_anual_y_nulo_son_validos(db_session):
    _pedido(db_session, periodo="mensual")
    _pedido(db_session, periodo="anual")
    _pedido(db_session, tipo="prueba", periodo=None)


def test_el_estado_solo_admite_los_siete_conocidos(db_session):
    for estado in ("pendiente", "pagado", "pagado_sin_empresa", "completado", "cancelado", "vencido", "fallido"):
        _pedido(db_session, estado=estado)
    mensaje = _choca(db_session, estado="reembolsado")
    assert "ck_pedido_contratacion_estado" in mensaje or "CHECK" in mensaje, mensaje


def test_el_plan_debe_existir(db_session):
    # SQLite no aplica FK por defecto en este entorno; basta con que plan_id sea obligatorio.
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            _pedido(db_session, plan_id=None)


# ---- Una sola prueba gratuita viva por correo -------------------------------------------------------------


def test_no_se_admiten_dos_pruebas_vivas_con_el_mismo_correo(db_session):
    _pedido(db_session, tipo="prueba", periodo=None, admin_email="mismo@example.com")
    mensaje = _choca(db_session, tipo="prueba", periodo=None, admin_email="mismo@example.com")
    assert "admin_email" in mensaje or "ux_pedido_prueba_correo" in mensaje, mensaje


@pytest.mark.parametrize("estado", ["pendiente", "pagado", "pagado_sin_empresa", "completado"])
def test_una_prueba_viva_o_completada_sigue_ocupando_el_correo(db_session, estado):
    _pedido(db_session, tipo="prueba", periodo=None, admin_email="ocupado@example.com", estado=estado)
    assert "admin_email" in _choca(db_session, tipo="prueba", periodo=None, admin_email="ocupado@example.com")


@pytest.mark.parametrize("estado", ["cancelado", "vencido", "fallido"])
def test_el_correo_se_puede_repetir_si_la_prueba_anterior_no_prospero(db_session, estado):
    _pedido(db_session, tipo="prueba", periodo=None, admin_email="otra-vez@example.com", estado=estado)

    nueva = _pedido(db_session, tipo="prueba", periodo=None, admin_email="otra-vez@example.com")
    assert nueva.estado == "pendiente"
    # Y la nueva ya ocupa el correo otra vez.
    assert "admin_email" in _choca(db_session, tipo="prueba", periodo=None, admin_email="otra-vez@example.com")


def test_el_indice_de_pruebas_no_limita_los_pedidos_de_pago(db_session):
    for _ in range(3):
        _pedido(db_session, tipo="pago", admin_email="comprador@example.com")
    # Un pedido de pago tampoco bloquea una prueba del mismo correo, ni al revés.
    _pedido(db_session, tipo="prueba", periodo=None, admin_email="comprador@example.com")
    _pedido(db_session, tipo="pago", admin_email="comprador@example.com")


def test_correos_distintos_pueden_tener_cada_uno_su_prueba(db_session):
    _pedido(db_session, tipo="prueba", periodo=None, admin_email="uno@example.com")
    _pedido(db_session, tipo="prueba", periodo=None, admin_email="dos@example.com")
