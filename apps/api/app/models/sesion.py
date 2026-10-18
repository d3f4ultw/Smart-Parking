from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Sesion(Base):
    __tablename__ = "sesiones"
    __table_args__ = (
        Index("ix_sesiones_usuario_id", "usuario_id"),
        Index("ix_sesiones_token_hash", "token_hash", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "usuarios.id",
            name="fk_sesiones_usuario_id_usuarios",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revocado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vision_autorizada: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
