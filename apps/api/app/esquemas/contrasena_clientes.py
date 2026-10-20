"""Esquemas para el cambio de contrasena de una cuenta cliente."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.seguridad.contrasenas import (
    LONGITUD_MAXIMA_CONTRASENA,
    LONGITUD_MINIMA_CONTRASENA,
    validar_confirmacion_contrasena,
)


class SolicitudCambioContrasena(BaseModel):
    """Credenciales requeridas para cambiar la contrasena autenticada."""

    model_config = ConfigDict(extra="forbid")

    contrasena_actual: Annotated[
        str,
        Field(
            strict=True,
            min_length=LONGITUD_MINIMA_CONTRASENA,
            max_length=LONGITUD_MAXIMA_CONTRASENA,
            repr=False,
            json_schema_extra={"writeOnly": True},
        ),
    ]
    contrasena_nueva: Annotated[
        str,
        Field(
            strict=True,
            min_length=LONGITUD_MINIMA_CONTRASENA,
            max_length=LONGITUD_MAXIMA_CONTRASENA,
            repr=False,
            json_schema_extra={"writeOnly": True},
        ),
    ]
    confirmacion_contrasena_nueva: Annotated[
        str,
        Field(
            strict=True,
            min_length=LONGITUD_MINIMA_CONTRASENA,
            max_length=LONGITUD_MAXIMA_CONTRASENA,
            repr=False,
            json_schema_extra={"writeOnly": True},
        ),
    ]

    @model_validator(mode="after")
    def validar_nueva_contrasena(self) -> SolicitudCambioContrasena:
        """Reutiliza exactamente la politica usada por el registro."""

        validar_confirmacion_contrasena(
            self.contrasena_nueva,
            self.confirmacion_contrasena_nueva,
        )
        return self


class RespuestaCambioContrasena(BaseModel):
    """Estado fijo, sin devolver informacion de credenciales o sesiones."""

    model_config = ConfigDict(extra="forbid")

    estado: Literal["contrasena_actualizada"] = "contrasena_actualizada"


__all__ = [
    "RespuestaCambioContrasena",
    "SolicitudCambioContrasena",
]
