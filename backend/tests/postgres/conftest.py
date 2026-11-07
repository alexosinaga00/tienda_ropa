"""Perfil de pruebas en PostgreSQL real.

La suite normal corre en SQLite en memoria, que no aplica `SELECT ... FOR
UPDATE`, no detecta deadlocks y no tiene columnas generadas ni vistas como las
de producción. Lo que depende de eso se prueba acá, contra una base PostgreSQL
de pruebas.

Se activa con la variable de entorno TEST_DATABASE_URL; si falta, todo este
directorio se salta (la suite en SQLite sigue completa). Ejemplo:

    postgresql+psycopg://usuario:clave@localhost:5432/fashionstore_test

Seguridad: la base se VACÍA y se recrea desde las migraciones al empezar, así
que el nombre de la base debe terminar en `_test`; de lo contrario, las pruebas
se niegan a correr. Nunca apuntar a `fashionstore_dev` ni a producción.
"""

import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import get_db
from app.core.tenant import CLAVE_EMPRESA, fijar_empresa
from app.core.tiempo import hoy_utc
from app.main import app
from app.plataforma.models import Empresa, Suscripcion
from app.plataforma.repository import UsuarioRepository
from app.plataforma.schemas import UsuarioCrear
from scripts.seed_entregas import seed as seed_entregas
from scripts.seed_inventario import seed as seed_inventario
from scripts.seed_pagos import seed as seed_pagos
from scripts.seed_planes import sembrar_planes
from scripts.seed_reservas import seed as seed_reservas
from scripts.seed_seguridad import seed as seed_seguridad
from scripts.seed_ventas import seed as seed_ventas

DIRECTORIO_BACKEND = Path(__file__).resolve().parents[2]
CLAVE = "claveSegura123"
CODIGO_EMPRESA = "fashionstore"
# Tras `TRUNCATE ... RESTART IDENTITY` la primera empresa sembrada siempre es la 1.
EMPRESA_ID_PG = 1


@pytest.fixture(scope="package", autouse=True)
def _sin_topes_de_reserva():
    """Las pruebas de aislamiento en PostgreSQL crean muchas reservas del mismo cliente en fechas lejanas: los topes de la
    reserva del cliente no son lo que se prueba aquí (ver tests/aislamiento/conftest.py)."""
    from app.core.config import get_settings

    ajustes = get_settings()
    parche = pytest.MonkeyPatch()
    parche.setattr(ajustes, "reserva_max_dias_anticipacion", 3650)
    parche.setattr(ajustes, "reserva_max_activas_por_cliente", 100_000)
    yield
    parche.undo()


@pytest.fixture(scope="session")
def url_pg() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL no está definida: se omite el perfil de PostgreSQL")
    base = make_url(url).database or ""
    if not base.endswith("_test"):
        pytest.fail(
            f"TEST_DATABASE_URL apunta a la base '{base}': el perfil de PostgreSQL vacía la base, "
            "así que su nombre debe terminar en '_test'"
        )
    return url


def ejecutar_alembic(url: str, *argumentos: str) -> subprocess.CompletedProcess:
    """Corre `alembic <argumentos>` contra `url` (siempre una base `_test`)."""
    assert (make_url(url).database or "").endswith("_test"), "alembic solo contra bases _test"
    entorno = {**os.environ, "DATABASE_URL": url, "PYTHONPATH": str(DIRECTORIO_BACKEND)}
    entorno.setdefault("JWT_SECRET_KEY", "clave-de-pruebas")
    return subprocess.run(
        [sys.executable, "-m", "alembic", *argumentos],
        cwd=DIRECTORIO_BACKEND,
        env=entorno,
        capture_output=True,
        text=True,
    )


def recrear_esquema(engine, url: str, revision: str = "head") -> None:
    """Vacía el esquema `public` y aplica las migraciones hasta `revision`."""
    assert (engine.url.database or "").endswith("_test"), "el esquema solo se vacía en bases _test"
    with engine.begin() as conexion:
        conexion.execute(text("DROP SCHEMA public CASCADE"))
        conexion.execute(text("CREATE SCHEMA public"))
    resultado = ejecutar_alembic(url, "upgrade", revision)
    assert resultado.returncode == 0, f"alembic upgrade {revision} falló:\n{resultado.stdout}\n{resultado.stderr}"


@pytest.fixture(scope="session")
def engine_pg(url_pg):
    """Recrea el esquema desde cero con `alembic upgrade head`: así cada
    ejecución también prueba que la cadena completa de migraciones se aplica."""
    engine = create_engine(url_pg, pool_pre_ping=True)
    recrear_esquema(engine, url_pg)

    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def fabrica_pg(engine_pg):
    """Sesiones ya fijadas en la empresa de pruebas ('fashionstore', id 1): las
    tablas de cada empresa exigen `empresa_id` al insertar y todavía no hay
    token que la fije (eso llega con el filtrado por empresa)."""
    return sessionmaker(
        bind=engine_pg, autoflush=False, autocommit=False, info={CLAVE_EMPRESA: EMPRESA_ID_PG}
    )


def sembrar_empresa_de_pruebas(db) -> Empresa:
    """Planes + empresa 'fashionstore' con suscripción activa del plan
    profesional. El TRUNCATE de `base_limpia` también borra los planes y la
    empresa que dejó la migración, así que se vuelven a crear."""
    planes = sembrar_planes(db)
    empresa = Empresa(nombre="FashionStore", codigo=CODIGO_EMPRESA, activo=True)
    db.add(empresa)
    db.flush()
    hoy = hoy_utc()  # la fecha de la aplicación es UTC
    db.add(
        Suscripcion(
            empresa_id=empresa.id,
            plan_id=planes["profesional"].id,
            estado="activa",
            fecha_inicio=hoy,
            fecha_vencimiento=hoy + dt.timedelta(days=365),
        )
    )
    db.flush()
    return empresa


