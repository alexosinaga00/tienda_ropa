"""Contratación de planes, fase 1: `plan.precio_mensual_bs` (visible en la portada, editable por el
superadministrador, nunca negativo) y `suscripcion.es_prueba` (falso por defecto). Los montos salen como texto
JSON ("120.00"), igual que los demás montos del proyecto."""

from decimal import Decimal

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.core.tenant import sin_filtro
from app.plataforma.models import Plan, Suscripcion

PUBLICO = "/api/v1/public/planes"
PLATAFORMA = "/api/v1/plataforma"
MI_SUSCRIPCION = "/api/v1/mi-empresa/suscripcion"


def _plan_id(db_session, codigo: str) -> int:
    return db_session.scalar(select(Plan.id).where(Plan.codigo == codigo))


def _publicos(client) -> dict:
    respuesta = client.get(PUBLICO)
    assert respuesta.status_code == 200, respuesta.text
    return {p["codigo"]: p for p in respuesta.json()}


# ---- Precio del plan -----------------------------------------------------------------------------


def test_la_portada_publica_trae_el_precio_mensual_como_texto(client_por_peticion):
    planes = _publicos(client_por_peticion)

    assert planes["basico"]["precio_mensual_bs"] == "120.00"
    assert planes["profesional"]["precio_mensual_bs"] == "590.00"
    assert "id" not in planes["basico"] and "activo" not in planes["basico"]


def test_un_plan_sin_precio_sale_con_null(client_por_peticion, superadmin_headers):
    creado = client_por_peticion.post(
        f"{PLATAFORMA}/planes", json={"codigo": "sin-precio", "nombre": "Sin precio", "max_sucursales": 1},
        headers=superadmin_headers,
    )  # fmt: skip
    assert creado.status_code == 201, creado.text
    assert creado.json()["precio_mensual_bs"] is None

    assert _publicos(client_por_peticion)["sin-precio"]["precio_mensual_bs"] is None


def test_el_superadministrador_crea_un_plan_con_precio(client_por_peticion, superadmin_headers):
    creado = client_por_peticion.post(
        f"{PLATAFORMA}/planes",
        json={"codigo": "con-precio", "nombre": "Con precio", "max_sucursales": 3, "precio_mensual_bs": "199.5"},
        headers=superadmin_headers,
    )  # fmt: skip

    assert creado.status_code == 201, creado.text
    assert Decimal(creado.json()["precio_mensual_bs"]) == Decimal("199.50")
    assert _publicos(client_por_peticion)["con-precio"]["precio_mensual_bs"] == "199.50"


def test_el_superadministrador_edita_y_borra_el_precio(client_por_peticion, db_session, superadmin_headers):
    plan_id = _plan_id(db_session, "basico")

    editado = client_por_peticion.put(
        f"{PLATAFORMA}/planes/{plan_id}", json={"precio_mensual_bs": 150}, headers=superadmin_headers
    )
    assert editado.status_code == 200, editado.text
    assert Decimal(editado.json()["precio_mensual_bs"]) == Decimal("150")
    assert Decimal(_publicos(client_por_peticion)["basico"]["precio_mensual_bs"]) == Decimal("150")

    # Editar otro campo no toca el precio.
    otro = client_por_peticion.put(f"{PLATAFORMA}/planes/{plan_id}", json={"nombre": "Básico 2"}, headers=superadmin_headers)
    assert otro.status_code == 200, otro.text
    assert Decimal(otro.json()["precio_mensual_bs"]) == Decimal("150")

    # `null` explícito lo borra: el plan queda sin precio publicado.
    borrado = client_por_peticion.put(
        f"{PLATAFORMA}/planes/{plan_id}", json={"precio_mensual_bs": None}, headers=superadmin_headers
    )
    assert borrado.status_code == 200, borrado.text
    assert borrado.json()["precio_mensual_bs"] is None
    assert _publicos(client_por_peticion)["basico"]["precio_mensual_bs"] is None


