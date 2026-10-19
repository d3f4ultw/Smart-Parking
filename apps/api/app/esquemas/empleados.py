"""Contratos HTTP estrictos para el directorio laboral."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.turno_empleado import CodigoTurnoEmpleado


class SolicitudRegistrarEmpleado(BaseModel):
    """Datos que puede elegir el Dueño al dar de alta a una persona."""

    model_config = ConfigDict(extra="forbid")

    nombres: Annotated[str, Field(min_length=1, max_length=100)]
    apellido_paterno: Annotated[str, Field(min_length=1, max_length=100)]
    apellido_materno: Annotated[str | None, Field(max_length=100)] = None
    turno_empleado_id: Annotated[int, Field(strict=True, gt=0)]

    @field_validator("nombres", "apellido_paterno", mode="before")
    @classmethod
    def recortar_nombre_requerido(cls, valor: object) -> object:
        if isinstance(valor, str):
            return valor.strip()
        return valor

    @field_validator("apellido_materno", mode="before")
    @classmethod
    def recortar_nombre_opcional(cls, valor: object) -> object:
        if isinstance(valor, str):
            return valor.strip() or None
        return valor


class SolicitudCambiarEstadoEmpleado(BaseModel):
    """Solicita un cambio de estado contra una revision conocida."""

    model_config = ConfigDict(extra="forbid")

    esta_activo: Annotated[bool, Field(strict=True)]
    revision_esperada: Annotated[int, Field(strict=True, gt=0)]


class TurnoEmpleadoDisponible(BaseModel):
    """Opcion de turno sin incluir ni copiar sus horas centrales."""

    model_config = ConfigDict(extra="forbid")

    id: str
    codigo: CodigoTurnoEmpleado
    nombre: str


class RespuestaEmpleado(BaseModel):
    """Representacion segura de identidad, turno y estado del empleado."""

    model_config = ConfigDict(extra="forbid")

    id: str
    codigo_empleado: str
    nombres: str
    apellido_paterno: str
    apellido_materno: str | None
    turno: TurnoEmpleadoDisponible
    esta_activo: bool
    revision_estado: int
    creado_en: datetime
    actualizado_en: datetime


class RespuestaListaEmpleados(BaseModel):
    """Pagina del directorio y catalogo compartido disponible."""

    model_config = ConfigDict(extra="forbid")

    empleados: list[RespuestaEmpleado]
    pagina: int
    tamano_pagina: int
    total: int
    total_paginas: int
    turnos_disponibles: list[TurnoEmpleadoDisponible]


__all__ = [
    "RespuestaEmpleado",
    "RespuestaListaEmpleados",
    "SolicitudCambiarEstadoEmpleado",
    "SolicitudRegistrarEmpleado",
    "TurnoEmpleadoDisponible",
]
