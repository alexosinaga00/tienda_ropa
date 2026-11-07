"""CU-24 (E11): entrenar los modelos de la empresa. Plan y suscripción, versiones, bitácora, candado y, sobre todo,
AISLAMIENTO: el entrenamiento de una empresa jamás usa datos de otra. SQLite en memoria; las pruebas con PostgreSQL
real están en tests/postgres/test_ml_postgres.py."""

import copy
import datetime as dt
import json

import pytest
from sqlalchemy import func, select

from app.catalogo.models import MovimientoInventario, Stock
from app.comercial import politicas as comercial_politicas
from app.comercial.models import Venta
from app.core.auditoria import ACCION_ENTRENAR, ENTIDAD_MODELO_ML, ContextoAuditoria
from app.core.deps import ParametrosPeriodo
from app.core.exceptions import DomainError, ErrorFuncional
from app.core.tenant import en_empresa
from app.inteligencia.casos_uso import cu24_analizar_con_machine_learning as cu24
from app.inteligencia.casos_uso.cu24_analizar_con_machine_learning import (
    CACHE_MODELOS,
    TIPO_ANOMALIAS,
    TIPO_DEMANDA,
    TIPO_SEGMENTOS,
    EntrenarModelosAnaliticos,
)
from app.inteligencia.ml import demanda, persistencia, sintetico
from app.inteligencia.ml.limites import ML_MAX_SEMANAS
from app.inteligencia.models import ModeloML
from app.inteligencia.repository import ModeloMLRepository
from app.plataforma.models import Bitacora, Suscripcion, Usuario
from tests.inteligencia.ml._escenario import FIN, cargar_historia, crear_vista_de_ventas, id_de, poblar
from tests.scripts._prendas_falsas import crear_carpeta

CU = EntrenarModelosAnaliticos()
REPO = ModeloMLRepository()


@pytest.fixture()
def mundo(db_session, tmp_path):
    """Tres organizaciones pobladas y la vista de ventas; el historial se carga en cada prueba según lo que necesite."""
    poblar(db_session, crear_carpeta(tmp_path))
    crear_vista_de_ventas(db_session)
    return db_session


def _entrenar(db, empresa_id, **kwargs):
    with en_empresa(db, empresa_id):
        return CU.ejecutar(db, None, hasta=FIN, **kwargs)


def _modelos(db, empresa_id):
    with en_empresa(db, empresa_id):
        return {(m.tipo, m.version): m for m in db.scalars(select(ModeloML))}


# ---- Lo básico -----------------------------------------------------------------------------------------------------------


def test_entrena_y_guarda_los_tres_tipos_con_su_version_y_su_huella(mundo):
    fs, *_ = cargar_historia(mundo, "fashionstore")
    resumen = _entrenar(mundo, fs)

    assert resumen.entrenados == [TIPO_DEMANDA, TIPO_SEGMENTOS, TIPO_ANOMALIAS]
    assert all(r.estado == "ok" and r.version == 1 and r.duracion_ms >= 0 for r in resumen.resultados)
    with en_empresa(mundo, fs):
        for tipo in (TIPO_DEMANDA, TIPO_SEGMENTOS, TIPO_ANOMALIAS):
            modelo = REPO.obtener_activo(mundo, tipo, con_artefacto=True)
            assert modelo.activo and modelo.version == 1 and modelo.empresa_id == fs
            assert modelo.artefacto_sha256 == persistencia.huella(modelo.artefacto) and modelo.artefacto_bytes == len(modelo.artefacto)
            assert modelo.filas_entrenamiento > 0 and modelo.datos_hasta <= FIN
            assert modelo.parametros["hasta"] == FIN.isoformat()
            # El artefacto lleva la empresa a la que pertenece (se comprueba al cargarlo, E12).
            assert persistencia.deserializar(modelo.artefacto, modelo.artefacto_sha256)["empresa_id"] == fs


