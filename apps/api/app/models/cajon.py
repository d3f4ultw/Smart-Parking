"""Modelo persistido de los cajones de estacionamiento."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Identity,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EstadoFisicoCajon(StrEnum):
    """Estados reportados por el sensor fisico."""

    DESCONOCIDO = "DESCONOCIDO"
    LIBRE = "LIBRE"
    OCUPADO = "OCUPADO"


class EstadoOperativoCajon(StrEnum):
    """Estados administrados por personal autorizado."""

    DISPONIBLE = "DISPONIBLE"
    MANTENIMIENTO = "MANTENIMIENTO"
    FUERA_DE_SERVICIO = "FUERA_DE_SERVICIO"


class EstadoEfectivoCajon(StrEnum):
    """Disponibilidad derivada sin persistir una bandera redundante."""

    DESCONOCIDO = "DESCONOCIDO"
    LIBRE = "LIBRE"
    OCUPADO = "OCUPADO"
    NO_DISPONIBLE = "NO_DISPONIBLE"


class Cajon(Base):
    """Estado fisico y operativo independiente de un cajon."""

    __tablename__ = "cajones"
    __table_args__ = (
        CheckConstraint("numero > 0", name="ck_cajones_numero_positivo"),
        UniqueConstraint("numero", name="uq_cajones_numero"),
        CheckConstraint(
            "estado_fisico IN ('DESCONOCIDO', 'LIBRE', 'OCUPADO')",
            name="ck_cajones_estado_fisico",
        ),
        CheckConstraint(
            "estado_operativo IN ('DISPONIBLE', 'MANTENIMIENTO', 'FUERA_DE_SERVICIO')",
            name="ck_cajones_estado_operativo",
        ),
        CheckConstraint(
            "(estado_operativo = 'DISPONIBLE' AND motivo_operativo IS NULL) OR "
            "(estado_operativo IN ('MANTENIMIENTO', 'FUERA_DE_SERVICIO') AND "
            "(motivo_operativo IS NULL OR "
            "motivo_operativo ~ '[^[:space:]]'))",
            name="ck_cajones_motivo_operativo",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    estado_fisico: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=EstadoFisicoCajon.DESCONOCIDO.value,
        server_default=text("'DESCONOCIDO'"),
    )
    estado_operativo: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=EstadoOperativoCajon.DISPONIBLE.value,
        server_default=text("'DISPONIBLE'"),
    )
    motivo_operativo: Mapped[str | None] = mapped_column(String(250))
    estado_fisico_actualizado_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    estado_operativo_actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


__all__ = [
    "Cajon",
    "EstadoEfectivoCajon",
    "EstadoFisicoCajon",
    "EstadoOperativoCajon",
]
