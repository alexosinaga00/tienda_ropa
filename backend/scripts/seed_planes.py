"""Seed de los 2 planes del sistema (D07): basico y profesional.

Idempotente: inserta el plan si no existe y, si existe, actualiza sus
columnas con los valores de PLANES. Los mismos valores están escritos como
literales en la migración multitenant (la producción no corre seeds); una
prueba comprueba que ambos coinciden.

Uso:
    .venv/Scripts/python -m scripts.seed_planes
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

PLANES: list[dict] = [
    {
        "codigo": "basico",
        "nombre": "Básico",
        "max_sucursales": 2,
        "reportes_convencionales": True,
        "reportes_ia": False,
        "operacion_offline": True,
        "analitica_ml": False,
        "copias_seguridad": False,
        "gestion_productos": True,
        "gestion_ventas": True,
        "reservas": True,
        "max_copias_historial": 0,
        "plazo_cambio_horas_defecto": 24,
        "activo": True,
    },
    {
        "codigo": "profesional",
        "nombre": "Profesional",
        "max_sucursales": 10,
        "reportes_convencionales": True,
        "reportes_ia": True,
        "operacion_offline": True,
        "analitica_ml": True,
        "copias_seguridad": True,
        "gestion_productos": True,
        "gestion_ventas": True,
        "reservas": True,
        "max_copias_historial": 5,
        "plazo_cambio_horas_defecto": 24,
        "activo": True,
    },
]

# Precio mensual en Bs de cada plan. Va aparte de PLANES a propósito: PLANES se compara con los literales de la
# migración multitenant (anterior al precio); el precio lo pone la migración de la contratación (c5e1b7a38d92).
PRECIOS_MENSUALES_BS: dict[str, Decimal] = {
    "basico": Decimal("120.00"),
    "profesional": Decimal("590.00"),
}


def sembrar_planes(db: Session) -> dict:
    """Inserta o actualiza los planes. Hace flush, no commit. Devuelve los
    planes por código."""
    from app.plataforma.models import Plan

    resultado: dict[str, Plan] = {}
    for datos in PLANES:
        plan = db.scalar(select(Plan).where(Plan.codigo == datos["codigo"]))
        if plan is None:
            plan = Plan(**datos)
            db.add(plan)
        else:
            for columna, valor in datos.items():
                setattr(plan, columna, valor)
        plan.precio_mensual_bs = PRECIOS_MENSUALES_BS[datos["codigo"]]
        resultado[datos["codigo"]] = plan
    db.flush()
    return resultado


def main() -> None:
    import app.main  # noqa: F401  (registra todos los modelos)
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        sembrar_planes(db)
        db.commit()
        print("Seed de planes aplicado.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
