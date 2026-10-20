"""Esquemas estrictos para el registro publico de clientes."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.seguridad.correos import CorreoInvalidoError, normalizar_correo


class SolicitudRegistroCliente(BaseModel):
    """Datos permitidos para crear una identidad de cliente."""

    model_config = ConfigDict(extra="forbid")

    nombre: Annotated[str, Field(strict=True, min_length=1, max_length=100)]
    apellido_paterno: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=100),
    ]
    apellido_materno: Annotated[
        str | None,
        Field(strict=True, max_length=100),
    ] = None
    correo: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=320, repr=False),
    ]
    contrasena: Annotated[
        str,
        Field(strict=True, min_length=10, max_length=128, repr=False),
    ]

    @field_validator("nombre", "apellido_paterno", mode="before")
    @classmethod
    def recortar_nombre(cls, valor: object) -> object:
        """Recorta espacios exteriores y evita nombres vacios."""

        return valor.strip() if isinstance(valor, str) else valor

    @field_validator("apellido_materno", mode="before")
    @classmethod
    def normalizar_apellido_materno(cls, valor: object) -> object:
        """Convierte un apellido opcional vacio en ausencia de dato."""

        if isinstance(valor, str):
            return valor.strip() or None
        return valor

    @field_validator("correo")
    @classmethod
    def validar_correo(cls, valor: str) -> str:
        """Guarda el correo canonico usado por las demas rutas de autenticacion."""

        try:
            return normalizar_correo(valor)
        except CorreoInvalidoError as error:
            raise ValueError("El correo no es valido.") from error


class RespuestaRegistroCliente(BaseModel):
    """Respuesta publica fija para solicitudes nuevas o repetidas."""

    model_config = ConfigDict(extra="forbid")

    estado: Literal["solicitud_recibida"] = "solicitud_recibida"


__all__ = ["RespuestaRegistroCliente", "SolicitudRegistroCliente"]