def test_las_metricas_y_los_parametros_son_json_puro_sin_datos_personales(mundo):
    fs, *_ = cargar_historia(mundo, "fashionstore")
    _entrenar(mundo, fs)
    modelos = _modelos(mundo, fs)
    for modelo in modelos.values():
        texto = json.dumps([modelo.metricas, modelo.parametros], allow_nan=False)  # ningún NaN ni objeto raro
        assert "sintetico" not in texto and "@" not in texto  # ni correos ni nombres de clientes
    segmentos = modelos[(TIPO_SEGMENTOS, 1)].metricas["segmentos"]
    assert segmentos and all({"id", "nombre", "n_clientes", "monto_total"} <= set(s) for s in segmentos)
    assert "asignaciones" not in modelos[(TIPO_SEGMENTOS, 1)].metricas  # cliente -> segmento no se guarda
    assert modelos[(TIPO_DEMANDA, 1)].metricas["modelo_elegido"] in ("ridge", "mezcla", "random_forest")


def test_se_puede_entrenar_un_solo_tipo(mundo):
    fs, *_ = cargar_historia(mundo, "fashionstore")
    resumen = _entrenar(mundo, fs, tipos=[TIPO_SEGMENTOS])
    assert resumen.entrenados == [TIPO_SEGMENTOS]
    assert set(_modelos(mundo, fs)) == {(TIPO_SEGMENTOS, 1)}


def test_los_tipos_desconocidos_se_rechazan_antes_de_entrenar_y_aunque_vengan_con_uno_valido(mundo):
    fs, *_ = cargar_historia(mundo, "fashionstore")
    with pytest.raises(DomainError, match="desconocido"):
        _entrenar(mundo, fs, tipos=["bola_de_cristal"])
    with pytest.raises(DomainError, match="desconocido"):  # uno malo entre tipos buenos: no se entrena NINGUNO
        _entrenar(mundo, fs, tipos=[TIPO_DEMANDA, "bola_de_cristal"])
    assert _modelos(mundo, fs) == {}


def test_reentrenar_crea_la_version_2_y_la_1_queda_inactiva_con_su_artefacto(mundo):
    fs, *_ = cargar_historia(mundo, "fashionstore")
    primera, segunda = _entrenar(mundo, fs), _entrenar(mundo, fs)
    assert [r.version for r in primera.resultados] == [1] * 3 and [r.version for r in segunda.resultados] == [2] * 3
    modelos = _modelos(mundo, fs)
    assert (modelos[(TIPO_DEMANDA, 1)].activo, modelos[(TIPO_DEMANDA, 2)].activo) == (False, True)
    with en_empresa(mundo, fs):
        assert REPO.obtener_version(mundo, TIPO_DEMANDA, 1, con_artefacto=True).artefacto  # se conserva (hasta 3 versiones)
    # Mismos datos y misma semilla: las dos versiones son idénticas (el entrenamiento es reproducible).
    a, b = modelos[(TIPO_DEMANDA, 1)], modelos[(TIPO_DEMANDA, 2)]
    assert a.metricas == b.metricas and a.artefacto_sha256 == b.artefacto_sha256


def test_el_artefacto_guardado_y_cargado_de_la_base_predice_igual(mundo):
    fs, *_ = cargar_historia(mundo, "fashionstore")
    _entrenar(mundo, fs)
    with en_empresa(mundo, fs):
        modelo = REPO.obtener_activo(mundo, TIPO_DEMANDA, con_artefacto=True)
        artefacto = persistencia.deserializar(modelo.artefacto, modelo.artefacto_sha256)
        filas = comercial_politicas.reporte_ventas_serie_diaria(
            mundo, ParametrosPeriodo(FIN - dt.timedelta(weeks=ML_MAX_SEMANAS), FIN), desglose=("categoria",)
        )
    recalculado = demanda.entrenar_demanda(filas, FIN).artefacto
    assert demanda.predecir_demanda(artefacto, 6) == demanda.predecir_demanda(recalculado, 6)
    assert len(demanda.predecir_demanda(artefacto, 4)) == 4 * len(artefacto["categorias"])


