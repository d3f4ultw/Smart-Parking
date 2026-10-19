"""Contratos HTTP para los horarios centralizados de empleados."""

import re

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.models import CodigoTurnoEmpleado

_PATRON_HORA = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


class IntervaloTurnoSolicitud(BaseModel):
    """Par de horas local o turno pendiente sin horas."""

    model_config = ConfigDict(extra="forbid")

    hora_inicio: str | None
    hora_fin: str | None

    @field_validator("hora_inicio", "hora_fin")
    @classmethod
    def validar_formato_hora(cls, valor: str | None) -> str | None:
        if valor is not None and _PATRON_HORA.fullmatch(valor) is None:
            raise ValueError("La hora debe usar el formato de 24 horas HH:MM.")
        return valor

    @model_validator(mode="after")
    def validar_par_horas(self) -> IntervaloTurnoSolicitud:
        if (self.hora_inicio is None) != (self.hora_fin is None):
            raise ValueError("El turno requiere ambas horas o ninguna.")
        if self.hora_inicio is not None and self.hora_inicio == self.hora_fin:
            raise ValueError("La hora de inicio y fin deben ser distintas.")
        return self


class TurnosConfigurablesSolicitud(BaseModel):
    """Exige los tres turnos configurables y excluye Sin restricción."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    matutino: IntervaloTurnoSolicitud = Field(alias="MATUTINO")
    vespertino: IntervaloTurnoSolicitud = Field(alias="VESPERTINO")
    nocturno: IntervaloTurnoSolicitud = Field(alias="NOCTURNO")


class SolicitudCambiarHorariosEmpleados(BaseModel):
    """Reemplazo atomico de las horas y la revision leida por la interfaz."""

    model_config = ConfigDict(extra="forbid")

    revision_esperada: int = Field(ge=1, strict=True)
    turnos: TurnosConfigurablesSolicitud


class TurnoEmpleadoRespuesta(BaseModel):
    """Turno compartido; la clave numerica se reserva para asignaciones futuras."""

    id: int
    codigo: CodigoTurnoEmpleado
    nombre: str
    hora_inicio: str | None
    hora_fin: str | None


class RespuestaHorariosEmpleados(BaseModel):
    """Instantanea segura para renderizar y editar los horarios del estacionamiento."""

    revision: int
    zona_horaria: str
    turnos: list[TurnoEmpleadoRespuesta]


__all__ = [
    "RespuestaHorariosEmpleados",
    "SolicitudCambiarHorariosEmpleados",
    "TurnoEmpleadoRespuesta",
    "TurnosConfigurablesSolicitud",
]
