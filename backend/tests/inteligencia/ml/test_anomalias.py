"""Detección de días inusuales por sucursal (E12b, CU-24): `app.inteligencia.ml.anomalias`. Cálculo puro: las pruebas
usan filas planas, sin base de datos. Las de control usan un generador propio con ruido de Poisson y semilla fija (las
anomalías se inyectan a mano, así que se sabe qué debe marcarse); la de aceptación usa el historial sintético de la E11.
"""

import datetime as dt
import json
import math
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from app.inteligencia.ml import anomalias, persistencia
from app.inteligencia.ml.anomalias import Anomalia, detectar_anomalias, entrenar_anomalias
from app.inteligencia.ml.sintetico import generar_historial
from tests.inteligencia.ml.test_sintetico import FIN, catalogo_de_prueba, config

RAIZ = Path(__file__).resolve().parents[3]
HASTA = dt.date(2026, 10, 25)  # domingo
# id -> (nombre, transacciones diarias base). Tres tamaños: con 60 a 150 transacciones diarias el ruido natural es
# chico frente a un pico del 200 % o un día sin ventas, que es lo que estas pruebas inyectan.
SUCURSALES = {1: ("Centro", 60.0), 2: ("Sur", 90.0), 3: ("Norte", 150.0)}
PESO_DIA = (0.9, 1.0, 1.0, 1.0, 1.3, 1.4, 0.7)  # lunes a domingo


def generar(n_dias: int = 300, hasta: dt.date = HASTA, semilla: int = 5, sucursales=SUCURSALES) -> list[dict]:
    """Una fila por (día, sucursal) con ventas: transacciones de Poisson, ticket entre 90 y 110."""
    rng = np.random.default_rng(semilla)
    filas = []
    for k in range(n_dias):
        dia = hasta - dt.timedelta(days=n_dias - 1 - k)
        for sucursal_id, (nombre, base) in sucursales.items():
            transacciones = int(rng.poisson(base * PESO_DIA[dia.weekday()]))
            if transacciones == 0:
                continue
            total = round(transacciones * float(rng.uniform(90.0, 110.0)), 2)
            filas.append(
                {
                    "dia": dia,
                    "sucursal_id": sucursal_id,
                    "sucursal": nombre,
                    "transacciones": transacciones,
                    "unidades": transacciones * 2,
                    "total_ventas": Decimal(str(total)),
                }
            )
    return filas


def escalar(filas: list[dict], dia: dt.date, sucursal_id: int, factor: float) -> list[dict]:
    """Copia de `filas` con las ventas de ese (día, sucursal) multiplicadas por `factor` (0 las quita)."""
    resultado = []
    for fila in filas:
        if fila["dia"] == dia and fila["sucursal_id"] == sucursal_id:
            if factor == 0:
                continue
            fila = {
                **fila,
                "transacciones": max(1, round(fila["transacciones"] * factor)),
                "total_ventas": (fila["total_ventas"] * Decimal(str(factor))).quantize(Decimal("0.01")),
            }
        resultado.append(fila)
    return resultado


def dias_atras(n: int) -> dt.date:
    return HASTA - dt.timedelta(days=n)


@pytest.fixture(scope="module")
def limpias() -> list[dict]:
    return generar()


@pytest.fixture(scope="module")
def modelo_limpio(limpias):
    resultado = entrenar_anomalias(limpias, HASTA)
    assert resultado.estado == "ok", resultado.motivo
    return resultado


def claves(lista: list[Anomalia]) -> set[tuple[dt.date, int]]:
    return {(a.fecha, a.sucursal_id) for a in lista}


# ---- Determinismo y forma del resultado --------------------------------------------------------


def test_misma_entrada_y_semilla_dan_el_mismo_artefacto_y_las_mismas_anomalias(limpias, modelo_limpio):
    otra = entrenar_anomalias(generar(), HASTA)
    huella_a = persistencia.serializar(modelo_limpio.artefacto)[1]
    huella_b = persistencia.serializar(otra.artefacto)[1]
    assert huella_a == huella_b
    assert otra.metricas == modelo_limpio.metricas
    assert detectar_anomalias(otra.artefacto, limpias, HASTA, 365) == detectar_anomalias(
        modelo_limpio.artefacto, limpias, HASTA, 365
    )
    # La semilla sí cuenta: otra semilla cambia el bosque y por tanto la huella.
    distinta = entrenar_anomalias(generar(), HASTA, semilla=7)
    assert persistencia.serializar(distinta.artefacto)[1] != huella_a