def test_entrenar_invalida_el_cache_de_esa_empresa_y_tipo(mundo):
    fs, *_ = cargar_historia(mundo, "fashionstore")
    CACHE_MODELOS.poner(fs, TIPO_DEMANDA, 1, "viejo")
    CACHE_MODELOS.poner(fs, TIPO_SEGMENTOS, 1, "otro-tipo")
    CACHE_MODELOS.poner(99999, TIPO_DEMANDA, 1, "de-otra-empresa")
    _entrenar(mundo, fs, tipos=[TIPO_DEMANDA])
    assert CACHE_MODELOS.obtener(fs, TIPO_DEMANDA, 1) is None
    assert CACHE_MODELOS.obtener(fs, TIPO_SEGMENTOS, 1) == "otro-tipo"
    assert CACHE_MODELOS.obtener(99999, TIPO_DEMANDA, 1) == "de-otra-empresa"
    CACHE_MODELOS.invalidar(fs)
    CACHE_MODELOS.invalidar(99999)


def test_entrenar_no_toca_el_stock_ni_las_ventas(mundo):
    fs, *_ = cargar_historia(mundo, "fashionstore")

    def foto():
        with en_empresa(mundo, fs):
            return (
                mundo.scalar(select(func.count()).select_from(Venta)),
                mundo.scalar(select(func.sum(Stock.cantidad_fisica))),
                mundo.scalar(select(func.count()).select_from(MovimientoInventario)),
            )

    antes = foto()
    _entrenar(mundo, fs)
    assert foto() == antes


# ---- Plan y suscripción ---------------------------------------------------------------------------------------------------


def test_el_plan_basico_no_entrena_nada_y_no_guarda_nada(mundo):
    pampa, *_ = cargar_historia(mundo, "pampa-casual")
    with pytest.raises(ErrorFuncional) as error:
        _entrenar(mundo, pampa)
    assert (error.value.status_code, error.value.codigo) == (403, "plan_no_incluye_funcionalidad")
    assert error.value.contexto["funcionalidad"] == "analitica_ml"
    assert _modelos(mundo, pampa) == {}


def test_una_suscripcion_no_activa_no_entrena_nada(mundo):
    fs, *_ = cargar_historia(mundo, "fashionstore")
    with en_empresa(mundo, fs):
        mundo.scalar(select(Suscripcion)).estado = "suspendida"
        mundo.commit()
    with pytest.raises(ErrorFuncional) as error:
        _entrenar(mundo, fs)
    assert (error.value.status_code, error.value.codigo) == (403, "suscripcion_no_activa")
    assert _modelos(mundo, fs) == {}


# ---- Datos insuficientes: resultado estructurado, nunca un error -----------------------------------------------------------


def test_sin_ventas_devuelve_datos_insuficientes_y_no_guarda_ninguna_version(mundo):
    chaski = id_de(mundo, "chaski-sport")  # poblada, sin historial de ventas
    resumen = _entrenar(mundo, chaski)
    assert [r.estado for r in resumen.resultados] == ["datos_insuficientes"] * 3
    assert all(r.version is None and r.motivo for r in resumen.resultados)
    assert _modelos(mundo, chaski) == {}


def test_si_un_tipo_no_tiene_datos_el_otro_igual_se_entrena(mundo):
    # Pocos clientes: menos de 30 con compras => sin segmentos, pero la demanda por categoría sí tiene datos.
    fs, *_ = cargar_historia(mundo, "fashionstore", clientes=10)
    resumen = _entrenar(mundo, fs)
    por_tipo = {r.tipo: r for r in resumen.resultados}
    assert por_tipo[TIPO_DEMANDA].estado == "ok" and por_tipo[TIPO_SEGMENTOS].estado == "datos_insuficientes"
    # Solo se guarda lo que entrenó bien: el que no tuvo datos no deja ninguna versión (el de anomalías es independiente).
    assert set(_modelos(mundo, fs)) == {(r.tipo, 1) for r in resumen.resultados if r.estado == "ok"}
    assert (TIPO_SEGMENTOS, 1) not in _modelos(mundo, fs)


