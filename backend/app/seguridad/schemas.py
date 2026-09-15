from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---- Roles ----------------------------------------------------------------


class RolCrear(BaseModel):
    nombre: str = Field(max_length=40)
    descripcion: str | None = Field(default=None, max_length=200)


class RolActualizar(BaseModel):
    nombre: str | None = Field(default=None, max_length=40)
    descripcion: str | None = Field(default=None, max_length=200)


class PermisoRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    modulo: str
    descripcion: str | None = None


class RolRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    descripcion: str | None = None
    activo: bool
    permisos: list[PermisoRespuesta] = []


class AsignarPermisosRequest(BaseModel):
    codigos_permiso: list[str]


# ---- Usuarios ---------------------------------------------------------------


class UsuarioCrear(BaseModel):
    nombre: str = Field(max_length=60)
    apellido: str = Field(max_length=60)
    email: EmailStr
    telefono: str | None = Field(default=None, max_length=20)
    password: str = Field(min_length=8, max_length=72)


class UsuarioActualizar(BaseModel):
    nombre: str | None = Field(default=None, max_length=60)
    apellido: str | None = Field(default=None, max_length=60)
    telefono: str | None = Field(default=None, max_length=20)
    activo: bool | None = None


class AsignarRolesRequest(BaseModel):
    nombres_rol: list[str]


class UsuarioRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    apellido: str
    email: str
    telefono: str | None = None
    activo: bool
    roles: list[str] = []

    @classmethod
    def from_modelo(cls, usuario) -> "UsuarioRespuesta":
        return cls(
            id=usuario.id,
            nombre=usuario.nombre,
            apellido=usuario.apellido,
            email=usuario.email,
            telefono=usuario.telefono,
            activo=usuario.activo,
            roles=[r.nombre for r in usuario.roles],
        )


class UsuarioYoRespuesta(UsuarioRespuesta):
    permisos: list[str] = []


# ---- Autenticación ----------------------------------------------------------


class RegistroRequest(BaseModel):
    nombre: str = Field(max_length=60)
    apellido: str = Field(max_length=60)
    email: EmailStr
    telefono: str | None = Field(default=None, max_length=20)
    password: str = Field(min_length=8, max_length=72)
    ci_nit: str | None = Field(default=None, max_length=20)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class RecuperarRequest(BaseModel):
    email: EmailStr


class RecuperarConfirmarRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=72)


class RecuperarRespuesta(BaseModel):
    detail: str
    token_dev: str | None = None


class TokenRespuesta(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# ---- Perfil de cliente --------------------------------------------------------


class ClientePerfilRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nombre: str
    apellido: str
    email: str
    telefono: str | None = None
    ci_nit: str | None = None
    razon_social: str | None = None
    fecha_nacimiento: dt.date | None = None
    estatura_cm: int | None = None
    preferencia_ajuste: str | None = None
    acepta_datos_foto: bool

    @classmethod
    def from_modelo(cls, cliente) -> "ClientePerfilRespuesta":
        return cls(
            nombre=cliente.usuario.nombre,
            apellido=cliente.usuario.apellido,
            email=cliente.usuario.email,
            telefono=cliente.usuario.telefono,
            ci_nit=cliente.ci_nit,
            razon_social=cliente.razon_social,
            fecha_nacimiento=cliente.fecha_nacimiento,
            estatura_cm=cliente.estatura_cm,
            preferencia_ajuste=cliente.preferencia_ajuste,
            acepta_datos_foto=cliente.acepta_datos_foto,
        )


class ClientePerfilActualizar(BaseModel):
    telefono: str | None = Field(default=None, max_length=20)
    ci_nit: str | None = Field(default=None, max_length=20)
    razon_social: str | None = Field(default=None, max_length=120)
    fecha_nacimiento: dt.date | None = None
    estatura_cm: int | None = Field(default=None, ge=100, le=250)
    # Mismos valores que el CHECK de la tabla `cliente`: un valor distinto
    # tiene que ser un 422 claro, no un error de la base.
    preferencia_ajuste: Literal["ajustado", "regular", "holgado"] | None = None
    acepta_datos_foto: bool | None = None
