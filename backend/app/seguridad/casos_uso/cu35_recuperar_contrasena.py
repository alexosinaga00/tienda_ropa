"""CU-35 — Recuperar contraseña

Actor: Cliente, Administrador, Encargado de sucursal, Cajero.
Precondición: el usuario existe.
Postcondición: si el email está registrado, se emite un token de
recuperación; al confirmarlo con una contraseña nueva, el hash se
actualiza.
"""

import logging

from fastapi import status
from sqlalchemy.orm import Session

from app.core.exceptions import DomainError
from app.core.security import crear_reset_token, decodificar_token
from app.seguridad.politicas import obtener_usuario_para_auth
from app.seguridad.repository import UsuarioRepository

logger = logging.getLogger(__name__)


class RecuperarContrasena:
    def __init__(self) -> None:
        self._usuarios = UsuarioRepository()

    def solicitar(self, db: Session, email: str) -> str | None:
        """Genera un token de recuperación si el email existe.

        Todavía no hay un servicio de correo en el proyecto, así que el token
        se deja en el log para pruebas manuales, y se devuelve acá para que
        el router lo incluya en la respuesta solo en entorno local (ver
        `RecuperarRespuesta.token_dev`). La respuesta al cliente es siempre
        genérica en cuanto al mensaje (ver router) para no revelar si el
        email está registrado.
        """
        usuario = self._usuarios.obtener_por_email(db, email)
        if usuario is None or not usuario.activo:
            return None

        token = crear_reset_token(usuario.id)
        logger.info("Token de recuperación para %s: %s", email, token)
        return token

    def confirmar(self, db: Session, token: str, password: str) -> None:
        payload = decodificar_token(token)
        if payload.get("tipo") != "reset":
            raise DomainError("Token inválido", status_code=status.HTTP_401_UNAUTHORIZED)

        usuario = obtener_usuario_para_auth(db, int(payload["sub"]))
        if usuario is None:
            raise DomainError("Token inválido", status_code=status.HTTP_401_UNAUTHORIZED)

        self._usuarios.actualizar_password(db, usuario, password)
