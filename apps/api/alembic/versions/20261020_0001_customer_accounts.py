"""Crea identidades de cliente sin vincularlas a la facturacion de Stripe."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261020_0001"
down_revision = "20261019_0002"
branch_labels = None
depends_on = None

NOMBRE_TABLA = "cuentas_clientes"
NOMBRE_INDICE_CORREO = "uq_cuentas_clientes_correo_lower"


def upgrade() -> None:
    op.create_table(
        NOMBRE_TABLA,
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("apellido_paterno", sa.String(length=100), nullable=False),
        sa.Column("apellido_materno", sa.String(length=100), nullable=True),
        sa.Column("correo", sa.String(length=320), nullable=False),
        sa.Column("contrasena_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "correo_verificado",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "esta_activa",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(btrim(nombre)) > 0",
            name="ck_cuentas_clientes_nombre_no_vacio",
        ),
        sa.CheckConstraint(
            "char_length(btrim(apellido_paterno)) > 0",
            name="ck_cuentas_clientes_apellido_paterno_no_vacio",
        ),
        sa.CheckConstraint(
            "apellido_materno IS NULL OR char_length(btrim(apellido_materno)) > 0",
            name="ck_cuentas_clientes_apellido_materno_no_vacio",
        ),
        sa.CheckConstraint(
            "char_length(btrim(correo)) > 0",
            name="ck_cuentas_clientes_correo_no_vacio",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cuentas_clientes"),
    )
    op.create_index(
        NOMBRE_INDICE_CORREO,
        NOMBRE_TABLA,
        [sa.text("lower(correo)")],
        unique=True,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM cuentas_clientes) THEN "
            "RAISE EXCEPTION 'No se pueden retirar cuentas de cliente registradas'; "
            "END IF; END $$"
        )
    )
    op.drop_index(NOMBRE_INDICE_CORREO, table_name=NOMBRE_TABLA)
    op.drop_table(NOMBRE_TABLA)
