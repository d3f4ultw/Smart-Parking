"""Esquemas HTTP para autenticacion de cuentas de Smart Parking."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class SolicitudLogin(BaseModel):
    """Credenciales recibidas para validar el acceso de una cuenta."""

    model_config = ConfigDict(extra="forbid")

    correo: Annotated[str, Field(min_length=1, max_length=320, repr=False)]
    contrasena: Annotated[str, Field(min_length=1, max_length=128, repr=False)]


class RespuestaLogin(BaseModel):
    """Respuesta mínima de login con el rol persistido; el token va en cookie."""

    estado: Literal["credenciales_validas"]
    rol: Literal["ADMIN", "OPERADOR"]


class RespuestaLogout(BaseModel):
    """Respuesta mínima de un cierre de sesión aceptado."""

    estado: Literal["sesion_cerrada"]


class UsuarioSesion(BaseModel):
    """Datos seguros del usuario asociado con la sesión actual."""

    nombre: str | None
    apellido_paterno: str | None
    apellido_materno: str | None
    correo: str
    rol: Literal["ADMIN", "OPERADOR"]


class RespuestaSesionActual(BaseModel):
    """Respuesta mínima de una sesión vigente de cualquier rol permitido."""

    autenticado: Literal[True]
    usuario: UsuarioSesion


__all__ = [
    "RespuestaLogin",
    "RespuestaLogout",
    "RespuestaSesionActual",
    "SolicitudLogin",
    "UsuarioSesion",
]
