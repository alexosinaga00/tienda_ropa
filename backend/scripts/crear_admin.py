"""Crea el primer usuario administrador de un despliegue nuevo.

El registro público (/auth/registro) solo crea clientes y asignar roles
exige ya ser administrador, así que en una base recién migrada no hay forma
de entrar al back office sin esto. Idempotente: si el email ya existe, solo
se asegura de que tenga el rol administrador.

La contraseña se lee de una variable de entorno, nunca por argumento (no
queda en el historial de la terminal).

Uso (después de scripts.seed_seguridad):
    $env:ADMIN_EMAIL="admin@tudominio.com"; $env:ADMIN_PASSWORD="..."
    python -m scripts.crear_admin
"""

from __future__ import annotations

import os
import sys

from app.core.database import SessionLocal
from app.seguridad import models as _seguridad_models  # noqa: F401  (registra las tablas)
from app.seguridad.repository import UsuarioRepository
from app.seguridad.schemas import UsuarioCrear


def main() -> None:
    email = os.environ.get("ADMIN_EMAIL", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not email or len(password) < 8:
        sys.exit("Definí ADMIN_EMAIL y ADMIN_PASSWORD (mínimo 8 caracteres) como variables de entorno")

    repo = UsuarioRepository()
    db = SessionLocal()
    try:
        usuario = repo.obtener_por_email(db, email)
        if usuario is None:
            usuario = repo.crear(
                db, UsuarioCrear(nombre="Administrador", apellido="FashionStore", email=email, password=password)
            )
            print(f"Usuario creado: {email}")
        else:
            print(f"El usuario {email} ya existía")
        nombres = {rol.nombre for rol in usuario.roles} | {"administrador"}
        repo.asignar_roles(db, usuario, sorted(nombres))
        print("Rol administrador asignado.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