@pytest.mark.parametrize("valor", [-1, "-0.01", "abc"])
def test_un_precio_negativo_o_invalido_se_rechaza(client_por_peticion, db_session, superadmin_headers, valor):
    plan_id = _plan_id(db_session, "basico")

    en_edicion = client_por_peticion.put(
        f"{PLATAFORMA}/planes/{plan_id}", json={"precio_mensual_bs": valor}, headers=superadmin_headers
    )
    en_alta = client_por_peticion.post(
        f"{PLATAFORMA}/planes",
        json={"codigo": "negativo", "nombre": "Negativo", "max_sucursales": 1, "precio_mensual_bs": valor},
        headers=superadmin_headers,
    )  # fmt: skip

    assert en_edicion.status_code == 422, en_edicion.text
    assert en_alta.status_code == 422, en_alta.text
    assert Decimal(_publicos(client_por_peticion)["basico"]["precio_mensual_bs"]) == Decimal("120")


def test_mas_de_dos_decimales_se_rechaza(client_por_peticion, db_session, superadmin_headers):
    respuesta = client_por_peticion.put(
        f"{PLATAFORMA}/planes/{_plan_id(db_session, 'basico')}",
        json={"precio_mensual_bs": "120.555"},
        headers=superadmin_headers,
    )

    assert respuesta.status_code == 422, respuesta.text


def test_la_base_rechaza_un_precio_negativo(db_session):
    with pytest.raises(IntegrityError) as error:
        with db_session.begin_nested():
            db_session.add(
                Plan(
                    codigo="roto", nombre="Roto", max_sucursales=1, reportes_convencionales=True, reportes_ia=False,
                    operacion_offline=False, analitica_ml=False, copias_seguridad=False, gestion_productos=True,
                    gestion_ventas=True, reservas=True, precio_mensual_bs=Decimal("-1"),
                )
            )  # fmt: skip
            db_session.flush()
    assert "ck_plan_precio_mensual" in str(error.value) or "CHECK" in str(error.value)


def test_un_plan_sin_precio_es_valido_en_la_base(db_session):
    plan = Plan(
        codigo="gratis-a-consultar", nombre="A consultar", max_sucursales=1, reportes_convencionales=True,
        reportes_ia=False, operacion_offline=False, analitica_ml=False, copias_seguridad=False,
        gestion_productos=True, gestion_ventas=True, reservas=True,
    )  # fmt: skip
    db_session.add(plan)
    db_session.flush()

    assert plan.precio_mensual_bs is None


# ---- Suscripción de prueba ---------------------------------------------------------------------------


def test_es_prueba_es_falso_por_defecto(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    suscripcion = db_session.scalar(sin_filtro(select(Suscripcion).where(Suscripcion.empresa_id == dos_empresas.a.id)))
    assert suscripcion.es_prueba is False

    mia = client_por_peticion.get(MI_SUSCRIPCION, headers=dos_empresas.a.headers)
    assert mia.status_code == 200, mia.text
    assert mia.json()["es_prueba"] is False

    lista = client_por_peticion.get(f"{PLATAFORMA}/suscripciones", headers=superadmin_headers)
    assert lista.status_code == 200, lista.text
    assert lista.json() and all(s["es_prueba"] is False for s in lista.json())


def test_una_suscripcion_de_prueba_se_informa_como_tal(client_por_peticion, db_session, dos_empresas, superadmin_headers):
    db_session.execute(
        sin_filtro(update(Suscripcion).where(Suscripcion.empresa_id == dos_empresas.b.id).values(es_prueba=True)),
        execution_options={"synchronize_session": False},
    )
    db_session.commit()

    mia = client_por_peticion.get(MI_SUSCRIPCION, headers=dos_empresas.b.headers)
    assert mia.status_code == 200, mia.text
    assert mia.json()["es_prueba"] is True
    # La otra empresa no se ve afectada.
    assert client_por_peticion.get(MI_SUSCRIPCION, headers=dos_empresas.a.headers).json()["es_prueba"] is False

    detalle = client_por_peticion.get(f"{PLATAFORMA}/suscripciones", params={"empresa_id": dos_empresas.b.id}, headers=superadmin_headers)
    assert detalle.status_code == 200, detalle.text
    assert [s["es_prueba"] for s in detalle.json()] == [True]
