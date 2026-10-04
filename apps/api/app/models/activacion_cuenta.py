from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ActivacionCuenta(Base):
    __tablename__ = "activaciones_cuenta"
    __table_args__ = (
        Index("ix_activaciones_cuenta_usuario_id", "usuario_id"),
        Index("ix_activaciones_cuenta_token_hash", "token_hash", unique=True),
        Index("ix_activaciones_cuenta_desafio_hash", "desafio_hash", unique=True),
        CheckConstraint(
            "(desafio_hash IS NULL AND desafio_expira_en IS NULL) OR "
            "(desafio_hash IS NOT NULL AND desafio_expira_en IS NOT NULL)",
            name="ck_activaciones_cuenta_desafio_completo",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "usuarios.id",
            name="fk_activaciones_cuenta_usuario_id_usuarios",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    codigo_hash: Mapped[str | None] = mapped_column(String(255))
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumido_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    desafio_hash: Mapped[str | None] = mapped_column(String(255))
    desafio_expira_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ultimo_reenvio_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
