"""Sesiones opacas y revocables de cuentas de cliente."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SesionCliente(Base):
    """Conserva el hash de un token y su vigencia para una cuenta cliente."""

    __tablename__ = "sesiones_clientes"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_sesiones_clientes_token_hash"),
        CheckConstraint(
            "char_length(token_hash) = 64",
            name="ck_sesiones_clientes_hash_sha256",
        ),
        CheckConstraint("expira_en > creada_en", name="ck_sesiones_clientes_vigencia"),
        Index(
            "ix_sesiones_clientes_cuenta_vigencia",
            "cuenta_cliente_id",
            "expira_en",
            postgresql_where=text("revocada_en IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    cuenta_cliente_id: Mapped[int] = mapped_column(
        ForeignKey(
            "cuentas_clientes.id",
            name="fk_sesiones_clientes_cuenta_cliente",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    creada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revocada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = ["SesionCliente"]
