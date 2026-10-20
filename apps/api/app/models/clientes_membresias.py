"""Datos privados de clientes, membresias, facturas y eventos Stripe."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Cliente(Base):
    """Identidad canonica del directorio, ligada opcionalmente a Stripe."""

    __tablename__ = "clientes"
    __table_args__ = (
        UniqueConstraint("stripe_customer_id", name="uq_clientes_stripe_customer"),
        UniqueConstraint("cuenta_cliente_id", name="uq_clientes_cuenta_cliente"),
        CheckConstraint(
            "nombre_completo IS NULL OR char_length(btrim(nombre_completo)) > 0",
            name="ck_clientes_nombre_no_vacio",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cuenta_cliente_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "cuentas_clientes.id",
            name="fk_clientes_cuenta_cliente",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    nombre_completo: Mapped[str | None] = mapped_column(String(255))
    correo_privado: Mapped[str | None] = mapped_column(String(320))
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Membresia(Base):
    """Snapshot vigente e historico de una Stripe Subscription."""

    __tablename__ = "membresias"
    __table_args__ = (
        UniqueConstraint(
            "stripe_subscription_id",
            name="uq_membresias_stripe_subscription",
        ),
        CheckConstraint("monto_centavos >= 0", name="ck_membresias_monto_no_negativo"),
        CheckConstraint(
            "estado_stripe IN ('incomplete', 'incomplete_expired', 'trialing', "
            "'active', 'past_due', 'canceled', 'unpaid', 'paused')",
            name="ck_membresias_estado_stripe",
        ),
        CheckConstraint(
            "char_length(moneda) = 3",
            name="ck_membresias_moneda_iso",
        ),
        Index(
            "uq_membresias_cliente_activa",
            "cliente_id",
            unique=True,
            postgresql_where=text(
                "estado_stripe IN ('active', 'past_due', 'unpaid', 'paused')"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    cliente_id: Mapped[int] = mapped_column(
        ForeignKey("clientes.id", name="fk_membresias_cliente", ondelete="RESTRICT"),
        nullable=False,
    )
    stripe_subscription_id: Mapped[str] = mapped_column(String(255), nullable=False)
    stripe_price_id: Mapped[str] = mapped_column(String(255), nullable=False)
    nombre_plan: Mapped[str] = mapped_column(String(255), nullable=False)
    monto_centavos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False)
    intervalo: Mapped[str] = mapped_column(String(16), nullable=False)
    intervalo_cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    estado_stripe: Mapped[str] = mapped_column(String(32), nullable=False)
    cancelacion_programada: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    fecha_inicio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    periodo_actual_inicio: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    periodo_actual_fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class FacturaMembresia(Base):
    """Historial minimo de cobros, incluidos fallos previos a la primera alta."""

    __tablename__ = "membresia_facturas"
    __table_args__ = (
        UniqueConstraint("stripe_invoice_id", name="uq_membresia_facturas_invoice"),
        CheckConstraint(
            "estado IN ('draft', 'open', 'paid', 'uncollectible', 'void')",
            name="ck_membresia_facturas_estado",
        ),
        CheckConstraint(
            "monto_pagado >= 0 AND monto_pendiente >= 0",
            name="ck_membresia_facturas_montos_no_negativos",
        ),
        CheckConstraint(
            "char_length(moneda) = 3",
            name="ck_membresia_facturas_moneda",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    membresia_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "membresias.id",
            name="fk_membresia_facturas_membresia",
            ondelete="RESTRICT",
        )
    )
    stripe_invoice_id: Mapped[str] = mapped_column(String(255), nullable=False)
    stripe_customer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255))
    estado: Mapped[str] = mapped_column(String(24), nullable=False)
    motivo_cobro: Mapped[str | None] = mapped_column(String(64))
    monto_pagado: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    monto_pendiente: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False)
    ultimo_fallo_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pagada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class EventoStripe(Base):
    """Clave durable de idempotencia sin guardar el payload de Stripe."""

    __tablename__ = "stripe_eventos"
    __table_args__ = (
        UniqueConstraint("stripe_event_id", name="uq_stripe_eventos_event_id"),
        CheckConstraint("intentos > 0", name="ck_stripe_eventos_intentos_positivos"),
        CheckConstraint("livemode = false", name="ck_stripe_eventos_sandbox"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    stripe_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tipo: Mapped[str] = mapped_column(String(128), nullable=False)
    livemode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    objeto_id: Mapped[str | None] = mapped_column(String(255))
    creado_en_stripe: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recibido_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    procesado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    intentos: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )


__all__ = ["Cliente", "EventoStripe", "FacturaMembresia", "Membresia"]