def test_resultado_ok_describe_los_datos_y_no_trae_nan(modelo_limpio):
    r = modelo_limpio
    assert (r.estado, r.motivo) == ("ok", None)
    assert r.datos_hasta == HASTA and r.datos_desde == HASTA - dt.timedelta(days=299)
    assert r.filas_entrenamiento == r.metricas["n_dias"] == 3 * 300
    assert r.metricas["n_sucursales"] == 3
    assert r.metricas["contamination"] == anomalias.CONTAMINACION
    assert set(r.metricas) >= {"n_dias", "n_sucursales", "n_marcados", "pct_marcados", "umbral", "contamination"}
    # JSON estricto: un NaN o un infinito en cualquiera de las salidas haría fallar esto.
    json.dumps(r.metricas, allow_nan=False)
    json.dumps(r.parametros, allow_nan=False)
    assert r.parametros["semilla"] == 42 and r.parametros["algoritmo"] == "IsolationForest"
    assert r.parametros["supuestos"] == anomalias.SUPUESTOS and len(anomalias.SUPUESTOS) >= 5
    assert set(r.artefacto["sucursales"]) == {1, 2, 3}  # las líneas base, por sucursal
    for linea in r.artefacto["sucursales"].values():
        assert len(linea["ventas"]["factor_dia"]) == 7 and len(linea["transacciones"]["factor_dia"]) == 7


def test_el_marcado_de_datos_limpios_es_pequeno_y_solo_incluye_desviaciones_reales(limpias, modelo_limpio):
    marcadas = detectar_anomalias(modelo_limpio.artefacto, limpias, HASTA, 365)[:]
    # La ventana de 365 días cubre todo el entrenamiento (300): lo marcado coincide con lo que dijo el entrenamiento.
    assert len(marcadas) == modelo_limpio.metricas["n_marcados"]
    assert modelo_limpio.metricas["pct_marcados"] <= 3.0
    # Con 60 a 150 transacciones diarias, un día marcado por casualidad se aparta bastante de lo esperado; uno que
    # casi no se aparta (menos de 15 %) sería un falso positivo del modelo.
    assert min(abs(a.desviacion_pct) for a in marcadas) >= 15.0
    for a in marcadas:
        assert math.isfinite(a.total_ventas) and math.isfinite(a.esperado) and math.isfinite(a.desviacion_pct)


# ---- Datos insuficientes -----------------------------------------------------------------------


def test_con_menos_de_ocho_semanas_hay_datos_insuficientes_sin_excepcion():
    corto = generar(n_dias=55)  # una semana menos que el mínimo (56 días)
    r = entrenar_anomalias(corto, HASTA)
    assert r.estado == "datos_insuficientes"
    assert r.artefacto is None and r.filas_entrenamiento == 0
    assert "semanas" in r.motivo
    json.dumps(r.metricas, allow_nan=False)
    # Exactamente 56 días ya alcanza: el límite es inclusivo.
    assert entrenar_anomalias(generar(n_dias=56), HASTA).estado == "ok"


def test_sin_filas_o_sin_ninguna_sucursal_apta_hay_datos_insuficientes():
    assert entrenar_anomalias([], HASTA).estado == "datos_insuficientes"
    # Hay 200 días de datos en total, pero la única sucursal abrió hace 20 y la otra cerró hace más de 28 días.
    nueva = generar(n_dias=20, sucursales={1: ("Nueva", 60.0)})
    cerrada = [f for f in generar(n_dias=200, sucursales={2: ("Cerrada", 60.0)}) if f["dia"] <= dias_atras(40)]
    r = entrenar_anomalias(nueva + cerrada, HASTA)
    assert r.estado == "datos_insuficientes"
    # El motivo de cada descarte queda en los avisos.
    assert any("Nueva" in a for a in r.avisos) and any("Cerrada" in a for a in r.avisos)


