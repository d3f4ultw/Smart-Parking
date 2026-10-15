"""Configuracion canonica y recibos idempotentes del proceso Vision."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class VisionConfiguration(Base):
    """Revision, allocator y liveness del unico publicador Vision vigente."""

    __tablename__ = "vision_configuration"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_vision_configuration_singleton"),
        CheckConstraint("revision >= 0", name="ck_vision_configuration_revision"),
        CheckConstraint(
            "next_c_number > 0",
            name="ck_vision_configuration_next_c_number",
        ),
        CheckConstraint("last_sequence >= 0", name="ck_vision_configuration_sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    next_c_number: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("1"),
    )
    current_session_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_observation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )


class VisionRequest(Base):
    """Respuesta retenida para repetir de forma segura una solicitud Vision."""

    __tablename__ = "vision_requests"
    __table_args__ = (
        CheckConstraint(
            "char_length(request_digest) = 64",
            name="ck_vision_requests_digest_length",
        ),
    )

    request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    request_type: Mapped[str] = mapped_column(String(24), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


__all__ = ["VisionConfiguration", "VisionRequest"]
