"""Additive customer, membership, invoice and Stripe event tables."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261019_0002"
down_revision = "20261019_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clientes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=False),
        sa.Column("nombre_completo", sa.String(length=255), nullable=True),
        sa.Column("correo_privado", sa.String(length=320), nullable=True),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "nombre_completo IS NULL OR char_length(btrim(nombre_completo)) > 0",
            name="ck_clientes_nombre_no_vacio",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_clientes"),
        sa.UniqueConstraint("stripe_customer_id", name="uq_clientes_stripe_customer"),
    )
    op.create_table(
        "membresias",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("cliente_id", sa.BigInteger(), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=False),
        sa.Column("stripe_price_id", sa.String(length=255), nullable=False),
        sa.Column("nombre_plan", sa.String(length=255), nullable=False),
        sa.Column("monto_centavos", sa.BigInteger(), nullable=False),
        sa.Column("moneda", sa.String(length=3), nullable=False),
        sa.Column("intervalo", sa.String(length=16), nullable=False),
        sa.Column("intervalo_cantidad", sa.Integer(), nullable=False),
        sa.Column("estado_stripe", sa.String(length=32), nullable=False),
        sa.Column(
            "cancelacion_programada",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("fecha_inicio", sa.DateTime(timezone=True), nullable=True),
        sa.Column("periodo_actual_inicio", sa.DateTime(timezone=True), nullable=True),
        sa.Column("periodo_actual_fin", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "creada_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "actualizada_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "monto_centavos >= 0",
            name="ck_membresias_monto_no_negativo",
        ),
        sa.CheckConstraint(
            "estado_stripe IN ('incomplete', 'incomplete_expired', 'trialing', "
            "'active', 'past_due', 'canceled', 'unpaid', 'paused')",
            name="ck_membresias_estado_stripe",
        ),
        sa.CheckConstraint("char_length(moneda) = 3", name="ck_membresias_moneda_iso"),
        sa.ForeignKeyConstraint(
            ["cliente_id"],
            ["clientes.id"],
            name="fk_membresias_cliente",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_membresias"),
        sa.UniqueConstraint(
            "stripe_subscription_id",
            name="uq_membresias_stripe_subscription",
        ),
    )
    op.create_index(
        "uq_membresias_cliente_activa",
        "membresias",
        ["cliente_id"],
        unique=True,
        postgresql_where=sa.text(
            "estado_stripe IN ('active', 'past_due', 'unpaid', 'paused')"
        ),
    )
    op.create_table(
        "membresia_facturas",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("membresia_id", sa.BigInteger(), nullable=True),
        sa.Column("stripe_invoice_id", sa.String(length=255), nullable=False),
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("estado", sa.String(length=24), nullable=False),
        sa.Column("motivo_cobro", sa.String(length=64), nullable=True),
        sa.Column("monto_pagado", sa.BigInteger(), nullable=False),
        sa.Column("monto_pendiente", sa.BigInteger(), nullable=False),
        sa.Column("moneda", sa.String(length=3), nullable=False),
        sa.Column("ultimo_fallo_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pagada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "creada_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "estado IN ('draft', 'open', 'paid', 'uncollectible', 'void')",
            name="ck_membresia_facturas_estado",
        ),
        sa.CheckConstraint(
            "monto_pagado >= 0 AND monto_pendiente >= 0",
            name="ck_membresia_facturas_montos_no_negativos",
        ),
        sa.CheckConstraint(
            "char_length(moneda) = 3",
            name="ck_membresia_facturas_moneda",
        ),
        sa.ForeignKeyConstraint(
            ["membresia_id"],
            ["membresias.id"],
            name="fk_membresia_facturas_membresia",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_membresia_facturas"),
        sa.UniqueConstraint(
            "stripe_invoice_id",
            name="uq_membresia_facturas_invoice",
        ),
    )
    op.create_table(
        "stripe_eventos",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("stripe_event_id", sa.String(length=255), nullable=False),
        sa.Column("tipo", sa.String(length=128), nullable=False),
        sa.Column("livemode", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("objeto_id", sa.String(length=255), nullable=True),
        sa.Column("creado_en_stripe", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "recibido_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("procesado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("intentos", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "intentos > 0",
            name="ck_stripe_eventos_intentos_positivos",
        ),
        sa.CheckConstraint("livemode = false", name="ck_stripe_eventos_sandbox"),
        sa.PrimaryKeyConstraint("id", name="pk_stripe_eventos"),
        sa.UniqueConstraint("stripe_event_id", name="uq_stripe_eventos_event_id"),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM clientes) "
            "OR EXISTS (SELECT 1 FROM membresias) "
            "OR EXISTS (SELECT 1 FROM membresia_facturas) "
            "OR EXISTS (SELECT 1 FROM stripe_eventos) THEN "
            "RAISE EXCEPTION 'No se pueden retirar datos de membresias'; "
            "END IF; END; $$"
        )
    )
    op.drop_table("stripe_eventos")
    op.drop_table("membresia_facturas")
    op.drop_index("uq_membresias_cliente_activa", table_name="membresias")
    op.drop_table("membresias")
    op.drop_table("clientes")
