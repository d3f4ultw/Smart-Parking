"""Contratos HTTP para autenticacion y sesion de clientes."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class SolicitudLoginCliente(BaseModel):
    """Credenciales recibidas para autenticar una cuenta de cliente."""

    model_config = ConfigDict(extra="forbid")

    correo: Annotated[str, Field(min_length=1, max_length=320, repr=False)]
    contrasena: Annotated[str, Field(min_length=1, max_length=128, repr=False)]


class RespuestaLoginCliente(BaseModel):
    """Respuesta mínima; la credencial se entrega solo mediante cookie."""

    estado: Literal["credenciales_validas"]


class RespuestaLogoutCliente(BaseModel):
    """Respuesta idempotente del cierre de sesión del cliente."""

    estado: Literal["sesion_cerrada"]


class ClienteSesion(BaseModel):
    """Datos de perfil mínimos expuestos a la propia cuenta autenticada."""

    nombre: str
    apellido_paterno: str
    apellido_materno: str | None
    correo: str
    correo_verificado: bool


class RespuestaSesionCliente(BaseModel):
    """Estado de autenticación y datos públicos de la sesión cliente."""

    autenticado: Literal[True]
    cliente: ClienteSesion


__all__ = [
    "ClienteSesion",
    "RespuestaLoginCliente",
    "RespuestaLogoutCliente",
    "RespuestaSesionCliente",
    "SolicitudLoginCliente",
]
