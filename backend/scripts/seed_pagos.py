"""Seed de metodo_pago y estado_pago, según los INSERT del propio
docs/fashionstore_esquema.sql. Idempotente.

Uso:
    .venv/Scripts/python -m scripts.seed_pagos
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.pagos.models import EstadoPago, MetodoPago

METODOS_PAGO: list[tuple[str, str, bool, bool, bool]] = [
    # codigo, nombre, requiere_pasarela, disponible_caja, disponible_online
    ("efectivo", "Efectivo", False, True, False),
    ("qr", "Codigo QR", False, True, True),
    ("tarjeta", "Tarjeta debito/credito", False, True, False),
    ("transferencia", "Transferencia bancaria", False, True, False),
    ("libelula", "Pasarela Libelula", True, False, True),
    ("paypal", "PayPal", True, False, True),
    ("qr_online", "Pago con QR (online)", True, False, True),
]

ESTADOS_PAGO: list[tuple[str, str]] = [
    ("iniciado", "Iniciado"),
    ("aprobado", "Aprobado"),
    ("rechazado", "Rechazado"),
    ("reembolsado", "Reembolsado"),
]


def seed(db: Session) -> None:
    for codigo, nombre, requiere_pasarela, disponible_caja, disponible_online in METODOS_PAGO:
        metodo = db.query(MetodoPago).filter(MetodoPago.codigo == codigo).one_or_none()
        if metodo is None:
            db.add(
                MetodoPago(
                    codigo=codigo,
                    nombre=nombre,
                    requiere_pasarela=requiere_pasarela,
                    disponible_caja=disponible_caja,
                    disponible_online=disponible_online,
                )
            )

    for codigo, nombre in ESTADOS_PAGO:
        estado = db.query(EstadoPago).filter(EstadoPago.codigo == codigo).one_or_none()
        if estado is None:
            db.add(EstadoPago(codigo=codigo, nombre=nombre))

    db.commit()


if __name__ == "__main__":
    session = SessionLocal()
    try:
        seed(session)
        print("Seed de pagos aplicado.")
    finally:
        session.close()
