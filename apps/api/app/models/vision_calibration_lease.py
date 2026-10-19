"""Lease persistente para excluir editores simultaneos de calibracion Vision."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class VisionCalibrationLease(Base):
    """Conserva el propietario de la unica sesion de calibracion vigente."""

    __tablename__ = "vision_calibration_lease"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_vision_calibration_lease_singleton"),
        CheckConstraint(
            "(owner_session_hash IS NULL AND editor_instance_id IS NULL "
            "AND expires_at IS NULL) OR "
            "(owner_session_hash IS NOT NULL AND editor_instance_id IS NOT NULL "
            "AND expires_at IS NOT NULL)",
            name="ck_vision_calibration_lease_owner_complete",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_session_hash: Mapped[str | None] = mapped_column(String(64))
    editor_instance_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = ["VisionCalibrationLease"]
