"""Intentos persistentes para proteger compras autenticadas de membresias."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class IntentoCheckoutCliente(Base):
    """Vincula una cuenta con un Checkout creado por el servidor."""

    __tablename__ = "intentos_checkout_cliente"
    __table_args__ = (
        UniqueConstraint(
            "cuenta_cliente_id",
            "clave_solicitud",
            name="uq_intentos_checkout_cliente_solicitud",
        ),
        UniqueConstraint(
            "stripe_idempotency_key",
            name="uq_intentos_checkout_cliente_stripe_key",
        ),
        UniqueConstraint(
            "checkout_session_id",
            name="uq_intentos_checkout_cliente_session",
        ),
        CheckConstraint(
            "estado IN ('creado', 'abierto', 'confirmado', 'expirado', 'fallido')",
            name="ck_intentos_checkout_cliente_estado",
        ),
        Index(
            "uq_intentos_checkout_cliente_activo",
            "cuenta_cliente_id",
            unique=True,
            postgresql_where=text("estado IN ('creado', 'abierto')"),
        ),
        Index("ix_intentos_checkout_cliente_expira", "expira_en"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    cuenta_cliente_id: Mapped[int] = mapped_column(
        ForeignKey(
            "cuentas_clientes.id",
            name="fk_intentos_checkout_cliente_cuenta_cliente",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    clave_solicitud: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    stripe_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    checkout_session_id: Mapped[str | None] = mapped_column(String(255))
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255))
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255))
    estado: Mapped[str] = mapped_column(String(24), nullable=False, default="creado")
    creada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    actualizada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["IntentoCheckoutCliente"]
