"""Sugerencia de reposición por categoría (E12b, CU-24): `app.inteligencia.ml.reposicion`. Cálculo puro con
aritmética a mano: cada valor esperado se puede verificar con una calculadora."""

import json
import math
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from app.inteligencia.ml import reposicion
from app.inteligencia.ml.reposicion import ItemReposicion, calcular_reposicion

RAIZ = Path(__file__).resolve().parents[3]


def categoria(categoria_id: int, unidades: list, nombre: str | None = None) -> dict:
    return {"categoria_id": categoria_id, "categoria": nombre or f"Cat {categoria_id}", "unidades_semanales": unidades}


def uno(unidades: list, disponible: int, semanas: int = 4) -> ItemReposicion:
    """El único ítem de una categoría con esa demanda y ese disponible."""
    (item,) = calcular_reposicion([categoria(1, unidades)], {1: disponible}, semanas)
    return item


# ---- Cobertura y agotamiento -------------------------------------------------------------------


def test_cobertura_es_disponible_entre_la_demanda_semanal_promedio():
    item = uno([10, 20, 30, 40], disponible=75)  # promedio 25 -> 3 semanas
    assert item.demanda_semanal_promedio == 25.0
    assert item.semanas_cobertura == 3.0
    assert (item.categoria_id, item.categoria, item.disponible) == (1, "Cat 1", 75)
    # Un valor no entero se redondea a 2 decimales: 10 / 30 = 0,33
    assert uno([30], disponible=10, semanas=1).semanas_cobertura == 0.33


def test_agotado_en_semana_es_la_primera_con_demanda_acumulada_mayor_o_igual_al_disponible():
    demanda = [10, 20, 30, 40]  # acumulada: 10, 30, 60, 100
    assert uno(demanda, disponible=5).agotado_en_semana == 1
    assert uno(demanda, disponible=10).agotado_en_semana == 1  # igual cuenta
    assert uno(demanda, disponible=11).agotado_en_semana == 2
    assert uno(demanda, disponible=60).agotado_en_semana == 3
    assert uno(demanda, disponible=61).agotado_en_semana == 4
    assert uno(demanda, disponible=100).agotado_en_semana == 4
    assert uno(demanda, disponible=101).agotado_en_semana is None  # alcanza todo el horizonte previsto


# ---- Estados -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("disponible", "semanas", "cobertura", "estado"),
    [
        (19, 4, 1.9, "critico"),  # justo debajo de 2 semanas
        (20, 4, 2.0, "atencion"),  # exactamente 2 semanas ya NO es crítico
        (39, 4, 3.9, "atencion"),  # debajo de las semanas pedidas
        (40, 4, 4.0, "ok"),  # exactamente las semanas pedidas ya NO es atención
        (41, 4, 4.1, "ok"),
        (0, 4, 0.0, "critico"),
        (19, 1, 1.9, "critico"),  # el umbral crítico no depende del horizonte pedido
        (20, 2, 2.0, "ok"),  # con 2 semanas pedidas, 2.0 de cobertura es suficiente
    ],
)
def test_los_tres_estados_con_valores_limite(disponible, semanas, cobertura, estado):
    item = uno([10, 10, 10, 10], disponible, semanas)  # promedio 10 por semana
    assert item.semanas_cobertura == cobertura
    assert item.estado == estado


def test_los_umbrales_son_los_del_plan():
    assert reposicion.UMBRAL_CRITICO_SEMANAS == 2 and reposicion.COLCHON == 0.10
    assert (reposicion.MIN_SEMANAS, reposicion.MAX_SEMANAS) == (1, 12)


# ---- Sugerencia --------------------------------------------------------------------------------


