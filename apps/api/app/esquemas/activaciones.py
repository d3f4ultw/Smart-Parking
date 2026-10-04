"""Esquemas HTTP para activaciones de cuenta."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.seguridad.activaciones import LONGITUD_CODIGO


class SolicitudActivacionManual(BaseModel):
    """Credenciales efimeras recibidas para activar una cuenta manual."""

    model_config = ConfigDict(extra="forbid")

    token: Annotated[str, Field(min_length=1, max_length=512, repr=False)]
    codigo: Annotated[
        str,
        Field(
            min_length=LONGITUD_CODIGO,
            max_length=LONGITUD_CODIGO,
            pattern=rf"^[0-9]{{{LONGITUD_CODIGO}}}$",
            repr=False,
        ),
    ]


class SolicitudActivacionTemporal(BaseModel):
    """Credenciales recibidas para reemplazar una contrasena temporal."""

    model_config = ConfigDict(extra="forbid")

    token: Annotated[str, Field(min_length=1, max_length=512, repr=False)]
    codigo: Annotated[
        str,
        Field(
            min_length=LONGITUD_CODIGO,
            max_length=LONGITUD_CODIGO,
            pattern=rf"^[0-9]{{{LONGITUD_CODIGO}}}$",
            repr=False,
        ),
    ]
    contrasena_temporal: Annotated[
        str,
        Field(min_length=1, max_length=128, repr=False),
    ]
    nueva_contrasena: Annotated[
        str,
        Field(min_length=1, max_length=128, repr=False),
    ]
    confirmar_contrasena: Annotated[
        str,
        Field(min_length=1, max_length=128, repr=False),
    ]


class SolicitudReenvioActivacion(BaseModel):
    """Correo recibido para solicitar un reenvio de activacion."""

    model_config = ConfigDict(extra="forbid")

    correo: Annotated[str, Field(min_length=1, max_length=320, repr=False)]


class SolicitudPrevalidacionActivacion(BaseModel):
    """Token recibido para resolver el modo de una activacion."""

    model_config = ConfigDict(extra="forbid")

    token: Annotated[str, Field(min_length=1, max_length=512, repr=False)]


class RespuestaActivacionManual(BaseModel):
    """Respuesta publica y minima de una activacion exitosa."""

    estado: Literal["activada"]


class RespuestaPrevalidacionActivacion(BaseModel):
    """Modo minimo y seguro para renderizar el formulario correcto."""

    modo: Literal["manual", "temporal"]


ESTADO_REENVIO_ACTIVACION = (
    "Si la cuenta requiere activacion, se enviara un nuevo correo"
)


class RespuestaReenvioActivacion(BaseModel):
    """Respuesta generica que evita revelar el estado de una cuenta."""

    estado: Literal["Si la cuenta requiere activacion, se enviara un nuevo correo"]


__all__ = [
    "ESTADO_REENVIO_ACTIVACION",
    "RespuestaActivacionManual",
    "RespuestaPrevalidacionActivacion",
    "RespuestaReenvioActivacion",
    "SolicitudActivacionManual",
    "SolicitudActivacionTemporal",
    "SolicitudPrevalidacionActivacion",
    "SolicitudReenvioActivacion",
]
