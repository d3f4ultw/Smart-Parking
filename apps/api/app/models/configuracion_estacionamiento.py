"""Modelos de modalidad vigente e historial de estacionamiento."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ConfiguracionEstacionamiento(Base):
    """Fila singleton con la modalidad elegida explicitamente."""

    __tablename__ = "configuracion_estacionamiento"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_configuracion_estacionamiento_singleton"),
        CheckConstraint(
            "modalidad IN ('PRIVADO', 'PUBLICO', 'MIXTO')",
            name="ck_configuracion_estacionamiento_modalidad",
        ),
        CheckConstraint(
            "revision > 0",
            name="ck_configuracion_estacionamiento_revision_positiva",
        ),
        CheckConstraint(
            "revision_horarios > 0",
            name="ck_configuracion_estacionamiento_revision_horarios_positiva",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    modalidad: Mapped[str] = mapped_column(String(8), nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    revision_horarios: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=1,
        server_default="1",
    )
    acceso_suspendido: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=false(),
    )
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class HistorialModalidadEstacionamiento(Base):
    """Cambio confirmado de modalidad, sin atribucion a una persona."""

    __tablename__ = "historial_modalidad_estacionamiento"
    __table_args__ = (
        UniqueConstraint(
            "configuracion_id",
            "revision",
            name="uq_historial_modalidad_config_revision",
        ),
        CheckConstraint(
            "revision > 0",
            name="ck_historial_modalidad_revision_positiva",
        ),
        CheckConstraint(
            "modalidad_nueva IN ('PRIVADO', 'PUBLICO', 'MIXTO')",
            name="ck_historial_modalidad_nueva",
        ),
        CheckConstraint(
            "(modalidad_anterior IS NULL AND revision = 1) OR "
            "(modalidad_anterior IS NOT NULL AND "
            "modalidad_anterior IN ('PRIVADO', 'PUBLICO', 'MIXTO') AND "
            "modalidad_anterior <> modalidad_nueva AND revision > 1)",
            name="ck_historial_modalidad_secuencia",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    configuracion_id: Mapped[int] = mapped_column(
        ForeignKey(
            "configuracion_estacionamiento.id",
            name="fk_historial_modalidad_configuracion",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    modalidad_anterior: Mapped[str | None] = mapped_column(String(8))
    modalidad_nueva: Mapped[str] = mapped_column(String(8), nullable=False)
    cambiado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
