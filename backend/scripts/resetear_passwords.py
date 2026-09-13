"""Fija la misma contraseña a todos los usuarios (pensado para una base de
demo/pruebas). Lista email, roles y estado de cada usuario.

La contraseña se lee de una variable de entorno, nunca por argumento. El
hash lo hace seguridad.repository (bcrypt), igual que la recuperación de
contraseña de la app.

Por defecto NO escribe nada (dry-run). Para escribir hace falta --ejecutar.

Uso (desde backend/):
    python -m scripts.resetear_passwords
    $env:NUEVA_PASSWORD="..."; python -m scripts.resetear_passwords --ejecutar

Variables de entorno: DATABASE_URL, JWT_SECRET_KEY (la exige Settings) y,
con --ejecutar, NUEVA_PASSWORD (mínimo 8 caracteres).
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import select


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ejecutar", action="store_true", help="Escribir de verdad (sin esto es dry-run)")
    args = parser.parse_args(argv)

    import app.main  # noqa: F401  (registra todos los modelos)
    from app.core.database import SessionLocal, engine
    from app.seguridad.models import Usuario
    from app.seguridad.repository import UsuarioRepository

    print(f"Base destino: {engine.url.host}:{engine.url.port}/{engine.url.database}")

    password = os.environ.get("NUEVA_PASSWORD")
    if args.ejecutar and (password is None or len(password) < 8):
        sys.exit("Falta NUEVA_PASSWORD (mínimo 8 caracteres)")

    repo = UsuarioRepository()
    db = SessionLocal()
    try:
        usuarios = list(db.scalars(select(Usuario).order_by(Usuario.id)))
        print(f"\n{'id':>4}  {'email':40} {'activo':6}  roles")
        for usuario in usuarios:
            roles = ", ".join(sorted(r.nombre for r in usuario.roles)) or "-"
            print(f"{usuario.id:>4}  {usuario.email:40} {'sí' if usuario.activo else 'no':6}  {roles}")
            if args.ejecutar:
                repo.actualizar_password(db, usuario, password)
    finally:
        db.close()

    if args.ejecutar:
        print(f"\nContraseña actualizada para {len(usuarios)} usuarios.")
    else:
        print(f"\n(dry-run: {len(usuarios)} usuarios, no se escribió nada; agregar --ejecutar)")


if __name__ == "__main__":
    main()
