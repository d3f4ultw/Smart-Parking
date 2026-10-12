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


class InscripcionPropietario(Base):
    """Conserva solo hashes y limites del enlace de alta de OWNER."""

    __tablename__ = "inscripciones_propietario"
    __table_args__ = (
        Index("uq_inscripciones_propietario_correo", "correo", unique=True),
        Index("uq_inscripciones_propietario_token_hash", "token_hash", unique=True),
        Index(
            "uq_inscripciones_propietario_desafio_hash",
            "desafio_hash",
            unique=True,
        ),
        CheckConstraint(
            "(desafio_hash IS NULL AND desafio_expira_en IS NULL) OR "
            "(desafio_hash IS NOT NULL AND desafio_expira_en IS NOT NULL)",
            name="ck_inscripciones_propietario_desafio_completo",
        ),
        CheckConstraint(
            "rol_anterior IS NULL OR rol_anterior IN ('ADMIN', 'OPERADOR')",
            name="ck_inscripciones_propietario_rol_anterior",
        ),
        CheckConstraint(
            "reenviados BETWEEN 0 AND 3",
            name="ck_inscripciones_propietario_reenvios",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    correo: Mapped[str] = mapped_column(String(320), nullable=False)
    usuario_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "usuarios.id",
            name="fk_inscripciones_propietario_usuario_id_usuarios",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    rol_anterior: Mapped[str | None] = mapped_column(String(32))
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    desafio_hash: Mapped[str | None] = mapped_column(String(64))
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    proceso_expira_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    desafio_expira_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ultimo_envio_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    reenviados: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    canjeado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumido_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
