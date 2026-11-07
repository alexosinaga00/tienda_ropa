"""La configuración falla cerrado ante lo peligroso (entorno "local" en un servidor, clave JWT corta) y avisa de lo dudoso; los
logs de la aplicación se encienden (RNF10) y los errores de base de datos no vuelcan valores."""

import logging

import pytest

from app.core.config import LARGO_MINIMO_CLAVE_JWT, LARGO_RECOMENDADO_CLAVE_JWT, Settings
from app.core.registro import configurar_logs, nivel_valido

CLAVE_LARGA = "k" * (LARGO_RECOMENDADO_CLAVE_JWT + 8)


def _ajustes(**cambios) -> Settings:
    base = {"database_url": "sqlite://", "jwt_secret_key": CLAVE_LARGA, "tareas_token": "token-de-servicio"}
    return Settings(_env_file=None, **{**base, **cambios})


@pytest.fixture(autouse=True)
def _sin_variables_de_railway(monkeypatch):
    for variable in ("RAILWAY_ENVIRONMENT_NAME", "RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID"):
        monkeypatch.delenv(variable, raising=False)


# ---- entorno ----


def test_en_una_maquina_local_el_entorno_local_es_valido():
    assert _ajustes(environment="local").environment == "local"


def test_el_entorno_se_normaliza_sin_espacios_ni_mayusculas():
    assert _ajustes(environment=" Production ").environment == "production"


def test_en_railway_el_entorno_local_no_arranca(monkeypatch):
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "proyecto-de-prueba")

    with pytest.raises(ValueError, match="ENVIRONMENT"):
        _ajustes(environment="local")


def test_en_railway_sin_ENVIRONMENT_tampoco_arranca(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")

    with pytest.raises(ValueError, match="ENVIRONMENT"):
        Settings(_env_file=None, database_url="sqlite://", jwt_secret_key=CLAVE_LARGA)  # el valor por defecto es "local"


def test_en_railway_con_production_arranca(monkeypatch):
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "proyecto-de-prueba")

    assert _ajustes(environment="production").environment == "production"


def test_el_mensaje_de_error_no_incluye_la_clave(monkeypatch):
    with pytest.raises(ValueError) as error:
        _ajustes(jwt_secret_key="corta")

    assert "corta" not in str(error.value).replace("JWT_SECRET_KEY es demasiado corta", "")


# ---- clave JWT ----


@pytest.mark.parametrize("clave", ["", "a", "k" * (LARGO_MINIMO_CLAVE_JWT - 1)])
def test_una_clave_jwt_demasiado_corta_no_arranca(clave):
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        _ajustes(jwt_secret_key=clave)


def test_una_clave_jwt_de_largo_minimo_arranca():
    assert _ajustes(jwt_secret_key="k" * LARGO_MINIMO_CLAVE_JWT).jwt_secret_key


# ---- avisos ----


def test_en_un_servidor_avisa_de_una_clave_corta_de_urls_a_localhost_y_de_tareas_sin_token(caplog):
    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        _ajustes(
            environment="production",
            jwt_secret_key="k" * (LARGO_RECOMENDADO_CLAVE_JWT - 1),
            tareas_token="",
        )

    texto = caplog.text
    assert "JWT_SECRET_KEY tiene menos de" in texto
    assert "FRONTEND_PUBLIC_URL apunta a localhost" in texto
    assert "BACKEND_PUBLIC_URL apunta a localhost" in texto
    assert "CORS_ORIGINS apunta a localhost" in texto
    assert "TAREAS_TOKEN está vacío" in texto
    assert "k" * 10 not in texto  # jamás imprime la clave


def test_una_configuracion_sana_de_produccion_no_avisa_de_nada(caplog):
    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        _ajustes(
            environment="production",
            frontend_public_url="https://tienda.example.com",
            backend_public_url="https://api.example.com",
            cors_origins="https://tienda.example.com",
        )

    assert caplog.text == ""


def test_en_local_no_avisa_de_localhost(caplog):
    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        _ajustes(environment="local", tareas_token="")

    assert caplog.text == ""


# ---- registro (logs) ----


@pytest.fixture()
def logger_app():
    registro = logging.getLogger("app")
    anterior = registro.level
    yield registro
    registro.setLevel(anterior)


def test_configurar_logs_enciende_los_mensajes_informativos_de_la_aplicacion(logger_app):
    configurar_logs("INFO")

    assert logging.getLogger("app.sincronizacion").isEnabledFor(logging.INFO)
    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)  # las librerías siguen calladas


def test_el_nivel_se_puede_subir_para_silenciar_lo_informativo(logger_app):
    configurar_logs("WARNING")

    assert not logging.getLogger("app.sincronizacion").isEnabledFor(logging.INFO)
    assert logging.getLogger("app.sincronizacion").isEnabledFor(logging.WARNING)


@pytest.mark.parametrize("texto, esperado", [("debug", "DEBUG"), (" Info ", "INFO"), ("ruidoso", "INFO"), ("", "INFO")])
def test_un_nivel_desconocido_vuelve_a_info(texto, esperado):
    assert nivel_valido(texto) == esperado


def test_configurar_logs_no_duplica_el_manejador(logger_app):
    raiz = logging.getLogger()
    antes = len(raiz.handlers)

    configurar_logs("INFO")
    configurar_logs("INFO")

    assert len(raiz.handlers) == antes  # las pruebas ya tienen manejador: no se agrega otro


def test_el_motor_de_base_de_datos_oculta_los_parametros_de_las_consultas():
    from app.core.database import engine

    assert engine.hide_parameters is True


def test_un_error_de_base_de_datos_no_vuelca_los_valores():
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, OperationalError

    from app.core.database import engine

    with pytest.raises((OperationalError, DBAPIError)) as error:
        with engine.connect() as conexion:
            conexion.execute(text("SELECT * FROM tabla_que_no_existe WHERE correo = :c"), {"c": "secreto@correo.com"})

    assert "secreto@correo.com" not in str(error.value)