def test_la_sugerencia_cubre_la_demanda_con_un_colchon_del_10_por_ciento_redondeado_hacia_arriba():
    assert uno([10, 10, 10, 10], disponible=0).sugerencia_unidades == 44  # 40 x 1,10
    assert uno([10, 10, 10, 10], disponible=10).sugerencia_unidades == 34
    # 33 x 1,10 = 36,3 -> 37 menos 5 disponibles = 32 (techo de 31,3, nunca hacia abajo).
    assert uno([11, 11, 11], disponible=5).sugerencia_unidades == 32
    # El ruido de punto flotante no suma una unidad: 100 x 1,10 = 110 exacto, no 111.
    assert uno([25, 25, 25, 25], disponible=0).sugerencia_unidades == 110
    assert uno([10, 10, 10, 10], disponible=0, semanas=2).sugerencia_unidades == 44  # no depende de `semanas`


def test_sin_necesidad_de_reponer_la_sugerencia_es_cero_nunca_negativa():
    assert uno([10, 10, 10, 10], disponible=44).sugerencia_unidades == 0  # justo el colchón
    assert uno([10, 10, 10, 10], disponible=45).sugerencia_unidades == 0
    assert uno([10, 10, 10, 10], disponible=1_000_000).sugerencia_unidades == 0


# ---- Sin demanda, sin existencias y extremos ---------------------------------------------------


def test_una_categoria_sin_demanda_prevista_tiene_cobertura_none_estado_ok_y_no_divide_por_cero():
    item = uno([0, 0, 0, 0], disponible=50)
    assert item.semanas_cobertura is None and item.estado == "ok"
    assert item.demanda_semanal_promedio == 0.0 and item.agotado_en_semana is None
    assert item.sugerencia_unidades == 0
    # Sin demanda y sin existencias tampoco es crítico: no hay nada que se venda.
    sin_nada = uno([0, 0], disponible=0)
    assert sin_nada.estado == "ok" and sin_nada.semanas_cobertura is None and sin_nada.agotado_en_semana is None
    # Una predicción vacía se trata igual, sin excepción.
    vacia = uno([], disponible=7)
    assert vacia.estado == "ok" and vacia.semanas_cobertura is None


def test_disponible_cero_con_demanda_es_critico_y_se_agota_en_la_semana_1():
    item = uno([0, 5, 5], disponible=0)  # aunque la semana 1 no tenga demanda: ya no hay nada que vender
    assert item.estado == "critico" and item.semanas_cobertura == 0.0
    assert item.agotado_en_semana == 1
    assert item.sugerencia_unidades == math.ceil(10 * 1.10)
    # Una categoría que el diccionario de disponibles no menciona cuenta como 0 existencias.
    (sin_dato,) = calcular_reposicion([categoria(3, [4, 4])], {}, 4)
    assert (sin_dato.disponible, sin_dato.estado, sin_dato.agotado_en_semana) == (0, "critico", 1)


def test_disponible_enorme_es_ok_sin_agotarse_y_sin_sugerencia():
    item = uno([10, 12, 14, 16], disponible=10**9, semanas=12)
    assert item.estado == "ok" and item.agotado_en_semana is None and item.sugerencia_unidades == 0
    assert item.semanas_cobertura == pytest.approx(10**9 / 13, abs=0.01)


# ---- Orden -------------------------------------------------------------------------------------


def test_orden_criticos_primero_luego_atencion_luego_ok_y_dentro_por_cobertura_ascendente():
    demanda = [
        categoria(1, [10, 10], "Ok bajo"),  # cobertura 10 -> ok
        categoria(2, [10, 10], "Atencion alta"),  # cobertura 3 -> atencion (semanas=4)
        categoria(3, [10, 10], "Critica alta"),  # cobertura 1.5 -> critico
        categoria(4, [0, 0], "Sin demanda"),  # cobertura None -> ok, al final
        categoria(5, [10, 10], "Critica baja"),  # cobertura 0.5 -> critico
        categoria(6, [10, 10], "Atencion baja"),  # cobertura 2.5 -> atencion
        categoria(7, [10, 10], "Ok alto"),  # cobertura 20 -> ok
    ]
    disponible = {1: 100, 2: 30, 3: 15, 4: 999, 5: 5, 6: 25, 7: 200}
    resultado = calcular_reposicion(demanda, disponible, 4)
    assert [i.categoria for i in resultado] == [
        "Critica baja", "Critica alta", "Atencion baja", "Atencion alta", "Ok bajo", "Ok alto", "Sin demanda",
    ]
    assert [i.estado for i in resultado] == ["critico"] * 2 + ["atencion"] * 2 + ["ok"] * 3
    # Con la misma cobertura el desempate es el id de la categoría, así el orden es estable.
    iguales = calcular_reposicion([categoria(9, [10]), categoria(2, [10])], {9: 5, 2: 5}, 4)
    assert [i.categoria_id for i in iguales] == [2, 9]
    assert calcular_reposicion([], {}, 4) == []


