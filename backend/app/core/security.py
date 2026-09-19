"""Hash de contraseñas, JWT y dependencias de autenticación/autorización.

Vive en `core` (así lo pide el plan de desarrollo), pero para resolver el
usuario/los permisos detrás de un JWT necesita al paquete `seguridad`
(dueño de esas tablas). En vez de consultar `usuario`/`rol_permiso`/
`usuario_rol` directamente, llama a `seguridad.politicas` -- mismo patrón
que CLAUDE.md pide entre los 13 paquetes de negocio ("llama a la política
del otro paquete, no consulta sus tablas"). El import es diferido (dentro
de cada función) porque `seguridad.repository` importa `core.security` a
nivel de módulo (para hash_password): con el import acá arriba, cargar
cualquiera de los dos módulos primero rompería con un ImportError
circular.
"""

from __future__ import annotations

import datetime as dt
import hmac

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import PermisoDenegadoError

settings = get_settings()

_bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificar_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def _crear_token(usuario_id: int, tipo: str, expira: dt.timedelta, extra: dict | None = None) -> str:
    ahora = dt.datetime.now(dt.timezone.utc)
    payload: dict = {"sub": str(usuario_id), "tipo": tipo, "iat": ahora, "exp": ahora + expira}
    payload.update(extra or {})
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def crear_access_token(usuario_id: int, roles: list[str], permisos: list[str]) -> str:
    """El payload lleva usuario_id, roles y permisos, nunca la contraseña."""
    return _crear_token(
        usuario_id,
        tipo="access",
        expira=dt.timedelta(minutes=settings.jwt_access_token_expire_minutes),
        extra={"roles": roles, "permisos": permisos},
    )


def crear_refresh_token(usuario_id: int) -> str:
    return _crear_token(
        usuario_id,
        tipo="refresh",
        expira=dt.timedelta(days=settings.jwt_refresh_token_expire_days),
    )


def crear_reset_token(usuario_id: int) -> str:
    return _crear_token(usuario_id, tipo="reset", expira=dt.timedelta(minutes=30))


def decodificar_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado"
        ) from exc


def permisos_de_usuario(db: Session, usuario_id: int) -> list[str]:
    """Códigos de permiso reales del usuario, vía sus roles activos. La
    consulta real vive en seguridad.politicas (dueño de esas tablas); acá
    solo se reexpone con el mismo nombre para no obligar a los demás
    paquetes a cambiar su import."""
    from app.seguridad import politicas as seguridad_politicas

    return seguridad_politicas.permisos_de_usuario(db, usuario_id)


def get_current_user(
    credenciales: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
):
    from app.seguridad import politicas as seguridad_politicas

    if credenciales is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")

    payload = decodificar_token(credenciales.credentials)
    if payload.get("tipo") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    usuario = seguridad_politicas.obtener_usuario_para_auth(db, int(payload["sub"]))
    if usuario is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario inválido")
    return usuario


def get_current_user_opcional(
    credenciales: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
):
    """Igual que `get_current_user`, pero devuelve `None` en vez de 401 si no
    hay token o es inválido/expirado. Para endpoints públicos que igual
    quieren asociar la acción a un usuario logueado cuando lo hay (p. ej.
    POST /ia/voz, que admite búsqueda anónima)."""
    from app.seguridad import politicas as seguridad_politicas

    if credenciales is None:
        return None
    try:
        payload = decodificar_token(credenciales.credentials)
    except HTTPException:
        return None
    if payload.get("tipo") != "access":
        return None
    return seguridad_politicas.obtener_usuario_para_auth(db, int(payload["sub"]))


def require_permission(codigo: str):
    """Dependencia que exige el permiso `codigo`.

    Consulta rol_permiso/usuario_rol en cada request: el permiso vivo en la
    base es la fuente de verdad, no una lista fija ni lo que venga en el JWT.
    """

    def verificador(usuario=Depends(get_current_user), db: Session = Depends(get_db)):
        if codigo not in permisos_de_usuario(db, usuario.id):
            raise PermisoDenegadoError(f"Falta el permiso '{codigo}'")
        return usuario

    return verificador


def require_service_token(x_service_token: str | None = Header(default=None)) -> None:
    """Protege endpoints de tareas de sistema (cron/scheduler), que no
    tienen un usuario logueado detrás. No es un JWT: es un secreto fijo
    compartido, configurado por variable de entorno (TAREAS_TOKEN). Si no
    está configurado, la tarea queda inhabilitada (nunca compara contra
    una cadena vacía)."""
    if not settings.tareas_token or not x_service_token or not hmac.compare_digest(x_service_token, settings.tareas_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de servicio inválido")
