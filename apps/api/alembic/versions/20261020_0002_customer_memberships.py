"""Agrega sesiones, compras autenticadas y directorio cliente en tiempo real."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261020_0002"
down_revision = "20261020_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sesiones_clientes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("cuenta_cliente_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "creada_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revocada_en", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "char_length(token_hash) = 64",
            name="ck_sesiones_clientes_hash_sha256",
        ),
        sa.CheckConstraint(
            "expira_en > creada_en",
            name="ck_sesiones_clientes_vigencia",
        ),
        sa.ForeignKeyConstraint(
            ["cuenta_cliente_id"],
            ["cuentas_clientes.id"],
            name="fk_sesiones_clientes_cuenta_cliente",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sesiones_clientes"),
        sa.UniqueConstraint("token_hash", name="uq_sesiones_clientes_token_hash"),
    )
    op.create_index(
        "ix_sesiones_clientes_cuenta_vigencia",
        "sesiones_clientes",
        ["cuenta_cliente_id", "expira_en"],
        postgresql_where=sa.text("revocada_en IS NULL"),
    )

    op.create_table(
        "intentos_checkout_cliente",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cuenta_cliente_id", sa.BigInteger(), nullable=False),
        sa.Column("clave_solicitud", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stripe_idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("checkout_session_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("estado", sa.String(length=24), nullable=False),
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
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "estado IN ('creado', 'abierto', 'confirmado', 'expirado', 'fallido')",
            name="ck_intentos_checkout_cliente_estado",
        ),
        sa.ForeignKeyConstraint(
            ["cuenta_cliente_id"],
            ["cuentas_clientes.id"],
            name="fk_intentos_checkout_cliente_cuenta_cliente",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_intentos_checkout_cliente"),
        sa.UniqueConstraint(
            "cuenta_cliente_id",
            "clave_solicitud",
            name="uq_intentos_checkout_cliente_solicitud",
        ),
        sa.UniqueConstraint(
            "stripe_idempotency_key",
            name="uq_intentos_checkout_cliente_stripe_key",
        ),
        sa.UniqueConstraint(
            "checkout_session_id",
            name="uq_intentos_checkout_cliente_session",
        ),
    )
    op.create_index(
        "uq_intentos_checkout_cliente_activo",
        "intentos_checkout_cliente",
        ["cuenta_cliente_id"],
        unique=True,
        postgresql_where=sa.text("estado IN ('creado', 'abierto')"),
    )
    op.create_index(
        "ix_intentos_checkout_cliente_expira",
        "intentos_checkout_cliente",
        ["expira_en"],
    )

    op.alter_column(
        "clientes",
        "stripe_customer_id",
        existing_type=sa.String(length=255),
        nullable=True,
    )
    op.add_column(
        "clientes",
        sa.Column("cuenta_cliente_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_clientes_cuenta_cliente",
        "clientes",
        "cuentas_clientes",
        ["cuenta_cliente_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_clientes_cuenta_cliente",
        "clientes",
        ["cuenta_cliente_id"],
    )

    op.drop_constraint(
        "ck_eventos_tiempo_real_tipo",
        "eventos_tiempo_real",
        type_="check",
    )
    op.create_check_constraint(
        "ck_eventos_tiempo_real_tipo",
        "eventos_tiempo_real",
        "(recurso_tipo = 'operador' AND "
        "tipo IN ('operador.creado', 'operador.actualizado')) OR "
        "(recurso_tipo = 'cajon' AND tipo = 'cajon.actualizado') OR "
        "(recurso_tipo = 'cliente' AND "
        "tipo IN ('cliente.registrado', 'membresia.actualizada'))",
    )
    op.alter_column(
        "eventos_tiempo_real",
        "recurso_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        postgresql_using="recurso_id::bigint",
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM sesiones_clientes) OR "
            "EXISTS (SELECT 1 FROM intentos_checkout_cliente) OR "
            "EXISTS (SELECT 1 FROM clientes WHERE cuenta_cliente_id IS NOT NULL) "
            "THEN RAISE EXCEPTION 'Hay datos de clientes que "
            "requieren esta migracion'; "
            "END IF; "
            "IF EXISTS (SELECT 1 FROM eventos_tiempo_real "
            "WHERE recurso_tipo = 'cliente') "
            "THEN RAISE EXCEPTION 'El journal contiene eventos de clientes'; "
            "END IF; "
            "IF EXISTS (SELECT 1 FROM eventos_tiempo_real "
            "WHERE recurso_id > 2147483647 OR recurso_id < -2147483648) "
            "THEN RAISE EXCEPTION 'Hay ids que no caben en integer'; "
            "END IF; END $$"
        )
    )

    op.alter_column(
        "eventos_tiempo_real",
        "recurso_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        postgresql_using="recurso_id::integer",
    )
    op.drop_constraint(
        "ck_eventos_tiempo_real_tipo",
        "eventos_tiempo_real",
        type_="check",
    )
    op.create_check_constraint(
        "ck_eventos_tiempo_real_tipo",
        "eventos_tiempo_real",
        "(recurso_tipo = 'operador' AND "
        "tipo IN ('operador.creado', 'operador.actualizado')) OR "
        "(recurso_tipo = 'cajon' AND tipo = 'cajon.actualizado')",
    )

    op.drop_constraint(
        "uq_clientes_cuenta_cliente",
        "clientes",
        type_="unique",
    )
    op.drop_constraint(
        "fk_clientes_cuenta_cliente",
        "clientes",
        type_="foreignkey",
    )
    op.drop_column("clientes", "cuenta_cliente_id")
    op.alter_column(
        "clientes",
        "stripe_customer_id",
        existing_type=sa.String(length=255),
        nullable=False,
    )

    op.drop_index(
        "ix_intentos_checkout_cliente_expira",
        table_name="intentos_checkout_cliente",
    )
    op.drop_index(
        "uq_intentos_checkout_cliente_activo",
        table_name="intentos_checkout_cliente",
    )
    op.drop_table("intentos_checkout_cliente")
    op.drop_index(
        "ix_sesiones_clientes_cuenta_vigencia",
        table_name="sesiones_clientes",
    )
    op.drop_table("sesiones_clientes")
