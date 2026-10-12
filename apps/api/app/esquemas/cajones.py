"""Esquemas HTTP para consultar y cambiar estados de cajones."""

from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

from app.models.cajon import (
    EstadoEfectivoCajon,
    EstadoFisicoCajon,
    EstadoOperativoCajon,
)


class SolicitudEstadoOperativoCajon(BaseModel):
    """Entrada estricta para cambiar el estado operativo y su motivo."""

    model_config = ConfigDict(extra="forbid")

    estado: EstadoOperativoCajon
    motivo: Annotated[str | None, Field(max_length=250)] = None

    @field_validator("motivo", mode="before")
    @classmethod
    def normalizar_motivo(cls, valor: object) -> object:
        """Recorta espacios y convierte texto vacio en ausencia de motivo."""

        if isinstance(valor, str):
            return valor.strip() or None
        return valor

    @model_validator(mode="after")
    def validar_motivo_por_estado(self) -> SolicitudEstadoOperativoCajon:
        """Impide motivo solo cuando el cajon esta disponible."""

        if self.estado == EstadoOperativoCajon.DISPONIBLE:
            if self.motivo is not None:
                raise ValueError("DISPONIBLE no admite motivo operativo.")
        return self


class SolicitudEstadoFisicoCajon(BaseModel):
    """Entrada estricta del sensor para reportar ocupacion fisica."""

    model_config = ConfigDict(extra="forbid")

    ocupado: StrictBool


class RespuestaCajon(BaseModel):
    """Vista segura de un cajon para personal autorizado."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    numero: int
    estado_fisico: EstadoFisicoCajon
    estado_operativo: EstadoOperativoCajon
    motivo_operativo: str | None
    estado_fisico_actualizado_en: datetime | None
    estado_operativo_actualizado_en: datetime
    creado_en: datetime
    estado_efectivo: EstadoEfectivoCajon


class RespuestaListaCajones(BaseModel):
    """Lista ordenada de cajones y high-water del journal SSE."""

    model_config = ConfigDict(extra="forbid")

    cajones: list[RespuestaCajon]
    cursor_eventos: str


class RespuestaMutacionCajon(RespuestaCajon):
    """Respuesta segura de una mutacion de estado."""

    cambio_aplicado: bool


class RespuestaEstadoFisicoCajon(BaseModel):
    """Confirmacion fisica minima y segura para el dispositivo."""

    model_config = ConfigDict(extra="forbid")

    cajon_id: int
    numero: int
    estado_fisico: EstadoFisicoCajon
    estado_fisico_actualizado_en: datetime | None
    cambio_aplicado: bool


__all__ = [
    "RespuestaCajon",
    "RespuestaEstadoFisicoCajon",
    "RespuestaListaCajones",
    "RespuestaMutacionCajon",
    "SolicitudEstadoFisicoCajon",
    "SolicitudEstadoOperativoCajon",
]
