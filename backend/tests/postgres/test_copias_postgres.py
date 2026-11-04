"""E22 en PostgreSQL real (base `fashionstore_test`): la copia de seguridad es COMPLETA, RECUPERABLE y COHERENTE.

  P1  R1-R6 de `tests/plataforma/test_copias_restauracion.py` sobre PostgreSQL (restricciones reales, columna
      generada `stock.cantidad_disponible` recalculada, `categoria` autorreferenciada, jsonb, uuid, numeric). Las
      mismas funciones de prueba corren aquí con el mundo de PostgreSQL; solo R5 (PRAGMA de SQLite) se reemplaza.
  P2  5 POST simultáneos de la misma empresa: exactamente 1 devuelve el ZIP y 4 reciben 409 `copia_en_curso`;
      después otra copia funciona (el candado se liberó).
  P3  consistencia: una venta con su detalle entra MIENTRAS corre la copia; el ZIP no puede tener un detalle sin su
      venta ni una venta sin sus detalles (REPEATABLE READ), y la misma prueba con READ COMMITTED lo demuestra
      necesario.
  P4  esquema (modelos == migraciones), índice único parcial `ux_copia_en_proceso`, y la migración
      `a9d3f5c27e84` (permiso `copias.gestionar` para el administrador), subida y bajada.
  P5  medición de tamaño, tiempo y memoria con datos sintéticos grandes (se imprime; ver `-s`).

Como `test_aislamiento_pg.py`, el módulo comparte UN mundo (base limpia una vez, universos de A y B, restauración
en C): el orden importa. Primero lo que solo lee, al final lo que escribe en A. Al terminar deja la base vacía.
"""

import datetime as dt
import io
import json
import sys
import time
import tracemalloc
import zipfile
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core import copias
from app.core.database import Base, get_db
from app.core.tenant import fijar_empresa
from app.main import app
from scripts.seed_entregas import seed as seed_entregas
from scripts.seed_inventario import seed as seed_inventario
from scripts.seed_pagos import seed as seed_pagos
from scripts.seed_reservas import seed as seed_reservas
from scripts.seed_seguridad import seed as seed_seguridad
from scripts.seed_ventas import seed as seed_ventas
from tests.aislamiento.conftest import _dos_empresas
from tests.aislamiento.universo import crear, crear_universo
from tests.conftest import crear_empresa, token_de
from tests.plataforma import test_copias_restauracion as sqlite_r
from tests.restaurador_copia import (
    TABLAS_NO_RESTAURADAS,
    agregar_datos_extra,
    checksums_canonicos,
    conteos_por_tabla,
    huerfanas_de_empresa,
    inconsistencias_de_empresa,
    leer_paquete,
    reempaquetar,
    restaurar_copia,
)
from tests.postgres.conftest import ejecutar_alembic, sembrar_empresa_de_pruebas

from .paralelo import ejecutar_en_paralelo

API = "/api/v1/copias-seguridad"
MB = 1024 * 1024
RESTAURABLES = [t for t in copias.TABLAS_INCLUIDAS if t not in TABLAS_NO_RESTAURADAS]
REVISION_ANTERIOR = "f6c2a8d93b41"  # la migración a9d3f5c27e84 (copia_seguridad) cuelga de esta; bajar hasta aquí
# también deshace las posteriores (hoy c5e1b7a38d92, contratación de planes) y `upgrade head` las vuelve a aplicar.


# =================================================================================================
# Fixtures del módulo
# =================================================================================================


