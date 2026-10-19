"""Turnos compartidos que pueden asignarse a empleados en el futuro."""

from __future__ import annotations

from datetime import datetime, time
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CodigoTurnoEmpleado(StrEnum):
    """Identificadores fijos que podrá guardar una asignación futura."""

    MATUTINO = "MATUTINO"
    VESPERTINO = "VESPERTINO"
    NOCTURNO = "NOCTURNO"
    SIN_RESTRICCION = "SIN_RESTRICCION"


CODIGOS_TURNOS_EMPLEADOS = tuple(CodigoTurnoEmpleado)
NOMBRES_TURNOS_EMPLEADOS = {
    CodigoTurnoEmpleado.MATUTINO: "Matutino",
    CodigoTurnoEmpleado.VESPERTINO: "Vespertino",
    CodigoTurnoEmpleado.NOCTURNO: "Nocturno",
    CodigoTurnoEmpleado.SIN_RESTRICCION: "Sin restricción",
}


class TurnoEmpleado(Base):
    """Horario único compartido por todos los empleados que lo asignen."""

    __tablename__ = "turnos_empleados"
    __table_args__ = (
        UniqueConstraint(
            "configuracion_estacionamiento_id",
            "codigo",
            name="uq_turnos_empleados_configuracion_codigo",
        ),
        UniqueConstraint(
            "configuracion_estacionamiento_id",
            "id",
            name="uq_turnos_empleados_configuracion_id_id",
        ),
        CheckConstraint(
            "codigo IN ('MATUTINO', 'VESPERTINO', 'NOCTURNO', 'SIN_RESTRICCION')",
            name="ck_turnos_empleados_codigo",
        ),
        CheckConstraint(
            "(codigo = 'SIN_RESTRICCION' AND hora_inicio IS NULL AND "
            "hora_fin IS NULL) OR (codigo <> 'SIN_RESTRICCION' AND "
            "((hora_inicio IS NULL AND hora_fin IS NULL) OR "
            "(hora_inicio IS NOT NULL AND hora_fin IS NOT NULL AND "
            "hora_inicio <> hora_fin)))",
            name="ck_turnos_empleados_horas_validas",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    configuracion_estacionamiento_id: Mapped[int] = mapped_column(
        ForeignKey(
            "configuracion_estacionamiento.id",
            name="fk_turnos_empleados_configuracion",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    codigo: Mapped[str] = mapped_column(String(24), nullable=False)
    hora_inicio: Mapped[time | None] = mapped_column(Time(timezone=False))
    hora_fin: Mapped[time | None] = mapped_column(Time(timezone=False))
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


__all__ = [
    "CODIGOS_TURNOS_EMPLEADOS",
    "NOMBRES_TURNOS_EMPLEADOS",
    "CodigoTurnoEmpleado",
    "TurnoEmpleado",
]