# ---- Aislamiento (D22) -------------------------------------------------------------------------------------------------------


def test_el_entrenamiento_de_una_empresa_usa_solo_sus_datos(mundo):
    fs, catalogo_fs, historial_fs, _ = cargar_historia(mundo, "fashionstore")
    ch, catalogo_ch, historial_ch, _ = cargar_historia(mundo, "chaski-sport", perfil="B")
    assert len(historial_fs.ventas) != len(historial_ch.ventas)  # historiales distintos

    _entrenar(mundo, fs)
    _entrenar(mundo, ch)
    modelos_fs, modelos_ch = _modelos(mundo, fs), _modelos(mundo, ch)

    # Lo calculado a mano con el historial de CADA empresa (sin pasar por la base): mismas semanas, mismas filas.
    esperado_fs = demanda.entrenar_demanda(sintetico.filas_serie_diaria(historial_fs, catalogo_fs), FIN)
    esperado_ch = demanda.entrenar_demanda(sintetico.filas_serie_diaria(historial_ch, catalogo_ch), FIN)
    assert modelos_fs[(TIPO_DEMANDA, 1)].filas_entrenamiento == esperado_fs.filas_entrenamiento
    assert modelos_ch[(TIPO_DEMANDA, 1)].filas_entrenamiento == esperado_ch.filas_entrenamiento
    # Los clientes que segmentó cada una son SOLO los suyos.
    clientes_fs = {f["cliente_id"] for f in sintetico.filas_rfm(historial_fs, FIN)}
    clientes_ch = {f["cliente_id"] for f in sintetico.filas_rfm(historial_ch, FIN)}
    assert modelos_fs[(TIPO_SEGMENTOS, 1)].metricas["n_clientes"] == len(clientes_fs)
    assert modelos_ch[(TIPO_SEGMENTOS, 1)].metricas["n_clientes"] == len(clientes_ch)
    # Y el modelo de una no es el de la otra.
    assert modelos_fs[(TIPO_DEMANDA, 1)].artefacto_sha256 != modelos_ch[(TIPO_DEMANDA, 1)].artefacto_sha256
    with en_empresa(mundo, fs):
        assert {m.empresa_id for m in mundo.scalars(select(ModeloML))} == {fs}


def test_inundar_de_datos_a_otra_empresa_no_cambia_las_metricas_de_la_primera(mundo):
    fs, *_ = cargar_historia(mundo, "fashionstore")
    _entrenar(mundo, fs)
    antes = _modelos(mundo, fs)[(TIPO_DEMANDA, 1)]
    metricas_antes, huella_antes = copy.deepcopy(antes.metricas), antes.artefacto_sha256
    segmentos_antes = copy.deepcopy(_modelos(mundo, fs)[(TIPO_SEGMENTOS, 1)].metricas)

    cargar_historia(mundo, "chaski-sport", semanas=40, clientes=400, perfil="B")  # un volumen masivo en OTRA empresa
    _entrenar(mundo, fs)

    despues = _modelos(mundo, fs)[(TIPO_DEMANDA, 2)]
    assert despues.metricas == metricas_antes and despues.artefacto_sha256 == huella_antes
    assert _modelos(mundo, fs)[(TIPO_SEGMENTOS, 2)].metricas == segmentos_antes


