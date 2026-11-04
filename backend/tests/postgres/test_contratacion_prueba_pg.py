"""Prueba gratis pública en PostgreSQL real: dos pruebas SIMULTÁNEAS con el mismo correo (o el mismo nombre de empresa)
dejan solo una ganadora, un 409 limpio para la otra y ninguna empresa huérfana.

SQLite no serializa las inserciones concurrentes; aquí el segundo INSERT espera al primero y cae en el índice único
parcial `ux_pedido_prueba_correo` (o en `empresa.codigo`). Las sesiones son anónimas (sin empresa), como en producción."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import ConflictoError, ErrorFuncional
from app.core.tenant import sin_filtro
from app.plataforma.casos_uso.cu04_gestionar_empresas_planes_suscripciones import GestionarContratacion
from app.plataforma.models import Empresa, PedidoContratacion, Suscripcion, Usuario
from app.plataforma.schemas import PruebaGratisSolicitud
from tests.postgres.paralelo import ejecutar_en_paralelo

CLAVE = "claveSegura123"


def _solicitud(nombre: str, correo: str) -> PruebaGratisSolicitud:
    return PruebaGratisSolicitud(
        nombre=nombre,
        plan_codigo="basico",
        administrador={"nombre": "Ana", "apellido": "Rojas", "email": correo, "password": CLAVE},
    )


@pytest.fixture()
def anonimas(engine_pg):
    """Sesiones SIN empresa (a diferencia de `fabrica_pg`, que fija la de pruebas)."""
    return sessionmaker(bind=engine_pg, autoflush=False, autocommit=False)


def _contar(anonimas) -> dict:
    with anonimas() as db:
        return {
            "empresas": db.scalar(select(func.count()).select_from(Empresa).where(Empresa.codigo != "fashionstore")),
            "pedidos": db.scalar(select(func.count()).select_from(PedidoContratacion)),
            "pruebas": db.scalar(sin_filtro(select(func.count()).select_from(Suscripcion).where(Suscripcion.es_prueba.is_(True)))),
            "administradores": db.scalar(
                sin_filtro(select(func.count()).select_from(Usuario).where(Usuario.email.like("%@carrera.example.com")))
            ),
        }


def test_dos_pruebas_simultaneas_con_el_mismo_correo_solo_deja_una(anonimas):
    correo = "ana@carrera.example.com"
    operaciones = [
        lambda db: GestionarContratacion().iniciar_prueba(db, _solicitud("Carrera Uno", correo)),
        lambda db: GestionarContratacion().iniciar_prueba(db, _solicitud("Carrera Dos", correo)),
    ]

    resultados = ejecutar_en_paralelo(anonimas, operaciones)

    ganadoras = [r for r in resultados if r.ok]
    perdedoras = [r for r in resultados if not r.ok]
    assert len(ganadoras) == 1, [repr(r.error) for r in perdedoras]
    (perdedora,) = perdedoras
    assert isinstance(perdedora.error, ErrorFuncional), repr(perdedora.error)
    assert (perdedora.error.codigo, perdedora.error.status_code) == ("prueba_ya_usada", 409)
    assert _contar(anonimas) == {"empresas": 1, "pedidos": 1, "pruebas": 1, "administradores": 1}


def test_dos_pruebas_simultaneas_con_el_mismo_nombre_solo_deja_una(anonimas):
    operaciones = [
        lambda db: GestionarContratacion().iniciar_prueba(db, _solicitud("Misma Tienda", "uno@carrera.example.com")),
        lambda db: GestionarContratacion().iniciar_prueba(db, _solicitud("Misma Tienda", "dos@carrera.example.com")),
    ]

    resultados = ejecutar_en_paralelo(anonimas, operaciones)

    perdedoras = [r for r in resultados if not r.ok]
    assert len(perdedoras) == 1, [repr(r.error) for r in perdedoras]
    assert isinstance(perdedoras[0].error, ConflictoError), repr(perdedoras[0].error)
    assert perdedoras[0].error.status_code == 409
    assert _contar(anonimas) == {"empresas": 1, "pedidos": 1, "pruebas": 1, "administradores": 1}


def test_pruebas_simultaneas_de_correos_y_nombres_distintos_se_crean_todas(anonimas):
    operaciones = [
        (lambda i: lambda db: GestionarContratacion().iniciar_prueba(db, _solicitud(f"Paralela {i}", f"p{i}@carrera.example.com")))(i)
        for i in range(3)
    ]

    resultados = ejecutar_en_paralelo(anonimas, operaciones)

    assert all(r.ok for r in resultados), [repr(r.error) for r in resultados if not r.ok]
    assert _contar(anonimas) == {"empresas": 3, "pedidos": 3, "pruebas": 3, "administradores": 3}
