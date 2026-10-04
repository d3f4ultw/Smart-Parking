"""Solicitudes y respuestas publicas del enlace de activacion OPERADOR."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class SolicitudCanjearEnlaceOperador(BaseModel):
    """Recibe el token de invitacion sin permitir campos adicionales."""

    model_config = ConfigDict(extra="forbid")

    token: Annotated[str, Field(min_length=32, max_length=128, repr=False)]


class SolicitudCompletarActivacionOperador(BaseModel):
    """Recibe solo la nueva contrasena; la confirmacion es del navegador."""

    model_config = ConfigDict(extra="forbid")

    nueva_contrasena: Annotated[str, Field(min_length=10, max_length=128, repr=False)]


class RespuestaEstadoDesafioOperador(BaseModel):
    """Estado booleano seguro de un desafio sin revelar la cuenta asociada."""

    model_config = ConfigDict(extra="forbid")

    valido: bool


class RespuestaCompletarActivacionOperador(BaseModel):
    """Resultado fijo de la primera activacion OPERADOR."""

    model_config = ConfigDict(extra="forbid")

    estado: Literal["cuenta_activada"]


__all__ = [
    "RespuestaCompletarActivacionOperador",
    "RespuestaEstadoDesafioOperador",
    "SolicitudCanjearEnlaceOperador",
    "SolicitudCompletarActivacionOperador",
]