# ---- Entradas inválidas ------------------------------------------------------------------------


@pytest.mark.parametrize("semanas", [0, 13, -1, 4.0, "4", None, True])
def test_semanas_fuera_de_1_a_12_o_no_enteras_son_value_error(semanas):
    with pytest.raises(ValueError, match="1 a 12"):
        calcular_reposicion([categoria(1, [1])], {1: 1}, semanas)


@pytest.mark.parametrize(
    ("demanda", "disponible"),
    [
        ([categoria(1, [-1, 2])], {1: 5}),  # demanda negativa
        ([categoria(1, [float("nan")])], {1: 5}),
        ([categoria(1, [float("inf")])], {1: 5}),
        ([categoria(1, ["10"])], {1: 5}),
        ([categoria(1, [True])], {1: 5}),
        ([categoria(1, [3])], {1: -1}),  # disponible negativo
        ([categoria(1, [3])], {1: 2.5}),  # el disponible son unidades enteras
        ([{"categoria_id": 1, "categoria": "Sin unidades"}], {1: 1}),  # falta una clave
        ([categoria(1, None)], {1: 1}),
    ],
)
def test_entradas_invalidas_son_value_error_y_no_un_resultado_silencioso(demanda, disponible):
    with pytest.raises(ValueError):
        calcular_reposicion(demanda, disponible, 4)


# ---- Horizontes y forma del resultado ----------------------------------------------------------


def test_horizonte_de_una_y_de_doce_semanas():
    una = uno([7], disponible=7, semanas=1)  # 1 semana de demanda y justo 1 de cobertura
    assert una.semanas_cobertura == 1.0 and una.agotado_en_semana == 1
    assert una.estado == "critico"  # menos de 2 semanas aunque se pida solo 1
    assert una.sugerencia_unidades == math.ceil(7 * 1.10 - 7)  # 1

    doce = uno([10] * 12, disponible=120, semanas=12)  # 12 semanas de cobertura exactas
    assert doce.semanas_cobertura == 12.0 and doce.estado == "ok"
    assert doce.agotado_en_semana == 12  # la semana 12 acumula 120 = disponible
    assert doce.sugerencia_unidades == 12  # 132 - 120
    # Con 1 unidad menos se agota y falta atención; con 1 más no se agota en el horizonte.
    assert uno([10] * 12, 119, 12).estado == "atencion"
    assert uno([10] * 12, 121, 12).agotado_en_semana is None


def test_el_resultado_es_json_estricto_y_la_documentacion_de_supuestos_existe():
    items = calcular_reposicion(
        [categoria(1, [0, 0]), categoria(2, [5, 5]), categoria(3, [3, 9, 2])], {1: 10, 2: 3, 3: 0}, 6
    )
    json.dumps([asdict(i) for i in items], allow_nan=False)  # ni NaN ni infinito (la cobertura infinita es None)
    assert len(reposicion.SUPUESTOS) >= 4
    assert any("órdenes de compra" in s for s in reposicion.SUPUESTOS)


def test_el_modulo_no_importa_numpy_ni_scikit_learn():
    codigo = (
        "import sys; from app.inteligencia.ml import reposicion; "
        "print(sorted(m for m in ('numpy', 'sklearn', 'scipy', 'joblib') if m in sys.modules))"
    )
    salida = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(RAIZ), "DATABASE_URL": "sqlite:///:memory:", "JWT_SECRET_KEY": "clave-de-pruebas-larga"},
    )
    assert salida.returncode == 0, salida.stderr
    assert salida.stdout.strip() == "[]"
