"""Contratos HTTP del registro inicial de OWNER."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class SolicitudCanjearEnlacePropietario(BaseModel):
    """Recibe el enlace opaco sin permitir campos adicionales."""

    model_config = ConfigDict(extra="forbid")

    token: Annotated[SecretStr, Field(min_length=32, max_length=128, repr=False)]


class SolicitudCompletarInscripcionPropietario(BaseModel):
    """Recibe identidad y contraseñas sin mostrar los secretos en errores."""

    model_config = ConfigDict(extra="forbid")

    nombre: Annotated[str, Field(min_length=1, max_length=100)]
    apellido_paterno: Annotated[str, Field(min_length=1, max_length=100)]
    apellido_materno: Annotated[str | None, Field(max_length=100)] = None
    contrasena_admin: Annotated[
        SecretStr,
        Field(min_length=10, max_length=128, repr=False),
    ]
    confirmar_contrasena_admin: Annotated[
        SecretStr,
        Field(min_length=10, max_length=128, repr=False),
    ]
    contrasena_login: Annotated[
        SecretStr | None,
        Field(default=None, min_length=10, max_length=128, repr=False),
    ] = None
    confirmar_contrasena_login: Annotated[
        SecretStr | None,
        Field(default=None, min_length=10, max_length=128, repr=False),
    ] = None


class RespuestaEstadoDesafioPropietario(BaseModel):
    """Expone identidad y vencimiento solo tras canjear el correo verificado."""

    model_config = ConfigDict(extra="forbid")

    valido: bool
    tipo_cuenta: Literal["nueva", "retorno"] | None
    nombre: str | None = None
    apellido_paterno: str | None = None
    apellido_materno: str | None = None
    expira_en: datetime | None = None


class RespuestaInscripcionPropietario(BaseModel):
    """Resultado fijo de una activacion OWNER aceptada."""

    model_config = ConfigDict(extra="forbid")

    estado: Literal["owner_activado"]


__all__ = [
    "RespuestaEstadoDesafioPropietario",
    "RespuestaInscripcionPropietario",
    "SolicitudCanjearEnlacePropietario",
    "SolicitudCompletarInscripcionPropietario",
]
