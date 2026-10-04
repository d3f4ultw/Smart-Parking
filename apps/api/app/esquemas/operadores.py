"""Esquemas HTTP para crear cuentas OPERADOR desde el panel ADMIN."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class SolicitudCrearOperador(BaseModel):
    """Datos requeridos para crear un OPERADOR sin campos de estado."""

    model_config = ConfigDict(extra="forbid")

    nombre: Annotated[str, Field(min_length=1, max_length=100)]
    apellido_paterno: Annotated[str, Field(min_length=1, max_length=100)]
    apellido_materno: Annotated[str, Field(min_length=1, max_length=100)]
    correo: Annotated[str, Field(min_length=1, max_length=320, repr=False)]


class RespuestaCrearOperador(BaseModel):
    """Respuesta mínima de una creación aceptada."""

    estado: Literal["operador_creado"]


class RespuestaCreadorOperador(BaseModel):
    """Identidad ADMIN segura atribuida a la creacion del OPERADOR."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    nombre: str | None
    apellido_paterno: str | None
    apellido_materno: str | None
    correo: str


class RespuestaOperador(BaseModel):
    """Vista publica minima de una cuenta OPERADOR."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    nombre: str
    apellido_paterno: str
    apellido_materno: str
    correo: str
    esta_activo: bool
    creado_en: datetime
    creado_por: RespuestaCreadorOperador | None
    estado_cuenta: Literal[
        "pendiente_activacion",
        "acceso_habilitado",
        "inactivo",
    ]


class RespuestaListaOperadores(BaseModel):
    """Lista segura de OPERADOR para ADMIN."""

    model_config = ConfigDict(extra="forbid")

    operadores: list[RespuestaOperador]
    pagina: int
    tamano_pagina: int
    total: int
    total_paginas: int
    cursor_eventos: str


class RespuestaAccionOperador(BaseModel):
    """Estado fijo devuelto por una mutacion administrativa."""

    model_config = ConfigDict(extra="forbid")

    estado: Literal[
        "operador_desactivado",
        "operador_reactivado",
        "contrasena_regenerada",
        "invitacion_enviada",
    ]


__all__ = [
    "RespuestaAccionOperador",
    "RespuestaCrearOperador",
    "RespuestaCreadorOperador",
    "RespuestaListaOperadores",
    "RespuestaOperador",
    "SolicitudCrearOperador",
]