@pytest.fixture(autouse=True)
def base_limpia(engine_pg, fabrica_pg):
    """Cada prueba parte de tablas vacías con los catálogos sembrados, los
    planes y la empresa de pruebas. No se
    usa el rollback por prueba de la suite en SQLite: acá las pruebas de
    concurrencia necesitan transacciones que de verdad se confirmen."""
    with engine_pg.begin() as conexion:
        tablas = conexion.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'")
        ).scalars().all()
        conexion.execute(text("TRUNCATE TABLE " + ", ".join(f'"{t}"' for t in tablas) + " RESTART IDENTITY CASCADE"))

    with fabrica_pg() as db:
        empresa = sembrar_empresa_de_pruebas(db)
        assert empresa.id == EMPRESA_ID_PG
        fijar_empresa(db, empresa.id)
        db.commit()
        seed_seguridad(db)
        seed_inventario(db)
        seed_reservas(db)
        seed_ventas(db)
        seed_pagos(db)
        seed_entregas(db)


@pytest.fixture()
def client_pg(fabrica_pg):
    """Cliente HTTP contra PostgreSQL. Cada petición abre su propia sesión,
    como el `get_db` real."""

    def _get_db():
        db = fabrica_pg()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as cliente:
        yield cliente
    app.dependency_overrides.clear()


def _login(client, email: str) -> dict:
    respuesta = client.post(
        "/api/v1/auth/login", json={"empresa": "fashionstore", "email": email, "password": CLAVE}
    )
    token = respuesta.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_pg(client_pg, fabrica_pg) -> dict:
    with fabrica_pg() as db:
        repo = UsuarioRepository()
        usuario = repo.crear(
            db, UsuarioCrear(nombre="Admin", apellido="Root", email="admin@example.com", password=CLAVE)
        )
        repo.asignar_roles(db, usuario, ["administrador"])
    return _login(client_pg, "admin@example.com")


def registrar_cliente(client, fabrica, email: str) -> int:
    """Alta de cliente por el registro de la tienda (crea también su fila en `cliente`).
    Devuelve el id del usuario."""
    respuesta = client.post(
        "/api/v1/public/fashionstore/registro",
        json={"nombre": "Cli", "apellido": "Ente", "email": email, "password": CLAVE},
    )
    assert respuesta.status_code == 201, respuesta.text
    from app.plataforma.models import Usuario

    with fabrica() as db:
        return db.query(Usuario).filter(Usuario.email == email).one().id


def _proxima_fecha_con_dia_semana(dia_semana: int):
    import datetime as dt

    base = dt.date.today() + dt.timedelta(days=7)
    return base + dt.timedelta(days=(dia_semana - base.isoweekday()) % 7)


@pytest.fixture()
def escenario(client_pg, admin_pg) -> dict:
    """Catálogo con dos variantes, una sucursal abierta los miércoles y 10
    unidades de cada variante recibidas en esa sucursal."""
    cat = client_pg.post("/api/v1/categorias", json={"nombre": "Camisas PG"}, headers=admin_pg).json()
    tallas = [
        client_pg.post("/api/v1/tallas", json={"codigo": codigo, "orden": i}, headers=admin_pg).json()
        for i, codigo in enumerate(("S", "M"), start=1)
    ]
    color = client_pg.post("/api/v1/colores", json={"nombre": "Gris PG"}, headers=admin_pg).json()
    producto = client_pg.post(
        "/api/v1/productos",
        json={
            "codigo": "PG-1",
            "nombre": "Camisa PostgreSQL",
            "categoria_id": cat["id"],
            "precio_base": "100.00",
            "tallas_ids": [t["id"] for t in tallas],
            "colores_ids": [color["id"]],
        },
        headers=admin_pg,
    ).json()
    variantes = sorted(
        v["id"] for v in client_pg.get(f"/api/v1/productos/{producto['id']}/variantes", headers=admin_pg).json()
    )

    ciudad = client_pg.post(
        "/api/v1/ciudades", json={"nombre": "Tarija PG", "departamento": "Tarija"}, headers=admin_pg
    ).json()
    sucursal_id = client_pg.post(
        "/api/v1/sucursales",
        json={"ciudad_id": ciudad["id"], "codigo": "SUC-PG", "nombre": "Sucursal PG", "direccion": "Av. 1"},
        headers=admin_pg,
    ).json()["id"]
    client_pg.post(
        f"/api/v1/sucursales/{sucursal_id}/horarios",
        json={"dia_semana": 3, "hora_apertura": "08:00:00", "hora_cierre": "20:00:00"},
        headers=admin_pg,
    )

    for variante_id in variantes:
        respuesta = client_pg.post(
            "/api/v1/inventario/movimientos",
            json={
                "variante_id": variante_id,
                "sucursal_id": sucursal_id,
                "tipo_movimiento_codigo": "recepcion",
                "cantidad": 10,
                "costo_unitario": "10.00",
            },
            headers=admin_pg,
        )
        assert respuesta.status_code == 201, respuesta.text

    return {
        "variantes": variantes,  # ascendentes
        "sucursal_id": sucursal_id,
        "fecha_visita": _proxima_fecha_con_dia_semana(3),  # miércoles
    }
