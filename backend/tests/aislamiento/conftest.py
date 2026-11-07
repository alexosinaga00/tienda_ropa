"""Fixtures de la suite de aislamiento (E05).

El universo de dos empresas se crea UNA vez por paquete, sobre un motor SQLite propio (no el
`db_session` de cada prueba, que vuelve a sembrar todo cada vez). Cada petición recibe una
sesión nueva y sin empresa, como en producción: la empresa la fija la propia petición.
"""

import datetime as dt
import hashlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.catalogo.repository import VW_INVENTARIO_CONSOLIDADO_V2_SQL
from app.core.database import Base, get_db
from app.core.tenant import fijar_empresa
from app.main import app
from app.plataforma.models import Empresa, Plan, Suscripcion
from app.plataforma.repository import UsuarioRepository
from app.plataforma.schemas import UsuarioCrear
from scripts.seed_entregas import seed as seed_entregas
from scripts.seed_inventario import seed as seed_inventario
from scripts.seed_pagos import seed as seed_pagos
from scripts.seed_planes import sembrar_planes
from scripts.seed_reservas import seed as seed_reservas
from scripts.seed_seguridad import seed as seed_seguridad
from scripts.seed_ventas import seed as seed_ventas
from sqlalchemy import select
from tests.conftest import EmpresaDePrueba, crear_empresa, token_de

from .universo import CLAVE, Universo, crear_universo


class Mundo:
    """Las dos empresas de la suite: A (plan Profesional) y B (plan Básico)."""

    def __init__(self, engine, sesiones, client, a: Universo, b: Universo):
        self.engine = engine
        self.sesiones = sesiones
        self.client = client
        self.a = a
        self.b = b

    def tablas_de_empresa(self) -> list:
        return [t for t in Base.metadata.sorted_tables if "empresa_id" in t.c]

    def instantanea(self, empresa_id: int) -> dict[str, tuple[int, str]]:
        """Por cada tabla propia de empresa: (filas, huella) de las filas de `empresa_id`.
        Igual antes y después = la empresa no cambió."""
        resultado = {}
        with self.engine.connect() as conexion:
            for tabla in self.tablas_de_empresa():
                filas = conexion.execute(tabla.select().where(tabla.c.empresa_id == empresa_id)).all()
                huella = hashlib.sha1("\n".join(sorted(repr(tuple(f)) for f in filas)).encode()).hexdigest()
                resultado[tabla.name] = (len(filas), huella)
        return resultado

    def cambios(self, antes: dict, despues: dict) -> list[str]:
        return [f"{nombre}: {antes[nombre][0]} -> {despues[nombre][0]} filas" if antes[nombre][0] != despues[nombre][0]
                else f"{nombre}: contenido distinto" for nombre in antes if antes[nombre] != despues[nombre]]


def _preparar_base(engine, sesiones):
    Base.metadata.create_all(engine)
    with engine.begin() as conexion:
        conexion.execute(text(VW_INVENTARIO_CONSOLIDADO_V2_SQL))
    with sesiones() as db:
        # Igual que `db_session`: planes, la empresa 'fashionstore' y las semillas globales.
        sembrar_planes(db)
        empresa = Empresa(nombre="FashionStore", codigo="fashionstore")
        db.add(empresa)
        db.flush()
        hoy = dt.date.today()
        db.add(
            Suscripcion(
                empresa_id=empresa.id,
                plan_id=db.scalar(select(Plan.id).where(Plan.codigo == "profesional")),
                estado="activa",
                fecha_inicio=hoy,
                fecha_vencimiento=hoy + dt.timedelta(days=365),
            )
        )
        db.commit()
        fijar_empresa(db, empresa.id)
        seed_seguridad(db)
        seed_inventario(db)
        seed_reservas(db)
        seed_ventas(db)
        seed_pagos(db)
        seed_entregas(db)


def _dos_empresas(sesiones) -> tuple[EmpresaDePrueba, EmpresaDePrueba]:
    """A ('tienda-a', Profesional) y B ('tienda-b', Básico), cada una con su administrador."""
    repo = UsuarioRepository()
    creadas = {}
    with sesiones() as db:
        for clave, codigo, plan in (("a", "tienda-a", "profesional"), ("b", "tienda-b", "basico")):
            empresa = crear_empresa(db, codigo, plan=plan)
            fijar_empresa(db, empresa.id)
            admin = repo.crear(
                db,
                UsuarioCrear(nombre="Admin", apellido=clave.upper(), email="admin@tienda.bo", password=CLAVE),
            )
            repo.asignar_roles(db, admin, ["administrador"])
            creadas[clave] = EmpresaDePrueba(id=empresa.id, codigo=codigo, admin_id=admin.id, headers=token_de(db, admin))
    return creadas["a"], creadas["b"]


@pytest.fixture(scope="package", autouse=True)
def _sin_topes_de_reserva():
    """El universo crea muchas reservas del MISMO cliente en fechas muy distintas (un día libre por reserva): los topes de la
    reserva del cliente (fecha cercana, reservas abiertas) no son lo que se prueba aquí, así que se aflojan en este paquete."""
    from app.core.config import get_settings

    ajustes = get_settings()
    parche = pytest.MonkeyPatch()
    parche.setattr(ajustes, "reserva_max_dias_anticipacion", 3650)
    parche.setattr(ajustes, "reserva_max_activas_por_cliente", 100_000)
    yield
    parche.undo()


@pytest.fixture(scope="package")
def _mundo():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _sin_begin_implicito(dbapi_conexion, _registro):
        dbapi_conexion.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin_explicito(conexion):
        conexion.exec_driver_sql("BEGIN")

    sesiones = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    _preparar_base(engine, sesiones)
    empresa_a, empresa_b = _dos_empresas(sesiones)

    def _db_por_peticion():
        sesion = sesiones()
        try:
            yield sesion
        finally:
            sesion.close()

    app.dependency_overrides[get_db] = _db_por_peticion
    with TestClient(app) as client:
        a = crear_universo(client, sesiones, empresa_a, "A")
        b = crear_universo(client, sesiones, empresa_b, "B")
        mundo = Mundo(engine, sesiones, client, a, b)
        mundo.db_por_peticion = _db_por_peticion
        yield mundo
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


@pytest.fixture(autouse=True)
def _almacenamiento_falso(monkeypatch):
    """Cloudinary no está configurado en las pruebas: sus funciones se reemplazan por dobles
    que no tocan la red. Solo cambia dónde se guarda la imagen, no lo que se aísla."""
    from app.core import storage

    monkeypatch.setattr(storage, "subir_imagen", lambda contenido, carpeta, **_: f"{carpeta}/falso")
    monkeypatch.setattr(storage, "eliminar_imagen", lambda public_id: None)
    monkeypatch.setattr(storage, "url_catalogo", lambda public_id, ancho=None, alto=None: f"https://cdn.test/{public_id}")
    monkeypatch.setattr(storage, "url_probador", lambda public_id: f"https://cdn.test/{public_id}")


@pytest.fixture()
def mundo(_mundo):
    """El mundo del paquete. Reinstala el override de `get_db` por si otra fixture lo limpió."""
    app.dependency_overrides[get_db] = _mundo.db_por_peticion
    return _mundo