def test_con_el_contexto_de_otra_empresa_no_se_puede_leer_el_modelo_ni_su_artefacto(mundo):
    fs, *_ = cargar_historia(mundo, "fashionstore")
    ch = id_de(mundo, "chaski-sport")
    _entrenar(mundo, fs)
    with en_empresa(mundo, fs):
        id_de_fs = REPO.obtener_activo(mundo, TIPO_DEMANDA).id
    with en_empresa(mundo, ch):
        assert REPO.obtener_activo(mundo, TIPO_DEMANDA, con_artefacto=True) is None
        assert REPO.listar_versiones(mundo, TIPO_DEMANDA) == []
        assert mundo.get(ModeloML, id_de_fs) is None


# ---- Candado y bitácora ---------------------------------------------------------------------------------------------------------


def test_dos_entrenamientos_a_la_vez_el_segundo_falla_limpio_sin_guardar_nada(mundo, monkeypatch):
    fs, *_ = cargar_historia(mundo, "fashionstore")
    # SQLite no tiene el candado de PostgreSQL: se simula que otro entrenamiento lo tiene tomado.
    monkeypatch.setattr(EntrenarModelosAnaliticos, "_candado_ocupado", staticmethod(lambda db, empresa_id, tipo: True))
    with pytest.raises(ErrorFuncional) as error:
        _entrenar(mundo, fs)
    assert (error.value.status_code, error.value.codigo) == (409, "entrenamiento_en_curso")
    assert _modelos(mundo, fs) == {}


def test_el_candado_solo_actua_en_postgresql(mundo):
    assert EntrenarModelosAnaliticos._candado_ocupado(mundo, 1, TIPO_DEMANDA) is False  # SQLite: no hay nada que tomar


def test_el_entrenamiento_deja_una_fila_de_bitacora_por_modelo_sin_datos_personales(mundo):
    fs, *_ = cargar_historia(mundo, "fashionstore")
    with en_empresa(mundo, fs):
        admin = mundo.scalar(select(Usuario).where(Usuario.email == "admin@fashionstore.bo"))
        contexto = ContextoAuditoria(usuario_id=admin.id, empresa_id=fs, ip="10.0.0.9")
        CU.ejecutar(mundo, admin.id, contexto=contexto, hasta=FIN)
        modelos = {m.tipo: m for m in mundo.scalars(select(ModeloML))}
        assert all(m.entrenado_por == admin.id for m in modelos.values())
    filas = mundo.scalars(select(Bitacora).where(Bitacora.entidad == ENTIDAD_MODELO_ML, Bitacora.accion == ACCION_ENTRENAR)).all()
    assert {f.entidad_id for f in filas} == {m.id for m in modelos.values()}
    assert all(f.empresa_id == fs and f.usuario_id == admin.id and f.ip == "10.0.0.9" for f in filas)
    demanda_fila = next(f for f in filas if f.datos["tipo"] == TIPO_DEMANDA)
    assert {"version", "filas", "duracion_ms", "mae", "r2", "modelo_elegido"} <= set(demanda_fila.datos)
    assert "@" not in json.dumps([f.datos for f in filas])


def test_sin_contexto_no_se_registra_bitacora(mundo):
    fs, *_ = cargar_historia(mundo, "fashionstore")
    _entrenar(mundo, fs)
    assert mundo.scalar(select(func.count()).select_from(Bitacora).where(Bitacora.entidad == ENTIDAD_MODELO_ML)) == 0


def test_el_modulo_del_caso_de_uso_no_carga_numpy_ni_scikit_learn_al_importarse():
    import subprocess
    import sys
    from pathlib import Path

    codigo = (
        "import sys; import app.inteligencia.casos_uso.cu24_analizar_con_machine_learning; "
        "print([m for m in ('sklearn', 'scipy') if m in sys.modules])"
    )
    raiz = Path(cu24.__file__).resolve().parents[3]
    salida = subprocess.run(
        [sys.executable, "-c", codigo], cwd=raiz, capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(raiz), "DATABASE_URL": "sqlite:///:memory:", "JWT_SECRET_KEY": "clave-de-pruebas-larga"},
    )  # fmt: skip
    assert salida.returncode == 0, salida.stderr
    assert salida.stdout.strip() == "[]"