def test_una_sucursal_nueva_o_cerrada_se_omite_con_aviso_y_las_demas_se_evaluan(limpias):
    nueva = [{**f, "sucursal_id": 9, "sucursal": "Nueva"} for f in generar(n_dias=20, sucursales={1: ("x", 60.0)})]
    r = entrenar_anomalias(limpias + nueva, HASTA)
    assert r.estado == "ok" and set(r.artefacto["sucursales"]) == {1, 2, 3}
    assert any("Nueva" in aviso for aviso in r.avisos)


# ---- Qué se marca ------------------------------------------------------------------------------


def test_un_dia_sin_ventas_en_una_tienda_que_vende_todos_los_dias_es_anomalia(limpias, modelo_limpio):
    dia = dias_atras(20)
    con_hueco = escalar(limpias, dia, 3, 0)
    assert not any(f["dia"] == dia and f["sucursal_id"] == 3 for f in con_hueco)  # de verdad no hay fila
    entrenado = entrenar_anomalias(con_hueco, HASTA)
    por_fecha = {(a.fecha, a.sucursal_id): a for a in detectar_anomalias(entrenado.artefacto, con_hueco, HASTA, 90)}
    marca = por_fecha[(dia, 3)]
    assert marca.total_ventas == 0.0
    assert marca.desviacion_pct == -100.0 and marca.severidad == "fuerte"
    # Con el modelo ya entrenado con datos limpios también se ve (el hueco llega solo en las filas nuevas).
    nuevos = {(a.fecha, a.sucursal_id) for a in detectar_anomalias(modelo_limpio.artefacto, con_hueco, HASTA, 90)}
    assert (dia, 3) in nuevos


def test_un_pico_se_marca_y_lo_esperado_sale_de_las_lineas_base(limpias):
    dia = dias_atras(33)
    con_pico = escalar(limpias, dia, 2, 3.0)
    entrenado = entrenar_anomalias(con_pico, HASTA)
    por_fecha = {(a.fecha, a.sucursal_id): a for a in detectar_anomalias(entrenado.artefacto, con_pico, HASTA, 90)}
    marca = por_fecha[(dia, 2)]
    assert marca.severidad == "fuerte" and marca.desviacion_pct > 150.0
    assert marca.sucursal == "Sur"
    # Ese día de la semana la sucursal 2 vende en promedio 90 x PESO_DIA transacciones a ~100 cada una.
    assert marca.esperado == pytest.approx(SUCURSALES[2][1] * PESO_DIA[dia.weekday()] * 100.0, rel=0.15)
    # Coherencia interna: la desviación sale de total y esperado.
    assert marca.desviacion_pct == pytest.approx((marca.total_ventas - marca.esperado) / marca.esperado * 100.0, abs=0.1)


def test_un_dia_normal_no_se_marca_aunque_haya_anomalias_cerca(limpias):
    dia_raro = dias_atras(40)
    con_pico = escalar(limpias, dia_raro, 1, 3.0)
    entrenado = entrenar_anomalias(con_pico, HASTA)
    marcadas = claves(detectar_anomalias(entrenado.artefacto, con_pico, HASTA, 90))
    assert (dia_raro, 1) in marcadas  # el control: sí se marca lo raro
    # Los días vecinos de la misma tienda y el mismo día en las otras tiendas, que no se tocaron, no se marcan.
    for vecino in (dia_raro - dt.timedelta(days=1), dia_raro + dt.timedelta(days=1), dia_raro - dt.timedelta(days=7)):
        assert (vecino, 1) not in marcadas
    assert (dia_raro, 2) not in marcadas and (dia_raro, 3) not in marcadas


def test_la_regla_de_desviacion_marca_un_dia_extremo_aunque_el_bosque_no_lo_aisle(limpias):
    dia = dias_atras(12)
    con_pico = escalar(limpias, dia, 3, 3.0)
    artefacto = entrenar_anomalias(con_pico, HASTA).artefacto
    # Un umbral de aislamiento imposible de alcanzar apaga el criterio del bosque (ningún puntaje es tan bajo).
    sin_bosque = {**artefacto, "umbral": -1e9}
    marcadas = detectar_anomalias(sin_bosque, con_pico, HASTA, 30)
    assert (dia, 3) in claves(marcadas)  # solo la regla |z| >= Z_REGLA lo marca
    assert all(abs(a.desviacion_pct) >= 20.0 for a in marcadas)  # y la regla no marca días corrientes
    # Y si además la regla se vuelve imposible, no se marca nada: las dos mitades del "o" cuentan.
    assert detectar_anomalias({**sin_bosque, "z_regla": 1e9}, con_pico, HASTA, 30) == []