def _vaciar(engine_pg) -> None:
    with engine_pg.begin() as conexion:
        tablas = conexion.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'")
        ).scalars().all()
        conexion.execute(text("TRUNCATE TABLE " + ", ".join(f'"{t}"' for t in tablas) + " RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="module", autouse=True)
def base_limpia(engine_pg):
    """Sustituye, solo en este módulo, a la `base_limpia` de conftest (que vacía la base antes de CADA prueba):
    aquí se vacía y resiembra una vez y, al terminar, se vuelve a vaciar (nada de lo medido en P5 queda)."""
    fabrica = sessionmaker(bind=engine_pg, autoflush=False, autocommit=False)
    _vaciar(engine_pg)
    with fabrica() as db:
        empresa = sembrar_empresa_de_pruebas(db)
        fijar_empresa(db, empresa.id)
        db.commit()
        seed_seguridad(db)
        seed_inventario(db)
        seed_reservas(db)
        seed_ventas(db)
        seed_pagos(db)
        seed_entregas(db)
    yield
    _vaciar(engine_pg)


@pytest.fixture(scope="module")
def sesiones(engine_pg):
    return sessionmaker(bind=engine_pg, autoflush=False, autocommit=False)


def _copiar_pg(engine, empresa_id: int, codigo: str, aislamiento: str = "REPEATABLE READ") -> copias.ContenidoCopia:
    """Como el caso de uso: conexión dedicada con aislamiento REPEATABLE READ."""
    with engine.connect().execution_options(isolation_level=aislamiento) as conexion:
        return copias.generar_copia(
            conexion, empresa_id, empresa={"codigo": codigo, "nombre": codigo}, plan_codigo="profesional",
            version_esquema=copias.leer_version_esquema(conexion), max_bytes=50 * MB, max_segundos=120,
        )  # fmt: skip


@pytest.fixture(scope="module")
def _mundo_pg(engine_pg, sesiones, base_limpia):
    empresa_a, empresa_b = _dos_empresas(sesiones)

    def _db_por_peticion():
        sesion = sesiones()
        try:
            yield sesion
        except Exception:
            sesion.rollback()
            raise
        finally:
            sesion.close()

    app.dependency_overrides[get_db] = _db_por_peticion
    try:
        with TestClient(app) as client:
            a = crear_universo(client, sesiones, empresa_a, "A")
            extra = agregar_datos_extra(a)
            b = crear_universo(client, sesiones, empresa_b, "B")

            origen = _copiar_pg(engine_pg, a.id, "tienda-a")
            with sesiones() as db:
                destino_id = crear_empresa(db, "tienda-c", plan="profesional").id
            with sesiones() as db:
                resultado = restaurar_copia(origen.contenido, db, destino_id)
            restaurada = _copiar_pg(engine_pg, destino_id, "tienda-c")

            yield SimpleNamespace(
                engine=engine_pg, sesiones=sesiones, client=client, a=a, b=b, extra=extra, origen=origen,
                destino_id=destino_id, resultado=resultado, restaurada=restaurada, db_por_peticion=_db_por_peticion,
            )  # fmt: skip
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def mundo(_mundo_pg):
    app.dependency_overrides[get_db] = _mundo_pg.db_por_peticion
    return _mundo_pg


@pytest.fixture(autouse=True)
def _almacenamiento_falso(monkeypatch):
    from app.core import storage

    monkeypatch.setattr(storage, "subir_imagen", lambda contenido, carpeta, **_: f"{carpeta}/falso")
    monkeypatch.setattr(storage, "eliminar_imagen", lambda public_id: None)
    monkeypatch.setattr(storage, "url_catalogo", lambda public_id, ancho=None, alto=None: f"https://cdn.test/{public_id}")
    monkeypatch.setattr(storage, "url_probador", lambda public_id: f"https://cdn.test/{public_id}")


# =================================================================================================
# P1: R1-R6 en PostgreSQL
# =================================================================================================

# Las pruebas de SQLite se vuelven a correr tal cual con el mundo de PostgreSQL (mismas aserciones). Excepto las
# dos que usan PRAGMA foreign_key_check, que tienen su equivalente propio más abajo. Van en el orden en que se
# definen (R6 escribe en C: después de las de lectura).
_SOLO_SQLITE = {"test_r5_todas_las_llaves_foraneas_de_c_resuelven", "test_r5_el_foreign_key_check_detecta_una_fila_huerfana"}
_DELEGADAS = [nombre for nombre in vars(sqlite_r) if nombre.startswith("test_") and nombre not in _SOLO_SQLITE]


@pytest.mark.parametrize("nombre", _DELEGADAS)
def test_p1_en_postgresql(mundo, nombre):
    getattr(sqlite_r, nombre)(mundo)


def test_p1_r5_las_restricciones_de_la_base_estan_validadas_y_nada_queda_huerfano(mundo):
    with mundo.engine.connect() as conexion:
        sin_validar = conexion.execute(text("SELECT conname FROM pg_constraint WHERE NOT convalidated")).scalars().all()
        assert sin_validar == []
        assert huerfanas_de_empresa(conexion, mundo.destino_id) == []
        assert inconsistencias_de_empresa(conexion, mundo.destino_id) == []
        # La consulta de consistencia de E05, completa: ni A, ni B, ni C apuntan a otra empresa.
        from tests.aislamiento.test_zz_consistencia_final import contar_inconsistentes

        assert contar_inconsistentes(conexion) == []


def test_p1_columna_generada_y_tipos_de_postgresql(mundo):
    """`cantidad_disponible` no viajó en la copia y la base la recalculó; los jsonb, uuid, numeric y time de C
    son los mismos valores que los de A."""
    with mundo.engine.connect() as conexion:
        generada = conexion.execute(
            text("SELECT is_generated FROM information_schema.columns WHERE table_name='stock' AND column_name='cantidad_disponible'")
        ).scalar_one()
        tipos = dict(
            conexion.execute(
                text(
                    "SELECT table_name || '.' || column_name, data_type FROM information_schema.columns WHERE table_schema='public' AND "
                    "(table_name, column_name) IN (('bitacora','datos'),('operacion_sync','operacion_id'),('venta','total'),"
                    "('horario_sucursal','hora_apertura'),('categoria','categoria_padre_id'))"
                )
            ).all()
        )
    assert generada == "ALWAYS"
    assert tipos == {
        "bitacora.datos": "jsonb", "operacion_sync.operacion_id": "uuid", "venta.total": "numeric",
        "horario_sucursal.hora_apertura": "time without time zone", "categoria.categoria_padre_id": "integer",
    }  # fmt: skip
    assert "cantidad_disponible" not in mundo.origen.manifiesto["tablas"]["stock"]["columnas"]


def test_p1_un_fallo_de_la_base_a_mitad_de_la_carga_lo_deshace_todo(mundo):
    """Dos productos con el mismo código violan el UNIQUE de la base cuando ya se cargaron muchas tablas: el
    error real de PostgreSQL llega al llamador y la empresa destino queda sin una sola fila."""
    destino = sqlite_r._empresa_vacia(mundo, "tienda-unique")

    def duplicar(filas):
        filas = [dict(f) for f in filas]
        filas[1]["codigo"] = filas[0]["codigo"]
        return filas

    mal = reempaquetar(mundo.origen.contenido, {"datos/producto.json": duplicar})
    with mundo.sesiones() as db, pytest.raises(IntegrityError):
        restaurar_copia(mal, db, destino)
    assert sum(sqlite_r._conteos(mundo, destino).values()) == 0
    with mundo.sesiones() as db:  # y el mismo destino admite después una restauración buena
        restaurar_copia(mundo.origen.contenido, db, destino)
    assert sqlite_r._conteos(mundo, destino) == {t: mundo.origen.manifiesto["tablas"][t]["filas"] for t in RESTAURABLES}


def test_p1_la_version_del_esquema_queda_en_el_manifiesto(mundo):
    with mundo.engine.connect() as conexion:
        version = conexion.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert mundo.origen.manifiesto["version_esquema"] == version
    assert mundo.restaurada.manifiesto["version_esquema"] == version


# =================================================================================================
# P2: cinco copias simultáneas de la misma empresa
# =================================================================================================


@contextmanager
def _sesiones_con_zona(url_pg, zona: str | None):
    """Sesiones para las peticiones. `zona` = 'UTC' fija el huso horario de TODAS las conexiones de la prueba (como
    una base alojada en UTC, p. ej. Railway); None deja el de la base de pruebas tal cual está configurada."""
    argumentos = {"options": f"-c timezone={zona}"} if zona else {}
    motor = create_engine(url_pg, connect_args=argumentos, pool_pre_ping=True)
    fabrica = sessionmaker(bind=motor, autoflush=False, autocommit=False)

    def _db():
        sesion = fabrica()
        try:
            yield sesion
        except Exception:
            sesion.rollback()
            raise
        finally:
            sesion.close()

    anterior = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _db
    try:
        yield fabrica
    finally:
        app.dependency_overrides[get_db] = anterior
        motor.dispose()


def _huso_del_servidor(engine) -> str:
    with engine.connect() as conexion:
        return conexion.execute(text("SHOW timezone")).scalar_one()


def _ultima_copia(engine) -> int:
    """Id de la última fila de `copia_seguridad` (el universo de pruebas ya deja una copia de ejemplo en A)."""
    with engine.connect() as conexion:
        return conexion.execute(text("SELECT coalesce(max(id), 0) FROM copia_seguridad")).scalar_one()


def _cinco_post_simultaneos(mundo, monkeypatch, fabrica) -> list:
    """La copia real de esta base dura milisegundos y la primera terminaría antes de que arranque la última; para
    que se SOLAPEN se hace lenta (2 s) con un doble de `generar_copia` que espera y delega en la verdadera."""
    real = copias.generar_copia

    def lenta(*args, **kwargs):
        time.sleep(2.0)
        return real(*args, **kwargs)

    monkeypatch.setattr(copias, "generar_copia", lenta)
    cabeceras = mundo.a.admin

    def pedir(_db):
        return TestClient(app).post(API, headers=cabeceras)  # un cliente por hilo; la barrera las suelta juntas

    resultados = ejecutar_en_paralelo(fabrica, [pedir] * 5)
    assert all(r.ok for r in resultados), [r.error for r in resultados if not r.ok]
    return [r.valor for r in resultados]


def _comprobar_un_solo_zip(mundo, respuestas, ultima_copia_previa: int) -> None:
    estados = sorted(r.status_code for r in respuestas)
    assert estados == [200, 409, 409, 409, 409], estados

    exitosa = next(r for r in respuestas if r.status_code == 200)
    assert exitosa.headers["content-type"] == "application/zip"
    assert zipfile.ZipFile(io.BytesIO(exitosa.content)).testzip() is None
    for rechazada in (r for r in respuestas if r.status_code == 409):
        assert rechazada.json()["codigo"] == "copia_en_curso"

    with mundo.engine.connect() as conexion:
        filas = conexion.execute(
            text("SELECT estado, count(*) FROM copia_seguridad WHERE empresa_id = :e AND id > :previa GROUP BY estado"), {"e": mundo.a.id, "previa": ultima_copia_previa}
        ).all()
        detalle = conexion.execute(text("SELECT id, estado, motivo_fallo, creado_en, terminado_en FROM copia_seguridad WHERE id > :previa ORDER BY id"), {"previa": ultima_copia_previa}).all()
    assert dict(filas) == {"completada": 1}, detalle  # ninguna quedó en_proceso ni fallida

    # El candado se liberó: una sexta copia funciona.
    sexta = TestClient(app).post(API, headers=mundo.a.admin)
    assert sexta.status_code == 200, sexta.text
    assert zipfile.ZipFile(io.BytesIO(sexta.content)).testzip() is None


def test_p2_cinco_post_simultaneos_solo_uno_entrega_el_zip(mundo, url_pg, monkeypatch):
    """Con la base en UTC (como en Railway): exactamente 1 respuesta 200 con el ZIP y 4 respuestas 409
    `copia_en_curso`; después, una sexta copia funciona."""
    with _sesiones_con_zona(url_pg, "UTC") as fabrica:
        previa = _ultima_copia(mundo.engine)
        respuestas = _cinco_post_simultaneos(mundo, monkeypatch, fabrica)
        _comprobar_un_solo_zip(mundo, respuestas, previa)


def test_p2_cinco_post_simultaneos_con_el_huso_de_la_base_tal_cual(mundo, url_pg, monkeypatch):
    """La MISMA prueba, con la base de pruebas tal como está configurada (aquí America/La_Paz, UTC-4). Detectó un
    defecto: `creado_en` salía de `now()` de la base (hora local) y se comparaba con UTC, de modo que una copia
    recién creada parecía abandonada y el candado se rompía. Ahora la hora la fija Python en UTC."""
    with _sesiones_con_zona(url_pg, None) as fabrica:
        previa = _ultima_copia(mundo.engine)
        respuestas = _cinco_post_simultaneos(mundo, monkeypatch, fabrica)
        _comprobar_un_solo_zip(mundo, respuestas, previa)


def test_p2_una_copia_recien_creada_no_debe_parecer_abandonada(mundo, engine_pg):
    """Determinista y sin hilos: se inserta la fila candado con `crear_en_proceso` y se
    llama a `marcar_abandonadas` con el umbral que calcula el caso de uso (UTC menos 2 x copias_max_segundos).
    Una copia de hace 0 segundos NO puede salir 'abandonada'."""
    from app.core.config import get_settings
    from app.plataforma.casos_uso.cu04_gestionar_empresas_planes_suscripciones import FACTOR_ABANDONO
    from app.plataforma.repository import CopiaSeguridadRepository

    umbral = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(seconds=FACTOR_ABANDONO * get_settings().copias_max_segundos)
    with mundo.sesiones() as db:
        fijar_empresa(db, mundo.b.id)
        repo = CopiaSeguridadRepository()
        fila = repo.crear_en_proceso(db, mundo.b.empresa.admin_id)
        db.commit()
        try:
            marcadas = repo.marcar_abandonadas(db, umbral)
            db.rollback()
            assert marcadas == 0, f"huso de la base: {_huso_del_servidor(engine_pg)}; creado_en={fila.creado_en}, umbral={umbral}"
        finally:
            db.rollback()
            db.execute(text("UPDATE copia_seguridad SET estado = 'fallida', motivo_fallo = 'prueba' WHERE id = :i"), {"i": fila.id})
            db.commit()

def _cabeceras_de_c(mundo) -> dict:
    """El administrador de A restaurado en C (sin contraseña): su token se firma a mano."""
    from app.plataforma.models import Usuario

    admin_c = mundo.resultado.equivalencias["usuario"][mundo.a.empresa.admin_id]
    with mundo.sesiones() as db:
        fijar_empresa(db, mundo.destino_id)
        return token_de(db, db.get(Usuario, admin_c))


def test_p2_dos_empresas_pueden_copiar_a_la_vez(mundo, monkeypatch):
    """El candado es POR empresa: A y B copian a la vez sin molestarse."""
    real = copias.generar_copia

    def lenta(*args, **kwargs):
        time.sleep(1.0)
        return real(*args, **kwargs)

    monkeypatch.setattr(copias, "generar_copia", lenta)
    resultados = ejecutar_en_paralelo(
        mundo.sesiones,
        [lambda _db: TestClient(app).post(API, headers=mundo.a.admin), lambda _db: TestClient(app).post(API, headers=_cabeceras_de_c(mundo))],
    )
    assert [r.valor.status_code for r in resultados] == [200, 200]
    codigos = [json.loads(zipfile.ZipFile(io.BytesIO(r.valor.content)).read("manifest.json"))["empresa"]["codigo"] for r in resultados]
    assert codigos == ["tienda-a", "tienda-c"]


# =================================================================================================
# P3: la copia es coherente aunque entre una venta a mitad
# =================================================================================================


def _venta_presencial(mundo):
    return crear(
        mundo.client, "/ventas/presencial",
        {"sucursal_id": mundo.a.ids["sucursal"], "cliente_id": mundo.a.cliente.id, "detalle": [{"variante_id": mundo.a.ids["variante"], "cantidad": 1}]},
        mundo.a.admin,
    )  # fmt: skip


def _con_venta_a_mitad(mundo, monkeypatch, aislamiento: str):
    """Corre la copia de A y, justo después de escribir `venta` y antes de `venta_detalle`, registra otra venta (con
    su detalle) desde otra sesión. Devuelve (la copia, la venta insertada)."""
    original = copias._escribir_tabla
    insertada: dict = {}

    def con_gancho(zf, carpeta, nombre, empresa_id, conexion, comprobar_topes):
        resultado = original(zf, carpeta, nombre, empresa_id, conexion, comprobar_topes)
        if carpeta == "datos" and nombre == "venta" and not insertada:
            insertada.update(_venta_presencial(mundo))
        return resultado

    monkeypatch.setattr(copias, "_escribir_tabla", con_gancho)
    try:
        copia = _copiar_pg(mundo.engine, mundo.a.id, "tienda-a", aislamiento)
    finally:
        monkeypatch.setattr(copias, "_escribir_tabla", original)
    assert insertada, "el gancho no llegó a insertar la venta"
    return copia, insertada


def _ventas_y_detalles(copia: copias.ContenidoCopia):
    paquete = leer_paquete(copia.contenido)
    ventas = {f["id"] for f in paquete.datos["venta"]}
    detalles = paquete.datos["venta_detalle"]
    return ventas, detalles


def test_p3_una_venta_que_entra_durante_la_copia_no_deja_huecos(mundo, monkeypatch):
    antes = leer_paquete(mundo.origen.contenido).datos["venta"]
    copia, nueva = _con_venta_a_mitad(mundo, monkeypatch, "REPEATABLE READ")
    ventas, detalles = _ventas_y_detalles(copia)
    assert len(ventas) == len(antes)  # la instantánea es la del inicio: la venta nueva no está
    assert nueva["id"] not in ventas
    assert {d["venta_id"] for d in detalles} <= ventas, "hay un detalle sin su venta"
    assert ventas <= {d["venta_id"] for d in detalles}, "hay una venta sin sus detalles"
    # Y la copia siguiente sí la trae, completa.
    despues, detalles_despues = _ventas_y_detalles(_copiar_pg(mundo.engine, mundo.a.id, "tienda-a"))
    assert nueva["id"] in despues and any(d["venta_id"] == nueva["id"] for d in detalles_despues)


def test_p3_control_sin_repeatable_read_la_copia_saldria_incoherente(mundo, monkeypatch):
    """Control de la propia prueba: con READ COMMITTED el mismo gancho SÍ deja un detalle sin su venta. Es lo
    que evita el aislamiento REPEATABLE READ de `_conexion_de_lectura`."""
    copia, nueva = _con_venta_a_mitad(mundo, monkeypatch, "READ COMMITTED")
    ventas, detalles = _ventas_y_detalles(copia)
    huerfanos = [d for d in detalles if d["venta_id"] not in ventas]
    assert nueva["id"] not in ventas
    assert [d["venta_id"] for d in huerfanos] == [nueva["id"]]


# =================================================================================================
# P4: esquema y migración
# =================================================================================================


def test_p4_las_migraciones_dejan_el_esquema_igual_a_los_modelos(engine_pg):
    from tests.postgres.test_esquema_postgres import test_las_migraciones_dejan_el_esquema_igual_a_los_modelos

    test_las_migraciones_dejan_el_esquema_igual_a_los_modelos(engine_pg)


def test_p4_el_indice_del_candado_es_unico_y_parcial(engine_pg):
    indices = {i["name"]: i for i in inspect(engine_pg).get_indexes("copia_seguridad")}
    assert indices["ux_copia_en_proceso"]["unique"]
    assert indices["ux_copia_en_proceso"]["column_names"] == ["empresa_id"]
    assert "en_proceso" in indices["ux_copia_en_proceso"]["dialect_options"]["postgresql_where"]


def test_p4_la_base_rechaza_dos_copias_en_proceso_de_una_empresa(engine_pg, mundo):
    with engine_pg.connect() as conexion:
        admin = mundo.a.empresa.admin_id
        insertar = text("INSERT INTO copia_seguridad (empresa_id, usuario_id, estado) VALUES (:e, :u, :s)")
        conexion.execute(insertar, {"e": mundo.a.id, "u": admin, "s": "en_proceso"})
        conexion.execute(insertar, {"e": mundo.b.id, "u": mundo.b.empresa.admin_id, "s": "en_proceso"})  # otra empresa: sí
        conexion.execute(insertar, {"e": mundo.a.id, "u": admin, "s": "completada"})  # no en proceso: sí
        with pytest.raises(IntegrityError):
            conexion.execute(insertar, {"e": mundo.a.id, "u": admin, "s": "en_proceso"})
        conexion.rollback()


def _permisos_de_copias(engine) -> tuple[list[str], list[str]]:
    with engine.connect() as conexion:
        permiso = conexion.execute(text("SELECT codigo FROM permiso WHERE codigo = 'copias.gestionar'")).scalars().all()
        roles = conexion.execute(
            text(
                "SELECT r.nombre FROM rol_permiso rp JOIN rol r ON r.id = rp.rol_id JOIN permiso p ON p.id = rp.permiso_id "
                "WHERE p.codigo = 'copias.gestionar' ORDER BY r.nombre"
            )
        ).scalars().all()
    return permiso, roles


def test_p4_la_migracion_a9d3f5c27e84_crea_el_permiso_y_se_puede_bajar_y_subir(engine_pg, url_pg, mundo):
    """Baja la migración (que borra la tabla y el permiso), comprueba que se fue, la sube otra vez y comprueba que
    creó la tabla, el índice, el permiso `copias.gestionar` y su asignación SOLO al administrador. Siempre
    termina en `head`. Solo sobre la base `_test` (la comprueba `ejecutar_alembic`)."""
    assert _permisos_de_copias(engine_pg) == (["copias.gestionar"], ["administrador"])  # estado de partida (seeds)
    engine_pg.dispose()  # sin conexiones abiertas durante el DDL
    try:
        bajada = ejecutar_alembic(url_pg, "downgrade", REVISION_ANTERIOR)
        assert bajada.returncode == 0, f"downgrade falló:\n{bajada.stdout}\n{bajada.stderr}"
        assert "copia_seguridad" not in inspect(engine_pg).get_table_names()
        assert _permisos_de_copias(engine_pg) == ([], [])
    finally:
        subida = ejecutar_alembic(url_pg, "upgrade", "head")
        engine_pg.dispose()
    assert subida.returncode == 0, f"upgrade falló:\n{subida.stdout}\n{subida.stderr}"
    assert "copia_seguridad" in inspect(engine_pg).get_table_names()
    indices = {i["name"]: i for i in inspect(engine_pg).get_indexes("copia_seguridad")}
    assert indices["ux_copia_en_proceso"]["unique"]
    assert _permisos_de_copias(engine_pg) == (["copias.gestionar"], ["administrador"])
    from tests.postgres.test_esquema_postgres import test_las_migraciones_dejan_el_esquema_igual_a_los_modelos

    test_las_migraciones_dejan_el_esquema_igual_a_los_modelos(engine_pg)  # y el esquema vuelve a ser el de los modelos


# =================================================================================================
# P5: medición con datos grandes (no es una prueba de contrato: imprime y comprueba contra los topes de hoy)
# =================================================================================================


def _pico_del_proceso_mb() -> float | None:
    """Pico de memoria residente del PROCESO entero (incluye el generador sintético, no solo la copia)."""
    if sys.platform != "win32":
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    import ctypes
    from ctypes import wintypes

    class Contadores(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]  # fmt: skip

    contadores = Contadores()
    contadores.cb = ctypes.sizeof(contadores)
    kernel32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Contadores), wintypes.DWORD]
    psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(contadores), contadores.cb)
    return contadores.PeakWorkingSetSize / MB


