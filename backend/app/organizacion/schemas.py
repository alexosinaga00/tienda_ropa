from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---- Ciudades -----------------------------------------------------------


class CiudadCrear(BaseModel):
    nombre: str = Field(max_length=60)
    departamento: str | None = Field(default=None, max_length=60)


class CiudadActualizar(BaseModel):
    nombre: str | None = Field(default=None, max_length=60)
    departamento: str | None = Field(default=None, max_length=60)


class CiudadRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    departamento: str | None = None
    activo: bool


# ---- Sucursales -----------------------------------------------------------
# SucursalRespuesta es la que se expone públicamente (GET /sucursales):
# no incluye datos de empleados, ni los va a incluir nunca. No se agrega
# una relación con Empleado al modelo por esa misma razón.


class SucursalCrear(BaseModel):
    ciudad_id: int
    codigo: str = Field(max_length=15)
    nombre: str = Field(max_length=80)
    direccion: str = Field(max_length=200)
    telefono: str | None = Field(default=None, max_length=20)
    latitud: Decimal | None = None
    longitud: Decimal | None = None
    es_deposito: bool = False


class SucursalActualizar(BaseModel):
    ciudad_id: int | None = None
    codigo: str | None = Field(default=None, max_length=15)
    nombre: str | None = Field(default=None, max_length=80)
    direccion: str | None = Field(default=None, max_length=200)
    telefono: str | None = Field(default=None, max_length=20)
    latitud: Decimal | None = None
    longitud: Decimal | None = None
    es_deposito: bool | None = None
    activo: bool | None = None


class SucursalRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ciudad_id: int
    codigo: str
    nombre: str
    direccion: str
    telefono: str | None = None
    latitud: Decimal | None = None
    longitud: Decimal | None = None
    es_deposito: bool
    activo: bool
    creado_en: dt.datetime


# ---- Horarios de sucursal --------------------------------------------------


class HorarioCrear(BaseModel):
    dia_semana: int = Field(ge=1, le=7)
    hora_apertura: dt.time
    hora_cierre: dt.time

    @model_validator(mode="after")
    def _validar_rango(self) -> "HorarioCrear":
        if self.hora_cierre <= self.hora_apertura:
            raise ValueError("hora_cierre debe ser posterior a hora_apertura")
        return self


class HorarioActualizar(BaseModel):
    hora_apertura: dt.time | None = None
    hora_cierre: dt.time | None = None

    @model_validator(mode="after")
    def _validar_rango(self) -> "HorarioActualizar":
        if (
            self.hora_apertura is not None
            and self.hora_cierre is not None
            and self.hora_cierre <= self.hora_apertura
        ):
            raise ValueError("hora_cierre debe ser posterior a hora_apertura")
        return self


class HorarioRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sucursal_id: int
    dia_semana: int
    hora_apertura: dt.time
    hora_cierre: dt.time


# ---- Empleados ----------------------------------------------------------


class EmpleadoCrear(BaseModel):
    usuario_id: int
    sucursal_id: int | None = None
    ci: str | None = Field(default=None, max_length=20)
    cargo: str | None = Field(default=None, max_length=60)
    fecha_ingreso: dt.date | None = None


class EmpleadoActualizar(BaseModel):
    sucursal_id: int | None = None
    ci: str | None = Field(default=None, max_length=20)
    cargo: str | None = Field(default=None, max_length=60)
    fecha_ingreso: dt.date | None = None
    activo: bool | None = None


class EmpleadoRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    usuario_id: int
    usuario_nombre: str | None = None
    usuario_apellido: str | None = None
    sucursal_id: int | None = None
    sucursal_nombre: str | None = None
    ci: str | None = None
    cargo: str | None = None
    fecha_ingreso: dt.date | None = None
    activo: bool