def test_el_ticket_se_mide_contra_el_esperado_y_sin_transacciones_no_aporta():
    ventas = np.array([300.0, 100.0, 50.0, 0.0])  # en "tickets": lo esperado es 100 con 100 transacciones
    transacciones = np.array([100.0, 100.0, 100.0, 0.0])
    z = anomalias._z_ticket_crudo(ventas, transacciones, np.full(4, 100.0), np.full(4, 100.0))
    assert z[1] == pytest.approx(0.0, abs=1e-9)  # ticket igual al esperado
    assert z[0] > 0 > z[2]  # ticket 3 veces mayor y la mitad
    assert z[0] == pytest.approx(math.log(3.0) * 10.0)  # log del cociente x raíz de las transacciones
    assert z[3] == 0.0  # sin transacciones no hay ticket que comparar (y no hay división por cero)


# ---- Severidad, ventana y orden ----------------------------------------------------------------


def test_severidad_por_desviacion_absoluta_con_el_limite_inclusivo():
    umbral = anomalias.UMBRAL_FUERTE_PCT
    assert anomalias._severidad(umbral) == "fuerte" and anomalias._severidad(-umbral) == "fuerte"
    assert anomalias._severidad(umbral - 0.1) == "leve" and anomalias._severidad(-(umbral - 0.1)) == "leve"
    assert anomalias._severidad(0.0) == "leve" and anomalias._severidad(250.0) == "fuerte"


def test_un_dia_con_desviacion_moderada_sale_leve_y_uno_extremo_fuerte(limpias):
    # La sucursal 3 vende ~150 transacciones: un +45 % ya es muy raro para ella, pero no llega a "fuerte" (60 %).
    moderado, extremo = dias_atras(25), dias_atras(50)
    datos = escalar(escalar(limpias, moderado, 3, 1.45), extremo, 3, 3.0)
    entrenado = entrenar_anomalias(datos, HASTA)
    por_fecha = {(a.fecha, a.sucursal_id): a for a in detectar_anomalias(entrenado.artefacto, datos, HASTA, 90)}
    assert por_fecha[(moderado, 3)].severidad == "leve"
    assert 30.0 < por_fecha[(moderado, 3)].desviacion_pct < anomalias.UMBRAL_FUERTE_PCT
    assert por_fecha[(extremo, 3)].severidad == "fuerte"


def test_dias_limita_la_ventana_y_valida_el_rango(limpias):
    reciente, antiguo = dias_atras(10), dias_atras(100)
    datos = escalar(escalar(limpias, reciente, 3, 3.0), antiguo, 3, 3.0)
    artefacto = entrenar_anomalias(datos, HASTA).artefacto
    en_30 = claves(detectar_anomalias(artefacto, datos, HASTA, 30))
    en_120 = claves(detectar_anomalias(artefacto, datos, HASTA, 120))
    assert (reciente, 3) in en_30 and (antiguo, 3) not in en_30
    assert {(reciente, 3), (antiguo, 3)} <= en_120
    assert all(fecha >= HASTA - dt.timedelta(days=29) for fecha, _ in en_30)
    assert en_30 <= en_120  # una ventana mayor nunca pierde lo que una menor ya veía
    # Los bordes de la ventana (inclusiva): `dias=11` llega hasta 10 días atrás; `dias=10`, solo hasta 9.
    assert (reciente, 3) in claves(detectar_anomalias(artefacto, datos, HASTA, 11))
    assert (reciente, 3) not in claves(detectar_anomalias(artefacto, datos, HASTA, 10))
    for invalido in (6, 366, 0, -5, True, 30.0):
        with pytest.raises(ValueError):
            detectar_anomalias(artefacto, datos, HASTA, invalido)
    for limite in (7, 365):  # los dos extremos válidos no fallan
        assert isinstance(detectar_anomalias(artefacto, datos, HASTA, limite), list)


