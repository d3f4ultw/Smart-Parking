"""Conserva hashes y auditoria no secreta de enlaces de desvinculacion OWNER."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DesvinculacionPropietario(Base):
    """Vincula un token de un solo uso con una cuenta y perfil OWNER concretos."""

    __tablename__ = "desvinculaciones_propietario"
    __table_args__ = (
        CheckConstraint(
            "emitida_en < expira_en",
            name="ck_desvinculaciones_propietario_vigencia",
        ),
        CheckConstraint(
            "consumida_en IS NULL OR invalidada_en IS NULL",
            name="ck_desvinculaciones_propietario_estado_final",
        ),
        Index(
            "uq_desvinculaciones_propietario_token_hash",
            "token_hash",
            unique=True,
        ),
        Index(
            "ix_desvinculaciones_propietario_usuario_emitida",
            "usuario_id",
            "emitida_en",
        ),
        Index(
            "uq_desvinculaciones_propietario_pendiente",
            "usuario_id",
            unique=True,
            postgresql_where=text(
                "consumida_en IS NULL AND invalidada_en IS NULL"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey(
            "usuarios.id",
            name="fk_desvinculaciones_propietario_usuario_id_usuarios",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    cuenta_propietario_id: Mapped[int] = mapped_column(
        ForeignKey(
            "cuentas_propietario.id",
            name="fk_desvinculaciones_propietario_cuenta_id_cuentas_propietario",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    emitida_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expira_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    consumida_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

