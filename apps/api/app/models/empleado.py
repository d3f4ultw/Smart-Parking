"""Entidad de personal separada de las cuentas de acceso a la aplicacion."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Empleado(Base):
    """Guarda la identidad laboral y referencia un turno compartido."""

    __tablename__ = "empleados"
    __table_args__ = (
        UniqueConstraint(
            "configuracion_estacionamiento_id",
            "id",
            name="uq_empleados_configuracion_id_id",
        ),
        UniqueConstraint("clave_solicitud", name="uq_empleados_clave_solicitud"),
        ForeignKeyConstraint(
            ["configuracion_estacionamiento_id", "turno_empleado_id"],
            [
                "turnos_empleados.configuracion_estacionamiento_id",
                "turnos_empleados.id",
            ],
            name="fk_empleados_turno_configuracion",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "char_length(btrim(nombres)) > 0",
            name="ck_empleados_nombres_no_vacios",
        ),
        CheckConstraint(
            "char_length(btrim(apellido_paterno)) > 0",
            name="ck_empleados_apellido_paterno_no_vacio",
        ),
        CheckConstraint(
            "apellido_materno IS NULL OR char_length(btrim(apellido_materno)) > 0",
            name="ck_empleados_apellido_materno_no_vacio",
        ),
        CheckConstraint("revision_estado > 0", name="ck_empleados_revision_positiva"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    configuracion_estacionamiento_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    turno_empleado_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    nombres: Mapped[str] = mapped_column(String(100), nullable=False)
    apellido_paterno: Mapped[str] = mapped_column(String(100), nullable=False)
    apellido_materno: Mapped[str | None] = mapped_column(String(100))
    esta_activo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    revision_estado: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=1,
        server_default="1",
    )
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    clave_solicitud: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


__all__ = ["Empleado"]
