"""Contratos estrictos entre Vision y la API de Smart Parking."""

from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
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
    polygon: Annotated[list[Coordenada], Field(min_length=4, max_length=128)]

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


class SolicitudLeaseCalibracionVision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    editor_instance_id: UUID


class RespuestaEstadoLeaseCalibracionVision(BaseModel):
    available: bool
    lease_duration_seconds: StrictInt = Field(gt=0)


class RespuestaLeaseCalibracionVision(BaseModel):
    acquired: bool = True
    lease_duration_seconds: StrictInt = Field(gt=0)


class RespuestaLiberacionLeaseCalibracionVision(BaseModel):
    released: bool


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


class SolicitudAutorizacionVision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contrasena_admin: Annotated[StrictStr, Field(min_length=1, max_length=128)]


class RespuestaAutorizacionVision(BaseModel):
    authorized: bool


class EstadoZonaRuntimeVision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numero: StrictInt = Field(ge=1)
    estado: Annotated[
        StrictStr,
        Field(pattern=r"^(DESCONOCIDO|LIBRE|CANDIDATO_OCUPADO|OCUPADO)$"),
    ]


class SolicitudEstadoRuntimeVision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    revision: StrictInt = Field(ge=0)
    sequence: StrictInt = Field(ge=1)
    mode: Annotated[StrictStr, Field(pattern=r"^(simulation|camera)$")]
    source_connected: StrictBool
    processing: StrictBool
    source_fps: Annotated[StrictFloat, Field(ge=0, le=120)] = 0.0
    inference_fps: Annotated[StrictFloat, Field(ge=0, le=120)] = 0.0
    zone_states: list[EstadoZonaRuntimeVision] = Field(
        default_factory=list, max_length=256
    )
    error_code: Annotated[
        StrictStr | None,
        Field(
            pattern=r"^(SOURCE_UNAVAILABLE|MODEL_UNAVAILABLE|API_UNAVAILABLE|FRAME_INVALID)$"
        ),
    ] = None


class EstadoVisualizadorMonitoreoVision(BaseModel):
    diagnostic_id: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{32}$")]
    stream_type: Literal["raw", "annotated"]
    reserved_at: datetime
    connection_age_seconds: Annotated[StrictFloat, Field(ge=0)]
    last_emitted_sequence: StrictInt | None = Field(default=None, ge=1)
    last_emitted_at: datetime | None = None
    jpeg_parts_emitted: StrictInt = Field(ge=0)
    jpeg_bytes_emitted: StrictInt = Field(ge=0)
    released_at: datetime | None = None
    release_reason: StrictStr | None = Field(default=None, max_length=64)


class RespuestaEstadoMonitoreoVision(BaseModel):
    mode: str
    source_connected: bool
    processing: bool
    source_fps: float = 0.0
    inference_fps: float = 0.0
    zone_states: list[EstadoZonaRuntimeVision] = Field(default_factory=list)
    source_sequence: int = 0
    annotated_sequence: int = 0
    configuration_revision: int = Field(ge=0)
    applied_revision: int | None = Field(default=None, ge=0)
    active_viewers: int = Field(default=0, ge=0)
    active_viewer_details: list[EstadoVisualizadorMonitoreoVision] = Field(
        default_factory=list, max_length=4
    )
    recent_viewer_releases: list[EstadoVisualizadorMonitoreoVision] = Field(
        default_factory=list, max_length=32
    )
    frame_fresh: bool
    annotated_frame_fresh: bool
    frame_age_seconds: float | None
    annotated_frame_age_seconds: float | None
    last_frame_at: datetime | None
    last_annotated_frame_at: datetime | None
    error_code: str | None
    zones_count: int


__all__ = [
    "EstadoServicioVision",
    "EstadoVision",
    "RespuestaAutorizacionVision",
    "RespuestaEstadoMonitoreoVision",
    "EstadoVisualizadorMonitoreoVision",
    "ObservacionVision",
    "RespuestaAceptacionVision",
    "RespuestaConfiguracionVision",
    "RespuestaSesionVision",
    "RespuestaZonaVision",
    "SolicitudConfiguracionVision",
    "SolicitudAutorizacionVision",
    "SolicitudObservacionesVision",
    "SolicitudSecuenciaVision",
    "SolicitudEstadoRuntimeVision",
    "ZonaVision",
]
