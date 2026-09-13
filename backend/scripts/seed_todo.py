"""Corre, en orden de dependencias, todos los seeds idempotentes: primero
los catálogos base y después scripts.seed_operativo (sucursales, staff,
proveedores y stock inicial).

scripts.seed_prendas_probador NO está incluido: necesita la carpeta del
dataset y credenciales de Cloudinary, se corre aparte y antes que este.

Sin --ejecutar, los seeds base NO se aplican y seed_operativo corre en
dry-run: solo se muestra qué se crearía.

Uso (desde backend/):
    python -m scripts.seed_todo
    python -m scripts.seed_todo --ejecutar
"""

from __future__ import annotations

import argparse

from scripts import (
    seed_catalogo,
    seed_entregas,
    seed_inventario,
    seed_operativo,
    seed_pagos,
    seed_reservas,
    seed_seguridad,
    seed_ventas,
)

SEEDS_BASE = [
    ("seguridad", seed_seguridad.seed),
    ("catalogo", seed_catalogo.seed),
    ("inventario", seed_inventario.seed),
    ("reservas", seed_reservas.seed),
    ("ventas", seed_ventas.seed),
    ("pagos", seed_pagos.seed),
    ("entregas", seed_entregas.seed),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ejecutar", action="store_true", help="Escribir de verdad (sin esto es dry-run)")
    args = parser.parse_args()

    if args.ejecutar:
        import app.main  # noqa: F401  (registra todos los modelos)
        from app.core.database import SessionLocal

        db = SessionLocal()
        try:
            for nombre, seed in SEEDS_BASE:
                seed(db)
                print(f"Seed de {nombre} aplicado.")
        finally:
            db.close()
    else:
        print("(dry-run: los seeds base no se aplican)")

    seed_operativo.main(["--ejecutar"] if args.ejecutar else [])


if __name__ == "__main__":
    main()
