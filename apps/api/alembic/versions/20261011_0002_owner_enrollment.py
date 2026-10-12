"""Add OWNER profile and expiring enrollment state."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261011_0002"
down_revision: str | None = "20261011_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Adds empty tables; existing users and credentials remain untouched."""

    op.create_table(
        "cuentas_propietario",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("contrasena_admin_hash", sa.String(length=255), nullable=False),
        sa.Column("rol_anterior", sa.String(length=32), nullable=True),
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
            "rol_anterior IS NULL OR rol_anterior IN ('ADMIN', 'OPERADOR')",
            name="ck_cuentas_propietario_rol_anterior",
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name="fk_cuentas_propietario_usuario_id_usuarios",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_cuentas_propietario_usuario_id",
        "cuentas_propietario",
        ["usuario_id"],
        unique=True,
    )

    op.create_table(
        "inscripciones_propietario",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("correo", sa.String(length=320), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("rol_anterior", sa.String(length=32), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("desafio_hash", sa.String(length=64), nullable=True),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("desafio_expira_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_envio_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reenviados", sa.Integer(), server_default="0", nullable=False),
        sa.Column("canjeado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumido_en", sa.DateTime(timezone=True), nullable=True),
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
            "(desafio_hash IS NULL AND desafio_expira_en IS NULL) OR "
            "(desafio_hash IS NOT NULL AND desafio_expira_en IS NOT NULL)",
            name="ck_inscripciones_propietario_desafio_completo",
        ),
        sa.CheckConstraint(
            "rol_anterior IS NULL OR rol_anterior IN ('ADMIN', 'OPERADOR')",
            name="ck_inscripciones_propietario_rol_anterior",
        ),
        sa.CheckConstraint(
            "reenviados BETWEEN 0 AND 3",
            name="ck_inscripciones_propietario_reenvios",
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name="fk_inscripciones_propietario_usuario_id_usuarios",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_inscripciones_propietario_correo",
        "inscripciones_propietario",
        ["correo"],
        unique=True,
    )
    op.create_index(
        "uq_inscripciones_propietario_token_hash",
        "inscripciones_propietario",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "uq_inscripciones_propietario_desafio_hash",
        "inscripciones_propietario",
        ["desafio_hash"],
        unique=True,
    )


def downgrade() -> None:
    """Removes only the Phase 2 tables and indexes."""

    op.drop_index(
        "uq_inscripciones_propietario_desafio_hash",
        table_name="inscripciones_propietario",
    )
    op.drop_index(
        "uq_inscripciones_propietario_token_hash",
        table_name="inscripciones_propietario",
    )
    op.drop_index(
        "uq_inscripciones_propietario_correo",
        table_name="inscripciones_propietario",
    )
    op.drop_table("inscripciones_propietario")
    op.drop_index("uq_cuentas_propietario_usuario_id", table_name="cuentas_propietario")
    op.drop_table("cuentas_propietario")