def test_el_orden_es_fecha_descendente_y_dentro_de_una_fecha_las_fuertes_primero(limpias):
    dia, otro = dias_atras(30), dias_atras(45)
    datos = limpias
    for d, sucursal, factor in ((dia, 3, 1.45), (dia, 2, 3.0), (otro, 1, 3.0)):
        datos = escalar(datos, d, sucursal, factor)
    artefacto = entrenar_anomalias(datos, HASTA).artefacto
    lista = detectar_anomalias(artefacto, datos, HASTA, 90)
    del_dia = [a for a in lista if a.fecha == dia]
    assert [a.sucursal_id for a in del_dia][:2] == [2, 3]  # fuerte (x3) antes que leve (+45 %)
    assert [a.severidad for a in del_dia][:2] == ["fuerte", "leve"]
    fechas = [a.fecha for a in lista]
    assert fechas == sorted(fechas, reverse=True) and otro in fechas
    # Dentro de cada fecha ninguna "leve" precede a una "fuerte".
    for fecha in set(fechas):
        severidades = [a.severidad for a in lista if a.fecha == fecha]
        assert severidades == sorted(severidades, key={"fuerte": 0, "leve": 1}.get)


def test_sin_datos_o_sucursales_desconocidas_la_lista_es_vacia_y_nunca_hay_error(modelo_limpio):
    assert detectar_anomalias(modelo_limpio.artefacto, [], HASTA, 30) == []
    extranjeras = generar(n_dias=120, sucursales={77: ("Otra empresa", 60.0)})
    assert detectar_anomalias(modelo_limpio.artefacto, escalar(extranjeras, dias_atras(5), 77, 3.0), HASTA, 30) == []
    antiguas = generar(n_dias=100, hasta=HASTA - dt.timedelta(days=200))  # todo anterior a la ventana pedida
    assert detectar_anomalias(modelo_limpio.artefacto, antiguas, HASTA, 30) == []
    with pytest.raises(ValueError):
        detectar_anomalias({"modelo": None}, generar(n_dias=30), HASTA, 30)


# ---- Persistencia ------------------------------------------------------------------------------


def test_serializar_y_deserializar_conservan_el_resultado(limpias):
    dia = dias_atras(15)
    datos = escalar(limpias, dia, 3, 0.0)  # un día sin ventas, para que haya algo que detectar
    original = entrenar_anomalias(datos, HASTA).artefacto
    bytes_, huella, tamano = persistencia.serializar(original)
    assert tamano == len(bytes_) < 2 * 1024 * 1024
    recuperado = persistencia.deserializar(bytes_, huella)
    esperado = detectar_anomalias(original, datos, HASTA, 90)
    assert (dia, 3) in claves(esperado)
    assert detectar_anomalias(recuperado, datos, HASTA, 90) == esperado
    assert recuperado["umbral"] == original["umbral"] and recuperado["sucursales"] == original["sucursales"]
    assert persistencia.huella(bytes_) == huella


# ---- Aceptación con el historial sintético de la E11 -------------------------------------------


def _filas_por_sucursal(historial) -> list[dict]:
    """Lo que entrega `reporte_ventas_serie_diaria(desglose=("sucursal",))`: ventas efectivas por (día, sucursal)."""
    acumulado: dict[tuple[dt.date, int], list] = {}
    for venta in historial.ventas:
        if venta.estado not in ("pagada", "entregada"):
            continue
        celda = acumulado.setdefault((venta.fecha, venta.sucursal_id), [0, 0, Decimal("0")])
        celda[0] += 1
        for linea in venta.lineas:
            celda[1] += linea.cantidad
            celda[2] += linea.precio_unitario * linea.cantidad - linea.descuento
    return [
        {
            "dia": dia,
            "sucursal_id": sucursal_id,
            "sucursal": f"Sucursal {sucursal_id}",
            "transacciones": celda[0],
            "unidades": celda[1],
            "total_ventas": celda[2],
        }
        for (dia, sucursal_id), celda in sorted(acumulado.items())
    ]