@pytest.mark.parametrize(
    ("quien", "clientes", "semanas"),
    [("b", 650, 78), ("a", 2000, 104)],
    ids=["historial-por-defecto-650-clientes-78-semanas", "historial-triple-2000-clientes-104-semanas"],
)
def test_p5_medicion_de_tamano_tiempo_y_memoria(mundo, quien, clientes, semanas):
    from scripts.seed_ml_sintetico import cargar_historial, generar

    universo = mundo.b if quien == "b" else mundo.a
    fin = dt.date.today() - dt.timedelta(days=1)
    inicio_carga = time.perf_counter()
    with mundo.sesiones() as db:
        fijar_empresa(db, universo.id)
        catalogo, historial = generar(db, universo.codigo, semanas=semanas, clientes=clientes, perfil="A", semilla=42, fin=fin)
        resumen = cargar_historial(db, historial, catalogo, universo.codigo)
    carga_s = time.perf_counter() - inicio_carga
    assert not resumen.ya_existia and resumen.ventas > 1000

    # Tiempo (sin tracemalloc, que frena todo) y tamaño.
    tiempos = []
    for _ in range(3):
        inicio = time.perf_counter()
        copia = _copiar_pg(mundo.engine, universo.id, universo.codigo)
        tiempos.append(time.perf_counter() - inicio)
    filas = sum(copia.tablas.values())
    tamano_sin_comprimir = sum(
        zipfile.ZipFile(io.BytesIO(copia.contenido)).getinfo(n).file_size for n in zipfile.ZipFile(io.BytesIO(copia.contenido)).namelist()
    )

    # Memoria: lo que Python reserva durante UNA copia (el ZIP vive en RAM) y el pico del proceso.
    tracemalloc.start()
    _copiar_pg(mundo.engine, universo.id, universo.codigo)
    _actual, pico = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    mayores = sorted(copia.tablas.items(), key=lambda par: -par[1])[:5]
    print(
        f"\n[P5 {quien.upper()} clientes={clientes} semanas={semanas}] ventas={resumen.ventas} lineas={resumen.lineas} "
        f"carga_sintetica={carga_s:.1f}s\n"
        f"  filas totales={filas} | ZIP={len(copia.contenido) / MB:.2f} MiB ({len(copia.contenido)} B) | "
        f"sin comprimir={tamano_sin_comprimir / MB:.2f} MiB | razon={tamano_sin_comprimir / len(copia.contenido):.1f}x | "
        f"{len(copia.contenido) / filas:.0f} B comprimidos por fila\n"
        f"  tiempo generar_copia: {', '.join(f'{t:.2f}s' for t in tiempos)} | "
        f"pico tracemalloc={pico / MB:.1f} MiB | pico del proceso (incluye el seed)={_pico_del_proceso_mb():.0f} MiB\n"
        f"  tablas mayores: {mayores}"
    )
    assert len(copia.contenido) < 25 * MB and min(tiempos) < 60
    assert zipfile.ZipFile(io.BytesIO(copia.contenido)).testzip() is None





