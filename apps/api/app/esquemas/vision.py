"""Contratos estrictos entre Vision y la API de Smart Parking."""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

Coordenada = tuple[float, float]


class EstadoVision(StrEnum):
    LIBRE = "LIBRE"
    OCUPADO = "OCUPADO"


class ObservacionVision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vision_zone_id: UUID
    numero: StrictInt = Field(ge=1)
    estado: EstadoVision


class ZonaVision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vision_zone_id: UUID
    numero: StrictInt | None = Field(default=None, ge=1)
    polygon: Annotated[list[Coordenada], Field(min_length=3, max_length=128)]

    @field_validator("polygon", mode="before")
    @classmethod
    def validar_coordenadas(cls, valor: object) -> object:
        """Rechaza coordenadas no finitas o fuera del espacio normalizado."""

        if not isinstance(valor, list):
            return valor
        for punto in valor:
            if not isinstance(punto, (list, tuple)) or len(punto) != 2:
                raise ValueError("Cada vertice debe contener dos coordenadas.")
            for coordenada in punto:
                if (
                    isinstance(coordenada, bool)
                    or not isinstance(coordenada, (int, float))
                    or not math.isfinite(coordenada)
                    or not 0 <= coordenada <= 1
                ):
                    raise ValueError(
                        "Las coordenadas deben ser finitas y estar entre 0 y 1."
                    )
        return valor


class SolicitudConfiguracionVision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    expected_revision: StrictInt = Field(ge=0)
    zones: list[ZonaVision]

    @model_validator(mode="after")
    def validar_identidades_unicas(self) -> SolicitudConfiguracionVision:
        """Impide zonas duplicadas antes de iniciar una transaccion."""

        ids = [zona.vision_zone_id for zona in self.zones]
        numeros = [zona.numero for zona in self.zones if zona.numero is not None]
        if len(set(ids)) != len(ids) or len(set(numeros)) != len(numeros):
            raise ValueError("La instantanea contiene identidades duplicadas.")
        return self


class RespuestaZonaVision(BaseModel):
    vision_zone_id: UUID
    numero: int
    cajon_id: int
    polygon: list[Coordenada]


class RespuestaConfiguracionVision(BaseModel):
    revision: int
    next_c_number: int
    zones: list[RespuestaZonaVision]


class RespuestaSesionVision(BaseModel):
    session_id: UUID
    revision: int


class SolicitudSecuenciaVision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    session_id: UUID
    sequence: StrictInt = Field(ge=1)


class SolicitudObservacionesVision(SolicitudSecuenciaVision):
    revision: StrictInt = Field(ge=0)
    observations: list[ObservacionVision]

    @model_validator(mode="after")
    def validar_observaciones_unicas(self) -> SolicitudObservacionesVision:
        ids = [item.vision_zone_id for item in self.observations]
        numeros = [item.numero for item in self.observations]
        if len(set(ids)) != len(ids) or len(set(numeros)) != len(numeros):
            raise ValueError("Las observaciones contienen identidades duplicadas.")
        return self


class RespuestaAceptacionVision(BaseModel):
    accepted: bool
    revision: int
    sequence: int
    changed_slots: int = 0


class EstadoServicioVision(BaseModel):
    stale: bool
    last_heartbeat_at: str | None
    last_observation_at: str | None
    stale_after_seconds: int


__all__ = [
    "EstadoServicioVision",
    "EstadoVision",
    "ObservacionVision",
    "RespuestaAceptacionVision",
    "RespuestaConfiguracionVision",
    "RespuestaSesionVision",
    "RespuestaZonaVision",
    "SolicitudConfiguracionVision",
    "SolicitudObservacionesVision",
    "SolicitudSecuenciaVision",
    "ZonaVision",
]