@pytest.fixture(scope="module")
def evaluacion_sintetica():
    """Entrena sobre 78 semanas y 650 clientes en 6 combinaciones (perfil A y B x 3 empresas) y devuelve, por cada una, las
    anomalías inyectadas que cambian las ventas (cierre y liquidación), el total de días y los días marcados."""
    resultados = []
    catalogo = catalogo_de_prueba()
    for perfil in ("A", "B"):
        for empresa in ("fashionstore", "boutique-andina", "chaski-sport"):
            historial = generar_historial(catalogo, config(n_clientes=650, perfil=perfil, codigo_empresa=empresa))
            filas = _filas_por_sucursal(historial)
            entrenado = entrenar_anomalias(filas, FIN)
            assert entrenado.estado == "ok"
            # La ventana máxima es 365 días y el historial dura 546: el límite se amplía solo dentro de esta prueba.
            anomalias.DIAS_DETECCION_MAX, original = 800, anomalias.DIAS_DETECCION_MAX
            try:
                marcadas = detectar_anomalias(entrenado.artefacto, filas, FIN, 800)
            finally:
                anomalias.DIAS_DETECCION_MAX = original
            inyectadas = {a.tipo: (a.fecha, a.sucursal_id) for a in historial.anomalias}
            resultados.append((entrenado, marcadas, inyectadas))
    return resultados


def test_aceptacion_sintetico_la_liquidacion_se_detecta_siempre_con_pocos_falsos_positivos(evaluacion_sintetica):
    for entrenado, marcadas, inyectadas in evaluacion_sintetica:
        por_clave = {(a.fecha, a.sucursal_id): a for a in marcadas}
        liquidacion = por_clave[inyectadas["liquidacion"]]  # KeyError = no se detectó
        # La liquidación vende 3 veces lo habitual; contra un esperado que ya incluye el día fuerte, sale > +70 %.
        assert liquidacion.severidad == "fuerte" and liquidacion.desviacion_pct > 70.0
        assert len(marcadas) / entrenado.filas_entrenamiento <= 0.03
        assert len(marcadas) == entrenado.metricas["n_marcados"]


def test_aceptacion_sintetico_el_cierre_se_ve_en_una_parte_de_los_casos_y_siempre_como_caida(evaluacion_sintetica):
    """Un cierre (ventas al 30 % de lo habitual) en la sucursal grande (~10 transacciones al día) queda a solo ~2
    errores típicos de lo esperado: no se distingue de un mal día sin marcar muchos días normales. Aquí se documenta
    lo que SÍ se logra: se detecta en una parte de los casos (medido: 9 de 24 con las semillas 42, 7, 99 y 123, y 2 de 6
    con la de esta prueba) y, cuando se marca, es una caída. Este número no es una garantía de producto."""
    detectados = 0
    for _, marcadas, inyectadas in evaluacion_sintetica:
        por_clave = {(a.fecha, a.sucursal_id): a for a in marcadas}
        cierre = por_clave.get(inyectadas["cierre"])
        if cierre is not None:
            detectados += 1
            assert cierre.desviacion_pct < 0
    assert detectados >= 1


# ---- Importación diferida ----------------------------------------------------------------------

PESADOS = ("sklearn", "scipy", "joblib", "threadpoolctl")


def _cargados_tras(importar: str) -> list[str]:
    codigo = f"import sys; {importar}; print(sorted(m for m in {PESADOS!r} if m in sys.modules))"
    entorno = {**os.environ, "PYTHONPATH": str(RAIZ), "DATABASE_URL": "sqlite:///:memory:", "JWT_SECRET_KEY": "clave-de-pruebas-larga"}
    salida = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True, env=entorno)
    assert salida.returncode == 0, salida.stderr
    return eval(salida.stdout.strip())  # lista de nombres que imprimió el propio subproceso


def test_importar_anomalias_no_carga_scikit_learn_hasta_que_se_entrena():
    assert _cargados_tras("from app.inteligencia.ml import anomalias") == []
    cargados = _cargados_tras(
        "from datetime import date, timedelta; from app.inteligencia.ml import anomalias; "
        "h = date(2026, 10, 25); "
        "f = [{'dia': h - timedelta(days=i), 'sucursal_id': 1, 'sucursal': 'A', 'transacciones': 5 + i % 3, "
        "'unidades': 9, 'total_ventas': 500.0 + i % 7} for i in range(80)]; "
        "anomalias.entrenar_anomalias(f, h)"
    )
    assert "sklearn" in cargados  # prueba de que la comprobación anterior no es vacía
