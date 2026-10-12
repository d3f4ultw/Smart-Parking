"""Contratos HTTP aislados para la gestion temporal de OWNER."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SolicitudReclamoGestionPropietario(BaseModel):
    """Recibe el ticket fragmento y el codigo solo durante el primer reclamo."""

    model_config = ConfigDict(extra="forbid")

    ticket: Annotated[str, Field(min_length=32, max_length=128, repr=False)]
    codigo_apareamiento: Annotated[
        str | None,
        Field(default=None, min_length=16, max_length=20, repr=False),
    ] = None


class SolicitudInscripcionGestionPropietario(BaseModel):
    """Recibe el correo cuya verificacion se iniciara de forma explicita."""

    model_config = ConfigDict(extra="forbid")

    correo: Annotated[
        EmailStr,
        Field(min_length=3, max_length=320, repr=False),
    ]


class SolicitudDesvinculacionGestionPropietario(BaseModel):
    """Recibe la credencial administrativa solo para autorizar el envío."""

    model_config = ConfigDict(extra="forbid")

    contrasena_admin: Annotated[
        str,
        Field(min_length=1, max_length=128, repr=False),
    ]


class SolicitudConfirmacionDesvinculacionPropietario(BaseModel):
    """Recibe el token de un solo uso sin incluirlo en repr ni logs."""

    model_config = ConfigDict(extra="forbid")

    token: Annotated[
        str,
        Field(min_length=43, max_length=64, repr=False),
    ]


class RespuestaSesionGestionPropietario(BaseModel):
    """Indica si la cookie aun corresponde a un lease activo."""

    model_config = ConfigDict(extra="forbid")

    activa: bool


class RespuestaInscripcionGestionPropietario(BaseModel):
    """Proyeccion segura del estado persistido de una inscripcion."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    correo: str
    estado: Literal["pendiente", "bloqueado", "expirado", "completado"]
    correo_inicial_enviado: bool
    expira_en: datetime
    proceso_expira_en: datetime
    enlace_vigente: bool
    segundos_proceso: int
    reenviados_usados: int
    reenviados_restantes: int
    proximo_reenvio_en: datetime | None
    segundos_cooldown: int
    reenvio_bloqueado: bool
    motivo_bloqueo: str | None


class ResumenOwnerGestionPropietario(BaseModel):
    """Datos mínimos del OWNER actual para la página temporal autorizada."""

    model_config = ConfigDict(extra="forbid")

    nombre: str
    correo: str


class RespuestaEstadoGestionPropietario(BaseModel):
    """Devuelve el estado minimo del OWNER y los procesos visibles."""

    model_config = ConfigDict(extra="forbid")

    owner_activo: bool
    owner: ResumenOwnerGestionPropietario | None
    desvinculacion_segundos_restantes: int
    inscripciones: list[RespuestaInscripcionGestionPropietario]


class RespuestaSolicitudDesvinculacionPropietario(BaseModel):
    """Confirma que el correo de un solo uso fue aceptado para entrega."""

    model_config = ConfigDict(extra="forbid")

    estado: Literal["confirmacion_enviada"]


class RespuestaConfirmacionDesvinculacionPropietario(BaseModel):
    """Indica que el enlace aplicó la desvinculación de forma atomica."""

    model_config = ConfigDict(extra="forbid")

    estado: Literal["dueno_desvinculado"]


__all__ = [
    "RespuestaConfirmacionDesvinculacionPropietario",
    "RespuestaEstadoGestionPropietario",
    "RespuestaInscripcionGestionPropietario",
    "RespuestaSolicitudDesvinculacionPropietario",
    "RespuestaSesionGestionPropietario",
    "ResumenOwnerGestionPropietario",
    "SolicitudConfirmacionDesvinculacionPropietario",
    "SolicitudDesvinculacionGestionPropietario",
    "SolicitudInscripcionGestionPropietario",
    "SolicitudReclamoGestionPropietario",
]
