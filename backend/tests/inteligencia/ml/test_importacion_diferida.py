"""El arranque de la aplicación no debe pagar el costo de scikit-learn (~1,3 s) ni el de scipy (~1 s): sus imports van
dentro de las funciones. numpy SÍ puede estar cargado al arrancar: `openpyxl` (los reportes en Excel, E10) lo importa
por su cuenta si lo encuentra instalado y cuesta ~0,1 s (ver la nota del PASO 1 de E11)."""

import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
PESADOS = ("sklearn", "scipy", "joblib", "threadpoolctl")


def _cargados_tras(importar: str) -> list[str]:
    codigo = f"import sys; {importar}; print(sorted(m for m in {PESADOS!r} if m in sys.modules))"
    entorno = {**os.environ, "PYTHONPATH": str(RAIZ), "DATABASE_URL": "sqlite:///:memory:", "JWT_SECRET_KEY": "clave-de-pruebas-larga"}
    salida = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True, env=entorno)
    assert salida.returncode == 0, salida.stderr
    return eval(salida.stdout.strip())  # una lista de nombres de módulos que imprimió el propio subproceso


def test_import_app_main_no_carga_scikit_learn_ni_scipy():
    assert _cargados_tras("import app.main") == []


def test_importar_los_modulos_de_ml_tampoco_los_carga_hasta_que_se_usan():
    modulos = "demanda, preprocesamiento, segmentos, sintetico, persistencia, limites"
    assert _cargados_tras(f"from app.inteligencia.ml import {modulos}") == []


def test_entrenar_si_los_carga_y_solo_en_ese_momento():
    cargados = _cargados_tras(
        "from tests.inteligencia.ml._datos_demanda import HASTA_BASE, generar_filas; "
        "from app.inteligencia.ml import demanda; "
        "demanda.entrenar_demanda(generar_filas(n_semanas=30, n_categorias=2), HASTA_BASE)"
    )
    assert "sklearn" in cargados  # prueba de que la comprobación de arriba no es vacía
