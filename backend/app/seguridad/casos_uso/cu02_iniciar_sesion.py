"""CU-02 — Iniciar sesión

Actor: Cliente, Administrador, Encargado, Cajero, Proveedor.
Precondición: el usuario existe y está activo.
Postcondición: se emiten access_token y refresh_token con los roles y
permisos vigentes del usuario.

Incluye también refrescar el token (mismo flujo de autenticación, no un CU
aparte del catálogo).
"""

import datetime as dt

from fastapi import status
from sqlalchemy.orm import Session

from app.core.exceptions import DomainError
from app.core.security import (
    crear_access_token,
    crear_refresh_token,
    decodificar_token,
    verificar_password,
)
from app.seguridad.politicas import obtener_usuario_para_auth, permisos_de_usuario
from app.seguridad.repository import UsuarioRepository
from app.seguridad.schemas import LoginRequest, TokenRespuesta

# Hash bcrypt fijo (de un password que no le pertenece a nadie) para que
# ejecutar() siempre corra verificar_password() con costo real, exista o no
# el email: sin esto, el cortocircuito de `or` se salta bcrypt.checkpw()
# cuando el usuario no existe, y ese ida-y-vuelta más rápido deja adivinar
# por tiempo de respuesta qué emails están registrados.
_HASH_DUMMY = "$2b$12$d1ru1mgPSWsBsc/AHIyMHeWrDeAVeESRlnXjY52JXjnR/XOLoWB22"


class IniciarSesion:
    def __init__(self) -> None:
        self._usuarios = UsuarioRepository()

    def _generar_tokens(self, usuario_id: int, roles: list[str], permisos: list[str]) -> TokenRespuesta:
        return TokenRespuesta(
            access_token=crear_access_token(usuario_id, roles, permisos),
            refresh_token=crear_refresh_token(usuario_id),
        )

    def ejecutar(self, db: Session, datos: LoginRequest) -> TokenRespuesta:
        usuario = self._usuarios.obtener_por_email(db, datos.email)
        hash_a_verificar = usuario.password_hash if usuario is not None else _HASH_DUMMY
        password_valida = verificar_password(datos.password, hash_a_verificar)
        credenciales_invalidas = usuario is None or not usuario.activo or not password_valida
        if credenciales_invalidas:
            raise DomainError("Credenciales inválidas", status_code=status.HTTP_401_UNAUTHORIZED)

        usuario.ultimo_acceso = dt.datetime.now(dt.timezone.utc)
        db.commit()

        roles = [r.nombre for r in usuario.roles]
        permisos = permisos_de_usuario(db, usuario.id)
        return self._generar_tokens(usuario.id, roles, permisos)

    def refrescar(self, db: Session, refresh_token: str) -> TokenRespuesta:
        payload = decodificar_token(refresh_token)
        if payload.get("tipo") != "refresh":
            raise DomainError("Token inválido", status_code=status.HTTP_401_UNAUTHORIZED)

        usuario = obtener_usuario_para_auth(db, int(payload["sub"]))
        if usuario is None:
            raise DomainError("Usuario inválido", status_code=status.HTTP_401_UNAUTHORIZED)

        roles = [r.nombre for r in usuario.roles]
        permisos = permisos_de_usuario(db, usuario.id)
        return self._generar_tokens(usuario.id, roles, permisos)
