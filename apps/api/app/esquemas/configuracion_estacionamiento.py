"""Esquemas HTTP para consultar y actualizar la modalidad del estacionamiento."""

from pydantic import BaseModel, ConfigDict, Field

from app.servicios.configuracion_estacionamiento import ModalidadEstacionamiento


class SolicitudCambiarModalidadEstacionamiento(BaseModel):
    """Modalidad solicitada y revisión leída por la interfaz."""

    model_config = ConfigDict(extra="forbid")

    modalidad: ModalidadEstacionamiento
    revision_esperada: int = Field(ge=0, strict=True)


class SolicitudCambiarAccesoEstacionamiento(BaseModel):
    """Estado de acceso solicitado y revision leida por la interfaz."""

    model_config = ConfigDict(extra="forbid")

    acceso_suspendido: bool = Field(strict=True)
    revision_esperada: int = Field(ge=0, strict=True)


class RespuestaModalidadEstacionamiento(BaseModel):
    """Única configuración visible para el OWNER desde la Web."""

    modalidad: ModalidadEstacionamiento | None
    revision: int
    acceso_suspendido: bool


__all__ = [
    "RespuestaModalidadEstacionamiento",
    "SolicitudCambiarAccesoEstacionamiento",
    "SolicitudCambiarModalidadEstacionamiento",
]
